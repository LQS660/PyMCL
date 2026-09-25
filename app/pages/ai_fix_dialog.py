# -*- coding: utf-8 -*-
"""崩溃弹窗的「交给 AI 修复」小窗：把崩溃报告直接喂给 AI 助手诊断。

独立于 AI 助手主页（app/pages/ai_page.py）：内存会话、不落盘、不占主页面的
会话列表，检查点会话 id 固定为 ai_fix——主页面那套 store / 检查点不被踩。
气泡、工具行、确认卡、提问卡、agent 线程全部复用 ai_page 的组件，两端
（主页 / 小窗）行为一致；小窗只是砍掉多会话、重试、回退和用量展示。
"""

from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition, PrimaryPushButton,
    ScrollArea, SubtitleLabel,
)

from mclauncher.ai import store as chat_store
from mclauncher.ai.permission import Behavior, Rule, rule_content_from_input
from mclauncher.ai.preview import change_preview
from mclauncher.ai.result import AgentResult, StopReason
from mclauncher.ai.tools import TOOL_META
from mclauncher.i18n import tr
from ..lucide import IconLabel
from ..pcl_chrome import Theme, prestyle_page
from .ai_page import AgentThread, AskCard, Bubble, ChatInput, ConfirmCard, ToolLine

# 喂给模型的各类日志截断上限：够定位问题，又不至于把上下文塞爆
_CLIP = {"detail": 2500, "output_tail": 3500, "log_mc": 2500, "log_crash": 2500, "log_hs": 1200}


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[:n] + tr("…（已截断）")


def build_crash_context(report: dict | None, settings: dict | None = None) -> str:
    """把崩溃报告压成一段隐藏的系统提示注入文本（用户气泡里看不到）。

    三件事必须说清，否则模型会拿「截断摘录」当全部证据、甚至瞎猜接口没配：
    · 日志只是末尾摘录 → 带着工具，自己去读完整日志核实；
    · 当前走的是启动器内置接口（公益/自定义）→ 别声称「没有配置接口」；
    · 修复许可：能改配置 / 禁模组就直接动手（写操作仍会先弹确认）。
    """
    r = report or {}
    s = settings or {}
    rows = [tr("【启动器注入 · 对用户不可见】本次对话的崩溃上下文：")]

    ctx = []
    if r.get("instance"):
        ctx.append(tr("实例：{0}").format(r["instance"]))
    if r.get("version"):
        ctx.append(tr("版本：{0}").format(r["version"]))
    if r.get("exit_code") is not None and r.get("exit_code") != "":
        hint = tr("（{0}）").format(r["exit_hint"]) if r.get("exit_hint") else ""
        ctx.append(tr("退出码：{0}{1}").format(r["exit_code"], hint))
    if ctx:
        rows.append("\n".join(ctx))

    for key, label in (
        ("headline", tr("现象")),
        ("summary", tr("摘要")),
        ("detail", tr("详细信息")),
        ("output_tail", tr("游戏输出（末尾）")),
        ("log_mc", tr("latest.log（末尾）")),
        ("log_crash", tr("崩溃报告（末尾）")),
        ("log_hs", tr("JVM 日志（末尾）")),
    ):
        text = _clip(r.get(key) or "", _CLIP.get(key, 2000))
        if text:
            rows.append(f"{label}：\n{text}")

    if r.get("direct_file"):
        rows.append(tr("完整日志文件：{0}").format(r["direct_file"]))

    rows.append(tr(
        "日志自查提醒：上面的日志只是截断摘录。你带有读取日志和检查实例的工具"
        "（get_latest_log、get_crash_report、read_artifact、inspect_mod、list_mods 等），"
        "请主动调用工具读取完整日志核实原因，不要以「没有日志」「无法访问日志」为由拒绝分析。"))

    mode = s.get("ai_mode") or "public"
    if mode == "custom":
        iface = tr("自定义接口（{0}）").format(s.get("ai_model") or tr("未命名模型"))
    else:
        iface = tr("公益接口（免费网关）")
    rows.append(tr(
        "接口状态：当前对话通过启动器内置的{0}接入，接口正常可用。"
        "不要声称「没有配置接口 / 接口不可用」。").format(iface))

    rows.append(tr(
        "如果问题能通过改配置、禁用模组等方式修复，请直接动手（写操作会先征求我同意）；"
        "需要更多上下文就自己读日志文件。边查边说：有阶段性发现或换步骤时，先用一两句话"
        "告诉我，再继续调用工具。最后用一句话给我结论和下一步建议。"))
    return "\n\n".join(rows)


class AiFixDialog(QDialog):
    """游戏报错「交给 AI 修复」的小对话窗（非模态，打开即自动开跑）。"""

    def __init__(self, report: dict | None = None, parent=None, *,
                 backend=None, title: str = ""):
        super().__init__(parent)
        self.report = dict(report or {})
        self.backend = backend or getattr(parent, "backend", None)
        self.setWindowTitle(title or tr("AI 修复"))
        self.resize(500, 640)
        self.setMinimumSize(400, 460)
        self.setModal(False)
        # 关掉即销毁：回合已在 closeEvent 里取消，留着只会占内存
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        # 裸 QDialog 不吃 qfluentwidgets 的主题（同 CrashDialog 的坑）
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"AiFixDialog {{ background: {Theme.bg}; }}"
            f"AiFixDialog QLabel {{ color: {Theme.text}; background: transparent; }}"
        )

        self._history: list[dict] = []
        self._worker: AgentThread | None = None
        self._round_bubble: Bubble | None = None   # 当前轮次的气泡
        self._round_text = ""                      # 当前轮次已说的话
        self._stream = ""                          # 整回合累积
        self._queue: list[str] = []
        self._tool_lines: dict[str, ToolLine] = {}
        self._task_lines: dict[str, ToolLine] = {}
        self._ai_pending_tasks: dict[str, str] = {}
        self._pending_user: str | None = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(33)
        self._flush_timer.timeout.connect(self._flush_stream)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._do_scroll)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("sparkles", 18, Theme.green), 0, Qt.AlignVCenter)
        title = SubtitleLabel(tr("AI 修复"), self)
        head.addWidget(title)
        self.status = CaptionLabel("", self)
        self.status.setStyleSheet(f"color: {Theme.muted};")
        head.addWidget(self.status)
        head.addStretch(1)
        # 停止入口合并进右下的发送键（跑动中变形为「停止」），头部不再单设按钮
        root.addLayout(head)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        host = QWidget()
        self.chat = QVBoxLayout(host)
        self.chat.setContentsMargins(0, 0, 8, 0)
        self.chat.setSpacing(10)
        self.chat.addStretch(1)
        self.scroll.setWidget(host)
        self._host = host
        root.addWidget(self.scroll, 1)
        prestyle_page(self, self.scroll)

        input_box = QFrame()
        input_box.setObjectName("aiFixInputBox")
        row = QHBoxLayout(input_box)
        row.setContentsMargins(10, 8, 10, 8)
        self.input = ChatInput()
        self.input.setPlaceholderText(tr("补充崩溃前做了什么…  Enter 发送，Shift+Enter 换行"))
        self.send_btn = PrimaryPushButton(getattr(FIF, "SEND", FIF.PLAY), tr("发送"), self)
        self.send_btn.setFixedHeight(34)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        input_box.setStyleSheet(
            f"#aiFixInputBox {{ background: {Theme.card};"
            f" border: 1px solid {Theme.line}; border-radius: 10px; }}")
        root.addWidget(input_box)

        self.send_btn.clicked.connect(self._on_send_clicked)
        self.input.submitted.connect(self._send_text)
        self.input.textChanged.connect(self._sync_send_btn)
        self._sync_send_btn()
        if self.backend is not None:
            # backend 缺席时 _kick_off 会给出错误气泡；连接本身不能崩在构造期
            self.backend.progress.connect(self._on_task_progress)
            self.backend.finished.connect(self._on_task_finished)

        # 开窗即把崩溃报告喂给模型；singleShot 让窗口先画出来再等网络
        QTimer.singleShot(0, self, self._kick_off)

    # ---------- 开跑 ----------

    def _kick_off(self):
        if self.backend is None:
            self._add_bubble("error", tr("没有连接到启动器后端"))
            return
        self._refresh_status()
        # 用户气泡只放这句短问话；崩溃报告走隐藏系统提示（见 _send）
        self._send(tr("帮我看看游戏为什么闪退"))

    def _refresh_status(self):
        try:
            from mclauncher.ai.defaults import DEFAULT_MODEL
            s = self.backend.get_settings()
            mode = s.get("ai_mode") or "public"
            label = (tr("自定义 · {0}").format(s.get("ai_model") or DEFAULT_MODEL)
                     if mode == "custom" else tr("公益接口 · {0}").format(DEFAULT_MODEL))
        except Exception:  # noqa: BLE001
            label = ""
        self.status.setText(label)

    def _launch_prefs(self) -> dict:
        # 照 app/pages/ai_page.py::AiPage._launch_prefs 抄：agent 的启动类工具
        # 要拿当前实例 / 账号 / 内存这些偏好，直接复用那份实现（只用 self.window()）
        from .ai_page import AiPage
        return AiPage._launch_prefs(self)

    def _send_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if self.backend is None:
            self._add_bubble("error", tr("没有连接到启动器后端"))
            return
        if self._worker:
            self._queue.append(text)
            self.input.clear()
            self._add_bubble("user", text)
            InfoBar.info(tr("已插队"), tr("这句话会立刻交给正在运行的助手"),
                         parent=self, position=InfoBarPosition.TOP, duration=1800)
            return
        self.input.clear()
        self._send(text)

    def _drain_queue(self):
        out = []
        while self._queue:
            out.append(self._queue.pop(0))
        return out

    def _send(self, text: str, *, echo: bool = True):
        if self._worker:
            self._queue.append(text)
            if echo:
                self._add_bubble("user", text)
            return
        if echo:
            self._add_bubble("user", text)
        self._stream = ""
        self._tool_lines = {}
        self._task_lines = {}
        self._open_round()
        settings = dict(self.backend.get_settings() or {})
        # 独立检查点会话：跟主页面对话的快照互不覆盖
        settings["ai_session_id"] = "ai_fix"
        # 崩溃报告从隐藏系统提示注入（ai_extra_context → agent._system_messages），
        # 每次发送都带上：后续追问时上下文仍然在场；不入库、用户气泡里看不到
        settings["ai_extra_context"] = build_crash_context(self.report, settings)
        self.backend._ui_launch = self._launch_prefs()
        worker = AgentThread(
            self.backend, settings,
            chat_store.api_messages(self._history[-chat_store.MAX_MESSAGES:]), text,
            self, queue_fn=self._drain_queue)
        self._worker = worker
        worker.delta.connect(self._on_delta, Qt.QueuedConnection)
        worker.status.connect(self._on_status, Qt.QueuedConnection)
        worker.need_confirm.connect(self._on_confirm, Qt.QueuedConnection)
        worker.need_ask.connect(self._on_ask, Qt.QueuedConnection)
        worker.done.connect(self._on_done, Qt.QueuedConnection)
        worker.failed.connect(self._on_fail, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        self._pending_user = text
        self._busy(True)
        worker.start()

    # ---------- 流式渲染（照 ai_page 同名逻辑裁剪） ----------

    def _add_widget(self, w: QWidget):
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        mine = isinstance(w, Bubble) and w.role == "user"
        if mine:
            row.addStretch(1)
            row.addWidget(w, 0, Qt.AlignRight)
        else:
            row.addWidget(w, 0, Qt.AlignLeft)
            row.addStretch(1)
        self.chat.insertWidget(self.chat.count() - 1, wrap)
        self._scroll_bottom()
        return wrap

    def _add_bubble(self, role: str, text: str) -> Bubble:
        b = Bubble(role, text)
        self._add_widget(b)
        return b

    def _scroll_bottom(self):
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _do_scroll(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _open_round(self, placeholder: str | None = None):
        """开一个新的轮次气泡：模型在工具之间开口时自动分段。"""
        if self._round_bubble is not None:
            return
        self._round_text = ""
        self._round_bubble = self._add_bubble("assistant", "")
        self._round_bubble.set_placeholder(placeholder or tr("正在想…"))

    def _close_round(self):
        """把当前轮次已说的话定稿在它自己的气泡里。"""
        if self._round_bubble is None:
            return
        self._round_bubble.set_text(self._round_text, live=False)
        self._round_bubble = None
        self._round_text = ""

    def _flush_stream(self):
        if self._round_bubble:
            self._round_bubble.set_text(self._round_text or "…", live=True)
        self._scroll_bottom()

    def _busy(self, on: bool):
        # 按钮在「发送 / 停止」之间变形，状态统一由 _sync_send_btn 计算
        self._sync_send_btn()

    def _on_send_clicked(self):
        text = self.input.toPlainText().strip()
        if text:
            self._send_text(text)
            return
        if self._worker:
            self._stop()

    def _sync_send_btn(self):
        """单按钮变形：输入框有字（或空闲待输入）= 发送；在跑且输入框空 = 停止。

        跑动中点「发送」不新开回合，走既有 steering 队列插话。
        """
        text = self.input.toPlainText().strip()
        running_stop = self._worker is not None and not text
        if running_stop:
            self.send_btn.setText(tr("停止"))
            self.send_btn.setIcon(FIF.CLOSE)
        else:
            self.send_btn.setText(tr("发送"))
            self.send_btn.setIcon(getattr(FIF, "SEND", FIF.PLAY))
        self.send_btn.setEnabled(bool(text) or self._worker is not None)

    def _on_delta(self, piece: str):
        if not piece:
            return
        # 「说一段 → 干活 → 再说一段」：模型在工具之间开口时自动开新气泡
        self._stream += piece
        self._open_round()
        self._round_text += piece
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _on_status(self, kind: str, payload: dict):
        label = payload.get("label") or payload.get("name") or kind
        name = payload.get("name") or ""
        if kind == "checkpoint_warn":
            InfoBar.warning(tr("无法一键撤回"),
                            str(payload.get("message") or tr("检查点不可用，本轮改动无法一键撤回")),
                            parent=self, position=InfoBarPosition.TOP, duration=6000)
            return
        if kind == "model_fallback":
            InfoBar.warning(tr("已切换备用模型"),
                            tr("主模型连续失败，本回合改用 {model} 完成").format(
                                model=payload.get("model") or ""),
                            parent=self, position=InfoBarPosition.TOP, duration=6000)
            return
        if kind == "think":
            if not self._round_text:
                tip = tr("搜完了，正在整理…") if payload.get("after_tools") else tr("正在想…")
                self._open_round(tip)
            return
        if kind == "tool":
            if name == "ask_user":
                if not self._round_text:
                    self._open_round(tr("请在下面选一下"))
                return
            # 工具要开工了：这一轮说的话就地定稿，工具行插在它下面
            self._close_round()
            line = self._tool_lines.get(name)
            if line:
                line.set_text(tr("准备：") + label)
            else:
                line = ToolLine(tr("准备：") + label, tool=name)
                self._tool_lines[name] = line
                self._add_widget(line)
            line.set_state("prepare")
            return
        self._close_round()
        line = self._tool_lines.get(name)
        if kind == "tool_run":
            if line:
                line.set_text(tr("执行中：") + label)
            else:
                line = ToolLine(tr("执行中：") + label, tool=name)
                self._tool_lines[name] = line
                self._add_widget(line)
            line.set_state("run")
        elif kind == "tool_done":
            if line:
                line.set_text(tr("完成：") + label)
            else:
                line = ToolLine(tr("完成：") + label, tool=name)
                self._tool_lines[name] = line
                self._add_widget(line)
            line.set_state("done")
            tid = payload.get("task_id") or ""
            if not tid:
                raw = payload.get("result") or ""
                try:
                    data = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {}
                    tid = data.get("task_id") or ""
                except Exception:  # noqa: BLE001
                    tid = ""
            if tid and line:
                line.bind_task(tid)
                self._task_lines[tid] = line
        elif kind == "tool_skip":
            if line:
                line.set_text(tr("已跳过：") + label)
            else:
                line = ToolLine(tr("已跳过：") + label, tool=name)
                self._add_widget(line)
            line.set_state("skip")
        self._scroll_bottom()

    def _on_confirm(self, name: str, args: dict, label: str, reason: str = ""):
        # 确认卡落在最后一段话下面：先把手头这段话封口
        self._close_round()
        detail_lines: list[str] = []
        try:
            pv = change_preview(self.backend, name, args or {})
        except Exception:  # noqa: BLE001
            pv = None
        if pv:
            if pv.get("head"):
                detail_lines.append(str(pv["head"]))
            detail_lines += [str(x) for x in (pv.get("lines") or [])]
        if name == "delete_instance" and not pv:
            detail_lines.append(tr("删掉后文件找不回来。"))
        if reason:
            detail_lines.append(str(reason))
        detail = "\n".join(x for x in detail_lines if x).strip()
        card = ConfirmCard(label, detail, name=name, args=args)
        meta = TOOL_META.get(name)
        if meta is None or getattr(meta, "side_effect", "") == "delete":
            for w in (card.always_btn, card.hint, card.scope_inst, card.scope_all):
                w.setVisible(False)
        worker = self._worker

        def yes():
            if worker:
                worker.answer_confirm(True)

        def always(scope: str):
            if worker:
                worker.answer_confirm(Rule(
                    name, rule_content_from_input(args or {}), Behavior.ALLOW, scope=scope))

        def no():
            if worker:
                worker.answer_confirm(False)

        card.accepted.connect(yes)
        card.always.connect(always)
        card.rejected.connect(no)
        self._add_widget(card)

    def _on_ask(self, questions: list, title: str):
        # 提问卡落在最后一段话下面：先把手头这段话封口
        self._close_round()
        card = AskCard(questions, title)
        worker = self._worker

        def ok(payload):
            if worker:
                worker.answer_ask(payload)

        def skip():
            card.setEnabled(False)
            if worker:
                worker.answer_ask(None)

        card.submitted.connect(ok)
        card.cancelled.connect(skip)
        self._add_widget(card)
        if not self._round_text:
            self._open_round(tr("请在下面选一下"))

    # ---------- 收尾 ----------

    @staticmethod
    def _stop_note(result) -> str:
        reason = getattr(result, "stop_reason", None)
        if reason is None or reason == StopReason.COMPLETED:
            return ""
        detail = (getattr(result, "detail", "") or "").strip()
        notes = {
            StopReason.NO_TOOL_CALL: tr("它没有真的开始执行：模型只回了文字，没有调用任何工具。"),
            StopReason.MAX_ROUNDS: tr("步骤太多，先停在这里。你可以让我继续。"),
            StopReason.PENDING_TASK: tr("下载/安装还在后台跑，完成后助手会回来汇报。"),
            StopReason.STREAM_FAILED: tr("接口这轮没有返回内容，已停止。"),
            StopReason.EMPTY_RESPONSE: tr("接口返回了空回复。"),
        }
        note = notes.get(reason)
        if not note:
            return ""
        if detail and detail not in note:
            note += "（" + detail + "）"
        return tr("（提示：") + note + tr("）")

    def _finish(self, assistant_text: str, ok: bool, result=None):
        self._flush_timer.stop()
        # 工具调用已经在对话流的工具行里逐条展示，不再往气泡尾巴上
        # 拼「（本轮：执行 …；…）」汇总（重复信息，还把正文顶得老长）
        shown = (assistant_text if ok else (assistant_text or tr("已停止"))).strip()
        note = self._stop_note(result) if (ok and result is not None) else ""
        # 轮次气泡收尾：失败/停止把原因写在最后一轮的气泡上；完成时把「为什么停」
        # 的增量补进最后一段（前面各轮已在各自工具事件处定稿）
        if not ok and self._round_bubble:
            self._round_bubble.set_text(shown or tr("已停止"))
        elif note:
            if self._round_bubble:
                self._round_text = (self._round_text + "\n\n" + note).strip()
            else:
                self._round_text = note
                self._open_round()
            self._round_bubble.set_text(self._round_text, live=False)
        self._close_round()
        self._round_bubble = None
        self._round_text = ""
        user = self._pending_user
        if user:
            # 只留在内存里：小窗是临时会话，不写 chat_store（主页面还开着时
            # 两个进程外写入会互相覆盖），关窗即结束
            turn_msgs = getattr(result, "turn_messages", None) or []
            # 压缩摘要（id=compact_*）插在用户这句之前：小窗里多轮追问也能吃到
            for m in turn_msgs:
                if isinstance(m, dict) and m.get("role") == "user" \
                        and str(m.get("id") or "").startswith("compact_"):
                    self._history.append(dict(m))
            self._history.append({"role": "user", "content": user})
            for m in turn_msgs:
                role = m.get("role") if isinstance(m, dict) else None
                if role == "tool" or (role == "assistant" and m.get("tool_calls")):
                    self._history.append(dict(m))
            note = self._stop_note(result) if (ok and result is not None) else ""
            content = shown or ""
            if note and note in content:
                content = re.sub(r"\n{3,}", "\n\n", content.replace(note, "")).strip()
            self._history.append({"role": "assistant" if ok else "error", "content": content,
                                  **({"note": note} if note else {})})
        self._pending_user = None
        self._worker = None
        self._round_bubble = None
        self._round_text = ""
        self._stream = ""
        self._busy(False)
        self.input.setFocus()
        self._scroll_bottom()
        if result is not None and getattr(result, "stop_reason", None) == StopReason.PENDING_TASK:
            for t in (result.pending_tasks or []):
                if t.get("task_id"):
                    self._ai_pending_tasks[t["task_id"]] = t.get("name") or tr("任务")
        if self._queue:
            nxt = self._queue.pop(0)
            QTimer.singleShot(30, self, lambda: self._send(nxt, echo=False))

    def _on_done(self, result):
        if not isinstance(result, AgentResult):
            result = AgentResult(str(result or ""))
        text = str(result) or self._stream
        note = self._stop_note(result)
        if note and note not in text:
            text = (text + "\n\n" + note).strip()
        self._finish(text, True, result=result)

    def _on_fail(self, msg: str):
        self._flush_timer.stop()
        text = (msg or "").strip() or tr("接口没返回具体原因")
        stopped = text in (tr("已停止"), tr("已取消"))
        if self._round_bubble:
            self._round_bubble.set_text(text)
        else:
            self._add_bubble("error", text)
        if stopped:
            InfoBar.info(tr("已停止"), tr("可以继续说下一句"), parent=self,
                         position=InfoBarPosition.TOP, duration=2200)
        else:
            InfoBar.error(tr("助手出错"), text, parent=self,
                          position=InfoBarPosition.TOP, duration=12000)
        self._finish(text, stopped)

    def _stop(self):
        if self._worker:
            self._worker.cancel()

    def _on_task_progress(self, task_id, current, total, message):
        line = self._task_lines.get(task_id)
        if line:
            line.set_progress(current, total, message or "")

    def _on_task_finished(self, task_id, success, message):
        pending_name = self._ai_pending_tasks.pop(task_id, None)
        line = self._task_lines.get(task_id)
        if line:
            line.set_text((tr("完成：") if success else tr("失败：")) + (message or ""))
            line.set_state("done" if success else "fail")
            if hasattr(line, "bar"):
                line.bar.setValue(100 if success else line.bar.value())
        if pending_name is None:
            return
        mark = tr("成功") if success else tr("失败")
        report = f"[后台任务回报] {pending_name} {mark}：{message or ''}"
        if self._worker:
            self._queue.append(report)
            return
        InfoBar.info(tr("后台任务完成"), tr("助手回来汇报结果"),
                     parent=self, position=InfoBarPosition.TOP, duration=3000)
        QTimer.singleShot(50, self, lambda: self._send(report, echo=False))

    def closeEvent(self, event):
        worker = self._worker
        if worker is not None:
            worker.cancel()
            worker.wait(1500)
        super().closeEvent(event)
