# -*- coding: utf-8 -*-
"""内置帮助。"""
from PySide6.QtWidgets import QHBoxLayout, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import ListWidget, SubtitleLabel


class HelpPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("helpPage")
        self.backend = backend
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.addWidget(SubtitleLabel("帮助"))
        body = QHBoxLayout()
        self.list = ListWidget()
        self.list.setFixedWidth(200)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        body.addWidget(self.list)
        body.addWidget(self.text, 1)
        root.addLayout(body, 1)
        for a in backend.help_articles():
            self.list.addItem(a["title"])
        self.list.currentRowChanged.connect(self._show)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _show(self, row: int):
        arts = self.backend.help_articles()
        if 0 <= row < len(arts):
            article = self.backend.help_article(arts[row]["id"])
            self.text.setPlainText(article.get("body") or "")

    def reload(self):
        pass
