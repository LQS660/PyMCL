# -*- coding: utf-8 -*-
"""批次 5.1/5.2：坏参数结构化回执 + 模型自纠；错误面规范化。

5 组坏参数（缺必填 / 类型错 / 值带多余空格 / key=value / JSON 截断）每组都有
明确回执；模型收到回执后下一轮自行修正（对话证明）。
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.tools import (
    ToolErrorCode, bad_args_payload, parse_args, run_tool, tool_error_payload,
)


class BadArgsFiveGroupsTests(unittest.TestCase):
    """改造清单 5.1 指定的 5 组坏参数，每组必须有含字段名的明确回执。"""

    def test_1_missing_required(self):
        args, err = parse_args('{"path": "a.toml"}', "write_mod_config")
        self.assertIsNone(err is None and args or None)
        self.assertIn("缺少必填字段", err)
        self.assertIn("content", err)

    def test_2_wrong_type(self):
        args, err = parse_args('{"version": 123}', "install_game")
        self.assertIn("类型不对", err)
        self.assertIn("version", err)
        self.assertIn("string", err)

    def test_3_extra_whitespace_trimmed(self):
        args, err = parse_args('{"query": "  钠   "}', "search_mods")
        self.assertIsNone(err)
        self.assertEqual(args["query"], "钠")

    def test_4_key_value_style(self):
        args, err = parse_args('name = "jei", instance = "demo"', "install_mod")
        self.assertIsNotNone(err)          # 明确回执：这不是标准 JSON
        self.assertIn("key=value", err)
        self.assertEqual(args.get("name"), "jei")   # 但字段抢救出来了

    def test_5_truncated_json(self):
        args, err = parse_args('{"query": "sodium", "vers', "search_mods")
        self.assertIsNotNone(err)
        self.assertIn("JSON", err)

    def test_every_group_returns_structured_receipt(self):
        # 组 3（多余空格）是自动修好、正常执行，不算错误——单测在上面单独覆盖
        groups = [
            ('{"path": "a.toml"}', "write_mod_config"),
            ('{"version": 123}', "install_game"),
            ('name = "jei"', "install_mod"),
            ('{"query": "sod', "search_mods"),
        ]
        for raw, name in groups:
            out = run_tool(SimpleNamespace(), name, raw)
            data = json.loads(out)
            self.assertEqual(data["ok"], False, raw)
            self.assertEqual(data["error_code"], ToolErrorCode.BAD_ARGUMENTS.value, raw)
            self.assertTrue(data["message"], raw)

    def test_whitespace_group_actually_executes(self):
        # 多余空格自动修剪后正常执行（backend 桩返回列表即证明跑到了工具）
        out = run_tool(SimpleNamespace(_instance=lambda n: SimpleNamespace(),
                                       get_installed_versions=lambda n: []),
                       "list_installed_versions", '{"instance": "  demo  "}')
        self.assertIsInstance(json.loads(out), list)


class ErrorSurfaceTests(unittest.TestCase):
    def test_exception_becomes_structured_receipt(self):
        out = run_tool(SimpleNamespace(), "list_mods", "{}")   # backend 没有实例方法 → 异常
        data = json.loads(out)
        self.assertEqual(data["ok"], False)
        self.assertIn(data["error_code"], {e.value for e in ToolErrorCode})
        self.assertTrue(data["message"])
        # 原始异常不再直接进模型上下文：detail 只有类型名+短原因
        self.assertLess(len(data.get("detail") or ""), 220)

    def test_enum_covers_all_readables(self):
        from mclauncher.ai.tools import _ERROR_READABLE
        self.assertEqual(set(_ERROR_READABLE), set(ToolErrorCode))

    def test_raw_exception_string_gone(self):
        src = open(ai_tools.__file__, encoding="utf-8").read()
        self.assertNotIn('f"工具失败: {exc}"', src)

    def test_tool_error_payload_direct(self):
        out = tool_error_payload(TimeoutError("超时 30s"), "install_game")
        data = json.loads(out)
        self.assertEqual(data["error_code"], ToolErrorCode.TIMEOUT.value)
        self.assertIn("超时", data["message"])


class ModelSelfCorrectionTests(unittest.TestCase):
    """坏参数回执 → 模型下一轮自行修正（对话证明）。"""

    def test_model_fixes_args_after_receipt(self):
        phases = {"n": 0}
        executed = []

        def stream(settings, messages, tools, http_cancel=None):
            phases["n"] += 1
            tool_rows = [m.get("content") for m in messages if m.get("role") == "tool"]
            if phases["n"] == 1:
                # 第一轮：缺 content 的坏参数
                yield {"type": "tool_calls", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "write_mod_config",
                                  "arguments": '{"path": "a.toml"}'}}]}
            elif phases["n"] == 2:
                # 第二轮：模型看到回执，补上 content 再调
                self.assertTrue(any("缺少必填字段" in (x or "") for x in tool_rows))
                yield {"type": "tool_calls", "tool_calls": [
                    {"id": "c2", "type": "function",
                     "function": {"name": "write_mod_config",
                                  "arguments": '{"path": "a.toml", "content": "k=1"}'}}]}
            else:
                self.assertTrue(any("已写入" in (x or "") for x in tool_rows))
                yield {"type": "delta", "text": "改好了"}
                yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(ai_tools.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool",
                               side_effect=lambda b, n, a, **k:
                                   executed.append((n, dict(a))) or "已写入 a.toml"):
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "把 a.toml 的 k 改成 1")

        # 第一轮没执行（参数被拦），第二轮修正后真正执行
        self.assertEqual([a for _, a in executed], [{"path": "a.toml", "content": "k=1"}])
        self.assertEqual(res.stop_reason.value, "completed")


if __name__ == "__main__":
    unittest.main()
