from bls.ui import mask


def test_mask_short_secret_is_fully_hidden():
    assert mask("abc") == "***"


def test_mask_long_secret_keeps_4_4():
    assert mask("abcdefghijklmnop") == "abcd****mnop"
