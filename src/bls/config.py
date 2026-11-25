"""配置与文件路径。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _config_root() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else _home() / ".config"
    return base / "bls"


def _cache_root() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else _home() / ".cache"
    return base / "bls"


def _qr_png_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "bls-qr.png"
    return _cache_root() / "bls-qr.png"


@dataclass
class Paths:
    config_file: Path = field(default_factory=lambda: _config_root() / "config.toml")
    credentials_file: Path = field(default_factory=lambda: _config_root() / "credentials.json")
    state_file: Path = field(default_factory=lambda: _config_root() / "live_state.json")
    qr_png: Path = field(default_factory=_qr_png_path)
    obs_config_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config")) / "obs-studio"
    )


@dataclass
class Config:
    obs_binary: str = "obs"
    obs_port: int = 4455
    obs_profile: str = ""
    obs_collection: str = ""
    area_id: int = 0
    launch_obs: bool = True


def load(paths: Paths | None = None) -> Config:
    paths = paths or Paths()
    path = paths.config_file
    cfg = Config()
    if not path.exists():
        return cfg
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    for key in ("obs_binary", "obs_port", "obs_profile", "obs_collection", "area_id", "launch_obs"):
        if key in raw:
            setattr(cfg, key, raw[key])
    return cfg


def save(cfg: Config, paths: Paths | None = None) -> None:
    paths = paths or Paths()
    path = paths.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'obs_binary = "{cfg.obs_binary}"',
        f"obs_port = {cfg.obs_port}",
        f'obs_profile = "{cfg.obs_profile}"',
        f'obs_collection = "{cfg.obs_collection}"',
        f"area_id = {cfg.area_id}",
        f"launch_obs = {'true' if cfg.launch_obs else 'false'}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
