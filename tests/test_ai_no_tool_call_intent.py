# -*- coding: utf-8 -*-
"""NO_TOOL_CALL 只在「用户要它动手、它却光说话」时打标。

原来一轮没调工具就是 NO_TOOL_CALL，「你好」也会弹「它没有真的开始执行」的警告条、
气泡末尾还追一句提示。现在按用户那句话判：下载 / 安装 / 改配置这类派活才算；
问答、闲聊回文字就是 COMPLETED。模型嘴上说「已经装好了」而工具轨迹为空，照旧
算没动手。全部离线，chat 流程打桩。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import trace as trace_mod
from mclauncher.ai.result import StopReason


class IntentWordsTests(unittest.TestCase):
    def test_action_requests(self):
        for text in ("帮我装个钠", "下载 1.20.1", "把内存改成 8G", "干活", "继续",
                     "能帮我装个钠吗？", "install fabric for me", "please set memory to 8G"):
            self.assertTrue(agent_mod.wants_action(text), text)

    def test_questions_and_chat(self):
        for text in ("你好", "1", "1.20.1 有什么新内容", "怎么安装 Fabric？", "钠是什么",
                     "how do I install fabric?", "谢谢", "设置在哪里？"):
            self.assertFalse(agent_mod.wants_action(text), text)

    def test_claims(self):
        self.assertTrue(agent_mod.claims_action("已经帮你安装好了钠。"))
        self.assertTrue(agent_mod.claims_action("正在下载 1.20.1，请稍等"))
        self.assertTrue(agent_mod.claims_action("安装完成！"))
        self.assertFalse(agent_mod.claims_action("我可以帮你安装钠，需要现在开始吗？"))
        self.assertFalse(agent_mod.claims_action("你好！我是启动器助手。"))


class StopReasonByIntentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = trace_mod.TRACE_DIR
        trace_mod.TRACE_DIR = Path(self._tmp.name)

    def tearDown(self):
        trace_mod.TRACE_DIR = self._old_dir
        self._tmp.cleanup()

    def _run(self, user_text: str, reply: str):
        stream = iter([{"type": "delta", "text": reply}, {"type": "done"}])
        once = {"content": "", "tool_calls": [], "finish_reason": "stop"}
        with mock.patch.object(agent_mod, "chat_stream", side_effect=[stream]), \
             mock.patch.object(agent_mod, "chat_once", return_value=once), \
             mock.patch.object(agent_mod, "run_tool", return_value="ok"):
            return agent_mod.run_agent(SimpleNamespace(), {}, [], user_text)

    def test_chat_reply_is_completed(self):
        res = self._run("你好", "你好！我是启动器助手，能帮你下游戏、装模组。")
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)

    def test_question_reply_is_completed(self):
        res = self._run("1.20.1 有什么新内容", "1.20.1 主要是修复……")
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)

    def test_action_request_without_tools_is_flagged(self):
        res = self._run("帮我装个钠", "好的，我帮你装钠。")
        self.assertEqual(res.stop_reason, StopReason.NO_TOOL_CALL)

    def test_false_claim_is_flagged_even_in_chat(self):
        res = self._run("你好", "已经帮你安装好了钠，重启就能用。")
        self.assertEqual(res.stop_reason, StopReason.NO_TOOL_CALL)


if __name__ == "__main__":
    unittest.main()
