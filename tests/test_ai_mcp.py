# -*- coding: utf-8 -*-
"""批次 3.2 MCP 客户端：tools/list 进模型可选集、调用结果回填、坏 server 隔离。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import mcp as mcp_mod

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ECHO_SERVER = [sys.executable, str(FIXTURES / "mcp_echo_server.py")]
CRASH_SERVER = [sys.executable, str(FIXTURES / "mcp_crash_server.py")]


def _tc(name, args_json='{"text": "你好"}'):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": args_json}}


class McpClientTests(unittest.TestCase):
    def test_connect_list_and_call(self):
        client = mcp_mod.McpClient("echo", ECHO_SERVER[0], ECHO_SERVER[1:])
        try:
            client.connect()
            tools = client.list_tools()
            self.assertEqual([t["name"] for t in tools], ["echo"])
            out = client.call_tool("echo", {"text": "你好"})
            self.assertEqual(out, "echo: 你好")
        finally:
            client.close()

    def test_schemas_get_prefixed_names(self):
        client = mcp_mod.McpClient("echo", ECHO_SERVER[0], ECHO_SERVER[1:])
        try:
            client.connect()
            schemas = mcp_mod.mcp_tool_schemas([client])
        finally:
            client.close()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["function"]["name"], "mcp_echo_echo")
        self.assertEqual(schemas[0]["function"]["parameters"]["type"], "object")

    def test_crashing_server_is_skipped(self):
        # 崩 server：连接失败被跳过，同批健康 server 与内置工具不受影响
        clients = mcp_mod.connect_servers({
            "ai_mcp_servers": [
                {"name": "bad", "command": CRASH_SERVER[0], "args": CRASH_SERVER[1:]},
                {"name": "echo", "command": ECHO_SERVER[0], "args": ECHO_SERVER[1:]},
            ]})
        try:
            self.assertEqual([c.name for c in clients], ["echo"])
            schemas = mcp_mod.mcp_tool_schemas(clients)
            self.assertEqual([s["function"]["name"] for s in schemas],
                             ["mcp_echo_echo"])
        finally:
            mcp_mod.close_all(clients)

    def test_route_call_unknown_prefix_raises_structured(self):
        with self.assertRaises(mcp_mod.McpError):
            mcp_mod.route_call([], "mcp_noserver_tool", {})


class McpAgentIntegrationTests(unittest.TestCase):
    def test_mcp_tool_declared_and_result_fed_back(self):
        """完整对话：MCP 工具出现在声明里 → 模型调用 → 结果回填 → 模型基于结果收尾。"""
        client = mcp_mod.McpClient("echo", ECHO_SERVER[0], ECHO_SERVER[1:])
        client.connect()   # 让 mcp_tool_schemas 真能拉到 tools/list
        seen_tools = []
        phases = {"n": 0}

        def stream(settings, messages, tools, http_cancel=None):
            phases["n"] += 1
            seen_tools.append({s["function"]["name"] for s in (tools or [])})
            if phases["n"] == 1:
                yield {"type": "tool_calls",
                       "tool_calls": [_tc("mcp_echo_echo", '{"text": "测试消息"}')]}
            else:
                tool_rows = [m.get("content") for m in messages if m.get("role") == "tool"]
                yield {"type": "delta", "text": f"工具说: {tool_rows[-1]}"}
                yield {"type": "done"}

        with mock.patch.object(mcp_mod, "connect_servers", return_value=[client]), \
             mock.patch.object(agent_mod.mcp_mod, "route_call",
                               side_effect=lambda cs, n, a: "echo: 测试消息"), \
             mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            res = agent_mod.run_agent(SimpleNamespace(),
                                      {"ai_mcp_servers": [{"name": "echo", "command": "x"}]},
                                      [], "用 echo 工具")
        client.close()
        # 工具进了模型可选集
        self.assertIn("mcp_echo_echo", seen_tools[0])
        # 结果回填进上下文，模型基于它继续
        self.assertIn("echo: 测试消息", str(res))
        self.assertEqual(res.stop_reason.value, "completed")

    def test_mcp_call_failure_returns_structured_error_and_turn_survives(self):
        def stream(settings, messages, tools, http_cancel=None):
            phases = len([1])  # noqa
            if not any(m.get("role") == "tool" for m in messages):
                yield {"type": "tool_calls", "tool_calls": [_tc("mcp_bad_tool")]}
            else:
                tool_rows = [m.get("content") for m in messages if m.get("role") == "tool"]
                yield {"type": "delta", "text": f"收到错误回执: {tool_rows[-1][:60]}"}
                yield {"type": "done"}

        with mock.patch.object(agent_mod.mcp_mod, "route_call",
                               side_effect=mcp_mod.McpError("server 已崩")), \
             mock.patch.object(mcp_mod, "connect_servers",
                               return_value=[mcp_mod.McpClient("bad", "noop")]), \
             mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "调坏工具")
        self.assertIn("MCP 工具失败", str(res), "失败原因要结构化回给模型")
        self.assertIn("server 已崩", str(res))
        self.assertEqual(res.stop_reason.value, "completed", "对话不中断")


if __name__ == "__main__":
    unittest.main()
