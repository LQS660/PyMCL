# -*- coding: utf-8 -*-
"""设置页：WinUI 风格设置卡片组。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton, ScrollArea, SettingCard,
    SettingCardGroup, SpinBox, SubtitleLabel, SwitchButton,
)


def _spin_card(icon, title, desc, lo, hi, value):
    card = SettingCard(icon, title, desc)
    spin = SpinBox(card)
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setFixedWidth(120)
    card.hBoxLayout.addWidget(spin, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(16)
    return card, spin


def _switch_card(icon, title, desc, checked=False):
    card = SettingCard(icon, title, desc)
    switch = SwitchButton(card)
    switch.setChecked(checked)
    card.hBoxLayout.addWidget(switch, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(16)
    return card, switch


def _combo_card(icon, title, desc, items, current):
    card = SettingCard(icon, title, desc)
    box = ComboBox(card)
    box.addItems(items)
    if current in items:
        box.setCurrentText(current)
    box.setFixedWidth(260)
    card.hBoxLayout.addWidget(box, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(16)
    return card, box


def _line_card(icon, title, desc, password=False, placeholder=""):
    card = SettingCard(icon, title, desc)
    edit = PasswordLineEdit(card) if password else LineEdit(card)
    edit.setPlaceholderText(placeholder)
    edit.setFixedWidth(280)
    card.hBoxLayout.addWidget(edit, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(16)
    return card, edit


class SettingsPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.backend = backend
        settings = backend.get_settings()

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root.addWidget(SubtitleLabel("设置"))

        iso_group = SettingCardGroup("版本隔离与存储", host)
        self.share_libs_card, self.share_libs = _switch_card(
            FIF.LIBRARY, "共享 libraries",
            "所有实例共享依赖库（节省空间，但会降低隔离性）",
            checked=settings["share_libraries"])
        self.share_assets_card, self.share_assets = _switch_card(
            FIF.PHOTO, "共享 assets 资源",
            "所有实例共享资源文件（节省空间，但会降低隔离性）",
            checked=settings["share_assets"])
        iso_group.addSettingCard(self.share_libs_card)
        iso_group.addSettingCard(self.share_assets_card)
        iso_map = {
            "none": "关闭（共用实例目录）",
            "saves": "隔离存档",
            "all": "隔离全部",
        }
        self._iso_keys = {v: k for k, v in iso_map.items()}
        self.iso_card, self.iso_box = _combo_card(
            FIF.FOLDER, "新版本默认隔离",
            "安装新版本时写入该版本的隔离模式，可稍后在版本设置改",
            list(iso_map.values()),
            iso_map.get(settings.get("default_isolation") or "none", iso_map["none"]))
        iso_group.addSettingCard(self.iso_card)
        root.addWidget(iso_group)

        ui_group = SettingCardGroup("界面", host)
        self.fly_card, self.fly_sw = _switch_card(
            FIF.SYNC,
            "下载飞入动画",
            "点击安装时，图标抛物线飞入侧栏「下载任务」",
            checked=bool(settings.get("ui_fly_animation", True)))
        ui_group.addSettingCard(self.fly_card)
        self.dark_card, self.dark_sw = _switch_card(
            FIF.BRIGHTNESS, "深色模式", "立即生效，接近 PCL 夜间主题",
            checked=bool(settings.get("ui_dark")))
        self.color_card, self.color_edit = _line_card(
            FIF.PALETTE if hasattr(FIF, "PALETTE") else FIF.EDIT,
            "主题色", "例如 #2E9B6B")
        self.color_edit.setText(settings.get("theme_color") or "#2E9B6B")
        self.bg_card, self.bg_edit = _line_card(
            FIF.PHOTO, "背景图", "本地图片路径，留空为纯色")
        self.bg_edit.setText(settings.get("ui_background") or "")
        ui_group.addSettingCard(self.dark_card)
        ui_group.addSettingCard(self.color_card)
        ui_group.addSettingCard(self.bg_card)
        root.addWidget(ui_group)

        perf_group = SettingCardGroup("下载与性能", host)
        self.threads_card, self.threads_spin = _spin_card(
            FIF.SYNC, "下载并发线程数", "同时下载的文件数量",
            1, 64, settings["download_threads"])
        self.memory_card, self.memory_spin = _spin_card(
            FIF.DEVELOPER_TOOLS, "默认内存 (MB)", "新实例的默认 JVM 内存",
            512, 32768, settings["default_memory_mb"])
        src_map = {"auto": "自动（官方>4秒改 BMCLAPI）", "official": "仅官方", "bmclapi": "仅 BMCLAPI"}
        comm_map = {"auto": "自动", "official": "仅官方", "mcim": "仅 MCIM"}
        self._src_keys = {v: k for k, v in src_map.items()}
        self._comm_keys = {v: k for k, v in comm_map.items()}
        self.src_card, self.src_box = _combo_card(
            FIF.CLOUD_DOWNLOAD, "文件下载源",
            "和 PCL 一样：自动测速，官方慢于 4 秒就改走 BMCLAPI",
            list(src_map.values()), src_map.get(settings.get("download_source") or "auto", src_map["auto"]))
        self.comm_card, self.comm_box = _combo_card(
            FIF.LIBRARY, "社区资源源",
            "模组 / 整合包：MCIM 国内镜像，挂了可改官方",
            list(comm_map.values()), comm_map.get(settings.get("community_source") or "auto", comm_map["auto"]))
        self.proxy_card, self.proxy_sw = _switch_card(
            FIF.VPN, "跟随系统代理",
            "默认开。Clash 7897 会生效；关掉才强制直连",
            checked=bool(settings.get("use_system_proxy", True)))
        perf_group.addSettingCard(self.threads_card)
        perf_group.addSettingCard(self.src_card)
        perf_group.addSettingCard(self.comm_card)
        perf_group.addSettingCard(self.proxy_card)
        perf_group.addSettingCard(self.memory_card)

        self.jvm_card, self.jvm_edit = _line_card(
            FIF.DEVELOPER_TOOLS, "默认 JVM 参数", "所有版本都会带上，版本设置可再追加")
        self.jvm_edit.setText(settings.get("default_jvm_args") or "")
        perf_group.addSettingCard(self.jvm_card)

        res_card = SettingCard(FIF.VIEW, "默认分辨率", "游戏窗口的默认宽高")
        res_row = QHBoxLayout()
        self.width_spin = SpinBox(res_card)
        self.width_spin.setRange(320, 7680)
        self.width_spin.setValue(settings["default_resolution"][0])
        self.height_spin = SpinBox(res_card)
        self.height_spin.setRange(240, 4320)
        self.height_spin.setValue(settings["default_resolution"][1])
        res_row.addWidget(self.width_spin)
        res_row.addWidget(BodyLabel("×"))
        res_row.addWidget(self.height_spin)
        res_card.hBoxLayout.addLayout(res_row)
        res_card.hBoxLayout.addSpacing(16)
        perf_group.addSettingCard(res_card)
        root.addWidget(perf_group)

        acc_group = SettingCardGroup("账号与下载源", host)
        self.ms_card, self.ms_client_edit = _line_card(
            FIF.PEOPLE, "微软 OAuth 客户端 ID", "一般无需修改")
        self.ms_client_edit.setText(settings["ms_client_id"])
        self.curse_card, self.curse_key_edit = _line_card(
            FIF.VPN, "CurseForge API 密钥",
            "可选；仅在国内镜像不可用时用于搜索兜底", password=True)
        self.curse_key_edit.setText(settings["curseforge_api_key"])
        acc_group.addSettingCard(self.ms_card)
        acc_group.addSettingCard(self.curse_card)
        root.addWidget(acc_group)

        maint_group = SettingCardGroup("维护", host)
        self.upd_card, self.upd_url = _line_card(
            FIF.UPDATE if hasattr(FIF, "UPDATE") else FIF.SYNC,
            "更新清单 URL", "JSON：version / url / notes")
        self.upd_url.setText(settings.get("update_url") or "")
        maint_group.addSettingCard(self.upd_card)
        tool_card = SettingCard(FIF.DEVELOPER_TOOLS, "维护工具", "更新、清理、导出、全局 Mod")
        self.chk_upd = PrimaryPushButton("检查更新")
        self.clean_btn = PushButton("清理")
        self.export_btn = PushButton("导出实例")
        self.global_btn = PushButton("全局 Mod")
        for b in (self.chk_upd, self.clean_btn, self.export_btn, self.global_btn):
            tool_card.hBoxLayout.addWidget(b, 0, Qt.AlignRight)
        tool_card.hBoxLayout.addSpacing(8)
        maint_group.addSettingCard(tool_card)
        root.addWidget(maint_group)
        self.chk_upd.clicked.connect(self._check_update)
        self.clean_btn.clicked.connect(self._clean)
        self.export_btn.clicked.connect(self._export)
        self.global_btn.clicked.connect(self.backend.open_global_mods)

        ai_group = SettingCardGroup("AI 助手", host)
        mode_card = SettingCard(getattr(FIF, "CHAT", None) or FIF.HELP, "接入方式", "公益接口已内置，小白不用填密钥")
        self.ai_mode = ComboBox(mode_card)
        self.ai_mode.addItems(["公益接口", "自定义 NewAPI"])
        self.ai_mode.setCurrentText(
            "自定义 NewAPI" if settings.get("ai_mode") == "custom" else "公益接口")
        self.ai_mode.setFixedWidth(180)
        mode_card.hBoxLayout.addWidget(self.ai_mode, 0, Qt.AlignRight)
        mode_card.hBoxLayout.addSpacing(16)
        self.gw_card, self.ai_gateway = _line_card(
            FIF.CLOUD_DOWNLOAD, "自建网关（可选）", "一般留空，走内置公益接口")
        self.ai_gateway.setText(settings.get("ai_gateway_url") or "")
        self.base_card, self.ai_base = _line_card(
            FIF.VIEW, "NewAPI Base URL", "自定义模式：填到 /v1 为止")
        self.ai_base.setText(settings.get("ai_base_url") or "")
        self.key_card, self.ai_key = _line_card(
            FIF.VPN, "NewAPI 令牌", "只在自定义模式使用，不要用站长无限额令牌", password=True)
        self.ai_key.setText(settings.get("ai_api_key") or "")
        self.model_card, self.ai_model = _line_card(
            FIF.EDIT, "模型名", "公益模式锁定 deepseek-v4-flash；自定义才改得了")
        self.ai_model.setText(settings.get("ai_model") or "deepseek-v4-flash")
        ai_group.addSettingCard(mode_card)
        ai_group.addSettingCard(self.gw_card)
        ai_group.addSettingCard(self.base_card)
        ai_group.addSettingCard(self.key_card)
        ai_group.addSettingCard(self.model_card)
        root.addWidget(ai_group)
        self.ai_mode.currentTextChanged.connect(self._sync_ai_mode)
        self._sync_ai_mode()

        fb_group = SettingCardGroup("反馈与诊断", host)
        self.fb_consent_card, self.fb_consent = _switch_card(
            FIF.VPN, "允许上传诊断数据",
            "第一次打开会询问。未同意时不会上传反馈和电脑配置",
            checked=bool(settings.get("feedback_consent")))
        self.fb_url_card, self.fb_url = _line_card(
            FIF.CLOUD_DOWNLOAD, "反馈上报地址", "指向上报口，不要填看板端口")
        self.fb_url.setText(settings.get("feedback_url") or "")
        self.fb_hb_card, self.fb_hb = _switch_card(
            FIF.SYNC, "定时上报本机配置",
            "同意上传后，启动器打开时把电脑配置发到上报口",
            checked=bool(settings.get("feedback_heartbeat", True)))
        fb_group.addSettingCard(self.fb_consent_card)
        fb_group.addSettingCard(self.fb_url_card)
        fb_group.addSettingCard(self.fb_hb_card)
        root.addWidget(fb_group)

        row = QHBoxLayout()
        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存设置")
        self.save_btn.setFixedHeight(36)
        self.test_ai_btn = PushButton(FIF.SYNC, "测试 AI 连接")
        self.test_ai_btn.setFixedHeight(36)
        row.addWidget(self.save_btn)
        row.addWidget(self.test_ai_btn)
        row.addStretch(1)
        root.addLayout(row)
        root.addWidget(CaptionLabel(f"启动器主目录: {settings.get('root', '')}"))
        root.addStretch(1)

        self.save_btn.clicked.connect(self._save)
        self.test_ai_btn.clicked.connect(self._test_ai)

    def _sync_ai_mode(self, _text=""):
        custom = self.ai_mode.currentText() == "自定义 NewAPI"
        self.gw_card.setVisible(not custom)
        self.base_card.setVisible(custom)
        self.key_card.setVisible(custom)
        self.model_card.setVisible(custom)

    def _save(self):
        self.backend.save_settings(self.collect())
        from mclauncher import feedback as fb
        if self.fb_consent.isChecked():
            fb.set_consent(True)
            fb.start_heartbeat()
        else:
            fb.set_consent(False)
            fb.stop_heartbeat(send_offline=False)
        InfoBar.success("已保存", "设置已写入 config.json", parent=self,
                        position=InfoBarPosition.TOP, duration=2500)
        win = self.window()
        if hasattr(win, "apply_theme"):
            win.apply_theme()

    def _check_update(self):
        def ok(info):
            info = info or {}
            if info.get("has_update"):
                self.backend.start_self_update()
                InfoBar.success("发现更新", info.get("message") or "", parent=self,
                                position=InfoBarPosition.TOP, duration=4000)
            else:
                InfoBar.info("检查更新", info.get("message") or "已是最新", parent=self,
                             position=InfoBarPosition.TOP, duration=3000)

        def err(exc):
            InfoBar.error("检查失败", str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)

        self.backend.call_async(self.backend.check_update, ok, err)

    def _clean(self):
        info = self.backend.cleaner_preview()
        n = info.get("count") or 0
        from mclauncher.utils import format_size
        box_msg = f"将删除 {n} 个未引用库 / 残留 .part / 更新缓存，约 {format_size(info.get('bytes') or 0)}"
        from qfluentwidgets import MessageBox
        box = MessageBox("清理文件", box_msg, self)
        if not box.exec():
            return
        result = self.backend.cleaner_apply()
        InfoBar.success("清理完成", f"删除 {result.get('removed')} 个文件", parent=self,
                        position=InfoBarPosition.TOP, duration=3000)

    def _export(self):
        from mclauncher.config import CONFIG
        name = CONFIG.get("default_instance") or "default"
        self.backend.export_modpack(name)
        InfoBar.success("开始导出", f"实例 {name} → exports/", parent=self,
                        position=InfoBarPosition.TOP, duration=3000)

    def _test_ai(self):
        self.backend.save_settings(self.collect())
        self.test_ai_btn.setEnabled(False)
        self.test_ai_btn.setText("测试中…")

        def ok(msg):
            self.test_ai_btn.setEnabled(True)
            self.test_ai_btn.setText("测试 AI 连接")
            InfoBar.success("AI 连接成功", str(msg), parent=self,
                            position=InfoBarPosition.TOP, duration=4000)

        def err(exc):
            self.test_ai_btn.setEnabled(True)
            self.test_ai_btn.setText("测试 AI 连接")
            InfoBar.error("AI 连接失败", str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)

        self.backend.call_async(self.backend.test_ai_connection, ok, err)

    def collect(self) -> dict:
        return {
            "share_libraries": self.share_libs.isChecked(),
            "share_assets": self.share_assets.isChecked(),
            "download_threads": self.threads_spin.value(),
            "download_source": self._src_keys.get(self.src_box.currentText(), "auto"),
            "community_source": self._comm_keys.get(self.comm_box.currentText(), "auto"),
            "use_system_proxy": self.proxy_sw.isChecked(),
            "default_memory_mb": self.memory_spin.value(),
            "default_resolution": [self.width_spin.value(), self.height_spin.value()],
            "ms_client_id": self.ms_client_edit.text().strip(),
            "curseforge_api_key": self.curse_key_edit.text().strip(),
            "ai_mode": "custom" if self.ai_mode.currentText() == "自定义 NewAPI" else "public",
            "ai_gateway_url": self.ai_gateway.text().strip(),
            "ai_base_url": self.ai_base.text().strip(),
            "ai_api_key": self.ai_key.text().strip(),
            "ai_model": self.ai_model.text().strip() or "deepseek-v4-flash",
            "feedback_url": self.fb_url.text().strip(),
            "feedback_heartbeat": self.fb_hb.isChecked(),
            "feedback_consent": self.fb_consent.isChecked(),
            "ui_fly_animation": self.fly_sw.isChecked(),
            "ui_dark": self.dark_sw.isChecked(),
            "theme_color": self.color_edit.text().strip() or "#2E9B6B",
            "ui_background": self.bg_edit.text().strip(),
            "default_isolation": self._iso_keys.get(self.iso_box.currentText(), "none"),
            "default_jvm_args": self.jvm_edit.text().strip(),
            "update_url": self.upd_url.text().strip(),
        }
