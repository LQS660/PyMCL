# -*- coding: utf-8 -*-
"""反馈页：提交问题并预览将附带的本机配置。"""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, ComboBox, FluentIcon as FIF, InfoBar,
    InfoBarPosition, LineEdit, PlainTextEdit, PrimaryPushButton, PushButton,
    ScrollArea, SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TransparentPushButton,
)

from mclauncher.feedback_defaults import CATEGORIES
from mclauncher import feedback as fb_mod

_SEND_ICON = getattr(FIF, "SEND", None) or getattr(FIF, "MAIL", None) or FIF.HELP


class FeedbackPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("feedbackPage")
        self.backend = backend
        self._info = None

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        head = QVBoxLayout()
        head.addWidget(SubtitleLabel("反馈"))
        head.addWidget(CaptionLabel("发给开发者。第一次打开需手动同意后才会上传；可附带本机配置。"))
        root.addLayout(head)

        form = SimpleCardWidget(host)
        box = QVBoxLayout(form)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)

        row1 = QHBoxLayout()
        self._cat_keys = [k for k, _ in CATEGORIES]
        self.cat = ComboBox(form)
        self.cat.addItems([label for _, label in CATEGORIES])
        self.cat.setFixedWidth(160)
        self.contact = LineEdit(form)
        self.contact.setPlaceholderText("联系方式（QQ / 邮箱，可选）")
        row1.addWidget(self.cat, 0)
        row1.addWidget(self.contact, 1)
        box.addLayout(row1)

        self.title_edit = LineEdit(form)
        self.title_edit.setPlaceholderText("标题，例如：1.20.1 Fabric 启动黑屏")
        box.addWidget(self.title_edit)

        self.body = PlainTextEdit(form)
        self.body.setPlaceholderText("发生了什么、怎么复现、期望结果。崩溃可直接从崩溃窗口点「发送给开发者」。")
        self.body.setMinimumHeight(160)
        box.addWidget(self.body)

        opt = QHBoxLayout()
        self.attach = CheckBox("附带本机配置", form)
        self.attach.setChecked(True)
        self.send_btn = PrimaryPushButton(_SEND_ICON, "发送反馈")
        self.send_btn.setFixedHeight(36)
        opt.addWidget(self.attach)
        opt.addStretch(1)
        opt.addWidget(self.send_btn)
        box.addLayout(opt)
        root.addWidget(form)

        spec_head = QHBoxLayout()
        spec_head.addWidget(StrongBodyLabel("本机配置预览"))
        spec_head.addStretch(1)
        self.refresh_btn = TransparentPushButton(FIF.SYNC, "重新采集")
        spec_head.addWidget(self.refresh_btn)
        root.addLayout(spec_head)

        self.spec = PlainTextEdit(host)
        self.spec.setReadOnly(True)
        self.spec.setMinimumHeight(220)
        self.spec.setPlainText("正在采集本机配置…")
        root.addWidget(self.spec)

        root.addWidget(BodyLabel("最近提交"))
        self.hist = CaptionLabel("暂无")
        self.hist.setWordWrap(True)
        root.addWidget(self.hist)
        root.addStretch(1)

        self.send_btn.clicked.connect(self._send)
        self.refresh_btn.clicked.connect(lambda: self.reload(force=True))
        self._reload_history()

    def prefill(self, category="bug", title="", body=""):
        if category in self._cat_keys:
            self.cat.setCurrentIndex(self._cat_keys.index(category))
        if title:
            self.title_edit.setText(title)
        if body:
            self.body.setPlainText(body)

    def reload(self, force=False):
        self.spec.setPlainText("正在采集本机配置…")

        def work():
            return self.backend.collect_sysinfo(force=force, scan_system_java=force)

        def ok(info):
            self._info = info or {}
            self.spec.setPlainText(self.backend.sysinfo_text(info))
            self._reload_history()

        def err(exc):
            self.spec.setPlainText(f"采集失败：{exc}")

        self.backend.call_async(work, ok, err)

    def _reload_history(self):
        rows = self.backend.feedback_history()
        if not rows:
            self.hist.setText("暂无")
            return
        lines = []
        for row in rows[:8]:
            label = fb_mod.category_label(row.get("category") or "")
            lines.append(f"{label}  {row.get('title') or ''}  ({row.get('id') or ''})")
        self.hist.setText("\n".join(lines))

    def _send(self):
        title = self.title_edit.text().strip()
        body = self.body.toPlainText().strip()
        if not title and not body:
            InfoBar.warning("空内容", "请填写标题或描述", parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            return
        idx = max(0, self.cat.currentIndex())
        cat = self._cat_keys[idx] if idx < len(self._cat_keys) else "other"
        contact = self.contact.text().strip()
        attach = self.attach.isChecked()
        if not fb_mod.has_consent():
            from ..widgets import prompt_feedback_consent
            if not prompt_feedback_consent(self.window()):
                InfoBar.warning("未同意", "不同意上传则不会发送反馈", parent=self,
                                position=InfoBarPosition.TOP, duration=3000)
                return
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中…")

        def work():
            return self.backend.submit_feedback(
                category=cat, title=title, body=body, contact=contact,
                include_sysinfo=attach)

        def ok(data):
            self.send_btn.setEnabled(True)
            self.send_btn.setText("发送反馈")
            self.body.setPlainText("")
            self.title_edit.setText("")
            self._reload_history()
            fid = (data or {}).get("id") or ""
            InfoBar.success("已发送", f"开发者会实时看到这条反馈 {fid}".strip(),
                            parent=self, position=InfoBarPosition.TOP, duration=3500)

        def err(exc):
            self.send_btn.setEnabled(True)
            self.send_btn.setText("发送反馈")
            InfoBar.error("发送失败", str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)

        self.backend.call_async(work, ok, err)
