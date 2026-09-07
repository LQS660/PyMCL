# -*- coding: utf-8 -*-
"""资源包 / 光影包页：搜索、安装到当前实例的对应目录。"""

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, ComboBox, FluentIcon as FIF, PushButton, ScrollArea, SearchLineEdit,
    SegmentedWidget, SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
    TransparentPushButton, TransparentToolButton,
)

from mclauncher.config import CONFIG
from mclauncher.packs import PACK_RESOURCE, kind_label
from ..widgets import EmptyState, InputDialog, Pill
from .modpack_page import ResultCard


class PackPage(QWidget):
    def __init__(self, backend, kind=PACK_RESOURCE, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.label = kind_label(kind)
        self.setObjectName("resourcepackPage" if kind == PACK_RESOURCE else "shaderPage")
        self.backend = backend

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(SubtitleLabel(self.label))
        folder = "resourcepacks" if kind == PACK_RESOURCE else "shaderpacks"
        self.subtitle = CaptionLabel(f"搜索并安装到当前实例的 {folder}")
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(160)
        self.link_btn = TransparentPushButton(FIF.LINK, "从链接安装")
        self.local_btn = TransparentPushButton(FIF.FOLDER, "导入本地 zip")
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
        self.search.setPlaceholderText(
            f"搜索{self.label}，回车搜索…（空则显示平台热门）")
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
        head2.addWidget(StrongBodyLabel(f"已安装{self.label}"))
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
        folder = "resourcepacks" if self.kind == PACK_RESOURCE else "shaderpacks"
        self.subtitle.setText(f"安装到实例 {self._current_instance()} / {folder}")

    def _source(self) -> str:
        return "Modrinth" if self.source_seg.currentRouteKey() == "modrinth" else "CurseForge"

    def _search(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        results = self.backend.search_packs(
            self.search.text().strip(), self._source(), self.kind)
        if not results:
            self.list_layout.addWidget(EmptyState(FIF.SEARCH, f"没有找到相关{self.label}"))
            return
        for row in results:
            self.list_layout.addWidget(ResultCard(row, self._install))
        self.list_layout.addStretch(1)

    def reload_installed(self):
        self._reload_instances()
        while self.installed_layout.count():
            item = self.installed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        names = self.backend.get_installed_packs(self._current_instance(), self.kind)
        self.count_pill.setText(f"{len(names)} 个")
        if not names:
            self.installed_layout.addWidget(EmptyState(FIF.PHOTO, f"还没有安装{self.label}"))
            return
        for name in names:
            row = QHBoxLayout()
            row.addWidget(CaptionLabel(name), 1)
            btn = TransparentToolButton(FIF.DELETE)
            btn.setToolTip("删除")
            btn.clicked.connect(lambda _, n=name: self._delete(n))
            row.addWidget(btn)
            wrap = QWidget()
            wrap.setLayout(row)
            self.installed_layout.addWidget(wrap)

    def _delete(self, name: str):
        try:
            self.backend.delete_pack(self._current_instance(), self.kind, name)
        except Exception:
            pass
        self.reload_installed()

    def _install(self, item: dict):
        extra = dict(item)
        extra["instance"] = self._current_instance()
        extra["kind"] = self.kind
        extra["source"] = item.get("source") or self._source()
        self.backend.install_pack(
            item.get("name") or item.get("slug") or "",
            self._current_instance(), extra=extra)

    def _install_from_link(self):
        dlg = InputDialog(
            f"从链接安装{self.label}",
            "Modrinth / CurseForge 项目页或 .zip 直链",
            placeholder="https://modrinth.com/…", parent=self)
        if dlg.exec() and dlg.value():
            extra = {"url": dlg.value(), "instance": self._current_instance(), "kind": self.kind}
            self.backend.install_pack(dlg.value(), self._current_instance(), extra=extra)

    def _import_local(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, f"选择{self.label} zip", "", "压缩包 (*.zip)")
        for p in paths:
            extra = {"path": p, "instance": self._current_instance(), "kind": self.kind}
            self.backend.install_pack(p, self._current_instance(), extra=extra)
