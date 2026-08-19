# -*- coding: utf-8 -*-
"""版本页：版本卡片网格 + 加载器安装 + 已安装管理。"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF, MessageBox, Pivot,
    PushButton, CheckBox, ScrollArea, SearchLineEdit, SimpleCardWidget,
    StrongBodyLabel, SubtitleLabel, TransparentToolButton,
)

from mclauncher.config import CONFIG
from ..widgets import EmptyState, Pill


class VersionCard(SimpleCardWidget):
    def __init__(self, info: dict, on_install, parent=None):
        super().__init__(parent)
        self.info = info
        self.setFixedSize(216, 132)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(info["version"]), 1)
        vtype = info["type"]
        labels = {"release": "正式版", "snapshot": "快照", "old_alpha": "远古", "old_beta": "远古"}
        colors = {"release": "#2FA36B", "snapshot": "#E8862E", "old_alpha": "#7C5CD6", "old_beta": "#7C5CD6"}
        top.addWidget(Pill(labels.get(vtype, vtype), colors.get(vtype, "#E8862E")))
        layout.addLayout(top)
        layout.addWidget(CaptionLabel(f'发布于 {info["date"]}'))
        layout.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        install_btn = PushButton(FIF.DOWNLOAD, "安装")
        install_btn.setFixedHeight(30)
        install_btn.clicked.connect(lambda: on_install(info, self))
        row.addWidget(install_btn)
        layout.addLayout(row)


class VersionPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("versionPage")
        self.backend = backend
        self._all_versions: list[dict] = []
        self._fetched = False
        self._cols = 0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._refill)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)
        root.addWidget(SubtitleLabel("版本"))

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("搜索版本号…")
        self.search.setFixedWidth(260)
        self.pivot = Pivot(self)
        self.pivot.addItem("all", "全部")
        self.pivot.addItem("release", "正式版")
        self.pivot.addItem("snapshot", "快照")
        self.pivot.setCurrentItem("all")
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(140)
        self.loader_box = ComboBox()
        self.loader_box.addItems(["无", "Fabric", "Forge", "Quilt", "NeoForge"])
        self.loader_box.setFixedWidth(120)
        self.launch_after = CheckBox("完成后启动")
        self.launch_after.setChecked(True)
        bar.addWidget(self.search)
        bar.addWidget(self.pivot)
        bar.addStretch(1)
        bar.addWidget(BodyLabel("实例"))
        bar.addWidget(self.instance_box)
        bar.addWidget(BodyLabel("加载器"))
        bar.addWidget(self.loader_box)
        bar.addWidget(self.launch_after)
        root.addLayout(bar)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(12)
        scroll.setWidget(self.grid_host)
        root.addWidget(scroll, 3)

        installed_card = SimpleCardWidget(self)
        ic_layout = QVBoxLayout(installed_card)
        ic_layout.setContentsMargins(20, 14, 20, 14)
        ic_layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("已安装版本"))
        head.addStretch(1)
        self.uninstall_btn = TransparentToolButton(FIF.DELETE)
        self.uninstall_btn.setToolTip("卸载选中版本")
        head.addWidget(self.uninstall_btn)
        ic_layout.addLayout(head)
        self.installed_area = QVBoxLayout()
        self.installed_area.setSpacing(6)
        ic_layout.addLayout(self.installed_area)
        root.addWidget(installed_card, 1)

        self.search.textChanged.connect(self._refill)
        self.pivot.currentItemChanged.connect(self._refill)
        self.uninstall_btn.clicked.connect(self._uninstall_selected)
        self.instance_box.currentTextChanged.connect(self._reload_installed)

        self.reload()

    def reload(self):
        cur = self.instance_box.currentText()
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        names = [i["name"] for i in self.backend.get_instances()]
        self.instance_box.addItems(names)
        if cur in names:
            self.instance_box.setCurrentText(cur)
        elif CONFIG.get("default_instance") in names:
            self.instance_box.setCurrentText(CONFIG.get("default_instance"))
        self.instance_box.blockSignals(False)
        self._all_versions = self.backend.get_version_list()
        self._refill()
        self._reload_installed()
        if self._fetched:
            return
        self._fetched = True
        self.backend.call_async(
            self.backend.fetch_version_list,
            self._on_versions_fetched,
        )

    def _on_versions_fetched(self, rows):
        self._all_versions = rows or []
        self._refill()

    def reload_installed_only(self):
        cur = self.instance_box.currentText()
        names = [i["name"] for i in self.backend.get_instances()]
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        self.instance_box.addItems(names)
        if cur in names:
            self.instance_box.setCurrentText(cur)
        self.instance_box.blockSignals(False)
        self._reload_installed()

    def _refill(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        text = self.search.text().strip().lower()
        vtype = self.pivot.currentRouteKey()
        rows = [v for v in self._all_versions
                if (not text or text in v["version"].lower())
                and (vtype == "all" or v["type"] == vtype)]

        if not rows:
            self.grid.addWidget(EmptyState(FIF.SEARCH, "没有匹配的版本"), 0, 0)
            self._cols = 1
            return
        cols = max(1, self.width() // 240)
        self._cols = cols
        for i, v in enumerate(rows[:80]):
            self.grid.addWidget(VersionCard(v, self._install), i // cols, i % cols)

    def _reload_installed(self):
        while self.installed_area.count():
            item = self.installed_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        self._installed_checks = []
        instance = self.instance_box.currentText() or "default"
        for v in self.backend.get_installed_versions(instance):
            row = QHBoxLayout()
            cb = CheckBox(v)
            color = "#7C5CD6" if "fabric" in v.lower() else (
                "#E8862E" if "forge" in v.lower() else "#4C8BF5")
            label = "Fabric" if "fabric" in v.lower() else (
                "Forge" if "forge" in v.lower() else (
                    "Quilt" if "quilt" in v.lower() else (
                        "NeoForge" if "neoforge" in v.lower() else "原版")))
            row.addWidget(cb, 1)
            row.addWidget(Pill(label, color))
            self.installed_area.addLayout(row)
            self._installed_checks.append((cb, f"{instance} / {v}"))

    def _install(self, info: dict, source=None):
        loader = self.loader_box.currentText()
        instance = self.instance_box.currentText() or "default"
        win = self.window()
        if source is not None and hasattr(win, "fly_to_tasks"):
            win.fly_to_tasks(source, info["version"], "#2FA36B")
        if loader == "无":
            tid = self.backend.install_game(info["version"], instance=instance)
        else:
            tid = self.backend.install_game(info["version"], loader, instance=instance)
        if self.launch_after.isChecked() and hasattr(win, "queue_launch_after"):
            win.queue_launch_after(tid, instance, info["version"], loader)

    def _uninstall_selected(self):
        selected = [v for rb, v in getattr(self, "_installed_checks", []) if rb.isChecked()]
        if not selected:
            box = MessageBox("未选择", "请先勾选要卸载的版本", self)
            box.exec()
            return
        box = MessageBox("确认卸载", f"将卸载 {len(selected)} 个版本：\n" + "\n".join(selected), self)
        if box.exec():
            for spec in selected:
                try:
                    self.backend.uninstall_version(spec)
                except Exception as e:
                    MessageBox("卸载失败", str(e), self).exec()
            self._reload_installed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._all_versions:
            return
        cols = max(1, self.width() // 240)
        if cols == self._cols:
            return
        self._resize_timer.start(120)
