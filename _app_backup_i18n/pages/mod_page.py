# -*- coding: utf-8 -*-
"""模组页：搜索卡片列表 + 已安装模组管理。"""

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, ComboBox, FluentIcon as FIF, MessageBox, PushButton, ScrollArea,
    SearchLineEdit, SegmentedWidget, SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
    TransparentPushButton, TransparentToolButton,
)

from mclauncher.config import CONFIG
from ..widgets import EmptyState, InputDialog, Pill
from .modpack_page import ResultCard


class ModPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("modPage")
        self.backend = backend

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(SubtitleLabel("模组"))
        self.subtitle = CaptionLabel("为当前实例增添玩法")
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(160)
        self.link_btn = TransparentPushButton(FIF.LINK, "从链接安装")
        self.local_btn = TransparentPushButton(FIF.FOLDER, "导入本地 jar")
        head.addWidget(self.instance_box, 0)
        head.addWidget(self.link_btn, 0)
        head.addWidget(self.local_btn, 0)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.source_seg = SegmentedWidget(self)
        self.source_seg.addItem("modrinth", "Modrinth")
        self.source_seg.addItem("curseforge", "CurseForge")
        self.source_seg.setCurrentItem("modrinth")
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("搜索模组，回车搜索…")
        bar.addWidget(self.source_seg)
        bar.addWidget(self.search, 1)
        root.addLayout(bar)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        left_card = SimpleCardWidget(self)
        left = QVBoxLayout(left_card)
        left.setContentsMargins(16, 14, 16, 14)
        left.setSpacing(10)
        left.addWidget(StrongBodyLabel("搜索结果（点击安装）"))
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        scroll.setWidget(host)
        left.addWidget(scroll, 1)
        columns.addWidget(left_card, 3)

        right_card = SimpleCardWidget(self)
        right = QVBoxLayout(right_card)
        right.setContentsMargins(16, 14, 16, 14)
        right.setSpacing(10)
        head2 = QHBoxLayout()
        head2.addWidget(StrongBodyLabel("已安装模组"))
        head2.addStretch(1)
        self.count_pill = Pill("0 个", "#4C8BF5")
        head2.addWidget(self.count_pill)
        right.addLayout(head2)
        self.installed_layout = QVBoxLayout()
        self.installed_layout.setSpacing(6)
        right.addLayout(self.installed_layout)
        right.addStretch(1)
        right_card.setMinimumWidth(240)
        columns.addWidget(right_card, 2)
        root.addLayout(columns, 1)

        self.search.returnPressed.connect(self._search)
        self.source_seg.currentItemChanged.connect(self._search)
        self.link_btn.clicked.connect(self._install_from_link)
        self.local_btn.clicked.connect(self._import_local)
        self.instance_box.currentTextChanged.connect(self.reload_installed)

        self._reload_instances()
        self._search()
        self.reload_installed()

    def _current_instance(self) -> str:
        return self.instance_box.currentText() or CONFIG.get("default_instance", "default")

    def _reload_instances(self):
        cur = self.instance_box.currentText()
        names = [i["name"] for i in self.backend.get_instances()]
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        self.instance_box.addItems(names)
        if cur in names:
            self.instance_box.setCurrentText(cur)
        elif CONFIG.get("default_instance") in names:
            self.instance_box.setCurrentText(CONFIG.get("default_instance"))
        self.instance_box.blockSignals(False)
        self.subtitle.setText(f"为当前实例增添玩法 · {self._current_instance()}")

    def _source(self) -> str:
        return "Modrinth" if self.source_seg.currentRouteKey() == "modrinth" else "CurseForge"

    def _search(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search.text().strip()
        source = self._source()
        if not query:
            self._render_mods(self.backend.search_mods("", source))
            return
        self.list_layout.addWidget(EmptyState(FIF.SEARCH, "搜索中…"))
        self.backend.call_async(
            lambda: self.backend.search_mods(query, source),
            self._render_mods,
            lambda _err: self._render_mods([]),
        )

    def _render_mods(self, results):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not results:
            self.list_layout.addWidget(EmptyState(FIF.SEARCH, "没有找到相关模组"))
            return
        for m in results:
            self.list_layout.addWidget(ResultCard(m, self._install))
        self.list_layout.addStretch(1)

    def reload_installed(self):
        self._reload_instances()
        while self.installed_layout.count():
            item = self.installed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        mods = self.backend.get_installed_mods(self._current_instance())
        self.count_pill.setText(f"{len(mods)} 个")
        if not mods:
            self.installed_layout.addWidget(EmptyState(FIF.TAG, "还没有安装模组"))
            return
        for name in mods:
            row = QHBoxLayout()
            row.addWidget(CaptionLabel(name), 1)
            btn = TransparentToolButton(FIF.DELETE)
            btn.setToolTip("删除")
            btn.clicked.connect(lambda _, n=name: self._delete_mod(n))
            row.addWidget(btn)
            wrap = QWidget()
            wrap.setLayout(row)
            self.installed_layout.addWidget(wrap)

    def _delete_mod(self, name: str):
        try:
            self.backend.delete_mod(self._current_instance(), name)
        except Exception as e:
            MessageBox("删除失败", str(e), self).exec()
        self.reload_installed()

    def _install(self, item: dict):
        extra = dict(item)
        extra["instance"] = self._current_instance()
        extra["source"] = self._source()
        self.backend.install_mod(item.get("name") or "", self._current_instance(), extra=extra)

    def _install_from_link(self):
        dlg = InputDialog("从链接安装", "模组下载链接 (URL)",
                          placeholder="https://…/mod.jar", parent=self)
        if dlg.exec() and dlg.value():
            url = dlg.value()
            extra = {"url": url, "instance": self._current_instance()}
            self.backend.install_mod(url, self._current_instance(), extra=extra)

    def _import_local(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择模组 jar", "", "模组 (*.jar)")
        for p in paths:
            extra = {"path": p, "instance": self._current_instance()}
            self.backend.install_mod(p, self._current_instance(), extra=extra)
