import json
import pathlib

import pytest

from bls import auth, bilibili

FIX = pathlib.Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def creds():
    return auth.Credentials(sessdata="S", bili_jct="J", dede_user_id="42", saved_at=0.0)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    """按 URL 片段返回预设响应，并记录所有调用顺序与参数。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _pick(self, url):
        for fragment, payload in self.routes.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected url: {url}")

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params or {}))
        return FakeResponse(self._pick(url))

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, dict(data or {})))
        return FakeResponse(self._pick(url))


def default_routes(**overrides):
    routes = {
        "/x/report/click/now": {"code": 0, "data": {"now": 1752971145}},
        "liveVersionInfo": fixture("live_version.json"),
        "Room/startLive": fixture("start_live_ok.json"),
        "Room/stopLive": {"code": 0, "data": {"change": 1, "status": "PREPARING"}},
    }
    routes.update(overrides)
    return routes


def test_start_live_parses_stream_info():
    session = FakeSession(default_routes())
    info = bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert info.addr.startswith("rtmp://")
    assert info.room_id == 1024
    assert info.code == "REDACTED_CODE"
    assert info.live_key == "REDACTED_LIVE_KEY"


def test_start_live_raises_with_hint_on_60024():
    session = FakeSession(default_routes(**{"Room/startLive": fixture("start_live_60024.json")}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert exc.value.code == 60024
    assert "人脸" in exc.value.hint


def test_start_live_raises_with_hint_on_60037():
    session = FakeSession(default_routes(**{"Room/startLive": fixture("start_live_60037.json")}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert exc.value.code == 60037
    assert "直播姬" in exc.value.hint


def test_start_live_raises_with_hint_on_60043():
    session = FakeSession(default_routes(**{"Room/startLive": fixture("start_live_60043.json")}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert exc.value.code == 60043
    assert "App" in exc.value.hint


def test_start_live_sends_required_params():
    session = FakeSession(default_routes())
    bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    post = [c for c in session.calls if c[0] == "POST" and "startLive" in c[1]][0]
    body = post[2]
    assert body["csrf"] == "J"
    assert body["csrf_token"] == "J"
    assert body["platform"] == "pc_link"
    assert body["area_v2"] == 27
    assert body["room_id"] == 1024
    assert body["version"] == "8.14.0.11278"
    assert body["build"] == 11278
    assert body["ts"] == 1752971145
    assert "sign" in body
    assert "appkey" in body


def test_start_live_requests_timestamp_before_version():
    session = FakeSession(default_routes())
    bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    urls = [c[1] for c in session.calls]
    assert urls.index(next(u for u in urls if "click/now" in u)) < urls.index(
        next(u for u in urls if "liveVersionInfo" in u)
    )
    assert urls.index(next(u for u in urls if "liveVersionInfo" in u)) < urls.index(
        next(u for u in urls if "startLive" in u)
    )


def test_stop_live_returns_none_on_success():
    session = FakeSession(default_routes())
    assert bilibili.stop_live(session, creds(), room_id=1024) is None
    post = [c for c in session.calls if c[0] == "POST"][0]
    assert post[2]["csrf"] == "J"
    assert post[2]["platform"] == "pc_link"


def test_stop_live_raises_on_error():
    session = FakeSession(default_routes(**{"Room/stopLive": fixture("not_logged_in.json")}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.stop_live(session, creds(), room_id=1024)
    assert exc.value.code == -101


def test_hint_for_unknown_code_is_generic():
    assert "未知" in bilibili.hint_for_code(99999)


def test_room_live_status_reads_live_status():
    session = FakeSession({"Room/get_info": fixture("room_info.json")})
    assert bilibili.room_live_status(session, 1) in (0, 1, 2)


def test_area_list_parses_parent_and_children():
    session = FakeSession({"Area/getList": fixture("area_list.json")})
    areas = bilibili.area_list(session)
    parent_id, parent_name, children = areas[0]
    assert isinstance(parent_id, int)
    assert parent_name
    child_id, child_name = children[0]
    assert isinstance(child_id, int)
    assert child_name


def test_room_id_of_uses_master_info():
    session = FakeSession({"Master/info": fixture("master_info.json")})
    assert isinstance(bilibili.room_id_of(session, creds(), 2), int)


def test_room_id_of_falls_back_to_room_info_when_short_id_missing():
    master = {"code": 0, "data": {"room_id": 0, "info": {"uid": 7}}}
    room = {"code": 0, "data": {"room_id": 7000, "short_id": 0}}
    session = FakeSession({"Master/info": master, "Room/get_info": room})
    assert bilibili.room_id_of(session, creds(), 7) == 7000


def test_face_auth_error_carries_payload():
    session = FakeSession(default_routes(**{"Room/startLive": fixture("start_live_60024.json")}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert exc.value.data["need_face_auth"] is True
    assert exc.value.face_auth_qr == ""


def test_face_auth_error_exposes_qr_when_bilibili_returns_one():
    payload = {"code": 60043, "message": "需要人脸", "data": {"qr": "https://example.com/auth"}}
    session = FakeSession(default_routes(**{"Room/startLive": payload}))
    with pytest.raises(bilibili.BiliError) as exc:
        bilibili.start_live(session, creds(), room_id=1024, area_id=27)
    assert exc.value.face_auth_qr == "https://example.com/auth"


def test_face_auth_url_points_at_official_middle_page():
    url = bilibili.face_auth_url("455033300")
    assert url.startswith("https://www.bilibili.com/blackboard/live/face-auth-middle.html")
    assert "mid=455033300" in url
