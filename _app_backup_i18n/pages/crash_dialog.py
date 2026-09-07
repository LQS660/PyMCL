# -*- coding: utf-8 -*-
"""PCL 同款：Minecraft 崩溃 / 启动器未捕获异常弹窗。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel, InfoBar, InfoBarPosition, PlainTextEdit, PrimaryPushButton, PushButton, SubtitleLabel

from mclauncher.crash import HELP_FOOTER, export_report, open_path


class CrashDialog(QDialog):
    def __init__(self, report: dict | None = None, parent=None, *,
                 title: str = "", detail: str = "", backend=None):
        super().__init__(parent)
        self.report = report or {}
        self.backend = backend or getattr(parent, "backend", None)
        self.setWindowTitle(title or self.report.get("title") or "Minecraft 出现错误")
        self.setMinimumSize(560, 420)
        self.resize(620, 480)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)

        head = SubtitleLabel(self.windowTitle(), self)
        root.addWidget(head)

        headline = self.report.get("headline") or ""
        if headline and headline != self.windowTitle():
            root.addWidget(BodyLabel(headline, self))

        body = PlainTextEdit(self)
        body.setReadOnly(True)
        text = (detail or self.report.get("detail") or "").strip()
        body.setPlainText(text)
        root.addWidget(body, 1)

        hint = CaptionLabel(self.report.get("help") or HELP_FOOTER, self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.ok_btn = PrimaryPushButton("确定", self)
        self.view_btn = PushButton("查看输出", self)
        self.export_btn = PushButton("导出错误报告", self)
        self.send_btn = PushButton("发送给开发者", self)
        self.ok_btn.clicked.connect(self.accept)
        self.view_btn.clicked.connect(self._view)
        self.export_btn.clicked.connect(self._export)
        self.send_btn.clicked.connect(self._send)
        has_file = bool(self.report.get("direct_file") or self.report.get("output_tail"))
        self.view_btn.setVisible(has_file)
        self.export_btn.setVisible(bool(self.report))
        btns.addWidget(self.view_btn)
        btns.addWidget(self.export_btn)
        btns.addWidget(self.send_btn)
        btns.addWidget(self.ok_btn)
        root.addLayout(btns)

    def _view(self):
        path = self.report.get("direct_file") or ""
        if path:
            open_path(path)
            return
        tail = self.report.get("output_tail") or self.report.get("detail") or ""
        if not tail:
            return
        from mclauncher import utils
        dest = utils.ROOT / "游戏崩溃前的输出.txt"
        try:
            dest.write_text(tail, encoding="utf-8")
            open_path(dest)
        except OSError:
            pass

    def _export(self):
        if not self.report:
            return
        try:
            path = export_report(self.report)
            open_path(path)
        except OSError:
            pass

    def _send(self):
        backend = self.backend or getattr(self.parent(), "backend", None)
        if backend is None:
            InfoBar.error("无法发送", "没有连接到启动器后端", parent=self,
                          position=InfoBarPosition.TOP, duration=3500)
            return
        from mclauncher import feedback as fb
        if not fb.has_consent():
            from ..widgets import prompt_feedback_consent
            parent = self.parent() or self
            win = getattr(parent, "window", lambda: parent)()
            if not prompt_feedback_consent(win or self):
                InfoBar.warning("未同意", "不同意上传则不会发送", parent=self,
                                position=InfoBarPosition.TOP, duration=3000)
                return
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中…")
        report = dict(self.report or {})

        def work():
            return backend.submit_crash_feedback(report)

        def ok(_data):
            self.send_btn.setText("已发送")
            InfoBar.success("已发给开发者", "反馈中心会实时显示这条崩溃和本机配置",
                            parent=self, position=InfoBarPosition.TOP, duration=3500)

        def err(exc):
            self.send_btn.setEnabled(True)
            self.send_btn.setText("发送给开发者")
            InfoBar.error("发送失败", str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)

        backend.call_async(work, ok, err)


def show_launcher_error(parent, kind: str, text: str, log_file: str = ""):
    title = "启动器出现错误" if kind != "thread" else "启动器后台线程出错"
    dlg = CrashDialog(
        {
            "title": title,
            "headline": "未捕获异常已写入日志",
            "detail": (text or "")[-8000:],
            "help": f"完整日志：{log_file}" if log_file else HELP_FOOTER,
            "direct_file": log_file,
            "files": [log_file] if log_file else [],
            "output_tail": text or "",
        },
        parent,
        title=title,
        backend=getattr(parent, "backend", None),
    )
    dlg.export_btn.setVisible(False)
    dlg.exec()
