# -*- coding: utf-8 -*-
"""模组管理页：查看已安装模组、启用/禁用、删除、导入、检查更新。

侧边栏一级入口。目录选择与安装目标一致：大锅饭共享 mods + 开了独立模组的版本。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition, LineEdit,
    MessageBox, PushButton, SubtitleLabel, SwitchButton, TransparentPushButton,
    TransparentToolButton,
)

from mclauncher.i18n import tr
from ..pcl_chrome import Theme, ghost_btn_qss, prestyle_page, row_qss
from ..widgets import EmptyState, IconTile, Pill, choose_export_dir, report_export
from .catalog_page import PclCard


def _fmt_size(n) -> str:
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{int(n)} B"


class _ModRow(QFrame):
    """单个已安装模组：图标 + 文件名 + 大小 + 启用开关 + 删除。"""

    def __init__(self, entry: dict, page):
        super().__init__(page)
        self.entry = entry
        self.setObjectName("modMgrRow")
        self.setStyleSheet(row_qss("modMgrRow"))
        self.setFixedHeight(60)
        name = entry.get("filename") or "?"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)
        lay.addWidget(IconTile(name, size=40))

        info = QVBoxLayout()
        info.setSpacing(1)
        title = QLabel(name)
        title.setStyleSheet(
            f"color: {Theme.title}; font-size: 13px; font-weight: 600; background: transparent;")
        info.addWidget(title)
        meta = CaptionLabel(
            f"{_fmt_size(entry.get('bytes'))}"
            + (f"  ·  {tr('已禁用')}" if not entry.get("enabled") else ""))
        meta.setStyleSheet(f"color: {Theme.muted}; font-size: 11px; background: transparent;")
        info.addWidget(meta)
        lay.addLayout(info, 1)

        self.switch = SwitchButton()
        self.switch.setChecked(bool(entry.get("enabled")))
        self.switch.setOnText(tr("启用"))
        self.switch.setOffText(tr("禁用"))
        self.switch.checkedChanged.connect(lambda on, n=name: page._toggle(n, on, self))
        lay.addWidget(self.switch)

        out = TransparentToolButton(getattr(FIF, "SHARE", FIF.DOWNLOAD))
        out.setToolTip(tr("导出到本地（默认启动器目录下的 exports）"))
        out.clicked.connect(lambda _, n=name: page._export_one(n))
        lay.addWidget(out)

        btn = TransparentToolButton(FIF.DELETE)
        btn.setToolTip(tr("删除"))
        btn.clicked.connect(lambda _, n=name: page._delete(n))
        lay.addWidget(btn)


class ModManagerPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("modsManagePage")
        self.backend = backend
        self.setStyleSheet("background: transparent;")
        self._entries: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        card = PclCard()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 12, 16, 14)
        cv.setSpacing(10)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title = SubtitleLabel(tr("模组管理"))
        # FluentLabel 的字色是它自己那份样式表里的 color 给的；这里整份替掉
        # 就必须自己带上 color，否则退回系统调色板的黑，深色下黑字压黑底。
        self.title.setStyleSheet(
            f"color: {Theme.text}; font-size: 17px; font-weight: 700; background: transparent;")
        self.subtitle = CaptionLabel(tr("查看与管理已安装的模组"))
        self.subtitle.setStyleSheet(f"color: {Theme.muted}; background: transparent;")
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.count_pill = Pill(tr("0 个"), "#4C8BF5")
        head.addWidget(self.count_pill)
        cv.addLayout(head)

        # 筛选和动作分两行：挤在一行要 970px 宽（两个定宽输入框 + 四颗带字按钮），
        # 会把整个主窗口的最小宽度顶到 1160——出厂 960 宽的窗口一进这页就会被撑大。
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.target_box = ComboBox()
        self.target_box.setFixedWidth(240)
        self.search = LineEdit()
        self.search.setPlaceholderText(tr("按文件名筛选…"))
        self.search.setFixedWidth(200)
        bar.addWidget(self.target_box)
        bar.addWidget(self.search)
        bar.addStretch(1)
        cv.addLayout(bar)
        acts = QHBoxLayout()
        acts.setSpacing(10)
        acts.addStretch(1)
        self.folder_btn = TransparentPushButton(FIF.FOLDER, tr("打开 mods 文件夹"))
        self.import_btn = TransparentPushButton(FIF.ADD, tr("导入 jar"))
        self.export_btn = TransparentPushButton(
            getattr(FIF, "SHARE", FIF.DOWNLOAD), tr("导出…"))
        self.export_btn.setToolTip(
            tr("把当前列出的模组导出到本地，默认启动器目录下的 exports"))
        self.update_btn = TransparentPushButton(FIF.SYNC, tr("检查更新"))
        for b in (self.folder_btn, self.import_btn, self.export_btn, self.update_btn):
            b.setFixedHeight(32)
            acts.addWidget(b)
        cv.addLayout(acts)

        tip = CaptionLabel(
            tr("「大锅饭」是所有共用版本合吃的那一份；在版本管理页把某个版本切成"
               "「独立」后，它会在这里单独列出来，改它不影响别人。"))
        tip.setStyleSheet(f"color: {Theme.muted}; font-size: 11px; background: transparent;")
        tip.setWordWrap(True)
        cv.addWidget(tip)
        root.addWidget(card)

        list_card = PclCard()
        lv = QVBoxLayout(list_card)
        lv.setContentsMargins(8, 6, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        scroll.setWidget(host)
        lv.addWidget(scroll)
        root.addWidget(list_card, 1)
        prestyle_page(self, scroll)

        self.search.textChanged.connect(self._refill)
        self.target_box.currentTextChanged.connect(lambda _t: self.reload_list())
        self.folder_btn.clicked.connect(self._open_folder)
        self.import_btn.clicked.connect(self._import_local)
        self.export_btn.clicked.connect(self._export_listed)
        self.update_btn.clicked.connect(self._check_updates)
        self.setAcceptDrops(True)

        self._reload_targets()
        self.reload_list()

    # ------------------------------------------------------------------
    def _current_instance(self) -> str:
        return self.backend.game_root_name()

    def _current_version(self) -> str:
        rows = getattr(self, "_target_rows", None) or []
        idx = self.target_box.currentIndex()
        return str(rows[idx].get("value") or "") if 0 <= idx < len(rows) else ""

    def _reload_targets(self):
        try:
            rows = self.backend.get_mods_targets(self._current_instance()) or []
        except Exception:
            rows = [{"label": tr("大锅饭（所有版本共用）"), "value": ""}]
        self._target_rows = rows
        cur_idx = self.target_box.currentIndex()
        self.target_box.blockSignals(True)
        self.target_box.clear()
        for r in rows:
            self.target_box.addItem(r.get("label") or "?")
        if 0 <= cur_idx < len(rows):
            self.target_box.setCurrentIndex(cur_idx)
        self.target_box.blockSignals(False)
        self.reload_list()

    # ------------------------------------------------------------------
    def reload(self):
        self._reload_targets()

    def reload_list(self):
        inst = self._current_instance()
        ver = self._current_version()
        try:
            self._entries = self.backend.get_installed_mod_entries(inst, ver) or []
        except Exception as e:
            self._entries = []
            InfoBar.error(tr("读取模组失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
        self._apply_subtitle()
        self._refill()

    def _apply_subtitle(self):
        total = len(self._entries)
        on = sum(1 for r in self._entries if r.get("enabled"))
        off = total - on
        size = sum(int(r.get("bytes") or 0) for r in self._entries)
        self.count_pill.setText(f"{on}/{total}")
        ver_label = self._current_version()
        where = ver_label or tr("大锅饭")
        self.subtitle.setText(
            f"{tr('启用')} {on} · {tr('禁用')} {off} · {_fmt_size(size)} · {where}")

    def _refill(self, *_):
        text = (self.search.text() or "").strip().lower()
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = [r for r in self._entries
                if not text or text in str(r.get("filename") or "").lower()]
        if not rows:
            if self._entries:
                self.list_layout.addWidget(EmptyState(FIF.SEARCH, tr("没有匹配的模组")))
            else:
                self.list_layout.addWidget(
                    EmptyState(FIF.TAG, tr("还没有安装模组，可点右上角「导入 jar」或到「下载」页安装")))
            self.list_layout.addStretch(1)
            return
        for row in rows:
            self.list_layout.addWidget(_ModRow(row, self))
        self.list_layout.addStretch(1)

    # ------------------------------------------------------------------
    def _toggle(self, filename: str, enabled: bool, row=None):
        inst = self._current_instance()
        ver = self._current_version()
        try:
            if enabled:
                self.backend.enable_mod(inst, filename, ver)
            else:
                self.backend.disable_mod(inst, filename, ver)
        except Exception as e:
            InfoBar.error(tr("切换失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
        finally:
            self.reload_list()

    def _delete(self, filename: str):
        inst = self._current_instance()
        ver = self._current_version()
        box = MessageBox(tr("删除确认"), f"将删除模组文件「{filename}」，不可恢复。", self)
        box.yesButton.setText(tr("删除"))
        box.cancelButton.setText(tr("取消"))
        if not box.exec():
            return
        try:
            self.backend.delete_mod(inst, filename, ver)
        except Exception as e:
            InfoBar.error(tr("删除失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return
        self.reload_list()

    def _open_folder(self):
        try:
            self.backend.open_mods_folder(self._current_instance(), self._current_version())
        except Exception as e:
            InfoBar.error(tr("打开失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)

    # ------------------------------------------------------------------
    def _export_one(self, filename: str):
        folder = choose_export_dir(self.backend, self)
        if not folder:
            return
        try:
            path = self.backend.export_content(
                "mod", filename, folder, self._current_version())
        except Exception as e:  # noqa: BLE001
            InfoBar.error(tr("导出失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)
            return
        report_export(None, self, single_path=path)

    def _export_listed(self):
        """导出当前列出的这些（受搜索框过滤），一个都没有就别弹选择框。"""
        text = (self.search.text() or "").strip().lower()
        names = [r.get("filename") for r in self._entries
                 if r.get("filename") and (not text or text in r["filename"].lower())]
        if not names:
            InfoBar.warning(tr("没有可导出的模组"), tr("当前列表是空的"), parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        folder = choose_export_dir(self.backend, self)
        if not folder:
            return
        try:
            result = self.backend.export_contents(
                "mod", names, folder, self._current_version())
        except Exception as e:  # noqa: BLE001
            InfoBar.error(tr("导出失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)
            return
        report_export(result, self)

    def _install_jars(self, paths):
        inst = self._current_instance()
        ver = self._current_version()
        win = self.window()
        for p in paths:
            extra = {"path": p, "instance": inst, "version": ver, "source": "本地"}
            if win is not None and hasattr(win, "fly_to_tasks"):
                win.fly_to_tasks(self.import_btn, Path(p).name)
            try:
                self.backend.install_mod(p, inst, extra=extra)
            except Exception as e:
                InfoBar.error(tr("导入失败"), str(e), parent=self,
                              position=InfoBarPosition.TOP, duration=4000)

    def _import_local(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("选择模组 jar"), "", tr("模组 (*.jar)"))
        if paths:
            self._install_jars(paths)

    def _check_updates(self):
        try:
            self.backend.start_mod_updates(self._current_instance())
        except Exception as e:
            InfoBar.error(tr("检查更新失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        # 本页压在分区壳上会把导航拖拽整个吃掉，替壳转交一下
        from .download_hub import forward_nav_drag
        forward_nav_drag(self, event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        from .download_hub import forward_nav_drag
        forward_nav_drag(self, event)

    def dragLeaveEvent(self, event):
        from .download_hub import forward_nav_leave
        forward_nav_leave(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        from .download_hub import forward_nav_drag
        if forward_nav_drag(self, event):
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile() and u.toLocalFile().lower().endswith(".jar")]
        if paths:
            self._install_jars(paths)

    def showEvent(self, event):
        super().showEvent(event)
        # 拖拽/粘贴场景少，这里只做轻量刷新
        clip = QGuiApplication.clipboard().text().strip()
        low = clip.lower()
        if clip and ("modrinth.com" in low or "curseforge.com" in low):
            InfoBar.info(tr("识别到剪贴板链接"), tr("到「下载」页搜索框粘贴即可安装"), parent=self,
                         position=InfoBarPosition.TOP, duration=3000)
