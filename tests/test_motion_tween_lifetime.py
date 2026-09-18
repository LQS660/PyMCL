# -*- coding: utf-8 -*-
"""`motion.tween` 的 setter 不能打在已经析构的控件上。

补间动画以前没有父对象、靠 `_TWEENS` 续命：侧栏分组还在展开（160~180ms），
用户一拖动重排，`_rebuild_sidebar` 把整条侧栏 deleteLater 掉，剩下的每一帧
`host.setMaximumHeight` 都打在死控件上 —— `RuntimeError: Internal C++ object
already deleted` 从事件循环里冒出来，跟 ThumbnailTile / call_async / 两参
singleShot 那三批是同一种病：**回调活得比控件久**。

修法是给 tween 一个 `context`：动画挂在它名下，控件先死动画随它析构，
valueChanged / finished 都不会再发。下面的扫描保证 app/ 里每一处 tween 都给了。
顺手把 ThumbnailTile 旧写法的形状（在 `destroyed` 里连 lambda / 连 self 的方法）
也钉死：那条路 PySide 抛的是 SystemError，`drop_if_gone` 接不住。
"""
from __future__ import annotations

import ast
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app import motion  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [ROOT / "app", ROOT / "main.py"]


class TweenBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._motion_ok = motion.ui_motion_ok
        motion.ui_motion_ok = lambda: True  # 别让系统「关闭动画」把补间短路成瞬时
        motion._TWEENS.clear()
        self.escaped: list[str] = []
        self._hooks = (sys.excepthook, sys.unraisablehook)
        sys.excepthook = lambda t, v, tb: self.escaped.append(
            f"{t.__name__}: {str(v).splitlines()[0]}")
        sys.unraisablehook = lambda a: self.escaped.append(
            f"unraisable {type(a.exc_value).__name__}: {a.exc_value}")

    def tearDown(self):
        sys.excepthook, sys.unraisablehook = self._hooks
        motion.ui_motion_ok = self._motion_ok
        motion._TWEENS.clear()

    def _spin(self, ms: int):
        """让事件循环跑 ms 毫秒（动画靠定时器推进），槽里漏出来的异常一并记下。"""
        deadline = time.monotonic() + ms / 1000.0
        while time.monotonic() < deadline:
            try:
                self.app.processEvents(QEventLoop.AllEvents, 20)
            except Exception as exc:  # noqa: BLE001 - 这里就是要抓漏网的
                self.escaped.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
            time.sleep(0.005)

    def test_setter_stops_when_the_context_dies(self):
        host = QWidget()
        calls: list = []

        def setter(v):
            host.setMaximumHeight(int(v))
            calls.append(v)

        anim = motion.tween(setter, 0, 100, ms=150, context=host)
        self._spin(40)
        seen = len(calls)
        self.assertGreater(seen, 0, "动画根本没跑起来")
        shiboken6.delete(host)
        self._spin(250)
        self.assertEqual(self.escaped, [], "控件死了 setter 还在往死控件上打")
        self.assertEqual(len(calls), seen, "context 没了之后 setter 不该再被调")
        self.assertFalse(shiboken6.isValid(anim), "动画该随 context 一起析构")
        motion._prune_tweens()
        self.assertEqual(motion._TWEENS, [], "死掉的补间还赖在寄存处")

    def test_without_context_it_really_does_blow_up(self):
        """证明上面那条不是空转：不给 context，同一段代码就是会炸。"""
        host = QWidget()
        motion.tween(lambda v: host.setMaximumHeight(int(v)), 0, 100, ms=150)
        self._spin(40)
        shiboken6.delete(host)
        self._spin(250)
        self.assertTrue(any("already deleted" in line for line in self.escaped),
                        f"本来就该炸的路子没炸: {self.escaped}")

    def test_finishes_normally_and_hands_ownership_back(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        done: list = []
        anim = motion.tween(lambda v: host.setMaximumHeight(int(v)), 0, 100, ms=60,
                            on_done=lambda: done.append(1), context=host)
        self._spin(300)
        self.assertEqual(done, [1])
        self.assertEqual(host.maximumHeight(), 100)
        self.assertEqual(self.escaped, [])
        self.assertNotIn(anim, motion._TWEENS)
        self.assertTrue(shiboken6.isValid(anim), "调用方还拿着引用，跑完不该被拆")
        self.assertIsNone(anim.parent(), "跑完该把所有权还给 Python，别在 context 名下越积越多")

    def test_interrupted_by_stop_is_released_too(self):
        """侧栏分组连点：上一条被 stop() 打断，也得从寄存处摘掉。"""
        host = QWidget()
        self.addCleanup(host.deleteLater)
        anim = motion.tween(lambda v: host.setMaximumHeight(int(v)), 0, 100, ms=300,
                            context=host)
        self._spin(40)
        anim.stop()
        self._spin(60)
        self.assertNotIn(anim, motion._TWEENS)
        self.assertEqual(self.escaped, [])

    def test_motion_off_takes_the_shortcut(self):
        motion.ui_motion_ok = lambda: False
        host = QWidget()
        self.addCleanup(host.deleteLater)
        done: list = []
        self.assertIsNone(motion.tween(lambda v: host.setMaximumHeight(int(v)), 0, 100,
                                       on_done=lambda: done.append(1), context=host))
        self.assertEqual(host.maximumHeight(), 100)
        self.assertEqual(done, [1])


def _mentions_self(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "self" for n in ast.walk(node))


def _is_tween_call(func: ast.AST) -> bool:
    return (isinstance(func, ast.Name) and func.id == "tween") or (
        isinstance(func, ast.Attribute) and func.attr == "tween")


def scan_tweens_without_context(tree: ast.Module) -> list[int]:
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _is_tween_call(node.func)
            and not any(kw.arg == "context" for kw in node.keywords)]


def scan_destroyed_hooks(tree: ast.Module) -> list[tuple[int, str]]:
    """`self.destroyed.connect(...)`，或任何 `x.destroyed.connect(lambda …)`。

    `destroyed` 发出来时 C++ 那半边已经没了：回调里再碰 self（哪怕只是拿
    self 的方法去 disconnect）都是往死对象上摸，PySide 抛的是 SystemError。
    别人的 destroyed 连到自己的绑定方法上（`other.destroyed.connect(self._gone)`）
    不算：接收者 self 活着，Qt 会在 self 先死时自动断开。
    """
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect" and node.args):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Attribute) and target.attr == "destroyed"):
            continue
        callback = node.args[0]
        own = isinstance(target.value, ast.Name) and target.value.id == "self"
        if own or isinstance(callback, ast.Lambda):
            hits.append((node.lineno, ast.unparse(node)[:100]))
    return hits


class LifetimeScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {}
        for target in SCAN_ROOTS:
            paths = sorted(target.rglob("*.py")) if target.is_dir() else [target]
            for path in paths:
                cls.trees[path] = ast.parse(path.read_text(encoding="utf-8"),
                                            filename=str(path))

    def test_scan_actually_sees_tween_calls(self):
        """先证明扫描器没空转：一处 tween 都没数到，下面那条永远是绿的。"""
        seen = sum(
            1 for tree in self.trees.values() for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _is_tween_call(node.func))
        self.assertGreaterEqual(seen, 3, "扫描范围八成缩了")

    def test_every_tween_passes_a_context(self):
        missing = [f"{path.relative_to(ROOT)}:{line}"
                   for path, tree in self.trees.items()
                   for line in scan_tweens_without_context(tree)]
        self.assertEqual(
            missing, [],
            "这些 tween 的 setter 碰控件却没给 context，控件先死动画照跑：\n"
            + "\n".join(missing))

    def test_nobody_hooks_their_own_destroyed(self):
        hits = [f"{path.relative_to(ROOT)}:{line} {src}"
                for path, tree in self.trees.items()
                for line, src in scan_destroyed_hooks(tree)]
        self.assertEqual(
            hits, [],
            "在 destroyed 里碰自己（ThumbnailTile 旧写法），PySide 抛 SystemError、"
            "drop_if_gone 接不住：\n" + "\n".join(hits))

    def test_scanners_catch_the_known_bad_shapes(self):
        """扫描器自己的体检：喂已知漏法，必须抓出来；合法写法必须放过。"""
        src = (
            "def go(self, host, other):\n"
            "    tween(lambda h: host.setMaximumHeight(h), 0, 1)\n"          # 漏了
            "    motion.tween(self._set, 0, 1, ms=5)\n"                      # 漏了
            "    motion.tween(self._set, 0, 1, context=self)\n"              # 给了
            "    self.destroyed.connect(lambda *_: self._bye())\n"           # 坏
            "    self.destroyed.connect(self._bye)\n"                        # 坏
            "    other.destroyed.connect(lambda *_: None)\n"                 # 坏（lambda 无接收者）
            "    other.destroyed.connect(self._other_gone)\n"                # 合法
        )
        tree = ast.parse(src)
        self.assertEqual(scan_tweens_without_context(tree), [2, 3])
        self.assertEqual([line for line, _ in scan_destroyed_hooks(tree)], [5, 6, 7])


if __name__ == "__main__":
    unittest.main()
