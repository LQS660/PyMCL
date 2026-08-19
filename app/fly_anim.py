# -*- coding: utf-8 -*-
"""fly_anim.py — "飞入下载任务"动画。

点击安装/下载时，源控件位置的图标缩成小球，沿二次贝塞尔抛物线
抛入左侧导航的"下载任务"按钮，落点扩散涟漪并累加角标计数。

用法::

    window.fly_to_tasks(source_widget, text="模组名", color="#4C8BF5")
"""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


def _bezier(p0: QPointF, pc: QPointF, p1: QPointF, t: float) -> QPointF:
    """二次贝塞尔曲线取点。"""
    u = 1.0 - t
    return QPointF(
        u * u * p0.x() + 2 * u * t * pc.x() + t * t * p1.x(),
        u * u * p0.y() + 2 * u * t * pc.y() + t * t * p1.y(),
    )


class FlyBall(QWidget):
    """飞行中的小球：从图标尺寸逐渐缩成圆点，前段显示首字母，尾段渐隐。"""

    START_SIZE = 44
    END_SIZE = 14

    def __init__(self, parent: QWidget, letter: str, color: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._letter = letter
        self._color = QColor(color)
        self._t = 0.0
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self.resize(self.START_SIZE, self.START_SIZE)

    def set_progress(self, center: QPointF, t: float):
        self._t = t
        size = round(self.START_SIZE + (self.END_SIZE - self.START_SIZE) * t)
        self.setFixedSize(size, size)
        self.move(round(center.x() - size / 2), round(center.y() - size / 2))
        # 最后 25% 渐隐
        self._opacity.setOpacity(1.0 if t < 0.75 else max(0.0, (1.0 - t) / 0.25))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # 圆角半径从方磁贴(10px)逐渐变到正圆
        radius = min(rect.width() / 2, 10 + (rect.width() / 2 - 10) * self._t)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, self._color)
        if self._t < 0.45 and self._letter:
            painter.setPen(Qt.white)
            font = painter.font()
            font.setPixelSize(max(8, int(rect.width() * 0.42)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self._letter)


class Ripple(QWidget):
    """落点扩散涟漪：圆环放大并淡出。"""

    MAX_R = 24
    DURATION = 420

    def __init__(self, parent: QWidget, center: QPoint, color: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._color = QColor(color)
        self._r = 6.0
        side = self.MAX_R * 2 + 8
        self.setFixedSize(side, side)
        self.move(center.x() - side // 2, center.y() - side // 2)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.55)

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(self.DURATION)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self.deleteLater)
        self._anim = anim  # 防 GC
        self.show()
        self.raise_()
        anim.start()

    def _step(self, t: float):
        self._r = 6 + (self.MAX_R - 6) * t
        self._opacity.setOpacity(0.55 * (1 - t))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self._color, 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(self.rect().center()), self._r, self._r)


def fly_to(window: QWidget, source: QWidget, letter: str, color: str,
           target_key: str = "tasksPage", on_landed=None, duration: int = 620,
           target=None):
    """从 source 控件中心抛物线飞一个小球到导航项 / 指定控件中心。"""
    start = source.mapTo(window, source.rect().center())
    if target is not None:
        end = target.mapTo(window, target.rect().center())
    else:
        nav = getattr(window, "navigationInterface", None)
        target_btn = nav.widget(target_key) if nav is not None else None
        if target_btn is None:
            end = QPoint(window.width() // 2, window.height() - 28)
        else:
            end = target_btn.mapTo(window, target_btn.rect().center())

    # 控制点：起点终点连线上方，形成上抛弧线
    control = QPointF((start.x() + end.x()) / 2, min(start.y(), end.y()) - 150)

    ball = FlyBall(window, letter, color)
    ball.show()
    ball.raise_()

    anim = QVariantAnimation(window)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)

    def step(t: float):
        ball.set_progress(_bezier(QPointF(start), control, QPointF(end), t), t)

    def done():
        ball.deleteLater()
        Ripple(window, end, color)
        if on_landed:
            on_landed()
        anim.deleteLater()

    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    step(0.0)
    anim.start()
    return anim
