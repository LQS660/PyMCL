# -*- coding: utf-8 -*-
"""motion.py — 通用微动效工具：淡入淡出、滑入、数值补间、缩放脉冲。

全部尊重系统动画偏好（motion_prefs.ui_motion_ok）：系统关闭窗口动画时
直接走终态。动画对象挂在触发控件名下避免被 GC 提前回收；结束后自动
摘掉 graphics effect（effect 常驻会拖慢绘制）。
"""

from PySide6.QtCore import (Property, QAbstractAnimation, QEasingCurve,
                            QPoint, QPropertyAnimation, QRectF, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsEffect, QGraphicsOpacityEffect
from qfluentwidgets import ProgressBar

from .motion_prefs import ui_motion_ok

# 补间动画没有天然宿主控件时的寄存处（防 GC）
_TWEENS: list = []

_STOPPED = QAbstractAnimation.Stopped


def _keep(widget, *anims):
    """把动画记在控件名下防 GC；回到 Stopped 就摘掉。

    清理挂在 stateChanged 而不是 finished 上：finished 只在跑到终点时发，
    被 stop() 打断、或 target（graphics effect）被新装的 effect 顶掉而
    销毁时都发不出来，那条动画就永远赖在 _mcl_anims 里——pop 靠这张表
    判重入，一条僵尸就够让它以后再也不脉冲。
    """
    box = getattr(widget, "_mcl_anims", None)
    if box is None:
        box = []
        widget._mcl_anims = box
    box.extend(anims)

    def _bind(a):
        def _drop(new_state, _old_state=None):
            if new_state == _STOPPED and a in box:
                box.remove(a)
        a.stateChanged.connect(_drop)
    for a in anims:
        _bind(a)


def fade(widget, start: float = 0.0, end: float = 1.0, ms: int = 180,
         on_done=None):
    """透明度过渡。结束移除 effect。"""
    if not ui_motion_ok() or not widget.isVisible():
        if on_done:
            on_done()
        return
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        widget.setGraphicsEffect(None)
        if on_done:
            on_done()
    a.finished.connect(done)
    _keep(widget, a)
    a.start()


def slide_in(widget, dy: int = -10, ms: int = 200):
    """从上方滑入 + 淡入（浮层工具条用）。结束后 y 恢复原值。"""
    if not ui_motion_ok():
        return
    x0, y0 = widget.x(), widget.y()
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    p = QVariantAnimation(widget)
    p.setDuration(ms)
    p.setStartValue(float(-dy))
    p.setEndValue(0.0)
    p.setEasingCurve(QEasingCurve.OutCubic)
    p.valueChanged.connect(lambda v: widget.move(x0, y0 + int(v)))
    o = QPropertyAnimation(eff, b"opacity", widget)
    o.setDuration(ms)
    o.setStartValue(0.0)
    o.setEndValue(1.0)
    o.setEasingCurve(QEasingCurve.OutCubic)
    o.finished.connect(lambda: widget.setGraphicsEffect(None))
    _keep(widget, p, o)
    p.start()
    o.start()


def _prune_tweens():
    """把已经随宿主一起析构的补间从寄存处摘掉（宿主先死时 stateChanged 不一定送得到）。"""
    from shiboken6 import isValid
    _TWEENS[:] = [t for t in _TWEENS if isValid(t)]


def tween(setter, start, end, ms: int = 240, on_done=None, context=None):
    """数值补间：setter(v) 按帧调用（高度展开、位移等）。

    `context` 是 setter / on_done 要碰的那个控件。给了它，动画就挂在它名下：
    控件先死，动画随它一起析构，valueChanged / finished 都不会再发，setter 不会
    打在死控件上。不给的话动画没有父对象、靠 _TWEENS 续命，控件死了它照跑
    ——每帧一条 `Internal C++ object already deleted`，跟 ThumbnailTile /
    call_async 那一批是同一种病（回调活得比控件久）。所以 setter 碰控件就必须
    给 context，`tests/test_motion_tween_lifetime.py` 扫着 app/ 下的每一处调用。
    """
    if not ui_motion_ok() or start == end:
        setter(end)
        if on_done:
            on_done()
        return None
    _prune_tweens()
    a = QVariantAnimation(context)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.valueChanged.connect(lambda v: setter(v))
    if on_done:
        a.finished.connect(on_done)
    _TWEENS.append(a)

    def _drop():
        if a in _TWEENS:
            _TWEENS.remove(a)
        # 挂了 context 的，C++ 那边归 context 管；跑完就把所有权还给 Python，
        # 调用方手里的引用一松它就释放，不会在 context 名下越积越多。
        # context 先死的场合 a 已经没了，摸它就是 RuntimeError，先验一下。
        from shiboken6 import isValid
        if isValid(a) and a.parent() is not None:
            a.setParent(None)

    def _release(new_state, _old_state=None):
        # 同 _keep：finished 只在跑到终点时发，调用方 stop() 打断的（侧栏分组
        # 连点就是）得靠 stateChanged 才摘得掉，否则 _TWEENS 只进不出。
        # 摘除推到下一拍，别在它自己的信号栈里把 C++ 对象拆了。
        if new_state == _STOPPED:
            QTimer.singleShot(0, _drop)
    a.stateChanged.connect(_release)
    a.start()
    return a


class _ScaleEffect(QGraphicsEffect):
    """围绕源中心缩放绘制的 graphics effect。

    QWidget 没有 transform；QGraphicsScale 是 QGraphicsItem 的 transform，
    不是 QGraphicsEffect，挂到 QWidget.setGraphicsEffect 上会直接 TypeError。
    这里自己画：放大时通过 boundingRectFor 扩大重绘区，避免被裁掉。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, s: float):
        s = float(s)
        if s == self._scale:
            return
        self._scale = s
        self.updateBoundingRect()
        self.update()

    scale = Property(float, _get_scale, _set_scale)

    def boundingRectFor(self, rect: QRectF) -> QRectF:
        k = max(1.0, self._scale)
        if k == 1.0:
            return QRectF(rect)
        c = rect.center()
        w, h = rect.width() * k, rect.height() * k
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def draw(self, painter: QPainter):
        k = self._scale
        if abs(k - 1.0) < 1e-3:
            self.drawSource(painter)
            return
        # 不能用 drawSource：源是 QWidget 时它直接把控件画到设备上、不吃
        # painter 的变换，缩放会被无视（画面上一动不动）。要先把源取成像素图
        # 再由 painter 带变换画出去——QGraphicsOpacityEffect 也是这么做的。
        offset = QPoint()
        pm = self.sourcePixmap(Qt.LogicalCoordinates, offset, QGraphicsEffect.NoPad)
        if pm.isNull():
            return
        dpr = pm.devicePixelRatio() or 1.0
        cx = offset.x() + pm.width() / dpr / 2
        cy = offset.y() + pm.height() / dpr / 2
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.translate(cx, cy)
        painter.scale(k, k)
        painter.translate(-cx, -cy)
        painter.drawPixmap(offset, pm)
        painter.restore()


def pop(widget, scale: float = 1.35, ms: int = 260):
    """缩放脉冲（角标计数变化）：effect 层围绕中心缩放绘制，不动布局。

    上一个脉冲还没放完就跳过（下载计数高频变化时会连成一片抖动）。
    """
    if not ui_motion_ok() or not widget.isVisible():
        return
    if getattr(widget, "_mcl_anims", None):
        return
    eff = _ScaleEffect(widget)
    eff._set_scale(scale)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"scale", widget)
    a.setDuration(ms)
    a.setStartValue(float(scale))
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutBack)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    _keep(widget, a)
    a.start()


class SmoothProgressBar(ProgressBar):
    """进度条补间：setValue 的变化走 240ms 缓动，进度增长不再跳格。

    value() 语义不变（立即反映目标值），只有绘制是渐进的。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown = super().value()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(
            lambda v: SmoothProgressBar.setValue(self, int(v)))

    def setValue(self, v):
        v = int(v)
        anim = getattr(self, "_anim", None)
        if anim is None:  # 父类构造期间会先调 setValue(0)
            ProgressBar.setValue(self, v)
            self._shown = v
            return
        if not ui_motion_ok():
            anim.stop()
            self._shown = v
            ProgressBar.setValue(self, v)
            return
        if anim.state() == QVariantAnimation.Running:
            anim.stop()          # 密集更新：直接跳终值，不再重启动画
            self._shown = v
            ProgressBar.setValue(self, v)
            return
        anim.setStartValue(self._shown)
        anim.setEndValue(v)
        self._shown = v
        anim.start()
