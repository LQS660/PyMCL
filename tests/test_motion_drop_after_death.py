# -*- coding: utf-8 -*-
"""motion._drop 的 singleShot 闭包在动画死后开火不许炸。

`QTimer.singleShot(0, _drop)` 的 `_drop` 是闭包，捕获了动画 `a`。排队等待的
这一拍里 context 先死、动画随之析构的场合，`_drop` 只能做身份比较摘表 +
isValid 守卫，任何对已析构包装器的真比较/方法调用都是 RuntimeError。

结论记录：摘表必须用 `t is not a`，不许 `a in _TWEENS`（那依赖包装器的
比较协议）；isValid 探测必须在任何"摸 a"之前。
"""
from __future__ import annotations

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app import motion  # noqa: E402


class MotionDropAfterDeathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._motion_ok = motion.ui_motion_ok
        motion.ui_motion_ok = lambda: True
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
        deadline = time.monotonic() + ms / 1000
        while time.monotonic() < deadline:
            try:
                self.app.processEvents(QEventLoop.AllEvents, 20)
            except Exception as exc:  # noqa: BLE001 - 这里就是要抓漏网的
                self.escaped.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
            time.sleep(0.005)

    def test_stop_then_context_death_is_clean(self):
        host = QWidget()
        anim = motion.tween(lambda v: host.setMaximumHeight(int(v)),
                            0, 100, ms=5000, context=host)
        self._spin(40)
        anim.stop()                # stateChanged(Stopped) → 排队 singleShot(0,_drop)
        shiboken6.delete(host)     # 下一拍到来前 context 带走动画
        self._spin(150)
        self.assertEqual(self.escaped, [],
                         f"动画死了 _drop 还在惹事: {self.escaped}")
        self.assertEqual(motion._TWEENS, [], "死掉的补间不许赖在寄存处")

    def test_stop_releases_live_animation(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        anim = motion.tween(lambda v: host.setMaximumHeight(int(v)),
                            0, 100, ms=5000, context=host)
        self._spin(40)
        anim.stop()
        self._spin(150)
        self.assertEqual(self.escaped, [])
        self.assertNotIn(anim, motion._TWEENS, "停了的补间该被摘掉")
        self.assertTrue(shiboken6.isValid(anim), "活动画跑完该把所有权还给 Python")
        self.assertIsNone(anim.parent())


if __name__ == "__main__":
    unittest.main()
