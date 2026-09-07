# -*- coding: utf-8 -*-
"""首次运行向导：游戏目录 / 下载源 / 内存 / 隔离。"""
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, LineEdit, MessageBoxBase, SpinBox, SubtitleLabel

from mclauncher.config import CONFIG


class FirstRunDialog(MessageBoxBase):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.viewLayout.addWidget(SubtitleLabel("欢迎使用 PyMCL", self))
        hint = BodyLabel("先选好游戏目录和下载源。这些以后都能在设置里改。", self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        self.game_dir = LineEdit()
        self.game_dir.setText(str(backend.get_settings().get("game_dir") or CONFIG.instances_dir))
        row = QHBoxLayout()
        row.addWidget(self.game_dir, 1)
        from qfluentwidgets import PushButton
        browse = PushButton("浏览")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        host = QWidget(self)
        host.setLayout(row)
        self.viewLayout.addWidget(BodyLabel("游戏 / 实例目录", self))
        self.viewLayout.addWidget(host)

        self.src = ComboBox()
        self.src.addItems(["自动（官方慢则 BMCLAPI）", "仅官方", "仅 BMCLAPI"])
        self.viewLayout.addWidget(BodyLabel("文件下载源", self))
        self.viewLayout.addWidget(self.src)

        self.memory = SpinBox()
        self.memory.setRange(512, 32768)
        self.memory.setValue(int(CONFIG.get("memory_mb") or 4096))
        self.viewLayout.addWidget(BodyLabel("默认内存 (MB)", self))
        self.viewLayout.addWidget(self.memory)

        self.iso = ComboBox()
        self.iso.addItems(["关闭（共用实例目录）", "隔离存档", "隔离 Mod 与配置", "隔离全部"])
        self.viewLayout.addWidget(BodyLabel("新版本默认隔离", self))
        self.viewLayout.addWidget(self.iso)

        self.yesButton.setText("开始使用")
        self.cancelButton.setText("以后再说")
        self.widget.setMinimumWidth(480)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "选择游戏目录", self.game_dir.text())
        if path:
            self.game_dir.setText(path)

    def apply(self):
        src = {"自动（官方慢则 BMCLAPI）": "auto", "仅官方": "official", "仅 BMCLAPI": "bmclapi"}
        iso = {
            "关闭（共用实例目录）": "none",
            "隔离存档": "saves",
            "隔离 Mod 与配置": "mods",
            "隔离全部": "all",
        }
        data = self.backend.get_settings()
        data.update({
            "download_source": src.get(self.src.currentText(), "auto"),
            "default_memory_mb": self.memory.value(),
            "default_isolation": iso.get(self.iso.currentText(), "none"),
            "first_run": False,
        })
        self.backend.save_settings(data)
        path = self.game_dir.text().strip()
        if path:
            try:
                self.backend.set_game_dir(path)
            except Exception:
                pass
