"""扫码登录与 cookie 持久化。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import qr
from .config import Paths
from .ui import info, ok

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

COOKIE_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5")

POLL_UNSCANNED = 86101
POLL_SCANNED = 86090
POLL_EXPIRED = 86038
POLL_OK = 0

QR_TIMEOUT = 180.0
POLL_INTERVAL = 1.5


class AuthTimeout(Exception):
    pass


class NotLoggedIn(Exception):
    pass


@dataclass(frozen=True)
class Credentials:
    sessdata: str
    bili_jct: str
    dede_user_id: str
    saved_at: float
    dede_user_id_ckmd5: str = ""


def parse_set_cookie(headers: list[str]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for header in headers:
        first = header.split(";", 1)[0]
        name, _, value = first.partition("=")
        name = name.strip()
        if name in COOKIE_KEYS and name not in cookies:
            cookies[name] = value.strip()
    return cookies


def cookie_header(creds: Credentials) -> str:
    return f"SESSDATA={creds.sessdata}; bili_jct={creds.bili_jct}; DedeUserID={creds.dede_user_id}"


def save(creds_file: Path, creds: Credentials) -> None:
    creds_file = Path(creds_file)
    creds_file.parent.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(json.dumps(asdict(creds)), encoding="utf-8")
    os.chmod(creds_file, 0o600)


def load(creds_file: Path) -> Credentials | None:
    creds_file = Path(creds_file)
    if not creds_file.exists():
        return None
    try:
        raw = json.loads(creds_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return Credentials(
            sessdata=raw["sessdata"],
            bili_jct=raw["bili_jct"],
            dede_user_id=raw["dede_user_id"],
            saved_at=float(raw["saved_at"]),
            dede_user_id_ckmd5=raw.get("dede_user_id_ckmd5", ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _set_cookie_headers(resp) -> list[str]:
    raw = resp.headers.get("Set-Cookie") or []
    return [raw] if isinstance(raw, str) else list(raw)


def poll_once(session, qrcode_key: str) -> tuple[int, dict[str, str]]:
    resp = session.get(QR_POLL_URL, params={"qrcode_key": qrcode_key}, timeout=15)
    header_cookies = parse_set_cookie(_set_cookie_headers(resp))
    payload = resp.json()
    data = payload.get("data") or {}
    code = data.get("code")
    if code is None:
        code = payload.get("code", -1)
    return int(code), header_cookies


def _nav_logged_in(session, creds: Credentials) -> bool:
    resp = session.get(
        NAV_URL,
        headers={"Cookie": cookie_header(creds), "User-Agent": UA},
        timeout=15,
    )
    payload = resp.json()
    return int(payload.get("code", -1)) == 0 and bool((payload.get("data") or {}).get("isLogin"))


def _generate(session) -> tuple[str, str]:
    resp = session.get(QR_GENERATE_URL, headers={"User-Agent": UA}, timeout=15)
    payload = resp.json()
    data = payload.get("data") or {}
    url = data.get("url") or ""
    key = data.get("qrcode_key") or ""
    if not url or not key:
        raise AuthTimeout("申请二维码失败")
    return url, key


def _scan(session, paths: Paths) -> Credentials:
    url, key = _generate(session)
    print()
    print(qr.render_terminal(url))
    print()
    png = qr.write_png(url, paths.qr_png)
    info(f"扫码登录：用 B 站 App 扫描上方二维码")
    info(f"扫不出来就打这个文件：{png}")

    deadline = time.monotonic() + QR_TIMEOUT
    regenerated = False
    while time.monotonic() < deadline:
        code, cookies = poll_once(session, key)
        if code == POLL_OK:
            if cookies.get("SESSDATA") and cookies.get("bili_jct"):
                return Credentials(
                    sessdata=cookies["SESSDATA"],
                    bili_jct=cookies["bili_jct"],
                    dede_user_id=cookies.get("DedeUserID", ""),
                    saved_at=time.time(),
                    dede_user_id_ckmd5=cookies.get("DedeUserID__ckMd5", ""),
                )
            # 登录成功但 header 里没拿到完整 cookie，退回会话 cookie jar
            jar = getattr(session, "cookies", None)
            if jar is not None and jar.get("SESSDATA") and jar.get("bili_jct"):
                return Credentials(
                    sessdata=jar.get("SESSDATA"),
                    bili_jct=jar.get("bili_jct"),
                    dede_user_id=jar.get("DedeUserID", ""),
                    saved_at=time.time(),
                )
            raise NotLoggedIn("登录成功但未取到 cookie")
        if code == POLL_EXPIRED:
            if regenerated:
                raise AuthTimeout("二维码已失效，请重新运行")
            regenerated = True
            info("二维码已失效，重新申请")
            url, key = _generate(session)
            print(qr.render_terminal(url))
            png = qr.write_png(url, paths.qr_png)
            info(f"新的二维码：{png}")
            continue
        time.sleep(POLL_INTERVAL)
    raise AuthTimeout("扫码超时")


def ensure_login(session, paths: Paths, *, interactive: bool) -> Credentials:
    creds = load(paths.credentials_file)
    if creds is not None:
        if _nav_logged_in(session, creds):
            return creds
        info("登录已失效")
        if not interactive:
            raise NotLoggedIn("登录已失效，请运行 bls login")
    elif not interactive:
        raise NotLoggedIn("尚未登录，请运行 bls login")

    creds = _scan(session, paths)
    save(paths.credentials_file, creds)
    ok(f"登录成功（UID {creds.dede_user_id}）")
    return creds
