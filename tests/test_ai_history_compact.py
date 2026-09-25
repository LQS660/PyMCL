# -*- coding: utf-8 -*-
"""上下文修复回归（2026-09-25）：压缩摘要活过回合结束 / 截断摘要化 /
microcompact 闲置触发 / 压缩熔断跨回合。全部离线打桩。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import compact as compact_mod
from mclauncher.ai import trace as trace_mod
from mclauncher.ai.compact import AutoDecision, CompactionResult, MicroConfig
from mclauncher.ai.result import StopReason


def _hist(n: int) -> list:
    """n 条无工具的普通历史消息。"""
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"历史消息 {i}"} for i in range(n)]


class TrimHistorySummaryTests(unittest.TestCase):
    def test_within_window_unchanged(self):
        kept, summary = agent_mod._trim_history(_hist(10), summarize=lambda m: "x")
        self.assertEqual(len(kept), 10)
        self.assertIsNone(summary)

    def test_over_window_gets_summary(self):
        seen = []

        def summarize(msgs):
            seen.append(list(msgs))
            return "用户之前聊过装钠。"

        kept, summary = agent_mod._trim_history(_hist(agent_mod.MAX_HISTORY + 6),
                                                summarize=summarize)
        self.assertEqual(len(kept), agent_mod.MAX_HISTORY)
        self.assertIsNotNone(summary)
        self.assertTrue(str(summary["id"]).startswith("compact_h"))
        self.assertIn("[历史摘要]", summary["content"])
        self.assertIn("装钠", summary["content"])
        self.assertEqual(summary["role"], "user")
        # 摘要输入是被裁掉的头部，不含保留区
        self.assertEqual(len(seen[0]), 6)
        self.assertNotIn("历史消息 29", [m["content"] for m in seen[0]])

    def test_summary_failure_falls_back_to_silent_trim(self):
        def summarize(_):
            raise RuntimeError("网关挂了")
        kept, summary = agent_mod._trim_history(_hist(agent_mod.MAX_HISTORY + 2),
                                                summarize=summarize)
        self.assertEqual(len(kept), agent_mod.MAX_HISTORY)
        self.assertIsNone(summary, "摘要失败必须退回静默截断，不能阻断回合")

    def test_empty_summary_falls_back(self):
        kept, summary = agent_mod._trim_history(_hist(agent_mod.MAX_HISTORY + 2),
                                                summarize=lambda m: "  ")
        self.assertIsNone(summary)

    def test_reuses_previous_summary_when_nothing_new(self):
        """被裁段里只有旧摘要、没有新内容：复用旧摘要，不重花一次请求。"""
        prev1 = {"role": "user", "content": "[历史摘要]\n更早摘要", "id": "compact_h20"}
        prev2 = {"role": "user", "content": "[历史摘要]\n旧摘要", "id": "compact_h30"}
        history = [dict(prev1), dict(prev2)] + _hist(agent_mod.MAX_HISTORY)
        calls = []

        def summarize(msgs):
            calls.append(list(msgs))
            return "新摘要"

        kept, summary = agent_mod._trim_history(history, summarize=summarize)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["id"], prev2["id"], "复用被裁段里最后一条摘要")
        self.assertEqual(summary["content"], prev2["content"])
        self.assertEqual(calls, [], "复用路径不再花一次摘要请求")

    def test_previous_summary_joins_new_slice(self):
        prev = {"role": "user", "content": "[历史摘要]\n旧摘要", "id": "compact_h30"}
        history = [prev] + _hist(agent_mod.MAX_HISTORY + 3)
        seen = []
        kept, summary = agent_mod._trim_history(
            history, summarize=lambda msgs: (seen.append(list(msgs)) or "合并摘要"))
        self.assertIsNotNone(summary)
        self.assertTrue(str(summary["id"]).startswith("compact_h"))
        # 摘要的摘要：输入以旧摘要开头，后面是被裁的新消息
        self.assertIs(seen[0][0], prev)
        self.assertEqual(len(seen[0]), 4)   # 旧摘要 + 3 条新被裁消息


class MicrocompactIdleTests(unittest.TestCase):
    @staticmethod
    def _conv():
        msgs = [{"role": "user", "content": "帮我装钠"}]
        for i in range(8):
            msgs.append({"role": "assistant", "content": None,
                         "tool_calls": [{"id": f"c{i}", "type": "function",
                                         "function": {"name": "list_mods",
                                                      "arguments": "{}"}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                         "name": "list_mods", "content": "字" * 2000 + str(i)})
        return msgs

    def test_idle_triggers_below_token_threshold(self):
        """闲置 30 分钟：没到 token 阈值也清旧工具结果（原来是写死 0.0 的死路径）。"""
        cfg = MicroConfig(threshold_tokens=None, min_token_savings=2000)
        res = compact_mod.microcompact(self._conv(), cfg, 0.0, 0.0,
                                       idle_seconds=31 * 60)
        self.assertEqual(res.decision_reason, "applied")
        self.assertEqual(res.cleared_count, 3)

    def test_short_idle_does_not_trigger(self):
        cfg = MicroConfig(threshold_tokens=None, min_token_savings=2000)
        res = compact_mod.microcompact(self._conv(), cfg, 0.0, 0.0,
                                       idle_seconds=5 * 60)
        self.assertEqual(res.decision_reason, "not_triggered")

    def test_zero_idle_keeps_old_behavior(self):
        cfg = MicroConfig(threshold_tokens=10 ** 9)
        res = compact_mod.microcompact(self._conv(), cfg, 0.0, 0.0)
        self.assertEqual(res.decision_reason, "not_triggered")


class CompactStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        agent_mod._COMPACT_STATES.clear()
        agent_mod._LAST_ACTIVITY["ts"] = 0.0
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        self._old_sessions = agent_mod.chat_store.SESSIONS_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name) / "trace"
        agent_mod.chat_store.SESSIONS_DIR = Path(self._tmp.name) / "sessions"

    def tearDown(self):
        agent_mod._COMPACT_STATES.clear()
        trace_mod.TRACE_DIR = self._old_dir
        agent_mod.chat_store.SESSIONS_DIR = self._old_sessions
        self._tmp.cleanup()

    def test_same_session_gets_same_state(self):
        st = agent_mod._compact_state_for("sess-a")
        self.assertIs(st, agent_mod._compact_state_for("sess-a"))
        self.assertIsNot(st, agent_mod._compact_state_for("sess-b"))

    def test_consecutive_failures_forgiven_each_turn(self):
        """压缩连续失败每回合清零：网关抖动不该把本会话的压缩永久关掉。"""
        calls = {"n": 0}

        def fake_compact(messages, cfg, summarize):
            calls["n"] += 1
            raise ValueError("摘要请求失败")

        def stream(settings, messages, tools, http_cancel=None):
            yield {"type": "delta", "text": "回复"}
            yield {"type": "done"}

        settings = {"ai_session_id": "sess-forgive"}
        with mock.patch.object(compact_mod, "should_autocompact",
                               return_value=AutoDecision(True, "above_threshold")), \
             mock.patch.object(compact_mod, "compact_conversation",
                               side_effect=fake_compact), \
             mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            agent_mod.run_agent(SimpleNamespace(), settings, [], "你好")
            first = calls["n"]
            st = agent_mod._compact_state_for("sess-forgive")
            self.assertGreaterEqual(st.consecutive_failures, 1)
            agent_mod.run_agent(SimpleNamespace(), settings, [], "你好")
        self.assertGreater(calls["n"], first, "第二回合必须重试压缩（失败计数被清零）")

    def test_tool_turns_survive_across_turns(self):
        """压缩成功后 tool_turns_since_compact 跨回合保留，rapid-refill 才有意义。"""
        def stream(settings, messages, tools, http_cancel=None):
            yield {"type": "delta", "text": "回复"}
            yield {"type": "done"}

        cres = CompactionResult(
            messages=[{"role": "system", "content": "s"},
                      {"role": "user", "content": "[历史摘要]\n摘要", "id": "compact_5"}],
            pre_token_count=200_000, post_token_count=100)
        settings = {"ai_session_id": "sess-keep"}
        with mock.patch.object(compact_mod, "should_autocompact",
                               return_value=AutoDecision(True, "above_threshold")), \
             mock.patch.object(compact_mod, "compact_conversation",
                               return_value=cres), \
             mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            agent_mod.run_agent(SimpleNamespace(), settings, [], "你好")
        st = agent_mod._compact_state_for("sess-keep")
        self.assertEqual(st.tool_turns_since_compact, 0, "压缩成功即清零")
        self.assertEqual(st.consecutive_failures, 0)


class TurnSlicePersistenceTests(unittest.TestCase):
    def setUp(self):
        agent_mod._COMPACT_STATES.clear()
        agent_mod._LAST_ACTIVITY["ts"] = 0.0
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        self._old_sessions = agent_mod.chat_store.SESSIONS_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name) / "trace"
        agent_mod.chat_store.SESSIONS_DIR = Path(self._tmp.name) / "sessions"

    def tearDown(self):
        agent_mod._COMPACT_STATES.clear()
        trace_mod.TRACE_DIR = self._old_dir
        agent_mod.chat_store.SESSIONS_DIR = self._old_sessions
        self._tmp.cleanup()

    def _run(self, history=(), user_text="你好", once=None):
        def stream(settings, messages, tools, http_cancel=None):
            yield {"type": "delta", "text": "回复"}
            yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "chat_once",
                               return_value=once if once is not None
                               else {"content": "早期对话摘要"}):
            return agent_mod.run_agent(SimpleNamespace(), {"ai_session_id": "s"},
                                       list(history), user_text)

    def test_autocompact_summary_survives_turn(self):
        """压缩后 turn_slice 必须带上摘要消息，否则下一轮模型失忆（原 bug）。"""
        cres = CompactionResult(
            messages=[{"role": "system", "content": "s"},
                      {"role": "user", "content": "[历史摘要]\n用户想装钠", "id": "compact_5"}],
            pre_token_count=200_000, post_token_count=100)
        with mock.patch.object(compact_mod, "should_autocompact",
                               return_value=AutoDecision(True, "above_threshold")), \
             mock.patch.object(compact_mod, "compact_conversation",
                               return_value=cres):
            res = self._run()
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        slice_msgs = list(res.turn_messages)
        compacts = [m for m in slice_msgs if str(m.get("id") or "").startswith("compact_")]
        self.assertEqual(len(compacts), 1, "压缩摘要必须进持久化切片")
        self.assertIn("用户想装钠", compacts[0]["content"])

    def test_trim_summary_enters_turn_slice(self):
        """截断摘要同样入库：下一轮在被裁段里找到它就复用，不再每回合重摘。"""
        history = _hist(agent_mod.MAX_HISTORY + 2)
        res = self._run(history=history)
        slice_msgs = list(res.turn_messages)
        compacts = [m for m in slice_msgs if str(m.get("id") or "").startswith("compact_h")]
        self.assertEqual(len(compacts), 1, "截断摘要必须进持久化切片")
        self.assertIn("[历史摘要]", compacts[0]["content"])

    def test_no_compact_no_extra_slice(self):
        res = self._run(history=_hist(4))
        self.assertFalse(any(str(m.get("id") or "").startswith("compact_")
                             for m in res.turn_messages))


if __name__ == "__main__":
    unittest.main()
