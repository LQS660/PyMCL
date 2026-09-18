# -*- coding: utf-8 -*-
"""侧栏 / 标题栏标了 WA_OpaquePaintEvent 之后，底还得有人画。

Qt 只给没标不透明的控件走 paintBackground——样式表的 background 就是在那一步
画的。mark_opaque 是壁纸场景下的重绘优化，标上之后这一笔被整段跳过，控件那块
矩形从此没人清底：浅色主题白底盖白底看不出来，深色主题一开侧栏和标题栏就是
两块白板，字是浅灰、底却是白的；从顶上滑进来的 InfoBar 还会在标题栏留下一串
残影。这里离屏 grab 直接采像素：深浅两套主题下，空白处颜色必须等于 Theme 色板。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from qfluentwidgets import FluentIcon as FIF  # noqa: E402

from app.pcl_chrome import PclSideBar, PclTitleBar, Theme  # noqa: E402


def _pixel(widget, x: int, y: int) -> str:
    return QColor(widget.grab().toImage().pixel(x, y)).name().upper()


class OpaqueChromePaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._opacity = Theme.sidebar_opacity
        self._dark = Theme.dark
        Theme.sidebar_opacity = 100

    def tearDown(self):
        Theme.sidebar_opacity = self._opacity
        Theme.apply(self._dark)

    def _build(self):
        side = PclSideBar([("item", "launch", FIF.PLAY, "启动"),
                           ("header", "通用"), ("stretch",)])
        side.resize(188, 400)
        host = QWidget()
        host.resize(800, 600)
        bar = PclTitleBar(host)
        bar.resize(800, 40)
        return side, bar, host

    def test_dark_theme_paints_sidebar_and_titlebar(self):
        Theme.apply(True)
        side, bar, _host = self._build()
        # 满不透明度时两块都该被标成不透明（优化仍在），但底必须自己画出来
        self.assertTrue(side.testAttribute(Qt.WA_OpaquePaintEvent))
        self.assertTrue(bar.testAttribute(Qt.WA_OpaquePaintEvent))
        self.assertEqual(_pixel(side, 90, 300), Theme.card.upper())
        self.assertEqual(_pixel(bar, 400, 20), Theme.bg.upper())

    def test_switching_back_to_light_repaints(self):
        # 跟运行时一样：窗口已经画过一帧，用户再去设置里切主题
        Theme.apply(True)
        side, bar, _host = self._build()
        self.assertEqual(_pixel(side, 90, 300), Theme.card.upper())
        self.assertEqual(_pixel(bar, 400, 20), Theme.bg.upper())
        Theme.apply(False)
        side.restyle()
        bar.restyle()
        self.assertEqual(_pixel(side, 90, 300), Theme.card.upper())
        self.assertEqual(_pixel(bar, 400, 20), Theme.bg.upper())


if __name__ == "__main__":
    unittest.main()
