# -*- coding: utf-8 -*-
"""主窗口：细顶栏 + 左侧 5 项导航。"""

import os

from qfluentwidgets import FluentIcon as FIF, InfoBar, InfoBarPosition, setTheme, setThemeColor, Theme as FluentTheme
from qfluentwidgets.window.fluent_window import FluentWindowBase
from PySide6.QtCore import Qt, QEasingCurve, QPoint, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from mclauncher import APP_DISPLAY_NAME, APP_VERSION
from .backend import BackendAPI
from .fly_anim import fly_to
from .pcl_chrome import Theme, fade_stack_to, paint_theme_surfaces, PclSideBar, PclTitleBar, TITLE_H
from .widgets import pick_color
from .pages.account_page import AccountPage
from .pages.ai_page import AiPage
from .pages.catalog_page import DatapackPage, ModPage, ModpackPage, ResourcePackPage, ShaderPage, WorldPage
from .pages.download_hub import DownloadSection
from .pages.feedback_page import FeedbackPage
from .pages.instance_page import InstancePage
from .pages.java_page import JavaPage
from .pages.launch_page import LaunchPage
from .pages.multiplayer_page import MultiplayerPage
from .pages.playtime_page import PlaytimePage
from .pages.servers_page import ServerPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import DownloadDock, TasksPage
from .pages.version_page import VersionPage
from mclauncher.i18n import tr


class MainWindow(FluentWindowBase):
    def __init__(self):
        # FluentWindowBase 在 super() / resize 时就会发 resizeEvent，
        # 这些属性必须先占位，否则一点开就闪退。
        self.side = None
        self.task_badge = None
        self.download_dock = None
        self._pages = {}
        self._nav_cover = None
        self._nav_fade = None
        self._dock_anim = None
        self._fly_jobs = []
        self._launch_after = {}
        self._clip_seen = None
        self._quit_on_exit = False
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor("#FFFFFF", "#1B1B1B")
        setThemeColor("#2E9B6B", save=False)

        self.backend = BackendAPI(self)
        self.apply_theme()

        self.launch_page = LaunchPage(self.backend, self)
        self.settings_page = SettingsPage(self.backend, self)
        self.version_page = VersionPage(self.backend, self)
        self.mod_page = ModPage(self.backend, self)
        self.modpack_page = ModpackPage(self.backend, self)
        self.datapack_page = DatapackPage(self.backend, self)
        self.resource_page = ResourcePackPage(self.backend, self)
        self.shader_page = ShaderPage(self.backend, self)
        self.world_page = WorldPage(self.backend, self)
        self.java_page = JavaPage(self.backend, self)
        self.instance_page = InstancePage(self.backend, self)
        self.account_page = AccountPage(self.backend, self)
        self.multiplayer_page = MultiplayerPage(self.backend, self)
        self.ai_page = AiPage(self.backend, self)
        self.feedback_page = FeedbackPage(self.backend, self)
        self.tasks_page = TasksPage(self.backend, self)
        self.servers_page = ServerPage(self.backend, self)
        self.playtime_page = PlaytimePage(self.backend, self)
        self.download_section = DownloadSection(self.backend, self)
        self.download_section.bind([
            (tr("原版游戏"), self.version_page),
            ("Mod", self.mod_page),
            (tr("整合包"), self.modpack_page),
            (tr("数据包"), self.datapack_page),
            (tr("资源包"), self.resource_page),
            (tr("光影包"), self.shader_page),
            (tr("世界"), self.world_page),
            ("Java", self.java_page),
        ])

        self._pages = {
            "launch": self.launch_page,
            "instance": self.instance_page,
            "account": self.account_page,
            "multiplayer": self.multiplayer_page,
            "download": self.download_section,
            "ai": self.ai_page,
            "servers": self.servers_page,
            "playtime": self.playtime_page,
            "feedback": self.feedback_page,
            "tasks": self.tasks_page,
            "settings": self.settings_page,
        }

        bar = PclTitleBar(self)
        self.setTitleBar(bar)

        self.side = PclSideBar([
            ("item", "launch", FIF.PLAY, tr("启动")),
            ("item", "instance", FIF.TILES, tr("实例")),
            ("item", "account", FIF.PEOPLE, tr("账号")),
            ("item", "multiplayer", FIF.PEOPLE, tr("联机")),
            ("item", "servers", getattr(FIF, "GLOBE", None) or FIF.CLOUD_DOWNLOAD, tr("服务器")),
            ("item", "playtime", getattr(FIF, "CLOCK", None) or FIF.DATE_TIME, tr("时长")),
            ("item", "download", FIF.DOWNLOAD, tr("下载")),
            ("item", "ai", getattr(FIF, "CHAT", None) or FIF.HELP, tr("AI 助手")),
            ("item", "feedback", getattr(FIF, "FEEDBACK", None) or getattr(FIF, "MAIL", None) or FIF.HELP, tr("反馈")),
            ("item", "settings", FIF.SETTING, tr("设置")),
            ("stretch",),
            ("item", "tasks", FIF.CLOUD_DOWNLOAD, tr("下载任务")),
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
        self.task_badge = QLabel("0", target)
        self.task_badge.setObjectName("taskBadge")
        self.task_badge.setAlignment(Qt.AlignCenter)
        self.task_badge.setFixedHeight(16)
        self.task_badge.setMinimumWidth(16)
        self.task_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.task_badge.setStyleSheet(
            "#taskBadge { background: #E23C3C; color: #fff; border-radius: 8px;"
            " font-size: 10px; font-weight: 700; padding: 0 4px; }"
        )
        self.task_badge.hide()

        self._launch_after = {}
        self.download_dock = DownloadDock(self.backend, self)
        self.backend.finished.connect(self._notify_task)
        self.backend.theme_changed.connect(self.apply_theme)
        self._ui_refresh = QTimer(self)
        self._ui_refresh.setSingleShot(True)
        self._ui_refresh.setInterval(280)
        self._ui_refresh.timeout.connect(self._refresh_pages)
        self.backend.ui_changed.connect(self._ui_refresh.start)
        self.backend.task_count_changed.connect(self._update_task_badge)
        self.backend.game_started.connect(self._on_game_started)
        self.backend.game_exited.connect(self._on_game_exited)
        self.stackedWidget.currentChanged.connect(lambda *_: self._place_download_dock())
        self.resize(1180, 760)
        # 上面 apply_theme() 时 _pages 还是空的，ScrollArea 表面没刷到。
        # 页面全部就位后再刷一遍，深色启动才不会白字压浅底。
        self.apply_theme()
        QTimer.singleShot(400, self._boot_extras)

    def apply_theme(self):
        color = self.backend.get_setting("theme_color", "#2E9B6B") or "#2E9B6B"
        dark = bool(self.backend.get_setting("ui_dark", False))
        Theme.apply(dark)
        setThemeColor(color, save=False)
        setTheme(FluentTheme.DARK if dark else FluentTheme.LIGHT, save=False)
        # 必须固定传「浅色槽 / 深色槽」两套值。以前写 Theme.bg 当浅色槽，
        # 一切深色 Theme.bg 已是 #1B1B1B，会把浅色槽也污染成深色，切回浅色时
        # Fluent 背景动画/缓存还会短暂甚至一直停在脏值上。
        self.setCustomBackgroundColor("#FFFFFF", "#1B1B1B")
        if hasattr(self, "_updateBackgroundColor"):
            try:
                self._updateBackgroundColor()
            except Exception:
                pass
        bar = self.titleBar
        if hasattr(bar, "restyle"):
            bar.restyle()
        side = getattr(self, "side", None)
        if side is not None and hasattr(side, "restyle"):
            side.restyle()
        cat = getattr(getattr(self, "download_section", None), "cat", None)
        if cat is not None and hasattr(cat, "restyle"):
            cat.restyle()
        # 刷新所有页面的一次性样式
        for _key, page in self._pages.items():
            if hasattr(page, "restyle"):
                try:
                    page.restyle()
                except Exception:
                    pass
        self._paint_page_surfaces()
        self._apply_background()
        if getattr(self, "_pages", None):
            page = self.stackedWidget.currentWidget()
            if page is not None:
                self._reload_page(page)
        self.update()

    def _paint_page_surfaces(self):
        """刷页面 + ScrollArea/viewport/宿主底色，并修正 QFormLayout 系统标签。

        Fluent 卡片深色是半透明白，必须压在 Theme.bg 上；只刷 page 本身不够，
        设置/实例里的 ScrollArea 仍是浅灰时就会白字压浅底。
        """
        for page in list(self._pages.values()):
            if page is None:
                continue
            paint_theme_surfaces(page)
        # 下载分区不在 _pages 里，单独刷
        ds = getattr(self, "download_section", None)
        if ds is not None:
            paint_theme_surfaces(ds)
        dock = getattr(self, "download_dock", None)
        if dock is not None:
            paint_theme_surfaces(dock)
            if hasattr(dock, "restyle"):
                try:
                    dock.restyle()
                except Exception:
                    pass

    def _apply_background(self):
        """把设置里的背景图刷到内容区。

        路径是直接拼进 QSS 的，两个坑必须挡住：
        文件被用户删掉后 Qt 只会静默画成空白，界面看起来像坏了；
        路径里带单引号（`D:/我的'图/bg.png`）会提前闭合 url('...')，整张样式表连带失效。
        """
        image = str(self.backend.get_setting("ui_background", "") or "").strip()
        bg = Theme.bg
        if not image or not os.path.isfile(image):
            # 无背景图时也要显式铺 Theme.bg，否则 stacked 透明，下面页又是浅色默认底
            self.stackedWidget.setStyleSheet(
                f"QStackedWidget {{ background-color: {bg}; border: none; }}"
            )
            return
        path = image.replace("\\", "/").replace("'", "%27")
        self.stackedWidget.setStyleSheet(
            f"QStackedWidget {{ background-color: {bg};"
            f" border-image: url('{path}') 0 0 0 0 stretch stretch; }}"
        )

    def _boot_extras(self):
        if self.backend.get_setting("first_run", True):
            from .pages.first_run import FirstRunDialog
            dlg = FirstRunDialog(self.backend, self)
            if dlg.exec():
                dlg.apply()
            else:
                data = self.backend.get_settings()
                data["first_run"] = False
                self.backend.save_settings(data)
        self._ask_feedback_consent()
        if not self.backend.get_setting("auto_check_update", True):
            return

        def ok(info):
            info = info or {}
            if info.get("has_update"):
                InfoBar.info(tr("发现更新"), info.get("message") or tr("到设置里安装"), parent=self,
                             position=InfoBarPosition.TOP_RIGHT, duration=5000)

        self.backend.call_async(self.backend.check_update, ok, lambda *_: None)

    def _on_game_started(self):
        mode = self.backend.get_setting("launcher_visibility") or "keep"
        if mode == "close":
            self._quit_on_exit = True
            self.hide()
        elif mode in ("hide", "hide_reopen"):
            self.hide()
        elif mode == "minimize":
            self.showMinimized()

    def _on_game_exited(self, _code):
        if self._quit_on_exit:
            self._quit_on_exit = False
            QApplication.instance().quit()
            return
        mode = self.backend.get_setting("launcher_visibility") or "keep"
        if mode == "hide_reopen":
            self.show()
            self.raise_()
            self.activateWindow()

    def _ask_feedback_consent(self):
        from mclauncher import feedback as fb
        from .widgets import prompt_feedback_consent
        if not fb.consent_asked():
            prompt_feedback_consent(self)
            return
        if fb.has_consent():
            fb.start_heartbeat()

    def _on_nav(self, key: str):
        page = self._pages.get(key)
        if page is None:
            return
        fade_stack_to(self.stackedWidget, page, self)
        paint_theme_surfaces(page)
        self._reload_page(page)

    def switchTo(self, interface):
        if self.download_section.has_page(interface) and interface is not self.download_section:
            fade_stack_to(self.stackedWidget, self.download_section, self)
            self.side.set_current("download", emit=False)
            self.download_section.show_page(interface)
            return
        fade_stack_to(self.stackedWidget, interface, self)
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
        self.task_badge.setFixedHeight(16)
        self.task_badge.show()
        self._place_task_badge()

    def _place_task_badge(self):
        side = getattr(self, "side", None)
        badge = getattr(self, "task_badge", None)
        if side is None or badge is None or badge.isHidden():
            return
        btn = side.button("tasks")
        if btn is None:
            return
        icon_w = btn.iconSize().width() if not btn.icon().isNull() else 16
        pad, gap = 14, 6
        text_w = btn.fontMetrics().horizontalAdvance(btn.text())
        x = pad + icon_w + gap + text_w + 6
        y = (btn.height() - badge.height()) // 2
        x = min(x, btn.width() - badge.width() - 8)
        x = max(pad + icon_w, x)
        badge.move(x, y)
        badge.raise_()

    def _place_download_dock(self, animate=True):
        dock = getattr(self, "download_dock", None)
        if not dock:
            return
        page = self.stackedWidget.currentWidget()
        hide_on = {self.settings_page, self.instance_page, self.tasks_page, self.feedback_page}
        want = bool(getattr(dock, "_active", None)) and page not in hide_on
        g = self.stackedWidget.geometry()
        dock.adjustSize()
        w = min(640, max(420, g.width() - 40))
        h = dock.sizeHint().height()
        x = g.x() + (g.width() - w) // 2
        y = g.y() + g.height() - h - 18
        dest = QPoint(max(g.x() + 12, x), max(g.y() + 12, y))
        dock.setFixedWidth(w)
        prev = getattr(self, "_dock_anim", None)
        if prev is not None:
            prev.stop()
            self._dock_anim = None
        if want:
            if not dock.isVisible():
                dock.move(dest.x(), dest.y() + 28)
                dock.show()
                dock.raise_()
                if animate:
                    self._dock_anim = self._anim_pos(dock, dest, 280)
                else:
                    dock.move(dest)
            else:
                dock.move(dest)
                dock.raise_()
            return
        if not dock.isVisible():
            return
        if not animate:
            dock.hide()
            return

        def after():
            dock.hide()
            self._dock_anim = None

        self._dock_anim = self._anim_pos(dock, QPoint(dest.x(), dest.y() + 24), 200, after)

    def _anim_pos(self, widget, end, ms, done=None):
        anim = QPropertyAnimation(widget, b"pos", self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(widget.pos())
        anim.setEndValue(end)
        if done:
            anim.finished.connect(done)
        anim.start()
        return anim

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "side", None) is None:
            return
        self._place_download_dock(animate=False)
        self._place_task_badge()

    def closeEvent(self, event):
        try:
            self.backend.terracotta_shutdown()
        except Exception:
            pass
        try:
            from mclauncher.feedback import stop_heartbeat
            stop_heartbeat(send_offline=True)
        except Exception:
            pass
        try:
            self.backend.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def fly_to_tasks(self, source, text: str, color: str | None = None):
        if source is None:
            return
        if not self.backend.get_setting("ui_fly_animation", True):
            return
        duration = max(1, int(self.backend.get_setting("ui_fly_duration_ms", 620)))
        letter = (str(text or "").strip()[:1] or "↓").upper()
        side = getattr(self, "side", None)
        target = side.button("tasks") if side is not None else None
        if target is None:
            return
        fly_to(
            self, source, letter, color or pick_color(str(text or "")),
            target=target, duration=duration,
        )

    def queue_launch_after(self, task_id, instance: str, version: str, loader: str = tr("无")):
        if not task_id:
            return
        self._launch_after[task_id] = (instance, version, loader or tr("无"))

    def _launch_installed(self, instance: str, version: str, loader: str = tr("无")):
        last = getattr(self.backend, "_last_installed", None) or {}
        vid = version
        if last.get("instance") == instance and last.get("version"):
            vid = last["version"]
        self.switchTo(self.launch_page)
        self.launch_page.reload()
        if instance:
            self.launch_page.instance_box.setCurrentText(instance)
            self.launch_page.reload()
        box = self.launch_page.version_box
        ids = [box.itemText(i) for i in range(box.count())]
        pick = vid if vid in ids else next(
            (i for i in ids if vid and vid in i),
            next((i for i in ids if version and version in i and (
                loader in ("", tr("无")) or (loader or "").lower() in i.lower()
            )), ids[0] if ids else ""),
        )
        if pick:
            box.setCurrentText(pick)
        self.launch_page._on_launch()

    def _notify_task(self, task_id, success, message):
        pending = self._launch_after.pop(task_id, None)
        title = self.backend.task_title(task_id)
        if pending and success:
            instance, version, loader = pending
            InfoBar.success(tr("安装完成"), tr("正在启动游戏…"), parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=2500)
            QTimer.singleShot(
                380, lambda i=instance, v=version, l=loader: self._launch_installed(i, v, l))
            return
        if str(title).startswith(tr("启动游戏")) or str(title).startswith(tr("微软登录")):
            return
        self._place_download_dock()
        if success:
            InfoBar.success(title, message, parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
        elif message != tr("已取消"):
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
        if cur is self.servers_page:
            self.servers_page.reload()
            return
        if cur is self.playtime_page:
            self.playtime_page.reload()
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
