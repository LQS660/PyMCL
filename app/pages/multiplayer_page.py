# -*- coding: utf-8 -*-
"""陶瓦联机：创建房间 / 加入好友。"""

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, InfoBar, InfoBarPosition, PrimaryPushButton,
    PushButton, SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
    TransparentPushButton,
)

from ..widgets import IconTile, InputDialog, Pill


class ActionCard(SimpleCardWidget):
    def __init__(self, letter, color, title, desc, button, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        layout.addWidget(IconTile(letter, color, size=46))
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(StrongBodyLabel(title))
        hint = CaptionLabel(desc)
        hint.setWordWrap(True)
        box.addWidget(hint)
        layout.addLayout(box, 1)
        if button is not None:
            layout.addWidget(button, 0, Qt.AlignVCenter)


class MultiplayerPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("multiplayerPage")
        self.backend = backend
        self._busy = False
        self._auto_started = False
        self._last_state = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)

        head = QVBoxLayout()
        head.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("陶瓦联机"))
        self.state_pill = Pill("未就绪", "#888888")
        title_row.addWidget(self.state_pill)
        title_row.addStretch(1)
        head.addLayout(title_row)
        head.addWidget(CaptionLabel(
            "输入邀请码即可加入。陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道；"
            "会和 HMCL 一样传官方节点，并带上本机 HMCL 用过的自定义会合节点。"
        ))
        root.addLayout(head)

        self.status = BodyLabel("正在检查联机内核…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        fw = SimpleCardWidget(self)
        fw_box = QHBoxLayout(fw)
        fw_box.setContentsMargins(16, 12, 16, 12)
        fw_box.setSpacing(12)
        fw_box.addWidget(IconTile("墙", "#E8862E", size=40))
        fw_text = QVBoxLayout()
        fw_text.setSpacing(2)
        fw_text.addWidget(StrongBodyLabel("防火墙通常不会弹窗"))
        fw_hint = CaptionLabel(
            "陶瓦在后台运行，Windows 不会提示。点「允许访问」后在 UAC 选是。"
            "若装了 360 / 电脑管家 / 火绒，还要在它们的名单里放行陶瓦和 EasyTier。"
        )
        fw_hint.setWordWrap(True)
        fw_text.addWidget(fw_hint)
        fw_box.addLayout(fw_text, 1)
        self.fw_btn = PrimaryPushButton("允许访问")
        self.fw_btn.setFixedWidth(110)
        self.fw_btn.clicked.connect(self._allow_firewall)
        fw_open = PushButton("打开设置")
        fw_open.setFixedWidth(90)
        fw_open.clicked.connect(self._open_firewall)
        fw_box.addWidget(self.fw_btn, 0, Qt.AlignVCenter)
        fw_box.addWidget(fw_open, 0, Qt.AlignVCenter)
        root.addWidget(fw)

        self.room_card = SimpleCardWidget(self)
        room_box = QVBoxLayout(self.room_card)
        room_box.setContentsMargins(18, 16, 18, 16)
        room_box.setSpacing(6)
        room_box.addWidget(CaptionLabel("邀请码（点击复制）"))
        self.room_label = SubtitleLabel("—")
        self.room_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.room_card.mousePressEvent = lambda e: self._copy(
            self.room_label.text() if self.room_label.text() != "—" else "", "已复制")
        room_box.addWidget(self.room_label)
        self.url_hint = CaptionLabel("")
        self.url_hint.setWordWrap(True)
        self.url_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        room_box.addWidget(self.url_hint)
        root.addWidget(self.room_card)
        self.room_card.hide()

        self.actions = QVBoxLayout()
        self.actions.setSpacing(10)
        root.addLayout(self.actions)

        self.players_title = StrongBodyLabel("房间成员")
        root.addWidget(self.players_title)
        self.players = QVBoxLayout()
        self.players.setSpacing(8)
        root.addLayout(self.players)
        self.players_title.hide()

        root.addStretch(1)

        foot = QHBoxLayout()
        link = TransparentPushButton("Terracotta 项目主页")
        link.clicked.connect(self._open_home)
        foot.addWidget(link)
        foot.addStretch(1)
        self.copy_label = CaptionLabel("Terracotta | 陶瓦联机  © burningtnt  ·  基于 EasyTier")
        foot.addWidget(self.copy_label)
        root.addLayout(foot)

        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.reload)
        if hasattr(backend, "finished"):
            backend.finished.connect(self._on_task)
        self.reload()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self._maybe_prepare()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _snapshot(self) -> dict:
        fn = getattr(self.backend, "terracotta_snapshot", None)
        if callable(fn):
            try:
                return fn() or {}
            except Exception as exc:
                return {"state": "fatal", "label": str(exc), "error": str(exc)}
        return {"state": "fatal", "label": "后端未接入陶瓦联机"}

    def _on_task(self, task_id, success, message):
        title = ""
        fn = getattr(self.backend, "task_title", None)
        if callable(fn):
            title = str(fn(task_id) or "")
        if "陶瓦" not in title:
            return
        self._busy = False
        if not success:
            InfoBar.error(title, str(message), parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)
        self.reload()

    def _maybe_prepare(self):
        if self._auto_started or self._busy:
            return
        info = self._snapshot()
        if info.get("supported") and info.get("installed") and not info.get("running"):
            self._auto_started = True
            self._prepare()

    def _prepare(self, source=None):
        if self._busy:
            return
        self._busy = True
        if source is not None:
            win = self.window()
            if hasattr(win, "fly_to_tasks"):
                win.fly_to_tasks(source, "联", "#2E9B6B")
        self.backend.terracotta_prepare()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _copy(self, text: str, title="已复制"):
        text = (text or "").strip()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        InfoBar.success(title, text, parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)

    def _open_home(self):
        QDesktopServices.openUrl(QUrl("https://github.com/burningtnt/Terracotta"))

    def _open_firewall(self):
        fn = getattr(self.backend, "terracotta_open_firewall_settings", None)
        if callable(fn):
            fn()
        else:
            QDesktopServices.openUrl(QUrl("ms-settings:windowsdefender"))

    def _allow_firewall(self):
        fn = getattr(self.backend, "terracotta_allow_firewall", None)
        if not callable(fn):
            return
        try:
            msg = fn()
            InfoBar.success("防火墙", str(msg), parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=5000)
        except Exception as exc:
            InfoBar.error("防火墙", str(exc), parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)

    def _host(self):
        info = self._snapshot()
        if not info.get("game_running"):
            box_ok = True
            try:
                from qfluentwidgets import MessageBox
                box = MessageBox(
                    "您似乎忘记启动游戏了",
                    "请先启动游戏，进入单人世界，按 ESC，选择对局域网开放。",
                    self,
                )
                box.yesButton.setText("游戏已启动")
                box.cancelButton.setText("取消")
                box_ok = bool(box.exec())
            except Exception:
                box_ok = True
            if not box_ok:
                return
        try:
            self.backend.terracotta_host()
        except Exception as exc:
            InfoBar.error("创建房间失败", str(exc), parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
        self.reload()

    def _join(self):
        dlg = InputDialog(
            "我想当房客",
            "请输入房主提供的邀请码",
            placeholder="U/XXXX-XXXX-XXXX-XXXX",
            parent=self,
        )
        if not (dlg.exec() and dlg.value()):
            return
        try:
            self.backend.terracotta_join(dlg.value())
        except Exception as exc:
            InfoBar.error("邀请码错误", str(exc), parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
        self.reload()

    def _direct(self):
        dlg = InputDialog(
            "公网直连",
            "朋友需先对局域网开放世界，并在路由器映射该端口。然后输入他的公网地址。",
            placeholder="例如 1.2.3.4:25565",
            parent=self,
        )
        if not (dlg.exec() and dlg.value()):
            return
        fn = getattr(self.backend, "terracotta_direct_connect", None)
        if not callable(fn):
            InfoBar.error("直连失败", "当前版本没有公网直连。", parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return
        try:
            result = fn(dlg.value())
            InfoBar.success("正在直连", str(result or "启动后会进入该服务器。"),
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
        except Exception as exc:
            InfoBar.error("直连失败", str(exc), parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)

    def _enter_world(self):
        fn = getattr(self.backend, "terracotta_enter_world", None)
        if not callable(fn):
            return
        try:
            result = fn()
        except Exception as exc:
            InfoBar.error("进入世界失败", str(exc), parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)
            return
        if isinstance(result, str) and result.startswith("task-"):
            win = self.window()
            if hasattr(win, "fly_to_tasks"):
                win.fly_to_tasks(self, "进", "#2E9B6B")
            InfoBar.success("正在启动游戏", "启动后会直接进入陶瓦联机大厅。",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
        else:
            InfoBar.success("已加入房间", str(result or "请到多人游戏双击「陶瓦联机大厅」。"),
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)

    def _back(self):
        try:
            self.backend.terracotta_idle()
        except Exception as exc:
            InfoBar.error("返回失败", str(exc), parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
        self.reload()

    def _add_action(self, letter, color, title, desc, text, slot, primary=False):
        btn = PrimaryPushButton(text) if primary else PushButton(text)
        btn.setFixedWidth(110)
        btn.clicked.connect(slot)
        self.actions.addWidget(ActionCard(letter, color, title, desc, btn))

    def reload(self):
        info = self._snapshot()
        state = info.get("state") or "missing"
        if self._busy and state in ("missing", "idle"):
            state = "installing"
        elif state in ("waiting", "host-ok", "guest-ok") or (state == "idle" and not self._busy):
            self._busy = False

        colors = {
            "host-ok": "#2E9B6B",
            "guest-ok": "#2E9B6B",
            "waiting": "#2E9B6B",
            "idle": "#4C8BF5",
            "exception": "#D95568",
            "fatal": "#D95568",
            "unsupported": "#D95568",
            "missing": "#E8862E",
        }
        pill_text = info.get("label") or state
        if state in ("exception", "fatal"):
            pill_text = "加入失败"
        self.state_pill.setText(pill_text)
        self.state_pill.setStyleSheet(
            f"color: white; background: {colors.get(state, '#888888')};"
            " border-radius: 8px; padding: 1px 8px; font-size: 11px;"
        )
        status_text = info.get("error") or info.get("label") or ""
        if info.get("error_hint"):
            status_text = (info.get("error") or "") + "\n" + info["error_hint"]
        elif info.get("difficulty_hint"):
            status_text = (info.get("label") or "") + "\n" + info["difficulty_hint"]
        self.status.setText(status_text)
        room = info.get("room") or ""
        url = info.get("url") or ""
        if room or url:
            self.room_card.show()
            self.room_label.setText(room or "陶瓦联机大厅")
            if url:
                self.url_hint.setText("请启动游戏，选择多人游戏，双击进入陶瓦联机大厅。")
            else:
                self.url_hint.setText("请提醒好友在联机页选择「我想当房客」，并输入该邀请码。")
        else:
            self.room_card.hide()

        if state != getattr(self, "_ui_state", None):
            self._ui_state = state
            self._clear_layout(self.actions)
            self._fill_actions(state, info, room, url)

        profiles = info.get("profiles") or []
        sig = tuple((p.get("name"), p.get("kind"), p.get("vendor")) for p in profiles)
        if sig != getattr(self, "_player_sig", None):
            self._player_sig = sig
            self._clear_layout(self.players)
            self.players_title.setVisible(bool(profiles))
            for row in profiles:
                card = SimpleCardWidget()
                line = QHBoxLayout(card)
                line.setContentsMargins(14, 10, 14, 10)
                kind = "房主" if str(row.get("kind") or "").upper() == "HOST" else "成员"
                line.addWidget(IconTile((row.get("name") or "?")[:1], "#2E9B6B", size=36))
                box = QVBoxLayout()
                box.setSpacing(1)
                box.addWidget(StrongBodyLabel(row.get("name") or "玩家"))
                box.addWidget(CaptionLabel(row.get("vendor") or kind))
                line.addLayout(box, 1)
                line.addWidget(Pill(kind, "#4C8BF5"))
                self.players.addWidget(card)

        if room and state == "host-ok" and self._last_state != "host-ok":
            self._copy(room, "已将邀请码复制到剪贴板")
        self._last_state = state

    def _fill_actions(self, state, info, room, url):
        if state == "unsupported":
            self._add_action("!", "#D95568", "当前系统不支持", "陶瓦联机暂未提供此架构的官方内核。", "了解", self._open_home)
        elif state == "missing":
            self._add_action("瓦", "#2E9B6B", "下载陶瓦联机内核",
                             "首次使用需要下载约 8 MB 的官方内核，之后可直接开房。",
                             "下载", lambda: self._prepare(self), primary=True)
        elif state == "idle":
            self._add_action("▶", "#4C8BF5", "启动联机内核", "内核已安装，点一下即可开始联机。",
                             "启动", lambda: self._prepare(self), primary=True)
        elif state in ("launching", "unknown", "installing"):
            self._add_action("…", "#888888", "请稍候", info.get("label") or "正在准备联机内核。", "刷新", self.reload)
        elif state == "waiting":
            self._add_action("房", "#2E9B6B", "我想当房主",
                             "创建房间并生成邀请码，与好友一起畅玩。",
                             "创建", self._host, primary=True)
            self._add_action("客", "#4C8BF5", "我想当房客",
                             "输入房主提供的邀请码加入游戏世界。",
                             "加入", self._join)
        elif state in ("host-scanning", "host-starting"):
            self._add_action("扫", "#E8862E", "正在扫描局域网世界",
                             "请启动游戏，进入单人世界，按 ESC，选择对局域网开放。",
                             "退出", self._back)
        elif state == "host-ok":
            self._add_action("复", "#2E9B6B", "复制邀请码", "好友在联机页选择房客并输入该邀请码即可加入。",
                             "复制", lambda: self._copy(room, "已将邀请码复制到剪贴板"), primary=True)
            self._add_action("返", "#888888", "退出", "这将同时彻底关闭房间，其他房客将退出。", "退出", self._back)
        elif state in ("guest-connecting", "guest-starting"):
            self._add_action("连", "#4C8BF5", "正在加入房间",
                             info.get("difficulty_hint") or "正在与房主建立连接。",
                             "退出", self._back)
        elif state == "guest-ok":
            self._add_action("进", "#2E9B6B", "进入世界",
                             "启动游戏后到多人游戏双击「陶瓦联机大厅」，或点这里直接进入。",
                             "进入", self._enter_world, primary=True)
            self._add_action("返", "#888888", "退出", "这不会影响其他房客加入当前房间。", "退出", self._back)
        elif state in ("exception", "fatal"):
            self._add_action("!", "#D95568", "联机失败",
                             info.get("error_hint") or info.get("error") or "请返回后重试，或检查网络。",
                             "返回", self._back)
            self._add_action("直", "#4C8BF5", "朋友是公网就直连",
                             "让他把单人世界对局域网开放，并在路由映射该端口，然后填他的公网 IP:端口。",
                             "直连", self._direct)
            self._add_action("启", "#4C8BF5", "重新启动内核", "若内核已退出，点此重新拉起。",
                             "重启", lambda: self._prepare(self))
