# -*- coding: utf-8 -*-
"""游玩时长统计展示页。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF, InfoBar, PushButton, ScrollArea, StrongBodyLabel,
    TransparentPushButton, CaptionLabel,
)

from ..pcl_chrome import Theme
from ..widgets import EmptyState, Pill

_CLOCK_ICON = getattr(FIF, "CLOCK", None) or getattr(FIF, "DATE_TIME", None) or FIF.HELP


class PlaytimePage(QWidget):
    """游玩时长页面。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._instance = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        self.topBar = QFrame()
        self.topBar.setObjectName("topBar")
        self.topBar.setStyleSheet(f"#topBar {{ background: {Theme.card}; border-bottom: 1px solid {Theme.line}; }}")
        self.topBar.setFixedHeight(56)
        tl = QHBoxLayout(self.topBar)
        tl.setContentsMargins(24, 0, 24, 0)
        self._title_lab = StrongBodyLabel("游玩时长")
        self._title_lab.setStyleSheet(f"color: {Theme.text}; font-size: 18px;")
        tl.addWidget(self._title_lab)
        tl.addStretch(1)
        clear_btn = PushButton("清除记录")
        clear_btn.clicked.connect(self._on_clear)
        tl.addWidget(clear_btn)
        root.addWidget(self.topBar)

        # 内容
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(24, 24, 24, 24)
        self._lay.setSpacing(16)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        self.empty = EmptyState(_CLOCK_ICON, "还没有游玩记录\n启动游戏后会自动记录")
        self.empty.hide()
        root.addWidget(self.empty)

    def reload(self, instance: str = ""):
        self._instance = instance or ""
        self._render()

    def restyle(self):
        """主题切换时刷新一次性样式。"""
        self.topBar.setStyleSheet(f"#topBar {{ background: {Theme.card}; border-bottom: 1px solid {Theme.line}; }}")
        self._title_lab.setStyleSheet(f"color: {Theme.text}; font-size: 18px;")
        if hasattr(self.empty, "restyle") and self.empty.isVisible():
            self.empty.restyle()
        self._render()

    def _render(self):
        # 清空
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        try:
            data = self.backend.get_playtime(self._instance) if self._instance else self.backend.get_all_playtime()
        except Exception:
            data = {}
        if not data or (isinstance(data, dict) and "total" in data and data["total"] == 0):
            self._content.hide()
            self.empty.show()
            return
        self._content.show()
        self.empty.hide()

        if isinstance(data, dict) and "total" in data:
            # 单个实例
            self._add_stat(data)
        elif isinstance(data, dict):
            # 所有实例
            for inst_name, inst_data in data.items():
                if isinstance(inst_data, dict) and inst_data.get("total", 0) > 0:
                    self._add_instance_card(inst_name, inst_data)

    def _add_instance_card(self, name: str, data: dict):
        card = QFrame()
        card.setObjectName("ptCard")
        card.setStyleSheet(
            f"#ptCard {{ background: {Theme.card}; border: 1px solid {Theme.line};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        # 标题行
        tl = QHBoxLayout()
        tl.setSpacing(8)
        n = QLabel(name)
        n.setStyleSheet(f"color: {Theme.title}; font-size: 15px; font-weight: 700; background: transparent;")
        tl.addWidget(n)
        total_s = data.get("total", 0)
        total_l = QLabel(self._fmt(total_s))
        total_l.setStyleSheet(f"color: {Theme.text}; font-size: 14px; background: transparent;")
        tl.addWidget(total_l)
        tl.addStretch(1)
        lay.addLayout(tl)
        # 版本列表
        for vid, secs in sorted(data.get("versions", {}).items(), key=lambda x: -x[1]):
            if secs <= 0:
                continue
            rl = QHBoxLayout()
            rl.setSpacing(8)
            v = QLabel(vid)
            v.setStyleSheet(f"color: {Theme.text}; font-size: 12px; background: transparent;")
            rl.addWidget(v)
            pill = Pill(self._fmt(secs))
            rl.addWidget(pill)
            rl.addStretch(1)
            lay.addLayout(rl)
        self._lay.addWidget(card)

    def _add_stat(self, data: dict):
        total = data.get("total", 0)
        versions = data.get("versions", {})
        card = QFrame()
        card.setObjectName("ptCard")
        card.setStyleSheet(
            f"#ptCard {{ background: {Theme.card}; border: 1px solid {Theme.line};"
            " border-radius: 10px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        # 总时长
        tl = QHBoxLayout()
        tl.setSpacing(8)
        n = QLabel("总时长")
        n.setStyleSheet(f"color: {Theme.title}; font-size: 16px; font-weight: 700; background: transparent;")
        tl.addWidget(n)
        v = QLabel(self._fmt(total))
        v.setStyleSheet(f"color: {Theme.text}; font-size: 20px; font-weight: 700; background: transparent;")
        tl.addWidget(v)
        tl.addStretch(1)
        lay.addLayout(tl)
        # 分版本
        for vid, secs in sorted(versions.items(), key=lambda x: -x[1]):
            if secs <= 0:
                continue
            rl = QHBoxLayout()
            rl.setSpacing(8)
            vn = QLabel(vid)
            vn.setStyleSheet(f"color: {Theme.text}; font-size: 12px; background: transparent;")
            rl.addWidget(vn)
            pill = Pill(self._fmt(secs))
            rl.addWidget(pill)
            rl.addStretch(1)
            lay.addLayout(rl)
        self._lay.addWidget(card)

    def _fmt(self, seconds: int) -> str:
        try:
            return self.backend.format_playtime(seconds)
        except Exception:
            s = seconds or 0
            h = s // 3600
            m = (s % 3600) // 60
            if h > 0:
                return f"{h} 小时 {m} 分钟"
            return f"{m} 分钟"

    def _on_clear(self):
        from qfluentwidgets import MessageBox
        box = MessageBox("确认清除", "清除所有游玩时长记录？此操作不可恢复。", self)
        if box.exec():
            try:
                self.backend.clear_playtime(self._instance)
                InfoBar.success("已清除", "", duration=2000, parent=self)
                self.reload(self._instance)
            except Exception as e:
                InfoBar.error("清除失败", str(e), duration=3000, parent=self)