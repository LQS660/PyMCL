# -*- coding: utf-8 -*-
"""服务器列表管理页。"""
from __future__ import annotations

import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF, InfoBar, MessageBox, PushButton,
    StrongBodyLabel, TransparentPushButton,
)

from ..pcl_chrome import Theme
from ..widgets import InputDialog, EmptyState

_GLOBE_ICON = getattr(FIF, "GLOBE", None) or FIF.WORLD or FIF.CLOUD_DOWNLOAD

_PORT_RE = re.compile(r"^\d{1,5}$")


class ServerPage(QWidget):
    """服务器管理页面。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._instance = ""
        self._servers = []

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
        self._title_lab = StrongBodyLabel("服务器列表")
        self._title_lab.setStyleSheet(f"color: {Theme.text}; font-size: 18px;")
        tl.addWidget(self._title_lab)
        tl.addStretch(1)
        add_btn = PushButton("添加服务器")
        add_btn.setIcon(FIF.ADD)
        add_btn.clicked.connect(self._on_add)
        tl.addWidget(add_btn)
        import_btn = PushButton("导入")
        import_btn.clicked.connect(self._on_import)
        tl.addWidget(import_btn)
        export_btn = PushButton("导出")
        export_btn.clicked.connect(self._on_export)
        tl.addWidget(export_btn)
        root.addWidget(self.topBar)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["名称", "地址", "端口", "描述", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {Theme.card}; border: none; gridline-color: {Theme.line}; }}"
            f"QTableWidget::item {{ padding: 8px 12px; }}"
            f"QHeaderView::section {{ background: {Theme.card}; color: {Theme.muted};"
            " border: none; border-bottom: 1px solid "
            f"{Theme.line}; font-weight: 600; padding: 8px; }}"
        )
        root.addWidget(self.table, 1)

        self.empty = EmptyState(_GLOBE_ICON, "没有可用的服务器\n点击「添加服务器」开始添加")
        self.empty.hide()
        root.addWidget(self.empty)

    def reload(self, instance: str = ""):
        self._instance = instance or ""
        try:
            self._servers = self.backend.list_servers(instance)
        except Exception:
            self._servers = []
        self._render()

    def restyle(self):
        """主题切换时刷新一次性样式。"""
        self.topBar.setStyleSheet(f"#topBar {{ background: {Theme.card}; border-bottom: 1px solid {Theme.line}; }}")
        self._title_lab.setStyleSheet(f"color: {Theme.text}; font-size: 18px;")
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {Theme.card}; border: none; gridline-color: {Theme.line}; }}"
            f"QTableWidget::item {{ padding: 8px 12px; }}"
            f"QHeaderView::section {{ background: {Theme.card}; color: {Theme.muted};"
            " border: none; border-bottom: 1px solid "
            f"{Theme.line}; font-weight: 600; padding: 8px; }}"
        )
        if hasattr(self.empty, "restyle") and self.empty.isVisible():
            self.empty.restyle()

    def _render(self):
        self.table.setRowCount(0)
        if not self._servers:
            self.table.hide()
            self.empty.show()
            return
        self.table.show()
        self.empty.hide()
        self.table.setRowCount(len(self._servers))
        for i, s in enumerate(self._servers):
            self.table.setItem(i, 0, QTableWidgetItem(s.get("name", "?")))
            self.table.setItem(i, 1, QTableWidgetItem(s.get("ip", "")))
            self.table.setItem(i, 2, QTableWidgetItem(str(s.get("port", 25565))))
            desc = (s.get("description", "") or "")[:40]
            self.table.setItem(i, 3, QTableWidgetItem(desc))
            btn_w = QWidget()
            btn_l = QHBoxLayout(btn_w)
            btn_l.setContentsMargins(4, 2, 4, 2)
            edit_b = TransparentPushButton("编辑")
            edit_b.setFixedWidth(40)
            edit_b.clicked.connect(lambda checked, idx=i: self._on_edit(idx))
            del_b = TransparentPushButton("删除")
            del_b.setFixedWidth(40)
            del_b.clicked.connect(lambda checked, idx=i: self._on_delete(idx))
            btn_l.addWidget(edit_b)
            btn_l.addWidget(del_b)
            self.table.setCellWidget(i, 4, btn_w)

    def _on_add(self):
        dlg = InputDialog("添加服务器", "服务器名称", placeholder="可选")
        if not dlg.exec():
            return
        name = dlg.value()
        ip_dlg = InputDialog("添加服务器", "服务器地址", placeholder="example.com 或 IP")
        if not ip_dlg.exec():
            return
        ip = ip_dlg.value()
        port_dlg = InputDialog("添加服务器", "端口", text="25565", placeholder="默认 25565")
        if not port_dlg.exec():
            return
        port_text = port_dlg.value()
        port = int(port_text) if _PORT_RE.match(port_text) else 25565
        try:
            self.backend.add_server(self._instance, name, ip, port)
            InfoBar.success("已添加", f"服务器 {name or ip} 已添加", duration=2000, parent=self)
            self.reload(self._instance)
        except Exception as e:
            InfoBar.error("添加失败", str(e), duration=3000, parent=self)

    def _on_edit(self, index: int):
        s = self._servers[index]
        dlg = InputDialog("编辑服务器", "服务器名称", text=s.get("name", ""))
        if not dlg.exec():
            return
        name = dlg.value()
        ip_dlg = InputDialog("编辑服务器", "服务器地址", text=s.get("ip", ""))
        if not ip_dlg.exec():
            return
        ip = ip_dlg.value()
        try:
            self.backend.update_server(self._instance, index, name=name, ip=ip,
                                       port=s.get("port", 25565))
            InfoBar.success("已更新", f"服务器已更新", duration=2000, parent=self)
            self.reload(self._instance)
        except Exception as e:
            InfoBar.error("更新失败", str(e), duration=3000, parent=self)

    def _on_delete(self, index: int):
        s = self._servers[index]
        box = MessageBox("确认删除", f"删除服务器 {s.get('name', '?')}？", self)
        if box.exec():
            try:
                self.backend.delete_server(self._instance, index)
                InfoBar.success("已删除", "", duration=2000, parent=self)
                self.reload(self._instance)
            except Exception as e:
                InfoBar.error("删除失败", str(e), duration=3000, parent=self)

    def _on_import(self):
        text, ok = QFileDialog.getOpenFileName(self, "选择导入文件", "", "文本文件 (*.txt);;JSON (*.json)")
        if not ok or not text:
            return
        try:
            with open(text, "r", encoding="utf-8") as f:
                data = f.read()
            n = self.backend.import_servers(self._instance, data)
            InfoBar.success("导入完成", f"已导入 {n} 个服务器", duration=2000, parent=self)
            self.reload(self._instance)
        except Exception as e:
            InfoBar.error("导入失败", str(e), duration=3000, parent=self)

    def _on_export(self):
        try:
            text = self.backend.export_servers(self._instance)
        except Exception as e:
            InfoBar.error("导出失败", str(e), duration=3000, parent=self)
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出服务器", "servers.txt", "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            InfoBar.success("已导出", f"已保存到 {path}", duration=2000, parent=self)
        except Exception as e:
            InfoBar.error("导出失败", str(e), duration=3000, parent=self)