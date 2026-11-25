from bls import config

REAL_PATHS = config.Paths


def _paths(tmp_path):
    return REAL_PATHS(
        config_file=tmp_path / "c.toml",
        credentials_file=tmp_path / "cred.json",
        state_file=tmp_path / "s.json",
        qr_png=tmp_path / "q.png",
        obs_config_dir=tmp_path / "obs",
    )


def test_load_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "Paths", lambda: _paths(tmp_path))
    cfg = config.load()
    assert cfg.obs_port == 4455
    assert cfg.area_id == 0
    assert cfg.launch_obs is True
    assert cfg.obs_profile == ""


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "Paths", lambda: _paths(tmp_path))
    cfg = config.Config(area_id=27, obs_profile="livestream")
    config.save(cfg)
    loaded = config.load()
    assert loaded.area_id == 27
    assert loaded.obs_profile == "livestream"
