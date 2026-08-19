# -*- coding: utf-8 -*-
"""下载任务中心：进度、速度、可展开日志；侧栏红点计数。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, PlainTextEdit, ProgressBar, ScrollArea,
    SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TransparentToolButton,
)

from ..widgets import EmptyState, IconTile

_TASK_ICONS = [
    ("安装游戏", FIF.GAME, "#4C8BF5"),
    ("安装整合包", FIF.FOLDER, "#7C5CD6"),
    ("安装模组", FIF.TAG, "#2FA36B"),
    ("安装光影", FIF.BRIGHTNESS, "#E8862E"),
    ("安装资源包", FIF.PHOTO, "#2E9FB8"),
    ("下载 Java", FIF.CODE, "#D95568"),
    ("启动游戏", FIF.PLAY, "#D95568"),
    ("微软登录", FIF.PEOPLE, "#8A6FBD"),
]


def _icon_for(title: str):
    for prefix, icon, color in _TASK_ICONS:
        if title.startswith(prefix):
            return icon, color
    return FIF.DOWNLOAD, "#4C8BF5"


def split_progress_message(message: str):
    text = message or ""
    if "  |  " in text:
        status, speed = text.split("  |  ", 1)
        return status.strip(), speed.strip()
    return text, ""


class TaskCard(SimpleCardWidget):
    def __init__(self, task_id: str, title: str, backend, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.backend = backend
        self._expanded = "整合包" in (title or "")
        self.setMinimumHeight(96)

        icon, color = _icon_for(title)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(IconTile(title.replace("安装", "").replace("下载", "").strip() or "T",
                               color, size=46))

        body = QVBoxLayout()
        body.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(title), 1)
        self.toggle_btn = TransparentToolButton(
            FIF.CARE_UP_SOLID if self._expanded else FIF.CARE_DOWN_SOLID)
        self.toggle_btn.setToolTip("收起日志" if self._expanded else "显示日志")
        self.cancel_btn = TransparentToolButton(FIF.CLOSE)
        self.cancel_btn.setToolTip("取消任务")
        top.addWidget(self.toggle_btn)
        top.addWidget(self.cancel_btn)
        body.addLayout(top)
        self.progress = ProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        body.addWidget(self.progress)
        status_row = QHBoxLayout()
        self.status = CaptionLabel("排队中…")
        self.speed = CaptionLabel("")
        self.speed.setAlignment(Qt.AlignRight)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.speed, 0)
        body.addLayout(status_row)
        row.addLayout(body, 1)
        root.addLayout(row)

        self.log_edit = PlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("安装过程的详细日志会显示在这里")
        self.log_edit.setFixedHeight(240)
        self.log_edit.setMaximumBlockCount(2500)
        self.log_edit.setVisible(self._expanded)
        root.addWidget(self.log_edit)

        self.toggle_btn.clicked.connect(self._toggle_log)
        self.cancel_btn.clicked.connect(self._cancel)

    def _toggle_log(self):
        self._expanded = not self._expanded
        self.log_edit.setVisible(self._expanded)
        self.toggle_btn.setIcon(FIF.CARE_UP_SOLID if self._expanded else FIF.CARE_DOWN_SOLID)
        self.toggle_btn.setToolTip("收起日志" if self._expanded else "显示日志")

    def _cancel(self):
        self.backend.cancel_task(self.task_id)
        self.status.setText("正在取消…")
        self.cancel_btn.setEnabled(False)

    def set_progress(self, current: int, total: int, message: str):
        if total > 0:
            self.progress.setValue(min(100, max(0, int(current * 100 / total))))
        status, speed = split_progress_message(message)
        self.status.setText(status or "处理中…")
        self.speed.setText(speed)

    def append_log(self, text: str):
        if not text:
            return
        self.log_edit.appendPlainText(text)

    def set_finished(self, success: bool, message: str):
        self.cancel_btn.setEnabled(False)
        if success:
            self.progress.setValue(100)
            self.status.setText(f"✔ {message}")
        else:
            self.status.setText(f"✘ {message}")
        self.speed.setText("")
        if message:
            self.log_edit.appendPlainText(message)
        if not success and not self._expanded:
            self._toggle_log()


class DownloadDock(SimpleCardWidget):
    """任意页面底部的下载条：速度 + 倒三角展开日志。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._expanded = False
        self._active: dict[str, str] = {}
        self._current = None
        self.setFixedWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.title = StrongBodyLabel("下载任务")
        self.status = CaptionLabel("就绪")
        self.speed = CaptionLabel("")
        self.toggle_btn = TransparentToolButton(FIF.CARE_DOWN_SOLID)
        self.toggle_btn.setToolTip("显示日志")
        bar.addWidget(self.title)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.speed)
        bar.addWidget(self.toggle_btn)
        root.addLayout(bar)

        self.progress = ProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.log_edit = PlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("安装过程的详细日志会显示在这里")
        self.log_edit.setFixedHeight(220)
        self.log_edit.setMaximumBlockCount(2500)
        self.log_edit.hide()
        root.addWidget(self.log_edit)

        self.toggle_btn.clicked.connect(self._toggle)
        backend.task_added.connect(self._add)
        backend.progress.connect(self._progress)
        backend.log.connect(self._log)
        backend.finished.connect(self._finished)
        self.hide()

    def _toggle(self):
        self._expanded = not self._expanded
        self.log_edit.setVisible(self._expanded)
        self.toggle_btn.setIcon(FIF.CARE_UP_SOLID if self._expanded else FIF.CARE_DOWN_SOLID)
        self.toggle_btn.setToolTip("收起日志" if self._expanded else "显示日志")
        self.adjustSize()
        parent = self.parent()
        if parent and hasattr(parent, "_place_download_dock"):
            parent._place_download_dock()

    def _add(self, task_id, title):
        self._active[task_id] = title
        self._current = task_id
        n = len(self._active)
        self.title.setText(f"下载任务（{n}）")
        self.status.setText(title)
        self.progress.setValue(0)
        self.speed.setText("")
        if n == 1:
            self.log_edit.clear()
        self.log_edit.appendPlainText(f"—— {title} ——")
        if "整合包" in (title or "") and not self._expanded:
            self._toggle()
        parent = self.parent()
        if parent and hasattr(parent, "_place_download_dock"):
            parent._place_download_dock()
        else:
            self.show()
            self.raise_()

    def _progress(self, task_id, current, total, message):
        if task_id not in self._active:
            return
        self._current = task_id
        if total > 0:
            self.progress.setValue(min(100, max(0, int(current * 100 / total))))
        status, speed = split_progress_message(message)
        title = self._active.get(task_id, "")
        n = len(self._active)
        self.title.setText(f"下载任务（{n}）")
        self.status.setText(status or title or "处理中…")
        self.speed.setText(speed)

    def _log(self, task_id, text):
        if task_id not in self._active and self._current != task_id:
            return
        if text:
            self.log_edit.appendPlainText(text)

    def _finished(self, task_id, success, message):
        self._active.pop(task_id, None)
        n = len(self._active)
        if message:
            self.log_edit.appendPlainText(message)
        if n <= 0:
            self.title.setText("下载任务")
            self.status.setText("✔ 全部完成" if success else (message or "已结束"))
            self.speed.setText("")
            self.progress.setValue(100 if success else self.progress.value())
            self.hide()
            return
        self.title.setText(f"下载任务（{n}）")
        self._current = next(iter(self._active))
        self.status.setText(self._active[self._current])


class TasksPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("tasksPage")
        self.backend = backend
        self._cards: dict[str, TaskCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)
        head = QVBoxLayout()
        head.addWidget(SubtitleLabel("下载任务"))
        head.addWidget(CaptionLabel("下载板块内所有安装任务的实时进度；整合包安装会自动展开详细日志"))
        root.addLayout(head)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(10)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        self.empty = EmptyState(FIF.DOWNLOAD, "暂无任务 —— 去下载板块里的版本 / 整合包 / 模组 / 光影 / 资源包 / Java 发起")
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)

        backend.task_added.connect(self._add)
        backend.progress.connect(self._progress)
        backend.log.connect(self._log)
        backend.finished.connect(self._finished)

    def _add(self, task_id, title):
        self.empty.hide()
        card = TaskCard(task_id, title, self.backend)
        self._cards[task_id] = card
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def _progress(self, task_id, current, total, message):
        card = self._cards.get(task_id)
        if card:
            card.set_progress(current, total, message)

    def _log(self, task_id, text):
        card = self._cards.get(task_id)
        if card:
            card.append_log(text)

    def _finished(self, task_id, success, message):
        card = self._cards.get(task_id)
        if card:
            card.set_finished(success, message)
