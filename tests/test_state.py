from bls import state


def test_state_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    state.save(p, addr="rtmp://a/", code="?k=1", room_id=1024, live_key="abc")
    s = state.load(p)
    assert s["room_id"] == 1024
    assert s["code"] == "?k=1"
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_state_clear_removes_file(tmp_path):
    p = tmp_path / "s.json"
    state.save(p, addr="a", code="c", room_id=1, live_key="k")
    state.clear(p)
    assert not p.exists()


def test_state_clear_missing_is_noop(tmp_path):
    state.clear(tmp_path / "nope.json")


def test_state_load_missing_returns_none(tmp_path):
    assert state.load(tmp_path / "nope.json") is None
