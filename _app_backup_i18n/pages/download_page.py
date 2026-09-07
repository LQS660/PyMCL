# -*- coding: utf-8 -*-
"""下载中心：原版 / Mod / 整合包 / 数据包 / 资源包 / 光影 收在同一页。"""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, Pivot, SubtitleLabel

from ..pcl_chrome import PCL_LINE


class DownloadPage(QWidget):
    def __init__(self, pages: list, parent=None):
        """pages: [(key, title, widget), ...]"""
        super().__init__(parent)
        self.setObjectName("downloadPage")
        self._pages = {}
        self._order = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(SubtitleLabel("下载"))
        head.addWidget(CaptionLabel("原版、模组、整合包、数据包、资源包和光影都在这里"))
        root.addLayout(head)

        self.pivot = Pivot(self)
        bar = QHBoxLayout()
        bar.addWidget(self.pivot)
        bar.addStretch(1)
        root.addLayout(bar)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {PCL_LINE};")
        root.addWidget(line)

        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget(self)
        self.stack.setStyleSheet("background: transparent;")
        root.addWidget(self.stack, 1)

        for key, title, page in pages:
            self._order.append(key)
            self._pages[key] = page
            self.pivot.addItem(key, title)
            self.stack.addWidget(page)

        if self._order:
            self.pivot.setCurrentItem(self._order[0])
            self.stack.setCurrentWidget(self._pages[self._order[0]])
        self.pivot.currentItemChanged.connect(self._on_tab)

    def show_tab(self, key: str):
        if key not in self._pages:
            return
        self.pivot.setCurrentItem(key)
        page = self._pages[key]
        self.stack.setCurrentWidget(page)
        self._reload(page)

    def current_key(self) -> str:
        return self.pivot.currentRouteKey() or (self._order[0] if self._order else "")

    def page(self, key: str):
        return self._pages.get(key)

    def _on_tab(self, key: str):
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self._reload(page)

    @staticmethod
    def _reload(page):
        if hasattr(page, "reload_installed"):
            page.reload_installed()
        elif hasattr(page, "reload"):
            try:
                page.reload()
            except TypeError:
                pass
