# -*- coding: utf-8 -*-
"""Java 页：环境卡片 + 版本下载磁贴。"""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, PushButton, SimpleCardWidget,
    StrongBodyLabel, SubtitleLabel, TransparentPushButton,
)

from ..widgets import EmptyState, IconTile, Pill


class JavaCard(SimpleCardWidget):
    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        layout.addWidget(IconTile("J", "#E8862E", size=46))
        info_box = QVBoxLayout()
        info_box.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.addWidget(StrongBodyLabel(f'Java {info["major"]}'))
        title_row.addWidget(Pill("可用", "#2FA36B"))
        title_row.addStretch(1)
        info_box.addLayout(title_row)
        info_box.addWidget(CaptionLabel(info.get("path") or info.get("name") or ""))
        layout.addLayout(info_box, 1)


class JavaDownloadTile(SimpleCardWidget):
    def __init__(self, major: str, note: str, on_download, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 128)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        title = StrongBodyLabel(f"Java {major}")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addWidget(CaptionLabel(note))
        layout.addStretch(1)
        btn = PushButton(FIF.DOWNLOAD, "下载")
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda: on_download(major, self))
        layout.addWidget(btn)


class JavaPage(QWidget):
    NOTES = {
        "8": "1.16 及以下旧版本",
        "11": "部分旧模组环境",
        "17": "1.18 – 1.20.4 推荐",
        "21": "1.20.5+ 新版本",
    }

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("javaPage")
        self.backend = backend

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(SubtitleLabel("Java"))
        title_box.addWidget(CaptionLabel("Minecraft 所需 Java 会在启动时自动匹配下载；也可在实例页为每个实例单独指定"))
        head.addLayout(title_box, 1)
        self.refresh_btn = TransparentPushButton(FIF.SYNC, "重新检测")
        head.addWidget(self.refresh_btn, 0)
        root.addLayout(head)

        root.addWidget(StrongBodyLabel("本机环境"))
        self.env_layout = QVBoxLayout()
        self.env_layout.setSpacing(10)
        root.addLayout(self.env_layout)

        root.addSpacing(6)
        root.addWidget(StrongBodyLabel("下载新运行时"))
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        for major in ("8", "11", "17", "21"):
            tiles.addWidget(JavaDownloadTile(major, self.NOTES[major], self._download))
        tiles.addStretch(1)
        root.addLayout(tiles)
        root.addStretch(1)

        self.refresh_btn.clicked.connect(lambda: self.reload(scan_system=True))
        self.reload(scan_system=False)

    def reload(self, scan_system: bool = False):
        local = self.backend.get_java_list(scan_system=False)
        self._fill(local)
        if not scan_system:
            return
        call_async = getattr(self.backend, "call_async", None)
        if callable(call_async):
            call_async(lambda: self.backend.get_java_list(True), self._fill)
            return
        self._fill(self.backend.get_java_list(scan_system=True))

    def _fill(self, javas):
        while self.env_layout.count():
            item = self.env_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        javas = list(javas or [])
        if not javas:
            self.env_layout.addWidget(EmptyState(FIF.CODE, "未检测到 Java，请从下方下载"))
            return
        for j in javas:
            self.env_layout.addWidget(JavaCard(j))

    def _download(self, major: str, source=None):
        win = self.window()
        if source is not None and hasattr(win, "fly_to_tasks"):
            win.fly_to_tasks(source, "J", "#E8862E")
        self.backend.download_java(major)
