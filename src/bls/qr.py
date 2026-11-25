"""二维码渲染：终端半块字符 + PNG 兜底。"""

from __future__ import annotations

from pathlib import Path

import qrcode


def _matrix(url: str) -> list[list[bool]]:
    code = qrcode.QRCode(border=2, box_size=1)
    code.add_data(url)
    code.make(fit=True)
    return code.get_matrix()


def render_terminal(url: str) -> str:
    """把二维码渲染成半块字符，每两个竖直模块合成一行。"""
    matrix = _matrix(url)
    lines: list[str] = []
    for y in range(0, len(matrix), 2):
        top = matrix[y]
        bottom = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(top)
        chars = []
        for upper, lower in zip(top, bottom):
            if upper and lower:
                chars.append("█")
            elif upper:
                chars.append("▀")
            elif lower:
                chars.append("▄")
            else:
                chars.append(" ")
        lines.append("".join(chars).rstrip())
    # 行宽必须一致才好看；用完整宽度重排一次
    width = max(len(line) for line in lines)
    return "\n".join(line.ljust(width) for line in lines)


def write_png(url: str, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = qrcode.make(url)
    img.save(path)
    return path
