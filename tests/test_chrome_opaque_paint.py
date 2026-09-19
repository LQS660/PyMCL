# -*- coding: utf-8 -*-
"""侧栏 / 标题栏标了 WA_OpaquePaintEvent 之后，底还得有人画。

Qt 只给没标不透明的控件走 paintBackground——样式表的 background 就是在那一步
画的。mark_opaque 是壁纸场景下的重绘优化，标上之后这一笔被整段跳过，控件那块
矩形从此没人清底：浅色主题白底盖白底看不出来，深色主题一开侧栏和标题栏就是
两块白板，字是浅灰、底却是白的；从顶上滑进来的 InfoBar 还会在标题栏留下一串
残影。这里离屏 grab 直接采像素：深浅两套主题下，空白处颜色必须等于 Theme 色板。

同一个坑还有第二处：壁纸「借底」给页面（background.adopt_surface）也是标不透明
加调色板刷子，同样没人画——借出去那块得逐像素等于壁纸成品图。最后顺带钉住
窗口级 InfoBar 的落点：从标题栏下沿起算，别再压着标题栏。
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from qfluentwidgets import FluentIcon as FIF, InfoBar, InfoBarPosition  # noqa: E402
from qfluentwidgets.components.widgets.info_bar import InfoBarManager  # noqa: E402

from app.background import BackgroundLayer  # noqa: E402
from app.pcl_chrome import (  # noqa: E402
    PclSideBar, PclTitleBar, TITLE_H, Theme, install_infobar_offsets,
)


def _pixel(widget, x: int, y: int) -> str:
    return QColor(widget.grab().toImage().pixel(x, y)).name().upper()


def _write_gradient(path: str, w: int = 400, h: int = 300) -> None:
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#FF0000"))
    g.setColorAt(1.0, QColor("#0000FF"))
    p.fillRect(img.rect(), g)
    p.end()
    img.save(path)


class LentWallpaperPaintTests(unittest.TestCase):
    """壁纸「借底」那条路：页面被标成不透明后，裁片得由背景层替它铺上。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self, tmp):
        png = os.path.join(tmp, "wall.png")
        _write_gradient(png)
        host = QWidget()
        host.resize(400, 300)
        layer = BackgroundLayer(host)
        layer.setGeometry(host.rect())
        self.assertTrue(layer.set_source(png), layer.error)
        layer.show()
        layer.lower()
        page = QWidget(host)
        page.setGeometry(100, 50, 200, 150)
        page.show()
        host.show()
        for _ in range(3):
            self.app.processEvents()
        return host, layer, page

    def test_adopted_page_paints_its_wallpaper_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, layer, page = self._scene(tmp)
            self.assertTrue(layer.adopt_surface(page))
            self.assertTrue(page.testAttribute(Qt.WA_OpaquePaintEvent))
            back = layer._backdrop().toImage()
            got = host.grab().toImage()
            for x, y in ((150, 100), (250, 150)):   # 页面盖住的两点：跟壁纸成品图逐像素一致
                self.assertEqual(QColor(got.pixel(x, y)).name(), QColor(back.pixel(x, y)).name())
            # 页面自己单独 grab 也得是那块裁片，而不是一片没人画的黑
            self.assertEqual(QColor(page.grab().toImage().pixel(50, 50)).name(),
                             QColor(back.pixel(150, 100)).name())

    def test_released_page_paints_solid_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, layer, page = self._scene(tmp)
            self.assertTrue(layer.adopt_surface(page))
            layer.release_surface(page)
            # 换回纯色：paint_theme_surfaces 会把调色板刷成实色，页面仍标着不透明
            pal = page.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor("#1B1B1B"))
            page.setPalette(pal)
            page.setAutoFillBackground(True)
            self.assertTrue(page.testAttribute(Qt.WA_OpaquePaintEvent))
            self.assertEqual(_pixel(page, 50, 50), "#1B1B1B")


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


class _FakeShell(QWidget):
    """长得像 FluentWindowBase 的顶层窗口：有 titleBar、有 side。"""

    def __init__(self):
        super().__init__()
        self.resize(900, 600)
        self.titleBar = QWidget(self)
        self.titleBar.setGeometry(0, 0, 900, TITLE_H)
        self.side = QWidget(self)
        self.side.setGeometry(0, TITLE_H, 188, 560)


class InfoBarOffsetTests(unittest.TestCase):
    """挂在主窗口上的顶部提示条：从标题栏下沿起算、居中对齐内容区。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_infobar_offsets()

    def _settle(self):
        for _ in range(3):
            self.app.processEvents()

    def test_window_level_top_bar_clears_titlebar(self):
        win = _FakeShell()
        win.show()
        self._settle()
        bar = InfoBar.success("t", "c", parent=win, position=InfoBarPosition.TOP, duration=-1)
        self._settle()
        pos = InfoBarManager.make(InfoBarPosition.TOP)._pos(bar)
        self.assertEqual(pos.y(), TITLE_H + 24)
        self.assertEqual(pos.x(), 188 + (900 - 188 - bar.width()) // 2)
        bar.close()

    def test_window_level_top_right_bar_clears_titlebar(self):
        win = _FakeShell()
        win.show()
        self._settle()
        bar = InfoBar.info("t", "c", parent=win, position=InfoBarPosition.TOP_RIGHT, duration=-1)
        self._settle()
        pos = InfoBarManager.make(InfoBarPosition.TOP_RIGHT)._pos(bar)
        self.assertEqual(pos.y(), TITLE_H + 24)
        self.assertEqual(pos.x(), 900 - bar.width() - 24)
        bar.close()

    def test_page_level_bar_untouched(self):
        win = _FakeShell()
        page = QWidget(win)
        page.setGeometry(188, TITLE_H, 712, 560)
        win.show()
        self._settle()
        bar = InfoBar.success("t", "c", parent=page, position=InfoBarPosition.TOP, duration=-1)
        self._settle()
        pos = InfoBarManager.make(InfoBarPosition.TOP)._pos(bar)
        self.assertEqual(pos.y(), 24)   # 页面级的本来就在标题栏下面，不动
        bar.close()


if __name__ == "__main__":
    unittest.main()
