from bls import qr


def test_terminal_render_is_rectangular_blocks():
    out = qr.render_terminal("https://example.com/x")
    lines = out.splitlines()
    assert len(lines) > 5
    assert len({len(line) for line in lines}) == 1
    assert set(out) <= set(" ▀▄█\n")


def test_terminal_render_has_quiet_zone():
    out = qr.render_terminal("https://example.com/x")
    lines = out.splitlines()
    assert lines[0].strip() == ""
    assert lines[-1].strip() == ""


def test_write_png_creates_file(tmp_path):
    p = qr.write_png("https://example.com/x", tmp_path / "q.png")
    assert p.exists()
    assert p.stat().st_size > 500
