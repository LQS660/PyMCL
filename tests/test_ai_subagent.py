# -*- coding: utf-8 -*-
"""批次 3.3 子代理：独立轮数上限、上下文隔离、结构化失败回执。"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.defaults import MAX_TOOL_ROUNDS, MAX_TOOL_ROUNDS_SUBAGENT
from mclauncher.ai.result import StopReason
from mclauncher.ai.tools import TOOL_META, select_tool_schemas


class SubagentToolTests(unittest.TestCase):
    def test_dispatch_tool_registered_and_constant_referenced(self):
        self.assertIn("dispatch_subagent", TOOL_META)
        meta = TOOL_META["dispatch_subagent"]
        self.assertTrue(meta.readonly)
        # 门禁判据：MAX_TOOL_ROUNDS_SUBAGENT 在 defaults.py 之外有实际引用
        src = agent_mod.__file__
        self.assertIn("MAX_TOOL_ROUNDS_SUBAGENT", open(src, encoding="utf-8").read())
        self.assertNotEqual(MAX_TOOL_ROUNDS_SUBAGENT, MAX_TOOL_ROUNDS)

    def test_subagent_mode_declares_readonly_only(self):
        main = select_tool_schemas([{"role": "user", "content": "删掉模组"}], {})
        self.assertIn("delete_mod", {s["function"]["name"] for s in main})
        sub = select_tool_schemas([{"role": "user", "content": "删掉模组"}],
                                  {"ai_subagent": True})
        names = {s["function"]["name"] for s in sub}
        self.assertNotIn("delete_mod", names)
        self.assertNotIn("dispatch_subagent", names)
        self.assertIn("get_launcher_state", names)   # 只读核心仍在

    def test_subagent_run_tool_scope(self):
        # 主代理在子代理模式下：写工具被过滤，run_tool 只会收到只读调用
        settings = {"ai_subagent": True}
        sel = select_tool_schemas([{"role": "user", "content": "写配置 file.toml"}],
                                  settings)
        names = {s["function"]["name"] for s in sel}
        self.assertNotIn("write_mod_config", names)


class RunSubagentTests(unittest.TestCase):
    def test_passes_subagent_limits_and_wraps_result(self):
        captured = {}

        def fake_run_agent(backend, settings, history, text, **kw):
            captured["settings"] = dict(settings)
            captured["text"] = text
            res = agent_mod.AgentResult("子代理结论：一切正常", stop_reason=StopReason.COMPLETED)
            return res

        with mock.patch.object(agent_mod, "run_agent", side_effect=fake_run_agent):
            out = agent_mod.run_subagent(SimpleNamespace(), {"ai_session_id": "chat-1"},
                                         {"task": "查日志", "context": "实例 demo"})
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["answer"], "子代理结论：一切正常")
        self.assertEqual(captured["settings"]["ai_max_rounds"], MAX_TOOL_ROUNDS_SUBAGENT)
        self.assertTrue(captured["settings"]["ai_subagent"])
        self.assertIn("[子任务] 查日志", captured["text"])
        self.assertIn("demo", captured["text"])

    def test_failure_returns_structured_error(self):
        with mock.patch.object(agent_mod, "run_agent",
                               side_effect=RuntimeError("上游炸了")):
            out = agent_mod.run_subagent(SimpleNamespace(), {}, {"task": "查状态"})
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertIn("子代理执行失败", data["error"])
        self.assertIn("上游炸了", data["error"])

    def test_missing_task_structured_error(self):
        data = json.loads(agent_mod.run_subagent(SimpleNamespace(), {}, {}))
        self.assertFalse(data["ok"])
        self.assertIn("task", data["error"])


class SubagentIsolationTests(unittest.TestCase):
    """主对话只收到一条结构化结论；子代理中间步骤不进主上下文。"""

    STREAM = [{"type": "tool_calls", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "dispatch_subagent",
                      "arguments": '{"task": "扫一遍日志找错误"}'}}]},
        {"type": "delta", "text": "子代理说没问题"},
        {"type": "done"}]

    def test_main_context_only_gets_conclusion(self):
        sub_calls = []

        def fake_sub(backend, settings, args, cancelled=None):
            sub_calls.append(dict(args))
            return json.dumps({"ok": True, "answer": "结论：没有错误"},
                              ensure_ascii=False)

        def stream(settings, messages, tools, http_cancel=None):
            if not any(m.get("role") == "tool" for m in messages):
                yield {"type": "tool_calls", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "dispatch_subagent",
                                  "arguments": '{"task": "扫一遍日志找错误"}'}}]}
            else:
                yield {"type": "delta", "text": "子代理说没问题"}
                yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(ai_tools.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_subagent", side_effect=fake_sub):
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "帮我看看日志")

        self.assertEqual(len(sub_calls), 1)
        self.assertEqual(sub_calls[0]["task"], "扫一遍日志找错误")
        roles = [m.get("role") for m in res.turn_messages]
        # 主对话 = 用户句 + assistant(tool_calls) + tool(结论) + assistant(正文)
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        tool_row = [m for m in res.turn_messages if m.get("role") == "tool"][0]
        # 4.2 起工具回执带来源标注前缀，JSON 在首行之后
        body = tool_row["content"].split("\n", 1)[-1]
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["answer"], "结论：没有错误")
        # 隔离性证据：子代理的任何中间步骤（角色/内容）都不在主对话里
        self.assertNotIn("扫描中", tool_row["content"])
        # 派发前后主对话 token 对比：只多了 tool_call + tool 回执两条
        self.assertEqual(len(res.turn_messages), 4)


if __name__ == "__main__":
    unittest.main()
