# -*- coding: utf-8 -*-
"""AI 助手页：多会话、流式、确认、进度。"""

from __future__ import annotations

import html
import json
import re
import threading

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QFrame, QHBoxLayout, QHeaderView,
    QListWidget, QListWidgetItem, QSizePolicy, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, ComboBox, FluentIcon as FIF, InfoBar,
    InfoBarPosition, LineEdit, MessageBoxBase, PlainTextEdit, PrimaryPushButton,
    ProgressBar, PushButton, RadioButton, ScrollArea, SubtitleLabel, TableWidget,
    TransparentPushButton, TransparentToolButton,
)

from mclauncher.ai.agent import AgentCancelled, run_agent
from mclauncher.ai.client import AIClientError, HttpCancel
from mclauncher.ai import permission as ai_perm
from mclauncher.ai import preview as ai_preview
from mclauncher.ai import rewind as ai_rewind_mod
from mclauncher.ai import store as chat_store
from mclauncher.ai.defaults import DEFAULT_MODEL
from mclauncher.ai.permission import Behavior, Rule, rule_content_from_input
from mclauncher.ai.result import AgentResult, StopReason
from mclauncher.ai.tools import TOOL_META
from ..lucide import IconLabel, ShimmerLabel, pixmap as lucide_pixmap, tool_icon
from ..pcl_chrome import Theme, prestyle_page
from mclauncher.i18n import tr

_RED = "#D64545"

_STOP = {tr("已停止"), tr("已取消")}
_CHIPS = (tr("下一款游戏 1.20.1 Fabric"), tr("装钠和光影"), tr("启动闪退了帮我看"))
_WELCOME = (
    tr("我是启动器助手。可以帮你下游戏、装模组和整合包、看启动报错、查模组冲突、改常用配置。\n"
    "直接说你想做什么就行。写操作我会先让你确认。")
)
_WELCOME_NOCONFIRM = (
    tr("我是启动器助手。可以帮你下游戏、装模组和整合包、看启动报错、查模组冲突、改常用配置。\n"
    "直接说你想做什么就行。写操作会直接执行，不逐条询问。")
)
_FENCE = re.compile(r"```(?:\w+)?\n([\s\S]*?)```")


def _split_think(text: str) -> tuple[list[str], str]:
    """把 <think>…</think> 块从回复里摘出来。

    流式期间可能只有开头没有收尾（模型还在想），这种情况把未闭合块整体
    算作思考内容，答案为空；收尾出现后答案从 </think> 之后起算。
    """
    parts: list[str] = []
    answer: list[str] = []
    rest = text or ""
    while True:
        i = rest.lower().find("<think>")
        if i < 0:
            break
        answer.append(rest[:i])
        j = rest.lower().find("</think>", i + 7)
        if j < 0:
            parts.append(rest[i + 7:])
            rest = ""
            break
        parts.append(rest[i + 7:j])
        rest = rest[j + 8:]
    answer.append(rest)
    return parts, "".join(answer).strip()


class _ThinkHead(QFrame):
    """思考块的标题行：brain 图标 + 文字 + 右侧折叠箭头，整行可点。"""

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)
        self.icon = IconLabel("brain", 16, Theme.muted)
        self.label = ShimmerLabel("")
        self.chevron = IconLabel("chevron-right", 16, Theme.muted)
        lay.addWidget(self.icon)
        lay.addWidget(self.label)
        lay.addStretch(1)
        lay.addWidget(self.chevron)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_click()
            e.accept()
            return
        super().mousePressEvent(e)


class ThinkFold(QFrame):
    """可折叠的思考过程块：平时一行收起，点开看全文；流式期间自动展开。

    标题行照 ZCode 的 Reasoning 行：左 brain 图标，中间文字（模型还在想时走流光），
    右侧 chevron 展开时转 90°。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        self.toggle = _ThinkHead(self._flip)
        self.body = BodyLabel("")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setVisible(False)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self._open = False
        self._live = False
        self._thinking = False
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.restyle()

    def _flip(self):
        self._open = not self._open
        self.body.setVisible(self._open)
        self._sync_head()

    def set_open(self, on: bool):
        if self._open == on:
            self._sync_head()
            return
        self._open = on
        self.body.setVisible(on)
        self._sync_head()

    def _sync_head(self):
        if self._thinking:
            head = tr("思考中…")
        else:
            n = len(self.body.text())
            head = tr("思考过程") + (f"（{n}）" if n else "")
        self.toggle.label.setText(head)
        self.toggle.label.set_active(self._thinking)
        self.toggle.chevron.set_angle(90 if self._open else 0)

    def set_think(self, text: str, *, live: bool, open_: bool):
        """live=整条消息还在流式；open_=思考块还没闭合（模型仍在想）。"""
        self._live = live
        self._thinking = bool(live and open_)
        self.body.setText(text or "")
        self.set_open(open_)
        self._sync_head()

    def restyle(self):
        bg = Theme.hover if not Theme.dark else "#232823"
        self.setStyleSheet(
            f"ThinkFold {{ background: {bg}; border: 1px solid {Theme.line};"
            " border-radius: 8px; }")
        self.body.setStyleSheet(f"color: {Theme.muted}; font-size: 12px;")
        self.toggle.setStyleSheet("QFrame { background: transparent; border: none; }")
        self.toggle.label.setStyleSheet(
            f"color: {Theme.text}; font-size: 12px; font-weight: 500; background: transparent;")
        self.toggle.label.set_shimmer_color(Theme.text)
        self.toggle.icon.set_color(Theme.muted)
        self.toggle.chevron.set_color(Theme.muted)
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _md(text: str) -> str:
    raw = text or ""
    pre_bg = "#2B2B2B" if Theme.dark else "#F4F6F5"
    pre_fg = "#E8E8E8" if Theme.dark else "#2B2B2B"
    parts = []
    idx = 0
    for m in _FENCE.finditer(raw):
        parts.append(_md_inline(raw[idx:m.start()]))
        code = html.escape(m.group(1).rstrip())
        parts.append(
            f"<pre style='background:{pre_bg};color:{pre_fg};padding:8px;border-radius:6px;"
            "white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;'>"
            f"{code}</pre>"
        )
        idx = m.end()
    parts.append(_md_inline(raw[idx:]))
    return "".join(parts)


def _md_inline(text: str) -> str:
    t = html.escape(text or "")
    t = _CODE.sub(r"<code>\1</code>", t)
    t = _BOLD.sub(r"<b>\1</b>", t)
    t = t.replace("\n", "<br>")
    return t


class AgentThread(QThread):
    delta = Signal(str)
    status = Signal(str, dict)
    need_confirm = Signal(str, dict, str, str)
    need_ask = Signal(list, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, backend, settings, history, user_text, parent=None,
                 queue_fn=None):
        super().__init__(parent)
        self.backend = backend
        self.settings = settings
        self.history = history
        self.user_text = user_text
        self._queue_fn = queue_fn
        self._cancel = False
        self._http = HttpCancel()
        self._confirm_ev = threading.Event()
        self._confirm_ok = False
        self._ask_ev = threading.Event()
        self._ask_result = None

    def cancel(self):
        self._cancel = True
        self._http.abort()
        self.answer_confirm(False)
        self.answer_ask(None)

    def answer_confirm(self, ok):
        # bool 或 Rule（返回 Rule 表示「以后都允许这类操作」）
        self._confirm_ok = ok
        self._confirm_ev.set()

    def answer_ask(self, result):
        self._ask_result = result
        self._ask_ev.set()

    def run(self):
        def on_delta(text):
            self.delta.emit(text)

        def on_status(kind, payload):
            self.status.emit(kind, payload or {})

        def confirm_fn(name, args, label, reason=""):
            self._confirm_ev.clear()
            self.need_confirm.emit(name, args, label, str(reason or ""))
            while not self._confirm_ev.wait(0.2):
                if self._cancel:
                    return False
            return self._confirm_ok

        def ask_fn(questions, title):
            self._ask_ev.clear()
            self._ask_result = None
            self.need_ask.emit(list(questions or []), str(title or ""))
            while not self._ask_ev.wait(0.2):
                if self._cancel:
                    return None
            return self._ask_result

        def cancelled():
            return self._cancel

        def drain_inputs_fn():
            # 运行中用户补的话：每轮开头取走，同一回合被采纳
            try:
                return list(self._queue_fn() or []) if self._queue_fn else []
            except Exception:  # noqa: BLE001
                return []

        try:
            result = run_agent(
                self.backend, self.settings, self.history, self.user_text,
                on_delta=on_delta, on_status=on_status,
                confirm_fn=confirm_fn, ask_fn=ask_fn, cancelled=cancelled,
                http_cancel=self._http, drain_inputs_fn=drain_inputs_fn,
            )
            if self._cancel:
                self.failed.emit(tr("已停止"))
                return
            self.done.emit(result if isinstance(result, AgentResult)
                           else AgentResult(result or ""))
        except AgentCancelled:
            self.failed.emit(tr("已停止"))
        except AIClientError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class Bubble(QFrame):
    def __init__(self, role: str, text: str = "", parent=None):
        super().__init__(parent)
        self.role = role
        self._plain = text or ""
        self._live = False
        mine = role == "user"
        err = role == "error"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self._err_icon: IconLabel | None = None
        if err:
            self._err_icon = IconLabel("circle-x", 14, _RED)
            head.addWidget(self._err_icon)
        self.who = CaptionLabel(tr("我") if mine else (tr("出错") if err else tr("助手")))
        head.addWidget(self.who)
        head.addStretch(1)
        if not mine:
            copy = TransparentPushButton(tr("复制"))
            copy.setFixedHeight(22)
            copy.clicked.connect(self._copy)
            head.addWidget(copy)
        lay.addLayout(head)
        self._think: ThinkFold | None = None
        self._answer = self._plain
        # 「正在想…」占位行：brain 图标 + 流光文字，对齐 ZCode 的思考行；
        # 一有正文（流式 delta / 最终答案）就收起来换回 body
        self._ph = QWidget()
        ph = QHBoxLayout(self._ph)
        ph.setContentsMargins(0, 2, 0, 2)
        ph.setSpacing(8)
        self._ph_icon = IconLabel("brain", 16, Theme.muted)
        self._ph_label = ShimmerLabel("")
        ph.addWidget(self._ph_icon)
        ph.addWidget(self._ph_label)
        ph.addStretch(1)
        self._ph.hide()
        lay.addWidget(self._ph)
        self.body = BodyLabel("")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.body.setOpenExternalLinks(True)
        lay.addWidget(self.body)
        self._apply_style()
        self.set_text(text)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setMaximumWidth(640)

    def _apply_style(self):
        err = self.role == "error"
        if self.role == "user":
            bg = "#1E3A2E" if Theme.dark else "#E8F6EF"
        elif err:
            bg = "#3A1E1E" if Theme.dark else "#FDECEC"
        else:
            bg = Theme.card
        self.setStyleSheet(
            "Bubble { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (bg, "#E07A7A" if err else Theme.line)
        )
        self.who.setStyleSheet(f"color: {'#C23A3A' if err else Theme.muted};")
        self.body.setStyleSheet(f"color: {Theme.text};")
        self._ph_icon.set_color(Theme.muted)
        self._ph_label.setStyleSheet(f"color: {Theme.text}; font-weight: 500;")
        self._ph_label.set_shimmer_color(Theme.text)
        if self._think is not None:
            self._think.restyle()

    def restyle(self):
        self._apply_style()
        if not self._ph.isHidden():
            return
        self.set_text(self._plain, live=self._live)

    def set_placeholder(self, text: str):
        """还没有正文时的「正在想…」：整条气泡只剩 brain + 流光一行。"""
        self._plain = ""
        self._answer = ""
        self._ph_label.setText(text or "")
        self._ph_label.set_active(True)
        self._ph.show()
        self.body.hide()
        if self._think is not None:
            self._think.hide()

    def _hide_placeholder(self):
        if not self._ph.isHidden():
            self._ph_label.set_active(False)
            self._ph.hide()
        if self.body.isHidden():
            self.body.show()
        if self._think is not None and self._think.isHidden():
            self._think.show()

    def set_text(self, text: str, *, live: bool = False):
        self._hide_placeholder()
        self._plain = text or ""
        self._live = live
        if self.role == "user":
            self.body.setTextFormat(Qt.PlainText)
            self.body.setText(self._plain)
            return
        think, answer = _split_think(self._plain)
        self._answer = answer
        if think:
            if self._think is None:
                self._think = ThinkFold(self)
                self.layout().insertWidget(self.layout().indexOf(self.body), self._think)
            open_think = (self._plain.lower().count("<think>")
                          > self._plain.lower().count("</think>"))
            self._think.set_think("\n\n".join(p.strip() for p in think if p.strip()),
                                  live=live, open_=(live and open_think))
        if live:
            self.body.setTextFormat(Qt.PlainText)
            self.body.setText(answer)
            return
        self.body.setTextFormat(Qt.RichText)
        self.body.setText(_md(answer) or "…")

    def _copy(self):
        QApplication.clipboard().setText(self._answer or self._plain or "")
        InfoBar.success(tr("已复制"), "", parent=self.window() or self,
                        position=InfoBarPosition.TOP, duration=1200)


class ToolLine(QFrame):
    """对话流里的一行工具状态：左侧图标 + 文字，绑了后台任务再带进度条。

    图标照 ZCode 的工具行：搜索 / 读文件 / 改文件三类工具在准备、执行时显示
    类型图标，其余工具显示旋转的 loader；结束后统一换成 circle-check /
    circle-slash-2 / circle-x。执行中文字走流光。
    """

    _STATES = ("prepare", "run", "done", "skip", "fail")

    def __init__(self, text: str, parent=None, *, tool: str = ""):
        super().__init__(parent)
        self.tool = tool or ""
        self._state = "prepare"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.icon = IconLabel("", 16, Theme.green)
        self.lab = ShimmerLabel(text)
        self.lab.setWordWrap(True)
        row.addWidget(self.icon, 0, Qt.AlignTop)
        row.addWidget(self.lab, 1)
        self.bar = ProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        lay.addLayout(row)
        lay.addWidget(self.bar)
        self.task_id = ""
        self.restyle()

    def restyle(self):
        self.setStyleSheet(f"ToolLine {{ background: {Theme.hover}; border-radius: 8px; }}")
        self.lab.setStyleSheet(f"color: {Theme.green}; font-size: 12px; background: transparent;")
        self.lab.set_shimmer_color(Theme.green)
        self._sync_icon()

    def set_text(self, text: str):
        self.lab.setText(text)

    def set_state(self, state: str):
        if state not in self._STATES:
            return
        self._state = state
        self._sync_icon()

    def _sync_icon(self):
        running = self._state in ("prepare", "run")
        self.lab.set_active(running)
        if running:
            kind = tool_icon(self.tool)
            if kind:
                self.icon.spin(False)
                self.icon.set_icon(kind, Theme.green)
            else:
                self.icon.set_icon("loader-circle", Theme.green)
                self.icon.spin(True)
            return
        self.icon.spin(False)
        if self._state == "done":
            self.icon.set_icon("circle-check", Theme.green)
        elif self._state == "skip":
            self.icon.set_icon("circle-slash-2", Theme.muted)
        else:
            self.icon.set_icon("circle-x", _RED)

    def bind_task(self, task_id: str):
        self.task_id = task_id or ""
        if self.task_id:
            self.bar.show()

    def set_progress(self, current: int, total: int, message: str = ""):
        if total:
            self.bar.setValue(min(100, max(0, int(current * 100 / total))))
        if message:
            self.lab.setText(message.split("  |  ", 1)[0])


_AMBER = "#D68A17"

# 工具 → 人话动词，给「始终允许」那行说明用；没列的工具退回工具名
_TOOL_TITLES = {
    "install_game": "安装游戏", "install_mod": "安装模组", "install_modpack": "安装整合包",
    "install_shader": "安装光影", "install_resourcepack": "安装资源包",
    "install_datapack": "安装数据包", "install_world": "安装地图",
    "download_java": "下载 Java", "launch_game": "启动游戏",
    "create_instance": "新建实例", "delete_instance": "删除实例", "delete_mod": "删除模组",
    "disable_mod": "禁用模组", "enable_mod": "启用模组", "write_mod_config": "改配置",
}


def always_hint(name: str, args: dict | None) -> str:
    """「始终允许」会记住什么，一句话说清（对齐 ZCode 的 allowAlways.description）。"""
    title = tr(_TOOL_TITLES[name]) if name in _TOOL_TITLES else (name or "")
    content = rule_content_from_input(args or {})
    if content:
        return tr("以后「{0} {1}」不再询问；换别的仍会问").format(title, content)
    return tr("以后所有「{0}」操作都不再询问").format(title)


class ConfirmCard(QFrame):
    """内联权限卡：允许 / 始终允许 / 拒绝 三键（ZCode 的 permission 卡），
    「始终允许」下面一行说明记什么、记到哪（仅当前实例 / 所有实例）。"""

    accepted = Signal()
    rejected = Signal()
    always = Signal(str)        # 参数 = 记忆范围 permission.SCOPE_*

    def __init__(self, label: str, detail: str = "", parent=None, *,
                 name: str = "", args: dict | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self._icon = IconLabel("shield-alert", 16, _AMBER)
        head.addWidget(self._icon, 0, Qt.AlignVCenter)
        self._title = BodyLabel(tr("需要你点一下确认："))
        head.addWidget(self._title, 1)
        lay.addLayout(head)
        desc = BodyLabel(label)
        desc.setWordWrap(True)
        lay.addWidget(desc)
        if detail:
            box = PlainTextEdit()
            box.setReadOnly(True)
            box.setPlainText(detail)
            box.setFixedHeight(min(160, 40 + detail.count("\n") * 16))
            lay.addWidget(box)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.yes_btn = PrimaryPushButton(tr("允许"))
        self.always_btn = PushButton(tr("始终允许"))
        self.no_btn = PushButton(tr("拒绝"))
        self.yes_btn.clicked.connect(lambda: self._done(tr("已允许"), self.accepted.emit))
        self.always_btn.clicked.connect(
            lambda: self._done(tr("已允许并记住"), lambda: self.always.emit(self.scope())))
        self.no_btn.clicked.connect(lambda: self._done(tr("已拒绝"), self.rejected.emit))
        row.addWidget(self.yes_btn)
        row.addWidget(self.always_btn)
        row.addWidget(self.no_btn)
        row.addStretch(1)
        self.state = CaptionLabel("")
        row.addWidget(self.state, 0, Qt.AlignVCenter)
        lay.addLayout(row)

        hint_row = QHBoxLayout()
        hint_row.setSpacing(10)
        self.hint = CaptionLabel(tr("始终允许 = ") + always_hint(name, args))
        self.hint.setWordWrap(True)
        hint_row.addWidget(self.hint, 1)
        self._scope_group = QButtonGroup(self)
        self.scope_inst = RadioButton(tr("仅当前实例"))
        self.scope_all = RadioButton(tr("所有实例"))
        self.scope_inst.setChecked(True)
        self._scope_group.addButton(self.scope_inst, 0)
        self._scope_group.addButton(self.scope_all, 1)
        hint_row.addWidget(self.scope_inst, 0, Qt.AlignVCenter)
        hint_row.addWidget(self.scope_all, 0, Qt.AlignVCenter)
        lay.addLayout(hint_row)
        self.restyle()

    def scope(self) -> str:
        return ai_perm.SCOPE_GLOBAL if self.scope_all.isChecked() else ai_perm.SCOPE_INSTANCE

    def _done(self, note: str, emit):
        for b in (self.yes_btn, self.always_btn, self.no_btn, self.scope_inst, self.scope_all):
            b.setEnabled(False)
        self.state.setText(note)
        emit()

    def restyle(self):
        el_bg = "#3A2E10" if Theme.dark else "#FFF8E8"
        el_border = "#8A7A3A" if Theme.dark else "#F0D48A"
        self.setStyleSheet(
            f"ConfirmCard {{ background: {el_bg}; border: 1px solid {el_border}; border-radius: 10px; }}"
        )
        self.hint.setStyleSheet(f"color: {Theme.muted};")
        self.state.setStyleSheet(f"color: {Theme.muted};")
        self._icon.set_color(_AMBER)


class AskCard(QFrame):
    submitted = Signal(object)
    cancelled = Signal()

    def __init__(self, questions: list, title: str = "", parent=None):
        super().__init__(parent)
        self.restyle()
        self._qs = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        if title:
            t = BodyLabel(title)
            t.setWordWrap(True)
            lay.addWidget(t)
        for q in questions or []:
            block = _AskBlock(q)
            self._qs.append(block)
            lay.addWidget(block)
        row = QHBoxLayout()
        ok = PrimaryPushButton(tr("确定"))
        no = PushButton(tr("跳过"))
        ok.clicked.connect(self._submit)
        no.clicked.connect(self.cancelled.emit)
        row.addWidget(ok)
        row.addWidget(no)
        row.addStretch(1)
        lay.addLayout(row)

    def restyle(self):
        bg = "#1E3A2E" if Theme.dark else "#F3F7F5"
        border = "#3A6B52" if Theme.dark else "#C9E4D6"
        self.setStyleSheet(
            f"AskCard {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
        )

    def _submit(self):
        answers = {}
        for block in self._qs:
            row = block.collect()
            if row is None:
                InfoBar.warning(tr("还没选"), block.prompt, parent=self.window() or self,
                                position=InfoBarPosition.TOP, duration=2200)
                return
            answers[block.qid] = row
        self.setEnabled(False)
        self.submitted.emit({"answers": answers})


class _AskBlock(QWidget):
    def __init__(self, q: dict, parent=None):
        super().__init__(parent)
        self.qid = str(q.get("id") or "q1")
        self.prompt = str(q.get("prompt") or tr("请选择"))
        self.multi = bool(q.get("allow_multiple"))
        self._opts = list(q.get("options") or [])
        self._group = None
        self._radios = []
        self._checks = []
        self._other = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        hint = BodyLabel(self.prompt + (tr("（可多选）") if self.multi else ""))
        hint.setWordWrap(True)
        root.addWidget(hint)
        if self.multi:
            for o in self._opts:
                box = CheckBox(o.get("label") or o.get("id") or "")
                box.setProperty("opt_id", o.get("id"))
                if o.get("id") == "other":
                    self._other = box
                    box.stateChanged.connect(self._sync_other)
                self._checks.append(box)
                root.addWidget(box)
        else:
            self._group = QButtonGroup(self)
            self._group.setExclusive(True)
            for i, o in enumerate(self._opts):
                btn = RadioButton(o.get("label") or o.get("id") or "")
                btn.setProperty("opt_id", o.get("id"))
                if o.get("id") == "other":
                    self._other = btn
                self._group.addButton(btn, i)
                self._radios.append(btn)
                root.addWidget(btn)
            if self._group:
                self._group.buttonToggled.connect(self._sync_other)
        self.other_edit = LineEdit()
        self.other_edit.setPlaceholderText(tr("选「其他」时在这里填"))
        self.other_edit.hide()
        root.addWidget(self.other_edit)

    def _sync_other(self, *_a):
        on = False
        if self.multi and self._other:
            on = self._other.isChecked()
        elif self._other:
            on = self._other.isChecked()
        self.other_edit.setVisible(on)

    def collect(self):
        picked = []
        if self.multi:
            for box in self._checks:
                if box.isChecked():
                    picked.append({"id": box.property("opt_id"), "label": box.text()})
        else:
            btn = self._group.checkedButton() if self._group else None
            if btn:
                picked.append({"id": btn.property("opt_id"), "label": btn.text()})
        extra = self.other_edit.text().strip()
        other_on = any(p.get("id") == "other" or tr("其他") in (p.get("label") or "") for p in picked)
        if extra and not other_on:
            picked.append({"id": "other", "label": tr("其他")})
            other_on = True
        if other_on and not extra and len(picked) == 1:
            return None
        if not picked:
            return None
        return {
            "ids": [p["id"] for p in picked],
            "labels": [p["label"] for p in picked],
            "other_text": extra if other_on else "",
        }


# 五档权限：值、标题、一句人话、图标。Qt / WPF 两端同一张表。
PERM_MODES = (
    ("default", "每次确认", "安装、删除、改配置、启动，所有写操作都先问你", "shield-alert"),
    ("acceptEdits", "写直接执行", "安装 / 改配置直接做，删除前仍会先问", "file-pen-line"),
    ("plan", "只看不动", "只能查看和诊断，任何写操作都被拦下", "eye"),
    ("yolo", "全自动", "一切直接执行，不再弹确认", "sparkles"),
    ("custom", "自定义规则", "按「每次确认」判定，再叠加下面的规则表", "sliders-horizontal"),
)
_BEHAVIOR_ICONS = {"allow": ("circle-check", None), "deny": ("ban", _RED),
                   "ask": ("shield-alert", _AMBER)}


class _ModeCard(QFrame):
    """档位卡片：图标 + 标题 + 一句说明，整块可点，选中亮绿边。"""

    clicked = Signal(str)

    def __init__(self, value: str, title: str, desc: str, icon: str, parent=None):
        super().__init__(parent)
        self.value = value
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        self.icon = IconLabel(icon, 18, Theme.muted)
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = BodyLabel(title)
        self.desc = CaptionLabel(desc)
        self.desc.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.desc)
        lay.addLayout(text, 1)
        self.check = IconLabel("circle-check", 16, Theme.green)
        self.check.setVisible(False)
        lay.addWidget(self.check, 0, Qt.AlignVCenter)
        self.restyle()

    def set_selected(self, on: bool):
        self._selected = bool(on)
        self.check.setVisible(self._selected)
        self.restyle()

    def restyle(self):
        border = Theme.green if self._selected else Theme.line
        bg = ("#1E3A2E" if Theme.dark else "#EEF7F2") if self._selected else Theme.card
        self.setStyleSheet(
            f"_ModeCard {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}")
        self.title.setStyleSheet(f"color: {Theme.text}; font-weight: 600; background: transparent;")
        self.desc.setStyleSheet(f"color: {Theme.muted}; background: transparent;")
        self.icon.set_color(Theme.green if self._selected else Theme.muted)
        self.check.set_color(Theme.green)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.value)
            e.accept()
            return
        super().mousePressEvent(e)


class PermissionDialog(MessageBoxBase):
    """AI 助手权限管理：五张档位卡片 + 规则表格。

    档位点哪张立即落盘；规则表每行「范围 / 工具 / 参数 / 行为 / 删除」，下面一行
    加规则（可选记到全局或当前实例）。on_changed 让 AI 页同步输入框旁的快捷下拉。
    """

    _MODES = tuple(m[0] for m in PERM_MODES)
    _BEHAVIORS = (Behavior.ALLOW, Behavior.DENY, Behavior.ASK)

    def __init__(self, backend, on_changed=None, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._on_changed = on_changed
        s = backend.get_settings()
        self._instance = str(s.get("default_instance") or "default")
        mode = s.get("ai_permission_mode") or "default"
        if mode not in self._MODES:
            mode = "default"

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("shield-alert", 18, Theme.green), 0, Qt.AlignVCenter)
        head.addWidget(SubtitleLabel(tr("权限管理"), self), 1)
        self.viewLayout.addLayout(head)
        self.viewLayout.addWidget(CaptionLabel(tr("控制 AI 助手改东西前要不要先问你")))
        self.viewLayout.addSpacing(8)

        self._cards: dict[str, _ModeCard] = {}
        for value, title, desc, icon in PERM_MODES:
            card = _ModeCard(value, tr(title), tr(desc), icon)
            card.clicked.connect(self._pick_mode)
            self._cards[value] = card
            self.viewLayout.addWidget(card)
        self._mode = mode
        self._cards[mode].set_selected(True)

        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel(tr("自定义规则"), self))
        self.viewLayout.addWidget(CaptionLabel(tr(
            "规则永远优先于档位：禁止 > 允许 > 每次问。「始终允许」点出来的也记在这里。")))
        self.table = TableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([tr("范围"), tr("工具"), tr("参数"), tr("行为"), ""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(150)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 40)
        self.viewLayout.addWidget(self.table)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.rule_tool = ComboBox(self)
        self.rule_tool.addItems(sorted(TOOL_META))
        self.rule_tool.setFixedWidth(170)
        self.rule_behavior = ComboBox(self)
        self.rule_behavior.addItems([tr("允许"), tr("禁止"), tr("每次问")])
        self.rule_behavior.setFixedWidth(96)
        self.rule_content = LineEdit(self)
        self.rule_content.setPlaceholderText(tr("限定参数（留空 = 整个工具）"))
        self.rule_scope = ComboBox(self)
        self.rule_scope.addItems([tr("所有实例"), tr("仅实例 {0}").format(self._instance)])
        self.rule_scope.setFixedWidth(150)
        add_btn = PushButton(tr("添加"), self)
        add_btn.clicked.connect(self._add_rule)
        add_row.addWidget(self.rule_tool)
        add_row.addWidget(self.rule_behavior)
        add_row.addWidget(self.rule_content, 1)
        add_row.addWidget(self.rule_scope)
        add_row.addWidget(add_btn)
        self.viewLayout.addLayout(add_row)

        self._reload_rules()

        self.yesButton.setText(tr("关闭"))
        self.cancelButton.hide()
        self.widget.setMinimumWidth(620)

    def _pick_mode(self, value: str):
        if value == self._mode:
            return
        self._cards[self._mode].set_selected(False)
        self._mode = value
        self._cards[value].set_selected(True)
        self._save()

    def _reload_rules(self):
        rows = ai_perm.list_stored_rules()
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            scope = tr("所有实例") if not row.get("instance") \
                else tr("实例 {0}").format(row["instance"])
            self.table.setItem(i, 0, QTableWidgetItem(scope))
            self.table.setItem(i, 1, QTableWidgetItem(row["toolName"]))
            self.table.setItem(i, 2, QTableWidgetItem(row.get("ruleContent") or tr("（整个工具）")))
            icon, color = _BEHAVIOR_ICONS.get(row["behavior"], ("shield-alert", _AMBER))
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(6, 0, 6, 0)
            cl.setSpacing(6)
            cl.addWidget(IconLabel(icon, 14, color or Theme.green), 0, Qt.AlignVCenter)
            cl.addWidget(CaptionLabel(row["behavior_label"]), 0, Qt.AlignVCenter)
            cl.addStretch(1)
            self.table.setCellWidget(i, 3, cell)
            btn = TransparentToolButton(QIcon(lucide_pixmap("trash-2", 16, Theme.muted)))
            btn.setFixedSize(30, 30)
            btn.setToolTip(tr("删除这条规则"))
            btn.clicked.connect(lambda *_a, k=row["key"], inst=row.get("instance") or "":
                                self._del_rule(k, inst))
            self.table.setCellWidget(i, 4, btn)
            self.table.setRowHeight(i, 34)
        if not rows:
            self.table.setRowCount(1)
            empty = QTableWidgetItem(tr("还没有规则。确认卡上点「始终允许」，或在下面手动加一条。"))
            self.table.setItem(0, 0, empty)
            self.table.setSpan(0, 0, 1, 5)

    def _add_rule(self):
        tool = self.rule_tool.currentText()
        if not tool:
            return
        behavior = self._BEHAVIORS[self.rule_behavior.currentIndex()]
        content = self.rule_content.text().strip() or None
        instance = self._instance if self.rule_scope.currentIndex() == 1 else None
        try:
            ai_perm.append_rule(Rule(tool, content, behavior), instance=instance)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("保存失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return
        self.rule_content.clear()
        self._reload_rules()

    def _del_rule(self, key: str, instance: str):
        ai_perm.remove_rule(key, instance=instance)
        self._reload_rules()

    def _save(self, *_a):
        mode = self._mode
        try:
            self.backend.save_settings({
                "ai_confirm_writes": mode != "yolo",
                "ai_permission_mode": mode,
            })
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("保存失败"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return
        if self._on_changed:
            self._on_changed()


class ChatInput(PlainTextEdit):
    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(tr("问我要下什么、哪报错、模组怎么配…  Enter 发送，Shift+Enter 换行"))
        self.setFixedHeight(48)
        self._preedit = ""
        self.textChanged.connect(self._grow)

    def _grow(self):
        h = int(self.document().size().height()) + 20
        self.setFixedHeight(min(140, max(48, h)))

    def inputMethodEvent(self, event):
        self._preedit = event.preeditString() or ""
        super().inputMethodEvent(event)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            if self._preedit:
                super().keyPressEvent(e)
                return
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            e.accept()
            return
        super().keyPressEvent(e)


class AiPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPage")
        self.backend = backend
        self._store = chat_store.load()
        # 早年每次进页面都建新会话，攒下一长串空「新对话」；这里收一次尾
        chat_store.prune_empty(self._store)
        self._history = []
        self._worker = None
        self._assistant_bubble = None
        self._stream = ""
        self._queue = []
        self._tool_lines = {}
        self._task_lines = {}
        self._notes = []
        self._pending_user = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(33)
        self._flush_timer.timeout.connect(self._flush_stream)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._do_scroll)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._side = QFrame()
        self._side.setFixedWidth(200)
        sl = QVBoxLayout(self._side)
        sl.setContentsMargins(10, 14, 10, 14)
        sl.setSpacing(8)
        new_btn = PrimaryPushButton(getattr(FIF, "ADD", FIF.PLAY), tr("新对话"))
        new_btn.setFixedHeight(32)
        new_btn.clicked.connect(self._new_chat)
        sl.addWidget(new_btn)
        self.chat_list = QListWidget()
        self.chat_list.currentItemChanged.connect(self._on_pick_chat)
        sl.addWidget(self.chat_list, 1)
        del_btn = TransparentPushButton(FIF.DELETE, tr("删除对话"))
        del_btn.clicked.connect(self._delete_chat)
        sl.addWidget(del_btn)
        root.addWidget(self._side)

        main = QVBoxLayout()
        main.setContentsMargins(24, 20, 24, 20)
        main.setSpacing(10)

        head = QHBoxLayout()
        title = SubtitleLabel(tr("AI 助手"))
        title.setFont(QFont(title.font().family(), 16, QFont.DemiBold))
        head.addWidget(title)
        self.status = CaptionLabel("")
        head.addWidget(self.status)
        head.addStretch(1)
        self.stop_btn = PushButton(FIF.CLOSE, tr("停止"))
        self.stop_btn.setEnabled(False)
        self.retry_btn = TransparentPushButton(FIF.SYNC, tr("重试"))
        self.retry_btn.setEnabled(False)
        self.rewind_btn = TransparentPushButton(getattr(FIF, "RETURN", FIF.SYNC),
                                                tr("回到上一步"))
        self.rewind_btn.setEnabled(False)
        self.rewind_btn.setToolTip(tr("撤回最近一轮对话；该轮对文件的改动一并还原"))
        self.rewind_btn.clicked.connect(self._rewind)
        head.addWidget(self.stop_btn)
        head.addWidget(self.retry_btn)
        head.addWidget(self.rewind_btn)
        main.addLayout(head)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for t in _CHIPS:
            b = PushButton(t)
            b.setFixedHeight(28)
            b.clicked.connect(lambda *_a, s=t: self._send_text(s))
            chips.addWidget(b)
        chips.addStretch(1)
        main.addLayout(chips)

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
        main.addWidget(self.scroll, 1)
        prestyle_page(self, self.scroll)

        self._input_box = QFrame()
        row = QHBoxLayout(self._input_box)
        row.setContentsMargins(10, 8, 10, 8)
        self.input = ChatInput()
        # 输入框旁的权限快捷区：下拉直接切档，齿轮开完整说明面板
        self.perm_combo = ComboBox()
        self.perm_combo.setFixedHeight(34)
        self.perm_combo.setFixedWidth(120)
        self.perm_combo.setToolTip(tr("AI 权限等级"))
        self.perm_combo.addItems([tr("每次确认"), tr("写直接执行"), tr("只看不动"),
                                  tr("全自动"), tr("自定义")])
        self.perm_combo.currentIndexChanged.connect(self._on_perm_level)
        self.perm_btn = TransparentToolButton(FIF.SETTING)
        self.perm_btn.setFixedSize(34, 34)
        self.perm_btn.setToolTip(tr("点击管理 AI 权限"))
        self.perm_btn.clicked.connect(self._open_permissions)
        self.send_btn = PrimaryPushButton(getattr(FIF, "SEND", FIF.PLAY), tr("发送"))
        self.send_btn.setFixedHeight(34)
        row.addWidget(self.input, 1)
        row.addWidget(self.perm_combo)
        row.addWidget(self.perm_btn)
        row.addWidget(self.send_btn)
        main.addWidget(self._input_box)

        wrap = QWidget()
        wrap.setLayout(main)
        root.addWidget(wrap, 1)

        self.send_btn.clicked.connect(lambda: self._send_text(self.input.toPlainText()))
        self.input.submitted.connect(self._send_text)
        self.stop_btn.clicked.connect(self._stop)
        self.retry_btn.clicked.connect(self._retry)
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.activated.connect(self._stop)
        self.backend.progress.connect(self._on_task_progress)
        self.backend.finished.connect(self._on_task_finished)

        self.restyle()
        self._reload_list()
        self._load_active()
        self._refresh_perm_ui()

    def reload(self):
        self._refresh_status()
        self._refresh_perm_ui()

    def restyle(self):
        self._side.setStyleSheet(
            f"QFrame {{ background: {Theme.card}; border-right: 1px solid {Theme.line}; }}")
        self.chat_list.setStyleSheet(
            f"QListWidget {{ border: none; background: transparent; color: {Theme.text}; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {Theme.hover}; }}"
        )
        self._input_box.setStyleSheet(
            f"QFrame {{ background: {Theme.card}; border: 1px solid {Theme.line}; border-radius: 10px; }}"
        )
        self.status.setStyleSheet(f"color: {Theme.muted};")
        # 已经贴在对话流里的气泡 / 工具行 / 卡片不会自己跟主题走，逐个刷一遍
        for kind in (Bubble, ToolLine, ConfirmCard, AskCard):
            for w in self._host.findChildren(kind):
                w.restyle()
        self._refresh_status()

    def _refresh_status(self):
        s = self.backend.get_settings()
        mode = s.get("ai_mode") or "public"
        if mode == "custom":
            label = f"自定义 · {s.get('ai_model') or DEFAULT_MODEL}"
        else:
            label = f"公益接口 · {DEFAULT_MODEL}"
        self.status.setText(label)

    _PERM_LEVELS = ("default", "acceptEdits", "plan", "yolo", "custom")

    def _perm_level(self) -> str:
        s = self.backend.get_settings()
        mode = s.get("ai_permission_mode") or "default"  # backend 已做旧值归一化
        if mode not in self._PERM_LEVELS:
            mode = "default" if bool(s.get("ai_confirm_writes", True)) else "yolo"
        return mode

    def _refresh_perm_ui(self):
        level = self._perm_level()
        self.perm_combo.blockSignals(True)
        self.perm_combo.setCurrentIndex(self._PERM_LEVELS.index(level))
        self.perm_combo.blockSignals(False)

    def _on_perm_level(self, index: int):
        data = {
            0: {"ai_confirm_writes": True, "ai_permission_mode": "default"},
            1: {"ai_confirm_writes": True, "ai_permission_mode": "acceptEdits"},
            2: {"ai_confirm_writes": True, "ai_permission_mode": "plan"},
            3: {"ai_confirm_writes": False, "ai_permission_mode": "yolo"},
            4: {"ai_confirm_writes": True, "ai_permission_mode": "custom"},
        }.get(index)
        if not data:
            return
        try:
            self.backend.save_settings(data)
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("保存失败"), str(exc), parent=self.window() or self,
                          position=InfoBarPosition.TOP, duration=4000)
        self._refresh_perm_ui()

    def _open_permissions(self):
        dlg = PermissionDialog(self.backend, on_changed=self._refresh_perm_ui,
                               parent=self.window())
        dlg.exec()

    def _launch_prefs(self) -> dict:
        win = self.window()
        lp = getattr(win, "launch_page", None)
        if lp is None:
            return {}
        java = ""
        try:
            java = lp._selected_java()
        except Exception:
            java = lp.java_box.currentText() if hasattr(lp, "java_box") else ""
        return {
            "instance": lp.instance_box.currentText() if hasattr(lp, "instance_box") else "",
            "version": lp.version_box.currentText() if hasattr(lp, "version_box") else "",
            "account": lp.account_box.currentText() if hasattr(lp, "account_box") else "",
            "username": lp.username_edit.text().strip() if hasattr(lp, "username_edit") else "Player",
            "memory_mb": lp.memory_slider.value() if hasattr(lp, "memory_slider") else 0,
            "width": lp.width_spin.value() if hasattr(lp, "width_spin") else 0,
            "height": lp.height_spin.value() if hasattr(lp, "height_spin") else 0,
            "java": java,
        }

    def _reload_list(self):
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        active = self._store.get("active_id")
        pick = None
        for c in self._store.get("chats") or []:
            item = QListWidgetItem(c.get("title") or tr("对话"))
            item.setData(Qt.UserRole, c.get("id"))
            self.chat_list.addItem(item)
            if c.get("id") == active:
                pick = item
        if pick:
            self.chat_list.setCurrentItem(pick)
        self.chat_list.blockSignals(False)

    def _wipe_messages(self):
        while self.chat.count() > 1:
            item = self.chat.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._assistant_bubble = None
        self._stream = ""
        self._tool_lines.clear()
        self._task_lines.clear()

    def _load_active(self):
        chat = chat_store.get_chat(self._store, self._store.get("active_id") or "")
        self._history = list((chat or {}).get("messages") or [])
        self._wipe_messages()
        if not self._history:
            s = self.backend.get_settings()
            welcome = _WELCOME if bool(s.get("ai_confirm_writes", True)) else _WELCOME_NOCONFIRM
            self._add_bubble("assistant", welcome)
        else:
            for m in self._history:
                role = m.get("role") or "assistant"
                if role in ("user", "assistant", "error"):
                    text = m.get("content") or ""
                    # 「为什么停」的提示单独存在 note 里（不喂模型），渲染时再拼回去
                    note = str(m.get("note") or "")
                    if note and note not in text:
                        text = (text + "\n\n" + note).strip()
                    self._add_bubble(role, text)
        self._scroll_bottom()

    def _persist(self):
        cid = self._store.get("active_id") or ""
        chat_store.upsert_messages(self._store, cid, self._history)
        self._reload_list()

    def _abandon_run(self):
        """切换 / 新建 / 删除对话前，把还在跑的回合整个收掉。

        只 cancel + wait 不够：worker 的 done / failed 是排队信号，会在 _load_active
        之后才送到，那时 `_finish` 里 `_pending_user` 还在，就把旧回合的提问和
        「已停止」写进**新对话**并落盘，`_on_fail` 还会往新对话里贴一个报错气泡。
        这里把信号断开、回合痕迹清零、按钮复位，后面那一帖到了也没人接。
        （WPF 端同一处按 chat_id 分流，语义一致：切走 = 放弃上一回合。）
        """
        worker = self._worker
        if worker is None:
            return
        worker.cancel()
        for sig, slot in ((worker.delta, self._on_delta), (worker.status, self._on_status),
                          (worker.need_confirm, self._on_confirm), (worker.need_ask, self._on_ask),
                          (worker.done, self._on_done), (worker.failed, self._on_fail)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        worker.wait(2500)
        self._flush_timer.stop()
        self._worker = None
        self._pending_user = None
        self._assistant_bubble = None
        self._stream = ""
        self._queue.clear()
        self._busy(False)
        InfoBar.info(tr("已停止上一个对话的回合"), tr("切换对话时正在运行的那一轮已中断"),
                     parent=self.window() or self, position=InfoBarPosition.TOP, duration=2200)

    def _new_chat(self):
        self._abandon_run()
        chat_store.new_chat(self._store)
        self._load_active()
        self._reload_list()

    def _delete_chat(self):
        cid = self._store.get("active_id")
        if not cid:
            return
        from qfluentwidgets import MessageBox
        box = MessageBox(
            tr("删除对话"),
            tr("当前对话及其全部历史将被删除，且无法恢复。确定删除？"),
            self.window() or self,
        )
        box.yesButton.setText(tr("删除"))
        box.cancelButton.setText(tr("取消"))
        if not box.exec():
            return
        self._abandon_run()
        chat_store.delete_chat(self._store, cid)
        self._load_active()
        self._reload_list()

    def _on_pick_chat(self, item, _prev=None):
        if item is None:
            return
        cid = item.data(Qt.UserRole)
        if cid == self._store.get("active_id"):
            return
        # 以前在跑时直接 return：列表高亮已经跳到新对话、内容却还是旧的，按钮也停在「忙」。
        # 现在跟新建 / 删除一致：切走就放弃上一回合，新对话从干净状态开始。
        self._abandon_run()
        chat_store.set_active(self._store, cid)
        self._load_active()

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

    def _flush_stream(self):
        if self._assistant_bubble:
            self._assistant_bubble.set_text(self._stream or "…", live=True)
        self._scroll_bottom()

    def _busy(self, on: bool):
        self.send_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        self.retry_btn.setEnabled(not on and bool(self._history))
        self._refresh_rewind()

    def _refresh_rewind(self):
        self.rewind_btn.setEnabled(
            not self._worker and any(m.get("role") == "user" for m in self._history))

    def _rewind(self):
        """撤回最近一轮：对话截回上一轮之前，该轮对文件的改动一并还原（方案甲）。

        快照失败的轮次回不来——返回值里 rollbackable=False 时明确告诉用户。
        """
        if self._worker:
            return
        chat_id = str(self._store.get("active_id") or "")
        try:
            res = ai_rewind_mod.rewind_last_round(chat_id)
        except Exception:
            res = {"ok": False, "truncated": False, "restored_files": 0,
                   "restored_bytes": 0, "rollbackable": False, "disk_changed": False}
        # rewind 落盘的是磁盘上的 store；页面内存里的副本要重载，别拿旧历史渲染
        self._store = chat_store.load()
        self._load_active()
        self._busy(False)
        if res.get("disk_changed"):
            if res.get("ok"):
                InfoBar.success(
                    tr("已撤回"),
                    tr("对话已回退，{n} 个文件的改动已还原")
                    .format(n=res.get("restored_files") or 0),
                    parent=self.window() or self,
                    position=InfoBarPosition.TOP, duration=4000)
            else:
                InfoBar.warning(
                    tr("部分还原"),
                    tr("对话已回退，但磁盘改动没能全部还原，请手动检查相关文件"),
                    parent=self.window() or self,
                    position=InfoBarPosition.TOP, duration=6000)
        elif not res.get("rollbackable"):
            InfoBar.info(
                tr("已撤回"),
                tr("只回退了对话。这一轮没有可还原的磁盘改动"),
                parent=self.window() or self,
                position=InfoBarPosition.TOP, duration=4000)

    def _send_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if self._worker:
            self._queue.append(text)
            self.input.clear()
            # 这里已经把气泡贴出去了，出队时 _send 不能再贴一次
            self._add_bubble("user", text)
            InfoBar.info(tr("已插队"), tr("这句话会立刻交给正在运行的助手"),
                         parent=self.window() or self,
                         position=InfoBarPosition.TOP, duration=1800)
            return
        self.input.clear()
        self._send(text)

    def _drain_queue(self):
        """steering：把排队的插话交给正在跑的 agent 回合（线程安全：pop 原子）。"""
        out = []
        while self._queue:
            out.append(self._queue.pop(0))
        return out

    def _send(self, text: str, *, echo: bool = True):
        if echo:
            self._add_bubble("user", text)
        self._stream = ""
        self._notes = []
        self._tool_lines = {}
        self._task_lines = {}
        self._assistant_bubble = self._add_bubble("assistant", "")
        self._assistant_bubble.set_placeholder(tr("正在想…"))
        settings = self.backend.get_settings()
        settings["ai_session_id"] = str(self._store.get("active_id") or "active")
        # 首条消息一发就把会话名从「新对话」换成摘要，不用等落盘
        chat = chat_store.get_chat(self._store, str(self._store.get("active_id") or ""))
        if chat and chat.get("title") in ("", "新对话", "对话"):
            chat["title"] = text.replace("\n", " ")[:24]
            self._reload_list()
        self.backend._ui_launch = self._launch_prefs()
        # 工具轨迹也在历史里（批次 5），截取上限交给 store.MAX_MESSAGES；
        # agent 侧 _trim_history 保证不从孤立的 tool 消息开切
        worker = AgentThread(
            self.backend, settings, chat_store.api_messages(
                self._history[-chat_store.MAX_MESSAGES:]), text,
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

    def _retry(self):
        last = None
        for m in reversed(self._history):
            if m.get("role") == "user" and (m.get("content") or "").strip():
                last = m["content"]
                break
        if last and not self._worker:
            self._send(last)

    def _on_delta(self, piece: str):
        if not piece:
            return
        self._stream += piece
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _on_status(self, kind: str, payload: dict):
        label = payload.get("label") or payload.get("name") or kind
        name = payload.get("name") or ""
        if kind == "checkpoint_warn":
            InfoBar.warning(
                tr("无法一键撤回"),
                str(payload.get("message") or tr("检查点不可用，本轮改动无法一键撤回")),
                parent=self.window() or self,
                position=InfoBarPosition.TOP, duration=6000)
            return
        if kind == "think":
            if not self._stream:
                if payload.get("after_tools"):
                    tip = tr("搜完了，正在整理…")
                else:
                    tip = tr("正在想…")
                if self._assistant_bubble:
                    self._assistant_bubble.set_placeholder(tip)
            return
        if kind == "tool":
            if name == "ask_user":
                if self._assistant_bubble and not self._stream:
                    self._assistant_bubble.set_text(tr("请在下面选一下"))
                return
            line = self._tool_lines.get(name)
            if line:
                line.set_text(tr("准备：") + label)
            else:
                line = ToolLine(tr("准备：") + label, tool=name)
                self._tool_lines[name] = line
                self._add_widget(line)
            line.set_state("prepare")
            return
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
                except Exception:
                    tid = ""
            if tid and line:
                line.bind_task(tid)
                self._task_lines[tid] = line
            if label:
                self._notes.append(label)
        elif kind == "tool_skip":
            if line:
                line.set_text(tr("已跳过：") + label)
            else:
                line = ToolLine(tr("已跳过：") + label, tool=name)
                self._add_widget(line)
            line.set_state("skip")
        self._scroll_bottom()

    def _on_confirm(self, name: str, args: dict, label: str, reason: str = ""):
        # 变更预览：确认卡上展示将要发生的实际变更（diff / 文件数与字节数 /
        # 目标路径），Qt 与 WPF 渲染同一份 preview.lines，两端信息量一致
        detail_lines: list[str] = []
        try:
            pv = ai_preview.change_preview(self.backend, name, args or {})
        except Exception:
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
        # 删除类不给「始终允许」：这些工具的参数键不在 RULE_CONTENT_KEYS 里，
        # 记一次就是整工具级放行，等于以后删什么都不问（permission.decide 也不吃这种规则）
        meta = TOOL_META.get(name)
        if meta is not None and getattr(meta, "side_effect", "") == "delete":
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
        card = AskCard(questions, title)
        worker = self._worker

        def ok(payload):
            if worker:
                worker.answer_ask(payload)
            try:
                labels = []
                for row in (payload or {}).get("answers", {}).values():
                    labels.extend(row.get("labels") or [])
                if labels:
                    self._notes.append(tr("已选 ") + "、".join(labels))
            except Exception:
                pass

        def skip():
            card.setEnabled(False)
            if worker:
                worker.answer_ask(None)

        card.submitted.connect(ok)
        card.cancelled.connect(skip)
        self._add_widget(card)
        if self._assistant_bubble and not self._stream:
            self._assistant_bubble.set_text(tr("请在下面选一下"))

    def _compose_assistant(self, text: str) -> str:
        body = (text or "").strip()
        if self._notes:
            extra = tr("（本轮：") + "；".join(self._notes[:8]) + "）"
            if extra not in body:
                body = (body + "\n\n" + extra).strip()
        return body

    @staticmethod
    def _stop_note(result) -> str:
        """把「为什么停」拼进气泡，别再让回合静默结束。"""
        reason = getattr(result, "stop_reason", None)
        if reason is None or reason == StopReason.COMPLETED:
            return ""
        detail = (getattr(result, "detail", "") or "").strip()
        notes = {
            StopReason.NO_TOOL_CALL: tr("它没有真的开始执行：模型只回了文字，没有调用任何工具。"),
            StopReason.MAX_ROUNDS: tr("步骤太多，先停在这里。你可以让我继续。"),
            StopReason.PENDING_TASK: tr("下载/安装还在后台跑，可以在「下载任务」里看进度。"),
            StopReason.STREAM_FAILED: tr("接口这轮没有返回内容，已停止。"),
            StopReason.EMPTY_RESPONSE: tr("接口返回了空回复。"),
        }
        note = notes.get(reason)
        if not note:
            return ""
        if detail and detail not in note:
            note += "（" + detail + "）"
        return tr("（提示：") + note + tr("）")

    def _notify_stop(self, result):
        reason = getattr(result, "stop_reason", None)
        if reason is None or reason == StopReason.COMPLETED:
            return
        win = self.window() or self
        if reason == StopReason.NO_TOOL_CALL:
            InfoBar.warning(
                tr("它没有真的开始执行"),
                tr("模型只回了文字，没有调用任何工具。可以点「重试」再催它一次。"),
                parent=win, position=InfoBarPosition.TOP, duration=6000)
        elif reason == StopReason.PENDING_TASK:
            InfoBar.info(tr("任务还在后台跑"), tr("可以在「下载任务」里查看进度。"),
                         parent=win, position=InfoBarPosition.TOP, duration=4000)

    def _finish(self, assistant_text: str, ok: bool, result=None):
        self._flush_timer.stop()
        shown = self._compose_assistant(assistant_text if ok else (assistant_text or tr("已停止")))
        if self._assistant_bubble:
            self._assistant_bubble.set_text(shown or (tr("已停止") if not ok else ""))
        user = getattr(self, "_pending_user", None)
        if user:
            self._history.append({"role": "user", "content": user})
            # 本回合的工具轨迹一并入库（W5-1）：重开程序模型才知道上次做到哪。
            # 只取 turn_messages（本回合新增那一段）：result.messages 是模型侧完整历史，
            # 里面还有上几轮的工具消息，照抄进来每轮都会把旧轨迹重复存一遍。
            for m in (getattr(result, "turn_messages", None) or []):
                role = m.get("role") if isinstance(m, dict) else None
                if role == "tool" or (role == "assistant" and m.get("tool_calls")):
                    self._history.append(dict(m))
            # 「为什么停」的提示不进正文（模型下一轮会读到自己上一句后面挂着
            # 「没有真的开始执行」），拆成 note 字段存，渲染历史时再拼回去
            content = shown or ""
            note = self._stop_note(result) if (ok and result is not None) else ""
            if note and note in content:
                content = re.sub(r"\n{3,}", "\n\n", content.replace(note, "")).strip()
            entry = {"role": "assistant" if ok else "error", "content": content}
            if note:
                entry["note"] = note
            self._history.append(entry)
            self._persist()
        self._pending_user = None
        self._worker = None
        self._assistant_bubble = None
        self._stream = ""
        self._busy(False)
        self.input.setFocus()
        self._scroll_bottom()
        if result is not None:
            # 后台任务登记：完成时 _on_task_finished 主动回来汇报（W5-2）
            if getattr(result, "stop_reason", None) == StopReason.PENDING_TASK:
                tasks = getattr(self, "_ai_pending_tasks", None)
                if tasks is None:
                    tasks = self._ai_pending_tasks = {}
                for t in (result.pending_tasks or []):
                    if t.get("task_id"):
                        tasks[t["task_id"]] = t.get("name") or "任务"
            self._notify_stop(result)
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
        if self._assistant_bubble:
            self._assistant_bubble.set_text(text)
        else:
            self._add_bubble("error", text)
        if text in _STOP:
            InfoBar.info(tr("已停止"), tr("可以继续说下一句"), parent=self.window() or self,
                         position=InfoBarPosition.TOP, duration=2200)
        else:
            InfoBar.error(tr("助手出错"), text, parent=self.window() or self,
                          position=InfoBarPosition.TOP, duration=12000)
        self._finish(text, text in _STOP)

    def _stop(self, wait=False):
        if self._worker:
            self._worker.cancel()
            if wait:
                self._worker.wait(2500)

    def _on_task_progress(self, task_id, current, total, message):
        line = self._task_lines.get(task_id)
        if line:
            line.set_progress(current, total, message or "")

    def _on_task_finished(self, task_id, success, message):
        pending_name = None
        tasks = getattr(self, "_ai_pending_tasks", None) or {}
        if task_id in tasks:
            pending_name = tasks.pop(task_id)
        line = self._task_lines.get(task_id)
        if line:
            line.set_text((tr("完成：") if success else tr("失败：")) + (message or ""))
            line.set_state("done" if success else "fail")
            if hasattr(line, "bar"):
                line.bar.setValue(100 if success else line.bar.value())
        if pending_name is None:
            return
        # W5-2：AI 之前说「完成后我回来汇报」——结果到了主动发起新回合
        mark = tr("成功") if success else tr("失败")
        report = f"[后台任务回报] {pending_name} {mark}：{message or ''}"
        if self._worker:
            self._queue.append(report)
            return
        InfoBar.info(tr("后台任务完成"), tr("助手回来汇报结果"),
                     parent=self.window() or self,
                     position=InfoBarPosition.TOP, duration=3000)
        QTimer.singleShot(50, self, lambda: self._send(report, echo=False))
