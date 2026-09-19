# -*- coding: utf-8 -*-
"""AI 页用的几枚 Lucide 线性图标（ISC）+ 两个小动效控件。

路径数据来自 Lucide 官方，与 ZCode 3.12 聊天界面同一套：思考行用 brain +
chevron-right，工具行用 loader-circle / circle-check / circle-slash-2 / circle-x，
搜索 / 读 / 写三类工具再各配一枚类型图标。启动器特有的安装 / 启动 / 删除 /
诊断类工具在 ZCode 里没有对应物，不硬套，那些行只显示状态图标。

只收 AI 页真用到的：别把整个图标库搬进来。
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLabel, QWidget

# 24×24 viewBox、stroke=currentColor、线宽 2、圆头圆角——Lucide 的固定规格。
ICONS: dict[str, tuple[str, ...]] = {
    "brain": (
        '<path d="M12 18V5"/>',
        '<path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4"/>',
        '<path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5"/>',
        '<path d="M17.997 5.125a4 4 0 0 1 2.526 5.77"/>',
        '<path d="M18 18a4 4 0 0 0 2-7.464"/>',
        '<path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517"/>',
        '<path d="M6 18a4 4 0 0 1-2-7.464"/>',
        '<path d="M6.003 5.125a4 4 0 0 0-2.526 5.77"/>',
    ),
    "chevron-right": ('<path d="m9 18 6-6-6-6"/>',),
    "loader-circle": ('<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',),
    "circle-check": ('<circle cx="12" cy="12" r="10"/>', '<path d="m9 12 2 2 4-4"/>'),
    "circle-slash-2": ('<circle cx="12" cy="12" r="10"/>', '<path d="M22 2 2 22"/>'),
    "circle-x": ('<circle cx="12" cy="12" r="10"/>', '<path d="m15 9-6 6"/>', '<path d="m9 9 6 6"/>'),
    "search": ('<path d="m21 21-4.34-4.34"/>', '<circle cx="11" cy="11" r="8"/>'),
    "file-text": (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
        'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>',
        '<path d="M14 2v5a1 1 0 0 0 1 1h5"/>',
        '<path d="M10 9H8"/>',
        '<path d="M16 13H8"/>',
        '<path d="M16 17H8"/>',
    ),
    "file-pen-line": (
        '<path d="M14.364 13.634a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837'
        'a2 2 0 0 0 .854-.506l4.013-4.009a1 1 0 0 0-3.004-3.004z"/>',
        '<path d="M14.487 7.858A1 1 0 0 1 14 7V2"/>',
        '<path d="M20 19.645V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8'
        'a2.4 2.4 0 0 1 1.704.706l2.516 2.516"/>',
        '<path d="M8 18h1"/>',
    ),
    # ---- 权限管理：档位卡片 / 规则行为 / 确认卡 ----
    "shield-alert": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1'
        'c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
        '<path d="M12 8v4"/>',
        '<path d="M12 16h.01"/>',
    ),
    "eye": (
        '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696'
        ' 10.75 10.75 0 0 1-19.876 0"/>',
        '<circle cx="12" cy="12" r="3"/>',
    ),
    "sparkles": (
        '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051'
        'a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0'
        'l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051'
        'a2 2 0 0 0 1.594-1.594z"/>',
        '<path d="M20 2v4"/>',
        '<path d="M22 4h-4"/>',
        '<circle cx="4" cy="20" r="2"/>',
    ),
    "sliders-horizontal": (
        '<path d="M10 5H3"/>', '<path d="M12 19H3"/>', '<path d="M14 3v4"/>',
        '<path d="M16 17v4"/>', '<path d="M21 12h-9"/>', '<path d="M21 19h-5"/>',
        '<path d="M21 5h-7"/>', '<path d="M8 10v4"/>', '<path d="M8 12H3"/>',
    ),
    "ban": ('<circle cx="12" cy="12" r="10"/>', '<path d="M4.929 4.929 19.07 19.071"/>'),
    "trash-2": (
        '<path d="M10 11v6"/>', '<path d="M14 11v6"/>',
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
        '<path d="M3 6h18"/>',
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    ),
}

# 工具名 → 类型图标。只映射 ZCode 也有的三类（搜索 / 读文件 / 改文件），
# 其余启动器特有工具返回 None，由状态图标占位。
_TOOL_ICONS = {
    "search_versions": "search", "search_mods": "search", "search_modpacks": "search",
    "search_content": "search", "search_worlds": "search",
    "read_mod_config": "file-text", "get_latest_log": "file-text",
    "get_crash_report": "file-text", "read_artifact": "file-text",
    "list_mod_configs": "file-text",
    "write_mod_config": "file-pen-line",
}


def tool_icon(tool_name: str) -> str | None:
    return _TOOL_ICONS.get(tool_name or "")


def svg_bytes(name: str, color: str) -> bytes:
    body = "".join(ICONS.get(name) or ())
    doc = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )
    return doc.encode("utf-8")


def _dpr(widget: QWidget | None) -> float:
    try:
        if widget is not None:
            return float(widget.devicePixelRatioF())
        scr = QApplication.primaryScreen()
        return float(scr.devicePixelRatio()) if scr else 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def pixmap(name: str, size: int, color: str, dpr: float = 1.0) -> QPixmap:
    """按逻辑尺寸 size 渲染一枚着色图标，按 dpr 放大以免高分屏发糊。"""
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg_bytes(name, color)))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


class IconLabel(QWidget):
    """一枚可换图、可着色、可旋转（含自旋）的图标位。

    set_icon 换图与颜色；set_angle 用于折叠箭头转 90°；spin() 打开就是
    loader-circle 那种一秒一圈的旋转。底图只渲染一次，旋转在 paintEvent 里做。
    """

    def __init__(self, name: str = "", size: int = 16, color: str = "#888888", parent=None):
        super().__init__(parent)
        self._name = name
        self._size = int(size)
        self._color = color
        self._angle = 0.0
        self._pm: QPixmap | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(self._size, self._size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._rebuild()

    @property
    def name(self) -> str:
        return self._name

    def set_icon(self, name: str, color: str | None = None):
        if color is not None:
            self._color = color
        self._name = name or ""
        self._rebuild()

    def set_color(self, color: str):
        if color != self._color:
            self._color = color
            self._rebuild()

    def set_angle(self, deg: float):
        self._angle = float(deg) % 360.0
        self.update()

    def spin(self, on: bool):
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
            self._angle = 0.0
            self.update()

    def _tick(self):
        # 16ms × 60 步 ≈ 1 秒一圈，与 ZCode 的 animate-spin 同速
        self._angle = (self._angle + 6.0) % 360.0
        self.update()

    def _rebuild(self):
        self._pm = pixmap(self._name, self._size, self._color, _dpr(self)) if self._name else None
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._pm is not None and abs(self._pm.devicePixelRatio() - _dpr(self)) > 0.01:
            self._rebuild()

    def paintEvent(self, _event):
        if self._pm is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        half = self._size / 2.0
        p.translate(half, half)
        if self._angle:
            p.rotate(self._angle)
        p.drawPixmap(QPointF(-half, -half), self._pm)
        p.end()


class ShimmerLabel(QLabel):
    """文字流光：一道淡色光带从左扫到右再停两秒，循环。

    对齐 ZCode 的 .animated-gradient-text（4s 周期，前 2s 扫过、后 2s 停住）。
    不激活时就是普通 QLabel，样式表照常生效。
    """

    _PERIOD_MS = 4000
    _SWEEP_MS = 2000

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._active = False
        self._elapsed = 0
        self._strong = QColor("#2B2B2B")
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_shimmer_color(self, color: str):
        self._strong = QColor(color)
        self.update()

    def set_active(self, on: bool):
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        self._elapsed = 0
        if on:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._elapsed = (self._elapsed + self._timer.interval()) % self._PERIOD_MS
        self.update()

    def paintEvent(self, event):
        if not self._active or not self.text():
            super().paintEvent(event)
            return
        rect = self.contentsRect()
        w = max(1.0, float(rect.width()))
        # 渐变「贴图」宽 3w：前 2s 从 x0=-2w 滑到 x0=0，光带（贴图 50% 处）由
        # -0.5w 扫到 1.5w；后 2s 停在屏外
        progress = min(1.0, self._elapsed / float(self._SWEEP_MS))
        x0 = rect.left() - 2.0 * w + 2.0 * w * progress
        soft = QColor(self._strong)
        soft.setAlpha(0x38)
        grad = QLinearGradient(QPointF(x0, 0), QPointF(x0 + 3.0 * w, 0))
        grad.setColorAt(0.0, self._strong)
        grad.setColorAt(0.34, self._strong)
        grad.setColorAt(0.5, soft)
        grad.setColorAt(0.66, self._strong)
        grad.setColorAt(1.0, self._strong)
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.font())
        p.setPen(QPen(QBrush(grad), 0))
        flags = int(self.alignment())
        if self.wordWrap():
            flags |= int(Qt.TextWordWrap)
        p.drawText(rect, flags, self.text())
        p.end()
