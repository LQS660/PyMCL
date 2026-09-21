# -*- coding: utf-8 -*-
"""公益接口占位（批次 4.1）。

历史版本把共享上游令牌 XOR 混淆内置进客户端——混淆不是加密，strings 扫描
照样能还原出可用令牌随包分发。改造后：分发包内不再含任何可用上游令牌，
``public_token()`` 返回不可用占位；未配置网关时 client.resolve_endpoint 直接
抛可读错误（不静默走内置通道）。自建公益网关见 ai_gateway/README.md。
"""

from __future__ import annotations

_UNAVAILABLE = "unavailable-token-removed-in-build"
_M = "deepseek-v4-flash"


def public_base() -> str:
    return ""


def public_token() -> str:
    return _UNAVAILABLE


def public_model() -> str:
    return _M


def public_endpoint() -> dict:
    return {
        "base": "",
        "token": _UNAVAILABLE,
        "model": _M,
    }
