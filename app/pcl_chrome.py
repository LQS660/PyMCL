# -*- coding: utf-8 -*-
"""PCL 风格色板：细顶栏 + 左侧主导航。深浅色运行时切换。"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget, QGraphicsOpacityEffect,
)
from qframelesswindow import TitleBar


class Theme:
    """运行时色板。页面样式请读 Theme.xxx，不要缓存导入时的常量。"""

    dark = False
    green = "#2E9B6B"
    green_deep = "#1E7A52"
    bg = "#FFFFFF"
    card = "#FFFFFF"
    line = "#E6E6E6"
    text = "#2B2B2B"
    muted = "#888888"
    title = "#1B7A54"
    hover = "#F3F7F5"
    chip = "#F0F4F8"
    btn_bg = "#FFFFFF"
    row_hover = "#F3F7F5"
    row_line = "#EEF3F7"

    @classmethod
    def apply(cls, dark: bool):
        cls.dark = bool(dark)
        if cls.dark:
            cls.bg = "#1B1B1B"
            cls.card = "#242424"
            cls.line = "#3A3A3A"
            cls.text = "#E8E8E8"
            cls.muted = "#9A9A9A"
            cls.title = "#6FCF9A"
            cls.hover = "#2A332F"
            cls.chip = "#333333"
            cls.btn_bg = "#2C2C2C"
            cls.row_hover = "#2A332F"
            cls.row_line = "#333333"
        else:
            cls.bg = "#FFFFFF"
            cls.card = "#FFFFFF"
            cls.line = "#E6E6E6"
            cls.text = "#2B2B2B"
            cls.muted = "#888888"
            cls.title = "#1B7A54"
            cls.hover = "#F3F7F5"
            cls.chip = "#F0F4F8"
            cls.btn_bg = "#FFFFFF"
            cls.row_hover = "#F3F7F5"
            cls.row_line = "#EEF3F7"
        _sync_aliases()


def _sync_aliases():
    global PCL_BG, PCL_CARD, PCL_LINE, PCL_TEXT, PCL_MUTED, PCL_TITLE, PCL_HOVER
    PCL_BG = Theme.bg
    PCL_CARD = Theme.card
    PCL_LINE = Theme.line
    PCL_TEXT = Theme.text
    PCL_MUTED = Theme.muted
    PCL_TITLE = Theme.title
    PCL_HOVER = Theme.hover


PCL_GREEN = "#2E9B6B"
PCL_GREEN_DEEP = "#1E7A52"
PCL_BLUE = PCL_GREEN
PCL_BLUE_DEEP = PCL_GREEN_DEEP
PCL_BG = Theme.bg
PCL_CARD = Theme.card
PCL_LINE = Theme.line
PCL_TEXT = Theme.text
PCL_MUTED = Theme.muted
PCL_TITLE = Theme.title
PCL_HOVER = Theme.hover
TITLE_H = 40
SIDE_W = 188


def ghost_btn_qss() -> str:
    return (
        f"PushButton {{ border: 1px solid {Theme.green}; color: {Theme.green};"
        f" background: {Theme.btn_bg}; border-radius: 4px; }}"
        f"PushButton:hover {{ background: {Theme.hover}; }}"
    )


def row_qss(name: str = "pclRow") -> str:
    return (
        f"#{name} {{ background: transparent; border-bottom: 1px solid {Theme.row_line}; }}"
        f"#{name}:hover {{ background: {Theme.row_hover}; }}"
    )


def chip_qss() -> str:
    return (
        f"color: {Theme.muted}; background: {Theme.chip}; border-radius: 3px;"
        " padding: 1px 6px; font-size: 11px;"
    )


def _icon(fif, color: str, size: int = 18):
    return fif.icon(color=QColor(color)).pixmap(size, size)


class PclTitleBar(TitleBar):
    """仅品牌 + 窗口按钮，不含主导航。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(TITLE_H)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.maxBtn.hide()
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)
        brand = QLabel("PyMCL")
        brand.setObjectName("pclBrand")
        self._brand = brand
        self.hBoxLayout.insertWidget(0, brand, 0, Qt.AlignVCenter)
        self.restyle()

    def restyle(self):
        self.setStyleSheet(
            f"PclTitleBar {{ background-color: {Theme.bg}; border-bottom: 1px solid {Theme.line}; }}"
            f"QLabel#pclBrand {{ color: {Theme.text}; font-size: 16px; font-weight: 700;"
            " background: transparent; padding-left: 16px; }"
        )
        idle = QColor(Theme.text)
        for btn in (self.minBtn, self.closeBtn):
            btn.setFixedSize(46, TITLE_H)
            btn.setNormalColor(idle)
            btn.setHoverColor(idle)
            btn.setPressedColor(idle)
            btn.setHoverBackgroundColor(QColor(0, 0, 0, 40) if Theme.dark else QColor(0, 0, 0, 20))
            btn.setPressedBackgroundColor(QColor(0, 0, 0, 70) if Theme.dark else QColor(0, 0, 0, 40))
        self.closeBtn.setHoverColor(QColor(255, 255, 255))
        self.closeBtn.setPressedColor(QColor(255, 255, 255))
        self.closeBtn.setHoverBackgroundColor(QColor(232, 17, 35))
        self.closeBtn.setPressedBackgroundColor(QColor(241, 112, 122))


class PclNavButton(QPushButton):
    def __init__(self, fif, text: str, indent: bool = False, parent=None):
        super().__init__(text, parent)
        self._fif = fif
        self._indent = indent
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32 if indent else 36)
        self.toggled.connect(self._sync_icon)
        self.restyle()

    def restyle(self):
        pad = 40 if self._indent else 14
        fs = "12px" if self._indent else "13px"
        idle = Theme.muted if self._indent else Theme.text
        self.setStyleSheet(
            f"PclNavButton {{ border: none; text-align: left; padding-left: {pad}px;"
            f" color: {idle}; background: transparent; font-size: {fs}; }}"
            f"PclNavButton:hover {{ background: {Theme.hover}; }}"
            f"PclNavButton:checked {{ color: {Theme.green}; background: {Theme.hover}; font-weight: 600; }}"
            f'PclNavButton[sectionOn="true"] {{ color: {Theme.green}; font-weight: 600; }}'
        )
        self._sync_icon(self.isChecked())

    def _sync_icon(self, checked: bool):
        size = 14 if self._indent else 16
        idle = Theme.muted if self._indent else Theme.text
        self.setIcon(_icon(self._fif, Theme.green if checked else idle, size))

    def set_section_on(self, on: bool):
        self.setProperty("sectionOn", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if not self.isCheckable() or not self.isChecked():
            size = 14 if self._indent else 16
            idle = Theme.muted if self._indent else Theme.text
            self.setIcon(_icon(self._fif, Theme.green if on else idle, size))


class PclSideBar(QFrame):
    """左侧导航。item=一级；group=可展开父级，children 为二级。"""

    currentChanged = Signal(str)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setObjectName("pclSide")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(SIDE_W)

        sl = QVBoxLayout(self)
        sl.setContentsMargins(0, 8, 0, 8)
        sl.setSpacing(1)
        self._root = sl

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._groups = {}
        self._last_group_child = {}
        self._headers = []
        self._dividers = []
        self.header_download = None

        first = None
        had_stretch = False
        for spec in items:
            kind = spec[0]
            if kind == "stretch":
                sl.addStretch(1)
                line = QFrame()
                line.setFixedHeight(1)
                self._dividers.append(line)
                sl.addWidget(line)
                had_stretch = True
                continue
            if kind == "header":
                lab = QLabel(spec[1])
                self._headers.append(lab)
                sl.addWidget(lab)
                continue
            if kind == "group":
                self._add_group(spec, sl)
                continue
            btn = self._add_leaf(spec, sl, indent=spec[4] if len(spec) > 4 else False)
            if first is None:
                first = spec[1]
        if not had_stretch:
            sl.addStretch(1)
        self.restyle()
        if first:
            self.set_current(first, emit=False)

    def restyle(self):
        self.setStyleSheet(
            f"#pclSide {{ background: {Theme.card}; border-right: 1px solid {Theme.line}; }}"
        )
        for lab in self._headers:
            lab.setStyleSheet(
                f"color: {Theme.muted}; font-size: 11px; padding: 12px 14px 4px 14px;"
                " background: transparent;")
        for line in self._dividers:
            line.setStyleSheet(f"background: {Theme.line}; border: none;")
        for btn in self._buttons.values():
            btn.restyle()
        for info in self._groups.values():
            info["btn"].restyle()
            info["chevron"].setStyleSheet(
                f"QToolButton {{ border: none; color: {Theme.muted}; font-size: 11px; background: transparent; }}"
            )

    def _add_leaf(self, spec, layout, indent=False):
        key, fif, title = spec[1], spec[2], spec[3]
        btn = PclNavButton(fif, title, indent=indent)
        layout.addWidget(btn)
        self._group.addButton(btn)
        self._buttons[key] = btn
        btn.clicked.connect(lambda _, k=key: self.set_current(k, emit=True))
        return btn

    def _add_group(self, spec, layout):
        gkey, fif, title, children = spec[1], spec[2], spec[3], spec[4]
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        head = QWidget()
        head.setFixedHeight(36)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 4, 0)
        hl.setSpacing(0)
        gbtn = PclNavButton(fif, title, indent=False)
        gbtn.setCheckable(False)
        chevron = QToolButton()
        chevron.setAutoRaise(True)
        chevron.setCursor(Qt.PointingHandCursor)
        chevron.setFixedSize(22, 22)
        hl.addWidget(gbtn, 1)
        hl.addWidget(chevron, 0, Qt.AlignVCenter)

        child_host = QWidget()
        cl = QVBoxLayout(child_host)
        cl.setContentsMargins(0, 0, 0, 4)
        cl.setSpacing(0)
        child_keys = []
        for child in children:
            self._add_leaf(child, cl, indent=True)
            child_keys.append(child[1])

        vl.addWidget(head)
        vl.addWidget(child_host)
        layout.addWidget(wrap)

        gbtn.clicked.connect(lambda: self._on_group_click(gkey))
        chevron.clicked.connect(lambda: self._toggle_group(gkey))

        self._groups[gkey] = {
            "btn": gbtn,
            "chevron": chevron,
            "host": child_host,
            "children": child_keys,
            "expanded": True,
        }
        if gkey == "download":
            self.header_download = gbtn
        self._sync_group(gkey)

    def _toggle_group(self, gkey: str):
        info = self._groups[gkey]
        info["expanded"] = not info["expanded"]
        self._sync_group(gkey)

    def _on_group_click(self, gkey: str):
        info = self._groups[gkey]
        if not info["expanded"]:
            info["expanded"] = True
            self._sync_group(gkey)
        last = self._last_group_child.get(gkey) or (info["children"][0] if info["children"] else None)
        if last:
            self.set_current(last, emit=True)

    def _sync_group(self, gkey: str):
        info = self._groups[gkey]
        info["host"].setVisible(info["expanded"])
        info["chevron"].setText("▾" if info["expanded"] else "▸")
        current_in = any(
            self._buttons[k].isChecked() for k in info["children"] if k in self._buttons
        )
        info["btn"].set_section_on(current_in)

    def set_current(self, key: str, emit: bool = True):
        if key in self._groups and key not in self._buttons:
            self._on_group_click(key)
            return
        btn = self._buttons.get(key)
        if btn is None:
            return
        btn.setChecked(True)
        for gkey, info in self._groups.items():
            if key in info["children"]:
                self._last_group_child[gkey] = key
                if not info["expanded"]:
                    info["expanded"] = True
            self._sync_group(gkey)
        if emit:
            self.currentChanged.emit(key)

    def button(self, key: str):
        if key in self._buttons:
            return self._buttons[key]
        info = self._groups.get(key)
        return info["btn"] if info else None


PclSubButton = PclNavButton


class PclSectionShell(QWidget):
    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setObjectName("pclSectionShell")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#pclSectionShell {{ background: {Theme.bg}; }}")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.stack = QStackedWidget()
        self._pages = {}
        nav_items = []
        for spec in items:
            if spec[0] == "header":
                nav_items.append(spec)
                continue
            _, key, fif, title, page = spec[:5]
            indent = spec[5] if len(spec) > 5 else False
            self._pages[key] = page
            self.stack.addWidget(page)
            nav_items.append(("item", key, fif, title, indent))
        self.side = PclSideBar(nav_items)
        self.side.currentChanged.connect(self.show_key)
        root.addWidget(self.side)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.addWidget(self.stack)
        root.addWidget(body, 1)

    def show_key(self, key: str):
        page = self._pages.get(key)
        if page is None:
            return
        self.side.set_current(key, emit=False)
        self.stack.setCurrentWidget(page)
        if hasattr(page, "reload_installed"):
            page.reload_installed()
        elif hasattr(page, "reload"):
            try:
                page.reload()
            except TypeError:
                pass


def fade_stack_to(stack, widget, holder, duration: int = 180):
    """主栈切页：抓当前帧叠在新页上淡出。holder 必须长期持有动画对象。"""
    from PySide6.QtWidgets import QLabel

    old = stack.currentWidget()
    if widget is None or widget is old:
        return
    if old is None or stack.width() < 8:
        _set_stack(stack, widget)
        return
    pix = old.grab()
    if pix.isNull():
        _set_stack(stack, widget)
        return
    _set_stack(stack, widget)
    cover = QLabel(stack)
    cover.setPixmap(pix)
    cover.setScaledContents(True)
    cover.setGeometry(0, 0, stack.width(), stack.height())
    cover.show()
    cover.raise_()
    effect = QGraphicsOpacityEffect(cover)
    cover.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", cover)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        cover.hide()
        cover.deleteLater()
        if getattr(holder, "_nav_fade", None) is anim:
            holder._nav_fade = None

    prev = getattr(holder, "_nav_cover", None)
    if prev is not None:
        try:
            prev.hide()
            prev.deleteLater()
        except RuntimeError:
            pass
    holder._nav_cover = cover
    holder._nav_fade = anim
    anim.finished.connect(done)
    anim.start()


def _stack_popout(stack, widget) -> bool:
    try:
        stack.setCurrentWidget(widget, popOut=False)
        return True
    except TypeError:
        stack.setCurrentWidget(widget)
        return False


def _set_stack(stack, widget):
    _stack_popout(stack, widget)
