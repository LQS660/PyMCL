# -*- coding: utf-8 -*-
"""版本管理页：已安装版本的卡片网格，对齐 PCL/HMCL 的版本列表。

一个游戏目录，版本平铺在里面。每张卡上直接能切「独立 / 大锅饭」——
独立的版本有自己的 mods 目录，大锅饭的版本共用游戏目录那一份。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    Action, CaptionLabel, CheckBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    LineEdit, ListWidget, MessageBox, MessageBoxBase, PushButton, RoundMenu,
    ScrollArea, SearchLineEdit, SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
    SwitchButton, TransparentPushButton, TransparentToolButton,
)

from mclauncher.config import CONFIG
from mclauncher.i18n import tr
from mclauncher.version_settings import ISOLATION_LABELS, ISOLATION_NONE, ISOLATED_DEFAULT
from ..pcl_chrome import prestyle_page
from ..widgets import (
    EmptyState, IconTile, InputDialog, Pill, choose_export_dir, grid_columns,
    report_export,
)

CARD_W = 252
CARD_H = 184


class VersionCard(SimpleCardWidget):
    """一个版本一张卡。

    卡按版本 id 复用：列表刷新时只改卡上会变的那几处（见 set_info），不重建控件。
    全删全建的话每进一次页面就把主线程堵住几十毫秒——那几十毫秒里所有动画都是定住的。
    """

    def __init__(self, info: dict, page, parent=None):
        super().__init__(parent)
        self.info: dict = {}
        self.page = page
        self.vid = vid = info["id"]
        self.setFixedSize(CARD_W, CARD_H)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(IconTile(vid, size=38))
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        self.loader_pill = Pill(info["loader"], info["loader_color"])
        self.title = StrongBodyLabel(vid)
        self.title.setToolTip(vid)
        self.mc_label = CaptionLabel("")
        name_box.addWidget(self.title)
        name_box.addWidget(self.mc_label)
        top.addLayout(name_box, 1)
        top.addWidget(self.loader_pill)
        layout.addLayout(top)

        stat = QHBoxLayout()
        stat.setSpacing(6)
        self.mods_pill = Pill("", "#4C8BF5")
        # 隐藏标常驻布局、按需显隐：加加减减会让这一行重新布一次
        self.hidden_pill = Pill(tr("已隐藏"), "#8A9099")
        stat.addWidget(self.mods_pill)
        stat.addWidget(self.hidden_pill)
        stat.addStretch(1)
        layout.addLayout(stat)

        iso_row = QHBoxLayout()
        iso_row.setSpacing(8)
        iso_row.addWidget(CaptionLabel(tr("独立模组")))
        self.iso_switch = SwitchButton()
        self.iso_switch.setOnText(tr("独立"))
        self.iso_switch.setOffText(tr("大锅饭"))
        self.iso_switch.setToolTip(
            tr("开：这个版本用自己的 mods / config；关：与其他大锅饭版本共用游戏目录那一份"))
        self.iso_switch.checkedChanged.connect(
            lambda on, v=vid: page.toggle_isolation(v, on))
        iso_row.addWidget(self.iso_switch)
        iso_row.addStretch(1)
        layout.addLayout(iso_row)

        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        launch = PushButton(FIF.PLAY, tr("启动"))
        launch.setFixedHeight(28)
        launch.clicked.connect(lambda: page.launch(vid))
        actions.addWidget(launch)
        actions.addStretch(1)
        for icon, tip, fn in (
            (FIF.TAG, tr("管理这个版本的模组"), lambda: page.open_mods(vid)),
            (FIF.SETTING, tr("版本设置"), lambda: page.setup(vid)),
            (getattr(FIF, "MORE", FIF.VIEW), tr("更多"), None),
        ):
            btn = TransparentToolButton(icon)
            btn.setToolTip(tip)
            if fn is None:
                btn.clicked.connect(lambda _=False, v=vid, b=btn: page.more_menu(v, b))
            else:
                btn.clicked.connect(lambda _=False, f=fn: f())
            actions.addWidget(btn)
        layout.addLayout(actions)

        self.set_info(info)

    def set_info(self, info: dict):
        """把这张卡换成 info 描述的样子。版本 id 不会变——卡就是按它复用的。"""
        if info == self.info:
            return
        self.info = info
        self.loader_pill.setText(info["loader"])
        self.loader_pill.set_color(info["loader_color"])
        self.loader_pill.adjustSize()
        # 版本 id 动不动就是 1.20.1-forge-47.2.0，不截断会顶穿卡片、压到加载器标上
        avail = max(60, CARD_W - 32 - 38 - 10 - self.loader_pill.sizeHint().width() - 8)
        self.title.setText(
            self.title.fontMetrics().elidedText(self.vid, Qt.ElideMiddle, avail))
        mc = f'Minecraft {info.get("mc") or "?"}'
        self.mc_label.setText(
            self.mc_label.fontMetrics().elidedText(mc, Qt.ElideRight, avail))
        self.mods_pill.setText(f'{tr("模组")} {info["mods"]}')
        self.hidden_pill.setVisible(bool(info.get("hidden")))
        want = bool(info.get("isolated"))
        if self.iso_switch.isChecked() != want:
            # 程序改开关不能走 toggle_isolation：那条路是给用户点的，会弹确认框
            self.iso_switch.blockSignals(True)
            self.iso_switch.setChecked(want)
            self.iso_switch.blockSignals(False)


class VersionModsDialog(MessageBoxBase):
    """单个版本的模组清单：启停、删除、导入、打开目录。"""

    def __init__(self, backend, version: str, isolated: bool, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.version = version
        self.viewLayout.addWidget(SubtitleLabel(f'{tr("模组")} · {version}', self))
        self.hint = CaptionLabel(self)
        self.hint.setWordWrap(True)
        self.hint.setText(
            tr("这个版本有自己的 mods 目录，改动不会影响别的版本。") if isolated else
            tr("这个版本吃大锅饭：下面是游戏目录共享的 mods，所有大锅饭版本都会一起变。"))
        self.viewLayout.addWidget(self.hint)

        self.filter = LineEdit(self)
        self.filter.setPlaceholderText(tr("按文件名筛选…"))
        self.viewLayout.addWidget(self.filter)

        self.list = ListWidget(self)
        self.list.setMinimumHeight(300)
        self.viewLayout.addWidget(self.list)

        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        self.toggle_btn = PushButton(tr("启用 / 禁用"))
        self.delete_btn = PushButton(tr("删除"))
        self.import_btn = PushButton(tr("导入 jar"))
        self.export_btn = PushButton(tr("导出…"))
        self.export_btn.setToolTip(
            tr("导出选中的模组；没选就导出整个列表。默认落在启动器目录的 exports"))
        self.folder_btn = PushButton(tr("打开目录"))
        for b in (self.toggle_btn, self.delete_btn, self.import_btn,
                  self.export_btn, self.folder_btn):
            row.addWidget(b)
        self.viewLayout.addWidget(host)

        self.yesButton.setText(tr("关闭"))
        self.cancelButton.hide()
        self.widget.setMinimumWidth(560)

        self.filter.textChanged.connect(self._refill)
        self.toggle_btn.clicked.connect(self._toggle)
        self.delete_btn.clicked.connect(self._delete)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.folder_btn.clicked.connect(self._open_folder)
        self.list.itemDoubleClicked.connect(lambda _i: self._toggle())
        self.reload()

    def _root(self) -> str:
        return self.backend.game_root_name()

    def reload(self):
        try:
            self._entries = self.backend.get_installed_mod_entries(
                self._root(), self.version) or []
        except Exception as exc:  # noqa: BLE001
            self._entries = []
            InfoBar.error(tr("读取模组失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
        self._refill()

    def _refill(self, *_):
        text = (self.filter.text() or "").strip().lower()
        self.list.clear()
        self._rows = [r for r in self._entries
                      if not text or text in str(r.get("filename") or "").lower()]
        for row in self._rows:
            mark = "" if row.get("enabled") else f'  [{tr("已禁用")}]'
            self.list.addItem(f'{row.get("filename")}{mark}')
        if not self._rows:
            self.list.addItem(tr("（空）到「下载」页搜模组，或点「导入 jar」"))

    def _selected(self) -> dict | None:
        idx = self.list.currentRow()
        rows = getattr(self, "_rows", [])
        return rows[idx] if 0 <= idx < len(rows) else None

    def _toggle(self):
        row = self._selected()
        if not row:
            return
        name = row.get("filename")
        try:
            if row.get("enabled"):
                self.backend.disable_mod(self._root(), name, self.version)
            else:
                self.backend.enable_mod(self._root(), name, self.version)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("切换失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
        self.reload()

    def _delete(self):
        row = self._selected()
        if not row:
            return
        name = row.get("filename")
        box = MessageBox(tr("删除确认"), f"将删除模组文件「{name}」，不可恢复。", self)
        box.yesButton.setText(tr("删除"))
        box.cancelButton.setText(tr("取消"))
        if not box.exec():
            return
        try:
            self.backend.delete_mod(self._root(), name, self.version)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("删除失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
        self.reload()

    def _import(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("选择模组 jar"), "", tr("模组 (*.jar)"))
        for p in paths or []:
            try:
                self.backend.install_mod(p, self._root(), extra={
                    "path": p, "instance": self._root(),
                    "version": self.version, "source": tr("本地"),
                })
            except Exception as exc:  # noqa: BLE001
                InfoBar.error(tr("导入失败"), str(exc), parent=self,
                              position=InfoBarPosition.TOP, duration=4000)
        if paths:
            QTimer.singleShot(900, self, self.reload)

    def _export(self):
        row = self._selected()
        names = [row["filename"]] if row else [
            r.get("filename") for r in getattr(self, "_rows", []) if r.get("filename")]
        if not names:
            InfoBar.warning(tr("没有可导出的模组"), tr("这个版本还没装模组"), parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        folder = choose_export_dir(self.backend, self)
        if not folder:
            return
        try:
            result = self.backend.export_contents("mod", names, folder, self.version)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("导出失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)
            return
        report_export(result, self)

    def _open_folder(self):
        try:
            self.backend.open_mods_folder(self._root(), self.version)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("打开失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)


class VersionManagePage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        # objectName 沿用 instancePage：侧栏路由键、已保存的布局配置都按它认页面
        self.setObjectName("instancePage")
        self.backend = backend
        self._reloading = False
        self._cols = 0
        self._rows: list[dict] = []
        self._cards: dict[str, VersionCard] = {}   # 版本 id -> 卡（差量刷新靠它复用）
        self._placed: list[str] = []               # 网格里当前的摆放顺序
        self._empty = None                         # 空态提示（有卡时不存在）
        self._syncing = False                      # 正在程序化更新卡，别把开关当用户点的
        self._show_hidden = bool(CONFIG.get("show_hidden_versions"))
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._refill)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(SubtitleLabel(tr("版本管理")))
        self.subtitle = CaptionLabel("")
        # 副标题里带完整游戏目录路径，不换行就把页面最小宽度顶到 1000+，
        # 主窗口跟着被撑大（见 multiplayer_page 同一处注释）
        self.subtitle.setWordWrap(True)
        title_box.addWidget(self.subtitle)
        head.addLayout(title_box, 1)
        self.open_dir_btn = TransparentPushButton(FIF.FOLDER, tr("打开游戏目录"))
        self.install_btn = TransparentPushButton(FIF.ADD, tr("安装新版本"))
        head.addWidget(self.open_dir_btn)
        head.addWidget(self.install_btn)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("搜索已安装的版本…"))
        self.search.setFixedWidth(260)
        self.hidden_box = CheckBox(tr("显示隐藏"))
        self.hidden_box.setChecked(self._show_hidden)
        bar.addWidget(self.search)
        bar.addWidget(self.hidden_box)
        bar.addStretch(1)
        root.addLayout(bar)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)
        prestyle_page(self, self.scroll)

        self.search.textChanged.connect(lambda _t: self._resize_timer.start())
        self.hidden_box.toggled.connect(self._toggle_hidden)
        self.open_dir_btn.clicked.connect(self._open_game_dir)
        self.install_btn.clicked.connect(self._goto_install)

        self.reload()

    # ------------------------------------------------------------------
    def reload(self):
        if self._reloading:
            return
        self._reloading = True
        try:
            self._rows = self.backend.get_version_rows(include_hidden=self._show_hidden)
            self._refill()
        finally:
            self._reloading = False

    def _refill(self):
        """差量刷新：按版本 id 复用卡片，只建新增的、只删消失的。

        每次导航到本页都会走一遍，所以不能全删全建再整页重刷主题表面：
        那一下会把主线程堵住几十毫秒（版本越多越久），期间所有动画定住。
        """
        text = (self.search.text() or "").strip().lower()
        rows = [r for r in self._rows if not text or text in r["id"].lower()]
        isolated = sum(1 for r in self._rows if r.get("isolated"))
        self.subtitle.setText(
            f'{tr("游戏目录")} {self.backend.game_root_path()}　·　'
            f'{len(self._rows)} {tr("个版本")}　·　'
            f'{tr("独立")} {isolated} / {tr("大锅饭")} {len(self._rows) - isolated}')

        if not rows:
            self._drop_cards(list(self._cards))
            self._placed = []
            self._cols = 1
            self._set_empty(bool(text))
            return
        self._set_empty(None)

        wanted = [r["id"] for r in rows]
        self._drop_cards([v for v in self._cards if v not in set(wanted)])

        created = []
        self._syncing = True
        try:
            for row in rows:
                card = self._cards.get(row["id"])
                if card is None:
                    card = VersionCard(row, self)
                    self._cards[row["id"]] = card
                    created.append(card)
                else:
                    card.set_info(row)
        finally:
            self._syncing = False

        cols = grid_columns(self.scroll, self, CARD_W)
        if created or cols != self._cols or wanted != self._placed:
            self._place(wanted, cols)
        self._cols = cols
        self._placed = wanted

        if created:
            # 只有真添了卡才刷一遍表面；一张没添就什么都不用动，
            # 老卡的颜色跟着主窗口切主题时的 ensure_theme_surfaces 走。
            from ..pcl_chrome import paint_theme_surfaces
            paint_theme_surfaces(self)

    def _place(self, order: list[str], cols: int):
        """按 order 重新摆放卡片。takeAt 只摘布局项，控件本身留着复用。"""
        while self.grid.count():
            self.grid.takeAt(0)
        for i, vid in enumerate(order):
            card = self._cards.get(vid)
            if card is not None:
                self.grid.addWidget(card, i // cols, i % cols)
                card.show()

    def _drop_cards(self, ids):
        for vid in list(ids):
            card = self._cards.pop(vid, None)
            if card is None:
                continue
            self.grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()

    def _set_empty(self, searching: bool | None):
        """searching=True/False 摆出空态，None 收掉它。"""
        if self._empty is not None:
            self.grid.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None
        if searching is None:
            return
        self._empty = EmptyState(
            FIF.SEARCH if searching else FIF.TAG,
            tr("没有匹配的版本") if searching else
            tr("还没有安装任何版本，点右上角「安装新版本」"))
        self.grid.addWidget(self._empty, 0, 0)

    def _toggle_hidden(self, on):
        self._show_hidden = bool(on)
        CONFIG.set("show_hidden_versions", self._show_hidden)
        CONFIG.save()
        self.reload()

    # ------------------------------------------------------------------
    def _root(self) -> str:
        return self.backend.game_root_name()

    def toggle_isolation(self, version: str, isolated: bool):
        # 差量刷新时是程序在拨开关，不是用户点的：别弹确认框、别回写后端
        if self._syncing:
            return
        seed = False
        if isolated:
            box = MessageBox(
                tr("转为独立模组"),
                f"「{version}」将拥有自己的 mods / config 目录。\n\n"
                "要把游戏目录里现有的共享模组复制一份过去吗？\n"
                "选「复制」保持现在能玩的样子；选「留空」从零开始装。",
                self,
            )
            box.yesButton.setText(tr("复制一份"))
            box.cancelButton.setText(tr("留空"))
            seed = bool(box.exec())
        try:
            self.backend.toggle_version_isolation(version, isolated, seed=seed)
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("切换失败"), str(exc), self).exec()
        self.reload()

    def launch(self, version: str):
        win = self.window()
        launch_page = getattr(win, "launch_page", None)
        if launch_page is None:
            return
        win.switchTo(launch_page)
        launch_page.reload()
        box = launch_page.version_box
        ids = [box.itemText(i) for i in range(box.count())]
        if version in ids:
            box.setCurrentText(version)
        launch_page._on_launch()

    def open_mods(self, version: str):
        row = next((r for r in self._rows if r["id"] == version), {})
        VersionModsDialog(self.backend, version, bool(row.get("isolated")), self).exec()
        self.reload()

    def setup(self, version: str):
        from .version_setup import VersionSetupDialog
        dlg = VersionSetupDialog(self.backend, self._root(), version, self)
        if dlg.exec():
            dlg.save()
        self.reload()

    def more_menu(self, version: str, btn):
        menu = RoundMenu(parent=self)

        def add(text, fn):
            act = Action(text)
            act.triggered.connect(fn)
            menu.addAction(act)

        add(tr("打开版本文件夹"), lambda: self._open_folder(version, "root"))
        add(tr("打开游戏文件夹"), lambda: self._open_folder(version, "game"))
        add(tr("存档管理…"), lambda: self._saves(version))
        add(tr("隔离细分…"), lambda: self._isolation_detail(version))
        add(tr("重命名"), lambda: self._rename(version))
        add(tr("复制一份"), lambda: self._copy(version))
        add(tr("隐藏 / 取消隐藏"), lambda: self._hide(version))
        add(tr("创建桌面快捷方式"), lambda: self._shortcut(version))
        add(tr("导出启动脚本"),
            lambda: self.backend.export_launch_script(self._root(), version))
        add(tr("修复（补全缺失文件）"),
            lambda: self.backend.repair_version(self._root(), version))
        add(tr("卸载这个版本"), lambda: self._uninstall(version))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _isolation_detail(self, version: str):
        from ..widgets import ComboDialog
        current = self.backend.get_version_isolation(version)
        labels = list(ISOLATION_LABELS.values())
        dlg = ComboDialog(
            tr("隔离细分"),
            f"「{version}」要把哪些东西跟别的版本分开？\n"
            "「大锅饭」= 全部共用；「完全独立」= 模组、配置、存档都各管各的。",
            labels, ISOLATION_LABELS.get(current, ISOLATION_LABELS[ISOLATION_NONE]), self)
        if not dlg.exec():
            return
        inverse = {v: k for k, v in ISOLATION_LABELS.items()}
        mode = inverse.get(dlg.value(), ISOLATION_NONE)
        if mode == current:
            return
        seed = False
        if mode == ISOLATED_DEFAULT:
            ask = MessageBox(tr("要带上现有模组吗"),
                             tr("把游戏目录里共享的模组复制一份到这个版本？"), self)
            ask.yesButton.setText(tr("复制一份"))
            ask.cancelButton.setText(tr("留空"))
            seed = bool(ask.exec())
        try:
            self.backend.set_version_isolation(version, mode, seed=seed)
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("切换失败"), str(exc), self).exec()
        self.reload()

    def _open_folder(self, version: str, which: str):
        try:
            self.backend.open_version_folder(self._root(), version, which)
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("无法打开"), str(exc), self).exec()

    def _saves(self, version: str):
        from .saves_dialog import SavesDialog
        SavesDialog(self.backend, self._root(), version, self).exec()

    def _rename(self, version: str):
        dlg = InputDialog(tr("重命名版本"), tr("新版本 ID"), text=version, parent=self)
        if dlg.exec() and dlg.value():
            try:
                self.backend.rename_version(self._root(), version, dlg.value())
            except Exception as exc:  # noqa: BLE001
                MessageBox(tr("重命名失败"), str(exc), self).exec()
            self.reload()

    def _copy(self, version: str):
        dlg = InputDialog(tr("复制版本"), tr("新版本 ID"),
                          text=f"{version}-copy", parent=self)
        if dlg.exec() and dlg.value():
            try:
                self.backend.copy_version(self._root(), version, dlg.value())
            except Exception as exc:  # noqa: BLE001
                MessageBox(tr("复制失败"), str(exc), self).exec()
            self.reload()

    def _hide(self, version: str):
        try:
            data = self.backend.get_version_settings(self._root(), version)
            self.backend.hide_version(self._root(), version, not bool(data.get("hidden")))
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("操作失败"), str(exc), self).exec()
        self.reload()

    def _shortcut(self, version: str):
        try:
            path = self.backend.create_desktop_shortcut(self._root(), version)
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("创建失败"), str(exc), self).exec()
            return
        MessageBox(tr("已创建"), f"桌面快捷方式：\n{path}\n\n双击即可直接启动该版本。",
                   self).exec()

    def _uninstall(self, version: str):
        box = MessageBox(
            tr("卸载版本"),
            f"确定卸载「{version}」？\n该版本目录下的独立模组与存档会一并删除。",
            self)
        box.yesButton.setText(tr("卸载"))
        box.cancelButton.setText(tr("取消"))
        if not box.exec():
            return
        try:
            self.backend.uninstall_version(version)
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("卸载失败"), str(exc), self).exec()
        self.reload()

    def _open_game_dir(self):
        try:
            self.backend.open_instance_folder(self._root())
        except Exception as exc:  # noqa: BLE001
            MessageBox(tr("无法打开"), str(exc), self).exec()

    def _goto_install(self):
        win = self.window()
        page = getattr(win, "version_page", None)
        if page is not None:
            win.switchTo(page)

    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.isVisible():
            return
        if grid_columns(self.scroll, self, CARD_W) == self._cols:
            return
        self._resize_timer.start()


# 旧名字还挂在侧栏工厂与懒加载属性上
InstancePage = VersionManagePage
