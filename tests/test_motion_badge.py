# -*- coding: utf-8 -*-
"""任务角标脉冲与 motion 动画寄存表的回归。

角标计数一涨，`MainWindow._update_task_badge` 就调 `motion.pop` 做一次缩放
脉冲。它曾把 `QGraphicsScale`（QGraphicsItem 的 transform）塞给
`QWidget.setGraphicsEffect`，每来一个下载任务就抛 TypeError。这里走真实的
`_create_task_badge` / `_update_task_badge`，只把侧栏换成一颗按钮，其余不假。

后半段盯 `_keep` / `tween` 的寄存表：动画被 stop() 或 target 销毁打断时 Qt
不发 finished，清理若只挂在 finished 上，僵尸就永远赖在 `_mcl_anims` /
`_TWEENS` 里——前者还会让 pop 以后再也不脉冲。
"""
from __future__ import annotations

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QGraphicsEffect, QLabel,  # noqa: E402
                               QPushButton, QWidget)

from app import motion  # noqa: E402


def _wait_until(cond, timeout_ms: int = 2000) -> bool:
    """转事件循环直到 cond() 为真；动画靠定时器推进，光 sleep 不走。"""
    end = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    QApplication.processEvents()
    return cond()


class _FakeSide:
    def __init__(self, btn):
        self._btn = btn

    def button(self, key):
        return self._btn if key == "tasks" else None


def _badge_host_class():
    """借 MainWindow 的三个角标方法，侧栏换成一颗真按钮，别的都不用建。"""
    from app.main_window import MainWindow

    class _BadgeHost:
        _create_task_badge = MainWindow._create_task_badge
        _update_task_badge = MainWindow._update_task_badge
        _place_task_badge = MainWindow._place_task_badge

        def __init__(self, side):
            self.side = side
            self.task_badge = None
            self._create_task_badge()

    return _BadgeHost


class _MotionOnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # 用户配置里 ui_motion 可能关着，那样 pop 直接返回、整组用例空转。
        patcher = mock.patch.object(motion, "ui_motion_ok", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TaskBadgePulseTests(_MotionOnTests):
    def setUp(self):
        super().setUp()
        self.root = QWidget()
        self.root.resize(260, 80)
        self.btn = QPushButton("下载任务", self.root)
        self.btn.setGeometry(0, 0, 188, 44)
        self.root.show()
        self.host = _badge_host_class()(_FakeSide(self.btn))
        self.badge = self.host.task_badge
        QApplication.processEvents()
        self.addCleanup(self.root.deleteLater)

    def _render(self, frames: int = 4):
        for _ in range(frames):
            self.root.grab()
            QApplication.processEvents()

    def _badge_bbox(self):
        """父控件截图里角标那团红的包围盒 (x, y, w, h)；看的是真画出来的像素。"""
        img = self.root.grab().toImage()
        xs, ys = [], []
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() > 180 and c.green() < 120 and c.blue() < 120:
                    xs.append(x)
                    ys.append(y)
        self.assertTrue(xs, "截图里找不到红色角标")
        return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1

    def test_scale_effect_really_scales_the_pixels(self):
        """effect 装上了不算数，画面上得真的变大：drawSource 对 QWidget 源不吃
        painter 变换，早先那版属性在变、像素一动不动。"""
        self.host._update_task_badge(3)
        self.assertTrue(_wait_until(lambda: self.badge.graphicsEffect() is None))
        x0, _y0, w0, h0 = self._badge_bbox()

        eff = motion._ScaleEffect(self.badge)
        eff._set_scale(1.35)
        self.badge.setGraphicsEffect(eff)
        QApplication.processEvents()
        x1, _y1, w1, h1 = self._badge_bbox()
        self.badge.setGraphicsEffect(None)

        self.assertTrue(1.2 < w1 / w0 < 1.5 and 1.2 < h1 / h0 < 1.5,
                        f"放大 1.35 没画出来: {w0}x{h0} -> {w1}x{h1}")
        self.assertLessEqual(abs((x1 + w1 / 2) - (x0 + w0 / 2)), 1.5, "得绕中心放大")

    def test_count_increase_pulses_with_a_real_graphics_effect(self):
        self.assertTrue(self.badge.isHidden())

        self.host._update_task_badge(1)
        QApplication.processEvents()

        self.assertTrue(self.badge.isVisible())
        self.assertEqual(self.badge.text(), "1")
        eff = self.badge.graphicsEffect()
        self.assertIsInstance(eff, QGraphicsEffect,
                              "挂到 QWidget 上的必须是 QGraphicsEffect（原 bug 是 QGraphicsScale）")
        self.assertIsInstance(eff, motion._ScaleEffect)
        self.assertGreater(eff.scale, 1.0, "脉冲从放大态起步")
        self._render()  # 真走一遍 _ScaleEffect.draw，不能抛
        self.assertTrue(_wait_until(lambda: self.badge.graphicsEffect() is None),
                        "脉冲放完要摘掉 effect")
        self.assertEqual(getattr(self.badge, "_mcl_anims", []), [], "动画寄存表要清空")

    def test_pulse_in_progress_is_not_restarted(self):
        self.host._update_task_badge(1)
        QApplication.processEvents()
        self.assertEqual(len(self.badge._mcl_anims), 1)

        self.host._update_task_badge(2)
        QApplication.processEvents()

        self.assertEqual(self.badge.text(), "2")
        self.assertEqual(len(self.badge._mcl_anims), 1, "上一个脉冲没放完就不叠第二个")
        self._render()
        self.assertTrue(_wait_until(lambda: not self.badge._mcl_anims))

    def test_decrease_and_zero_do_not_pulse(self):
        self.host._update_task_badge(3)
        self.assertTrue(_wait_until(lambda: self.badge.graphicsEffect() is None))

        self.host._update_task_badge(1)
        QApplication.processEvents()
        self.assertIsNone(self.badge.graphicsEffect(), "计数减少不脉冲")

        self.host._update_task_badge(0)
        QApplication.processEvents()
        self.assertTrue(self.badge.isHidden())

    def test_overflow_label_pulses_too(self):
        self.host._update_task_badge(120)
        QApplication.processEvents()
        self.assertEqual(self.badge.text(), "99+")
        self.assertIsInstance(self.badge.graphicsEffect(), motion._ScaleEffect)
        self._render()
        self.assertTrue(_wait_until(lambda: self.badge.graphicsEffect() is None))


class MotionRegistryCleanupTests(_MotionOnTests):
    def setUp(self):
        super().setUp()
        self.root = QWidget()
        self.root.resize(300, 200)
        self.w = QLabel("x", self.root)
        self.w.resize(80, 24)
        self.root.show()
        QApplication.processEvents()
        self.addCleanup(self.root.deleteLater)

    def test_fade_interrupted_by_another_fade_is_dropped(self):
        first_done = []
        motion.fade(self.w, 1.0, 0.0, ms=300, on_done=lambda: first_done.append(1))
        QApplication.processEvents()
        # 第二个 fade 新装的 effect 顶掉第一个的 target，第一条动画被 Qt 静默 stop
        motion.fade(self.w, 0.0, 1.0, ms=60)

        self.assertTrue(_wait_until(lambda: not self.w._mcl_anims),
                        f"被打断的动画没从 _mcl_anims 摘掉: {self.w._mcl_anims}")
        self.assertEqual(first_done, [], "没跑到终点的 fade 不该报 on_done")
        self.assertIsNone(self.w.graphicsEffect())

    def test_pop_still_works_after_an_interrupted_fade(self):
        motion.pop(self.w)
        QApplication.processEvents()
        motion.fade(self.w, 1.0, 0.0, ms=60)   # 顶掉 pop 的 _ScaleEffect
        self.assertTrue(_wait_until(lambda: not self.w._mcl_anims))

        motion.pop(self.w)
        QApplication.processEvents()

        self.assertIsInstance(self.w.graphicsEffect(), motion._ScaleEffect,
                              "寄存表里留了僵尸，pop 以后就永远被判成重入")
        self.assertTrue(_wait_until(lambda: self.w.graphicsEffect() is None))

    def test_stopped_tween_leaves_the_registry(self):
        done = []
        anim = motion.tween(lambda v: None, 0, 100, ms=300, on_done=lambda: done.append(1))
        QApplication.processEvents()
        self.assertIn(anim, motion._TWEENS)

        anim.stop()   # pcl_chrome._sync_group 连点分组就是这么打断上一条的

        self.assertTrue(_wait_until(lambda: anim not in motion._TWEENS),
                        "stop() 掉的补间不能永远留在 _TWEENS")
        self.assertEqual(done, [], "被打断的补间不该报 on_done")

    def test_finished_tween_calls_on_done_and_leaves_the_registry(self):
        seen = []
        done = []
        anim = motion.tween(seen.append, 0, 100, ms=60, on_done=lambda: done.append(1))

        self.assertTrue(_wait_until(lambda: done and anim not in motion._TWEENS))
        self.assertEqual(seen[-1], 100)


if __name__ == "__main__":
    unittest.main()
