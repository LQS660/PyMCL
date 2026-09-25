# -*- coding: utf-8 -*-
"""Agent 主循环：turn 状态机 + 流式模型调用 + 工具并行调度 + 权限判权。"""

from __future__ import annotations

import inspect
import json
import random
import re
import time
import uuid

from mclauncher.i18n import tr

from . import compact
from . import checkpoint
from . import hooks as hook_mod
from . import mcp as mcp_mod
from . import memory as memory_mod
from . import permission
from . import scheduler
from . import store as chat_store
from . import tokens as tokens_mod
from . import trace
from . import usage as usage_mod
from .client import AIClientError, chat_once, chat_stream, is_context_overflow
from .defaults import (
    MAX_HISTORY, MAX_TOOL_ROUNDS, MAX_TOOL_ROUNDS_SUBAGENT,
)
from .permission import Behavior, Decision, Rule
from .prompt import system_prompt
from .result import AgentResult, StopReason
from .state import IllegalTransition, ToolCall, ToolCallStatus, TurnPhase, TurnState
from .tools import (
    TOOL_META, TOOL_SCHEMAS, ToolCancelled, affected_paths, confirm_label, is_ask_tool,
    normalize_ask_answer, normalize_ask_args, parse_args, run_tool, runtime_context,
    select_tool_schemas, tool_error_payload, ToolErrorCode,
)


class AgentCancelled(Exception):
    pass


def _is_compact_msg(m) -> bool:
    """压缩摘要消息（autocompact 的 compact_<idx> / 截断摘要的 compact_h<len>）。"""
    return isinstance(m, dict) and bool(str(m.get("id") or "").startswith("compact_"))


def _drop_orphan_tool_head(msgs: list) -> list:
    """切片不能从孤立的 tool 消息开始（它前面的 assistant.tool_calls 被切掉了）。"""
    i = 0
    while i < len(msgs) and isinstance(msgs[i], dict) \
            and msgs[i].get("role") == "tool":
        i += 1
    return msgs[i:]


def _trim_history(history: list, summarize=None) -> tuple:
    """裁剪上一轮历史：超过 MAX_HISTORY 的头部换成一条摘要消息放回保留区开头。

    静默切片是跨回合失忆的真正来源：被切掉的头部一步一丢、没有任何补偿。
    summarize 传入时，被裁部分（连同已滑出窗口的上一条摘要，摘要的摘要）
    总结成一条 [历史摘要] 消息；请求失败退回旧行为（静默截断），绝不阻断回合。
    返回 (保留区, 摘要消息或 None)。
    """
    history = list(history or [])
    if len(history) <= MAX_HISTORY:
        return _drop_orphan_tool_head(history), None
    dropped = history[:-MAX_HISTORY]
    kept = history[-MAX_HISTORY:]
    kept = _drop_orphan_tool_head(kept)
    if summarize is None:
        return kept, None
    prev_idx = -1
    for idx, m in enumerate(dropped):
        if _is_compact_msg(m):
            prev_idx = idx
    prev = dropped[prev_idx] if prev_idx >= 0 else None
    if prev_idx >= 0:
        fresh = [m for m in dropped[prev_idx + 1:] if not _is_compact_msg(m)]
    else:
        fresh = [m for m in dropped if not _is_compact_msg(m)]
    if prev is not None and not fresh:
        # 被裁段里没有新内容：复用上一条摘要，不重复花一次摘要请求
        return kept, dict(prev)
    if not fresh:
        return kept, None
    try:
        summary = summarize(([prev] if prev is not None else []) + fresh)
    except AgentCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        trace.record("history_trim_summary_failed", exc=exc, dropped=len(dropped))
        return kept, None
    if not (summary or "").strip():
        return kept, None
    return kept, {
        "role": "user",
        "content": f"[历史摘要]\n{summary.strip()}\n（以上是更早对话的摘要，继续当前任务。）",
        "id": f"compact_h{len(history)}",
    }


def _current_instance() -> str:
    try:
        from mclauncher.config import CONFIG
        return CONFIG.get("default_instance", "default") or "default"
    except Exception:  # noqa: BLE001
        return "default"


# wait_task 超时的哨兵原文；两端 wait_task 现在都带 timeout=True，这里是老后端的兜底
_WAIT_TIMEOUT_KEY = "等待任务超时"


def _task_still_running(res) -> bool:
    """wait_task 的返回是「还在跑」还是「已出结果」。

    以前只认 `msg == "等待任务超时"` 这一句中文，英文界面下 wait_task 回的是
    tr() 过的译文，长任务被当成失败摘出 pending、模型收到「失败」，实际任务还在跑。
    """
    if not isinstance(res, dict):
        return True
    if res.get("timeout") or res.get("running"):
        return True
    if res.get("ok") is None:
        return True
    msg = str(res.get("message") or "")
    return msg == _WAIT_TIMEOUT_KEY or msg == tr(_WAIT_TIMEOUT_KEY)


def _summary_input(slice_messages, limit: int = 60000) -> str:
    """压缩摘要的输入：控制体量但别把 JSON 切在中间。

    单条过长的内容先截，整体仍超限就从第二条起丢最早的（第一条通常是用户最初
    的诉求，摘要提示词要求保留它）。
    """
    rows = []
    for m in slice_messages or []:
        if not isinstance(m, dict):
            continue
        row = {"role": m.get("role")}
        content = m.get("content")
        if isinstance(content, str) and len(content) > 4000:
            content = content[:4000] + "…(已截断)"
        row["content"] = content
        if m.get("name"):
            row["name"] = m.get("name")
        calls = []
        for tc in m.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            calls.append({"name": fn.get("name"),
                          "arguments": str(fn.get("arguments") or "")[:500]})
        if calls:
            row["tool_calls"] = calls
        rows.append(row)
    text = json.dumps(rows, ensure_ascii=False)
    while len(text) > limit and len(rows) > 2:
        rows.pop(1)
        text = json.dumps(rows, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit]


def _system_messages(backend, settings: dict) -> list:
    ctx = runtime_context(backend)
    msgs = [
        {"role": "system", "content": system_prompt()},
        {"role": "system", "content": "当前启动器状态：\n" + ctx},
    ]
    note = permission.permission_note(settings or {})
    if note:
        msgs.append({"role": "system", "content": note})
    # 3.5 长期记忆插槽：默认 NoopMemory 返回空串，不追加任何消息——
    # 启用与否模型请求逐字一致（空实现一致性由 tests 钉死）
    try:
        mem_text = memory_mod.get_memory().load(str((settings or {}).get("ai_session_id") or "active"))
    except Exception:  # noqa: BLE001
        mem_text = ""
    if mem_text:
        msgs.append({"role": "system", "content": f"长期记忆：\n{mem_text}"})
    # 调用方注入的隐藏上下文（「交给 AI 修复」小窗的崩溃报告）：只进模型请求，
    # 不入库、不出现在对话 UI；放最末尾，紧挨着对话内容。不设置时请求逐字不变。
    extra = str((settings or {}).get("ai_extra_context") or "").strip()
    if extra:
        msgs.append({"role": "system", "content": extra})
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


# ---- 跨回合压缩状态（原 CompactState 每回合新建，rapid-refill 熔断永远攒不起来）----
_COMPACT_STATES: dict = {}
# 上一回合结束时刻：microcompact 闲置触发的真实时钟（进程内，多端共用无害）
_LAST_ACTIVITY = {"ts": 0.0}


def _compact_state_for(session_id: str) -> compact.CompactState:
    st = _COMPACT_STATES.get(session_id)
    if st is None:
        # 会话数有限（store 上限 40 条对话）；超限整表清一次，状态只是熔断
        # 计数不是正确性数据，丢了也只是重新攒
        if len(_COMPACT_STATES) >= 16:
            _COMPACT_STATES.clear()
        st = compact.CompactState()
        _COMPACT_STATES[session_id] = st
    return st


# ---- 「只回了文字」到底算不算没干活 -------------------------------------
# NO_TOOL_CALL 原来的口径是「一轮下来没调过工具」，于是「你好」「1.20.1 有啥新东西」
# 这类本来就该用文字回答的回合也被打成没动手，三端都弹「它没有真的开始执行」。
# 这里按用户那句话判：要求下载 / 安装 / 改配置这类得调工具才办得到的事，模型却
# 光说话，才是真的没动手；问答、闲聊回文字就是完成。模型嘴上说「已经装好了」
# 而工具轨迹是空的，也算没动手——那是在编。
# 动作词表只留真操作（下载/安装/改…）。「帮我 / 给我 / 替我」只是委婉语气，
# 不再单独构成派活——否则「帮我看看这是什么意思」会被当成动手请求（历史误伤）。
_ACTION_RE = re.compile(
    r"下载|安装|重装|卸载|装(?:个|一下|上|好|到|进|下)|删(?:除|掉|了|个|一下)|移除"
    r"|清(?:理|掉|空|一下)|修(?:复|好|一下|下)|修改|改(?:成|为|一下|下|掉|到|个)"
    r"|设(?:置|成|为|定|到)|配置|调(?:成|到|整|一下|大|小|高|低)|换(?:成|到|个|一下)"
    r"|切(?:换|到|成)|开(?:启|一下|下)|关(?:闭|掉|上|一下)|打开|启动|运行|跑(?:一下|起来|个)"
    r"|导入|导出|更新|升级|备份|恢复|还原|重启|添加|加(?:个|上|一下|进|到)|新建|创建"
    r"|重命名|迁移|干活|搞定|弄(?:好|一下|个)|试试|继续|开始|执行|动手"
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
# 纯观察词：剥掉之后再判动作。「帮我看看这是什么意思」剥掉「看看」就没有动作词了。
_OBSERVE_RE = re.compile(r"看(?:看|下|一下|一?眼)?|瞧(?:瞧|下|一下)?|瞅(?:瞅|下|一下)?")
# 诊断对象：「帮我看下崩溃」这类句子没有操作动词，但模型必须调工具查日志才算数，
# 仍按派活处理（只回文字照样打 NO_TOOL_CALL）。
_DIAGNOSE_RE = re.compile(
    r"报错|崩溃|日志|闪退|起不来|打不开|蓝屏|错误|异常|排查|哪里出了|什么问题")
_CLAIM_RE = re.compile(
    r"(?:已经?|正在|马上|现在)(?:帮你|为你|给你)?(?:开始)?"
    r"(?:下载|安装|重装|卸载|删除|移除|清理|修复|修改|设置|配置|调整|切换|开启|关闭|打开"
    r"|启动|导入|导出|更新|升级|备份|恢复|重启|添加|创建|重命名|迁移)"
    r"|(?:下载|安装|删除|清理|修复|修改|设置|切换|导入|导出|更新|升级|备份|恢复|添加)"
    r"(?:完成|好了|成功|完毕)"
    # 「我打算把 ××× 删除」这类意图句（2026-09-25 实测：模型说了要删却没调工具，
    # 上游还把话说一半就 EOS——不认意图就会静默降级成「正常完成」）
    r"|(?:打算|准备|即将|计划|这就(?:去|开始)|接下来我?(?:会|要|将)|我(?:会|要|将)(?:先|直接|把)?)"
    r"(?:[^。！？\n]{0,80}?)?"
    r"(?:下载|安装|重装|卸载|删除|删掉|移除|禁用|启用|清理|修复|修改|设置|配置|调整|切换"
    r"|开启|关闭|打开|启动|导入|导出|更新|升级|备份|恢复|重启|添加|创建|新建|重命名|迁移)"
    r"|\bI(?:'ve| have) (?:installed|downloaded|removed|deleted|updated|set|changed|configured"
    r"|enabled|disabled|fixed|added|created)\b"
    r"|\b(?:installing|downloading|removing|updating|configuring) (?:it|now|the)\b"
    r"|\bI(?:'ll| will) (?:install|download|remove|delete|disable|enable|fix|set|change|update)\b",
    re.IGNORECASE,
)


def wants_action(user_text: str) -> bool:
    """用户这句话是不是在要求动手（得调工具才办得到的事）。

    带动作词才算；带动作词但整句是个问法（怎么 / 什么 / 吗 / ？）且没有
    「帮我 / 请 / 把」这类派活语气的，按提问处理。
    「帮我看看…」这种纯观察句（剥掉看/瞧/瞅后没有动作词）不算派活，除非
    指明了诊断对象（崩溃 / 日志 / 报错）——那类必须调工具才答得出。
    """
    text = (user_text or "").strip()
    if not text:
        return False
    if not _ACTION_RE.search(_OBSERVE_RE.sub("", text)):
        return bool(_DELEGATE_RE.search(text) and _DIAGNOSE_RE.search(text))
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

    session_id = str((settings or {}).get("ai_session_id") or "active")

    def _summarize(slice_messages) -> str:
        # 压缩 / 截断摘要会再发一次模型请求，必须尊重停止信号
        _check()
        prompt = [
            {"role": "system", "content": compact._SUMMARY_PROMPT},
            {"role": "user", "content": _summary_input(slice_messages)},
        ]
        data = chat_once(settings, prompt, None, http_cancel=http_cancel)
        _check()
        return data.get("content") or ""

    kept_history, trim_summary = _trim_history(history, _summarize)
    messages = _system_messages(backend, settings)
    if trim_summary is not None:
        messages.append(trim_summary)
        _status("compact", {"reason": "history_trim"})
    messages += kept_history
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
    auto_cfg = compact.auto_config_from_settings(settings)
    # micro 阈值从 autocompact 阈值派生：先清旧工具结果，实在不行再全量总结
    micro_cfg = compact.MicroConfig(
        threshold_tokens=max(4_000, compact.auto_threshold(auto_cfg) - 16_000))
    cstate = _compact_state_for(session_id)
    # rapid-refill / 工具轮计数跨回合存活（熔断跨回合才有效）；压缩连续失败
    # 每回合原谅一次：网关抖动不该把本会话的自动压缩永久关掉
    cstate.consecutive_failures = 0
    # ③ microcompact 闲置触发：距上一回合结束的真实间隔（原来是写死的 0.0，死路径）
    idle_seconds = 0.0
    if _LAST_ACTIVITY["ts"] > 0:
        idle_seconds = max(0.0, time.time() - _LAST_ACTIVITY["ts"])
    token_state = tokens_mod.TokenState()
    usage_got = [False]   # 本 step 是否已拿到真实 usage（没拿到才在 step 末尾记一次估算）

    def _force_compact(round_: int) -> bool:
        """reactive compact：上游报「塞不下」时强制压缩，成功返回 True。"""
        nonlocal token_state
        try:
            cres = compact.compact_conversation(messages, auto_cfg, _summarize)
        except AgentCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            compact.note_compact_failure(cstate, auto_cfg)
            trace.record("reactive_compact_failure", round_=round_, exc=exc)
            return False
        messages[:] = cres.messages
        # 压缩后消息集完全变了：token 基线指着旧消息下标，不重置会在
        # 消息数涨回旧下标之后拿「旧基数 + 新消息」严重高估，连环误触发压缩
        token_state = tokens_mod.TokenState()
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
            if _task_still_running(res):
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

    # ---- 用量采集（2.3）：真实 usage 进 trace 与事件日志；公益网关拿不到就保持估算 ----
    def _record_usage(usage: dict, n_req: int) -> None:
        usage = usage or {}
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        if prompt <= 0 and completion <= 0:
            return
        details = usage.get("prompt_tokens_details") or {}
        cached = int((details or {}).get("cached_tokens") or 0)
        if prompt > 0:
            usage_got[0] = True
        tokens_mod.update_from_usage(token_state, usage, n_req)
        usage_mod.add(session_id, usage)
        trace.record("usage", prompt_tokens=prompt, completion_tokens=completion,
                     cached_tokens=cached)
        chat_store.log_event(session_id, "Usage", turn_id=turn.id,
                             prompt_tokens=prompt, completion_tokens=completion,
                             cached_tokens=cached, source="provider")

    # ---- 模型降级（2.4）：主模型连续 429/5xx → 备用模型完成本回合；未配置则原样 ----
    fallback_model = str((settings or {}).get("ai_fallback_model") or "").strip()
    fallback_active = [False]

    # ---- 3.4 计划工作流：模型出的结构化待办 + plan 档批准门禁 ----
    plan_holder = {"items": [], "turn_id": "", "approved": False}

    # ---- 6.2 回合埋点：停止原因/轮数/工具调用数/失败数/耗时 ----
    turn_started_at = time.monotonic()
    tool_counts = {"calls": 0, "failures": 0}

    def _maybe_fallback(exc: AIClientError) -> bool:
        if not fallback_model or fallback_active[0]:
            return False
        if exc.status not in (429, 500, 502, 503, 504) \
                and exc.category != "rate_limited":
            return False
        fallback_active[0] = True
        _status("model_fallback", {"model": fallback_model,
                                   "error": str(exc)[:160]})
        trace.record("model_fallback", round_=round_no[0], model=fallback_model, exc=exc)
        chat_store.log_event(session_id, "ModelFallback", turn_id=turn.id,
                             model=fallback_model, error=str(exc)[:160])
        return True

    def _request_settings() -> dict:
        if fallback_active[0]:
            return dict(settings or {}, ai_model=fallback_model)
        return settings or {}

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
        # 用量口径给 UI：provider_usage = 真实回执；estimate = 公益网关拿不到 usage 的估算
        res.usage_source = token_state.source
        res.usage = usage_mod.get(session_id)
        # 6.2 回合摘要：一次回合只记一条，进 trace 与事件日志（本地聚合视图用）
        if not getattr(res, "_summary_recorded", False):
            res._summary_recorded = True
            elapsed = round(time.monotonic() - turn_started_at, 2)
            trace.record("turn_summary", stop_reason=reason.value,
                         rounds=round_no[0], tools=tool_counts["calls"],
                         tool_failures=tool_counts["failures"], elapsed=elapsed)
            chat_store.log_event(session_id, "TurnSummary", turn_id=turn.id,
                                 stop_reason=reason.value, rounds=round_no[0],
                                 tools=tool_counts["calls"],
                                 tool_failures=tool_counts["failures"],
                                 elapsed=elapsed)
        # 3.4 本回合最新的待办计划（UI 持久化用）
        res.plan = list(plan_holder["items"]) if plan_holder["turn_id"] == turn.id else []
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
            # 局部名用 turn_slice，别遮蔽外层的 TurnState（plan 归属判定要用 turn.id）
            if compacted[0]:
                # 压缩摘要必须活过回合结束：把它带进持久化切片，否则下一轮模型
                # 从历史里读不到本回合做过什么（原来只落 [用户这句, 最终正文]，
                # 压缩白做）。保留区里更早回合的旧消息不再抄一遍——UI 侧区分
                # 不了新旧，抄进去就是重复入库。
                turn_slice = [{"role": "user", "content": user_text}]
                turn_slice += [dict(m) for m in messages if _is_compact_msg(m)]
            else:
                turn_slice = [dict(m) for m in messages[base_len:]
                              if isinstance(m, dict) and m.get("role") != "system"]
                # 截断摘要同样入库（UI 会插在用户这句之前），下一轮被裁段里
                # 找得到它就复用，不必每回合重新摘要
                if trim_summary is not None:
                    turn_slice.insert(0, dict(trim_summary))
            if text and (not turn_slice
                         or turn_slice[-1].get("role") != "assistant"
                         or turn_slice[-1].get("tool_calls")):
                turn_slice.append({"role": "assistant", "content": str(text)})
            res.turn_messages = turn_slice
        except Exception:  # noqa: BLE001
            res.messages = []
            res.turn_messages = []
        return res

    # 子代理宣称「只读、不写磁盘」：绝不能把 MCP 外部工具（能力未知）追加进
    # 它的工具集，也不再为它起一整套 MCP 子进程
    is_subagent = bool((settings or {}).get("ai_subagent"))
    checkpoint.begin_chat(session_id)
    # 3.1 工具 hooks：settings 一键总闸（默认开），关闭后透传、行为与无 hook 一致
    hook_mod.set_enabled(bool((settings or {}).get("ai_hooks_enabled", True)))
    # 3.2 MCP：配置了 server 才连；坏 server 只记 trace，绝不影响内置工具
    if is_subagent:
        mcp_clients, mcp_schemas = [], []
    else:
        try:
            mcp_clients = mcp_mod.connect_servers(settings)
            mcp_schemas = mcp_mod.mcp_tool_schemas(mcp_clients)
        except Exception as exc:  # noqa: BLE001
            trace.record("mcp_setup_failed", exc=exc)
            mcp_clients, mcp_schemas = [], []
    chat_store.log_event(session_id, "TurnStarted", turn_id=turn.id,
                         user_len=len(user_text or ""))

    try:
        turn.transition(TurnPhase.PROCESSING_INPUT)
        # 3.3 子代理用独立轮数上限（MAX_TOOL_ROUNDS_SUBAGENT），主循环保持 MAX_TOOL_ROUNDS
        max_rounds = int((settings or {}).get("ai_max_rounds") or 0) or MAX_TOOL_ROUNDS
        # 2.2 按需声明：核心集 + 关键词扩展；模型想调没声明的工具时全量重发一次
        # （回合级只重发一次，schema_override 放循环外，别每轮都重置）
        schema_override: list | None = None
        schemas: list = TOOL_SCHEMAS
        for _round in range(max_rounds):
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
                    extra += f"\n\n[进度] 本轮已用 {round_no[0]}/{max_rounds} 步。"
                    if max_rounds - round_no[0] < 4:
                        extra += "剩余不足 4 步时请优先收尾并说明当前状态。"
                if continuation_pending:
                    extra += ("\n用户刚在选项里做出选择：若需要执行操作，"
                              "请立刻调用对应工具；若无需操作，请说明原因。")
                    # 只提醒紧接着的这一次模型调用；之前从不复位，ask 之后的每一轮
                    # （哪怕已经跑了十几轮工具）都还挂着「请立刻调用工具」。
                    continuation_pending = False
                messages[1]["content"] = state_base + extra

            _status("think", {"after_tools": any(m.get("role") == "tool" for m in messages)})

            # ---- 上下文管理：先试两级压缩，再发模型请求 ----
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
                    # 同 _force_compact：压缩后 token 基线必须重置（见其注释）
                    token_state = tokens_mod.TokenState()
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
            else:
                # microcompact 自己判触发（token 过阈值或闲置超时）：闲置清理
                # 必须不依赖 token 阈值才成立——离开 30 分钟回来，没到阈值也该清
                mres = compact.microcompact(messages, micro_cfg, 0.0, 0.0,
                                            idle_seconds=idle_seconds)
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
            usage_got[0] = False
            for _attempt in range(6):
                tool_calls = []
                text_parts = []
                truncated = False
                stream_failed = False
                schemas = schema_override or select_tool_schemas(messages, settings)
                if mcp_schemas:
                    schemas = list(schemas) + [s for s in mcp_schemas
                                               if s not in schemas]
                n_req = len(messages)
                usage_info = None
                stream_err = ""
                chat_store.log_event(session_id, "ModelRequest",
                                     turn_id=turn.id, round=round_no[0],
                                     attempt=_attempt, msg_count=n_req,
                                     tools=len(schemas))
                try:
                    for ev in chat_stream(_request_settings(), messages, schemas, http_cancel=http_cancel):
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
                    if _maybe_fallback(exc):
                        continue
                    stream_failed = True
                    stream_err = str(exc)
                    trace.record("stream_error", round_=round_no[0], exc=exc, stream_failed=True)
                except Exception as exc:  # noqa: BLE001
                    stream_failed = True
                    stream_err = str(exc)
                    trace.record("stream_exception", round_=round_no[0], exc=exc, stream_failed=True)
                if usage_info:
                    _record_usage(usage_info, n_req)

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
                        data = chat_once(_request_settings(), messages, TOOL_SCHEMAS,
                                         http_cancel=http_cancel)
                    except AIClientError as exc:
                        if exc.fatal():
                            raise
                        if is_context_overflow(str(exc)) and not reactive_attempted:
                            reactive_attempted = True
                            if _force_compact(round_no[0]):
                                continue
                        if _maybe_fallback(exc):
                            continue
                        raise
                    if isinstance(data.get("usage"), dict) and data["usage"]:
                        _record_usage(data["usage"], len(messages))
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

            # 整个 step（含重试与非流式兜底）都没拿到真实 usage：只记一次估算。
            # 原来每个失败 attempt 都各记一次，重试越多会话用量越虚高。
            if not usage_got[0]:
                usage_mod.add(session_id, None,
                              estimated_input=tokens_mod.estimate_messages(messages))

            content = "".join(text_parts)
            if content:
                final = content

            # 2.2 兜底：模型调了没声明的工具 → 全量 schema 重发一次，绝不让调用悬空
            if tool_calls and schema_override is None:
                declared = {s["function"]["name"] for s in schemas}
                if any((tc.get("function") or {}).get("name") not in declared
                       for tc in tool_calls):
                    schema_override = select_tool_schemas(messages, settings,
                                                           force_all=True)
                    trace.record("tool_schema_miss",
                                 tools=[(tc.get("function") or {}).get("name")
                                        for tc in tool_calls])
                    # 回合级 continue 前把状态机拨回 AWAITING_MODEL，
                    # 否则下一轮顶部 STREAMING→STREAMING 是非法迁移
                    turn.transition(TurnPhase.SCHEDULING_TOOLS)
                    turn.transition(TurnPhase.EXECUTING_TOOLS)
                    turn.transition(TurnPhase.AWAITING_MODEL)
                    continue

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
                        _full(content) + "\n\n" + tr("（回复被长度限制截断了，需要的话让我继续。）"),
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
            parse_errors: dict = {}
            for i, tc in enumerate(tool_calls):
                fn = tc.get("function") or {}
                parsed_args, parse_err = parse_args(fn.get("arguments"), fn.get("name") or "")
                obj = turn.add_tool_call(ToolCall(
                    id=tc["id"],
                    name=fn.get("name") or "",
                    args=parsed_args))
                if parse_err:
                    parse_errors[obj.id] = parse_err
                tool_objs.append(obj)

            # 判权：deny/modify 直接定，ask 稍后集中处理（可能弹 UI）
            # 3.1 前置钩子必须在判权之前跑：钩子改写后的入参才是被授权、被确认、
            # 被快照、被执行的——否则用户批的是旧参数、实际跑的是新参数
            needs_perm = False
            decisions: dict = {}
            for obj in tool_objs:
                if obj.id not in parse_errors:
                    hooked_args, hb_errs = hook_mod.run_before(obj.name, obj.args)
                    if hb_errs:
                        trace.record("hook_errors", tool_name=obj.name,
                                     phase="before", count=len(hb_errs))
                    obj.args = hooked_args
                _status("tool", {"name": obj.name, "args": obj.args,
                                 "label": confirm_label(obj.name, obj.args)})
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
                elif meta is None and obj.name.startswith("mcp_") \
                        and res.decision == Decision.ALLOW and not res.rule_id \
                        and mode not in (permission.PermissionMode.YOLO,
                                         permission.PermissionMode.BYPASS_PERMISSIONS):
                    # 外部 MCP 工具的读写能力未知：acceptEdits/build 这类
                    # 「自动接受本地编辑」的档位不能顺带放行外部 server 的工具，
                    # 逐次确认（yolo 按其语义仍然直接放行；显式 allow 规则仍有效）
                    decisions[obj.id] = ("ask", "外部 MCP 工具能力未知，需确认")
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
                if not is_ask_tool(obj.name) and confirm_fn is None and is_subagent:
                    # 子代理没有确认通道：需要确认的操作一律拒绝，不能把
                    # ASK 静默当 ALLOW——那等于子代理自带无人把关的写权限。
                    # （主代理无 confirm_fn 的无头场景保持旧行为：视为允许）
                    decisions[obj.id] = ("deny", "子代理无交互确认通道，需要确认的操作已拒绝")
                    turn.set_tool_status(obj.id, ToolCallStatus.DENIED,
                                         result="[权限] 子代理无确认通道，已拒绝")
                    _status("tool_skip", {"name": obj.name, "label": label})
                    continue
                turn.set_tool_status(obj.id, ToolCallStatus.WAITING_PERMISSION)
                if is_ask_tool(obj.name):
                    questions = normalize_ask_args(obj.args)
                    title = obj.args.get("title") or ""
                    answered = ask_fn(questions, title) if ask_fn else None
                    # Qt / WPF 两端应答形状不同，统一成一种再给模型（见 normalize_ask_answer）
                    answered = normalize_ask_answer(questions, answered)
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
                        _status("tool_done", {"name": obj.name, "label": tr("已选择"),
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
                # 5.1 参数不合 schema：给模型结构化回执，绝不用空参数静默执行
                if obj.id in parse_errors:
                    err = parse_errors[obj.id]
                    trace.record("tool_bad_args", tool_name=obj.name, detail=err[:200])
                    payload = tool_error_payload(ValueError(err), obj.name,
                                                 code=ToolErrorCode.BAD_ARGUMENTS)
                    turn.set_tool_status(obj.id, ToolCallStatus.FAILED,
                                         error=err, result=payload)
                    return payload
                try:
                    _check()
                    turn.set_tool_status(obj.id, ToolCallStatus.RUNNING)
                    chat_store.log_event(session_id, "ToolStarted",
                                         turn_id=turn.id, round=round_no[0],
                                         tool=obj.name, tool_call_id=obj.id)
                    meta = TOOL_META.get(obj.name)
                    label = confirm_label(obj.name, obj.args)
                    _status("tool_run", {"name": obj.name, "label": label})
                    tool_counts["calls"] += 1
                    # 写/删落盘前先打检查点（变更可逆性）：快照失败不阻断本操作，
                    # 但这一轮标记为不可回滚并明确告警
                    if meta and meta.side_effect in ("write_local", "delete"):
                        snap = checkpoint.snapshot(
                            session_id, turn.id,
                            affected_paths(backend, obj.name, obj.args))
                        if not snap.get("ok"):
                            _status("checkpoint_warn", {
                                "name": obj.name,
                                "message": tr("检查点不可用（{reason}），本轮改动无法一键撤回")
                                           .format(reason=snap.get("reason") or "")})
                            trace.record("checkpoint_unavailable", tool_name=obj.name,
                                         reason=str(snap.get("reason") or ""))
                    wait = not (meta and (meta.long_running or meta.side_effect == "launch"))
                    # 3.1 前置钩子已提前到判权之前跑（改写后的入参才是被授权/被快照的）；
                    # 这里只负责执行。后置钩子照旧在结果产出后跑
                    if obj.name == "update_plan":
                        # 3.4 计划工作流：结构化待办进 UI，不落任何后端操作
                        items = [it for it in (obj.args.get("items") or [])
                                 if isinstance(it, dict) and str(it.get("title") or "").strip()]
                        plan_holder["items"] = items
                        plan_holder["turn_id"] = turn.id
                        plan_holder["approved"] = False
                        _status("plan", {"items": items, "turn_id": turn.id})
                        result = tr("已更新计划（共 {0} 项）").format(len(items))
                    elif obj.name == "dispatch_subagent":
                        # 3.3 子代理：独立轮数上限、只读工具、结构化结论回主对话
                        result = run_subagent(backend, settings, obj.args,
                                              cancelled=cancelled)
                    elif obj.name.startswith("mcp_"):
                        # 3.2 MCP 工具调用：失败返回结构化错误给模型，不影响内置工具
                        try:
                            result = mcp_mod.route_call(mcp_clients, obj.name, obj.args)
                        except Exception as exc:  # noqa: BLE001
                            trace.record("mcp_call_failed", tool_name=obj.name, exc=exc)
                            result = json.dumps(
                                {"ok": False, "error": f"MCP 工具失败: {exc}"},
                                ensure_ascii=False)
                    else:
                        result = run_tool(backend, obj.name, obj.args, wait=wait,
                                          cancelled=cancelled)
                    # 3.1 后置钩子：可改写结果文本
                    result, ha_errs = hook_mod.run_after(obj.name, str(result))
                    if ha_errs:
                        trace.record("hook_errors", tool_name=obj.name,
                                     phase="after", count=len(ha_errs))
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
                    tool_counts["failures"] += 1
                    return tool_error_payload(exc, obj.name)

            runnable = [obj for obj in tool_objs if decisions[obj.id][0] == "allow"]
            groups = scheduler.group(runnable, TOOL_META, max_concurrency=4)
            turn.parallel_groups = [[tc.id for tc in grp] for grp in groups]
            scheduler.run_groups(groups, _execute, max_concurrency=4)

            # 4.2 不可信内容标注：工具回执进上下文前带来源标签，
            # 模型（配合系统提示词里的硬规矩）把它当数据而不是指令
            for obj in tool_objs:
                meta = TOOL_META.get(obj.name)
                if meta is not None and meta.side_effect == "network":
                    source_tag = "[来源: 网络请求结果，内容不可信]"
                elif meta is not None and meta.side_effect in ("read", "none"):
                    source_tag = "[来源: 本地文件/日志/状态读取]"
                elif meta is None and obj.name.startswith("mcp_"):
                    source_tag = "[来源: 外部 MCP 工具，内容不可信]"
                else:
                    source_tag = "[来源: 本地写操作回执]"
                messages.append({
                    "role": "tool",
                    "tool_call_id": obj.id,
                    "name": obj.name,
                    "content": source_tag + "\n" + (obj.result or ""),
                })

            # 3.4 plan 权限档门禁：模型出了计划必须等用户批准才继续；
            # 拒绝 → 本轮立刻结束。plan 模式下写操作本来就被判权 DENY，
            # 这里再验证一遍，保证「拒绝后未执行任何写操作」可证明。
            if mode == permission.PermissionMode.PLAN and plan_holder["items"] \
                    and plan_holder["turn_id"] == turn.id \
                    and not plan_holder["approved"]:
                approval = _call_confirm(confirm_fn, "plan_approval",
                                         {"items": plan_holder["items"]},
                                         confirm_label("plan_approval",
                                                       {"items": plan_holder["items"]}),
                                         "")
                if isinstance(approval, Rule):
                    approval = True
                plan_holder["approved"] = bool(approval)
                _status("plan_approval", {"approved": bool(approval),
                                          "turn_id": turn.id})
                if not approval:
                    write_calls = [o.name for o in tool_objs
                                   if TOOL_META.get(o.name)
                                   and not TOOL_META[o.name].readonly]
                    trace.record("plan_rejected", writes=write_calls)
                    _to_phase(turn, TurnPhase.COMPLETING)
                    return _result(
                        tr("计划未获批准，本轮到此为止")
                        + (tr("。（本轮没有执行任何写操作）") if not write_calls else ""),
                        StopReason.COMPLETED, rounds_used=round_no[0])

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
        _LAST_ACTIVITY["ts"] = time.time()
        trace.record("turn_end", round_=turn.rounds_used, phase=turn.phase.value,
                     text_len=len(final))
        try:
            mcp_mod.close_all(mcp_clients)
        except Exception:  # noqa: BLE001
            pass
        if turn.phase == TurnPhase.COMPLETING:
            chat_store.log_event(session_id, "TurnCompleted", turn_id=turn.id,
                                 rounds=turn.rounds_used)

    trace.record("max_rounds", round_=max_rounds, text_len=len(final))
    _to_phase(turn, TurnPhase.COMPLETING)
    return _result(
        _full(final) or tr("步骤有点多，先停在这里。你再说一下接下来要哪一步。"),
        StopReason.MAX_ROUNDS,
        detail=f"已用 {turn.rounds_used}/{max_rounds} 回合",
        pending_tasks=pending,
        rounds_used=turn.rounds_used,
    )


# ---------------------------------------------------------------- 子代理（3.3）

def run_subagent(backend, settings: dict, args: dict, cancelled=None) -> str:
    """派发子任务给独立子代理：中间步骤留在子代理自己的上下文里。

    - 轮数上限用 defaults.MAX_TOOL_ROUNDS_SUBAGENT（经 settings.ai_max_rounds 传入）；
    - 子代理只声明只读工具、不能再派发（tools.select_tool_schemas 的子代理过滤）；
    - 主对话只收到结构化结论 {"ok": true/false, "answer"/"error"}，不吞失败。
    """
    task = str((args or {}).get("task") or "").strip()
    context = str((args or {}).get("context") or "").strip()
    if not task:
        return json.dumps({"ok": False, "error": "缺少子任务描述（task 字段）"},
                          ensure_ascii=False)
    user_text = f"[子任务] {task}" + (f"\n相关背景：{context}" if context else "")
    sub_settings = dict(settings or {},
                        ai_subagent=True,
                        ai_max_rounds=MAX_TOOL_ROUNDS_SUBAGENT,
                        ai_session_id=f"{(settings or {}).get('ai_session_id') or 'active'}-sub")
    try:
        res = run_agent(backend, sub_settings, [], user_text, cancelled=cancelled)
    except AgentCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        trace.record("subagent_failed", exc=exc, task=task[:100])
        return json.dumps({"ok": False, "error": f"子代理执行失败: {exc}"},
                          ensure_ascii=False)
    answer = str(res)
    if res.stop_reason not in (StopReason.COMPLETED, StopReason.NO_TOOL_CALL) \
            and not answer.strip():
        return json.dumps({"ok": False,
                           "error": f"子代理未得出结论（停止原因: {res.stop_reason.value}）"},
                          ensure_ascii=False)
    return json.dumps({"ok": True, "answer": answer,
                       "stop_reason": res.stop_reason.value},
                      ensure_ascii=False)
