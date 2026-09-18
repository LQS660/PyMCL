# -*- coding: utf-8 -*-
"""批次 0：run_agent 的停止原因打标 + 异常落盘。

全部离线：chat 流程打桩，后端用空壳（runtime_context 自己会兜住）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import trace as trace_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.client import AIClientError
from mclauncher.ai.result import AgentResult, StopReason


def _tool_call(cid="c1", name="list_mods", args="{}"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}}


class StopReasonTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.trace_dir = Path(self._tmp.name)
        self._old_dir = trace_mod.TRACE_DIR
        trace_mod.TRACE_DIR = self.trace_dir

    def tearDown(self):
        trace_mod.TRACE_DIR = self._old_dir
        self._tmp.cleanup()

    def _trace_events(self):
        out = []
        for p in self.trace_dir.glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def _run(self, streams, run_tool="ok", **kw):
        """streams：每项要么是事件列表（一轮 chat_stream），要么是异常实例。"""
        sides = [item if isinstance(item, BaseException) else iter(item)
                 for item in streams]
        backend = SimpleNamespace()
        once = {"content": "", "tool_calls": [], "finish_reason": "stop"}
        with mock.patch.object(agent_mod, "chat_stream", side_effect=sides), \
             mock.patch.object(agent_mod, "chat_once", return_value=once), \
             mock.patch.object(agent_mod, "run_tool", return_value=run_tool):
            return agent_mod.run_agent(backend, {}, [], "帮我装个钠", **kw)


class StopReasonTests(StopReasonTestBase):
    def test_completed_after_tools(self):
        """执行过工具后的正常收尾 = COMPLETED。"""
        res = self._run([
            [{"type": "tool_calls", "tool_calls": [_tool_call()]}],
            [{"type": "delta", "text": "已经装好了。"}, {"type": "done"}],
        ])
        self.assertEqual(res.stop_reason, StopReason.COMPLETED)
        self.assertEqual(str(res), "已经装好了。")
        self.assertEqual(res.rounds_used, 2)

    def test_no_tool_call_first_round(self):
        """★1：模型只回文字没调工具 → NO_TOOL_CALL，UI 能据此提示。"""
        res = self._run([[{"type": "delta", "text": "好的，我帮你装钠。"},
                          {"type": "done"}]])
        self.assertEqual(res.stop_reason, StopReason.NO_TOOL_CALL)
        self.assertIn("帮你装钠", str(res))

    def test_max_rounds(self):
        """★3：撞上限 → MAX_ROUNDS，detail 带回合数。"""
        streams = [[{"type": "tool_calls", "tool_calls": [_tool_call()]}]] * 2
        with mock.patch.object(agent_mod, "MAX_TOOL_ROUNDS", 2):
            res = self._run(streams)
        self.assertEqual(res.stop_reason, StopReason.MAX_ROUNDS)
        self.assertIn("2/2", res.detail)
        self.assertEqual(res.rounds_used, 2)

    def test_truncated(self):
        """★4：finish_reason=length → TRUNCATED。"""
        res = self._run([[{"type": "delta", "text": "讲一半的排错方案"},
                          {"type": "done", "finish_reason": "length"}]])
        self.assertEqual(res.stop_reason, StopReason.TRUNCATED)
        self.assertIn("截断", str(res))

    def test_stream_failed(self):
        """★5：流式挂了、非流式兜底也空 → STREAM_FAILED，不再静默。"""
        res = self._run([AIClientError("接口超时", 504)])
        self.assertEqual(res.stop_reason, StopReason.STREAM_FAILED)
        self.assertEqual(str(res), "")

    def test_empty_response(self):
        res = self._run([[{"type": "done"}]])
        self.assertEqual(res.stop_reason, StopReason.EMPTY_RESPONSE)

    def test_pending_task(self):
        """★2：后台任务已排队 → PENDING_TASK，并带任务清单。"""
        res = self._run([
            [{"type": "tool_calls",
              "tool_calls": [_tool_call(name="install_mod", args='{"name": "钠"}')]}],
            [{"type": "delta", "text": "已经开始安装了。"}, {"type": "done"}],
        ], run_tool='{"task_id": "t1", "queued": true}')
        self.assertEqual(res.stop_reason, StopReason.PENDING_TASK)
        self.assertEqual(res.pending_tasks, [{"task_id": "t1", "name": "install_mod"}])

    def test_final_not_replayed(self):
        """★6：末轮空 content 时不得复读早前轮次的旧文本。"""
        res = self._run([
            [{"type": "delta", "text": "第一轮的旧话"},
             {"type": "tool_calls", "tool_calls": [_tool_call()]}],
            [{"type": "done"}],
        ])
        self.assertNotIn("第一轮的旧话", str(res))
        self.assertEqual(res.stop_reason, StopReason.EMPTY_RESPONSE)

    def test_result_is_str_compatible(self):
        """bridge/api.py 把返回值当纯文本用，str 兼容不能破。"""
        res = AgentResult("文本", stop_reason=StopReason.MAX_ROUNDS, detail="d")
        self.assertIsInstance(res, str)
        self.assertIn("文", res)
        self.assertEqual(res + "!", "文本!")
        json.dumps({"text": res})
        self.assertEqual(res.text, "文本")
        self.assertEqual(res.stop_reason, StopReason.MAX_ROUNDS)
        self.assertEqual(res.pending_tasks, [])


class TraceTests(StopReasonTestBase):
    def test_stream_exception_is_traced(self):
        """W0-4：流式异常不再静默，trace 里能看到 exc_type 与 round。"""
        self._run([RuntimeError("SSE 炸了")])
        events = self._trace_events()
        hit = [e for e in events if e.get("event") == "stream_exception"]
        self.assertTrue(hit, "stream_exception 必须落盘")
        self.assertEqual(hit[0]["exc_type"], "RuntimeError")
        self.assertEqual(hit[0]["round"], 1)

    def test_tool_exception_is_traced(self):
        """W0-4：工具执行异常带 tool_name 落盘。"""
        out = ai_tools.run_tool(SimpleNamespace(), "list_mods", {})
        self.assertTrue(str(out).startswith("工具失败"))
        hit = [e for e in self._trace_events() if e.get("event") == "tool_exception"]
        self.assertTrue(hit)
        self.assertEqual(hit[0]["tool_name"], "list_mods")

    def test_trace_never_raises(self):
        """trace 本身绝不能抛异常：目录指到一个文件路径上也要静默吞掉。"""
        bad = self.trace_dir / "not-a-dir"
        bad.write_text("x", encoding="utf-8")
        old = trace_mod.TRACE_DIR
        trace_mod.TRACE_DIR = bad
        try:
            trace_mod.record("whatever", exc=ValueError("x"))
        finally:
            trace_mod.TRACE_DIR = old


if __name__ == "__main__":
    unittest.main()
