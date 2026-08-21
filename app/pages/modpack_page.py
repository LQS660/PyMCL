# -*- coding: utf-8 -*-
"""整合包页：大搜索框 + 结果卡片列表。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF, PushButton, ScrollArea,
    SearchLineEdit, SegmentedWidget, SimpleCardWidget, StrongBodyLabel,
    SubtitleLabel, TransparentPushButton,
)

from mclauncher.config import CONFIG
from ..widgets import EmptyState, IconTile
from mclauncher.i18n import tr


class ResultCard(SimpleCardWidget):
    def __init__(self, item: dict, on_install, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        name = item.get("name") or "?"
        author = item.get("author") or "?"
        downloads = int(item.get("downloads") or 0)

        src = (item.get("source") or "").lower()
        src_label = "CurseForge" if src.startswith("curse") else "Modrinth"
        desc = (item.get("description") or "").strip()
        caption = f"{src_label} · by {author}"
        if desc:
            caption = f"{caption} · {desc[:48]}"

        layout.addWidget(IconTile(name, size=46))
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(StrongBodyLabel(name))
        info.addWidget(CaptionLabel(caption))
        layout.addLayout(info, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        dl = BodyLabel(f"{downloads:,}" if downloads else tr("热门"))
        dl.setAlignment(Qt.AlignRight)
        cap = CaptionLabel(tr("下载量"))
        cap.setAlignment(Qt.AlignRight)
        right.addWidget(dl)
        right.addWidget(cap)
        layout.addLayout(right)

        install_btn = PushButton(FIF.DOWNLOAD, tr("安装"))
        install_btn.setFixedSize(96, 32)
        install_btn.clicked.connect(lambda: on_install(item))
        layout.addWidget(install_btn)


class ModpackPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("modpackPage")
        self.backend = backend

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        root_title = QVBoxLayout()
        root_title.addWidget(SubtitleLabel(tr("整合包")))
        root_title.addWidget(CaptionLabel(tr("一键安装别人调配好的世界")))
        head.addLayout(root_title, 1)
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(160)
        self.local_btn = TransparentPushButton(FIF.FOLDER, tr("从本地文件安装 (.mrpack/.zip)"))
        head.addWidget(self.instance_box, 0, Qt.AlignBottom)
        head.addWidget(self.local_btn, 0, Qt.AlignBottom)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.source_seg = SegmentedWidget(self)
        self.source_seg.addItem("modrinth", "Modrinth")
        self.source_seg.addItem("curseforge", "CurseForge")
        self.source_seg.setCurrentItem("curseforge")
        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("搜索整合包，回车搜索…（机械动力 = 黄铜协奏曲 CBC 1.20.1）"))
        bar.addWidget(self.source_seg)
        bar.addWidget(self.search, 1)
        root.addLayout(bar)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(10)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        self.search.returnPressed.connect(self._search)
        self.source_seg.currentItemChanged.connect(self._search)
        self.local_btn.clicked.connect(self._install_local)

        self._reload_instances()
        self._search()

    def _reload_instances(self):
        cur = self.instance_box.currentText()
        names = [i["name"] for i in self.backend.get_instances()]
        self.instance_box.clear()
        self.instance_box.addItems(names)
        if cur in names:
            self.instance_box.setCurrentText(cur)
        elif CONFIG.get("default_instance") in names:
            self.instance_box.setCurrentText(CONFIG.get("default_instance"))

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
            self._render_packs(self.backend.search_modpacks("", source))
            return
        self.list_layout.addWidget(EmptyState(FIF.SEARCH, tr("搜索中…")))
        self.backend.call_async(
            lambda: self.backend.search_modpacks(query, source),
            self._render_packs,
            lambda _err: self._render_packs([]),
        )

    def _render_packs(self, results):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not results:
            self.list_layout.addWidget(EmptyState(FIF.SEARCH, tr("没有找到相关整合包")))
            return
        for p in results:
            self.list_layout.addWidget(ResultCard(p, self._install))
        self.list_layout.addStretch(1)

    def _install(self, item: dict):
        extra = dict(item)
        extra["instance"] = self.instance_box.currentText() or "default"
        # 必须用这条结果自己的来源，不能用当前页签；否则 CDC 会在 Modrinth 页被装成 Create+
        src = item.get("source") or self._source()
        self.backend.install_modpack(item.get("name") or "", src, extra=extra)

    def _install_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择整合包文件"), "", tr("整合包 (*.mrpack *.zip)"))
        if path:
            extra = {"path": path, "instance": self.instance_box.currentText() or "default"}
            self.backend.install_modpack(path, tr("本地文件"), extra=extra)
