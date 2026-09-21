# -*- coding: utf-8 -*-
"""批次 3.4 计划工作流 + 3.5 长期记忆接口。

3.4：结构化待办进 UI（plan 状态事件）、plan 权限档出计划必须等批准、
拒绝后本轮结束且未执行任何写操作、待办随会话持久化重开仍在。
3.5：默认空记忆启用与否，模型请求 messages 逐字一致。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import memory as memory_mod
from mclauncher.ai import store as chat_store
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.permission import Behavior, Rule
from mclauncher.ai.result import StopReason
from mclauncher.ai.tools import TOOL_META


def _tc(name, args_json="{}"):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": args_json}}


PLAN_ARGS = ('{"items": [{"title": "扫描冲突", "status": "completed"},'
             ' {"title": "卸载旧版", "status": "pending"},'
             ' {"title": "安装新版", "status": "pending"}]}')


class PlanWorkflowTests(unittest.TestCase):
    STREAM = [{"type": "tool_calls", "tool_calls": [_tc("update_plan", PLAN_ARGS)]},
              {"type": "delta", "text": "收尾"},
              {"type": "done"}]

    def _run(self, settings, confirm_fn=None):
        stream_called = {"n": 0}

        def stream(settings, messages, tools, http_cancel=None):
            stream_called["n"] += 1
            # plan 档批准后再给一轮：验证「等批准才继续」
            if stream_called["n"] == 1:
                yield self.STREAM[0]
            else:
                yield from self.STREAM[1:]

        statuses = []
        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(ai_tools.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool", return_value="ok"):
            res = agent_mod.run_agent(
                SimpleNamespace(), settings, [], "装个东西",
                confirm_fn=confirm_fn,
                on_status=lambda k, p: statuses.append((k, p)))
        return res, statuses

    def test_plan_tool_registered_and_emits_status(self):
        self.assertIn("update_plan", TOOL_META)
        self.assertTrue(TOOL_META["update_plan"].readonly)
        res, statuses = self._run({}, confirm_fn=lambda *a: True)
        kinds = [k for k, _ in statuses]
        self.assertIn("plan", kinds)
        plan_status = [p for k, p in statuses if k == "plan"][0]
        self.assertEqual(len(plan_status["items"]), 3)
        self.assertEqual([i["title"] for i in plan_status["items"]][0], "扫描冲突")

    def test_plan_mode_requires_approval_before_continuing(self):
        confirm_calls = []

        def confirm_fn(name, args, label, reason=""):
            confirm_calls.append((name, label))
            return True

        res, statuses = self._run({"ai_permission_mode": "plan"}, confirm_fn)
        # 出计划后立即请求批准，批准后回合才继续到收尾
        self.assertEqual([n for n, _ in confirm_calls], ["plan_approval"])
        self.assertIn("plan_approval", [k for k, _ in statuses])

    def test_plan_mode_rejection_ends_turn_with_zero_writes(self):
        run_tool_calls = []

        def confirm_fn(name, args, label, reason=""):
            return False   # 用户拒绝计划

        with mock.patch.object(agent_mod, "run_tool",
                               side_effect=lambda *a, **k:
                                   run_tool_calls.append(a) or "ok"):
            res, statuses = self._run({"ai_permission_mode": "plan"}, confirm_fn)
        # 本轮立刻结束、没有执行任何写操作（run_tool 只会收到只读调用，且本轮根本没再跑）
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        self.assertIn("没有执行任何写操作", str(res))
        self.assertEqual(run_tool_calls, [])
        self.assertIn("plan_rejected", open(agent_mod.__file__, encoding="utf-8").read())

    def test_plan_persisted_and_reloaded(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(chat_store, "STORE_FILE", Path(d) / "ai_chats.json"):
                data = chat_store.load()
                cid = data["active_id"]
                plan = {"turn_id": "turn-1",
                        "items": [{"title": "第一步", "status": "pending"}]}
                chat_store.set_plan(data, cid, plan)
                # 重开程序 = 重新 load
                data2 = chat_store.load()
                got = chat_store.get_chat(data2, cid).get("plan")
                self.assertEqual(got["items"][0]["title"], "第一步")
                chat_store.set_plan(data2, cid, None)
                self.assertIsNone(chat_store.load().get("chats")[0].get("plan"))


class MemoryInterfaceTests(unittest.TestCase):
    def setUp(self):
        memory_mod.set_memory(None)   # 回到 NoopMemory

    def tearDown(self):
        memory_mod.set_memory(None)

    def _capture_messages(self):
        seen = {}

        def stream(settings, messages, tools, http_cancel=None):
            seen["messages"] = [dict(m) for m in messages]
            yield {"type": "delta", "text": "好"}
            yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            agent_mod.run_agent(SimpleNamespace(), {"ai_session_id": "chat-m"}, [], "你好")
        return seen["messages"]

    def test_noop_memory_keeps_messages_identical(self):
        msgs_before = self._capture_messages()
        # 显式注册一个空实现，行为与默认完全一致
        memory_mod.set_memory(memory_mod.NoopMemory())
        msgs_noop = self._capture_messages()
        self.assertEqual(msgs_before, msgs_noop)

    def test_memory_content_enters_system_block(self):
        class FakeMemory(memory_mod.NoopMemory):
            def load(self, chat_id):
                return "用户偏好最小内存启动" if chat_id == "chat-m" else ""

        memory_mod.set_memory(FakeMemory())
        msgs = self._capture_messages()
        mem_blocks = [m for m in msgs if m.get("role") == "system"
                      and "长期记忆" in str(m.get("content"))]
        self.assertEqual(len(mem_blocks), 1)
        self.assertIn("用户偏好最小内存启动", mem_blocks[0]["content"])


if __name__ == "__main__":
    unittest.main()
