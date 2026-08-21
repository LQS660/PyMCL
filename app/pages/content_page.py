# -*- coding: utf-8 -*-
"""光影 / 资源包浏览页（仅 UI）。搜索安装走 BackendAPI，缺方法时空态或占位任务。"""

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, ComboBox, FluentIcon as FIF, ScrollArea, SearchLineEdit,
    SegmentedWidget, SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
    TransparentPushButton, TransparentToolButton,
)

from ..widgets import EmptyState, InputDialog, Pill
from .modpack_page import ResultCard
from mclauncher.i18n import tr

try:
    from mclauncher.config import CONFIG
except ImportError:  # 独立 UI 包没有 mclauncher
    class CONFIG:
        @staticmethod
        def get(key, default=None):
            return default


SHADER_SPEC = {
    "object_name": "shaderPage",
    "title": tr("光影"),
    "subtitle": tr("安装到当前实例 shaderpacks（需 Iris / OptiFine / Oculus）"),
    "search_ph": tr("搜索光影，回车搜索…"),
    "empty_search": tr("没有找到相关光影"),
    "empty_installed": tr("还没有安装光影"),
    "installed_title": tr("已安装光影"),
    "local_label": tr("导入本地 zip"),
    "local_filter": tr("光影包 (*.zip)"),
    "local_dialog": tr("选择光影包"),
    "link_label": tr("从链接安装"),
    "link_title": tr("从链接安装光影"),
    "link_hint": tr("光影包下载链接 (URL)"),
    "link_ph": "https://…/shader.zip",
    "icon": FIF.BRIGHTNESS,
    "search": "search_shaders",
    "install": "install_shader",
    "list_installed": "get_installed_shaders",
    "delete": "delete_shader",
    "task_prefix": tr("安装光影"),
}

RESOURCE_SPEC = {
    "object_name": "resourcePackPage",
    "title": tr("资源包"),
    "subtitle": tr("安装到当前实例 resourcepacks"),
    "search_ph": tr("搜索资源包，回车搜索…"),
    "empty_search": tr("没有找到相关资源包"),
    "empty_installed": tr("还没有安装资源包"),
    "installed_title": tr("已安装资源包"),
    "local_label": tr("导入本地 zip"),
    "local_filter": tr("资源包 (*.zip)"),
    "local_dialog": tr("选择资源包"),
    "link_label": tr("从链接安装"),
    "link_title": tr("从链接安装资源包"),
    "link_hint": tr("资源包下载链接 (URL)"),
    "link_ph": "https://…/pack.zip",
    "icon": FIF.PHOTO,
    "search": "search_resourcepacks",
    "install": "install_resourcepack",
    "list_installed": "get_installed_resourcepacks",
    "delete": "delete_resourcepack",
    "task_prefix": tr("安装资源包"),
}


class PackBrowsePage(QWidget):
    def __init__(self, backend, spec: dict, parent=None):
        super().__init__(parent)
        self.setObjectName(spec["object_name"])
        self.backend = backend
        self.spec = spec

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(SubtitleLabel(spec["title"]))
        self.subtitle = CaptionLabel(spec["subtitle"])
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(160)
        self.link_btn = TransparentPushButton(FIF.LINK, spec["link_label"])
        self.local_btn = TransparentPushButton(FIF.FOLDER, spec["local_label"])
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
        self.search.setPlaceholderText(spec["search_ph"])
        bar.addWidget(self.source_seg)
        bar.addWidget(self.search, 1)
        root.addLayout(bar)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        left_card = SimpleCardWidget(self)
        left = QVBoxLayout(left_card)
        left.setContentsMargins(16, 14, 16, 14)
        left.setSpacing(10)
        left.addWidget(StrongBodyLabel(tr("搜索结果（点击安装）")))
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
        head2.addWidget(StrongBodyLabel(spec["installed_title"]))
        head2.addStretch(1)
        self.count_pill = Pill(tr("0 个"), "#4C8BF5")
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
        return self.instance_box.currentText() or CONFIG.get("default_instance", "default") or "default"

    def _reload_instances(self):
        cur = self.instance_box.currentText()
        getter = getattr(self.backend, "get_instances", None)
        names = [i["name"] for i in getter()] if callable(getter) else ["default"]
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        self.instance_box.addItems(names)
        if cur in names:
            self.instance_box.setCurrentText(cur)
        elif CONFIG.get("default_instance") in names:
            self.instance_box.setCurrentText(CONFIG.get("default_instance"))
        self.instance_box.blockSignals(False)
        self.subtitle.setText(f"{self.spec['subtitle']} · {self._current_instance()}")

    def _source(self) -> str:
        return "Modrinth" if self.source_seg.currentRouteKey() == "modrinth" else "CurseForge"

    def _search(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        fn = getattr(self.backend, self.spec["search"], None)
        results = fn(self.search.text().strip(), self._source()) if callable(fn) else []
        if not results:
            self.list_layout.addWidget(EmptyState(FIF.SEARCH, self.spec["empty_search"]))
            return
        for row in results:
            self._add_result_card(row)
        self.list_layout.addStretch(1)

    def _add_result_card(self, item: dict):
        try:
            card = ResultCard(item, self._install)
        except TypeError:
            card = ResultCard(
                item.get("name") or "?",
                item.get("author") or "?",
                int(item.get("downloads") or 0),
                lambda name, tile=None, row=item: self._install(row, tile),
            )
        self.list_layout.addWidget(card)

    def reload_installed(self):
        self._reload_instances()
        while self.installed_layout.count():
            item = self.installed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        getter = getattr(self.backend, self.spec["list_installed"], None)
        rows = getter(self._current_instance()) if callable(getter) else []
        self.count_pill.setText(f"{len(rows)} 个")
        if not rows:
            self.installed_layout.addWidget(EmptyState(self.spec["icon"], self.spec["empty_installed"]))
            return
        for name in rows:
            row = QHBoxLayout()
            row.addWidget(CaptionLabel(name), 1)
            btn = TransparentToolButton(FIF.DELETE)
            btn.setToolTip(tr("删除"))
            btn.clicked.connect(lambda _, n=name: self._delete(n))
            row.addWidget(btn)
            wrap = QWidget()
            wrap.setLayout(row)
            self.installed_layout.addWidget(wrap)

    def _delete(self, name: str):
        fn = getattr(self.backend, self.spec["delete"], None)
        if callable(fn):
            try:
                fn(self._current_instance(), name)
            except Exception:
                pass
        self.reload_installed()

    def _install(self, item, tile=None):
        if isinstance(item, str):
            item = {"name": item}
        name = item.get("name") or ""
        win = self.window()
        if tile is not None and hasattr(win, "fly_to_tasks"):
            win.fly_to_tasks(tile, name)
        fn = getattr(self.backend, self.spec["install"], None)
        extra = dict(item)
        extra["instance"] = self._current_instance()
        extra["source"] = self._source()
        if callable(fn):
            try:
                fn(name, self._current_instance(), extra=extra)
            except TypeError:
                fn(name, self._current_instance())
            return
        self._placeholder_task(name)

    def _placeholder_task(self, name: str):
        start = getattr(self.backend, "start_task", None)
        if not callable(start):
            return
        title = f"{self.spec['task_prefix']} {name}".strip()

        def _pending(progress, log, *_a, **_k):
            log(tr("待后端对接"))
            progress(1, 1, tr("待对接"))

        start(title, _pending)

    def _install_from_link(self):
        dlg = InputDialog(self.spec["link_title"], self.spec["link_hint"],
                          placeholder=self.spec["link_ph"], parent=self)
        if dlg.exec() and dlg.value():
            url = dlg.value()
            extra = {"name": url, "url": url, "instance": self._current_instance(),
                     "source": self._source()}
            self._install(extra, self.link_btn)

    def _import_local(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.spec["local_dialog"], "", self.spec["local_filter"])
        for p in paths:
            extra = {"name": p, "path": p, "instance": self._current_instance()}
            self._install(extra, self.local_btn)


class ShaderPage(PackBrowsePage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, SHADER_SPEC, parent)


class ResourcePackPage(PackBrowsePage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, RESOURCE_SPEC, parent)
