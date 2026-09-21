# -*- coding: utf-8 -*-
"""会话用量追踪（批次 6.1）：进程内按对话累计 token，供 AI 页展示。

- 有真实 usage 的请求（自定义 NewAPI 直连）→ source=provider_usage；
- 公益网关拿不到 usage → 用本地估算垫数，source=estimate，界面必须标「估算」；
- 混合来源：real_requests > 0 即认为有真实口径，但估算部分单独累计——
  界面展示「输入 X（其中估算 Y）」级别的诚实数字，不把估算假装成实测。
"""

from __future__ import annotations

import threading

from . import tokens as tokens_mod

_LOCK = threading.Lock()
_data: dict = {}


def _blank() -> dict:
    return {"input": 0, "output": 0, "input_estimated": 0,
            "requests": 0, "real_requests": 0}


def add(chat_id: str, usage: dict | None, estimated_input: int = 0,
        estimated_output: int = 0) -> None:
    """记一次模型请求。usage 为 None/空 = 该通道拿不到真实回执（公益网关）。"""
    chat_id = str(chat_id or "active")
    with _LOCK:
        row = _data.setdefault(chat_id, _blank())
        row["requests"] += 1
        usage = usage or {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        if prompt > 0 or completion > 0:
            row["real_requests"] += 1
            row["input"] += prompt
            row["output"] += completion
        else:
            row["input_estimated"] += int(estimated_input or 0)
            row["output"] += int(estimated_output or 0)


def get(chat_id: str) -> dict:
    with _LOCK:
        row = _data.get(str(chat_id or "active"))
        if not row:
            return {"input": 0, "output": 0, "input_estimated": 0,
                    "requests": 0, "real_requests": 0, "source": "estimate"}
        out = dict(row)
        out["source"] = "provider_usage" if row["real_requests"] else "estimate"
        return out


def reset(chat_id: str) -> None:
    with _LOCK:
        _data.pop(str(chat_id or "active"), None)


def estimate_messages_output(messages) -> int:
    return tokens_mod.estimate_messages(messages)
