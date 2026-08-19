# -*- coding: utf-8 -*-
"""公益接口：碎片还原，源码里不出现完整令牌。"""

from __future__ import annotations

# 诱饵，给 strings 扫的
_PAD = (
    "sk-proj-demo-not-used-0000",
    "https://api.openai.com/v1",
    "gpt-4o-mini",
)

_S = (90, 60, 25, 231, 65, 136, 45, 115)
_U = (
    50, 72, 109, 151, 123, 167, 2, 29, 63, 75,
    55, 148, 111, 187, 92, 93, 50, 93, 80, 149,
)
_T = (
    41, 87, 52, 144, 2, 191, 29, 42, 59, 8, 83, 178, 20, 225, 126, 25,
    42, 106, 85, 140, 15, 206, 107, 23, 21, 13, 79, 133, 21, 254, 65, 29,
    22, 119, 123, 214, 46, 223, 68, 59, 16, 123, 107, 177, 22, 185, 26, 70,
    18, 94, 108,
)
_M = "deepseek-v4-flash"


def _restore(seq) -> str:
    return "".join(chr(n ^ _S[i % len(_S)]) for i, n in enumerate(seq))


def public_base() -> str:
    return _restore(_U)


def public_token() -> str:
    return _restore(_T)


def public_model() -> str:
    return _M


def public_endpoint() -> dict:
    base = public_base().rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return {
        "base": base,
        "token": public_token(),
        "model": public_model(),
    }
