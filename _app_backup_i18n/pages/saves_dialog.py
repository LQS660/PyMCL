# -*- coding: utf-8 -*-
"""存档 / 截图 / 崩溃报告 / 日志 — 带缩略图预览。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBox, ListWidget, MessageBox, MessageBoxBase, PushButton, SubtitleLabel,
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
        self.kind.addItems(["存档", "备份", "截图", "崩溃报告", "日志"])
        self.list = ListWidget()
        self.list.setMinimumHeight(280)
        self.list.setIconSize(QSize(48, 48))
        self.list.setSpacing(4)
        self.viewLayout.addWidget(self.kind)
        self.viewLayout.addWidget(self.list)
        host = QWidget(self)
        rows = QVBoxLayout(host)
        rows.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.open_btn = PushButton("打开")
        self.del_btn = PushButton("删除存档")
        self.dp_btn = PushButton("把数据包装进所选存档")
        row.addWidget(self.open_btn)
        row.addWidget(self.del_btn)
        row.addWidget(self.dp_btn)
        row2 = QHBoxLayout()
        self.backup_btn = PushButton("备份存档")
        self.restore_btn = PushButton("还原备份")
        self.export_btn = PushButton("导出为 zip")
        row2.addWidget(self.backup_btn)
        row2.addWidget(self.restore_btn)
        row2.addWidget(self.export_btn)
        rows.addLayout(row)
        rows.addLayout(row2)
        self.viewLayout.addWidget(host)
        self.yesButton.setText("关闭")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(640)
        self.kind.currentTextChanged.connect(self.reload)
        self.open_btn.clicked.connect(self._open)
        self.del_btn.clicked.connect(self._delete)
        self.dp_btn.clicked.connect(self._datapack)
        self.backup_btn.clicked.connect(self._backup)
        self.restore_btn.clicked.connect(self._restore)
        self.export_btn.clicked.connect(self._export)
        self.reload()

    def _set_actions(self, kind: str):
        is_save = kind == "存档"
        is_backup = kind == "备份"
        self.del_btn.setEnabled(is_save or is_backup)
        self.del_btn.setText("删除备份" if is_backup else "删除存档")
        self.dp_btn.setEnabled(is_save)
        self.backup_btn.setEnabled(is_save)
        self.export_btn.setEnabled(is_save)
        self.restore_btn.setEnabled(is_backup)

    def reload(self):
        self.list.clear()
        kind = self.kind.currentText()
        self._set_actions(kind)
        if kind == "备份":
            for r in self.backend.list_save_backups(self.instance, "", self.version):
                self.list.addItem(f"{r['name']}  ({format_size(r.get('bytes') or 0)})")
            return
        if kind == "存档":
            rows = self.backend.list_saves(self.instance, self.version)
            for r in rows:
                icon_path = r.get("icon", "")
                pix = None
                if icon_path:
                    try:
                        pix = QPixmap(icon_path)
                        if pix.isNull():
                            pix = None
                        else:
                            pix = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    except Exception:
                        pix = None
                item = QListWidgetItem(f"{r['name']}  ({format_size(r.get('bytes') or 0)})")
                if pix:
                    item.setIcon(QIcon(pix))
                self.list.addItem(item)
            return
        mapk = {"截图": "screenshots", "崩溃报告": "crash-reports", "日志": "logs"}
        rows = self.backend.list_media(self.instance, mapk[kind], self.version)
        for r in rows:
            path = r.get("path", "")
            if kind == "截图" and path:
                try:
                    pix = QPixmap(path)
                    if not pix.isNull():
                        thumb = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        item = QListWidgetItem(r["name"])
                        item.setIcon(QIcon(thumb))
                        self.list.addItem(item)
                        continue
                except Exception:
                    pass
            self.list.addItem(r["name"])

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
        if self.kind.currentText() == "备份":
            if MessageBox("删除备份", f"确定删除备份「{name}」？", self).exec():
                self.backend.delete_save_backup(self.instance, name, self.version)
                self.reload()
            return
        box = MessageBox("删除存档", f"确定删除「{name}」？", self)
        if box.exec():
            self.backend.delete_save(self.instance, name, self.version)
            self.reload()

    def _backup(self):
        name = self._selected_name()
        if not name:
            MessageBox("未选择", "请先在列表里选一个存档。", self).exec()
            return
        try:
            self.backend.backup_save(self.instance, name, self.version)
        except Exception as e:
            MessageBox("备份失败", str(e), self).exec()
            return
        MessageBox("已开始备份", f"「{name}」正在打包，可到下载任务页看进度。", self).exec()

    def _restore(self):
        name = self._selected_name()
        if not name:
            return
        box = MessageBox(
            "还原备份",
            f"从「{name}」还原存档？\n若同名存档已存在，会另存为「原名-还原」，不会覆盖。",
            self,
        )
        if not box.exec():
            return
        try:
            out = self.backend.restore_save_backup(self.instance, name, self.version)
        except Exception as e:
            MessageBox("还原失败", str(e), self).exec()
            return
        MessageBox("还原完成", f"已还原为存档「{out.get('name')}」。", self).exec()
        self.kind.setCurrentText("存档")

    def _export(self):
        name = self._selected_name()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出存档", f"{name}.zip", "压缩包 (*.zip)")
        if not path:
            return
        try:
            out = self.backend.export_save(self.instance, name, path, self.version)
        except Exception as e:
            MessageBox("导出失败", str(e), self).exec()
            return
        MessageBox("导出完成", f"已导出到：\n{out}", self).exec()

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