# -*- coding: utf-8 -*-
"""审计 05 P1-2 回归：检查点回滚不得删掉「快照前就存在的空目录」。

修前 `checkpoint._apply_op` 的 `known_dirs` 只从「有 sha256 的文件」的父目录推导
（`{str(Path(f["path"]).parent) for f in files if f.get("sha256")}`），空目录永远
进不了集合；`_sweep_new_entries` 于是把用户手工建的空目录当「快照后新增」rmtree 掉
（审计 05 实测 `empty_but_mine/` 消失）。

修后快照时把目录树里的目录项（含空目录）一并登记，回滚只删「快照后才出现的」目录。

全部离线：临时目录，不碰真实 .minecraft。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mclauncher.ai import checkpoint as ckpt


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.sandbox = base / "inst"
        self.sandbox.mkdir()
        ck = base / "ck"
        ck.mkdir()
        self._patch = mock.patch.object(ckpt, "CHECKPOINTS_DIR", ck)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class EmptyDirSurvivesRollback(_Base):
    def test_preexisting_empty_dir_survives(self):
        """快照前就存在的空目录，回滚后必须还在。"""
        (self.sandbox / "mods").mkdir()
        (self.sandbox / "mods" / "a.jar").write_bytes(b"A")
        empty = self.sandbox / "empty_but_mine"
        empty.mkdir()
        notes = self.sandbox / "user_notes"
        notes.mkdir()
        (notes / "keep.txt").write_text("mine", encoding="utf-8")

        snap = ckpt.snapshot("chat-empty", "t1", [self.sandbox])
        self.assertTrue(snap["ok"], snap)
        (self.sandbox / "mods" / "new_mod.jar").write_bytes(b"NEW")

        res = ckpt.rollback("chat-empty", all_ops=True)
        self.assertTrue(res["ok"], res)
        self.assertFalse((self.sandbox / "mods" / "new_mod.jar").exists(),
                         "快照后新增的文件没清掉")
        self.assertTrue(empty.is_dir(),
                        "快照前就存在的空目录被回滚清扫误删了")
        self.assertTrue(notes.is_dir())
        self.assertEqual((notes / "keep.txt").read_text(encoding="utf-8"), "mine")

    def test_new_dir_after_snapshot_is_swept(self):
        """快照后新建的目录（含空目录）仍然要清掉。"""
        (self.sandbox / "mods").mkdir()
        (self.sandbox / "mods" / "a.jar").write_bytes(b"A")
        ckpt.snapshot("chat-new", "t1", [self.sandbox])
        fresh = self.sandbox / "fresh_empty"
        fresh.mkdir()
        deep = self.sandbox / "sub" / "deeper"
        deep.mkdir(parents=True)

        res = ckpt.rollback("chat-new", all_ops=True)
        self.assertTrue(res["ok"], res)
        self.assertFalse(fresh.exists(), "快照后新建的空目录没被清掉")
        self.assertFalse((self.sandbox / "sub").exists())

    def test_nested_preexisting_empty_dirs_survive(self):
        """多层已存在的空目录：整条链都要留下。"""
        a = self.sandbox / "config" / "nested" / "empty"
        a.mkdir(parents=True)
        (self.sandbox / "mods").mkdir()
        ckpt.snapshot("chat-nested", "t1", [self.sandbox])
        (self.sandbox / "mods" / "x.jar").write_bytes(b"X")

        ckpt.rollback("chat-nested", all_ops=True)
        self.assertTrue(a.is_dir(), "多层空目录链被误删")
        self.assertFalse((self.sandbox / "mods" / "x.jar").exists())

    def test_file_scope_still_touches_nothing_else(self):
        """文件级快照的既有承诺不变：绝不碰父目录里的其他条目。"""
        cfg = self.sandbox / "config"
        cfg.mkdir()
        empty = cfg / "empty_sibling"
        empty.mkdir()
        f = cfg / "x.toml"
        f.write_text("k=0", encoding="utf-8")
        ckpt.snapshot("chat-fs", "t1", [f])
        f.write_text("k=1", encoding="utf-8")

        ckpt.rollback("chat-fs", all_ops=True)
        self.assertEqual(f.read_text(encoding="utf-8"), "k=0")
        self.assertTrue(empty.is_dir())

    def test_journal_records_dirs(self):
        """快照的 journal 条目里要登记目录项（含空目录），这是修复的落点。"""
        empty = self.sandbox / "empty_but_mine"
        empty.mkdir()
        ckpt.snapshot("chat-j", "t1", [self.sandbox])
        ops = ckpt._load_journal("chat-j")
        self.assertEqual(len(ops), 1)
        known = ops[0].get("known_dirs") or []
        self.assertIn(str(empty.resolve()), known,
                      f"空目录没进 known_dirs：{known}")
        # 目录范围本身也要在 dirs 里（回滚清扫的入口）
        self.assertIn(str(self.sandbox.resolve()), ops[0].get("dirs") or [])

    def test_truncated_snapshot_still_refuses(self):
        """截断保护不变：目录文件数超限 → ok=False，不产生可回滚记录。"""
        (self.sandbox / "mods").mkdir()
        for i in range(5):
            (self.sandbox / "mods" / f"m{i}.jar").write_bytes(b"x")
        with mock.patch.object(ckpt, "MAX_DIR_FILES", 2):
            snap = ckpt.snapshot("chat-trunc", "t1", [self.sandbox])
        self.assertFalse(snap["ok"])
        self.assertIn("不可回滚", snap["reason"])


class EmptyDirInNewlyCreatedInstance(_Base):
    """delete_instance 类整目录快照 + 用户预留空目录的组合。"""

    def test_user_reserved_dirs_survive_instance_wide_rollback(self):
        for name in ("saves", "resourcepacks", "shaderpacks", "screenshots"):
            (self.sandbox / name).mkdir()
        (self.sandbox / "mods").mkdir()
        (self.sandbox / "mods" / "a.jar").write_bytes(b"A")
        ckpt.snapshot("chat-inst", "t1", [self.sandbox])
        (self.sandbox / "mods" / "b.jar").write_bytes(b"B")

        ckpt.rollback("chat-inst", all_ops=True)
        for name in ("saves", "resourcepacks", "shaderpacks", "screenshots"):
            self.assertTrue((self.sandbox / name).is_dir(),
                            f"用户预留的空目录 {name}/ 被误删")
        self.assertFalse((self.sandbox / "mods" / "b.jar").exists())


if __name__ == "__main__":
    unittest.main()
