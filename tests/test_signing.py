from bls.signing import app_sign


def test_app_sign_matches_known_vector():
    signed = app_sign(
        {"system_version": "2", "ts": "1752971145"},
        "aae92bc66f3edfab",
        "af125a0d5279fd576c1b4418a3e8276d",
    )
    assert signed["sign"] == "49d289e3ad34c509cc66fbee1c0affec"
    assert signed["appkey"] == "aae92bc66f3edfab"


def test_app_sign_does_not_mutate_input():
    src = {"ts": "1"}
    app_sign(src, "k", "s")
    assert src == {"ts": "1"}
