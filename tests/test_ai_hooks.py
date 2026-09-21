# -*- coding: utf-8 -*-
"""批次 3.1 工具 hooks：前置/后置拦截、入参与结果改写、异常不中断、总闸关闭后行为不变。

「关闭该钩子后行为不变」的回归口径：ai_hooks_enabled=False 时，同一打桩序列
产出的模型请求 messages 与「钩子注册表清空（机制旁路）」时逐字一致。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import hooks as hook_mod
from mclauncher.ai import trace as trace_mod
from mclauncher.ai.tools import TOOL_META


def _tc(name, args="{}"):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": args}}


class HooksTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir_patch = mock.patch.object(hook_mod, "HOOKS_DIR",
                                            Path(self._tmp.name) / "hooks")
        self._dir_patch.start()
        self._trace_patch = mock.patch.object(trace_mod, "TRACE_DIR",
                                              Path(self._tmp.name) / "trace")
        self._trace_patch.start()
        hook_mod.clear()
        # setUp 的 clear 会连内置审计钩子一起清掉，恢复它
        hook_mod.register(hook_mod.Hook("write_audit", before=hook_mod._audit_before))
        hook_mod.set_enabled(True)

    def tearDown(self):
        hook_mod.clear()
        self._dir_patch.stop()
        self._trace_patch.stop()
        self._tmp.cleanup()


def _two_phase_stream(tool_name):
    """第一轮吐 tool_calls，第二轮吐正文收尾——模拟真实回合。"""
    holder = {"n": 0}

    def stream(settings, messages, tools, http_cancel=None):
        holder["n"] += 1
        if holder["n"] == 1:
            yield {"type": "tool_calls", "tool_calls": [_tc(tool_name)]}
        else:
            yield {"type": "delta", "text": "完成"}
            yield {"type": "done"}

    return stream


class HookSemanticsTests(HooksTestBase):
    def test_before_rewrites_args_and_after_rewrites_result(self):
        seen = {}

        def grab(name, args):
            seen["args"] = dict(args)
            return dict(args, name="改写过")

        hook_mod.register(hook_mod.Hook("rw", before=grab,
                                        after=lambda n, r: r + "（已审）"))

        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=_two_phase_stream("install_mod")), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(agent_mod.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool",
                               side_effect=lambda *a, **k: "装好了") as rt:
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "装钠")

        rt.assert_called_once()
        # 改写后的入参真正进了 run_tool（第一个位置参数是 backend，第二个是工具名）
        executed_args = rt.call_args[0][2]
        self.assertEqual(executed_args.get("name"), "改写过")
        # after 改写的是工具回执（进模型上下文），不是最终正文
        tool_rows = [m for m in res.turn_messages if m.get("role") == "tool"]
        self.assertTrue(any("（已审）" in m.get("content") for m in tool_rows))

    def test_hook_exception_does_not_break_turn(self):
        def boom(name, args):
            raise RuntimeError("钩子炸了")

        hook_mod.register(hook_mod.Hook("bad", before=boom, after=boom))

        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=_two_phase_stream("list_mods")), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(agent_mod.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool", return_value="正常结果"):
            res = agent_mod.run_agent(SimpleNamespace(), {}, [], "查一下")
        # 回合正常收尾、工具结果进了上下文、对话未中断
        self.assertEqual(res.stop_reason.value, "completed")
        tool_rows = [m for m in res.turn_messages if m.get("role") == "tool"]
        self.assertTrue(any("正常结果" in m.get("content") for m in tool_rows))

    def test_builtin_audit_hook_writes_file(self):
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=_two_phase_stream("delete_mod")), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(agent_mod.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool", return_value="已删除"):
            agent_mod.run_agent(SimpleNamespace(), {}, [], "删模组")
        audit = Path(self._tmp.name) / "hooks" / "audit.jsonl"
        self.assertTrue(audit.is_file())
        row = json.loads(audit.read_text("utf-8").splitlines()[0])
        self.assertEqual(row["tool"], "delete_mod")


class HookDisabledParityTests(HooksTestBase):
    def _run(self, settings, with_hook):
        stream = _two_phase_stream("install_mod")
        if with_hook:
            hook_mod.register(hook_mod.Hook(
                "rw", before=lambda n, a: dict(a, name="改写"),
                after=lambda n, r: r + "（已审）"))
        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(agent_mod.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool",
                               return_value="装好了") as rt:
            res = agent_mod.run_agent(SimpleNamespace(), settings, [], "装钠")
        return res, rt

    def test_disabled_behaves_as_if_no_hooks(self):
        # 关闭总闸：run_tool 收到的入参、工具回执与「注册表清空（机制旁路）」逐字一致
        res_off, rt_off = self._run({"ai_hooks_enabled": False}, with_hook=True)
        args_off = rt_off.call_args[0][2]
        tool_rows_off = [m.get("content") for m in res_off.turn_messages
                         if m.get("role") == "tool"]
        # 旁路口径：同一序列，无钩子注册
        hook_mod.clear()
        res_bypass, rt_bypass = self._run({"ai_hooks_enabled": True}, with_hook=False)
        args_bypass = rt_bypass.call_args[0][2]
        tool_rows_bypass = [m.get("content") for m in res_bypass.turn_messages
                            if m.get("role") == "tool"]
        self.assertEqual(args_off, args_bypass)
        self.assertEqual(tool_rows_off, tool_rows_bypass)


if __name__ == "__main__":
    unittest.main()
