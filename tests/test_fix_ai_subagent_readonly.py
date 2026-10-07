# -*- coding: utf-8 -*-
"""审计 05 P0-2 回归：子代理的「只读」契约必须有执行层硬约束。

修前只做了 schema 层过滤（`tools.select_tool_schemas` 把写工具从子代理的工具集里
摘掉），执行层没有任何对应校验：`_execute` 不检查模型发出的工具是否在已声明集合里，
`permission.decide` 也没有子代理分支。于是 acceptEdits / auto / edit / build / yolo
档下，子代理发出 `write_mod_config` / `install_mod` / `delete_mod` 会被真的执行
（审计 05 实测磁盘被写入 / 删除）。

修后在判权处（decisions 循环）与执行入口（_execute）各加一道：子代理上下文里
只读工具之外一律拒绝。主对话的写操作不受影响。

全部离线：模型打桩 + 临时目录，不联网、不碰真实数据。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import checkpoint as ckpt_mod
from mclauncher.ai.result import StopReason
from mclauncher.ai.tools import TOOL_META

WRITE_TOOL = "write_mod_config"
WRITE_ARGS = '{"path": "jei.toml", "content": "SUBAGENT-WROTE-THIS"}'


def _tc(name, args):
    return {"id": "c1", "type": "function",
            "function": {"name": name, "arguments": args}}


class _Backend:
    """最小后端：只够 write_mod_config 走通（get_instances / get_java_list / _instance）。"""

    def __init__(self, inst):
        self._inst = inst

    def get_instances(self):
        return [{"name": "default", "versions": 1, "mc_version": "1.20.1"}]

    def get_java_list(self, deep=False):
        return [{"major": 17}]

    def _instance(self, name):
        return self._inst


def _stream_calling(tool_name: str, args_json: str, declared_out: list | None = None):
    """第一轮发一次工具调用；之后收尾。按「上下文里有没有 tool 回执」判定轮次，
    这样无论拒绝发生在哪一层都只发一次。"""

    def stream(settings, messages, tools, http_cancel=None):
        if declared_out is not None:
            names = {s["function"]["name"] for s in (tools or [])}
            declared_out.append(tool_name in names)
        if not any(m.get("role") == "tool" for m in messages):
            yield {"type": "tool_calls", "tool_calls": [_tc(tool_name, args_json)]}
        else:
            yield {"type": "delta", "text": "done"}
            yield {"type": "done"}

    return stream


class SubagentCannotWrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "inst" / "config").mkdir(parents=True)
        (root / "inst" / "mods").mkdir(parents=True)
        (root / "inst" / "mods" / "evil.jar").write_bytes(b"JAR")
        self.inst_root = root / "inst"
        self.backend = _Backend(SimpleNamespace(name="default", path=self.inst_root))
        self.ckpt = root / "ck"
        self._patch = mock.patch.object(ckpt_mod, "CHECKPOINTS_DIR", self.ckpt)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _run(self, mode: str, tool: str, args: str, subagent: bool,
             declared_out: list | None = None):
        settings = {"ai_permission_mode": mode, "ai_session_id": "sub-fix"}
        if subagent:
            settings["ai_subagent"] = True
        with mock.patch.object(agent_mod, "chat_stream",
                               side_effect=_stream_calling(tool, args, declared_out)):
            return agent_mod.run_agent(self.backend, settings, [], "动手吧")

    def test_subagent_cannot_write_config_in_any_mode(self):
        for mode in ("yolo", "acceptEdits", "auto", "autoEdit", "edit", "build", "default"):
            with self.subTest(mode=mode):
                target = self.inst_root / "config" / "jei.toml"
                if target.exists():
                    target.unlink()
                res = self._run(mode, WRITE_TOOL, WRITE_ARGS, subagent=True)
                self.assertEqual(res.stop_reason, StopReason.COMPLETED)
                self.assertFalse(target.exists(),
                                 f"{mode} 档下子代理真的写盘了：{target}")
        # 清理：最后一次运行可能留下文件，不影响其它用例（每个用例独立 tmp）

    def test_subagent_write_is_denied_not_asked(self):
        """拒绝理由要落到 tool 回执里，模型看得到「子代理只读」。"""
        seen: list[str] = []

        def stream(settings, messages, tools, http_cancel=None):
            if not any(m.get("role") == "tool" for m in messages):
                yield {"type": "tool_calls", "tool_calls": [_tc(WRITE_TOOL, WRITE_ARGS)]}
            else:
                row = [m.get("content") for m in messages if m.get("role") == "tool"][-1]
                seen.append(str(row))
                yield {"type": "delta", "text": "好"}
                yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            agent_mod.run_agent(self.backend,
                                {"ai_subagent": True, "ai_permission_mode": "yolo"},
                                [], "动手吧")
        self.assertTrue(seen, "工具回执没进上下文")
        self.assertIn("子代理只读", seen[-1])

    def test_subagent_cannot_install_or_delete(self):
        for tool, args, check in [
            ("install_mod", '{"name": "sodium"}', lambda: True),
            ("delete_mod", '{"filename": "evil.jar"}', lambda: True),
        ]:
            with self.subTest(tool=tool):
                if tool == "install_mod":
                    with mock.patch.object(agent_mod, "run_tool") as rt:
                        self._run("yolo", tool, args, subagent=True)
                    self.assertEqual(rt.call_count, 0,
                                     "子代理不该执行写工具（run_tool 被调用了）")
                else:
                    target = self.inst_root / "mods" / "evil.jar"
                    self._run("yolo", tool, args, subagent=True)
                    self.assertTrue(target.exists(), "子代理把模组删了")

    def test_subagent_cannot_dispatch_subagent(self):
        """dispatch_subagent 是 readonly，但子代理不许再派生（schema 层已剔除）。"""
        with mock.patch.object(agent_mod, "run_subagent") as rs:
            rs.return_value = json.dumps({"ok": True, "answer": "x"}, ensure_ascii=False)
            self._run("yolo", "dispatch_subagent", '{"task": "再派一个"}', subagent=True)
        self.assertEqual(rs.call_count, 0, "子代理不该再派生子代理")

    def test_main_agent_writes_normally(self):
        """主对话（无 ai_subagent）在 acceptEdits 档下写操作必须照常执行。"""
        res = self._run("acceptEdits", WRITE_TOOL, WRITE_ARGS, subagent=False)
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        target = self.inst_root / "config" / "jei.toml"
        self.assertTrue(target.exists(), "主对话的写操作被误伤了")
        self.assertEqual(target.read_text(encoding="utf-8"), "SUBAGENT-WROTE-THIS")

    def test_main_agent_can_still_dispatch_subagent(self):
        with mock.patch.object(agent_mod, "run_subagent") as rs:
            rs.return_value = json.dumps({"ok": True, "answer": "结论"}, ensure_ascii=False)
            self._run("acceptEdits", "dispatch_subagent", '{"task": "查日志"}',
                      subagent=False)
        self.assertEqual(rs.call_count, 1, "主对话派发子代理被误伤")

    def test_readonly_tools_still_work_in_subagent(self):
        """只读工具不受影响：子代理照常能读状态。"""
        executed: list[str] = []

        def stream(settings, messages, tools, http_cancel=None):
            if not any(m.get("role") == "tool" for m in messages):
                yield {"type": "tool_calls",
                       "tool_calls": [_tc("get_launcher_state", "{}")]}
            else:
                executed.append("ok")
                yield {"type": "delta", "text": "状态读到了"}
                yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream):
            res = agent_mod.run_agent(self.backend,
                                      {"ai_subagent": True, "ai_permission_mode": "yolo"},
                                      [], "看看状态")
        self.assertTrue(executed, "只读工具没执行")
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)


class ExecutionLayerGuardIsIndependent(unittest.TestCase):
    """执行层自己也要挡：不能只靠判权那一层的顺序。"""

    def test_every_write_tool_is_blocked_by_execute_layer(self):
        """直接调 run_agent 且让判权放行（yolo），执行层仍须拒绝写工具。"""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "inst" / "config").mkdir(parents=True)
            backend = _Backend(SimpleNamespace(name="default", path=root / "inst"))
            with mock.patch.object(ckpt_mod, "CHECKPOINTS_DIR", root / "ck"), \
                 mock.patch.object(agent_mod, "chat_stream",
                                   side_effect=_stream_calling(WRITE_TOOL, WRITE_ARGS)):
                agent_mod.run_agent(
                    backend, {"ai_subagent": True, "ai_permission_mode": "yolo"},
                    [], "动手吧")
            # 流式脚本第一轮就发写调用；无论拒绝发生在哪一层，磁盘都不能变
            self.assertFalse((root / "inst" / "config" / "jei.toml").exists())

    def test_tool_meta_readonly_flag_is_the_criterion(self):
        """判定依据就是 TOOL_META.readonly —— 写工具集合非空，别把判据写反。"""
        writes = [n for n, m in TOOL_META.items() if not m.readonly]
        self.assertIn("write_mod_config", writes)
        self.assertIn("delete_mod", writes)
        self.assertIn("install_mod", writes)
        self.assertTrue(TOOL_META["get_launcher_state"].readonly)


if __name__ == "__main__":
    unittest.main()
