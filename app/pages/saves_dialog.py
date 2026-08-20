# -*- coding: utf-8 -*-
"""存档 / 截图 / 崩溃报告。"""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, ComboBox, ListWidget, MessageBox, MessageBoxBase, PrimaryPushButton,
    PushButton, SubtitleLabel,
)

from mclauncher.utils import format_size


class SavesDialog(MessageBoxBase):
    def __init__(self, backend, instance: str, version: str = "", parent=None):
        super().__init__(parent)
        self.backend = backend
        self.instance = instance
        self.version = version
        self.viewLayout.addWidget(SubtitleLabel(f"存档 · {instance}", self))
        self.kind = ComboBox()
        self.kind.addItems(["存档", "截图", "崩溃报告", "日志"])
        self.list = ListWidget()
        self.list.setMinimumHeight(280)
        self.viewLayout.addWidget(self.kind)
        self.viewLayout.addWidget(self.list)
        row = QHBoxLayout()
        self.open_btn = PushButton("打开")
        self.del_btn = PushButton("删除存档")
        self.dp_btn = PushButton("把数据包装进所选存档")
        row.addWidget(self.open_btn)
        row.addWidget(self.del_btn)
        row.addWidget(self.dp_btn)
        host = QWidget(self)
        host.setLayout(row)
        self.viewLayout.addWidget(host)
        self.yesButton.setText("关闭")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(560)
        self.kind.currentTextChanged.connect(self.reload)
        self.open_btn.clicked.connect(self._open)
        self.del_btn.clicked.connect(self._delete)
        self.dp_btn.clicked.connect(self._datapack)
        self.reload()

    def reload(self):
        self.list.clear()
        kind = self.kind.currentText()
        if kind == "存档":
            rows = self.backend.list_saves(self.instance, self.version)
            for r in rows:
                self.list.addItem(f"{r['name']}  ({format_size(r.get('bytes') or 0)})")
            self.del_btn.setEnabled(True)
            self.dp_btn.setEnabled(True)
            return
        mapk = {"截图": "screenshots", "崩溃报告": "crash-reports", "日志": "logs"}
        rows = self.backend.list_media(self.instance, mapk[kind], self.version)
        for r in rows:
            self.list.addItem(r["name"])
        self.del_btn.setEnabled(False)
        self.dp_btn.setEnabled(False)

    def _selected_name(self) -> str:
        item = self.list.currentItem()
        if not item:
            return ""
        return item.text().split("  (")[0]

    def _open(self):
        name = self._selected_name()
        kind = self.kind.currentText()
        if kind == "存档" and name:
            self.backend.open_save(self.instance, name, self.version)
            return
        mapk = {"截图": "screenshots", "崩溃报告": "crash-reports", "日志": "logs"}
        if kind in mapk:
            rows = self.backend.list_media(self.instance, mapk[kind], self.version)
            for r in rows:
                if r["name"] == name:
                    self.backend.open_media(r["path"])
                    return

    def _delete(self):
        name = self._selected_name()
        if not name:
            return
        box = MessageBox("删除存档", f"确定删除「{name}」？", self)
        if box.exec():
            self.backend.delete_save(self.instance, name, self.version)
            self.reload()

    def _datapack(self):
        name = self._selected_name()
        if not name:
            return
        packs = self.backend.get_installed_datapacks(self.instance) or []
        if not packs:
            MessageBox("没有数据包", "先到下载页安装数据包。", self).exec()
            return
        dlg = MessageBoxBase(self)
        dlg.viewLayout.addWidget(SubtitleLabel("选择数据包", dlg))
        box = ComboBox(dlg)
        box.addItems(packs)
        dlg.viewLayout.addWidget(box)
        dlg.yesButton.setText("安装")
        if dlg.exec():
            self.backend.install_datapack_into_save(self.instance, box.currentText(), name, self.version)
