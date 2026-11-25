"""终端输出。步骤行统一 ✓ / ✗ / · 前缀。"""

from __future__ import annotations


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def info(msg: str) -> None:
    print(f"  · {msg}")


def mask(secret: str) -> str:
    """前 4 后 4 打码；短于 8 位则整体隐藏。"""
    if not secret:
        return ""
    if len(secret) < 8:
        return "*" * len(secret)
    return f"{secret[:4]}****{secret[-4:]}"
