# -*- coding: utf-8 -*-
"""扫系统 Java：候选本身就是一个 JDK 家目录时也得认出来。

`find_system_javas` 往 `_walk_javas` 里塞的候选有两类：`JAVA_HOME` 和
`which java` 推出来的**家目录本身**，以及 `C:\\Program Files` 这种**上级目录**。
`_walk_javas` 原来只翻 root 的子目录、翻到名叫 bin 的还专门跳过，于是第一类
候选一个都认不出来 —— `<JDK>\\bin\\java.exe` 谁都碰不到。

本机实测就是这么撞上的：Microsoft OpenJDK 17 装在
`C:\\Program Files\\Microsoft\\jdk-17.0.20.8-hotspot`，`java` 就在 PATH 上，
启动器报「没找到 Java」。Program Files 那圈 glob 也救不了：它只看子目录名里
有没有 java/jdk/jre 字样，而这台机器上那一层叫 `Microsoft`。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mclauncher import java as java_mod

EXE = "java.exe" if os.name == "nt" else "java"


def _fake_jdk(home: Path) -> Path:
    (home / "bin").mkdir(parents=True, exist_ok=True)
    exe = home / "bin" / EXE
    exe.write_bytes(b"not really java")
    for junk in ("conf", "include", "legal", "lib"):
        (home / junk).mkdir(exist_ok=True)
    return exe


class WalkJavasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _walk(self, start: Path) -> list[str]:
        found: list[Path] = []
        java_mod._walk_javas(start, found, set())
        return [str(p) for p in found]

    def test_candidate_is_the_jdk_home_itself(self):
        """JAVA_HOME / which java 给的就是这一种。"""
        home = self.root / "jdk-17.0.20.8-hotspot"
        exe = _fake_jdk(home)
        self.assertEqual(self._walk(home), [str(exe)])

    def test_candidate_is_the_bin_dir_itself(self):
        home = self.root / "jdk-21"
        exe = _fake_jdk(home)
        self.assertEqual(self._walk(home / "bin"), [str(exe)])

    def test_candidate_is_a_parent_directory(self):
        """`C:\\Program Files` 那一类：JDK 埋在下面，还可能隔着一层厂商目录。"""
        exe = _fake_jdk(self.root / "Microsoft" / "jdk-17.0.20.8-hotspot")
        self.assertEqual(self._walk(self.root), [str(exe)])

    def test_no_duplicates_across_candidates(self):
        """同一个 JDK 被两类候选各命中一次，只该进结果一回。"""
        home = self.root / "vendor" / "jdk-17"
        exe = _fake_jdk(home)
        found: list[Path] = []
        seen: set = set()
        java_mod._walk_javas(self.root, found, seen)
        java_mod._walk_javas(home, found, seen)
        self.assertEqual([str(p) for p in found], [str(exe)])

    def test_directory_without_java_finds_nothing(self):
        (self.root / "notjava" / "bin").mkdir(parents=True)
        self.assertEqual(self._walk(self.root), [])


if __name__ == "__main__":
    unittest.main()
