"""B 站直播相关接口。所有非公开接口集中在这个文件里。"""

from __future__ import annotations

from dataclasses import dataclass

from .auth import UA, Credentials, cookie_header
from .signing import LIVE_APPKEY, LIVE_APPSEC, app_sign

LIVE_HOST = "https://api.live.bilibili.com"
MAIN_HOST = "https://api.bilibili.com"

CLICK_NOW_URL = f"{MAIN_HOST}/x/report/click/now"
NAV_URL = f"{MAIN_HOST}/x/web-interface/nav"
LIVE_VERSION_URL = f"{LIVE_HOST}/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion"
START_LIVE_URL = f"{LIVE_HOST}/room/v1/Room/startLive"
STOP_LIVE_URL = f"{LIVE_HOST}/room/v1/Room/stopLive"
ROOM_INFO_URL = f"{LIVE_HOST}/room/v1/Room/get_info"
AREA_LIST_URL = f"{LIVE_HOST}/room/v1/Area/getList"
MASTER_INFO_URL = f"{LIVE_HOST}/live_user/v1/Master/info"

PLATFORM = "pc_link"

_HINTS = {
    -101: "登录已失效，请运行 bls login",
    1: "请求失败，请稍后重试",
    65530: "登录凭证错误，请重新运行 bls login",
    60009: "分区不存在，请换一个分区",
    60013: "所在地区受实名认证限制，无法开播",
    60024: "目标分区需要人脸认证，请在 B 站 App 完成一次认证后重试；也可换一个分区",
    60034: "系统维护中，仅支持直播姬开播",
    60037: "web 在线开播已下线，只能通过直播姬开播",
    60043: "本次开播需要人脸认证：在 B 站 App 里点开播，按提示完成人脸认证后重试",
}

FACE_AUTH_CODES = frozenset({60024, 60043})

FACE_AUTH_MIDDLE_URL = (
    "https://www.bilibili.com/blackboard/live/face-auth-middle.html?source_event=400&mid={uid}"
)


def face_auth_url(uid: str) -> str:
    """60043 不返回链接，用 B 站官方人脸认证中间页拼一个。"""
    return FACE_AUTH_MIDDLE_URL.format(uid=uid)


class BiliError(Exception):
    def __init__(self, code: int, message: str, hint: str = "", data: dict | None = None):
        self.code = code
        self.message = message
        self.hint = hint or hint_for_code(code)
        self.data: dict = data or {}
        super().__init__(f"[{code}] {message}")

    @property
    def face_auth_qr(self) -> str:
        """B 站要求人脸认证时可能下发的认证链接，没有就是空串。"""
        if self.code not in FACE_AUTH_CODES:
            return ""
        return str(self.data.get("qr") or "")


@dataclass(frozen=True)
class StreamInfo:
    addr: str
    code: str
    room_id: int
    live_key: str


def hint_for_code(code: int) -> str:
    return _HINTS.get(code) or f"未知错误（code {code}），可运行 bls doctor 排查"


def _check(payload: dict) -> dict:
    code = int(payload.get("code", -1))
    if code != 0:
        message = payload.get("message") or payload.get("msg") or ""
        data = payload.get("data")
        raise BiliError(code, str(message), data=data if isinstance(data, dict) else None)
    return payload


def _request(session, method: str, url: str, *, creds: Credentials | None = None, **kwargs) -> dict:
    headers = {"User-Agent": UA, **kwargs.pop("headers", {})}
    if creds is not None:
        headers["Cookie"] = cookie_header(creds)
    if method == "GET":
        resp = session.get(url, headers=headers, timeout=15, **kwargs)
    else:
        resp = session.post(url, headers=headers, timeout=15, **kwargs)
    return _check(resp.json())


def user_uid(session, creds: Credentials) -> int:
    payload = _request(session, "GET", NAV_URL, creds=creds)
    data = payload.get("data") or {}
    if not data.get("isLogin"):
        raise BiliError(-101, "账号未登录")
    return int(data.get("mid", 0))


def room_id_of(session, creds: Credentials, uid: int) -> int:
    payload = _request(session, "GET", MASTER_INFO_URL, params={"uid": uid})
    data = payload.get("data") or {}
    room_id = int(data.get("room_id") or 0)
    if room_id:
        return room_id
    candidate = int((data.get("info") or {}).get("uid") or uid)
    info = _request(session, "GET", ROOM_INFO_URL, params={"room_id": candidate})
    return int((info.get("data") or {}).get("room_id") or 0)


def area_list(session) -> list[tuple[int, str, list[tuple[int, str]]]]:
    payload = _request(session, "GET", AREA_LIST_URL)
    result = []
    for parent in payload.get("data") or []:
        children = [
            (int(child["id"]), str(child["name"])) for child in (parent.get("list") or [])
        ]
        result.append((int(parent["id"]), str(parent["name"]), children))
    return result


def room_live_status(session, room_id: int) -> int:
    payload = _request(session, "GET", ROOM_INFO_URL, params={"room_id": room_id})
    return int((payload.get("data") or {}).get("live_status", 0))


def _now_ts(session) -> int:
    payload = _request(session, "GET", CLICK_NOW_URL)
    return int((payload.get("data") or {}).get("now", 0))


def _live_version(session, ts: int) -> tuple[str, int]:
    params = app_sign({"system_version": "2", "ts": str(ts)}, LIVE_APPKEY, LIVE_APPSEC)
    payload = _request(session, "GET", LIVE_VERSION_URL, params=params)
    data = payload.get("data") or {}
    return str(data.get("curr_version") or ""), int(data.get("build") or 0)


def start_live(session, creds: Credentials, room_id: int, area_id: int) -> StreamInfo:
    ts = _now_ts(session)
    version, build = _live_version(session, ts)
    body = {
        "room_id": room_id,
        "platform": PLATFORM,
        "area_v2": area_id,
        "backup_stream": 0,
        "csrf": creds.bili_jct,
        "csrf_token": creds.bili_jct,
        "version": version,
        "build": build,
        "ts": ts,
    }
    # 签名按字符串计算；requests 对表单的编码与 str() 一致，所以可以直接发原值
    signed = app_sign({k: str(v) for k, v in body.items()}, LIVE_APPKEY, LIVE_APPSEC)
    body["appkey"] = signed["appkey"]
    body["sign"] = signed["sign"]
    payload = _request(session, "POST", START_LIVE_URL, creds=creds, data=body)
    data = payload.get("data") or {}
    rtmp = data.get("rtmp") or {}
    addr = rtmp.get("addr") or ""
    code = rtmp.get("code") or ""
    if not addr or not code:
        raise BiliError(-1, "开播响应里没有推流地址")
    return StreamInfo(
        addr=str(addr),
        code=str(code),
        room_id=room_id,
        live_key=str(data.get("live_key") or ""),
    )


def stop_live(session, creds: Credentials, room_id: int) -> None:
    body = {
        "room_id": str(room_id),
        "platform": PLATFORM,
        "csrf": creds.bili_jct,
        "csrf_token": creds.bili_jct,
    }
    _request(session, "POST", STOP_LIVE_URL, creds=creds, data=body)
