# -*- coding: utf-8 -*-
"""变更预览（批次 1.2）与 rewind 共享实现（批次 1.3 方案甲）。

- write_mod_config 确认卡给 unified diff（+/- 前缀、保留上下文行）；
- delete_* 给将删除的文件数与总字节数；install_* 给目标路径与预计新增文件数；
- 变更过大降级（「变更过大，见 <路径>」）不卡死；
- 界面语言 en 时预览标签全英文；
- rewind：对话截回上一轮之前 + 该轮写操作字节级还原；快照失败轮次明确不可回滚。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mclauncher import i18n
from mclauncher.ai import checkpoint as ckpt
from mclauncher.ai import preview as ai_preview
from mclauncher.ai import rewind as ai_rewind
from mclauncher.ai import store as chat_store


class BackendStub:
    """最小 backend：只提供 _instance(name).path 供 preview/affected_paths 用。"""

    def __init__(self, inst_dir: Path):
        self._dir = inst_dir

    class _Inst:
        def __init__(self, path: Path):
            self.path = path

    def _instance(self, name: str):
        return BackendStub._Inst(self._dir)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.inst = Path(self._tmp.name) / "demo"
        (self.inst / "config").mkdir(parents=True)
        (self.inst / "mods").mkdir()
        self.backend = BackendStub(self.inst)
        self._lang = i18n.current_language()

    def tearDown(self):
        i18n._current_lang = self._lang
        self._tmp.cleanup()

    def test_write_config_diff_has_unified_markers(self):
        cfg = self.inst / "config" / "jei.toml"
        cfg.write_text("a = 1\nb = 2\n", encoding="utf-8")
        pv = ai_preview.change_preview(self.backend, "write_mod_config",
                                       {"path": "jei.toml", "content": "a = 1\nb = 9\n"})
        self.assertEqual(pv["kind"], "diff")
        self.assertTrue(any(x.startswith("-") and "b = 2" in x for x in pv["lines"]))
        self.assertTrue(any(x.startswith("+") and "b = 9" in x for x in pv["lines"]))
        self.assertFalse(pv["too_large"])

    def test_write_config_new_file_marked(self):
        pv = ai_preview.change_preview(self.backend, "write_mod_config",
                                       {"path": "new.toml", "content": "x = 1\n"})
        self.assertTrue(any("（新建文件）" in x for x in pv["lines"]))

    def test_oversized_diff_degrades_without_blocking(self):
        big = "\n".join(f"line{i} = {i}" for i in range(3000))
        with mock.patch.object(ai_preview.artifacts, "store", return_value="cache/ai_results/x.txt"):
            pv = ai_preview.change_preview(self.backend, "write_mod_config",
                                           {"path": "big.toml", "content": big})
        self.assertTrue(pv["too_large"])
        self.assertLessEqual(len(pv["lines"]), ai_preview.MAX_PREVIEW_LINES + 2)
        self.assertTrue(any("cache/ai_results/x.txt" in x for x in pv["lines"]))

    def test_delete_mod_counts_files_and_bytes(self):
        jar = self.inst / "mods" / "jei.jar"
        jar.write_bytes(b"J" * 2048)
        pv = ai_preview.change_preview(self.backend, "delete_mod", {"filename": "jei.jar"})
        self.assertEqual(pv["kind"], "summary")
        joined = "\n".join(pv["lines"])
        self.assertIn("mods/jei.jar", joined)
        self.assertIn("2.0 KB", joined)

    def test_delete_instance_reports_stats(self):
        (self.inst / "saves").mkdir()
        (self.inst / "saves" / "w" / "level.dat").parent.mkdir(parents=True)
        (self.inst / "saves" / "w" / "level.dat").write_bytes(b"L" * 10)
        pv = ai_preview.change_preview(self.backend, "delete_instance", {"name": "demo"})
        joined = "\n".join(pv["lines"])
        self.assertIn("demo/", joined)
        self.assertIn("不可恢复", joined)

    def test_install_mod_shows_target_and_count(self):
        pv = ai_preview.change_preview(self.backend, "install_mod", {"name": "钠"})
        joined = "\n".join(pv["lines"])
        self.assertIn(str(self.inst / "mods"), joined)
        self.assertIn("预计新增文件数", joined)

    def test_en_labels_are_english(self):
        i18n._current_lang = "en"
        pv = ai_preview.change_preview(self.backend, "install_mod", {"name": "sodium"})
        self.assertEqual(pv["head"], "Install target:")
        cfg = self.inst / "config" / "x.toml"
        cfg.write_text("a=1\n", encoding="utf-8")
        pv2 = ai_preview.change_preview(self.backend, "write_mod_config",
                                        {"path": "x.toml", "content": "a=2\n"})
        self.assertEqual(pv2["head"], "Changes to be written:")
        self.assertTrue(any("+a=2" in x for x in pv2["lines"]))
        i18n._current_lang = "zh_CN"
        pv3 = ai_preview.change_preview(self.backend, "install_mod", {"name": "钠"})
        self.assertNotEqual(pv3["head"], "Install target:")

    def test_readonly_tools_have_no_preview(self):
        self.assertIsNone(ai_preview.change_preview(self.backend, "list_mods", {}))


class RewindTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        ckpt_dir = self.root / "ck"
        self._store_p = mock.patch.object(chat_store, "STORE_FILE", self.root / "ai_chats.json")
        self._ckpt_p = mock.patch.object(ckpt, "CHECKPOINTS_DIR", ckpt_dir)
        self._sess_p = mock.patch.object(chat_store, "SESSIONS_DIR", self.root / "sessions")
        for p in (self._store_p, self._ckpt_p, self._sess_p):
            p.start()
        self.root.mkdir(exist_ok=True)

    def tearDown(self):
        for p in (self._sess_p, self._ckpt_p, self._store_p):
            p.stop()
        self._tmp.cleanup()

    def test_rewind_truncates_and_restores_disk(self):
        # 对话里两轮：第一轮带写操作，第二轮只聊天
        data = chat_store.load()
        cid = data["active_id"]
        chat = chat_store.get_chat(data, cid)
        chat["messages"] = [
            {"role": "user", "content": "帮我把 a 改成 1"},
            {"role": "assistant", "content": "好"},
            {"role": "user", "content": "今天天气如何"},
            {"role": "assistant", "content": "不错"},
        ]
        chat_store.save(data)

        f = self.root / "work" / "a.txt"
        f.parent.mkdir()
        f.write_text("v0", encoding="utf-8")
        ckpt.snapshot(cid, "turn-A", [f])
        f.write_text("v1", encoding="utf-8")
        # 会话事件日志：最后开始的回合是 turn-B（纯聊天，没有写操作）
        sess = self.root / "sessions"
        sess.mkdir()
        with open(sess / f"{cid}.jsonl", "w", encoding="utf-8") as fh:
            fh.write('{"event": "TurnStarted", "turn_id": "turn-A"}\n')
            fh.write('{"event": "TurnCompleted", "turn_id": "turn-A"}\n')
            fh.write('{"event": "TurnStarted", "turn_id": "turn-B"}\n')

        res = ai_rewind.rewind_last_round(cid)
        self.assertTrue(res["ok"])
        self.assertTrue(res["truncated"])
        # 最近一轮是纯聊天：对话截断，但磁盘不该被回滚（turn-A 的改动保留）
        self.assertFalse(res["disk_changed"])
        self.assertEqual(f.read_text(encoding="utf-8"), "v1")
        data2 = chat_store.load()
        chat2 = chat_store.get_chat(data2, cid)
        self.assertEqual([m["role"] for m in chat2["messages"]], ["user", "assistant"])
        self.assertEqual(chat2["messages"][0]["content"], "帮我把 a 改成 1")

        # 再撤一轮：这次轮到 turn-A（写操作轮）→ 对话 + 磁盘一起还原
        res2 = ai_rewind.rewind_last_round(cid)
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["disk_changed"])
        self.assertEqual(res2["restored_files"], 1)
        self.assertEqual(f.read_text(encoding="utf-8"), "v0")
        data3 = chat_store.load()
        self.assertEqual(chat_store.get_chat(data3, cid)["messages"], [])

    def test_rewind_takes_whole_turn_with_steer(self):
        """入库的插话是 user 消息，但不是回合开头：撤回要撤整个回合，不能只截到插的那句。"""
        data = chat_store.load()
        cid = data["active_id"]
        chat = chat_store.get_chat(data, cid)
        call = {"id": "c1", "type": "function",
                "function": {"name": "install_mod", "arguments": "{}"}}
        chat["messages"] = [
            {"role": "user", "content": "装钠"},
            {"role": "assistant", "content": "装好了"},
            {"role": "user", "content": "再装 Iris"},
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "content": "ok", "tool_call_id": "c1"},
            {"role": "user", "content": "顺便装 Sodium Extra", "id": "steer_t2_0"},
            {"role": "assistant", "content": "都装好了"},
        ]
        chat_store.save(data)
        res = ai_rewind.rewind_last_round(cid)
        self.assertTrue(res["truncated"])
        msgs = chat_store.get_chat(chat_store.load(), cid)["messages"]
        self.assertEqual([m["content"] for m in msgs], ["装钠", "装好了"])

    def test_rewind_empty_chat_is_noop(self):
        data = chat_store.load()
        cid = data["active_id"]
        res = ai_rewind.rewind_last_round(cid)
        self.assertTrue(res["ok"])
        self.assertFalse(res["truncated"])


if __name__ == "__main__":
    unittest.main()
