from argparse import Namespace
from pathlib import Path

import pytest

from bls import __main__ as cli
from bls import auth, bilibili, obs


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """把所有外部依赖换掉，只测编排逻辑。"""
    paths = auth.Paths(
        config_file=tmp_path / "config.toml",
        credentials_file=tmp_path / "cred.json",
        state_file=tmp_path / "live_state.json",
        qr_png=tmp_path / "q.png",
        obs_config_dir=tmp_path / "obs",
    )
    monkeypatch.setattr(cli, "Paths", lambda: paths)
    monkeypatch.setattr(cli, "load_config", lambda p=None: cli.Config(area_id=27))
    monkeypatch.setattr(cli, "make_session", lambda: object())
    monkeypatch.setattr(
        cli,
        "ensure_login",
        lambda session, paths, interactive: auth.Credentials(
            sessdata="S", bili_jct="J", dede_user_id="42", saved_at=0.0
        ),
    )
    monkeypatch.setattr(cli, "user_uid", lambda session, creds: 42)
    monkeypatch.setattr(cli, "room_id_of", lambda session, creds, uid: 1024)
    monkeypatch.setattr(cli, "area_list", lambda session: [(2, "网游", [(27, "虚拟主播")])])
    monkeypatch.setattr(
        cli,
        "load_creds",
        lambda p: auth.Credentials(sessdata="S", bili_jct="J", dede_user_id="42", saved_at=0.0),
    )
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 0)
    return paths


def _stream():
    return bilibili.StreamInfo(addr="rtmp://a/", code="?k=1", room_id=1024, live_key="lk")


def test_go_stops_after_start_live_failure(fake_env, monkeypatch, capsys):
    def boom(*a, **kw):
        raise bilibili.BiliError(60024, "目标分区需要人脸认证")

    monkeypatch.setattr(cli, "start_live", boom)
    called = []
    monkeypatch.setattr(cli, "ensure_running", lambda *a, **kw: called.append(1))

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "人脸" in out
    assert called == []


def test_go_reminds_bili_only_when_obs_launch_fails(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 0)
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: _stream())
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr(cli, "save_state", lambda *a, **kw: None)

    def boom(*a, **kw):
        raise obs.ObsError(0, "OBS 启动后 websocket 端口仍未监听")

    monkeypatch.setattr(cli, "ensure_running", boom)

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "bls stop --bili-only" in out


def test_go_reuses_state_when_bili_already_live(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 1)
    monkeypatch.setattr(
        cli,
        "load_state",
        lambda path: {"addr": "rtmp://old/", "code": "?k=old", "room_id": 1024, "live_key": "x"},
    )
    started = []
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: started.append(1))

    seen = {}

    class _Client:
        def close(self):
            pass

    def fake_ensure(*a, **kw):
        return _Client()

    def fake_sync(client, addr, code):
        seen["addr"] = addr
        seen["code"] = code
        return "unchanged"

    monkeypatch.setattr(cli, "ensure_running", fake_ensure)
    monkeypatch.setattr(cli, "sync_stream", fake_sync)
    monkeypatch.setattr(cli, "wait_streaming", lambda client, timeout=20.0: True)

    rc = cli.main(["go"])
    assert rc == 0
    assert started == []
    assert seen == {"addr": "rtmp://old/", "code": "?k=old"}


def test_go_warns_when_live_without_state(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 1)
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("不应提问")))
    started = []
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: started.append(1))

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "已开播" in out
    assert started == []


def test_go_reports_failure_when_bytes_stall(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 0)
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: _stream())
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr(cli, "save_state", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "ensure_running", lambda *a, **kw: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(cli, "sync_stream", lambda *a, **kw: "started")
    monkeypatch.setattr(cli, "wait_streaming", lambda client, timeout=20.0: False)
    stopped = []
    monkeypatch.setattr(cli, "stop_live", lambda *a, **kw: stopped.append(1))

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "没有发出去" in out
    assert stopped == []


def test_stop_calls_obs_and_bili(fake_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "room_live_status", lambda session, room_id: 1)
    monkeypatch.setattr(cli, "load_state", lambda path: {"room_id": 1024, "addr": "a", "code": "c"})
    monkeypatch.setattr(cli, "ensure_running", lambda *a, **kw: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(cli, "stop_stream", lambda client: calls.append("obs"))
    monkeypatch.setattr(cli, "stop_live", lambda *a, **kw: calls.append("bili"))
    monkeypatch.setattr(cli, "clear_state", lambda path: calls.append("state"))

    rc = cli.main(["stop"])
    assert rc == 0
    assert calls == ["obs", "bili", "state"]


def test_stop_bili_only_skips_obs(fake_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "load_state", lambda path: {"room_id": 1024, "addr": "a", "code": "c"})
    monkeypatch.setattr(cli, "ensure_running", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不应连 OBS")))
    monkeypatch.setattr(cli, "stop_live", lambda *a, **kw: calls.append("bili"))
    monkeypatch.setattr(cli, "clear_state", lambda path: calls.append("state"))

    rc = cli.main(["stop", "--bili-only"])
    assert rc == 0
    assert calls == ["bili", "state"]


def test_dry_run_does_not_start_live(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("dry-run 不应开播")))
    rc = cli.main(["go", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "27" in out


def test_go_persists_area_when_given(fake_env, monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(cli, "save_config", lambda cfg, paths=None: saved.update(area=cfg.area_id))
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr(cli, "start_live", lambda *a, **kw: (_ for _ in ()).throw(
        bilibili.BiliError(60024, "目标分区需要人脸认证")))
    cli.main(["go", "--area", "88"])
    assert saved == {"area": 88}


def test_make_session_sends_browser_ua():
    session = cli.make_session()
    assert session.headers["User-Agent"] == auth.UA
    assert session.headers["Referer"] == "https://www.bilibili.com/"


def _write_ws_config(paths, enabled: bool, password: str = "") -> None:
    ws_dir = paths.obs_config_dir / "plugin_config" / "obs-websocket"
    ws_dir.mkdir(parents=True)
    (ws_dir / "config.json").write_text(
        f'{{"server_enabled": {"true" if enabled else "false"}, "server_password": "{password}"}}',
        encoding="utf-8",
    )


def _write_obs_profile(paths) -> None:
    profiles = paths.obs_config_dir / "basic" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "Untitled").mkdir()


def test_doctor_reports_ready_env(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "shutil_which", lambda binary: "/usr/bin/obs")
    _write_obs_profile(fake_env)
    _write_ws_config(fake_env, enabled=True, password="pw")

    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "obs-websocket 已启用" in out


def test_doctor_flags_disabled_websocket(fake_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "shutil_which", lambda binary: "/usr/bin/obs")
    _write_obs_profile(fake_env)
    _write_ws_config(fake_env, enabled=False)

    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "obs-websocket 未启用" in out


def test_go_retries_and_starts_obs_after_face_auth(fake_env, monkeypatch, capsys):
    attempts = []

    def start(*a, **kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise bilibili.BiliError(
                60043, "本次开播需要人脸认证", data={"qr": "https://example.com/auth"}
            )
        return _stream()

    monkeypatch.setattr(cli, "start_live", start)
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr(cli, "save_state", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli, "ensure_running", lambda *a, **kw: type("C", (), {"close": lambda self: None})()
    )
    monkeypatch.setattr(cli, "sync_stream", lambda *a, **kw: "started")
    monkeypatch.setattr(cli, "wait_streaming", lambda client, timeout=20.0: True)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(attempts) == 2
    assert "https://example.com/auth" in out


def test_go_gives_up_when_user_quits_face_auth(fake_env, monkeypatch, capsys):
    def start(*a, **kw):
        raise bilibili.BiliError(60024, "目标分区需要人脸认证", data={"qr": ""})

    monkeypatch.setattr(cli, "start_live", start)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "q")

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "未启动 OBS" in out


def test_go_shows_face_auth_middle_page_for_60043_without_qr(fake_env, monkeypatch, capsys):
    attempts = []

    def start(*a, **kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise bilibili.BiliError(
                60043, "本次开播需要身份验证", data={"qr": "", "need_face_auth": False}
            )
        return _stream()

    monkeypatch.setattr(cli, "start_live", start)
    monkeypatch.setattr(cli, "load_state", lambda path: None)
    monkeypatch.setattr(cli, "save_state", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli, "ensure_running", lambda *a, **kw: type("C", (), {"close": lambda self: None})()
    )
    monkeypatch.setattr(cli, "sync_stream", lambda *a, **kw: "started")
    monkeypatch.setattr(cli, "wait_streaming", lambda client, timeout=20.0: True)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")

    rc = cli.main(["go"])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(attempts) == 2
    assert "face-auth-middle.html" in out
    assert "mid=42" in out
