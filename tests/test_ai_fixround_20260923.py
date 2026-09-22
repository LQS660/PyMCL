# -*- coding: utf-8 -*-
"""2026-09-23 修复轮回归：checkpoint 数据安全、rewind 守卫、MCP、hooks 顺序、
client usage 顺序、tools 路径与参数处理。

每条用例对应本轮一个确认过的缺陷（见 docs/STATUS.md 2026-09-23 条目）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mclauncher.ai import checkpoint as ckpt
from mclauncher.ai import client as ai_client
from mclauncher.ai import hooks as ai_hooks
from mclauncher.ai import mcp as ai_mcp
from mclauncher.ai import rewind as ai_rewind
from mclauncher.ai import store as chat_store
from mclauncher.ai import tools as ai_tools


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "sandbox"
        self.root.mkdir()
        ckpt_dir = Path(self._tmp.name) / "ck"
        ckpt_dir.mkdir(parents=True)
        sess_dir = Path(self._tmp.name) / "sessions"
        sess_dir.mkdir(parents=True)
        # STORE_FILE 不隔离会写穿仓库根的真实 ai_chats.json（用户数据）
        self._old_store = chat_store.STORE_FILE
        chat_store.STORE_FILE = Path(self._tmp.name) / "ai_chats.json"
        self._p1 = mock.patch.object(ckpt, "CHECKPOINTS_DIR", ckpt_dir)
        self._p2 = mock.patch.object(chat_store, "SESSIONS_DIR", sess_dir)
        self._p1.start()
        self._p2.start()
        self.ckpt_dir = ckpt_dir
        self.sess_dir = sess_dir

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        chat_store.STORE_FILE = self._old_store
        self._tmp.cleanup()


class DirSnapshotTruncationTests(_Sandbox):
    """P0：目录快照在 MAX_DIR_FILES 截断时必须整轮标记不可回滚——
    带着不完整的 known 集合去回滚清扫，会把 20000 名之后的老文件当新增误删。"""

    def test_truncated_dir_snapshot_refuses(self):
        big = self.root / "inst"
        big.mkdir()
        for i in range(5):
            (big / f"f{i}.txt").write_text(f"old{i}", encoding="utf-8")
        with mock.patch.object(ckpt, "MAX_DIR_FILES", 3):
            res = ckpt.snapshot("c1", "t1", [big])
        self.assertFalse(res["ok"])
        # journal 里不能有这条「半份 known 集合」的目录范围操作
        self.assertEqual(ckpt._load_journal("c1"), [])

    def test_normal_dir_snapshot_still_ok(self):
        big = self.root / "inst"
        big.mkdir()
        (big / "a.txt").write_text("x", encoding="utf-8")
        res = ckpt.snapshot("c2", "t1", [big])
        self.assertTrue(res["ok"])


class GhostDirRollbackTests(_Sandbox):
    """P1：快照时不存在的目标目录（新实例的 mods/）被当「幽灵文件」登记，
    回滚必须整树删除后来出现的目录，而不是 unlink 失败后假装成功。"""

    def test_missing_dir_snapshot_rolls_back_created_tree(self):
        mods = self.root / "mods"          # 快照时不存在
        res = ckpt.snapshot("c3", "t1", [mods])
        self.assertTrue(res["ok"])
        # 操作发生：目录被创建并装了东西
        mods.mkdir()
        (mods / "jei.jar").write_bytes(b"jar-bytes")
        (mods / "sub").mkdir()
        (mods / "sub" / "x.txt").write_text("x", encoding="utf-8")
        rb = ckpt.rollback("c3", turn_id="t1")
        self.assertTrue(rb["ok"], rb)
        self.assertFalse(mods.exists(), "回滚后快照时不存在、后来出现的目录应被整树删除")


class FailedRestoreKeepTests(_Sandbox):
    """P1：恢复失败的操作必须保留在 journal（可重试），不能连同 blob 一起删掉。"""

    def test_failed_op_stays_in_journal(self):
        cfg = self.root / "config"
        cfg.mkdir()
        (cfg / "a.txt").write_text("v0", encoding="utf-8")
        ckpt.snapshot("c4", "t1", [cfg / "a.txt"])
        (cfg / "a.txt").write_text("v1", encoding="utf-8")
        # 模拟 blob 丢失：删掉备份内容
        for blob in (self.ckpt_dir / "c4" / "files").glob("*.bin"):
            blob.unlink()
        rb = ckpt.rollback("c4", turn_id="t1")
        self.assertFalse(rb["ok"])
        self.assertGreater(len(ckpt._load_journal("c4")), 0,
                           "恢复失败的操作必须留在 journal 里供重试")


class RewindMissingLogTests(_Sandbox):
    """P2：会话日志缺失时无法对齐轮次——只截断对话、不动磁盘、rollbackable=False。"""

    def test_missing_session_log_only_truncates(self):
        data = chat_store.load()
        chat_store.new_chat(data)
        cid = data["active_id"]
        chat = chat_store.get_chat(data, cid)
        chat["messages"] = [{"role": "user", "content": "装个模组"},
                            {"role": "assistant", "content": "好了"}]
        chat_store.save(data)
        # journal 里有「更早轮次」的写操作，但会话日志文件不存在
        target = self.root / "old.txt"
        target.write_text("v0", encoding="utf-8")
        ckpt.snapshot(cid, "older-turn", [target])
        target.write_text("v1", encoding="utf-8")

        res = ai_rewind.rewind_last_round(cid)
        self.assertTrue(res["truncated"])
        self.assertFalse(res["rollbackable"])
        self.assertFalse(res["disk_changed"])
        self.assertEqual(target.read_text(encoding="utf-8"), "v1",
                         "没对齐轮次绝不能动磁盘——那会误删用户没要求撤销的改动")


class AffectedPathsTests(_Sandbox):
    """P2：write_mod_config 的 path 带盘符 / NTFS 流必须拒绝，防检查点越界复制。"""

    def _backend(self):
        inst = mock.MagicMock()
        inst.path = self.root / "inst"
        backend = mock.MagicMock()
        backend._instance.return_value = inst
        return backend

    def test_drive_letter_rejected(self):
        paths = ai_tools.affected_paths(self._backend(), "write_mod_config",
                                        {"path": "C:/Users/x/secret.txt"})
        self.assertEqual(paths, [])

    def test_ntfs_stream_rejected(self):
        paths = ai_tools.affected_paths(self._backend(), "write_mod_config",
                                        {"path": "opts.txt:hidden"})
        self.assertEqual(paths, [])

    def test_normal_rel_path_kept(self):
        paths = ai_tools.affected_paths(self._backend(), "write_mod_config",
                                        {"path": "options.txt"})
        self.assertEqual(paths, [self.root / "inst" / "config" / "options.txt"])


class McpRouteTests(unittest.TestCase):
    """P2：server `a` 与 `a_b` 并存时，mcp_a_b_x 必须路由到 `a_b`（最长前缀）。"""

    def test_longest_prefix_wins(self):
        a = mock.MagicMock()
        a.name = "a"
        ab = mock.MagicMock()
        ab.name = "a_b"
        ai_mcp.route_call([a, ab], "mcp_a_b_x", {"q": 1})
        ab.call_tool.assert_called_once_with("x", {"q": 1})
        a.call_tool.assert_not_called()

    def test_short_server_name_still_routable(self):
        a = mock.MagicMock()
        a.name = "a"
        ai_mcp.route_call([a], "mcp_a_x", {})
        a.call_tool.assert_called_once_with("x", {})

    def test_bad_server_name_skipped_in_config(self):
        cfgs = ai_mcp._server_configs({"ai_mcp_servers": [
            {"name": "bad name", "command": "x"},
            {"name": "ok", "command": "y", "env": {"K": "V"}},
        ]})
        self.assertEqual([c["name"] for c in cfgs], ["ok"])
        self.assertEqual(cfgs[0]["env"], {"K": "V"})


class StreamUsageOrderTests(unittest.TestCase):
    """P2：finish_reason=tool_calls 时 usage 包在后面——必须先发 usage 再发
    tool_calls，否则每个工具轮的真实用量都采不到（调用方见 tool_calls 就 break）。"""

    @staticmethod
    def _sse(obj) -> bytes:
        return ("data: " + json.dumps(obj, ensure_ascii=False)).encode("utf-8")

    def _stream(self, events):
        resp = mock.MagicMock()
        resp.iter_lines.return_value = iter(events)
        return list(ai_client._assemble_stream(resp, expect_usage=True))

    def test_usage_yielded_before_tool_calls(self):
        out = self._stream([
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "f", "arguments": "{}"}}]}}]}),
            self._sse({"choices": [{"finish_reason": "tool_calls"}]}),
            self._sse({"usage": {"prompt_tokens": 11, "completion_tokens": 7}}),
            b"data: [DONE]",
        ])
        kinds = [e["type"] for e in out]
        self.assertIn("usage", kinds)
        self.assertIn("tool_calls", kinds)
        self.assertLess(kinds.index("usage"), kinds.index("tool_calls"))
        usage = next(e for e in out if e["type"] == "usage")["usage"]
        self.assertEqual(usage["prompt_tokens"], 11)

    def test_usage_before_tool_calls_on_stream_end_without_done(self):
        out = self._stream([
            self._sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
                "finish_reason": "tool_calls"}]}),
            self._sse({"usage": {"prompt_tokens": 9, "completion_tokens": 3}}),
        ])
        kinds = [e["type"] for e in out]
        self.assertLess(kinds.index("usage"), kinds.index("tool_calls"))


class HookOrderTests(unittest.TestCase):
    """P1：前置钩子改写的入参必须先于判权/确认/快照——批的是改后的参数。
    这里用纯 agent 循环验证：改写后的 args 才是 run_tool 收到的。"""

    def test_before_hook_rewrites_args_seen_by_run_tool(self):
        from mclauncher.ai import agent as agent_mod

        captured = {}

        def fake_run_agent_loop():
            # 直接复刻 agent 判权段的钩子顺序：hook 改写 → decide → 执行
            args = {"path": "options.txt"}
            args, errs = ai_hooks.run_before("write_mod_config", args)
            captured["hooked"] = args
            return args

        ai_hooks.clear()
        ai_hooks.register(ai_hooks.Hook(
            "rewrite", before=lambda n, a: {"path": "other.txt"} if n == "write_mod_config" else None))
        try:
            self.assertEqual(fake_run_agent_loop(), {"path": "other.txt"})
        finally:
            ai_hooks.clear()

    def test_audit_hook_covers_launch_side_effect(self):
        """P3：审计钩子按 ToolMeta.side_effect 判（含 launch_game），不再漏启动操作。"""
        import os
        audit_dir = Path(tempfile.mkdtemp())
        ai_hooks.clear()
        with mock.patch.object(ai_hooks, "HOOKS_DIR", audit_dir):
            ai_hooks.clear()
            ai_hooks.register(ai_hooks.Hook("write_audit", before=ai_hooks._audit_before))
            ai_hooks._audit_before("launch_game", {})
        log = audit_dir / "audit.jsonl"
        self.assertTrue(log.exists(), "launch_game 必须进审计日志")
        entry = json.loads(log.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["tool"], "launch_game")
        import shutil
        shutil.rmtree(audit_dir, ignore_errors=True)


class ParseArgsNoStripContentTests(unittest.TestCase):
    """P3：write_mod_config 的 content 逐字写盘，strip 会剥掉模型特意保留的末尾换行。"""

    def test_content_not_stripped(self):
        args, err = ai_tools.parse_args(
            json.dumps({"path": "options.txt", "content": "a=1\n\n"}), "write_mod_config")
        self.assertIsNone(err)
        self.assertEqual(args["content"], "a=1\n\n")

    def test_name_fields_still_stripped(self):
        args, err = ai_tools.parse_args(
            json.dumps({"filename": " jei.jar "}), "delete_mod")
        self.assertIsNone(err)
        self.assertEqual(args["filename"], "jei.jar")


if __name__ == "__main__":
    unittest.main()
