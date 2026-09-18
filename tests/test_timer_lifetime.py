# -*- coding: utf-8 -*-
"""`QTimer.singleShot` 的回调必须挂一个 context 对象。

两参写法（`singleShot(ms, 回调)`）不认接收者：控件都析构完了，那一枪照样开。
回调里但凡碰一下 `self` 的 Qt 部分，就是
`RuntimeError: Internal C++ object already deleted` 从事件循环里冒出来 ——
跟 pymcl-error.log 里 ThumbnailTile 那一批是同一种病：**回调活得比控件久**。

三参写法 `singleShot(ms, context, 回调)` 把 context 的生死交给 Qt 管，
context 一没，这一枪自动作废。而且 context 不在当前线程时，回调会落到
context 所在的线程上跑 —— 工作线程里报错想弹窗，靠的就是这一条。
"""
from __future__ import annotations

import ast
import os
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [ROOT / "app", ROOT / "main.py"]


def _mentions_self(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "self" for n in ast.walk(node))


def scan_single_shots(tree: ast.Module) -> list[tuple[int, str]]:
    """这棵树里「两参 singleShot 且回调碰了 self」的点 → [(行号, 回调源码)]。

    回调不碰 self 的（`QApplication.instance().quit` 这种）不管：那类回调
    本来就不依赖某个控件还活着。
    """
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "singleShot"):
            continue
        if len(node.args) != 2:
            continue
        if _mentions_self(node.args[1]):
            bad.append((node.lineno, ast.unparse(node.args[1])))
    return bad


class SingleShotScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {}
        for target in SCAN_ROOTS:
            paths = sorted(target.rglob("*.py")) if target.is_dir() else [target]
            for path in paths:
                cls.trees[path] = ast.parse(path.read_text(encoding="utf-8"),
                                            filename=str(path))

    def test_scan_actually_sees_the_calls(self):
        """先证明扫描器没空转：一个 singleShot 都没数到，下面那条永远是绿的。"""
        seen = 0
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "singleShot"):
                    seen += 1
        self.assertGreater(seen, 8, "扫描范围八成缩了")

    def test_every_self_callback_has_a_context(self):
        missing = []
        for path, tree in self.trees.items():
            for line, src in scan_single_shots(tree):
                rel = path.relative_to(ROOT)
                missing.append(f"{rel}:{line} singleShot(…, {src})")
        self.assertEqual(
            missing, [],
            "这些 singleShot 的回调碰了 self 却没给 context，控件先死就抛：\n"
            + "\n".join(missing))

    def test_scanner_catches_a_missing_context(self):
        """扫描器自己的体检：喂一段已知漏传的代码，必须抓出来。"""
        src = (
            "def go(self):\n"
            "    QTimer.singleShot(0, self._boot)\n"            # 漏了
            "    QTimer.singleShot(0, lambda: self._boot())\n"  # 漏了
            "    QTimer.singleShot(0, self, self._boot)\n"      # 给了
            "    QTimer.singleShot(0, app.quit)\n"              # 不碰 self，放过
        )
        hits = [line for line, _ in scan_single_shots(ast.parse(src))]
        self.assertEqual(hits, [2, 3])


class SingleShotBehaviourTests(unittest.TestCase):
    """把「为什么非得加 context」钉在可执行的行为上。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _spin(self, rounds: int = 6):
        for _ in range(rounds):
            self.app.processEvents()

    def test_two_arg_form_still_fires_after_the_widget_dies(self):
        """两参写法不认接收者 —— 这就是病根，控件没了那一枪照开。"""
        fired = []
        page = QWidget()
        QTimer.singleShot(0, lambda: fired.append("ran"))
        page.destroyed.connect(lambda *_: None)
        shiboken6.delete(page)
        self._spin()
        self.assertEqual(fired, ["ran"])

    def test_context_form_is_cancelled_with_the_context(self):
        fired = []
        page = QWidget()
        QTimer.singleShot(0, page, lambda: fired.append("ran"))
        shiboken6.delete(page)
        self._spin()
        self.assertEqual(fired, [], "context 都没了，这一枪不该开")

    def test_context_form_runs_on_the_context_thread(self):
        """工作线程里挂的一枪，要落到 context 所在的 GUI 线程上跑。

        main.py 的崩溃弹窗钩子就靠这条：它可能在任何线程里被调到，而普通线程
        没有事件循环，两参写法挂上去的定时器根本不会响。
        """
        page = QWidget()
        self.addCleanup(page.deleteLater)
        where: list[int] = []
        worker = threading.Thread(
            target=lambda: QTimer.singleShot(
                0, page, lambda: where.append(threading.get_ident())))
        worker.start()
        worker.join(5)
        self._spin()
        self.assertEqual(where, [threading.get_ident()])


if __name__ == "__main__":
    unittest.main()
