# -*- coding: utf-8 -*-
"""Agent 主循环：turn 状态机 + 流式模型调用 + 工具并行调度 + 权限判权。"""

from __future__ import annotations

import inspect
import json
import random
import re
import time
import uuid

from . import compact
from . import permission
from . import scheduler
from . import store as chat_store
from . import tokens as tokens_mod
from . import trace
from .client import AIClientError, chat_once, chat_stream, is_context_overflow
from .defaults import MAX_HISTORY, MAX_TOOL_ROUNDS
from .permission import Behavior, Decision, Rule
from .prompt import system_prompt
from .result import AgentResult, StopReason
from .state import IllegalTransition, ToolCall, ToolCallStatus, TurnPhase, TurnState
from .tools import (
    TOOL_META, TOOL_SCHEMAS, ToolCancelled, confirm_label, is_ask_tool,
    normalize_ask_args, parse_args, run_tool, runtime_context,
)


class AgentCancelled(Exception):
    pass


def _trim_history(history: list) -> list:
    if len(history) <= MAX_HISTORY:
        trimmed = list(history)
    else:
        trimmed = list(history[-MAX_HISTORY:])
    # 切片不能从孤立的 tool 消息开始（它前面的 assistant.tool_calls 被切掉了）
    i = 0
    while i < len(trimmed) and isinstance(trimmed[i], dict) \
            and trimmed[i].get("role") == "tool":
        i += 1
    return trimmed[i:]


def _current_instance() -> str:
    try:
        from mclauncher.config import CONFIG
        return CONFIG.get("default_instance", "default") or "default"
    except Exception:  # noqa: BLE001
        return "default"


def _system_messages(backend, settings: dict) -> list:
    ctx = runtime_context(backend)
    msgs = [
        {"role": "system", "content": system_prompt()},
        {"role": "system", "content": "当前启动器状态：\n" + ctx},
    ]
    note = permission.permission_note(settings or {})
    if note:
        msgs.append({"role": "system", "content": note})
    return msgs


def _call_confirm(confirm_fn, tname: str, args: dict, label: str, reason: str):
    """confirm_fn 兼容两种签名：旧三参（bridge 端）与新四参（带拒绝原因）。

    返回 bool 或 Rule（Rule = 用户选了「以后都允许」）。
    """
    if confirm_fn is None:
        return True
    try:
        nparams = len(inspect.signature(confirm_fn).parameters)
    except (TypeError, ValueError):  # noqa: BLE001
        nparams = 3
    if nparams >= 4:
        return confirm_fn(tname, args, label, reason)
    return confirm_fn(tname, args, label)


def _to_phase(turn: TurnState, phase: TurnPhase) -> None:
    """收尾用的迁移：失败只记 trace，绝不在清理路径上抛异常。"""
    try:
        if turn.phase not in (TurnPhase.COMPLETING, TurnPhase.ERROR):
            turn.transition(phase)
    except IllegalTransition as exc:
        trace.record("illegal_transition", phase=turn.phase.value, exc=exc)


# ---- 「只回了文字」到底算不算没干活 -------------------------------------
# NO_TOOL_CALL 原来的口径是「一轮下来没调过工具」，于是「你好」「1.20.1 有啥新东西」
# 这类本来就该用文字回答的回合也被打成没动手，三端都弹「它没有真的开始执行」。
# 这里按用户那句话判：要求下载 / 安装 / 改配置这类得调工具才办得到的事，模型却
# 光说话，才是真的没动手；问答、闲聊回文字就是完成。模型嘴上说「已经装好了」
# 而工具轨迹是空的，也算没动手——那是在编。
_ACTION_RE = re.compile(
    r"下载|安装|重装|卸载|装(?:个|一下|上|好|到|进|下)|删(?:除|掉|了|个|一下)|移除"
    r"|清(?:理|掉|空|一下)|修(?:复|好|一下|下)|修改|改(?:成|为|一下|下|掉|到|个)"
    r"|设(?:置|成|为|定|到)|配置|调(?:成|到|整|一下|大|小|高|低)|换(?:成|到|个|一下)"
    r"|切(?:换|到|成)|开(?:启|一下|下)|关(?:闭|掉|上|一下)|打开|启动|运行|跑(?:一下|起来|个)"
    r"|导入|导出|更新|升级|备份|恢复|还原|重启|添加|加(?:个|上|一下|进|到)|新建|创建"
    r"|重命名|迁移|帮我|给我|替我|干活|搞定|弄(?:好|一下|个)|试试|继续|开始|执行|动手"
    r"|\b(?:install|download|uninstall|remove|delete|clean|fix|repair|set|change|configure"
    r"|config|enable|disable|turn (?:on|off)|switch|launch|start|run|import|export|update"
    r"|upgrade|back ?up|restore|add|create|rename|migrate|do it|go ahead|continue|proceed)\b",
    re.IGNORECASE,
)
# 问法：「怎么安装 Fabric」是在问，不是在派活——除非同时带着「帮我 / 请 / 把」
_QUESTION_RE = re.compile(
    r"怎么|怎样|如何|为什么|为啥|什么|哪(?:个|些|里|儿)|是不是|能不能|可不可以|区别|介绍"
    r"|解释|说说|讲讲|意思|吗[？?]?\s*$|[？?]\s*$"
    r"|\b(?:how|what|why|which|where|when|does|do|is|are|should)\b",
    re.IGNORECASE,
)
_DELEGATE_RE = re.compile(
    r"帮我|给我|替我|请你?|麻烦|把|\b(?:can you|could you|would you|please|go ahead|do it)\b",
    re.IGNORECASE,
)
_CLAIM_RE = re.compile(
    r"(?:已经?|正在|马上|现在)(?:帮你|为你|给你)?(?:开始)?"
    r"(?:下载|安装|重装|卸载|删除|移除|清理|修复|修改|设置|配置|调整|切换|开启|关闭|打开"
    r"|启动|导入|导出|更新|升级|备份|恢复|重启|添加|创建|重命名|迁移)"
    r"|(?:下载|安装|删除|清理|修复|修改|设置|切换|导入|导出|更新|升级|备份|恢复|添加)"
    r"(?:完成|好了|成功|完毕)"
    r"|\bI(?:'ve| have) (?:installed|downloaded|removed|deleted|updated|set|changed|configured"
    r"|enabled|disabled|fixed|added|created)\b"
    r"|\b(?:installing|downloading|removing|updating|configuring) (?:it|now|the)\b",
    re.IGNORECASE,
)


def wants_action(user_text: str) -> bool:
    """用户这句话是不是在要求动手（得调工具才办得到的事）。

    带动作词才算；带动作词但整句是个问法（怎么 / 什么 / 吗 / ？）且没有
    「帮我 / 请 / 把」这类派活语气的，按提问处理。
    """
    text = (user_text or "").strip()
    if not text or not _ACTION_RE.search(text):
        return False
    if _QUESTION_RE.search(text) and not _DELEGATE_RE.search(text):
        return False
    return True


def claims_action(reply: str) -> bool:
    """模型的回复是不是在声称「已经做了 / 正在做」某件要调工具的事。"""
    return bool(_CLAIM_RE.search(reply or ""))


def run_agent(backend, settings: dict, history: list, user_text: str,
              on_delta=None, on_status=None, confirm_fn=None, ask_fn=None,
              cancelled=None, http_cancel=None, drain_inputs_fn=None):
    """
    on_delta(text)
    on_status(kind, payload)
    confirm_fn(tool_name, args, label[, reason]) -> bool | Rule
    ask_fn(questions, title) -> dict | None
    cancelled() -> bool
    drain_inputs_fn() -> list[str]   运行中用户插话（steering），每轮开头取走
    返回 AgentResult（str 子类，可直接当文本用；额外带 stop_reason 等元数据）。
    """
    def _check():
        if cancelled and cancelled():
            raise AgentCancelled()

    round_no = [0]

    def _status(kind, payload):
        if not on_status:
            return
        try:
            on_status(kind, payload or {})
        except Exception as exc:  # noqa: BLE001
            trace.record("on_status_error", round_=round_no[0], exc=exc, kind=kind)

    def _delta(piece):
        if not on_delta or not piece:
            return
        try:
            on_delta(piece)
        except Exception as exc:  # noqa: BLE001
            trace.record("on_delta_error", round_=round_no[0], exc=exc)

    messages = _system_messages(backend, settings) + _trim_history(history)
    # 这之后追加的都是本回合新产生的（用户这句 + 工具轨迹 + 续写），导出给 UI 持久化时
    # 只取这一段，别把裁剪过的旧历史再抄一遍进去
    base_len = len(messages)
    compacted = [False]
    messages.append({"role": "user", "content": user_text})
    state_base = messages[1]["content"] if len(messages) > 1 and \
        messages[1].get("role") == "system" else ""

    instance_name = _current_instance()
    mode = permission.normalize_permission_mode(
        (settings or {}).get("ai_permission_mode"),
        bool((settings or {}).get("ai_confirm_writes", True)))
    dont_ask = bool((settings or {}).get("ai_permission_dont_ask", False))
    rules = permission.dedupe_rules(
        list(permission.load_rules(instance_name))
        + list((settings or {}).get("ai_permission_rules") or []))

    final = ""
    acted = False
    pending: list = []
    ask_answered_prev = False       # 上一轮 ask_user 拿到了答案
    continuation_used = False       # 代码保证的续步只用一次
    continuation_pending = False    # 下一轮 progress 通道带行动指引
    continuation_parts: list = []   # 截断续写时已产出的片段
    continuation_count = 0          # 截断续写次数（最多 2 次）
    turn = TurnState(id=uuid.uuid4().hex[:12], session_id="active", turn_number=1)

    # ---- 上下文与 token（批次 3）----
    auto_cfg = compact.AutoConfig(
        context_window=int((settings or {}).get("ai_context_window") or 200_000))
    # micro 阈值从 autocompact 阈值派生：先清旧工具结果，实在不行再全量总结
    micro_cfg = compact.MicroConfig(
        threshold_tokens=max(4_000, compact.auto_threshold(auto_cfg) - 16_000))
    cstate = compact.CompactState()
    token_state = tokens_mod.TokenState()

    def _summarize(slice_messages) -> str:
        # 压缩会再发一次模型请求，必须尊重停止信号
        _check()
        prompt = [
            {"role": "system", "content": compact._SUMMARY_PROMPT},
            {"role": "user", "content": json.dumps(
                slice_messages, ensure_ascii=False)[:60000]},
        ]
        data = chat_once(settings, prompt, None, http_cancel=http_cancel)
        _check()
        return data.get("content") or ""

    def _force_compact(round_: int) -> bool:
        """reactive compact：上游报「塞不下」时强制压缩，成功返回 True。"""
        try:
            cres = compact.compact_conversation(messages, auto_cfg, _summarize)
        except AgentCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            compact.note_compact_failure(cstate, auto_cfg)
            trace.record("reactive_compact_failure", round_=round_, exc=exc)
            return False
        messages[:] = cres.messages
        compacted[0] = True
        compact.note_compact_success(cstate)
        _status("compact", {"reason": "reactive", "pre": cres.pre_token_count,
                            "post": cres.post_token_count})
        trace.record("reactive_compact", round_=round_,
                     pre=cres.pre_token_count, post=cres.post_token_count)
        return True

    def _full(text: str) -> str:
        """截断续写后，返回给用户的必须是拼完整的全文。"""
        if not continuation_parts:
            return text
        return "".join(continuation_parts) + text

    def _await_pending(timeout: float) -> list:
        """回合内短超时等后台任务；拿到结果的从 pending 里摘掉。"""
        got = []
        deadline = time.monotonic() + timeout
        for task in list(pending):
            left = deadline - time.monotonic()
            if left <= 0:
                break
            _check()
            try:
                res = backend.wait_task(task["task_id"], timeout=left,
                                        cancelled=cancelled)
            except Exception as exc:  # noqa: BLE001
                trace.record("wait_task_error", tool_name=task["name"], exc=exc)
                continue
            msg = str(res.get("message") or "")
            if res.get("ok") is None or msg == "等待任务超时":
                continue   # 还在跑
            pending.remove(task)
            got.append({"name": task["name"], "ok": bool(res.get("ok")), "message": msg})
        return got

    def _sleep_backoff(attempt: int) -> None:
        """指数退避 1s / 2s / 4s + 抖动；期间保持可取消。"""
        base = min(4.0, 2 ** (attempt - 1))
        _check()
        time.sleep(base * (0.8 + 0.4 * random.random()))
        _check()

    def _looks_like_request(text: str) -> bool:
        """用户这句像不像「要我动手」：像才把只回文字判成 NO_TOOL_CALL。

        打招呼、问概念、追问原因，模型只回文字是正常收尾，不该被标成「没有真的
        开始执行」——那句提示会被两端拼进正文并入库，下一轮模型读到自己上一句后面
        挂着这话，容易误判成要补动作。词表与问法过滤见模块级 wants_action。
        """
        return wants_action(text)

    def _result(text, reason, **kw):
        # 只回文字算不算没动手，统一在这儿裁决（所有 NO_TOOL_CALL 出口都经过这里）：
        # 用户没派活、模型也没自称干了什么 → 就是一次正常的文字回答
        if reason == StopReason.NO_TOOL_CALL and not _looks_like_request(user_text) \
                and not claims_action(text):
            reason = StopReason.COMPLETED
            kw.pop("detail", None)
        res = AgentResult(text, stop_reason=reason, **kw)
        try:
            # 本回合完整轨迹（不含 system 头），供 UI 持久化（W5-1）
            export = [dict(m) for m in messages
                      if isinstance(m, dict) and m.get("role") != "system"]
            # 最终 assistant 正文没有进 messages（只有带 tool_calls 的才进），
            # 导出时补上，重开程序后模型才知道上一轮说了什么
            if text and (not export
                         or export[-1].get("role") != "assistant"
                         or export[-1].get("tool_calls")):
                export.append({"role": "assistant", "content": str(text)})
            res.messages = export
            # 只属于本回合的那一段（用户这句 + 工具轨迹 + 最终正文）：UI 往历史里
            # 追加时用它，别把 messages 里抄来的旧历史再存一遍。压缩过就取不准了，
            # 退回「用户这句 + 最终正文」。
            if compacted[0]:
                turn = [{"role": "user", "content": user_text}]
            else:
                turn = [dict(m) for m in messages[base_len:]
                        if isinstance(m, dict) and m.get("role") != "system"]
            if text and (not turn
                         or turn[-1].get("role") != "assistant"
                         or turn[-1].get("tool_calls")):
                turn.append({"role": "assistant", "content": str(text)})
            res.turn_messages = turn
        except Exception:  # noqa: BLE001
            res.messages = []
            res.turn_messages = []
        return res

    session_id = str((settings or {}).get("ai_session_id") or "active")
    chat_store.log_event(session_id, "TurnStarted", turn_id=turn.id,
                         user_len=len(user_text or ""))

    try:
        turn.transition(TurnPhase.PROCESSING_INPUT)
        for _round in range(MAX_TOOL_ROUNDS):
            round_no[0] = _round + 1
            turn.rounds_used = round_no[0]
            _check()

            # steering：用户在跑动期间补的话，同一回合被采纳
            if drain_inputs_fn:
                try:
                    steers = [str(s or "").strip() for s in (drain_inputs_fn() or [])]
                except Exception as exc:  # noqa: BLE001
                    trace.record("drain_inputs_error", round_=round_no[0], exc=exc)
                    steers = []
                for steer_text in steers:
                    if not steer_text:
                        continue
                    messages.append({"role": "user", "content": steer_text})
                    _status("steer", {"text": steer_text[:200]})

            if turn.phase == TurnPhase.PROCESSING_INPUT:
                turn.transition(TurnPhase.AWAITING_MODEL)
            turn.transition(TurnPhase.STREAMING)

            # 每轮把剩余步数注入 system 状态段（原样替换，不往历史里堆积）
            if state_base:
                extra = ""
                if _round > 0:
                    extra += f"\n\n[进度] 本轮已用 {round_no[0]}/{MAX_TOOL_ROUNDS} 步。"
                    if MAX_TOOL_ROUNDS - round_no[0] < 4:
                        extra += "剩余不足 4 步时请优先收尾并说明当前状态。"
                if continuation_pending:
                    extra += ("\n用户刚在选项里做出选择：若需要执行操作，"
                              "请立刻调用对应工具；若无需操作，请说明原因。")
                messages[1]["content"] = state_base + extra

            _status("think", {"after_tools": any(m.get("role") == "tool" for m in messages)})

            # ---- 上下文管理：先试两级压缩，再发模型请求 ----
            cur_tokens = tokens_mod.current_input_tokens(messages, token_state)
            decision = compact.should_autocompact(messages, auto_cfg, cstate, token_state)
            if decision.should:
                try:
                    compact.check_rapid_refill(cstate, auto_cfg)
                except compact.RapidRefillBlocked as exc:
                    _to_phase(turn, TurnPhase.COMPLETING)
                    trace.record("compact_rapid_refill_blocked", round_=round_no[0], exc=exc)
                    return _result(
                        final or "", StopReason.ERROR,
                        detail="上下文反复逼近窗口上限，已中断本轮以保护额度",
                        pending_tasks=pending, rounds_used=round_no[0])
                try:
                    cres = compact.compact_conversation(messages, auto_cfg, _summarize)
                    messages[:] = cres.messages
                    compacted[0] = True
                    compact.note_compact_success(cstate)
                    _status("compact", {"reason": decision.reason,
                                        "pre": cres.pre_token_count,
                                        "post": cres.post_token_count,
                                        "summarized": cres.summarized_message_count})
                    trace.record("autocompact", round_=round_no[0],
                                 pre=cres.pre_token_count, post=cres.post_token_count)
                    chat_store.log_event(session_id, "CompactBoundary",
                                         turn_id=turn.id, round=round_no[0],
                                         trigger="auto", pre=cres.pre_token_count,
                                         post=cres.post_token_count)
                except AgentCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if compact.note_compact_failure(cstate, auto_cfg):
                        trace.record("compact_circuit_break", round_=round_no[0])
                    else:
                        trace.record("compact_failure", round_=round_no[0], exc=exc)
            elif cur_tokens >= (micro_cfg.threshold_tokens or 10 ** 12):
                mres = compact.microcompact(messages, micro_cfg, 0.0, 0.0)
                if mres.changed:
                    messages[:] = mres.messages
                    _status("compact", {"reason": "microcompact",
                                        "cleared": mres.cleared_count,
                                        "saved": mres.tokens_saved})

            reactive_attempted = False
            retry_no = 0
            tool_calls: list = []
            text_parts: list = []
            truncated = False
            stream_failed = False
            for _attempt in range(6):
                tool_calls = []
                text_parts = []
                truncated = False
                stream_failed = False
                n_req = len(messages)
                usage_info = None
                stream_err = ""
                chat_store.log_event(session_id, "ModelRequest",
                                     turn_id=turn.id, round=round_no[0],
                                     attempt=_attempt, msg_count=n_req)
                try:
                    for ev in chat_stream(settings, messages, TOOL_SCHEMAS, http_cancel=http_cancel):
                        _check()
                        kind = ev.get("type")
                        if kind == "delta":
                            piece = ev.get("text") or ""
                            text_parts.append(piece)
                            _delta(piece)
                        elif kind == "tool_calls":
                            tool_calls = ev.get("tool_calls") or []
                            break
                        elif kind == "done":
                            truncated = ev.get("finish_reason") == "length"
                            break
                        elif kind == "usage":
                            usage_info = ev.get("usage")
                        elif kind == "error":
                            raise AIClientError(ev.get("message") or "接口错误")
                except AIClientError as exc:
                    if exc.fatal():
                        raise
                    if exc.retryable() and not text_parts and not tool_calls \
                            and retry_no < 3:
                        # 429/超时/网络抖动：退避重试，而不是终止对话（W5-3）
                        retry_no += 1
                        _status("retry", {"attempt": retry_no, "error": str(exc)[:160]})
                        trace.record("retry", round_=round_no[0], attempt=retry_no, exc=exc)
                        _sleep_backoff(retry_no)
                        continue
                    stream_failed = True
                    stream_err = str(exc)
                    trace.record("stream_error", round_=round_no[0], exc=exc, stream_failed=True)
                except Exception as exc:  # noqa: BLE001
                    stream_failed = True
                    stream_err = str(exc)
                    trace.record("stream_exception", round_=round_no[0], exc=exc, stream_failed=True)
                if usage_info:
                    tokens_mod.update_from_usage(token_state, usage_info, n_req)

                # reactive compact：上下文塞不下 → 压缩后重试同一个 step（每步一次）
                if is_context_overflow(stream_err) and not reactive_attempted:
                    reactive_attempted = True
                    if _force_compact(round_no[0]):
                        chat_store.log_event(session_id, "CompactBoundary",
                                             turn_id=turn.id, round=round_no[0],
                                             trigger="reactive")
                        continue

                if not tool_calls and (stream_failed or not "".join(text_parts)):
                    _check()
                    try:
                        data = chat_once(settings, messages, TOOL_SCHEMAS,
                                         http_cancel=http_cancel)
                    except AIClientError as exc:
                        if exc.fatal():
                            raise
                        if is_context_overflow(str(exc)) and not reactive_attempted:
                            reactive_attempted = True
                            if _force_compact(round_no[0]):
                                continue
                        raise
                    if isinstance(data.get("usage"), dict) and data["usage"]:
                        tokens_mod.update_from_usage(token_state, data["usage"], len(messages))
                    fb_content = data.get("content") or ""
                    if fb_content and not text_parts:
                        text_parts.append(fb_content)
                        _delta(fb_content)
                    elif fb_content and stream_failed:
                        # 流中途断了、已经吐出半截：兜底拿回来的是完整正文，得采纳它，
                        # 否则用户只看到半句还没有任何提示。界面上已经显示了前半截：
                        # 是同一开头就只补后半截，不是就换行接完整版（ai.done 会整段覆盖）。
                        partial = "".join(text_parts)
                        if fb_content.startswith(partial):
                            _delta(fb_content[len(partial):])
                        else:
                            _delta("\n\n" + fb_content)
                        text_parts[:] = [fb_content]
                    if not tool_calls:
                        tool_calls = data.get("tool_calls") or []
                    truncated = truncated or data.get("finish_reason") == "length"
                    if not tool_calls and not data.get("content"):
                        trace.record("empty_fallback", round_=round_no[0],
                                     stream_failed=stream_failed, text_len=0)
                break

            content = "".join(text_parts)
            if content:
                final = content

            if not tool_calls:
                rounds_used = round_no[0]
                # ask_user 刚拿到答案：由代码保证继续（一次），不靠提示词补丁
                if ask_answered_prev and not continuation_used and content:
                    continuation_used = True
                    ask_answered_prev = False
                    continuation_pending = True
                    turn.transition(TurnPhase.SCHEDULING_TOOLS)
                    turn.transition(TurnPhase.EXECUTING_TOOLS)
                    turn.transition(TurnPhase.AWAITING_MODEL)
                    continue
                if truncated:
                    # 截断续写：把已产出内容接回去再要一段，最多 2 次（W4-4）
                    if continuation_count < 2 and content:
                        continuation_count += 1
                        continuation_parts.append(content)
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user",
                                         "content": "请从断开处继续，不要重复。"})
                        turn.transition(TurnPhase.SCHEDULING_TOOLS)
                        turn.transition(TurnPhase.EXECUTING_TOOLS)
                        turn.transition(TurnPhase.AWAITING_MODEL)
                        continue
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result(
                        _full(content) + "\n\n（回复被长度限制截断了，需要的话让我继续。）",
                        StopReason.TRUNCATED, rounds_used=rounds_used)
                if stream_failed and not content:
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result("", StopReason.STREAM_FAILED,
                                   detail="流式与非流式兜底都没有返回内容",
                                   rounds_used=rounds_used)
                if pending:
                    # 回合内短超时等一等（W5-2）：拿到结果就回灌，模型来汇报
                    waited = _await_pending(20)
                    if waited:
                        for w in waited:
                            mark = "成功" if w["ok"] else "失败"
                            messages.append({"role": "user", "content":
                                             f"[后台任务回报] {w['name']} {mark}：{w['message']}"})
                        acted = True
                        turn.transition(TurnPhase.SCHEDULING_TOOLS)
                        turn.transition(TurnPhase.EXECUTING_TOOLS)
                        turn.transition(TurnPhase.AWAITING_MODEL)
                        continue
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result(_full(content), StopReason.PENDING_TASK,
                                   pending_tasks=pending, rounds_used=rounds_used)
                if not content and not continuation_parts:
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result("", StopReason.EMPTY_RESPONSE,
                                   detail="上游返回了空内容", rounds_used=rounds_used)
                if acted or continuation_parts:
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result(_full(content), StopReason.COMPLETED,
                                   rounds_used=rounds_used)
                # 问答 / 闲聊只回文字算不算没动手，由 _result 统一裁决
                _to_phase(turn, TurnPhase.COMPLETING)
                return _result(_full(content), StopReason.NO_TOOL_CALL,
                               detail="模型只回了文字，没有调用任何工具",
                               rounds_used=rounds_used)

            # ---- 工具阶段 ----
            turn.transition(TurnPhase.SCHEDULING_TOOLS)
            # 个别网关会给同一批 tool_calls 重复的 id：decisions / set_tool_status 都按 id
            # 索引，撞了就串号（第二个工具的结果落成空串）。这里先补齐再去重，
            # 并写回 tool_calls，随后进 messages 的 assistant.tool_calls 与 tool 回执才对得上。
            seen_ids: set = set()
            for i, tc in enumerate(tool_calls):
                cid = str(tc.get("id") or f"call_{round_no[0]}_{i}")
                if cid in seen_ids:
                    cid = f"{cid}_{i}"
                seen_ids.add(cid)
                tc["id"] = cid
            messages.append({"role": "assistant", "content": content or None,
                             "tool_calls": tool_calls})
            acted = True

            tool_objs = []
            for i, tc in enumerate(tool_calls):
                fn = tc.get("function") or {}
                obj = turn.add_tool_call(ToolCall(
                    id=tc["id"],
                    name=fn.get("name") or "",
                    args=parse_args(fn.get("arguments"))))
                tool_objs.append(obj)
                _status("tool", {"name": obj.name, "args": obj.args,
                                 "label": confirm_label(obj.name, obj.args)})

            # 判权：deny/modify 直接定，ask 稍后集中处理（可能弹 UI）
            needs_perm = False
            decisions: dict = {}
            for obj in tool_objs:
                if is_ask_tool(obj.name):
                    decisions[obj.id] = ("ask", "")
                    needs_perm = True
                    continue
                meta = TOOL_META.get(obj.name)
                res = permission.decide(meta, obj.args, mode, rules)
                if res.decision == Decision.MODIFY and res.modified_input:
                    obj.args = res.modified_input
                if res.decision == Decision.DENY:
                    decisions[obj.id] = ("deny", res.reason)
                    turn.set_tool_status(obj.id, ToolCallStatus.DENIED,
                                         result=f"[权限] 已拒绝：{res.reason}")
                elif res.decision == Decision.ASK and dont_ask:
                    decisions[obj.id] = ("deny", "用户开启了「不询问」模式")
                    turn.set_tool_status(obj.id, ToolCallStatus.DENIED,
                                         result="[权限] 已拒绝：用户开启了「不询问」模式")
                elif res.decision == Decision.ASK:
                    decisions[obj.id] = ("ask", res.reason)
                    needs_perm = True
                else:
                    decisions[obj.id] = ("allow", "")

            # 需要用户交互的（确认 / ask_user）在这一段串行完成，绝不进并行组
            if needs_perm:
                turn.transition(TurnPhase.AWAITING_PERMISSION)
            for obj in tool_objs:
                kind, reason = decisions[obj.id]
                if kind != "ask":
                    continue
                label = confirm_label(obj.name, obj.args)
                turn.set_tool_status(obj.id, ToolCallStatus.WAITING_PERMISSION)
                if is_ask_tool(obj.name):
                    questions = normalize_ask_args(obj.args)
                    title = obj.args.get("title") or ""
                    answered = ask_fn(questions, title) if ask_fn else None
                    if not answered:
                        turn.set_tool_status(obj.id, ToolCallStatus.COMPLETED,
                                             result="用户取消了选择")
                        _status("tool_skip", {"name": obj.name, "label": label})
                    else:
                        answer_text = answered if isinstance(answered, str) else json.dumps(
                            answered, ensure_ascii=False)
                        turn.set_tool_status(obj.id, ToolCallStatus.COMPLETED,
                                             result=answer_text)
                        ask_answered_prev = True
                        _status("tool_done", {"name": obj.name, "label": "已选择",
                                              "result": str(answer_text)[:400]})
                    continue
                rv = _call_confirm(confirm_fn, obj.name, obj.args, label, reason)
                if isinstance(rv, Rule):
                    rules = permission.apply_updates(rules, [rv])
                    # 「始终允许」按卡片上选的范围落盘：默认只记当前实例，选了全局进 global
                    scope_inst = None if getattr(rv, "scope", "") == permission.SCOPE_GLOBAL \
                        else instance_name
                    permission.append_rule(rv, scope_inst)
                    decisions[obj.id] = ("allow", "")
                elif not rv:
                    decisions[obj.id] = ("deny", "用户拒绝了这次操作")
                    turn.set_tool_status(obj.id, ToolCallStatus.DENIED,
                                         result="用户拒绝了这次操作")
                    _status("tool_skip", {"name": obj.name, "label": label})
                else:
                    decisions[obj.id] = ("allow", "")

            turn.transition(TurnPhase.EXECUTING_TOOLS)

            def _execute(obj: ToolCall) -> str:
                try:
                    _check()
                    turn.set_tool_status(obj.id, ToolCallStatus.RUNNING)
                    chat_store.log_event(session_id, "ToolStarted",
                                         turn_id=turn.id, round=round_no[0],
                                         tool=obj.name, tool_call_id=obj.id)
                    meta = TOOL_META.get(obj.name)
                    label = confirm_label(obj.name, obj.args)
                    _status("tool_run", {"name": obj.name, "label": label})
                    wait = not (meta and (meta.long_running or meta.side_effect == "launch"))
                    result = run_tool(backend, obj.name, obj.args, wait=wait,
                                      cancelled=cancelled)
                    if meta and not meta.readonly:
                        try:
                            parsed = json.loads(result) if isinstance(result, str) \
                                and result.startswith("{") else {}
                            if isinstance(parsed, dict) and parsed.get("task_id") \
                                    and parsed.get("queued"):
                                pending.append({"task_id": parsed["task_id"],
                                                "name": obj.name})
                        except Exception:  # noqa: BLE001
                            pass
                    _status("tool_done", {"name": obj.name, "label": label,
                                          "result": str(result)[:400]})
                    turn.set_tool_status(obj.id, ToolCallStatus.COMPLETED,
                                         result=str(result))
                    chat_store.log_event(session_id, "ToolCompleted",
                                         turn_id=turn.id, round=round_no[0],
                                         tool=obj.name, tool_call_id=obj.id,
                                         result_len=len(str(result)))
                    return str(result)
                except ToolCancelled:
                    turn.set_tool_status(obj.id, ToolCallStatus.FAILED, error="已停止")
                    raise
                except Exception as exc:  # noqa: BLE001
                    turn.set_tool_status(obj.id, ToolCallStatus.FAILED, error=str(exc))
                    chat_store.log_event(session_id, "ToolFailed",
                                         turn_id=turn.id, round=round_no[0],
                                         tool=obj.name, error=str(exc)[:200])
                    return f"工具失败: {exc}"

            runnable = [obj for obj in tool_objs if decisions[obj.id][0] == "allow"]
            groups = scheduler.group(runnable, TOOL_META, max_concurrency=4)
            turn.parallel_groups = [[tc.id for tc in grp] for grp in groups]
            scheduler.run_groups(groups, _execute, max_concurrency=4)

            for obj in tool_objs:
                messages.append({
                    "role": "tool",
                    "tool_call_id": obj.id,
                    "name": obj.name,
                    "content": obj.result or "",
                })
            turn.transition(TurnPhase.AWAITING_MODEL)
            cstate.tool_turns_since_compact += 1
    except AgentCancelled:
        _to_phase(turn, TurnPhase.COMPLETING)
        chat_store.log_event(session_id, "TurnFailed", turn_id=turn.id,
                             rounds=turn.rounds_used, reason="cancelled")
        raise
    except ToolCancelled as exc:
        # 工具中途被打断：对 UI 而言就是用户点了停止
        _to_phase(turn, TurnPhase.COMPLETING)
        chat_store.log_event(session_id, "TurnFailed", turn_id=turn.id,
                             rounds=turn.rounds_used, reason="cancelled")
        raise AgentCancelled() from exc
    except AIClientError:
        _to_phase(turn, TurnPhase.ERROR)
        chat_store.log_event(session_id, "TurnFailed", turn_id=turn.id,
                             rounds=turn.rounds_used, reason="error")
        raise
    finally:
        trace.record("turn_end", round_=turn.rounds_used, phase=turn.phase.value,
                     text_len=len(final))
        if turn.phase == TurnPhase.COMPLETING:
            chat_store.log_event(session_id, "TurnCompleted", turn_id=turn.id,
                                 rounds=turn.rounds_used)

    trace.record("max_rounds", round_=MAX_TOOL_ROUNDS, text_len=len(final))
    _to_phase(turn, TurnPhase.COMPLETING)
    return _result(
        _full(final) or "步骤有点多，先停在这里。你再说一下接下来要哪一步。",
        StopReason.MAX_ROUNDS,
        detail=f"已用 {turn.rounds_used}/{MAX_TOOL_ROUNDS} 回合",
        pending_tasks=pending,
        rounds_used=turn.rounds_used,
    )
