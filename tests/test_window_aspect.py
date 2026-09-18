"""主窗口宽高比：默认尺寸按档位来、拖边拖角保比例、非法值回出厂。

壁纸按整窗保比例裁切，窗口比例锁在图片 / 视频常见档位上，用户挑同比例的
壁纸就能完整显示；拖窗口也不会变成裁头裁脚。三条硬要求：
比例要对（标准比）、要固定（拖不歪）、要能手动改（设置里切档）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mclauncher import config as config_mod
from app.main_window import (
    WINDOW_ASPECTS, _ASPECT_DEFAULT_SIZE, constrain_sizing_rect, default_window_size,
    fit_aspect, window_aspect_key, window_aspect_ratio,
)
from app.backend import _window_aspect

R43 = 4 / 3
R169 = 16 / 9


class _IsolatedConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_file = config_mod.CONFIG_FILE
        self._real_data = dict(config_mod.CONFIG.data)
        config_mod.CONFIG_FILE = Path(self._tmp.name) / "config.json"

    def tearDown(self):
        config_mod.CONFIG_FILE = self._real_file
        config_mod.CONFIG.data = self._real_data
        self._tmp.cleanup()

    def aspect(self, value):
        config_mod.CONFIG.set("ui_window_aspect", value)
        config_mod.CONFIG.save()


class FitAspectTests(unittest.TestCase):
    def test_width_drives_height(self):
        self.assertEqual(fit_aspect(1040, 650, R43), (1040, 780))
        self.assertEqual(fit_aspect(1040, 650, R169), (1040, 585))

    def test_height_drives_width(self):
        self.assertEqual(fit_aspect(1040, 600, R43, drive="height"), (800, 600))

    def test_box_caps_keep_ratio(self):
        # 盒子装不下：整体缩到最大同比矩形，两边都不越界
        w, h = fit_aspect(960, 720, R43, max_w=800, max_h=700)
        self.assertEqual((w, h), (800, 600))
        w, h = fit_aspect(960, 720, R169, max_w=2000, max_h=500)
        self.assertEqual((w, h), (889, 500))
        self.assertAlmostEqual(w / h, R169, delta=0.01)

    def test_min_size_keeps_ratio(self):
        w, h = fit_aspect(300, 200, R43, min_w=820)
        self.assertEqual((w, h), (820, 615))
        w, h = fit_aspect(300, 200, R43, min_h=600)
        self.assertEqual((w, h), (800, 600))

    def test_free_only_clamps(self):
        self.assertEqual(fit_aspect(1040, 650, None), (1040, 650))
        self.assertEqual(fit_aspect(1040, 650, None, max_w=900, min_h=700), (900, 700))


class SizingRectTests(unittest.TestCase):
    """WM_SIZING：跟着光标走的那条边贴着光标，另一维按比例补。"""

    def test_drag_right_edge_moves_bottom(self):
        self.assertEqual(constrain_sizing_rect(2, 0, 0, 1000, 600, R43), (0, 0, 1000, 750))

    def test_drag_left_edge_keeps_right_anchor(self):
        self.assertEqual(constrain_sizing_rect(1, 200, 0, 1200, 600, R43), (200, 0, 1200, 750))

    def test_drag_top_edge_height_drives_width(self):
        # 抓着上边：高 600 定宽 800，右边跟着动，底边不动
        self.assertEqual(constrain_sizing_rect(3, 0, 100, 1000, 700, R43), (0, 100, 800, 700))

    def test_drag_bottom_edge(self):
        self.assertEqual(constrain_sizing_rect(6, 0, 0, 1000, 600, R43), (0, 0, 800, 600))

    def test_corners_anchor_opposite_side(self):
        # 右下角：左上不动
        self.assertEqual(constrain_sizing_rect(8, 0, 0, 1000, 600, R43), (0, 0, 1000, 750))
        # 左上角：右下不动，上边往上补
        self.assertEqual(constrain_sizing_rect(4, 100, 100, 1100, 700, R43), (100, -50, 1100, 700))
        # 右上角：左、下不动
        self.assertEqual(constrain_sizing_rect(5, 100, 100, 1100, 700, R43), (100, -50, 1100, 700))
        # 左下角：右、上不动
        self.assertEqual(constrain_sizing_rect(7, 100, 100, 1100, 700, R43), (100, 100, 1100, 850))

    def test_min_size_respected(self):
        l, t, r, b = constrain_sizing_rect(2, 0, 0, 400, 300, R43, min_w=820)
        self.assertEqual((r - l, b - t), (820, 615))

    def test_result_is_on_ratio(self):
        for edge in range(1, 9):
            l, t, r, b = constrain_sizing_rect(edge, 10, 20, 1234, 567, R169)
            self.assertAlmostEqual((r - l) / (b - t), R169, delta=0.01, msg=f"edge {edge}")


def _screen_box():
    """同一进程里别的用例可能已经起了（离屏）QApplication，那时出厂尺寸会被
    它那块 800x600 的「屏幕」按 90% 封顶；期望值照同一条规则算，别写死。"""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None, None
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return None, None
    avail = screen.availableGeometry()
    return int(avail.width() * 0.9), int(avail.height() * 0.9)


class DefaultSizeTests(_IsolatedConfig):
    def test_factory_default_is_4_3(self):
        self.assertEqual(window_aspect_key(), "4:3")
        self.assertAlmostEqual(window_aspect_ratio(), R43)
        max_w, max_h = _screen_box()
        self.assertEqual(default_window_size(),
                         fit_aspect(*_ASPECT_DEFAULT_SIZE["4:3"], R43, max_w=max_w, max_h=max_h))
        self.assertEqual(_ASPECT_DEFAULT_SIZE["4:3"], (960, 720))

    def test_each_aspect_default_size_is_on_ratio(self):
        max_w, max_h = _screen_box()
        for key, ratio in WINDOW_ASPECTS.items():
            self.aspect(key)
            w, h = default_window_size()
            fw, fh = _ASPECT_DEFAULT_SIZE[key]
            if ratio is None:
                self.assertEqual((fw, fh), (1040, 650))
            else:
                self.assertAlmostEqual(fw / fh, ratio, delta=0.01, msg=key)
                self.assertAlmostEqual(w / h, ratio, delta=0.02, msg=key)
            self.assertEqual((w, h), fit_aspect(fw, fh, ratio, max_w=max_w, max_h=max_h), key)
            # 侧栏 188 + 下载页横条 628：出厂宽度必须放得下
            self.assertGreaterEqual(fw, 820, key)
            # 16:9 那档不能再矮：横幅最小高 165，画布高 = 窗高 - 64，
            # 0.315 x 画布高 >= 167 才不压到启动配置卡
            if key != "free":
                self.assertGreaterEqual(round(0.315 * (fh - 64)), 167, key)

    def test_invalid_value_falls_back(self):
        self.aspect("9:16")
        self.assertEqual(window_aspect_key(), "4:3")
        self.aspect("")
        self.assertEqual(window_aspect_key(), "4:3")

    def test_backend_normalizer(self):
        self.assertEqual(_window_aspect("16:9"), "16:9")
        self.assertEqual(_window_aspect("free"), "free")
        self.assertEqual(_window_aspect(" 4:3 "), "4:3")
        self.assertEqual(_window_aspect("garbage"), "4:3")
        self.assertEqual(_window_aspect(None), "4:3")


if __name__ == "__main__":
    unittest.main()
