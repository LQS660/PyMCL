# -*- coding: utf-8 -*-
"""批次 2：turn 状态机 + 工具调度。全部离线打桩。

门禁 2.2 对应：
- 非法迁移抛 IllegalTransition
- 三个只读工具同轮并行，总耗时 ≈ 最慢一个
- agent.py 无 need_followup/followup_used/need_pick/pick_nudged/search_done
- ask_user 永远不在并行组
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import compact as compact_mod
from mclauncher.ai import scheduler
from mclauncher.ai import store as chat_store
from mclauncher.ai import trace as trace_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.client import AIClientError, is_context_overflow
from mclauncher.ai.permission import Behavior, Rule
from mclauncher.ai.result import StopReason
from mclauncher.ai.state import (
    ALLOWED, IllegalTransition, StepOutcome, ToolCall, ToolCallStatus,
    TurnPhase, TurnState,
)
from mclauncher.ai.tools import TOOL_META


def _tc(cid="c1", name="list_mods", args="{}"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}}


def _obj(cid="c1", name="list_mods"):
    return ToolCall(id=cid, name=name, args={})


class StateMachineTests(unittest.TestCase):
    def test_illegal_transition_raises(self):
        turn = TurnState(id="t", session_id="s", turn_number=1)
        with self.assertRaises(IllegalTransition):
            turn.transition(TurnPhase.EXECUTING_TOOLS)  # IDLE → EXECUTING 非法

    def test_completing_is_terminal(self):
        turn = TurnState(id="t", session_id="s", turn_number=1)
        turn.transition(TurnPhase.PROCESSING_INPUT)
        turn.transition(TurnPhase.COMPLETING)
        with self.assertRaises(IllegalTransition):
            turn.transition(TurnPhase.AWAITING_MODEL)

    def test_full_legal_path(self):
        turn = TurnState(id="t", session_id="s", turn_number=1)
        for phase in (TurnPhase.PROCESSING_INPUT, TurnPhase.AWAITING_MODEL,
                      TurnPhase.STREAMING, TurnPhase.SCHEDULING_TOOLS,
                      TurnPhase.AWAITING_PERMISSION, TurnPhase.EXECUTING_TOOLS,
                      TurnPhase.AWAITING_MODEL, TurnPhase.STREAMING,
                      TurnPhase.SCHEDULING_TOOLS, TurnPhase.EXECUTING_TOOLS,
                      TurnPhase.COMPLETING):
            turn.transition(phase)
        self.assertEqual(turn.phase, TurnPhase.COMPLETING)

    def test_allowed_table_guards(self):
        """表里没声明的迁移都要抛 IllegalTransition。"""
        for phase, targets in ALLOWED.items():
            for other in TurnPhase:
                if other not in targets:
                    turn = TurnState(id="t", session_id="s", turn_number=1)
                    turn.phase = phase
                    with self.assertRaises(IllegalTransition,
                                           msg=f"{phase} → {other} 应非法"):
                        turn.transition(other)

    def test_tool_call_lifecycle(self):
        turn = TurnState(id="t", session_id="s", turn_number=1)
        tc = turn.add_tool_call(_obj())
        turn.set_tool_status(tc.id, ToolCallStatus.RUNNING)
        self.assertGreater(tc.started_at, 0)
        turn.set_tool_status(tc.id, ToolCallStatus.COMPLETED, result="ok")
        self.assertEqual(tc.status, ToolCallStatus.COMPLETED)
        self.assertGreater(tc.ended_at, 0)
        self.assertEqual(turn.tool_results[0]["name"], "list_mods")
        self.assertEqual(turn.status_trace()[0]["status"], "completed")

    def test_step_outcome_values(self):
        self.assertEqual({o.value for o in StepOutcome},
                         {"continue", "output_continuation", "turn_completed"})


class SchedulerGroupTests(unittest.TestCase):
    def test_readonly_tools_share_one_group(self):
        objs = [_obj("a", "list_mods"), _obj("b", "get_latest_log"),
                _obj("c", "scan_mod_conflicts")]
        groups = scheduler.group(objs, TOOL_META)
        self.assertEqual(groups, [objs])

    def test_max_concurrency_splits(self):
        objs = [_obj(str(i), "list_mods") for i in range(3)]
        groups = scheduler.group(objs, TOOL_META, max_concurrency=2)
        self.assertEqual([len(g) for g in groups], [2, 1])

    def test_exclusive_tools_are_solo(self):
        objs = [_obj("a", "list_mods"), _obj("b", "delete_instance"),
                _obj("c", "ask_user"), _obj("d", "launch_game"),
                _obj("e", "list_instances")]
        groups = scheduler.group(objs, TOOL_META)
        self.assertEqual([g[0].name for g in groups],
                         ["list_mods", "delete_instance", "ask_user",
                          "launch_game", "list_instances"])
        self.assertTrue(all(len(g) == 1 for g in groups[1:]))

    def test_write_not_mixed_with_readonly(self):
        objs = [_obj("a", "list_mods"), _obj("b", "install_mod"),
                _obj("c", "get_java_list")]
        groups = scheduler.group(objs, TOOL_META)
        self.assertEqual([[t.name for t in g] for g in groups],
                         [["list_mods"], ["install_mod"], ["get_java_list"]])

    def test_ask_user_never_in_parallel_group(self):
        """死锁断言：任何组里出现 ask_user 时该组必须只有它自己。"""
        names = ["ask_user", "list_mods", "get_launcher_state", "scan_mod_conflicts",
                 "install_mod", "delete_mod", "launch_game", "get_latest_log"]
        objs = [_obj(f"c{i}", n) for i, n in enumerate(names)]
        for mc in (1, 2, 4, 8):
            for grp in scheduler.group(objs, TOOL_META, max_concurrency=mc):
                if any(t.name == "ask_user" for t in grp):
                    self.assertEqual(len(grp), 1,
                                     f"ask_user 混进了并行组: {[t.name for t in grp]}")

    def test_run_groups_parallel_timing(self):
        """三个只读工具并行：总耗时 ≈ 最慢一个，而不是三者之和。"""
        objs = [_obj(f"c{i}", "list_mods") for i in range(3)]

        def execute(tc):
            time.sleep(0.25)
            return tc.id

        start = time.monotonic()
        out = scheduler.run_groups([objs], execute, max_concurrency=4)
        elapsed = time.monotonic() - start
        self.assertEqual(set(out.values()), {"c0", "c1", "c2"})
        self.assertLess(elapsed, 0.65, f"并行未生效：耗时 {elapsed:.2f}s ≈ 三者之和")
        self.assertGreaterEqual(elapsed, 0.2)

    def test_run_groups_serial_between_groups(self):
        order = []

        def execute(tc):
            order.append(tc.id)
            return tc.id

        scheduler.run_groups([[_obj("a", "list_mods")], [_obj("b", "install_mod")]],
                             execute)
        self.assertEqual(order, ["a", "b"], "组间必须严格串行")


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name)
        self._seen = []

    def tearDown(self):
        trace_mod.TRACE_DIR = self._old_dir
        self._tmp.cleanup()

    def _fake_stream(self, streams):
        """返回一个 chat_stream 替身，记录每次收到的 messages。"""
        holder = {"n": 0}

        def fake(settings, messages, tools=None, http_cancel=None, **k):
            self._seen.append([dict(m) for m in messages])
            events = streams[holder["n"]]
            holder["n"] += 1
            yield from events
        return fake

    def _run(self, streams, ask_fn=None, run_tool="ok", confirm_fn=None,
             settings=None, **kw):
        # 批次 2.2 起工具按需声明；这里打桩的 tool_calls 不一定在核心集里，
        # 直接声明全量 schema，避免触发「漏选→全量重发」把流序列错位
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=self._fake_stream(streams)), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=ai_tools.TOOL_SCHEMAS), \
             mock.patch.object(agent_mod, "chat_once",
                               return_value={"content": "", "tool_calls": [],
                                             "finish_reason": "stop"}), \
             mock.patch.object(agent_mod, "run_tool", side_effect=run_tool):
            res = agent_mod.run_agent(SimpleNamespace(), settings or {}, [], "干活",
                                      ask_fn=ask_fn, confirm_fn=confirm_fn, **kw)
        return res, self._seen

    def test_parallel_reads_via_agent(self):
        """同轮三个只读工具走并行，总耗时 ≈ 最慢一个。"""
        streams = [
            [{"type": "tool_calls", "tool_calls": [
                _tc("a", "list_mods"), _tc("b", "get_latest_log"),
                _tc("c", "scan_mod_conflicts")]}],
            [{"type": "delta", "text": "查完了"}, {"type": "done"}],
        ]

        def slow_run_tool(*a, **k):
            time.sleep(0.25)
            return "ok"

        start = time.monotonic()
        res, _ = self._run(streams, run_tool=slow_run_tool)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.7, f"agent 并行未生效: {elapsed:.2f}s")
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)

    def test_no_prompt_patches_left_in_history(self):
        """删除的中文补丁不得再出现在 messages 里。"""
        streams = [
            [{"type": "tool_calls",
              "tool_calls": [_tc("a", "search_mods", '{"query": "钠"}')]}],
            [{"type": "delta", "text": "搜到了"}, {"type": "done"}],
        ]
        _, seen = self._run(streams)
        banned = ("禁止再搜", "选项已经选完", "搜索已经结束",
                  "下一动作必须是", "禁止只说话")
        for msgs in seen:
            for m in msgs:
                if m.get("role") == "system":
                    continue  # 系统提示词里的正常规矩不算补丁
                for frag in banned:
                    self.assertNotIn(frag, str(m.get("content") or ""))

    def test_ask_user_answer_continues_by_code(self):
        """ask_user 拿到答案后模型只回文字：代码保证再走一步，而不是直接结束。"""
        streams = [
            [{"type": "tool_calls",
              "tool_calls": [_tc("a", "ask_user",
                                 '{"prompt": "选哪个", "options": ["甲", "乙"]}')]}],
            [{"type": "delta", "text": "好的。"}, {"type": "done"}],
            [{"type": "delta", "text": "已经帮你装好。"}, {"type": "done"}],
        ]
        calls = []

        def ask_fn(questions, title):
            calls.append(questions)
            return "选了甲"

        res, _ = self._run(streams, ask_fn=ask_fn)
        self.assertEqual(len(calls), 1)
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)

    def test_progress_injected_from_second_round(self):
        streams = [
            [{"type": "tool_calls", "tool_calls": [_tc("a", "list_mods")]}],
            [{"type": "delta", "text": "好了"}, {"type": "done"}],
        ]
        _, seen = self._run(streams)
        self.assertNotIn("[进度]", seen[0][1]["content"])
        self.assertIn("[进度] 本轮已用 2/20 步", seen[1][1]["content"])

    def test_denied_write_reports_reason_to_model(self):
        """被规则拒绝的写操作：messages 里能看到 [权限] 已拒绝及原因。"""
        streams = [
            [{"type": "tool_calls",
              "tool_calls": [_tc("a", "install_mod", '{"name": "钠"}')]}],
            [{"type": "delta", "text": "明白了"}, {"type": "done"}],
        ]
        rules = [Rule("install_mod", None, Behavior.DENY)]
        res, seen = self._run(streams, settings={"ai_permission_rules": rules})
        tool_msg = [m for m in seen[1] if m.get("role") == "tool"][0]
        self.assertIn("[权限] 已拒绝", tool_msg["content"])
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)


class InterruptAndSteeringTests(unittest.TestCase):
    """批次 4：中断、插话、reactive compact、截断续写。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name)
        self._seen = []

    def tearDown(self):
        trace_mod.TRACE_DIR = self._old_dir
        self._tmp.cleanup()

    def _fake_stream(self, streams):
        holder = {"n": 0}

        def fake(settings, messages, tools=None, http_cancel=None, **k):
            self._seen.append([dict(m) for m in messages])
            events = streams[holder["n"]]
            holder["n"] += 1
            yield from events
        return fake

    def _run(self, streams, **kw):
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=self._fake_stream(streams)), \
             mock.patch.object(agent_mod, "chat_once",
                               return_value={"content": "", "tool_calls": [],
                                             "finish_reason": "stop"}), \
             mock.patch.object(agent_mod, "run_tool", return_value="ok"):
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "干活", **kw)
        return res, self._seen

    def test_run_tool_cancelled_at_entry(self):
        """W4-1：点了停止后 run_tool 入口立刻抛 ToolCancelled，不再执行。"""
        with self.assertRaises(ai_tools.ToolCancelled):
            ai_tools.run_tool(SimpleNamespace(), "list_mods", {},
                              cancelled=lambda: True)

    def test_run_tool_cancelled_after_execution(self):
        state = {"v": False}

        def cancelled():
            return state["v"]

        def execute(backend, name, args, wait=True, cancelled=None):
            state["v"] = True   # 执行期间用户点了停止
            return "ok"

        with mock.patch.object(ai_tools, "execute_tool", side_effect=execute):
            with self.assertRaises(ai_tools.ToolCancelled):
                ai_tools.run_tool(SimpleNamespace(), "list_mods", {},
                                  cancelled=cancelled)

    def test_tool_cancelled_maps_to_agent_cancelled(self):
        """agent 收到 ToolCancelled → 转 AgentCancelled，UI 显示已停止。"""
        streams = [[{"type": "tool_calls", "tool_calls": [_tc("a", "list_mods")]}]]
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=self._fake_stream(streams)), \
             mock.patch.object(agent_mod, "chat_once",
                               return_value={"content": "", "tool_calls": [],
                                             "finish_reason": "stop"}), \
             mock.patch.object(agent_mod, "run_tool",
                               side_effect=ai_tools.ToolCancelled("已停止")):
            with self.assertRaises(agent_mod.AgentCancelled):
                agent_mod.run_agent(SimpleNamespace(), {}, [], "干活")

    def test_steering_reaches_model_same_turn(self):
        """W4-2：跑动中补的话在同一个回合被模型看到。"""
        streams = [
            [{"type": "tool_calls", "tool_calls": [_tc("a", "list_mods")]}],
            [{"type": "delta", "text": "好的，内存改到 8G。"}, {"type": "done"}],
        ]
        queue = [["内存加到 8G"], []]
        res, seen = self._run(streams, drain_inputs_fn=lambda: queue.pop(0))
        steer = [m for m in seen[1] if m.get("role") == "user"
                 and "内存加到 8G" in str(m.get("content") or "")]
        self.assertEqual(len(steer), 1, "插话必须作为 user 消息进入下一轮请求")
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)

    def test_truncation_continuation_messages(self):
        """W4-4：截断后续写请求注入 assistant+user 两条消息。"""
        streams = [
            [{"type": "delta", "text": "前半"},
             {"type": "done", "finish_reason": "length"}],
            [{"type": "delta", "text": "后半。"}, {"type": "done"}],
        ]
        res, seen = self._run(streams)
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        self.assertEqual(str(res), "前半后半。")
        roles = [(m.get("role"), str(m.get("content") or "")) for m in seen[1]]
        self.assertIn(("assistant", "前半"), roles)
        self.assertIn(("user", "请从断开处继续，不要重复。"), roles)

    def test_reactive_compact_retries_same_step(self):
        """W4-3：上游报塞不下 → 压缩 → 重试同一步，用户看不到报错。"""
        streams = [
            [{"type": "error",
              "message": "This model's maximum context length is 8192 tokens"}],
            [{"type": "delta", "text": "恢复了"}, {"type": "done"}],
        ]
        compacted = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "[历史摘要]\n摘要正文"},
        ]
        cres = compact_mod.CompactionResult(messages=compacted, pre_token_count=5000,
                                            post_token_count=100)
        with mock.patch.object(compact_mod, "compact_conversation",
                               return_value=cres) as fake_compact:
            res, seen = self._run(streams)
        self.assertEqual(fake_compact.call_count, 1, "每步只抢救一次")
        self.assertEqual(res.stop_reason, StopReason.NO_TOOL_CALL)
        self.assertEqual(str(res), "恢复了")
        # 重试请求用的是压缩后的 messages
        self.assertEqual(seen[1], compacted)

    def test_is_context_overflow_keywords(self):
        self.assertTrue(is_context_overflow(
            "This model's maximum context length is 8192 tokens"))
        self.assertTrue(is_context_overflow("prompt too long"))
        self.assertTrue(is_context_overflow("上下文长度超出限制"))
        self.assertFalse(is_context_overflow("接口超时"))
        self.assertFalse(is_context_overflow(""))


class PersistAndHandoffTests(unittest.TestCase):
    """批次 5：持久化、错误重试、后台任务回灌、会话事件。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        self._old_sessions = chat_store.SESSIONS_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name) / "trace"
        chat_store.SESSIONS_DIR = Path(self._tmp.name) / "sessions"
        self._seen = []

    def tearDown(self):
        trace_mod.TRACE_DIR = self._old_dir
        chat_store.SESSIONS_DIR = self._old_sessions
        self._tmp.cleanup()

    def _fake_stream(self, streams):
        holder = {"n": 0}

        def fake(settings, messages, tools=None, http_cancel=None, **k):
            self._seen.append([dict(m) for m in messages])
            events = streams[holder["n"]]
            holder["n"] += 1
            for ev in events:
                if isinstance(ev, BaseException):
                    raise ev
                yield ev
        return fake

    def _run(self, streams, backend=None, settings=None, run_tool="ok", **kw):
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=self._fake_stream(streams)), \
             mock.patch.object(agent_mod, "chat_once",
                               return_value={"content": "", "tool_calls": [],
                                             "finish_reason": "stop"}), \
             mock.patch.object(agent_mod, "run_tool", return_value=run_tool):
            res = agent_mod.run_agent(backend or SimpleNamespace(),
                                      settings or {}, [], "干活", **kw)
        return res, self._seen

    def test_store_roundtrip_keeps_tool_trace(self):
        """W5-1：工具轨迹入库，重开（load）后 api_messages 仍带 tool 角色。"""
        old = chat_store.STORE_FILE
        chat_store.STORE_FILE = Path(self._tmp.name) / "ai_chats.json"
        try:
            data = chat_store.load()
            cid = data["active_id"]
            msgs = [
                {"role": "user", "content": "装钠"},
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": "install_mod",
                                              "arguments": '{"name": "钠"}'}}]},
                {"role": "tool", "tool_call_id": "c1", "name": "install_mod",
                 "content": '{"task_id": "t1", "queued": true}'},
                {"role": "assistant", "content": "已经在装了"},
            ]
            chat_store.upsert_messages(data, cid, msgs)
            reloaded = chat_store.load()
            chat = chat_store.get_chat(reloaded, cid)
            self.assertEqual([m["role"] for m in chat["messages"]],
                             ["user", "assistant", "tool", "assistant"])
            api = chat_store.api_messages(chat["messages"])
            self.assertEqual(api[1]["tool_calls"][0]["function"]["name"], "install_mod")
            self.assertEqual(api[2]["tool_call_id"], "c1")
        finally:
            chat_store.STORE_FILE = old

    def test_max_messages_raised(self):
        self.assertEqual(chat_store.MAX_MESSAGES, 200)

    def test_trim_history_drops_orphan_tool_head(self):
        """切片不能从孤立的 tool 消息开始。"""
        history = [{"role": "user", "content": "旧"},
                   {"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]},
                   {"role": "tool", "tool_call_id": "c", "name": "x", "content": "r"},
                   {"role": "assistant", "content": "完"},
                   {"role": "user", "content": "新"}]
        for cut in (2, 3):   # 切到 tool 消息开头时必须再往前丢
            trimmed, summary = agent_mod._trim_history(history[-cut:])
            self.assertIsNone(summary, "未超窗口不该产生摘要")
            self.assertNotEqual(trimmed[0].get("role"), "tool")

    def test_error_classification(self):
        """W5-3：429 不再致命、可重试；401 致命。"""
        e429 = AIClientError("网络繁忙", 429)
        self.assertFalse(e429.fatal())
        self.assertTrue(e429.retryable())
        e401 = AIClientError("令牌无效", 401)
        self.assertTrue(e401.fatal())
        self.assertFalse(e401.retryable())
        e_timeout = AIClientError("connect timed out", 0)
        self.assertEqual(e_timeout.category, "provider_timeout")
        self.assertTrue(e_timeout.retryable())

    def test_retry_with_backoff(self):
        """可重试错误退避重试，恢复后对话继续。"""
        streams = [
            [AIClientError("HTTP 429 too many requests", 429)],
            [AIClientError("connect ECONNRESET", 0)],
            [{"type": "delta", "text": "恢复了"}, {"type": "done"}],
        ]
        sleeps = []
        with mock.patch.object(agent_mod.time, "sleep", side_effect=sleeps.append):
            res, _ = self._run(streams)
        self.assertEqual(len(sleeps), 2, "两次重试各退避一次")
        self.assertEqual(res.stop_reason, StopReason.NO_TOOL_CALL)
        self.assertEqual(str(res), "恢复了")

    def test_pending_task_waited_in_turn(self):
        """W5-2 回合内：后台任务短超时内完成 → 结果回灌，模型来汇报。"""
        streams = [
            [{"type": "tool_calls",
              "tool_calls": [_tc("a", "install_mod", '{"name": "钠"}')]}],
            [{"type": "delta", "text": "在装了。"}, {"type": "done"}],
            [{"type": "delta", "text": "钠已经装好了。"}, {"type": "done"}],
        ]

        backend = SimpleNamespace()
        backend.wait_task = lambda task_id, timeout=1800, cancelled=None: {
            "ok": True, "message": "安装完成", "task_id": task_id}

        res, seen = self._run(streams, backend=backend,
                              run_tool='{"task_id": "t9", "queued": true}')
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        self.assertEqual(res.pending_tasks, [])
        report = [m for m in seen[2] if m.get("role") == "user"
                  and "后台任务回报" in str(m.get("content") or "")]
        self.assertEqual(len(report), 1)
        self.assertIn("安装完成", report[0]["content"])

    def test_result_carries_message_trace(self):
        """W5-1：AgentResult 带本回合轨迹，UI 据此持久化工具痕迹。"""
        streams = [
            [{"type": "tool_calls", "tool_calls": [_tc("a", "list_mods")]}],
            [{"type": "delta", "text": "好了"}, {"type": "done"}],
        ]
        res, _ = self._run(streams)
        roles = [m["role"] for m in res.messages]
        self.assertIn("tool", roles)
        self.assertEqual(roles[-1], "assistant")
        self.assertNotIn("system", roles)

    def test_session_events_logged(self):
        streams = [
            [{"type": "tool_calls", "tool_calls": [_tc("a", "list_mods")]}],
            [{"type": "delta", "text": "好了"}, {"type": "done"}],
        ]
        self._run(streams, settings={"ai_session_id": "sessX"})
        log = (chat_store.SESSIONS_DIR / "sessX.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line)["event"] for line in log.splitlines() if line.strip()]
        self.assertIn("TurnStarted", events)
        self.assertIn("ModelRequest", events)
        self.assertIn("ToolStarted", events)
        self.assertIn("ToolCompleted", events)
        self.assertIn("TurnCompleted", events)


if __name__ == "__main__":
    unittest.main()
