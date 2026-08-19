# -*- coding: utf-8 -*-
"""主窗口：细顶栏 + 左侧 5 项导航。"""

from qfluentwidgets import FluentIcon as FIF, InfoBadge, InfoBadgePosition, InfoBar, InfoBarPosition, setThemeColor
from qfluentwidgets.window.fluent_window import FluentWindowBase
from PySide6.QtCore import QTimer

from mclauncher import APP_DISPLAY_NAME, APP_VERSION
from .backend import BackendAPI
from .pcl_chrome import PCL_BG, PCL_GREEN, PclSideBar, PclTitleBar, TITLE_H
from .pages.ai_page import AiPage
from .pages.catalog_page import DatapackPage, ModPage, ModpackPage, ResourcePackPage, ShaderPage
from .pages.download_hub import DownloadSection
from .pages.instance_page import InstancePage
from .pages.java_page import JavaPage
from .pages.launch_page import LaunchPage
from .pages.multiplayer_page import MultiplayerPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import DownloadDock, TasksPage
from .pages.version_page import VersionPage


class MainWindow(FluentWindowBase):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.resize(1180, 760)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(PCL_BG, "#1B1B1B")
        setThemeColor(PCL_GREEN, save=False)

        self.backend = BackendAPI(self)

        self.launch_page = LaunchPage(self.backend, self)
        self.settings_page = SettingsPage(self.backend, self)
        self.version_page = VersionPage(self.backend, self)
        self.mod_page = ModPage(self.backend, self)
        self.modpack_page = ModpackPage(self.backend, self)
        self.datapack_page = DatapackPage(self.backend, self)
        self.resource_page = ResourcePackPage(self.backend, self)
        self.shader_page = ShaderPage(self.backend, self)
        self.java_page = JavaPage(self.backend, self)
        self.instance_page = InstancePage(self.backend, self)
        self.multiplayer_page = MultiplayerPage(self.backend, self)
        self.ai_page = AiPage(self.backend, self)
        self.tasks_page = TasksPage(self.backend, self)
        self.download_section = DownloadSection(self.backend, self)
        self.download_section.bind([
            ("原版游戏", self.version_page),
            ("Mod", self.mod_page),
            ("整合包", self.modpack_page),
            ("数据包", self.datapack_page),
            ("资源包", self.resource_page),
            ("光影包", self.shader_page),
            ("Java", self.java_page),
        ])

        self._pages = {
            "launch": self.launch_page,
            "instance": self.instance_page,
            "multiplayer": self.multiplayer_page,
            "download": self.download_section,
            "ai": self.ai_page,
            "tasks": self.tasks_page,
            "settings": self.settings_page,
        }

        bar = PclTitleBar(self)
        self.setTitleBar(bar)

        self.side = PclSideBar([
            ("item", "launch", FIF.PLAY, "启动"),
            ("item", "instance", FIF.TILES, "实例"),
            ("item", "multiplayer", FIF.PEOPLE, "联机"),
            ("item", "download", FIF.DOWNLOAD, "下载"),
            ("item", "ai", getattr(FIF, "CHAT", None) or FIF.HELP, "AI 助手"),
            ("item", "settings", FIF.SETTING, "设置"),
            ("stretch",),
            ("item", "tasks", FIF.CLOUD_DOWNLOAD, "下载任务"),
        ])
        self.side.currentChanged.connect(self._on_nav)

        self.hBoxLayout.setContentsMargins(0, TITLE_H, 0, 0)
        self.hBoxLayout.addWidget(self.side)
        self.hBoxLayout.addWidget(self.stackedWidget)
        for page in self._pages.values():
            self.stackedWidget.addWidget(page)
        self.stackedWidget.setCurrentWidget(self.launch_page)
        self.side.set_current("launch", emit=False)

        target = self.side.button("tasks")
        self.task_badge = InfoBadge.error(
            0, parent=self, target=target,
            position=InfoBadgePosition.TOP_RIGHT)
        self.task_badge.hide()

        self.download_dock = DownloadDock(self.backend, self)
        self.backend.finished.connect(self._notify_task)
        self._ui_refresh = QTimer(self)
        self._ui_refresh.setSingleShot(True)
        self._ui_refresh.setInterval(280)
        self._ui_refresh.timeout.connect(self._refresh_pages)
        self.backend.ui_changed.connect(self._ui_refresh.start)
        self.backend.task_count_changed.connect(self._update_task_badge)
        self.stackedWidget.currentChanged.connect(lambda *_: self._place_download_dock())

    def _on_nav(self, key: str):
        page = self._pages.get(key)
        if page is None:
            return
        self.stackedWidget.setCurrentWidget(page, popOut=False)
        self._reload_page(page)

    def switchTo(self, interface):
        if self.download_section.has_page(interface) and interface is not self.download_section:
            self.stackedWidget.setCurrentWidget(self.download_section, popOut=False)
            self.side.set_current("download", emit=False)
            self.download_section.show_page(interface)
            return
        self.stackedWidget.setCurrentWidget(interface, popOut=False)
        for key, page in self._pages.items():
            if page is interface:
                self.side.set_current(key, emit=False)
                self._reload_page(page)
                return

    def _reload_page(self, page):
        if page is self.download_section:
            inner = page.current_page()
            if inner is not None and inner is not page:
                self._reload_page(inner)
            return
        if page is self.version_page:
            if getattr(page, "_all_versions", None):
                page.reload_installed_only()
            else:
                page.reload()
            return
        if page is self.java_page:
            page.reload(scan_system=False)
            return
        if hasattr(page, "reload_installed"):
            page.reload_installed()
            return
        if hasattr(page, "reload"):
            try:
                page.reload()
            except TypeError:
                pass

    def _update_task_badge(self, count: int):
        if count <= 0:
            self.task_badge.hide()
            return
        self.task_badge.setText("99+" if count > 99 else str(count))
        self.task_badge.adjustSize()
        self.task_badge.show()
        if self.task_badge.manager:
            self.task_badge.move(self.task_badge.manager.position())

    def _place_download_dock(self):
        dock = getattr(self, "download_dock", None)
        if not dock:
            return
        page = self.stackedWidget.currentWidget()
        hide_on = {self.settings_page, self.instance_page, self.tasks_page}
        if (not getattr(dock, "_active", None)) or page in hide_on:
            dock.hide()
            return
        dock.show()
        g = self.stackedWidget.geometry()
        dock.adjustSize()
        w = min(640, max(420, g.width() - 40))
        h = dock.sizeHint().height()
        x = g.x() + (g.width() - w) // 2
        y = g.y() + g.height() - h - 18
        dock.setFixedWidth(w)
        dock.move(max(g.x() + 12, x), max(g.y() + 12, y))
        dock.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_download_dock()

    def closeEvent(self, event):
        try:
            self.backend.terracotta_shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def _notify_task(self, task_id, success, message):
        title = self.backend.task_title(task_id)
        if title.startswith("启动游戏"):
            return
        self._place_download_dock()
        if success:
            InfoBar.success(title, message, parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
        elif message != "已取消":
            InfoBar.error(title, message, parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)

    def _refresh_pages(self):
        cur = self.stackedWidget.currentWidget()
        if cur is self.launch_page:
            self.launch_page.reload()
            return
        if cur is self.instance_page:
            self.instance_page.reload()
            return
        if cur is self.download_section:
            inner = self.download_section.current_page()
            if inner is self.version_page and hasattr(inner, "reload_installed_only"):
                inner.reload_installed_only()
            elif inner is self.java_page:
                inner.reload(scan_system=False)
            elif inner is not None and hasattr(inner, "reload_installed"):
                inner.reload_installed()
            elif inner is not None and hasattr(inner, "reload"):
                try:
                    inner.reload()
                except TypeError:
                    pass
