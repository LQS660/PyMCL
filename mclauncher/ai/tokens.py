# -*- coding: utf-8 -*-
"""token 计量：优先用 provider 的 usage 做基线，只对新增消息估算。

估算启发式：中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。
真实窗口（deepseek-v4-flash）未实测，context_window 由 settings 传入。
"""

from __future__ import annotations

from dataclasses import dataclass

_PER_MSG_OVERHEAD = 4        # 每条消息的角色/结构开销
_ASCII_CHARS_PER_TOKEN = 4


@dataclass
class TokenState:
    base_tokens: int = 0            # provider 报的 input_tokens
    base_msg_index: int = 0         # 基线对应到第几条消息（发送时的 len(messages)）
    cache_read: int = 0
    cache_write: int = 0
    source: str = "estimate"        # provider_usage | estimate
    last_output_tokens: int = 0


def estimate_text(s: str) -> int:
    if not s:
        return 0
    tokens = 0
    for ch in s:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            tokens += 1
        else:
            tokens += 0.25
    return int(tokens) + 1


def estimate_messages(messages) -> int:
    total = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        total += _PER_MSG_OVERHEAD
        total += estimate_text(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            total += estimate_text(str((tc.get("function") or {}).get("arguments") or ""))
            total += estimate_text(str((tc.get("function") or {}).get("name") or ""))
    return total


def update_from_usage(st: TokenState, usage: dict, n_messages: int) -> None:
    """用最近一次 provider usage 更新基线。n_messages = 该请求发出时的条数。"""
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = int((details or {}).get("cached_tokens") or 0)
    if prompt > 0:
        st.base_tokens = prompt
        st.base_msg_index = int(n_messages)
        st.cache_read = cached
        st.source = "provider_usage"
    st.last_output_tokens = completion


def current_input_tokens(messages, st: TokenState) -> int:
    """当前上下文的估算输入 token：基线 + 基线之后新增消息的估算。"""
    messages = messages or []
    if st.source == "provider_usage" and st.base_msg_index <= len(messages):
        return st.base_tokens + estimate_messages(messages[st.base_msg_index:])
    return estimate_messages(messages)
