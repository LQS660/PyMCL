# -*- coding: utf-8 -*-
"""变更可逆性（批次 1.1 / 1.3）：文件检查点 + rewind 共享实现。

验收口径（改造清单 1.1）：
- 一次对话内连续 3 轮写操作后能回滚到第 1 轮之前，磁盘字节级一致（sha256）；
- 回滚不误伤本次操作之外的文件（全量 路径+size+mtime 清单比对）；
- 快照磁盘占用可解释（usage() 报字节数）；超限/写失败不阻断、标记不可回滚；
- 目录范围快照回滚时清掉快照后新增的文件；文件级快照绝不碰父目录其他文件。
"""
from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mclauncher.ai import checkpoint as ckpt


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(root: Path) -> dict:
    """全量 路径+size+mtime 清单（验收里的「不误伤」比对口径）。"""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p)] = (st.st_size, round(st.st_mtime, 4))
    return out


class CheckpointTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "sandbox"
        self.root.mkdir()
        ckpt_dir = Path(self._tmp.name) / "ck"
        ckpt_dir.mkdir(parents=True)
        self._patch = mock.patch.object(ckpt, "CHECKPOINTS_DIR", ckpt_dir)
        self._patch.start()
        self.ckpt_dir = ckpt_dir

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class ThreeRoundRollbackTests(CheckpointTestBase):
    """连续 3 轮写操作 → 回滚到第 1 轮之前：sha256 逐文件一致 + 不误伤。"""

    def test_three_writes_rollback_byte_identical(self):
        cfg = self.root / "config"
        cfg.mkdir()
        target = cfg / "options.txt"
        bystander = cfg / "mine.txt"
        bystander.write_text("user's own file", encoding="utf-8")
        pre_manifest = _manifest(self.root)

        # 第 1 轮之前的基线：一个旧文件
        old = cfg / "old.txt"
        old.write_text("v0", encoding="utf-8")
        baseline = {str(p): _sha(p) for p in self.root.rglob("*") if p.is_file()}
        baseline_manifest = _manifest(self.root)

        chat, turn = "chat-3r", "t1"
        ckpt.begin_chat(chat)
        for i, content in enumerate(("v1", "v2", "v3")):
            snap = ckpt.snapshot(chat, turn, [old])
            self.assertTrue(snap["ok"], snap)
            old.write_text(content, encoding="utf-8")

        # 快照占用可解释：3 次操作、字节数即 3 个版本内容之和
        usage = ckpt.usage(chat)
        self.assertEqual(usage["ops"], 3)
        self.assertEqual(usage["bytes"], len(b"v0") + len(b"v1") + len(b"v2"))
        self.assertTrue(usage["rollbackable"])

        res = ckpt.rollback(chat, all_ops=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["restored_files"], 3)
        self.assertEqual(res["restored_bytes"], len(b"v0") + len(b"v1") + len(b"v2"))

        # 字节级一致（sha256 逐文件）
        after = {str(p): _sha(p) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, baseline)
        # 不误伤：size+mtime 全量清单与动手前一致（bystander 一个字节都没动）
        self.assertEqual(_manifest(self.root), baseline_manifest)
        self.assertEqual(bystander.read_text(encoding="utf-8"), "user's own file")
        self.assertNotIn(str(target), after)

    def test_rollback_last_turn_only(self):
        cfg = self.root / "config"
        cfg.mkdir()
        f = cfg / "a.txt"
        f.write_text("r0", encoding="utf-8")
        ckpt.snapshot("chat-t", "turn-1", [f])
        f.write_text("r1", encoding="utf-8")
        ckpt.snapshot("chat-t", "turn-2", [f])
        f.write_text("r2", encoding="utf-8")

        res = ckpt.rollback("chat-t")   # 默认回滚最近一个有操作的回合
        self.assertTrue(res["ok"])
        self.assertEqual(res["restored_files"], 1)
        self.assertEqual(f.read_text(encoding="utf-8"), "r1")

    def test_non_rollbackable_when_blob_write_fails(self):
        f = self.root / "x.txt"
        f.write_text("data", encoding="utf-8")
        with mock.patch.object(ckpt, "_store_blob", return_value=False):
            snap = ckpt.snapshot("chat-fail", "turn-9", [f])
        self.assertFalse(snap["ok"])          # 检查点写失败
        self.assertTrue(snap.get("reason"))   # 有可读原因（给 UI 告警）
        # 原操作不被阻断：文件仍能正常写
        f.write_text("new data", encoding="utf-8")
        self.assertEqual(f.read_text(encoding="utf-8"), "new data")
        self.assertFalse(ckpt.usage("chat-fail")["rollbackable"])


class ScopeTests(CheckpointTestBase):
    """目录范围 vs 文件范围：新增文件清不清，边界要卡准。"""

    def test_dir_scope_sweeps_new_files(self):
        target = self.root / "mods"
        target.mkdir()
        (target / "a.jar").write_bytes(b"A")
        ckpt.snapshot("chat-dir", "t", [target])
        (target / "b.jar").write_bytes(b"B")          # 快照后新增
        sub = target / "sub"
        sub.mkdir()
        (sub / "c.jar").write_bytes(b"C")             # 新增的子目录

        res = ckpt.rollback("chat-dir", all_ops=True)
        self.assertTrue(res["ok"])
        self.assertFalse((target / "b.jar").exists())
        self.assertFalse(sub.exists())
        self.assertEqual((target / "a.jar").read_bytes(), b"A")

    def test_file_scope_never_touches_parent(self):
        cfg = self.root / "config"
        cfg.mkdir()
        f = cfg / "x.toml"
        f.write_text("k=0", encoding="utf-8")
        ckpt.snapshot("chat-fs", "t", [f])
        user_new = cfg / "user-made.txt"
        user_new.write_text("user created this", encoding="utf-8")
        f.write_text("k=1", encoding="utf-8")

        ckpt.rollback("chat-fs", all_ops=True)
        self.assertEqual(f.read_text(encoding="utf-8"), "k=0")
        # 文件级快照：用户在父目录里自己建的文件绝不能被清掉
        self.assertTrue(user_new.exists())
        self.assertEqual(user_new.read_text(encoding="utf-8"), "user created this")

    def test_absence_tracking_for_renamed_files(self):
        """disable_mod 类操作：快照时不存在、操作后出现的文件，回滚必须删掉。"""
        mods = self.root / "mods"
        mods.mkdir()
        f = mods / "jei.jar"
        f.write_bytes(b"J")
        ckpt.snapshot("chat-abs", "t", [f, mods / "jei.jar.disabled"])
        f.rename(mods / "jei.jar.disabled")           # 模拟禁用改名

        ckpt.rollback("chat-abs", all_ops=True)
        self.assertTrue(f.exists())
        self.assertEqual(f.read_bytes(), b"J")
        self.assertFalse((mods / "jei.jar.disabled").exists())


class PruneTests(CheckpointTestBase):
    def test_keep_chats_prune(self):
        ckpt.begin_chat("chat-now")
        # 伪造 KEEP_CHATS 个更老的对话目录，begin_chat 应把最老的挤出去；
        # 当前对话目录刷新 mtime，保证它是最新的、绝不被清
        for i in range(ckpt.KEEP_CHATS + 3):
            d = self.ckpt_dir / f"old{i}"
            d.mkdir()
            (d / "files").mkdir()
            time.sleep(0.01)
        import os
        os.utime(self.ckpt_dir / "chat-now", None)
        ckpt.begin_chat("chat-now")
        remaining = {d.name for d in self.ckpt_dir.iterdir() if d.is_dir()}
        self.assertNotIn("old0", remaining)
        self.assertIn("chat-now", remaining)

    def test_journal_corrupt_returns_empty(self):
        (self.ckpt_dir / "chat-bad").mkdir()
        (self.ckpt_dir / "chat-bad" / "journal.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(ckpt.usage("chat-bad")["ops"], 0)
        res = ckpt.rollback("chat-bad", all_ops=True)
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
