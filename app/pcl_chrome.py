# -*- coding: utf-8 -*-
"""PCL 风格色板：细顶栏 + 左侧主导航。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)
from qframelesswindow import TitleBar

PCL_GREEN = "#2E9B6B"
PCL_GREEN_DEEP = "#1E7A52"
PCL_BLUE = PCL_GREEN
PCL_BLUE_DEEP = PCL_GREEN_DEEP
PCL_BG = "#FFFFFF"
PCL_CARD = "#FFFFFF"
PCL_LINE = "#E6E6E6"
PCL_TEXT = "#2B2B2B"
PCL_MUTED = "#888888"
PCL_TITLE = "#1B7A54"
PCL_HOVER = "#F3F7F5"
TITLE_H = 40
SIDE_W = 188


def _icon(fif, color: str, size: int = 18):
    return fif.icon(color=QColor(color)).pixmap(size, size)


class PclTitleBar(TitleBar):
    """仅品牌 + 窗口按钮，不含主导航。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(TITLE_H)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"PclTitleBar {{ background-color: {PCL_BG}; border-bottom: 1px solid {PCL_LINE}; }}"
            f"QLabel#pclBrand {{ color: {PCL_TEXT}; font-size: 16px; font-weight: 700;"
            " background: transparent; padding-left: 16px; }"
        )

        self.maxBtn.hide()
        for btn in (self.minBtn, self.closeBtn):
            btn.setFixedSize(46, TITLE_H)
            btn.setNormalColor(QColor(43, 43, 43))
            btn.setHoverColor(QColor(43, 43, 43))
            btn.setPressedColor(QColor(43, 43, 43))
            btn.setHoverBackgroundColor(QColor(0, 0, 0, 20))
            btn.setPressedBackgroundColor(QColor(0, 0, 0, 40))
        self.closeBtn.setHoverColor(QColor(255, 255, 255))
        self.closeBtn.setPressedColor(QColor(255, 255, 255))
        self.closeBtn.setHoverBackgroundColor(QColor(232, 17, 35))
        self.closeBtn.setPressedBackgroundColor(QColor(241, 112, 122))

        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)
        brand = QLabel("PyMCL")
        brand.setObjectName("pclBrand")
        self.hBoxLayout.insertWidget(0, brand, 0, Qt.AlignVCenter)


class PclNavButton(QPushButton):
    def __init__(self, fif, text: str, indent: bool = False, parent=None):
        super().__init__(text, parent)
        self._fif = fif
        self._indent = indent
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32 if indent else 36)
        pad = 40 if indent else 14
        size = 14 if indent else 16
        self.setIcon(_icon(fif, PCL_MUTED if indent else PCL_TEXT, size))
        fs = "12px" if indent else "13px"
        self.setStyleSheet(
            f"PclNavButton {{ border: none; text-align: left; padding-left: {pad}px;"
            f" color: {PCL_MUTED if indent else PCL_TEXT}; background: transparent; font-size: {fs}; }}"
            "PclNavButton:hover { background: rgba(46,155,107,18); }"
            f"PclNavButton:checked {{ color: {PCL_GREEN}; background: {PCL_HOVER}; font-weight: 600; }}"
            f'PclNavButton[sectionOn="true"] {{ color: {PCL_GREEN}; font-weight: 600; }}'
        )
        self.toggled.connect(self._sync_icon)

    def _sync_icon(self, checked: bool):
        size = 14 if self._indent else 16
        idle = PCL_MUTED if self._indent else PCL_TEXT
        self.setIcon(_icon(self._fif, PCL_GREEN if checked else idle, size))

    def set_section_on(self, on: bool):
        self.setProperty("sectionOn", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if not self.isCheckable() or not self.isChecked():
            size = 14 if self._indent else 16
            idle = PCL_MUTED if self._indent else PCL_TEXT
            self.setIcon(_icon(self._fif, PCL_GREEN if on else idle, size))


class PclSideBar(QFrame):
    """左侧导航。item=一级；group=可展开父级，children 为二级。"""

    currentChanged = Signal(str)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setObjectName("pclSide")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(SIDE_W)
        self.setStyleSheet(
            f"#pclSide {{ background: {PCL_CARD}; border-right: 1px solid {PCL_LINE}; }}"
        )

        sl = QVBoxLayout(self)
        sl.setContentsMargins(0, 8, 0, 8)
        sl.setSpacing(1)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._groups = {}
        self._last_group_child = {}
        self.header_download = None

        first = None
        had_stretch = False
        for spec in items:
            kind = spec[0]
            if kind == "stretch":
                sl.addStretch(1)
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background: {PCL_LINE}; border: none;")
                sl.addWidget(line)
                had_stretch = True
                continue
            if kind == "header":
                lab = QLabel(spec[1])
                lab.setStyleSheet(
                    f"color: {PCL_MUTED}; font-size: 11px; padding: 12px 14px 4px 14px;"
                    " background: transparent;")
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
        if first:
            self.set_current(first, emit=False)

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
        chevron.setStyleSheet(
            "QToolButton { border: none; color: #888888; font-size: 11px; background: transparent; }"
        )
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


# 兼容旧引用：分区壳仍可用于嵌套页
PclSubButton = PclNavButton


class PclSectionShell(QWidget):
    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setObjectName("pclSectionShell")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#pclSectionShell {{ background: {PCL_BG}; }}")
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
