"""OBS 进程管理与 obs-websocket 5 客户端。"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import websocket

WS_TIMEOUT = 5.0
BOOT_TIMEOUT = 30.0


class ObsError(Exception):
    def __init__(self, code: int, comment: str):
        self.code = code
        self.comment = comment
        super().__init__(f"[{code}] {comment}")


def auth_string(password: str, salt: str, challenge: str) -> str:
    """obs-websocket 5 的 Identify 鉴权串。"""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_ws_password(obs_config_dir: Path) -> tuple[bool, str]:
    cfg = Path(obs_config_dir) / "plugin_config" / "obs-websocket" / "config.json"
    if not cfg.exists():
        return False, ""
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ""
    return bool(raw.get("server_enabled", False)), str(raw.get("server_password") or "")


class ObsClient:
    def __init__(self, ws: Any, port: int):
        self.ws = ws
        self.port = port
        self._closed = False

    def call(self, request_type: str, data: dict | None = None) -> dict:
        request_id = str(uuid.uuid4())
        self.ws.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "requestType": request_type,
                        "requestId": request_id,
                        "requestData": data or {},
                    },
                }
            )
        )
        deadline = time.monotonic() + WS_TIMEOUT
        while time.monotonic() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                break
            if message.get("op") != 7:
                continue
            if message.get("d", {}).get("requestId") != request_id:
                continue
            status = message["d"].get("requestStatus") or {}
            if not status.get("result", False):
                raise ObsError(int(status.get("code", 0)), str(status.get("comment", "")))
            return message["d"].get("responseData") or {}
        raise ObsError(0, f"{request_type} 超时")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.ws.close()


def connect(port: int, password: str = "", host: str = "127.0.0.1") -> ObsClient:
    ws = websocket.create_connection(f"ws://{host}:{port}", timeout=WS_TIMEOUT)
    ws.settimeout(WS_TIMEOUT)
    hello = json.loads(ws.recv())
    if hello.get("op") != 0:
        ws.close()
        raise ObsError(0, "不是 obs-websocket 的 Hello 消息")
    identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
    auth = hello.get("d", {}).get("authentication")
    if auth:
        identify["authentication"] = auth_string(
            password, str(auth.get("salt", "")), str(auth.get("challenge", ""))
        )
    ws.send(json.dumps({"op": 1, "d": identify}))
    identified = json.loads(ws.recv())
    if identified.get("op") != 2:
        ws.close()
        raise ObsError(0, "OBS 鉴权失败，请检查 websocket 密码")
    return ObsClient(ws, port)


def launch(binary: str, profile: str = "", collection: str = "") -> None:
    args = [binary, "--minimize-to-tray"]
    if profile:
        args += ["--profile", profile]
    if collection:
        args += ["--collection", collection]
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_running(cfg, obs_config_dir: Path, *, launch_obs: bool = True) -> ObsClient:
    """确保 OBS websocket 可用并返回已鉴权的 client。"""
    if not port_open(cfg.obs_port):
        if not launch_obs:
            raise ObsError(0, "OBS 未运行，且配置为不自动启动")
        launch(cfg.obs_binary, cfg.obs_profile, cfg.obs_collection)
        deadline = time.monotonic() + BOOT_TIMEOUT
        while time.monotonic() < deadline and not port_open(cfg.obs_port):
            time.sleep(0.5)
        if not port_open(cfg.obs_port):
            raise ObsError(0, "OBS 启动后 websocket 端口仍未监听")
    enabled, password = read_ws_password(obs_config_dir)
    if not enabled and password:
        raise ObsError(0, "obs-websocket 未启用：工具 → WebSocket 服务器设置")
    return connect(cfg.obs_port, password)


def sync_stream(client, addr: str, code: str) -> Literal["unchanged", "restarted", "started"]:
    status = client.call("GetStreamStatus")
    result: Literal["unchanged", "restarted", "started"]
    if status.get("outputActive"):
        current = client.call("GetStreamServiceSettings")
        settings = current.get("streamServiceSettings") or {}
        if settings.get("server") == addr and settings.get("key") == code:
            return "unchanged"
        client.call("StopStream")
        result = "restarted"
    else:
        result = "started"
    client.call(
        "SetStreamServiceSettings",
        {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {"server": addr, "key": code},
        },
    )
    client.call("StartStream")
    return result


def wait_streaming(client, timeout: float = 20.0, start_grace: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    started_at = time.monotonic()
    previous = -1
    growths = 0
    while time.monotonic() < deadline:
        status = client.call("GetStreamStatus")
        current = int(status.get("outputBytes") or 0)
        if current > previous and current > 0:
            growths += 1
            if growths >= 2:
                return True
        else:
            growths = 0
        if not status.get("outputActive", True) and time.monotonic() - started_at > start_grace:
            return False
        previous = current
        time.sleep(0.5)
    return False


def stop_stream(client) -> bool:
    status = client.call("GetStreamStatus")
    if status.get("outputActive"):
        client.call("StopStream")
        return True
    return False
