# -*- coding: utf-8 -*-
"""`SmoothProgressBar` 的数值语义：setValue 后 value() 立即反映目标值。

它以前把 `QVariantAnimation.valueChanged` 直接连回自己的 `setValue`，等于
自己连自己：对处于 Stopped 的动画调 `setStartValue(x)` 会同步 emit
`valueChanged(旧 startValue)`，重入进来时 `anim.state()` 还是 Stopped
（不是 Running），密集更新分支不生效，于是重入那层拿**旧值**覆盖
start/end 再 `start()` —— 动画区间与 `_shown` 脱节，进度卡在中间值。
实测：任务已完成、`set_finished` 发完 100%，进度条停在 72%，`value()`
仍是 80，`TaskCard` 的 `setValue(100)` 也拉不回来。

修法是断开自反馈：动画回调只走 `_apply_shown`（直连基类），公开
`setValue` 只负责设目标值并启动动画。下面把 docstring 承诺的两条钉死。
"""
from __future__ import annotations

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import ProgressBar  # noqa: E402

from app import motion  # noqa: E402
from app.motion import SmoothProgressBar  # noqa: E402


def _pump(ms: int):
    """转事件循环推进动画；动画靠定时器走，光 sleep 不推进。"""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()


def _drawn(bar) -> int:
    """当前绘制值：绕过 SmoothProgressBar.value() 的重写，直读基类。"""
    return ProgressBar.value(bar)


class SmoothProgressBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # 用户配置里 ui_motion 可能关着，那样 setValue 直接跳终态、整组用例空转
        self._patch = mock.patch.object(motion, "ui_motion_ok", return_value=True)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_value_reflects_target_immediately(self):
        bar = SmoothProgressBar()
        bar.setRange(0, 100)
        bar.setValue(80)
        self.assertEqual(bar.value(), 80)
        bar.setValue(100)
        # docstring 承诺：value() 立即反映目标值（修复前这里返回 80）
        self.assertEqual(bar.value(), 100)
        bar.deleteLater()

    def test_animation_ends_at_target(self):
        bar = SmoothProgressBar()
        bar.setRange(0, 100)
        bar.setValue(100)
        _pump(500)  # 补间 240ms，留足余量
        self.assertEqual(bar.value(), 100)
        # 动画结束后**绘制值**也必须是 100（修复前停在 72~80）
        self.assertEqual(_drawn(bar), 100)
        self.assertEqual(bar._shown, 100)
        bar.deleteLater()

    def test_throttled_progress_reaches_100(self):
        """后端进度被节流到 80ms（backend.py 的节流），恰好命中重入路径。"""
        bar = SmoothProgressBar()
        bar.setRange(0, 100)
        for v in (8, 21, 37, 49, 62, 70, 83, 91, 97, 100):
            bar.setValue(v)
            _pump(80)
        self.assertEqual(bar.value(), 100)
        _pump(400)
        self.assertEqual(bar.value(), 100)
        self.assertEqual(_drawn(bar), 100)
        self.assertEqual(bar._shown, 100)
        bar.deleteLater()

    def test_still_smooth_without_motion(self):
        """动效关掉时直接跳终值，不许被补间拦住。"""
        bar = SmoothProgressBar()
        bar.setRange(0, 100)
        with mock.patch.object(motion, "ui_motion_ok", return_value=False):
            bar.setValue(42)
            self.assertEqual(bar.value(), 42)
            self.assertEqual(_drawn(bar), 42)
            self.assertEqual(bar._shown, 42)
        bar.deleteLater()

    def test_anim_callback_does_not_reenter_public_setvalue(self):
        """动画回调不许再走公开 setValue：那是自反馈环的入口。"""
        bar = SmoothProgressBar()
        with mock.patch.object(SmoothProgressBar, "setValue",
                               side_effect=AssertionError("自反馈重入")):
            bar._apply_shown(55)
        self.assertEqual(bar._shown, 55)
        self.assertEqual(_drawn(bar), 55)
        bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
