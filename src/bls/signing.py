"""B 站 App 接口签名：参数排序 → urlencode → 拼 appsec → MD5。"""

from __future__ import annotations

import hashlib
import urllib.parse

# PC 直播姬 / PC 投稿工具的 appkey + appsec
LIVE_APPKEY = "aae92bc66f3edfab"
LIVE_APPSEC = "af125a0d5279fd576c1b4418a3e8276d"


def app_sign(params: dict[str, str], appkey: str, appsec: str) -> dict[str, str]:
    """返回带 appkey 与 sign 的新 dict，不修改入参。"""
    signed = dict(params)
    signed["appkey"] = appkey
    query = urllib.parse.urlencode(dict(sorted(signed.items())))
    signed["sign"] = hashlib.md5((query + appsec).encode()).hexdigest()
    return signed
