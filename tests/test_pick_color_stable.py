# -*- coding: utf-8 -*-
"""pick_color 跨进程确定性。

以前用内建 hash(name)：str 哈希有进程级随机化（PYTHONHASHSEED），同一个
任务名这次启动飞字是绿的下一次可能是紫的。换成 crc32 后，不同种子进程
必须算出同一种颜色。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CODE = (
    "import app.widgets as w; "
    "print('|'.join(w.pick_color(n) for n in "
    "['下载 Forge 47.2.0', '安装游戏 1.20.1', '导出整合包 default', 'x']))"
)


class PickColorStableTests(unittest.TestCase):
    def test_same_across_hash_seeds(self):
        outs = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed, QT_QPA_PLATFORM="offscreen")
            r = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            outs.append(r.stdout.strip())
        self.assertTrue(outs[0])
        self.assertEqual(len(set(outs)), 1,
                         f"同一批名字在不同 PYTHONHASHSEED 下颜色不同:\n{outs}")

    def test_same_within_one_process(self):
        from app.widgets import pick_color
        self.assertEqual(pick_color("Fabulous"), pick_color("Fabulous"))
        self.assertIn(pick_color("anything"), [
            "#2E9B6B", "#7C5CD6", "#3E7C4F", "#E8862E",
            "#D95568", "#2E9FB8", "#8A6FBD", "#5B8C5A",
        ])


if __name__ == "__main__":
    unittest.main()
