# -*- coding: utf-8 -*-
"""全局 Mod 列表与启禁。"""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, InfoBar, InfoBarPosition, MessageBoxBase, SubtitleLabel,
    SwitchButton, TransparentPushButton, FluentIcon as FIF,
)


class GlobalModsDialog(MessageBoxBase):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.viewLayout.addWidget(SubtitleLabel("全局 Mod", self))
        self.viewLayout.addWidget(BodyLabel("启用的 jar 会在每次启动前链到当前版本的 mods。", self))
        self.host = QVBoxLayout()
        wrap = QWidget(self)
        wrap.setLayout(self.host)
        self.viewLayout.addWidget(wrap)
        open_btn = TransparentPushButton(FIF.FOLDER, "打开文件夹")
        open_btn.clicked.connect(backend.open_global_mods)
        self.viewLayout.addWidget(open_btn)
        self.yesButton.setText("关闭")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(480)
        self.reload()

    def reload(self):
        while self.host.count():
            it = self.host.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = self.backend.list_global_mods() or []
        if not rows:
            self.host.addWidget(BodyLabel("还没有全局模组，点「打开文件夹」放入 jar。"))
            return
        for row in rows:
            bar = QHBoxLayout()
            name = row.get("filename") or "?"
            bar.addWidget(QLabel(name), 1)
            sw = SwitchButton()
            sw.setChecked(bool(row.get("enabled")))
            sw.checkedChanged.connect(lambda on, n=name: self._toggle(n, on, sw))
            wrap = QWidget()
            wrap.setLayout(bar)
            bar.addWidget(sw)
            self.host.addWidget(wrap)

    def _toggle(self, filename, enabled, switch=None):
        try:
            self.backend.set_global_mod_enabled(filename, enabled)
        except Exception as e:
            if switch is not None:
                switch.blockSignals(True)
                switch.setChecked(not enabled)
                switch.blockSignals(False)
            InfoBar.error("切换失败", str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
