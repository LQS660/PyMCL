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
        root.addWidget(iso_group)

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
        InfoBar.success("已保存", "设置已写入 config.json", parent=self,
                        position=InfoBarPosition.TOP, duration=2500)

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
        }
