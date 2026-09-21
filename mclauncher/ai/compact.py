# -*- coding: utf-8 -*-
"""两级上下文压缩 + 双重熔断（对齐 ZCode 的 microcompact / autocompact）。

第一级 microcompact：把老的工具结果替换成占位符，省不够 min_token_savings
就整体回退，绝不为省几百 token 破坏上下文。
第二级 autocompact：把较早的对话整体总结成一条摘要消息。
熔断：连续失败 max_consecutive_failures 次不再尝试；压缩后不足
tool_turn_threshold 个工具轮又触发，连续 max_consecutive_rapid_refills 次
抛 RapidRefillBlocked 中断本轮，防止「压缩→立刻满→再压缩」烧钱。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import tokens as tokens_mod


class RapidRefillBlocked(Exception):
    """rapid-refill 熔断：上下文压缩后立刻又满，连续多次。"""


# ---------------------------------------------------------------- microcompact

@dataclass
class MicroConfig:
    enabled: bool = True
    threshold_tokens: int | None = None   # 默认从 autocompact 阈值派生
    keep_recent_tool_results: int = 5     # ★ ZCode 默认值未取到，此为自定
    min_token_savings: int = 2000         # ★ 同上，自定
    idle_threshold_minutes: int = 30      # ★ 同上，自定


@dataclass
class MicroResult:
    messages: list = field(default_factory=list)
    decision_reason: str = ""   # disabled|not_triggered|no_candidates|nothing_to_clear|below_min_savings|applied
    cleared_count: int = 0
    cleared_ids: list = field(default_factory=list)
    kept_ids: list = field(default_factory=list)
    tokens_saved: int = 0
    changed: bool = False


# 全工程没有「按 tool_call_id 找回原文」的通道（read_artifact 只认 artifact 文件名），
# 占位文案不能许诺这个——模型照着做只会白跑一轮。
_PLACEHOLDER = "[工具结果已清理：内容较旧已从上下文移除，需要时请重新调用该工具获取]"


def _tool_candidates(messages) -> list:
    """消息里 role=tool 的下标（越靠后越新）。"""
    return [i for i, m in enumerate(messages)
            if isinstance(m, dict) and m.get("role") == "tool"]


def microcompact(messages, cfg: MicroConfig, last_assistant_at: float = 0.0,
                 now: float = 0.0) -> MicroResult:
    messages = list(messages or [])
    if not cfg.enabled:
        return MicroResult(messages=messages, decision_reason="disabled")
    candidates = _tool_candidates(messages)
    keep = max(0, cfg.keep_recent_tool_results)
    if not candidates:
        return MicroResult(messages=messages, decision_reason="no_candidates")
    to_clear = candidates[:-keep] if keep else candidates
    if not to_clear:
        return MicroResult(messages=messages,
                           decision_reason="nothing_to_clear", kept_ids=[
                               str(messages[i].get("tool_call_id") or i)
                               for i in candidates[-keep:]])
    # 触发条件：token 过阈值，或闲置超过 idle_threshold_minutes
    est = tokens_mod.estimate_messages(messages)
    triggered = cfg.threshold_tokens is not None and est >= cfg.threshold_tokens
    idle_triggered = (now and last_assistant_at
                      and (now - last_assistant_at) >= cfg.idle_threshold_minutes * 60)
    if not triggered and not idle_triggered:
        return MicroResult(messages=messages, decision_reason="not_triggered")

    out = list(messages)
    cleared_ids = []
    for i in to_clear:
        m = out[i]
        cleared_ids.append(str(m.get("tool_call_id") or i))
        out[i] = dict(m, content=_PLACEHOLDER)
    saved = est - tokens_mod.estimate_messages(out)
    if saved < cfg.min_token_savings:
        # 省不够：整体回退，别为省几百 token 破坏上下文
        return MicroResult(messages=messages, decision_reason="below_min_savings",
                           tokens_saved=saved)
    kept_ids = [str(messages[i].get("tool_call_id") or i)
                for i in candidates[-keep:]]
    return MicroResult(messages=out, decision_reason="applied",
                       cleared_count=len(to_clear), cleared_ids=cleared_ids,
                       kept_ids=kept_ids, tokens_saved=saved, changed=True)


# ---------------------------------------------------------------- autocompact

@dataclass
class AutoConfig:
    enabled: bool = True
    # 保守默认 128k：目标模型 deepseek-v4-flash 的真实窗口【待实测】（tokens.py 有实测
    # 方法）。取公开 DeepSeek 系列常见窗口上界，宁小勿大——估大了 autocompact 触发过晚
    # 会撞上游 400（有 reactive compact 兜底），估小了只是多压几次。设置 UI 可改
    # （ai_context_window，Qt/WPF 设置页均有），本常量只是无配置时的兜底。
    context_window: int = 131_072
    buffer_tokens: int = 13_000
    max_consecutive_failures: int = 3
    max_consecutive_rapid_refills: int = 3
    tool_turn_threshold: int = 3
    keep_recent_messages: int = 6     # 压缩时保留的最近消息数（不含 system）


# 与 AutoConfig.context_window 默认值保持一致；settings.ai_context_window 的
# 解析入口（含夹取）统一走 auto_config_from_settings
DEFAULT_CONTEXT_WINDOW = 131_072
MIN_CONTEXT_WINDOW = 8_192
MAX_CONTEXT_WINDOW = 2_000_000


def auto_config_from_settings(settings: dict | None) -> AutoConfig:
    """settings['ai_context_window'] → AutoConfig；非法/非正值回退保守默认。"""
    raw = (settings or {}).get("ai_context_window")
    try:
        window = int(raw)
    except (TypeError, ValueError):
        window = DEFAULT_CONTEXT_WINDOW
    if window <= 0:
        window = DEFAULT_CONTEXT_WINDOW
    window = max(MIN_CONTEXT_WINDOW, min(window, MAX_CONTEXT_WINDOW))
    return AutoConfig(context_window=window)


def auto_threshold(cfg: AutoConfig) -> int:
    return max(0, int(cfg.context_window) - int(cfg.buffer_tokens))


@dataclass
class CompactState:
    consecutive_failures: int = 0
    rapid_refills: int = 0
    tool_turns_since_compact: int = 10 ** 9   # 初始视为「很久没压缩」


@dataclass
class AutoDecision:
    should: bool
    reason: str   # disabled|not_enough_messages|circuit_breaker|below_threshold|above_threshold


def should_autocompact(messages, cfg: AutoConfig, cstate: CompactState,
                       st=None) -> AutoDecision:
    if not cfg.enabled:
        return AutoDecision(False, "disabled")
    if cstate.consecutive_failures >= cfg.max_consecutive_failures:
        return AutoDecision(False, "circuit_breaker")
    # system 头 + 少量消息不值得压
    body = [m for m in messages or [] if isinstance(m, dict) and m.get("role") != "system"]
    if len(body) < cfg.keep_recent_messages + 2:
        return AutoDecision(False, "not_enough_messages")
    est = (st and tokens_mod.current_input_tokens(messages, st)) or \
        tokens_mod.estimate_messages(messages)
    if est < auto_threshold(cfg):
        return AutoDecision(False, "below_threshold")
    return AutoDecision(True, "above_threshold")


def check_rapid_refill(cstate: CompactState, cfg: AutoConfig) -> None:
    """压缩后不足 tool_turn_threshold 个工具轮又要压：计数，超限抛断。"""
    if cstate.tool_turns_since_compact >= cfg.tool_turn_threshold:
        return
    cstate.rapid_refills += 1
    if cstate.rapid_refills >= cfg.max_consecutive_rapid_refills:
        raise RapidRefillBlocked(
            f"上下文压缩后 {cstate.tool_turns_since_compact} 个工具轮又触发压缩，"
            f"连续 {cstate.rapid_refills} 次，已熔断")


def note_compact_success(cstate: CompactState) -> None:
    cstate.consecutive_failures = 0
    cstate.tool_turns_since_compact = 0


def note_compact_failure(cstate: CompactState, cfg: AutoConfig) -> bool:
    """返回是否达到失败熔断线。"""
    cstate.consecutive_failures += 1
    return cstate.consecutive_failures >= cfg.max_consecutive_failures


@dataclass
class CompactionResult:
    messages: list = field(default_factory=list)
    pre_token_count: int = 0
    post_token_count: int = 0
    true_post_token_count: int = 0
    summarized_message_count: int = 0
    kept_message_count: int = 0
    last_summarized_message_id: str = ""
    will_retrigger_next_turn: bool = False
    threshold: int = 0


_SUMMARY_PROMPT = (
    "把这段启动器对话压成一份简短摘要。必须保留：用户最终想要什么、"
    "已经执行过哪些操作（工具名和结果成败）、提到的游戏版本/实例/模组名、"
    "还没做完的事。直接输出摘要正文，不要客套。"
)


def _align_keep_boundary(body, cut: int) -> int:
    """把「保留区」起点往前挪到不会切出孤儿 tool 消息的位置。

    OpenAI 语义下 role=tool 必须紧跟在带 tool_calls 的 assistant 之后；若保留区
    第一条是 tool、而它对应的 assistant 已被摘要掉，下一轮请求直接 400，整回合失败。
    往前多保留几条比少保留安全，所以只向前挪、不向后挪。
    """
    cut = max(0, min(cut, len(body)))
    while cut > 0 and cut < len(body) and isinstance(body[cut], dict) \
            and body[cut].get("role") == "tool":
        cut -= 1
    return cut


def compact_conversation(messages, cfg: AutoConfig, summarize_fn) -> CompactionResult:
    """把较早的对话换成一条摘要消息；summarize_fn(list) -> str 由 agent 注入。"""
    messages = list(messages or [])
    pre = tokens_mod.estimate_messages(messages)
    threshold = auto_threshold(cfg)
    head = 0
    while head < len(messages) and isinstance(messages[head], dict) \
            and messages[head].get("role") == "system":
        head += 1
    body = messages[head:]
    keep = max(2, cfg.keep_recent_messages)
    if len(body) <= keep:
        return CompactionResult(messages=messages, pre_token_count=pre,
                                post_token_count=pre, true_post_token_count=pre,
                                summarized_message_count=0,
                                kept_message_count=len(body),
                                threshold=threshold)
    cut = _align_keep_boundary(body, len(body) - keep)
    if cut <= 0:
        # 对齐后没有可摘要的部分（最近几条全是同一组工具往返），原样返回
        return CompactionResult(messages=messages, pre_token_count=pre,
                                post_token_count=pre, true_post_token_count=pre,
                                summarized_message_count=0,
                                kept_message_count=len(body),
                                threshold=threshold)
    to_summarize = body[:cut]
    kept = body[cut:]
    summary = summarize_fn(to_summarize)
    if not (summary or "").strip():
        raise ValueError("摘要为空，拒绝替换历史")
    last_id = ""
    for i, m in enumerate(to_summarize):
        mid = (m.get("id") if isinstance(m, dict) else None) or f"idx_{head + i}"
        last_id = str(mid)
    summary_msg = {
        "role": "user",
        "content": f"[历史摘要]\n{summary.strip()}\n（以上是更早对话的摘要，继续当前任务。）",
        "id": f"compact_{last_id}",
    }
    out = messages[:head] + [summary_msg] + kept
    post = tokens_mod.estimate_messages(out)
    return CompactionResult(
        messages=out, pre_token_count=pre, post_token_count=post,
        true_post_token_count=post,
        summarized_message_count=len(to_summarize), kept_message_count=len(kept),
        last_summarized_message_id=last_id,
        will_retrigger_next_turn=post >= threshold, threshold=threshold)
