# -*- coding: utf-8 -*-
"""列目录与 stat 之间版本目录被外部删掉，启动路径不许崩。

`_launch_into_server` 里 `max(ids, key=... .stat().st_mtime)`：installed_ids()
列完目录、stat 取 mtime 前版本目录被删（正在下载/杀毒/手滑），整条启动路径
死于未捕获 FileNotFoundError。现在走 `_latest_version_id`，消失的目录按
mtime=0 跳过。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.backend import BackendAPI  # noqa: E402


class LatestVersionRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        vdir = Path(self.tmp.name) / "versions"
        (vdir / "old").mkdir(parents=True)
        (vdir / "old" / "old.json").write_text("{}", "utf-8")
        # 「new」只出现在 ids 里，目录已经没了 —— 竞态现场
        self.inst = SimpleNamespace(versions_dir=lambda: vdir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_dir_is_skipped_not_fatal(self):
        picked = BackendAPI._latest_version_id(self.inst, ["new", "old"])
        self.assertEqual(picked, "old")

    def test_newest_existing_wins(self):
        import os
        vdir = self.inst.versions_dir()
        (vdir / "zzz").mkdir()
        # 用定值时间戳，不吃文件系统 mtime 粒度的亏
        os.utime(vdir / "old", (1000, 1000))
        os.utime(vdir / "zzz", (2000, 2000))
        self.assertEqual(
            BackendAPI._latest_version_id(self.inst, ["old", "zzz"]), "zzz")

    def test_all_missing_still_returns_first(self):
        picked = BackendAPI._latest_version_id(self.inst, ["ghost1", "ghost2"])
        self.assertEqual(picked, "ghost1")


if __name__ == "__main__":
    unittest.main()
