# -*- coding: utf-8 -*-
"""启动页：自由布局画布（横幅/配置/日志/新闻/便签等卡片，可任意拖拽缩放）。"""

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QTextBrowser, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition,
    PrimaryPushButton, PushButton, StrongBodyLabel, setFont,
)

from mclauncher.config import CONFIG
from mclauncher.instances import JAVA_AUTO
from .crash_dialog import CrashDialog
from ..widgets import DeviceCodeDialog
from .. import layout_model
from ..dashboard import DashboardCanvas
from .home_cards import (
    BannerBody, ConfigBody, LogBody, NewsBody, build_registry,
)
from mclauncher.i18n import tr


DOCK_CORNERS = ("bl", "br", "tl", "tr")


class _LaunchDock(QFrame):
    """启动坞本体：按住空白处拖动，松手吸到最近的角。

    按钮自己吃掉鼠标事件，所以拖拽只会从顶部把手、进度条、状态行这些
    地方起手，不会误触「启动游戏」。
    """

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self._grab_at: QPoint | None = None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(tr("按住拖动，可以把它挪到窗口的其它角落"))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        self._grab_at = e.globalPosition().toPoint() - self.mapToGlobal(QPoint(0, 0))
        self.setCursor(Qt.ClosedHandCursor)
        e.accept()

    def mouseMoveEvent(self, e):
        if self._grab_at is None:
            super().mouseMoveEvent(e)
            return
        want = self.parentWidget().mapFromGlobal(
            e.globalPosition().toPoint() - self._grab_at)
        x = max(0, min(want.x(), self.parentWidget().width() - self.width()))
        y = max(0, min(want.y(), self.parentWidget().height() - self.height()))
        self.move(x, y)
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._grab_at is None:
            super().mouseReleaseEvent(e)
            return
        self._grab_at = None
        self.setCursor(Qt.OpenHandCursor)
        self.page.snap_dock_to_nearest_corner()
        e.accept()


class LaunchPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("launchPage")
        self.backend = backend
        self._task_id = None
        self._login_dlg = None
        self._login_task_id = None
        self._java_opts = []
        self._syncing_java = False
        self._crash_shown = False
        self._body_cache = {}   # 单例卡片正文缓存：移除再添加时复用控件状态

        # 启动坞先于卡片构造：launch_btn / progress / status_label 是页面级
        # chrome，不再依附任何一张卡片。
        self._build_launch_dock()

        # 四个单例正文先于画布构造：页面逻辑（reload/启动/日志）始终能
        # 稳定引用 instance_box / log_edit 等控件，即使卡片被用户移除。
        for BodyCls in (BannerBody, ConfigBody, LogBody, NewsBody):
            if BodyCls.key not in self._body_cache:
                self._body_cache[BodyCls.key] = BodyCls(self, None, None)
        self.launch_btn.clicked.connect(self._on_launch)
        self.stop_btn.clicked.connect(self._on_stop)
        self.instance_box.currentTextChanged.connect(self._on_instance_changed)
        self.java_box.currentTextChanged.connect(self._on_java_changed)
        self.version_box.currentTextChanged.connect(self._sync_banner)
        # 记住「上次从 CONFIG 同步过来的值」，reload() 靠它区分
        # 「用户在本页手改过」和「一直是配置里的默认值」。
        self._cfg_snapshot = (
            int(CONFIG.get("memory_mb", 4096)),
            int(CONFIG.get("width", 854)),
            int(CONFIG.get("height", 480)),
        )

        self.registry = build_registry(self)
        self.canvas = DashboardCanvas(self.registry, self)
        self.canvas.layout_changed.connect(self._on_layout_changed)
        self.canvas.build_from_doc(layout_model.load_active_doc())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(0)
        root.addWidget(self.canvas)
        # 卡片是布局排完才落到新几何的，挑角要等那之后：resize 当场先把坞
        # 贴回边上，这个 0ms 定时器再按最终几何复核一次。
        self._dock_settle = QTimer(self)
        self._dock_settle.setSingleShot(True)
        self._dock_settle.setInterval(0)
        self._dock_settle.timeout.connect(self._place_dock)
        self._place_dock()

        self._layout_persist = QTimer(self)
        self._layout_persist.setSingleShot(True)
        self._layout_persist.setInterval(400)
        self._layout_persist.timeout.connect(self._persist_layout_now)

        backend.progress.connect(self._on_progress)
        backend.log.connect(self._on_log)
        backend.finished.connect(self._on_finished)
        backend.crash.connect(self._on_crash)
        backend.login_code.connect(self._on_login_code)
        backend.login_status.connect(self._on_login_status)

        # 扫盘（实例/账号/版本）延后到事件循环空转：首帧先出壳，
        # MainWindow._boot_reload 的合并刷新会覆盖这次 reload。
        QTimer.singleShot(0, self, self._boot_load)

    # ------------------------------------------------------------------
    # 启动坞：常驻四角之一（可拖拽换角），不随布局增删
    # ------------------------------------------------------------------
    def _build_launch_dock(self):
        """浮在画布上的启动坞（启动/停止 + 进度 + 状态）。

        任何一张卡片都可能被用户移除，所以「开游戏」这条主路径不能挂在
        横幅卡片里。坞是页面级 chrome：绝对定位在某个角上，不进 root
        布局，也不进布局文档；按住把手能拖到另外三个角，位置记在
        CONFIG["ui_launch_dock_corner"] 里。
        """
        dock = _LaunchDock(self)
        dock.setObjectName("launchDock")
        dock.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(dock)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(6)

        # 拖拽把手：按钮会自己吃掉鼠标事件，没有这条横杠就只剩边距能起手。
        self.dock_grip = QFrame(dock)
        self.dock_grip.setObjectName("launchDockGrip")
        self.dock_grip.setFixedSize(30, 4)
        self.dock_grip.setAttribute(Qt.WA_StyledBackground, True)
        self.dock_grip.setCursor(Qt.OpenHandCursor)
        lay.addWidget(self.dock_grip, 0, Qt.AlignHCenter)

        self.launch_btn = PrimaryPushButton(FIF.PLAY, tr("启动游戏"), dock)
        self.launch_btn.setFixedSize(170, 46)
        setFont(self.launch_btn, 15, QFont.DemiBold)
        self.stop_btn = PushButton(FIF.CLOSE, tr("停止"), dock)
        self.stop_btn.setFixedSize(170, 30)
        self.stop_btn.setEnabled(False)

        from ..motion import SmoothProgressBar
        self.progress = SmoothProgressBar(dock)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(170)
        self.status_label = CaptionLabel(tr("就绪"), dock)
        self.status_label.setFixedWidth(170)
        self.status_label.setWordWrap(True)

        lay.addWidget(self.launch_btn)
        lay.addWidget(self.stop_btn)
        lay.addWidget(self.progress)
        lay.addWidget(self.status_label)
        self.dock = dock
        self._dock_busy = None
        self._set_dock_busy(False)
        self._style_dock()

    def _style_dock(self):
        from ..pcl_chrome import Theme
        self.dock.setStyleSheet(
            f"#launchDock {{ background: {Theme.card};"
            f" border: 1px solid {Theme.line}; border-radius: 10px; }}"
            f"#launchDockGrip {{ background: {Theme.line}; border-radius: 2px; }}"
        )

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self._place_dock()   # 状态行换行数变了，坞的高度跟着变

    def _set_dock_busy(self, busy: bool):
        """闲着只留「启动游戏」；停止 / 进度 / 状态只在启动过程里展开。

        坞是浮在画布上的，占地越小压掉的卡片越少——不启动的时候那三样
        没什么可看的（状态永远是「就绪」、进度永远是 0）。
        """
        timer = getattr(self, "_dock_idle", None)
        if timer is not None:
            timer.stop()
        if self._dock_busy == busy:
            return
        self._dock_busy = busy
        for w in (self.stop_btn, self.progress, self.status_label):
            w.setVisible(busy)
        self._place_dock()

    def _collapse_dock_later(self, ms: int = 4000):
        """跑完先把结果留在坞上几秒，再收回到只剩启动按钮。"""
        timer = getattr(self, "_dock_idle", None)
        if timer is None:
            timer = self._dock_idle = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._set_dock_busy(False))
        timer.start(ms)

    # ---- 停靠角 ----
    def _dock_margins(self) -> tuple[int, int, int, int]:
        m = self.layout().contentsMargins() if self.layout() else None
        if m is None:
            return 16, 12, 16, 12
        return m.left(), m.top(), m.right(), m.bottom()

    def _dock_pos_for(self, corner: str) -> QPoint:
        left, top, right, bottom = self._dock_margins()
        w, h = self.dock.width(), self.dock.height()
        x = left if corner.endswith("l") else max(0, self.width() - w - right)
        y = top if corner.startswith("t") else max(0, self.height() - h - bottom)
        return QPoint(x, y)

    def _dock_cover_cost(self, rect: QRect) -> float:
        """坞摆在 rect 上会挡掉多少卡片（面积；启动配置按 3 倍算）。

        配置卡是要动手填的表单，被挡住比挡住新闻、日志难受得多。
        """
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return 0.0
        off = canvas.pos()
        cost = 0.0
        for card in canvas.cards:
            hit = rect.intersected(QRect(card.pos() + off, card.size()))
            if hit.isEmpty():
                continue
            weight = 3.0 if card.item.type == "config" else 1.0
            cost += weight * hit.width() * hit.height()
        return cost

    def dock_corner(self) -> str:
        """当前停靠角。用户拖过就认他拖的，没拖过挑一个不压卡片的。"""
        want = str(CONFIG.get("ui_launch_dock_corner") or "auto").lower()
        if want in DOCK_CORNERS:
            return want
        best, best_cost = DOCK_CORNERS[0], None
        for corner in DOCK_CORNERS:   # 顺序即偏好：空画布上还是落左下角
            cost = self._dock_cover_cost(QRect(self._dock_pos_for(corner), self.dock.size()))
            if cost <= 0.0:
                return corner
            if best_cost is None or cost < best_cost:
                best, best_cost = corner, cost
        return best

    def snap_dock_to_nearest_corner(self):
        """松手：吸到最近的角并记住它，下次开启动器还在那儿。"""
        cx = self.dock.x() + self.dock.width() / 2
        cy = self.dock.y() + self.dock.height() / 2
        corner = ("t" if cy < self.height() / 2 else "b") + \
                 ("l" if cx < self.width() / 2 else "r")
        CONFIG.set("ui_launch_dock_corner", corner)
        CONFIG.save()
        self._place_dock(animate=True)

    def _place_dock(self, animate: bool = False):
        """把坞摆回它的角；状态行换行把坞撑高时也跟着重新对齐。"""
        self.dock.adjustSize()
        dest = self._dock_pos_for(self.dock_corner())
        self.dock.raise_()
        if dest == self.dock.pos():
            return
        if not animate or not self.isVisible():
            self.dock.move(dest)
            return
        from .. import motion
        start = self.dock.pos()
        motion.tween(
            lambda v: self.dock.move(
                QPoint(round(start.x() + (dest.x() - start.x()) * v),
                       round(start.y() + (dest.y() - start.y()) * v))),
            0.0, 1.0, ms=180, context=self.dock)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_dock()
        settle = getattr(self, "_dock_settle", None)
        if settle is not None:
            settle.start()

    # ------------------------------------------------------------------
    # 布局：持久化 / 方案应用 / 编辑入口
    # ------------------------------------------------------------------
    def _on_layout_changed(self):
        self._layout_persist.start()
        # 卡片增删/挪位可能把坞压在了新卡片上：没被拖过的坞自己换个清静的角
        self._place_dock(animate=True)

    def persist_layout_soon(self):
        """卡片内容（便签文字、快捷入口配置）变化时的落盘入口。"""
        self._layout_persist.start()

    def _persist_layout_now(self):
        doc = self.canvas.current_doc()
        name = layout_model.active_profile()
        layout_model.save_active_doc(doc)
        if name:
            # 命名方案被就地编辑：同步回方案表，切换回来不丢改动。
            layout_model.save_profile(name, doc)

    def apply_doc(self, doc):
        """外部（设置页切方案）应用一份新布局，不触发落盘回环。"""
        self.canvas.build_from_doc(doc)
        self._place_dock(animate=True)

    def enter_edit_mode(self):
        self.canvas.set_edit_mode(True)

    def nav_to(self, key: str):
        win = self.window()
        if win is not None and hasattr(win, "switchTo"):
            win.switchTo(key)

    def restyle(self):
        self.canvas.restyle()
        self._style_dock()

    def _boot_load(self):
        if getattr(self, "_boot_loaded", False):
            return
        self._boot_loaded = True
        self.reload()
        self._load_news()

    def _version_setup(self):
        from .version_setup import VersionSetupDialog
        inst = self.instance_box.currentText() or "default"
        ver = self.version_box.currentText()
        if not ver:
            InfoBar.info(tr("未选择版本"), tr("请先安装并选择一个版本"), parent=self,
                         position=InfoBarPosition.TOP, duration=2500)
            return
        dlg = VersionSetupDialog(self.backend, inst, ver, self)
        if dlg.exec():
            dlg.save()
            InfoBar.success(tr("已保存"), tr("版本设置已写入"), parent=self,
                            position=InfoBarPosition.TOP, duration=2000)

    def _load_news(self):
        if getattr(self, "news_body", None) is None:
            return
        while self.news_host.count():
            item = self.news_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        mode = CONFIG.get("homepage_mode") or "news"
        if mode == "blank":
            self.news_body.set_title(tr("主页"))
            self.news_host.addWidget(CaptionLabel(tr("主页已设为空白")))
            return
        if mode == "custom":
            from pathlib import Path
            self.news_body.set_title(tr("自定义主页"))
            path = CONFIG.get("custom_homepage") or ""
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            p = Path(path) if path else None
            if p and p.is_file():
                if p.suffix.lower() in (".html", ".htm"):
                    try:
                        browser.setSource(QUrl.fromLocalFile(str(p.resolve())))
                    except Exception as exc:
                        browser.setPlainText(tr("无法加载自定义主页：{0}").format(exc))
                else:
                    try:
                        browser.setPlainText(p.read_text(encoding="utf-8", errors="replace"))
                    except OSError as exc:
                        browser.setPlainText(tr("无法读取自定义主页：{0}").format(exc))
            else:
                browser.setPlainText(tr("未设置自定义主页。到设置 → 启动页主页 填写本地 HTML 路径。"))
            self.news_host.addWidget(browser)
            return
        self.news_body.set_title(tr("Minecraft 新闻"))
        cached = self.backend.cached_news()
        self._fill_news(cached)

        def ok(rows):
            if not getattr(self, "news_host", None):
                return
            if (CONFIG.get("homepage_mode") or "news") != "news":
                return
            while self.news_host.count():
                item = self.news_host.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._fill_news(rows or [])

        def err(exc):
            if not getattr(self, "news_host", None):
                return
            InfoBar.warning(
                tr("新闻刷新失败"),
                str(exc or tr("将继续显示缓存")),
                parent=self, position=InfoBarPosition.TOP, duration=3500,
            )

        self.backend.call_async(self.backend.fetch_news, ok, err)

    def _fill_news(self, rows):
        if not rows:
            self.news_host.addWidget(CaptionLabel(tr("暂无新闻")))
            return
        for row in rows[:6]:
            t = StrongBodyLabel(row.get("title") or "")
            d = CaptionLabel((row.get("body") or row.get("version") or "")[:80])
            d.setWordWrap(True)
            self.news_host.addWidget(t)
            self.news_host.addWidget(d)

    def reload(self):
        if self._task_id and not self.launch_btn.isEnabled():
            return
        self.canvas.refresh_cards()
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        self.instance_box.addItem(self.backend.game_root_name())
        self.instance_box.blockSignals(False)

        cur_acc = self.account_box.currentText()
        accounts = self.backend.get_accounts()
        self.account_box.clear()
        self.account_box.addItems(accounts)
        active = None
        for row in self.backend.get_account_rows():
            if row.get("active"):
                active = row.get("name")
                break
        if cur_acc in accounts:
            self.account_box.setCurrentText(cur_acc)
        elif active in accounts:
            self.account_box.setCurrentText(active)

        self._sync_from_config()
        self._reload_versions()
        self._reload_java_box()

    def _on_memory_changed(self, value: int):
        self.memory_label.setText(f"{value} MB")
        self._persist_launch_defaults()

    def _persist_launch_defaults(self, *_args):
        """启动页改的内存 / 分辨率写回 CONFIG（防抖入口）。

        滑条每拖一格、SpinBox 每点一次箭头都会触发 valueChanged，
        直接落盘等于每次都原子写 + fsync config.json，拖动时磁盘
        和 UI 一起卡。这里 400ms 合并；点「启动游戏」时立即冲刷。
        """
        if not hasattr(self, "_defaults_persist"):
            self._defaults_persist = QTimer(self)
            self._defaults_persist.setSingleShot(True)
            self._defaults_persist.setInterval(400)
            self._defaults_persist.timeout.connect(self._persist_launch_defaults_now)
        self._defaults_persist.start()

    def _flush_launch_defaults(self):
        """立刻落盘待写的默认值（启动游戏 / 关窗前调用）。"""
        timer = getattr(self, "_defaults_persist", None)
        if timer is not None and timer.isActive():
            timer.stop()
            self._persist_launch_defaults_now()

    def _persist_launch_defaults_now(self):
        mem = int(self.memory_slider.value())
        w = int(self.width_spin.value())
        h = int(self.height_spin.value())
        CONFIG.set("memory_mb", mem)
        CONFIG.set("width", w)
        CONFIG.set("height", h)
        CONFIG.save()
        self._cfg_snapshot = (mem, w, h)

    def _sync_from_config(self):
        """把设置页刚保存的内存 / 分辨率同步到本页。

        这三个控件不能只在构造时读一次 CONFIG：`reload()` 必须把它们也带上，
        否则「设置里改了默认内存 → 回启动页 → 直接启动」用的还是旧值，得重开启动器才对得上。
        只覆盖用户没在本页动过的控件，避免把他这次临时调的参数冲掉。
        """
        mem, w, h = self._cfg_snapshot
        new_mem = int(CONFIG.get("memory_mb", 4096))
        new_w = int(CONFIG.get("width", 854))
        new_h = int(CONFIG.get("height", 480))
        if self.memory_slider.value() == mem:
            self.memory_slider.setValue(new_mem)
        if self.width_spin.value() == w:
            self.width_spin.setValue(new_w)
        if self.height_spin.value() == h:
            self.height_spin.setValue(new_h)
        self._cfg_snapshot = (new_mem, new_w, new_h)

    def _on_instance_changed(self):
        self._reload_versions()
        self._reload_java_box()

    def _reload_java_box(self):
        instance = self.instance_box.currentText() or "default"
        self._apply_java_opts(instance, self.backend.java_combo_options(instance, scan_system=False))
        call_async = getattr(self.backend, "call_async", None)
        if callable(call_async):
            call_async(
                lambda inst=instance: self.backend.java_combo_options(inst, True),
                lambda opts, inst=instance: self._on_java_opts(inst, opts),
            )

    def _on_java_opts(self, instance, opts):
        if (self.instance_box.currentText() or "default") != instance:
            return
        self._apply_java_opts(instance, opts or [])

    def _apply_java_opts(self, instance, opts):
        self._syncing_java = True
        try:
            self._java_opts = opts or []
            labels = [o["label"] for o in self._java_opts]
            self.java_box.blockSignals(True)
            self.java_box.clear()
            self.java_box.addItems(labels)
            want = self.backend.java_combo_label_for(instance, self._java_opts)
            self.java_box.setCurrentText(want if want in labels else JAVA_AUTO)
            self.java_box.blockSignals(False)
        finally:
            self._syncing_java = False

    def _on_java_changed(self, _text=""):
        if self._syncing_java:
            return
        instance = self.instance_box.currentText()
        if not instance:
            return
        self.backend.set_instance_java(instance, self._selected_java())

    def _selected_java(self) -> str:
        text = self.java_box.currentText() or JAVA_AUTO
        for o in self._java_opts:
            if o["label"] == text:
                return o["value"]
        return text

    def _reload_versions(self):
        cur = self.version_box.currentText()
        self.version_box.blockSignals(True)
        self.version_box.clear()
        instance = self.instance_box.currentText() or "default"
        ids = self.backend.get_installed_versions(instance)
        self.version_box.addItems(ids)
        if cur in ids:
            self.version_box.setCurrentText(cur)
        self.version_box.blockSignals(False)
        self._sync_banner()

    def _sync_banner(self):
        version = self.version_box.currentText() or "—"
        instance = self.instance_box.currentText() or "default"
        pack_name = ""
        pack_ver = ""
        pack_mc = ""
        for row in self.backend.get_instances():
            if row.get("name") == instance:
                pack_name = row.get("pack") or ""
                pack_ver = row.get("pack_version") or ""
                pack_mc = row.get("mc_version") or ""
                break
        if pack_name:
            bits = [b for b in (pack_ver, f"Minecraft {pack_mc}" if pack_mc else "", version) if b]
            self.banner.set_info(pack_name, " · ".join(bits) or version)
        else:
            self.banner.set_info(version, tr("点击「启动游戏」进入世界"))

    def _on_launch(self):
        from qfluentwidgets import MessageBox

        self._flush_launch_defaults()
        instance = self.instance_box.currentText() or "default"
        version = self.version_box.currentText()
        memory_mb = self.memory_slider.value()
        java = self._selected_java()
        try:
            pf = self.backend.preflight_launch(
                instance=instance, version=version,
                memory_mb=memory_mb, java=java,
            )
        except Exception as exc:
            MessageBox(tr("启动预检失败"), str(exc), self).exec()
            return

        items = list((pf or {}).get("items") or [])
        errors = [i for i in items if i.get("level") == "error"]
        warns = [i for i in items if i.get("level") == "warn"]
        if errors:
            body = "\n\n".join(
                f"· {e.get('title')}\n{e.get('detail')}" for e in errors)
            MessageBox(tr("启动预检未通过"), body, self).exec()
            return
        if warns:
            body = "\n\n".join(
                f"· {w.get('title')}\n{w.get('detail')}" for w in warns)
            box = MessageBox(
                tr("启动预检有警告"),
                body + "\n\n" + tr("是否仍要继续启动？"),
                self,
            )
            box.yesButton.setText(tr("继续启动"))
            box.cancelButton.setText(tr("取消"))
            if not box.exec():
                return

        self.log_edit.clear()
        for w in warns:
            self.log_edit.appendPlainText(
                f"[预检:warn] {w.get('title')}: {w.get('detail')}")
        self._set_dock_busy(True)
        self.progress.setValue(0)
        self._set_status(tr("准备启动…"))
        self.launch_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._crash_shown = False
        extra = []
        server = self.server_edit.text().strip()
        if server:
            if ":" in server:
                host, port = server.rsplit(":", 1)
                extra = ["--server", host, "--port", port]
            else:
                extra = ["--server", server, "--port", "25565"]
        self._task_id = self.backend.launch_game(
            instance=instance,
            version=version,
            account=self.account_box.currentText(),
            username=self.username_edit.text().strip(),
            memory_mb=memory_mb,
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            java=java,
            extra_game_args=extra or None,
        )

    def _on_stop(self):
        if self._task_id:
            self.backend.cancel_task(self._task_id)

    def _copy_cmd(self):
        try:
            cmd = self.backend.build_launch_command(
                instance=self.instance_box.currentText() or "default",
                version=self.version_box.currentText(),
                account=self.account_box.currentText(),
                username=self.username_edit.text().strip(),
                memory_mb=self.memory_slider.value(),
                width=self.width_spin.value(),
                height=self.height_spin.value(),
                java=self._selected_java(),
            )
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(cmd)
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(tr("已复制"), tr("启动命令已复制到剪贴板"), parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=2500)
        except Exception as e:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error(tr("复制失败"), str(e), parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=3500)

    def _login(self):
        if self._login_dlg:
            return
        self._login_dlg = DeviceCodeDialog(self.window())
        self._login_task_id = self.backend.start_microsoft_login()
        accepted = self._login_dlg.exec()
        self._login_dlg = None
        # 用户关掉设备码框就是放弃登录：后台任务要一并取消、task_id 要清掉，
        # 否则那个轮询会一直问微软要令牌直到超时，期间再点一次登录还会撞上旧任务的回调。
        if not accepted and self._login_task_id:
            cancel = getattr(self.backend, "cancel_task", None)
            if callable(cancel):
                try:
                    cancel(self._login_task_id)
                except Exception:
                    pass
            self._login_task_id = None
        self.reload()

    def _on_login_code(self, code, uri):
        if self._login_dlg:
            self._login_dlg.show_code(code, uri)

    def _on_login_status(self, text):
        if self._login_dlg:
            self._login_dlg.show_status(text)

    def _on_progress(self, task_id, current, total, message):
        if task_id != self._task_id:
            return
        self._set_dock_busy(True)
        self.progress.setValue(min(100, max(0, int(current * 100 / total))) if total else 0)
        status, speed = (message or "").split("  |  ", 1) if "  |  " in (message or "") else (message, "")
        self._set_status((status or tr("处理中…")) + (f"    {speed}" if speed else ""))

    def _on_log(self, task_id, text):
        if task_id == self._task_id:
            self.log_edit.appendPlainText(text)

    def _on_crash(self, task_id, report):
        if task_id != self._task_id:
            return
        self._crash_shown = True
        win = self.window()
        dlg = CrashDialog(
            report or {}, win, backend=getattr(win, "backend", None)
        )
        dlg.exec()
        if getattr(dlg, "want_relaunch", False):
            # 用报告里的实例/版本对齐选择框后再启动
            rep = report or {}
            inst = rep.get("instance") or ""
            ver = rep.get("version") or ""
            if inst:
                idx = self.instance_box.findText(inst)
                if idx >= 0:
                    self.instance_box.setCurrentIndex(idx)
            if ver:
                idx = self.version_box.findText(ver)
                if idx >= 0:
                    self.version_box.setCurrentIndex(idx)
            self._on_launch()

    def _on_finished(self, task_id, success, message):
        if task_id == self._login_task_id:
            if self._login_dlg:
                if success:
                    self._login_dlg.accept()
                else:
                    self._login_dlg.show_status(message)
            if success:
                self.reload()
        if task_id != self._task_id:
            return
        self.launch_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_status(message)
        self._collapse_dock_later()
        if success:
            self.progress.setValue(100)
            InfoBar.success(tr("游戏已结束"), message or tr("已正常退出"), parent=self,
                             position=InfoBarPosition.TOP, duration=3000)
            return
        if self._crash_shown or message == tr("已取消"):
            if message == tr("已取消"):
                InfoBar.info(tr("已停止"), message, parent=self,
                             position=InfoBarPosition.TOP, duration=2500)
            return
        win = self.window()
        dlg = CrashDialog({
            "title": tr("启动失败"),
            "headline": tr("启动中止"),
            "detail": message or tr("启动失败"),
            "help": tr("这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。"),
            "instance": self.instance_box.currentText() or "default",
            "version": self.version_box.currentText() or "",
        }, win, backend=getattr(win, "backend", None))
        dlg.exec()
        if getattr(dlg, "want_relaunch", False):
            self._on_launch()
