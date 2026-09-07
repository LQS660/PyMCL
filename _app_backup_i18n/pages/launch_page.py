# -*- coding: utf-8 -*-
"""启动页：渐变 Banner + 大启动按钮 + 配置 + 实时日志。"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
    HeaderCardWidget, InfoBar, InfoBarPosition, LineEdit, PlainTextEdit,
    PrimaryPushButton, ProgressBar, PushButton, SimpleCardWidget, Slider,
    SpinBox, StrongBodyLabel, TransparentPushButton, setFont,
)

from mclauncher.config import CONFIG
from mclauncher.instances import JAVA_AUTO
from .crash_dialog import CrashDialog
from ..widgets import BannerWidget, DeviceCodeDialog


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

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)

        self.banner = BannerWidget(self)
        self.launch_btn = PrimaryPushButton(FIF.PLAY, "启动游戏")
        self.launch_btn.setFixedSize(170, 46)
        setFont(self.launch_btn, 15, QFont.DemiBold)
        self.stop_btn = PushButton(FIF.CLOSE, "停止")
        self.stop_btn.setFixedSize(170, 30)
        self.stop_btn.setEnabled(False)
        self.banner.right_area.addStretch(1)
        self.banner.right_area.addWidget(self.launch_btn, 0, Qt.AlignRight)
        self.banner.right_area.addWidget(self.stop_btn, 0, Qt.AlignRight)
        root.addWidget(self.banner)

        self.progress = ProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = CaptionLabel("就绪")
        root.addWidget(self.progress)
        root.addWidget(self.status_label)

        middle = QHBoxLayout()
        middle.setSpacing(16)

        cfg_card = SimpleCardWidget(self)
        cfg = QFormLayout(cfg_card)
        cfg.setContentsMargins(20, 18, 20, 18)
        cfg.setSpacing(12)
        cfg.setLabelAlignment(Qt.AlignLeft)
        cfg.addRow(StrongBodyLabel("启动配置"))

        self.instance_box = ComboBox()
        self.version_box = ComboBox()
        self.account_box = ComboBox()
        self.java_box = ComboBox()
        self.username_edit = LineEdit()
        self.username_edit.setPlaceholderText("离线用户名")
        self.username_edit.setText("Player")

        self.memory_slider = Slider(Qt.Horizontal)
        self.memory_slider.setRange(512, 32768)
        self.memory_slider.setSingleStep(256)
        self.memory_slider.setValue(int(CONFIG.get("memory_mb", 4096)))
        self.memory_label = CaptionLabel(f"{self.memory_slider.value()} MB")
        self.memory_slider.valueChanged.connect(
            lambda v: self.memory_label.setText(f"{v} MB"))
        mem_row = QHBoxLayout()
        mem_row.addWidget(self.memory_slider, 1)
        mem_row.addWidget(self.memory_label)

        res_row = QHBoxLayout()
        self.width_spin = SpinBox()
        self.width_spin.setRange(320, 7680)
        self.width_spin.setValue(int(CONFIG.get("width", 854)))
        self.height_spin = SpinBox()
        self.height_spin.setRange(240, 4320)
        self.height_spin.setValue(int(CONFIG.get("height", 480)))
        res_row.addWidget(self.width_spin)
        res_row.addWidget(BodyLabel("×"))
        res_row.addWidget(self.height_spin)
        res_row.addStretch(1)

        cfg.addRow("实例", self.instance_box)
        cfg.addRow("版本", self.version_box)
        cfg.addRow("账号", self.account_box)
        cfg.addRow("用户名", self.username_edit)
        cfg.addRow("Java（本实例）", self.java_box)
        cfg.addRow("内存", mem_row)
        cfg.addRow("分辨率", res_row)
        self.server_edit = LineEdit()
        self.server_edit.setPlaceholderText("直连服务器 host 或 host:port")
        cfg.addRow("服务器", self.server_edit)
        setup_btn = TransparentPushButton(FIF.SETTING, "此版本设置…")
        setup_btn.clicked.connect(self._version_setup)
        news_btn = TransparentPushButton(FIF.SYNC, "刷新新闻")
        news_btn.clicked.connect(self._load_news)
        cfg.addRow("", setup_btn)
        cfg.addRow("", news_btn)

        ms_btn = TransparentPushButton(FIF.PEOPLE, "使用微软账户登录…")
        ms_btn.clicked.connect(self._login)
        cfg.addRow("", ms_btn)
        cfg_card.setFixedWidth(360)
        middle.addWidget(cfg_card)

        log_card = HeaderCardWidget(self)
        log_card.setTitle("实时日志")
        self.log_edit = PlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("启动日志将输出到这里…")
        log_card.viewLayout.addWidget(self.log_edit)
        # 启动命令复制
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)
        self.cmd_btn = PushButton("复制启动命令")
        self.cmd_btn.clicked.connect(self._copy_cmd)
        cmd_row.addStretch(1)
        cmd_row.addWidget(self.cmd_btn)
        log_card.viewLayout.addLayout(cmd_row)
        middle.addWidget(log_card, 1)

        news_card = HeaderCardWidget(self)
        news_card.setTitle("Minecraft 新闻")
        self.news_card = news_card
        self.news_host = QVBoxLayout()
        news_card.viewLayout.addLayout(self.news_host)
        middle.addWidget(news_card)
        root.addLayout(middle, 1)

        self.launch_btn.clicked.connect(self._on_launch)
        self.stop_btn.clicked.connect(self._on_stop)
        self.instance_box.currentTextChanged.connect(self._on_instance_changed)
        self.java_box.currentTextChanged.connect(self._on_java_changed)
        self.version_box.currentTextChanged.connect(self._sync_banner)
        backend.progress.connect(self._on_progress)
        backend.log.connect(self._on_log)
        backend.finished.connect(self._on_finished)
        backend.crash.connect(self._on_crash)
        backend.login_code.connect(self._on_login_code)
        backend.login_status.connect(self._on_login_status)

        self.reload()
        self._load_news()

    def _version_setup(self):
        from .version_setup import VersionSetupDialog
        inst = self.instance_box.currentText() or "default"
        ver = self.version_box.currentText()
        if not ver:
            InfoBar.info("未选择版本", "请先安装并选择一个版本", parent=self,
                         position=InfoBarPosition.TOP, duration=2500)
            return
        dlg = VersionSetupDialog(self.backend, inst, ver, self)
        if dlg.exec():
            dlg.save()
            InfoBar.success("已保存", "版本设置已写入", parent=self,
                            position=InfoBarPosition.TOP, duration=2000)

    def _load_news(self):
        while self.news_host.count():
            item = self.news_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        mode = CONFIG.get("homepage_mode") or "news"
        if mode == "blank":
            self.news_card.setTitle("主页")
            self.news_host.addWidget(CaptionLabel("主页已设为空白"))
            return
        if mode == "custom":
            from pathlib import Path
            self.news_card.setTitle("自定义主页")
            path = CONFIG.get("custom_homepage") or ""
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            p = Path(path) if path else None
            if p and p.is_file():
                if p.suffix.lower() in (".html", ".htm"):
                    browser.setSource(QUrl.fromLocalFile(str(p.resolve())))
                else:
                    browser.setPlainText(p.read_text(encoding="utf-8", errors="replace"))
            else:
                browser.setPlainText("未设置自定义主页。到设置 → 启动页主页 填写本地 HTML 路径。")
            self.news_host.addWidget(browser)
            return
        self.news_card.setTitle("Minecraft 新闻")
        cached = self.backend.cached_news()
        self._fill_news(cached)

        def ok(rows):
            if (CONFIG.get("homepage_mode") or "news") != "news":
                return
            while self.news_host.count():
                item = self.news_host.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._fill_news(rows or [])

        self.backend.call_async(self.backend.fetch_news, ok, lambda *_: None)

    def _fill_news(self, rows):
        if not rows:
            self.news_host.addWidget(CaptionLabel("暂无新闻"))
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
        cur_inst = self.instance_box.currentText()
        self.instance_box.blockSignals(True)
        self.instance_box.clear()
        names = [i["name"] for i in self.backend.get_instances()]
        self.instance_box.addItems(names)
        if cur_inst in names:
            self.instance_box.setCurrentText(cur_inst)
        elif CONFIG.get("default_instance") in names:
            self.instance_box.setCurrentText(CONFIG.get("default_instance"))
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

        self._reload_versions()
        self._reload_java_box()

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
            bits = [b for b in (pack_ver, f"Minecraft {pack_mc}" if pack_mc else "", f"实例 {instance}") if b]
            self.banner.set_info(pack_name, " · ".join(bits) or version)
        else:
            self.banner.set_info(version, f"实例 {instance} · 点击「启动游戏」进入世界")

    def _on_launch(self):
        self.log_edit.clear()
        self.progress.setValue(0)
        self.status_label.setText("准备启动…")
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
            instance=self.instance_box.currentText() or "default",
            version=self.version_box.currentText(),
            account=self.account_box.currentText(),
            username=self.username_edit.text().strip(),
            memory_mb=self.memory_slider.value(),
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            java=self._selected_java(),
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
            InfoBar.success("已复制", "启动命令已复制到剪贴板", parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=2500)
        except Exception as e:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("复制失败", str(e), parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=3500)

    def _login(self):
        if self._login_dlg:
            return
        self._login_dlg = DeviceCodeDialog(self.window())
        self._login_task_id = self.backend.start_microsoft_login()
        self._login_dlg.exec()
        self._login_dlg = None
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
        self.progress.setValue(min(100, max(0, int(current * 100 / total))) if total else 0)
        status, speed = (message or "").split("  |  ", 1) if "  |  " in (message or "") else (message, "")
        self.status_label.setText((status or "处理中…") + (f"    {speed}" if speed else ""))

    def _on_log(self, task_id, text):
        if task_id == self._task_id:
            self.log_edit.appendPlainText(text)

    def _on_crash(self, task_id, report):
        if task_id != self._task_id:
            return
        self._crash_shown = True
        win = self.window()
        CrashDialog(
            report or {}, win, backend=getattr(win, "backend", None)
        ).exec()

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
        self.status_label.setText(message)
        if success:
            self.progress.setValue(100)
            InfoBar.success("游戏已结束", message or "已正常退出", parent=self,
                             position=InfoBarPosition.TOP, duration=3000)
            return
        if self._crash_shown or message == "已取消":
            if message == "已取消":
                InfoBar.info("已停止", message, parent=self,
                             position=InfoBarPosition.TOP, duration=2500)
            return
        CrashDialog({
            "title": "启动失败",
            "headline": "启动中止",
            "detail": message or "启动失败",
            "help": "这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。",
        }, self.window()).exec()
