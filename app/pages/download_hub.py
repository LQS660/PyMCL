# -*- coding: utf-8 -*-
"""下载分区：顶部分类横条 + 内容页。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ..pcl_chrome import PCL_GREEN, PCL_HOVER, PCL_LINE, PCL_MUTED, PCL_TEXT


class DownloadCatBar(QFrame):
    currentChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadCatBar")
        self.setFixedHeight(44)
        self.setStyleSheet(
            f"#downloadCatBar {{ background: transparent; border-bottom: 1px solid {PCL_LINE}; }}"
        )
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(20, 0, 20, 0)
        self._layout.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._layout.addStretch(1)

    def add_item(self, title: str, page):
        btn = QPushButton(title)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(44)
        btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {PCL_MUTED};"
            " font-size: 14px; padding: 0 16px; }"
            f"QPushButton:hover {{ color: {PCL_TEXT}; background: {PCL_HOVER}; }}"
            f"QPushButton:checked {{ color: {PCL_GREEN}; font-weight: 700;"
            f" border-bottom: 2px solid {PCL_GREEN}; }}"
        )
        self._group.addButton(btn)
        self._buttons[id(page)] = (btn, page)
        btn.clicked.connect(lambda _, p=page: self.currentChanged.emit(p))
        self._layout.insertWidget(self._layout.count() - 1, btn)
        if not any(b.isChecked() for b in self._group.buttons() if b is not btn):
            if len(self._group.buttons()) == 1:
                btn.setChecked(True)

    def select_page(self, page):
        hit = self._buttons.get(id(page))
        if not hit:
            return
        btn, _ = hit
        btn.setChecked(True)


class DownloadSection(QWidget):
    """侧栏「下载」：分类横条切换子页。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadSection")
        self.backend = backend
        self.hub = self
        self._by_widget = {}

        self.cat = DownloadCatBar()
        self.cat.currentChanged.connect(self.show_page)
        self.stack = QStackedWidget(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.cat)
        root.addWidget(self.stack, 1)

    def add_page(self, page, title: str = ""):
        if page is None or page in self._by_widget:
            return
        self.stack.addWidget(page)
        self._by_widget[page] = title
        if title:
            self.cat.add_item(title, page)
        if self.stack.count() == 1:
            self.stack.setCurrentWidget(page)

    def bind(self, items: list, opener=None):
        del opener
        for spec in items:
            if len(spec) == 2:
                title, page = spec
            else:
                title, page = spec[2], spec[4]
            self.add_page(page, title)

    def has_page(self, page) -> bool:
        return page is self or page in self._by_widget

    def current_page(self):
        return self.stack.currentWidget()

    def show_hub(self):
        pages = list(self._by_widget)
        if pages:
            self.show_page(pages[0])

    def show_page(self, page):
        if page is self:
            self.show_hub()
            return
        if page not in self._by_widget:
            return
        self.stack.setCurrentWidget(page)
        self.cat.select_page(page)
        win = self.window()
        fn = getattr(win, "_reload_page", None)
        if callable(fn):
            fn(page)
