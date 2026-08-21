# -*- coding: utf-8 -*-
"""widgets.py — 公共视觉组件：图标磁贴、胶囊徽章、渐变 Banner。"""

from PySide6.QtCore import Qt, QRectF, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, LineEdit, MessageBoxBase, StrongBodyLabel, SubtitleLabel,
    isDarkTheme,
)
from mclauncher.i18n import tr


class InputDialog(MessageBoxBase):
    """Fluent 风格的单行输入对话框。"""

    def __init__(self, title: str, label: str = "", text: str = "",
                 placeholder: str = "", parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        if label:
            self.viewLayout.addWidget(BodyLabel(label, self))
        self.edit = LineEdit(self)
        self.edit.setText(text)
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText(tr("确定"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(380)
        self.edit.setFocus()

    def value(self) -> str:
        return self.edit.text().strip()


def prompt_feedback_consent(parent) -> bool:
    """首次（或未同意时）弹窗，必须手动点同意才会上传。"""
    from qfluentwidgets import MessageBox
    from mclauncher import feedback as fb
    box = MessageBox(
        tr("是否上传诊断数据"),
        tr("第一次打开需要你亲自选择。\n\n"
        "同意后才会向开发者上传：\n"
        "· 你提交的反馈内容\n"
        "· 本机配置（CPU / 内存 / 显卡 / Java / 实例）\n\n"
        "暂不同意则不会上传，以后可在设置里更改。"),
        parent,
    )
    box.yesButton.setText(tr("同意"))
    box.cancelButton.setText(tr("暂不同意"))
    ok = bool(box.exec())
    fb.set_consent(ok)
    if ok:
        fb.start_heartbeat()
    else:
        fb.stop_heartbeat(send_offline=False)
    return ok


class ComboDialog(MessageBoxBase):
    """Fluent 风格的下拉选择对话框。"""

    def __init__(self, title: str, label: str = "", items=None, current: str = "",
                 parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        if label:
            hint = BodyLabel(label, self)
            hint.setWordWrap(True)
            self.viewLayout.addWidget(hint)
        self.combo = ComboBox(self)
        self.combo.addItems(list(items or []))
        if current and current in (items or []):
            self.combo.setCurrentText(current)
        self.viewLayout.addWidget(self.combo)
        self.yesButton.setText(tr("确定"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(420)

    def value(self) -> str:
        return self.combo.currentText()


class DeviceCodeDialog(MessageBoxBase):
    """微软设备代码登录提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(tr("微软账号登录"), self))
        self.hint = BodyLabel(tr("正在获取登录代码…"), self)
        self.hint.setWordWrap(True)
        self.code = StrongBodyLabel("------", self)
        self.uri = BodyLabel("", self)
        self.uri.setWordWrap(True)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.code)
        self.viewLayout.addWidget(self.uri)
        self.yesButton.setText(tr("打开浏览器"))
        self.cancelButton.setText(tr("关闭"))
        self.widget.setMinimumWidth(420)
        self._uri = ""
        try:
            self.yesButton.clicked.disconnect()
        except TypeError:
            pass
        self.yesButton.clicked.connect(self._open)

    def show_code(self, code: str, uri: str):
        self._uri = uri
        self.code.setText(code)
        self.uri.setText(uri)
        self.hint.setText(tr("请在浏览器打开下面的地址并输入代码："))

    def show_status(self, text: str):
        self.hint.setText(text)

    def _open(self):
        if self._uri:
            QDesktopServices.openUrl(QUrl(self._uri))


PALETTE = [
    "#2E9B6B", "#7C5CD6", "#3E7C4F", "#E8862E",
    "#D95568", "#2E9FB8", "#8A6FBD", "#5B8C5A",
]


def pick_color(name: str) -> str:
    return PALETTE[hash(name) % len(PALETTE)]


def grid_columns(scroll, page, card_w: int, spacing: int = 12, gutter: int = 8) -> int:
    """按滚动区**可视宽度**算卡片网格该放几列。

    不能拿页面自身的 width()：页面左右各有 28px 边距、网格右侧留 8px、
    还有一条竖直滚动条，这些地方都摆不下卡片。按页面宽算会多算出一列，
    网格被顶宽，反而冒出一条横向滚动条。

    viewport 在页面首次构造、还没布局时宽度不可信，这时退回按页面宽度扣掉固定边距估算；
    之后 resizeEvent 会再算一次，拿到的就是真实值。
    """
    avail = scroll.viewport().width() if scroll is not None else 0
    if avail <= card_w:
        avail = page.width() - 56
    avail -= gutter
    if avail <= 0:
        return 1
    return max(1, (avail + spacing) // (card_w + spacing))


class IconTile(QWidget):
    """圆角彩色磁贴，中间显示一个字符。"""

    def __init__(self, text: str, color: str | None = None, size: int = 44, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color or pick_color(text))
        label = QLabel(text[:1].upper() if text else "?", self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; background: transparent;"
                            f"font-size: {int(size * 0.42)}px; font-weight: 700;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.fillPath(path, self._color)
        super().paintEvent(event)


class Pill(QLabel):
    """WinUI 风格胶囊徽章。

    改颜色必须走 `set_color()`，不要在外面直接 `setStyleSheet()`：
    `paintEvent` 发现主题变了会重跑 `_apply_style()`，外部样式会被无声刷掉，
    表现就是「切一次深浅色，状态色全丢」。
    """

    def __init__(self, text: str, color: str = "#2E9B6B", parent=None, solid: bool = False):
        super().__init__(text, parent)
        self.setProperty("pymclKeepBg", True)
        self._color_hex = color
        self._solid = solid
        self._style_ver = -1
        self._apply_style()

    def set_color(self, color: str, solid: bool | None = None):
        if solid is not None:
            self._solid = solid
        self._color_hex = color
        self._apply_style()

    def _apply_style(self):
        color = self._color_hex
        if self._solid:
            self.setStyleSheet(
                f"color: white; background-color: {color};"
                "border-radius: 8px; padding: 1px 8px; font-size: 11px; font-weight: 600;"
            )
            return
        bg = QColor(color)
        bg.setAlpha(38 if not isDarkTheme() else 60)
        self.setStyleSheet(
            f"color: {color}; background-color: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            "border-radius: 9px; padding: 2px 10px; font-size: 12px; font-weight: 600;"
        )

    def paintEvent(self, event):
        from .pcl_chrome import Theme
        if self._style_ver != Theme._version:
            self._style_ver = Theme._version
            self._apply_style()
        super().paintEvent(event)


class ThumbnailTile(QWidget):
    """圆角缩略图磁贴，从 URL 加载图片。"""

    def __init__(self, text: str, thumb_url: str, size: int = 52, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pixmap = None
        self._thumb_url = thumb_url
        self._text = text[:1].upper() if text else "?"
        self._size = size
        self._loaded = False
        self._color = QColor(pick_color(text))
        self._load_thumb()

    def _load_thumb(self):
        if not self._thumb_url:
            return
        try:
            from mclauncher.thumbnails import ensure_thumb
            path = ensure_thumb(self._thumb_url)
            if path:
                from PySide6.QtGui import QPixmap
                pix = QPixmap(path)
                if not pix.isNull():
                    self._pixmap = pix.scaled(self._size, self._size,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._loaded = True
                    self.update()
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        if self._pixmap is not None:
            painter.setClipPath(path)
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            painter.fillPath(path, self._color)
            painter.setPen(Qt.NoPen)
            painter.setClipPath(path)
            font = painter.font()
            font.setPixelSize(int(self._size * 0.42))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), Qt.AlignCenter, self._text)
        super().paintEvent(event)


class BannerWidget(QFrame):
    """启动页渐变 Hero 横幅。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._g1 = QColor("#123B2A")
        self._g2 = QColor("#3E7C4F")
        self._g3 = QColor("#7BB661")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)

        left = QVBoxLayout()
        self.kicker = QLabel("MINECRAFT")
        self.kicker.setStyleSheet("color: rgba(255,255,255,170); background: transparent;"
                                  "font-size: 12px; letter-spacing: 4px; font-weight: 600;")
        self.title = QLabel(tr("准备启程"))
        self.title.setStyleSheet("color: white; background: transparent;"
                                 "font-size: 30px; font-weight: 700;")
        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color: rgba(255,255,255,190); background: transparent;"
                                    "font-size: 13px;")
        left.addWidget(self.kicker)
        left.addSpacing(6)
        left.addWidget(self.title)
        left.addSpacing(6)
        left.addWidget(self.subtitle)
        left.addStretch(1)

        layout.addLayout(left, 1)
        self.right_area = QVBoxLayout()
        self.right_area.setSpacing(10)
        layout.addLayout(self.right_area)

    def set_info(self, title: str, subtitle: str):
        self.title.setText(title)
        self.subtitle.setText(subtitle)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, self._g1)
        grad.setColorAt(0.55, self._g2)
        grad.setColorAt(1.0, self._g3)
        painter.fillPath(path, grad)

        painter.setClipPath(path)
        painter.setPen(Qt.NoPen)
        glow = QColor(255, 255, 255, 18)
        painter.setBrush(glow)
        painter.drawEllipse(int(rect.right() - 260), -120, 320, 320)
        painter.drawEllipse(int(rect.right() - 420), int(rect.bottom() - 140), 220, 220)
        painter.setClipping(False)


class EmptyState(QWidget):
    """空状态提示。"""

    def __init__(self, icon, text: str, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self._style_ver = -1
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._text_label = CaptionLabel(text)
        self._text_label.setAlignment(Qt.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._icon_label)
        layout.addSpacing(10)
        layout.addWidget(self._text_label)
        layout.addStretch(1)
        self._apply_style()

    def restyle(self):
        self._apply_style()

    def _apply_style(self):
        from .pcl_chrome import Theme
        self._icon_label.setPixmap(self._icon.icon(color=QColor(140, 140, 140)).pixmap(48, 48))
        self._text_label.setStyleSheet(f"color: {Theme.muted}; background: transparent;")
