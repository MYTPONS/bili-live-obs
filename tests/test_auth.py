import pytest

from bls import auth


def _resp(payload, set_cookies=()):
    class _R:
        def __init__(self):
            self.headers = {"Set-Cookie": list(set_cookies)} if set_cookies else {}
            self._payload = payload

        def json(self):
            return self._payload

    return _R()


class _Session:
    def __init__(self, payload, set_cookies=()):
        self._payload = payload
        self._set_cookies = set_cookies

    def get(self, url, params=None, timeout=None, headers=None):
        return _resp(self._payload, self._set_cookies)


def test_parse_set_cookie_extracts_four_fields():
    headers = [
        "SESSDATA=abc%2C123; Path=/; Domain=bilibili.com; Expires=Sun, 01 Jan 2027 00:00:00 GMT; HttpOnly; Secure",
        "bili_jct=deadbeef; Path=/; Domain=bilibili.com",
        "DedeUserID=42; Path=/; Domain=bilibili.com",
        "DedeUserID__ckMd5=zzz; Path=/; Domain=bilibili.com",
        "sid=other; Path=/",
    ]
    cookies = auth.parse_set_cookie(headers)
    assert cookies["SESSDATA"] == "abc%2C123"
    assert cookies["bili_jct"] == "deadbeef"
    assert cookies["DedeUserID"] == "42"
    assert "sid" not in cookies


def test_cookie_header_shape():
    creds = auth.Credentials(sessdata="s", bili_jct="j", dede_user_id="42", saved_at=0.0)
    assert auth.cookie_header(creds) == "SESSDATA=s; bili_jct=j; DedeUserID=42"


def test_save_sets_0600(tmp_path):
    p = tmp_path / "cred.json"
    auth.save(p, auth.Credentials(sessdata="s", bili_jct="j", dede_user_id="1", saved_at=0.0))
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_load_roundtrip(tmp_path):
    p = tmp_path / "cred.json"
    creds = auth.Credentials(sessdata="s", bili_jct="j", dede_user_id="1", saved_at=1.5)
    auth.save(p, creds)
    assert auth.load(p) == creds


def test_load_missing_returns_none(tmp_path):
    assert auth.load(tmp_path / "nope.json") is None


def test_poll_expired_returns_86038():
    session = _Session({"code": 0, "data": {"code": 86038, "message": "二维码已失效"}})
    code, cookies = auth.poll_once(session, "key")
    assert code == 86038
    assert cookies == {}


def test_poll_success_returns_cookies():
    session = _Session(
        {"code": 0, "data": {"code": 0, "message": ""}},
        set_cookies=[
            "SESSDATA=abc; Path=/; Domain=bilibili.com",
            "bili_jct=deadbeef; Path=/; Domain=bilibili.com",
            "DedeUserID=42; Path=/; Domain=bilibili.com",
        ],
    )
    code, cookies = auth.poll_once(session, "key")
    assert code == 0
    assert cookies["SESSDATA"] == "abc"
    assert cookies["DedeUserID"] == "42"


def test_ensure_login_non_interactive_without_creds_raises(tmp_path):
    paths = auth.Paths(
        config_file=tmp_path / "c.toml",
        credentials_file=tmp_path / "cred.json",
        state_file=tmp_path / "s.json",
        qr_png=tmp_path / "q.png",
        obs_config_dir=tmp_path / "obs",
    )
    with pytest.raises(auth.NotLoggedIn):
        auth.ensure_login(_Session({}), paths, interactive=False)
