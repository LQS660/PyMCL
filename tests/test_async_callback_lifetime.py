# -*- coding: utf-8 -*-
"""后台调用的回调，不能打在已经析构的控件上。

`call_async` 的回调多半是闭包（`lambda rows: self._fill(rows)`）。Qt 眼里
这种回调的接收者是 PySide 内部那个转发对象、不是页面，所以页面被关掉 /
重建掉时连接并不会自动断：结果回来照样跑，碰到死控件就抛
`RuntimeError: Internal C++ object already deleted` —— 而它是从事件循环里
冒出来的，调用栈上没人接得住，只能进 pymcl-error.log。

跟 ThumbnailTile 那一批是同一种病：回调活得比控件久。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.backend import BackendAPI, SilentWorker  # noqa: E402
from app.ui_alive import drop_if_gone  # noqa: E402


class FakeBackend(QObject):
    """只借 BackendAPI 真正的 call_async 那段代码，不碰它庞大的构造。"""

    call_async = BackendAPI.call_async

    def __init__(self):
        super().__init__()
        self._bg_threads: list = []


class DropIfGoneTests(unittest.TestCase):
    def test_passes_through_when_everything_is_alive(self):
        wrapped = drop_if_gone(lambda a, b=0: a + b)
        self.assertEqual(wrapped(2, b=3), 5)

    def test_swallows_the_deleted_object_error(self):
        def boom():
            raise RuntimeError("Internal C++ object (Foo) already deleted.")

        self.assertIsNone(drop_if_gone(boom)())

    def test_other_runtime_errors_still_surface(self):
        """别把真 bug 一起吃掉。"""
        def boom():
            raise RuntimeError("磁盘满了")

        with self.assertRaises(RuntimeError):
            drop_if_gone(boom)()


class CallAsyncLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = FakeBackend()
        self.addCleanup(self.backend.deleteLater)

    def _run_until_idle(self, worker, limit: int = 400):
        """转到后台线程收工为止，顺手记下所有漏出来的异常。

        槽里抛出来的异常有两条出路：冒出 `processEvents()`，或者被 PySide
        交给 `sys.excepthook` 打印掉（真机上就是这条，最后落进
        pymcl-error.log）。两条都得收，只盯一条会漏。
        """
        escaped: list[str] = []
        hooks = (sys.excepthook, sys.unraisablehook)
        sys.excepthook = lambda t, v, tb: escaped.append(
            f"{t.__name__}: {str(v).splitlines()[0]}")
        sys.unraisablehook = lambda a: escaped.append(
            f"unraisable {type(a.exc_value).__name__}: {a.exc_value}")

        def spin():
            try:
                self.app.processEvents()
            except Exception as exc:  # noqa: BLE001 - 这里就是要抓漏网的
                escaped.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")

        try:
            for _ in range(limit):
                spin()
                if worker.isFinished():
                    break
            worker.wait(3000)
            for _ in range(5):
                spin()
        finally:
            sys.excepthook, sys.unraisablehook = hooks
        return escaped

    def test_callback_on_a_dead_page_is_dropped(self):
        page = QWidget()
        landed = []

        def on_ok(rows):
            page.setWindowTitle(str(rows))   # 页面没了就在这一行抛
            landed.append(rows)

        worker = self.backend.call_async(lambda: [1, 2, 3], on_ok)
        shiboken6.delete(page)
        escaped = self._run_until_idle(worker)

        self.assertEqual(escaped, [], "回调把异常甩进事件循环了")
        self.assertEqual(landed, [], "页面都没了，回调不该走完")

    def test_callback_still_lands_when_the_page_is_alive(self):
        """护栏不能顺手把正常结果也吞掉。"""
        page = QWidget()
        self.addCleanup(page.deleteLater)
        landed = []

        worker = self.backend.call_async(
            lambda: [1, 2, 3], lambda rows: (page.setWindowTitle(str(rows)),
                                             landed.append(rows)))
        escaped = self._run_until_idle(worker)

        self.assertEqual(escaped, [])
        self.assertEqual(landed, [[1, 2, 3]])
        self.assertEqual(page.windowTitle(), "[1, 2, 3]")

    def test_without_the_guard_it_really_does_blow_up(self):
        """证明上面那条不是空转：不套护栏，同一段代码就是会炸。"""
        page = QWidget()
        worker = SilentWorker(lambda: [1, 2, 3], self.backend)
        worker.ok.connect(lambda rows: page.setWindowTitle(str(rows)),
                          Qt.QueuedConnection)
        worker.start()
        shiboken6.delete(page)
        escaped = self._run_until_idle(worker)

        self.assertTrue(any("already deleted" in line for line in escaped),
                        f"本来就该炸的路子没炸: {escaped}")


if __name__ == "__main__":
    unittest.main()
