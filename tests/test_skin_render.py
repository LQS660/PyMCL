# -*- coding: utf-8 -*-
"""正面小人拼图：每一块都得从贴图里正确的位置取。

皮肤贴图是一张图集，取错几个像素不会报错，只会让用户看到一个胳膊长在
脸上的小人——而这张图正是「离线皮肤到底设没设对」的唯一反馈。这里给每个
源矩形刷一种独有的颜色，再去成品图上按位置查回来。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 源矩形 -> 颜色。名字对应 app/skin_render.front_view 里那几次 blit。
PARTS = {
    "head": ((8, 8, 8, 8), "#ff0000"),
    "body": ((20, 20, 8, 12), "#00ff00"),
    "right_arm": ((44, 20, 4, 12), "#0000ff"),
    "right_leg": ((4, 20, 4, 12), "#ffff00"),
    "left_arm": ((36, 52, 4, 12), "#ff00ff"),
    "left_leg": ((20, 52, 4, 12), "#00ffff"),
}
TRANSPARENT = QColor(0, 0, 0, 0)


def _texture(height: int) -> bytes:
    """一张 64x{height} 的测试贴图：只给底层那几块上色，外层全透明。"""
    img = QImage(64, height, QImage.Format_ARGB32)
    img.fill(TRANSPARENT)
    for rect, color in PARTS.values():
        x, y, w, h = rect
        if y + h > height:
            continue  # 64x32 里没有左臂左腿那两块
        for px in range(x, x + w):
            for py in range(y, y + h):
                img.setPixelColor(px, py, QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class FrontViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def at(self, img, x, y) -> str:
        return img.pixelColor(x, y).name()

    def test_modern_skin_puts_every_part_where_it_belongs(self):
        from app.skin_render import front_view
        img = front_view(_texture(64))

        self.assertEqual((img.width(), img.height()), (16, 32))
        self.assertEqual(self.at(img, 8, 4), PARTS["head"][1], "头")
        self.assertEqual(self.at(img, 8, 14), PARTS["body"][1], "身体")
        self.assertEqual(self.at(img, 1, 14), PARTS["right_arm"][1], "右臂在画面左侧")
        self.assertEqual(self.at(img, 14, 14), PARTS["left_arm"][1], "左臂在画面右侧")
        self.assertEqual(self.at(img, 5, 26), PARTS["right_leg"][1], "右腿")
        self.assertEqual(self.at(img, 10, 26), PARTS["left_leg"][1], "左腿")

    def test_slim_arms_are_three_pixels_wide(self):
        from app.skin_render import front_view
        img = front_view(_texture(64), slim=True)

        # 细臂从 x=1 起（4-3），x=0 那一列该空着；宽臂那一档它是有色的
        self.assertEqual(img.pixelColor(0, 14).alpha(), 0, "细臂不该占满 4 像素")
        self.assertEqual(self.at(img, 1, 14), PARTS["right_arm"][1])
        self.assertEqual(self.at(img, 12, 14), PARTS["left_arm"][1])
        self.assertEqual(img.pixelColor(15, 14).alpha(), 0)

    def test_legacy_64x32_mirrors_the_missing_half(self):
        """1.8 以前的贴图只有右半边，左臂左腿得镜像出来，不能留空。"""
        from app.skin_render import front_view
        img = front_view(_texture(32))

        self.assertEqual(self.at(img, 14, 14), PARTS["right_arm"][1], "左臂缺了")
        self.assertEqual(self.at(img, 10, 26), PARTS["right_leg"][1], "左腿缺了")

    def test_garbage_input_returns_a_null_image(self):
        from app.skin_render import front_view
        self.assertTrue(front_view(b"not a png at all").isNull())
        self.assertTrue(front_view(b"").isNull())


if __name__ == "__main__":
    unittest.main()
