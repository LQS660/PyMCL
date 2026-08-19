# -*- coding: utf-8 -*-
"""PCL 同款搜索页：名称/来源/版本/类型 + 结果列表。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBox, EditableComboBox, FluentIcon as FIF, LineEdit, PushButton,
    ScrollArea, TransparentPushButton,
)

from ..pcl_chrome import PCL_BLUE, PCL_CARD, PCL_HOVER, PCL_LINE, PCL_MUTED, PCL_TITLE, _icon
from ..widgets import EmptyState, IconTile, InputDialog

try:
    from mclauncher.config import CONFIG
except ImportError:
    class CONFIG:
        @staticmethod
        def get(key, default=None):
            return default


def fmt_downloads(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    if n >= 100_000_000:
        s = f" {n / 100_000_000:.1f}亿"
        return s.replace(".0", "").strip()
    if n >= 10_000:
        return f"{n / 10_000:.0f}万"
    return str(n) if n else "—"


class PclCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pclCard")
        self.setStyleSheet(
            f"#pclCard {{ background: {PCL_CARD}; border: 1px solid {PCL_LINE};"
            " border-radius: 10px; }"
        )


def _src_label(src) -> str:
    s = str(src or "").lower()
    if s.startswith("curse"):
        return "CurseForge"
    if s.startswith("modrinth") or s == "modrinth":
        return "Modrinth"
    if not src:
        return "—"
    return str(src)


def _meta_chip(fif, text: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(3)
    icon = QLabel()
    icon.setPixmap(_icon(fif, PCL_MUTED, 12))
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {PCL_MUTED}; font-size: 11px; background: transparent;")
    h.addWidget(icon)
    h.addWidget(lab)
    return w


class PclResultRow(QFrame):
    def __init__(self, item: dict, on_install, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("pclRow")
        self.setStyleSheet(
            "#pclRow { background: transparent; border-bottom: 1px solid #EEF3F7; }"
            "#pclRow:hover { background: #F5FBFF; }"
        )
        self.setFixedHeight(88)
        name = item.get("name") or "?"
        desc = (item.get("description") or item.get("summary") or "").strip()
        tags = item.get("tags") or []
        ver = item.get("game_version") or item.get("version") or "—"
        updated = item.get("updated") or item.get("date") or "—"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(IconTile(name, size=52))

        info = QVBoxLayout()
        info.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel(name)
        title.setStyleSheet(
            f"color: {PCL_TITLE}; font-size: 14px; font-weight: 700; background: transparent;")
        title_row.addWidget(title)
        for tag in tags[:4]:
            chip = QLabel(str(tag))
            chip.setStyleSheet(
                f"color: {PCL_MUTED}; background: #F0F4F8; border-radius: 3px;"
                " padding: 1px 6px; font-size: 11px;")
            title_row.addWidget(chip)
        title_row.addStretch(1)
        info.addLayout(title_row)
        if desc:
            d = QLabel(desc[:90])
            d.setStyleSheet(f"color: {PCL_MUTED}; font-size: 12px; background: transparent;")
            info.addWidget(d)
        meta = QHBoxLayout()
        meta.setSpacing(14)
        meta.addWidget(_meta_chip(FIF.GAME, str(ver)))
        meta.addWidget(_meta_chip(FIF.DOWNLOAD, fmt_downloads(item.get("downloads"))))
        meta.addWidget(_meta_chip(FIF.UP, str(updated)))
        meta.addWidget(_meta_chip(FIF.GLOBE, _src_label(item.get("source"))))
        meta.addStretch(1)
        info.addLayout(meta)
        layout.addLayout(info, 1)

        btn = PushButton("安装")
        btn.setFixedSize(72, 30)
        btn.setStyleSheet(
            f"PushButton {{ border: 1px solid {PCL_BLUE}; color: {PCL_BLUE};"
            " background: white; border-radius: 4px; }"
            "PushButton:hover { background: " + PCL_HOVER + "; }"
        )
        btn.clicked.connect(lambda: on_install(item, btn))
        layout.addWidget(btn)


MOD_SPEC = {
    "object_name": "modPage",
    "search_title": "搜索 Mod",
    "empty_search": "没有找到相关模组",
    "empty_installed": "还没有安装模组",
    "installed_title": "已安装",
    "local_label": "导入 jar",
    "local_filter": "模组 (*.jar)",
    "local_dialog": "选择模组",
    "link_label": "从链接安装",
    "link_title": "从链接安装模组",
    "link_hint": "模组下载链接 (URL)",
    "link_ph": "https://…/mod.jar",
    "icon": FIF.TAG,
    "search": "search_mods",
    "install": "install_mod",
    "list_installed": "get_installed_mods",
    "delete": "delete_mod",
    "task_prefix": "安装模组",
    "types": ["全部", "优化", "科技", "魔法", "冒险"],
}

MODPACK_SPEC = {
    "object_name": "modpackPage",
    "search_title": "搜索整合包",
    "empty_search": "没有找到相关整合包",
    "empty_installed": "还没有安装整合包",
    "installed_title": "已安装",
    "local_label": "导入文件",
    "local_filter": "整合包 (*.mrpack *.zip)",
    "local_dialog": "选择整合包",
    "link_label": "从链接安装",
    "link_title": "从链接安装整合包",
    "link_hint": "整合包链接或文件",
    "link_ph": "https://…/pack.mrpack",
    "icon": FIF.ZIP_FOLDER,
    "search": "search_modpacks",
    "install": "install_modpack",
    "list_installed": "get_installed_modpacks",
    "delete": "delete_modpack",
    "task_prefix": "安装整合包",
    "types": ["全部", "生存", "空岛", "科技", "魔法"],
}

RESOURCE_SPEC = {
    "object_name": "resourcePackPage",
    "search_title": "搜索资源包",
    "empty_search": "没有找到相关资源包",
    "empty_installed": "还没有安装资源包",
    "installed_title": "已安装",
    "local_label": "导入 zip",
    "local_filter": "资源包 (*.zip)",
    "local_dialog": "选择资源包",
    "link_label": "从链接安装",
    "link_title": "从链接安装资源包",
    "link_hint": "资源包下载链接 (URL)",
    "link_ph": "https://…/pack.zip",
    "icon": FIF.PHOTO,
    "search": "search_resourcepacks",
    "install": "install_resourcepack",
    "list_installed": "get_installed_resourcepacks",
    "delete": "delete_resourcepack",
    "task_prefix": "安装资源包",
    "types": ["全部", "16x", "32x", "64x", "写实", "现代风", "动态效果"],
}

SHADER_SPEC = {
    "object_name": "shaderPage",
    "search_title": "搜索光影包",
    "empty_search": "没有找到相关光影",
    "empty_installed": "还没有安装光影",
    "installed_title": "已安装",
    "local_label": "导入 zip",
    "local_filter": "光影包 (*.zip)",
    "local_dialog": "选择光影包",
    "link_label": "从链接安装",
    "link_title": "从链接安装光影",
    "link_hint": "光影包下载链接 (URL)",
    "link_ph": "https://…/shader.zip",
    "icon": FIF.BRIGHTNESS,
    "search": "search_shaders",
    "install": "install_shader",
    "list_installed": "get_installed_shaders",
    "delete": "delete_shader",
    "task_prefix": "安装光影",
    "types": ["全部", "写实", "卡通", "高性能", "光追"],
}

DATAPACK_SPEC = {
    "object_name": "datapackPage",
    "search_title": "搜索数据包",
    "empty_search": "没有找到相关数据包",
    "empty_installed": "还没有安装数据包",
    "installed_title": "已安装",
    "local_label": "导入 zip",
    "local_filter": "数据包 (*.zip)",
    "local_dialog": "选择数据包",
    "link_label": "从链接安装",
    "link_title": "从链接安装数据包",
    "link_hint": "数据包下载链接 (URL)",
    "link_ph": "https://…/datapack.zip",
    "icon": FIF.LEAF,
    "search": "search_datapacks",
    "install": "install_datapack",
    "list_installed": "get_installed_datapacks",
    "delete": "delete_datapack",
    "task_prefix": "安装数据包",
    "types": ["全部", "生存", "冒险", "装饰"],
}


class PclCatalogPage(QWidget):
    def __init__(self, backend, spec: dict, parent=None):
        super().__init__(parent)
        self.setObjectName(spec["object_name"])
        self.backend = backend
        self.spec = spec
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        search_card = PclCard()
        sc = QVBoxLayout(search_card)
        sc.setContentsMargins(16, 12, 16, 14)
        sc.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(spec["search_title"])
        title.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        head.addWidget(title)
        head.addStretch(1)
        self.instance_box = ComboBox()
        self.instance_box.setFixedWidth(120)
        self.link_btn = TransparentPushButton(FIF.LINK, spec["link_label"])
        self.local_btn = TransparentPushButton(FIF.FOLDER, spec["local_label"])
        head.addWidget(self.instance_box)
        head.addWidget(self.link_btn)
        head.addWidget(self.local_btn)
        sc.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("名称")
        self.source_box = ComboBox()
        self.source_box.addItems(["全部", "Modrinth", "CurseForge"])
        self.version_box = EditableComboBox()
        self.version_box.addItems(["全部 (也可自行输入)", "1.21.1", "1.20.1", "1.19.2", "1.18.2", "1.16.5", "1.12.2"])
        self.version_box.setCurrentIndex(0)
        self.type_box = ComboBox()
        self.type_box.addItems(spec.get("types") or ["全部"])
        grid.addWidget(self._lab("名称"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1)
        grid.addWidget(self._lab("来源"), 0, 2)
        grid.addWidget(self.source_box, 0, 3)
        grid.addWidget(self._lab("版本"), 1, 0)
        grid.addWidget(self.version_box, 1, 1)
        grid.addWidget(self._lab("类型"), 1, 2)
        grid.addWidget(self.type_box, 1, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(3, 2)
        sc.addLayout(grid)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.search_btn = PushButton("搜索")
        self.search_btn.setFixedSize(88, 32)
        self.search_btn.setStyleSheet(
            f"PushButton {{ border: 1px solid {PCL_BLUE}; color: {PCL_BLUE};"
            " background: white; border-radius: 4px; }"
            "PushButton:hover { background: " + PCL_HOVER + "; }"
        )
        self.reset_btn = PushButton("重置条件")
        self.reset_btn.setFixedSize(88, 32)
        btns.addWidget(self.search_btn)
        btns.addSpacing(12)
        btns.addWidget(self.reset_btn)
        btns.addStretch(1)
        sc.addLayout(btns)
        root.addWidget(search_card)

        result_card = PclCard()
        rc = QVBoxLayout(result_card)
        rc.setContentsMargins(8, 6, 8, 8)
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        scroll.setWidget(host)
        rc.addWidget(scroll)
        root.addWidget(result_card, 1)

        self.name_edit.returnPressed.connect(self._search)
        self.search_btn.clicked.connect(self._search)
        self.reset_btn.clicked.connect(self._reset)
        self.link_btn.clicked.connect(self._install_from_link)
        self.local_btn.clicked.connect(self._import_local)
        self.instance_box.currentTextChanged.connect(self.reload_installed)

        self._search_token = 0
        self._popular_loaded = False
        self._reload_instances()
        self._show_idle()

    def _lab(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"color: {PCL_MUTED}; font-size: 12px; background: transparent;")
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lab.setFixedWidth(40)
        return lab

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

    def _source(self) -> str:
        text = self.source_box.currentText()
        if text == "CurseForge":
            return "CurseForge"
        if text == "Modrinth":
            return "Modrinth"
        return "全部"

    def _reset(self):
        self.name_edit.clear()
        self.source_box.setCurrentIndex(0)
        self.version_box.setCurrentIndex(0)
        self.type_box.setCurrentIndex(0)
        self._search()

    def _clear_list(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_idle(self):
        self._search_token += 1
        self._clear_list()
        self.list_layout.addWidget(EmptyState(self.spec["icon"], "输入名称后点击搜索"))
        self.list_layout.addStretch(1)

    def _search(self):
        self._search_token += 1
        token = self._search_token
        self._clear_list()
        fn = getattr(self.backend, self.spec["search"], None)
        if not callable(fn):
            self.list_layout.addWidget(EmptyState(self.spec["icon"], self.spec["empty_search"]))
            self.list_layout.addStretch(1)
            return
        query = self.name_edit.text().strip()
        source = self._source()
        type_f = self.type_box.currentText()
        call_async = getattr(self.backend, "call_async", None)
        if callable(call_async):
            self.list_layout.addWidget(EmptyState(self.spec["icon"], "正在搜索…"))
            self.list_layout.addStretch(1)
            call_async(
                lambda: fn(query, source),
                lambda rows, t=token, tf=type_f: self._on_search_ok(t, rows, tf),
                lambda err, t=token: self._on_search_err(t, err),
            )
            return
        self._on_search_ok(token, fn(query, source), type_f)

    def _on_search_err(self, token, err):
        if token != self._search_token:
            return
        self._clear_list()
        self.list_layout.addWidget(EmptyState(self.spec["icon"], f"搜索失败: {err}"))
        self.list_layout.addStretch(1)

    def _on_search_ok(self, token, results, type_f):
        if token != self._search_token:
            return
        results = list(results or [])
        if type_f and type_f != "全部" and self.name_edit.text().strip():
            q = type_f.lower()
            filtered = []
            for row in results:
                blob = " ".join(str(row.get(k) or "") for k in ("name", "description", "tags")).lower()
                tags = " ".join(str(t) for t in (row.get("tags") or [])).lower()
                if q in blob or q in tags:
                    filtered.append(row)
            if filtered:
                results = filtered
        self._clear_list()
        query = self.name_edit.text().strip()
        if not query:
            head = QLabel("热门推荐")
            head.setStyleSheet(
                f"color: {PCL_TITLE}; font-size: 13px; font-weight: 700;"
                " background: transparent; padding: 10px 12px 6px 12px;")
            self.list_layout.addWidget(head)
        if not results:
            self.list_layout.addWidget(EmptyState(self.spec["icon"], self.spec["empty_search"]))
            self.list_layout.addStretch(1)
            return
        for row in results:
            self.list_layout.addWidget(PclResultRow(row, self._install))
        self.list_layout.addStretch(1)

    def reload_installed(self):
        self._reload_instances()
        if not self._popular_loaded:
            self._popular_loaded = True
            self._search()

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
        extra["source"] = item.get("source") or self._source()
        gv = self.version_box.currentText()
        extra["game_version"] = "" if (not gv or str(gv).startswith("全部")) else gv
        if callable(fn):
            try:
                if self.spec.get("install") == "install_modpack":
                    fn(name, extra.get("source") or "Modrinth", extra=extra)
                else:
                    fn(name, extra["instance"], extra=extra)
            except TypeError:
                try:
                    fn(name, extra["instance"])
                except TypeError:
                    fn(name)
            return
        start = getattr(self.backend, "start_task", None)
        if callable(start):
            def _pending(progress, log, *_a, **_k):
                log("待后端对接")
                progress(1, 1, "待对接")
            start(f"{self.spec['task_prefix']} {name}".strip(), _pending)

    def _install_from_link(self):
        dlg = InputDialog(self.spec["link_title"], self.spec["link_hint"],
                          placeholder=self.spec["link_ph"], parent=self)
        if dlg.exec() and dlg.value():
            url = dlg.value()
            self._install({"name": url, "url": url}, self.link_btn)

    def _import_local(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.spec["local_dialog"], "", self.spec["local_filter"])
        for p in paths:
            self._install({"name": p, "path": p}, self.local_btn)


class ModPage(PclCatalogPage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, MOD_SPEC, parent)


class ModpackPage(PclCatalogPage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, MODPACK_SPEC, parent)


class ShaderPage(PclCatalogPage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, SHADER_SPEC, parent)


class ResourcePackPage(PclCatalogPage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, RESOURCE_SPEC, parent)


class DatapackPage(PclCatalogPage):
    def __init__(self, backend, parent=None):
        super().__init__(backend, DATAPACK_SPEC, parent)
