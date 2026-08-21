# -*- coding: utf-8 -*-
"""fly_anim.py — "飞入下载任务"动画。

点击安装/下载时，源控件位置的图标缩成小球，沿二次贝塞尔抛物线
抛入左侧导航的"下载任务"按钮，落点扩散涟漪并累加角标计数。

用法::

    window.fly_to_tasks(source_widget, text="模组名", color="#4C8BF5")
"""

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def _bezier(p0: QPointF, pc: QPointF, p1: QPointF, t: float) -> QPointF:
    u = 1.0 - t
    return QPointF(
        u * u * p0.x() + 2 * u * t * pc.x() + t * t * p1.x(),
        u * u * p0.y() + 2 * u * t * pc.y() + t * t * p1.y(),
    )


def _clamp_control(p0: QPointF, p1: QPointF, window: QWidget) -> QPointF:
    """弧高随距离缩放，并夹在窗口内，避免短距/贴边飞出屏幕。"""
    mid_x = (p0.x() + p1.x()) / 2
    dist = ((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2) ** 0.5
    arc = max(48.0, min(150.0, dist * 0.35))
    cy = min(p0.y(), p1.y()) - arc
    margin = 8.0
    cy = max(margin, min(cy, window.height() - margin))
    mid_x = max(margin, min(mid_x, window.width() - margin))
    return QPointF(mid_x, cy)


class FlyBall(QWidget):
    """固定画布；缩放/透明度只在 paint 里算，避免每帧 resize + OpacityEffect。"""

    CANVAS = 48
    START_SIZE = 44
    END_SIZE = 14

    def __init__(self, parent: QWidget, letter: str, color: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._letter = letter
        self._color = QColor(color)
        self._t = 0.0
        self._alpha = 1.0
        self.setFixedSize(self.CANVAS, self.CANVAS)

    def set_progress(self, center: QPointF, t: float):
        self._t = t
        self._alpha = 1.0 if t < 0.75 else max(0.0, (1.0 - t) / 0.25)
        self.move(round(center.x() - self.CANVAS / 2), round(center.y() - self.CANVAS / 2))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._alpha)
        size = self.START_SIZE + (self.END_SIZE - self.START_SIZE) * self._t
        ox = (self.CANVAS - size) / 2
        oy = (self.CANVAS - size) / 2
        rect = QRectF(ox, oy, size, size).adjusted(0.5, 0.5, -0.5, -0.5)
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
    """落点扩散涟漪：圆环放大并淡出（自绘透明度）。"""

    MAX_R = 24
    DURATION = 420

    def __init__(self, parent: QWidget, center: QPoint, color: str):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._color = QColor(color)
        self._r = 6.0
        self._alpha = 0.55
        side = self.MAX_R * 2 + 8
        self.setFixedSize(side, side)
        self.move(center.x() - side // 2, center.y() - side // 2)

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(self.DURATION)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self.deleteLater)
        self._anim = anim
        self.show()
        self.raise_()
        anim.start()

    def _step(self, t: float):
        self._r = 6 + (self.MAX_R - 6) * t
        self._alpha = 0.55 * (1 - t)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._alpha)
        c = QColor(self._color)
        painter.setPen(QPen(c, 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(self.rect().center()), self._r, self._r)


def pulse_widget(widget: QWidget, duration: int = 220):
    """角标/按钮落地反馈：短促放大再回弹。"""
    from .ui_alive import widget_alive
    if not widget_alive(widget):
        return
    start = widget.geometry()
    cx, cy = start.center().x(), start.center().y()
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def step(t: float):
        if not widget_alive(widget):
            return
        # 0→0.5 放大到 1.12，0.5→1 回到 1.0
        if t < 0.5:
            s = 1.0 + 0.12 * (t / 0.5)
        else:
            s = 1.12 - 0.12 * ((t - 0.5) / 0.5)
        w = max(4, round(start.width() * s))
        h = max(4, round(start.height() * s))
        widget.setGeometry(cx - w // 2, cy - h // 2, w, h)

    def done():
        if widget_alive(widget):
            widget.setGeometry(start)

    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    anim.start()
    widget._pulse_anim = anim  # 防 GC


def fly_to(window: QWidget, source: QWidget, letter: str, color: str,
           target_key: str = "tasksPage", on_landed=None, duration: int = 620,
           target=None):
    """从 source 控件中心抛物线飞一个小球到导航项 / 指定控件中心。"""
    from .ui_alive import widget_alive
    if not widget_alive(window) or not widget_alive(source):
        return None
    start = source.mapTo(window, source.rect().center())
    if target is not None and widget_alive(target):
        end = target.mapTo(window, target.rect().center())
    else:
        nav = getattr(window, "navigationInterface", None)
        target_btn = nav.widget(target_key) if nav is not None else None
        if target_btn is None:
            side = getattr(window, "side", None)
            target_btn = side.button("tasks") if side is not None else None
        if target_btn is None or not widget_alive(target_btn):
            end = QPoint(window.width() // 2, window.height() - 28)
        else:
            end = target_btn.mapTo(window, target_btn.rect().center())

    control = _clamp_control(QPointF(start), QPointF(end), window)

    ball = FlyBall(window, letter, color)
    ball.show()
    ball.raise_()

    jobs = getattr(window, "_fly_jobs", None)
    if jobs is None:
        window._fly_jobs = []
        jobs = window._fly_jobs
    while len(jobs) >= 2:
        old = jobs.pop(0)
        try:
            old.stop()
            cleanup = getattr(old, "_fly_cleanup", None)
            if cleanup is not None:
                cleanup()
        except RuntimeError:
            pass

    anim = QVariantAnimation(window)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.InOutCubic)
    jobs.append(anim)

    def step(t: float):
        if not widget_alive(ball):
            return
        ball.set_progress(_bezier(QPointF(start), control, QPointF(end), t), t)

    finished = [False]

    def done():
        if finished[0]:
            return
        finished[0] = True
        try:
            jobs.remove(anim)
        except ValueError:
            pass
        if widget_alive(ball):
            ball.deleteLater()
        if widget_alive(window):
            Ripple(window, end, color)
            badge = getattr(window, "task_badge", None)
            if badge is not None and widget_alive(badge) and badge.isVisible():
                pulse_widget(badge)
            elif target is not None and widget_alive(target):
                pulse_widget(target)
        if on_landed:
            on_landed()
        anim.deleteLater()

    anim._fly_cleanup = done
    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    step(0.0)
    anim.start()
    return anim
