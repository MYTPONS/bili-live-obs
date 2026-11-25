"""本次开播的推流码状态，停播后删除。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def save(path: Path, *, addr: str, code: str, room_id: int, live_key: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "addr": addr,
        "code": code,
        "room_id": room_id,
        "live_key": live_key,
        "saved_at": time.time(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def load(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not raw.get("addr") or not raw.get("code"):
        return None
    return raw


def clear(path: Path) -> None:
    path = Path(path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
