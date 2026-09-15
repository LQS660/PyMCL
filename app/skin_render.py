# -*- coding: utf-8 -*-
"""把 Minecraft 皮肤贴图拼成一张正面小人图。

离线自定义皮肤要给用户一眼能确认的反馈：贴图本身是一张 64x64 的图集，
原样摆上去谁也看不出自己选对没有。这里只拼正面这一眼——头、身体、两条
胳膊两条腿，外加 1.8 之后的外层（帽子 / 外套），够确认就行。

尺寸按贴图像素 1:1 拼（16x32），放大交给调用方，且必须用 FastTransformation：
像素画一平滑插值就糊成一团。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QTransform

# 左右翻转。QImage.mirrored() 在 Qt6 里已标记弃用，换成等价的变换
_FLIP_X = QTransform().scale(-1, 1)

# 正面小人的画布：经典手臂 4px，两条胳膊加身体正好 16 宽
CANVAS_W, CANVAS_H = 16, 32
CLASSIC_ARM, SLIM_ARM = 4, 3


def front_view(png: bytes, slim: bool = False) -> QImage:
    """返回 16x32 的正面小人；贴图读不出来时返回空 QImage。

    64x32 是 1.8 以前的老格式：贴图里只有右半边，左臂左腿镜像右边那份，
    外层也只有帽子。照着 64x64 的偏移去取会取到空白，小人会缺胳膊少腿。
    """
    tex = QImage.fromData(png, "PNG")
    if tex.isNull() or tex.width() < 64 or tex.height() < 32:
        return QImage()
    tex = tex.convertToFormat(QImage.Format_ARGB32)
    legacy = tex.height() < 64
    arm = SLIM_ARM if slim else CLASSIC_ARM

    out = QImage(CANVAS_W, CANVAS_H, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    painter = QPainter(out)

    def blit(src, dest, mirror=False):
        x, y, w, h = src
        part = tex.copy(x, y, w, h)
        if mirror:
            part = part.transformed(_FLIP_X)
        painter.drawImage(dest[0], dest[1], part)

    blit((8, 8, 8, 8), (4, 0))                  # 头
    blit((20, 20, 8, 12), (4, 8))               # 身体
    blit((44, 20, arm, 12), (4 - arm, 8))       # 右臂（画面左侧）
    blit((4, 20, 4, 12), (4, 20))               # 右腿
    if legacy:
        blit((44, 20, arm, 12), (12, 8), mirror=True)
        blit((4, 20, 4, 12), (8, 20), mirror=True)
    else:
        blit((36, 52, arm, 12), (12, 8))
        blit((20, 52, 4, 12), (8, 20))

    blit((40, 8, 8, 8), (4, 0))                 # 帽子（两种格式都有）
    if not legacy:
        blit((20, 36, 8, 12), (4, 8))           # 外套
        blit((44, 36, arm, 12), (4 - arm, 8))
        blit((52, 52, arm, 12), (12, 8))
        blit((4, 36, 4, 12), (4, 20))
        blit((4, 52, 4, 12), (8, 20))

    painter.end()
    return out
