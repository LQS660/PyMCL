# -*- coding: utf-8 -*-
"""账号页：微软 / 离线 / 皮肤站，带皮肤预览与离线自定义皮肤。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    LineEdit, MessageBoxBase, PasswordLineEdit, PrimaryPushButton, PushButton, ScrollArea,
    SimpleCardWidget, StrongBodyLabel, SubtitleLabel, TransparentPushButton,
)

from ..skin_render import front_view
from ..widgets import DeviceCodeDialog, IconTile, Pill, ThumbnailTile
from ..pcl_chrome import Theme, prestyle_page
from mclauncher.i18n import tr

# 皮肤预览框（正面小人 16x32，整数倍放大才不糊）
SKIN_BOX = (140, 260)


def skin_pixmap(png: bytes, slim: bool, box=SKIN_BOX) -> QPixmap:
    """本地皮肤 PNG → 预览图；读不出来返回空 QPixmap。"""
    img = front_view(png, slim)
    if img.isNull():
        return QPixmap()
    return QPixmap.fromImage(img).scaled(
        box[0], box[1], Qt.KeepAspectRatio, Qt.FastTransformation)


class OfflineSkinDialog(MessageBoxBase):
    """给离线账号换一张自定义皮肤，或清回游戏默认。

    真正让它显示出来的是启动时拉起的本地 Yggdrasil 服务
    （mclauncher/skinserver.py）——1.19.3 起内置默认皮肤有九种，
    靠挑 UUID 凑 Steve/Alex 的老办法已经不成立了。
    """

    PREVIEW = (110, 200)

    def __init__(self, backend, name: str, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.name = name
        self._picked = ""       # 这一轮新挑的文件
        self._clear = False
        current = backend.get_account_skin(name)
        self._current_file = current.get("skin_file") or ""

        self.viewLayout.addWidget(SubtitleLabel(tr("「{0}」的皮肤").format(name), self))
        hint = BodyLabel(
            tr("64x64 或 64x32 的 PNG。只对离线账号有效，进游戏后由启动器自带的"
               "本地皮肤服务发给游戏，不需要联网。"), self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        self.preview = BodyLabel(tr("还没设皮肤"), self)
        self.preview.setFixedSize(*self.PREVIEW)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"background: {Theme.hover}; border-radius: 8px;")
        self.viewLayout.addWidget(self.preview, 0, Qt.AlignHCenter)

        self.file_label = CaptionLabel(self._current_file or tr("游戏默认皮肤"), self)
        self.file_label.setAlignment(Qt.AlignCenter)
        self.viewLayout.addWidget(self.file_label)

        row = QHBoxLayout()
        pick = PrimaryPushButton(tr("选择 PNG"))
        pick.clicked.connect(self._pick)
        self.clear_btn = PushButton(tr("清除，用游戏默认"))
        self.clear_btn.clicked.connect(self._mark_clear)
        self.clear_btn.setEnabled(bool(self._current_file))
        row.addWidget(pick, 1)
        row.addWidget(self.clear_btn, 1)
        host = QWidget(self)
        host.setLayout(row)
        self.viewLayout.addWidget(host)

        self._models = {tr("宽臂（Steve）"): "classic", tr("细臂（Alex）"): "slim"}
        self.model_box = ComboBox(self)
        self.model_box.addItems(list(self._models))
        if current.get("skin_model") == "slim":
            self.model_box.setCurrentIndex(1)
        self.model_box.currentTextChanged.connect(lambda *_: self._refresh_preview())
        self.viewLayout.addWidget(BodyLabel(tr("手臂模型"), self))
        self.viewLayout.addWidget(self.model_box)

        self.yesButton.setText(tr("保存"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(420)
        self._refresh_preview()

    def model(self) -> str:
        return self._models.get(self.model_box.currentText(), "classic")

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择皮肤 PNG"), "", tr("PNG 图片 (*.png)"))
        if path:
            self.preset(path)

    def preset(self, path: str):
        """替用户先挑好一张（皮肤是拖进窗口来的），开框就能看到预览。"""
        self._picked = path
        self._clear = False
        self.clear_btn.setEnabled(True)
        self.file_label.setText(path)
        self._refresh_preview()

    def _mark_clear(self):
        self._picked = ""
        self._clear = True
        self.clear_btn.setEnabled(False)
        self.file_label.setText(tr("保存后清除，恢复游戏默认皮肤"))
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("游戏默认皮肤"))

    def _source_png(self) -> bytes:
        """预览要用的那份 PNG：优先这一轮挑的，其次账号已经绑着的。"""
        if self._picked:
            try:
                with open(self._picked, "rb") as fh:
                    return fh.read()
            except OSError:
                return b""
        import base64
        raw = (self.backend.get_account_skin(self.name).get("data_url") or "")
        raw = raw.split(",", 1)[-1]
        return base64.b64decode(raw) if raw else b""

    def _refresh_preview(self):
        if self._clear:
            return
        png = self._source_png()
        pix = skin_pixmap(png, self.model() == "slim", self.PREVIEW) if png else QPixmap()
        if pix.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(tr("这张图读不出来") if png else tr("还没设皮肤"))
            return
        self.preview.setText("")
        self.preview.setPixmap(pix)

    def apply(self) -> str:
        """落盘。返回给用户看的一句话；空串 = 什么都没改。"""
        if self._clear:
            self.backend.set_account_skin(self.name)
            return tr("已清除，回到游戏默认皮肤")
        path = self._picked
        if not path and self._current_file:
            # 只改了手臂模型：把现有那张原样再交一遍（import_skin 认得同一个文件）
            from mclauncher.skin import skins_dir
            path = str(skins_dir() / self._current_file)
        if not path:
            return ""
        self.backend.set_account_skin(self.name, path=path, model=self.model())
        return tr("下次启动游戏时生效")


class AccountPage(QWidget):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("accountPage")
        self.backend = backend
        self._login_dlg = None
        self._login_task = None
        self._pix_token = 0
        self._auth_busy = False

        # 整页放进滚动区：五张卡竖着摞起来最小高 850+，直接铺在页面上会把
        # 主窗口最小高度顶到 950（QStackedWidget 取所有子页最小值之最大），
        # 960x720 的出厂窗口一点进这页就会被撑大。其它长页都是这么做的。
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
        prestyle_page(self, scroll)
        root.addWidget(SubtitleLabel(tr("账号")))
        intro = CaptionLabel(tr("微软正版、离线、Little Skin、统一通行证 / 自建 Yggdrasil"))
        intro.setWordWrap(True)
        root.addWidget(intro)

        top = QHBoxLayout()
        skin_card = SimpleCardWidget(self)
        sl = QVBoxLayout(skin_card)
        sl.setContentsMargins(16, 14, 16, 14)
        self.skin = BodyLabel(tr("皮肤"))
        self.skin.setFixedSize(*SKIN_BOX)
        self.skin.setAlignment(Qt.AlignCenter)
        self.skin.setStyleSheet(f"background: {Theme.hover}; border-radius: 8px;")
        sl.addWidget(self.skin, 0, Qt.AlignHCenter)
        self.skin_name = StrongBodyLabel(tr("未登录"))
        self.skin_name.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.skin_name)
        top.addWidget(skin_card)

        list_card = SimpleCardWidget(self)
        ll = QVBoxLayout(list_card)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.addWidget(StrongBodyLabel(tr("已保存账号")))
        self.list_box = QVBoxLayout()
        ll.addLayout(self.list_box)
        ll.addStretch(1)
        top.addWidget(list_card, 1)
        root.addLayout(top)

        ms = SimpleCardWidget(self)
        ms_l = QHBoxLayout(ms)
        ms_l.setContentsMargins(16, 12, 16, 12)
        ms_l.addWidget(StrongBodyLabel(tr("微软账号")), 1)
        btn = PrimaryPushButton(FIF.PEOPLE, tr("设备码 / 浏览器登录"))
        btn.clicked.connect(self._ms)
        ms_l.addWidget(btn)
        root.addWidget(ms)

        yg = SimpleCardWidget(self)
        yl = QVBoxLayout(yg)
        yl.setContentsMargins(16, 12, 16, 12)
        yl.addWidget(StrongBodyLabel(tr("皮肤站（authlib-injector）")))
        row = QHBoxLayout()
        self.preset = ComboBox()
        self.preset.setFixedWidth(180)
        for item in backend.authlib_presets():
            self.preset.addItem(item["name"])
        self.api = LineEdit()
        self.api.setPlaceholderText("https://littleskin.cn/api/yggdrasil")
        self.user = LineEdit()
        self.user.setPlaceholderText(tr("邮箱 / 用户名"))
        self.pw = PasswordLineEdit()
        self.pw.setPlaceholderText(tr("密码"))
        self.yg_btn = PrimaryPushButton(tr("登录皮肤站"))
        self.yg_btn.clicked.connect(self._ygg)
        row.addWidget(self.preset)
        row.addWidget(self.api, 1)
        yl.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(self.user)
        row2.addWidget(self.pw)
        row2.addWidget(self.yg_btn)
        yl.addLayout(row2)
        self.preset.currentTextChanged.connect(self._fill_preset)
        self._fill_preset()
        root.addWidget(yg)

        n8 = SimpleCardWidget(self)
        n8l = QVBoxLayout(n8)
        n8l.setContentsMargins(16, 12, 16, 12)
        n8l.addWidget(StrongBodyLabel(tr("统一通行证（Nide8）")))
        n8l.addWidget(CaptionLabel(tr("填 32 位服务器 ID，或把含该 ID 的链接贴进来")))
        n8row = QHBoxLayout()
        self.nide8_id = LineEdit()
        self.nide8_id.setPlaceholderText(tr("服务器 ID / 链接"))
        self.nide8_user = LineEdit()
        self.nide8_user.setPlaceholderText(tr("用户名"))
        self.nide8_pw = PasswordLineEdit()
        self.nide8_pw.setPlaceholderText(tr("密码"))
        self.n8_btn = PrimaryPushButton(tr("登录通行证"))
        self.n8_btn.clicked.connect(self._nide8)
        n8row.addWidget(self.nide8_id, 1)
        n8l.addLayout(n8row)
        n8row2 = QHBoxLayout()
        n8row2.addWidget(self.nide8_user)
        n8row2.addWidget(self.nide8_pw)
        n8row2.addWidget(self.n8_btn)
        n8l.addLayout(n8row2)
        root.addWidget(n8)

        off = SimpleCardWidget(self)
        ol = QHBoxLayout(off)
        ol.setContentsMargins(16, 12, 16, 12)
        self.offline = LineEdit()
        self.offline.setPlaceholderText(tr("离线角色名"))
        self.skin_box = ComboBox()
        self.skin_box.addItems([tr("默认"), "Steve", "Alex"])
        self.skin_box.setFixedWidth(90)
        off_btn = PushButton(tr("保存离线账号"))
        off_btn.clicked.connect(self._offline)
        ol.addWidget(StrongBodyLabel(tr("离线")), 0)
        ol.addWidget(self.offline, 1)
        ol.addWidget(self.skin_box)
        ol.addWidget(off_btn)
        root.addWidget(off)
        root.addStretch(1)

        backend.finished.connect(self._on_finished)
        backend.login_code.connect(self._on_login_code)
        backend.login_status.connect(self._on_login_status)
        self.reload()

    def _fill_preset(self, _t=""):
        name = self.preset.currentText()
        for item in self.backend.authlib_presets():
            if item["name"] == name and item.get("api"):
                self.api.setText(item["api"])

    def reload(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = self.backend.get_account_rows()
        if not rows:
            self.list_box.addWidget(CaptionLabel(tr("还没有正版或皮肤站账号")))
        for row in rows:
            card = QWidget()
            card.setObjectName("accCard")
            card.setStyleSheet(
                f"#accCard {{ background: transparent; border: 1px solid {Theme.line};"
                " border-radius: 8px; padding: 6px; }"
                f"#accCard:hover {{ background: {Theme.hover}; }}"
            )
            bar = QHBoxLayout(card)
            bar.setContentsMargins(8, 4, 8, 4)
            # 头像预览
            body_url = row.get("body", "")
            if body_url:
                face_url = body_url.replace("/body", "/face") if "/body" in body_url else body_url
                thumb = ThumbnailTile(row["name"], face_url, size=36)
                bar.addWidget(thumb)
            else:
                bar.addWidget(IconTile(row["name"], size=36))
            bar.addWidget(StrongBodyLabel(row["name"]))
            kind = {
                "microsoft": tr("微软"),
                "authlib": tr("皮肤站"),
                "nide8": tr("统一通行证"),
                "offline": tr("离线"),
            }.get(row["type"], row["type"])
            color = "#2E9B6B" if row["type"] == "microsoft" else (
                "#E8862E" if row["type"] == "nide8" else "#7C5CD6")
            bar.addWidget(Pill(kind, color))
            if row.get("active"):
                bar.addWidget(Pill(tr("当前"), "#4C8BF5"))
            if row["type"] == "offline" and row.get("skin_file"):
                bar.addWidget(Pill(tr("自定义皮肤"), "#2E9B6B"))
            use_btn = TransparentPushButton(tr("使用"))
            use_btn.clicked.connect(lambda _, n=row["name"]: self._use(n))
            del_btn = TransparentPushButton(FIF.DELETE, tr("删除"))
            del_btn.clicked.connect(lambda _, n=row["name"]: self._delete(n))
            bar.addStretch(1)
            if row["type"] == "offline":
                # 自定义皮肤只对离线账号有效：正版和皮肤站的皮肤在各自网站上改
                skin_btn = TransparentPushButton(tr("皮肤"))
                skin_btn.clicked.connect(lambda _, n=row["name"]: self._edit_skin(n))
                bar.addWidget(skin_btn)
            bar.addWidget(use_btn)
            bar.addWidget(del_btn)
            self.list_box.addWidget(card)
        active = next((r for r in rows if r.get("active")), None) or (rows[0] if rows else None)
        self.skin_name.setText(active["name"] if active else "Steve")
        # 绑了本地皮肤的离线账号：预览走本地那张，mc-heads 不可能知道它
        if active and active.get("skin_file") and self._show_local_skin(active["name"]):
            return
        self._load_skin(active["body"] if active else "")

    def _show_local_skin(self, name: str) -> bool:
        """把账号绑定的本地皮肤画进预览框，返回有没有画成。"""
        import base64
        try:
            info = self.backend.get_account_skin(name)
        except Exception:  # noqa: BLE001
            return False
        raw = (info.get("data_url") or "").split(",", 1)[-1]
        if not raw:
            return False
        pix = skin_pixmap(base64.b64decode(raw), info.get("skin_model") == "slim")
        if pix.isNull():
            return False
        # 网络头像那条路是异步的，晚回来的一张会盖掉这张本地图；换个令牌作废它
        self._pix_token += 1
        self.skin.setPixmap(pix)
        return True

    def _edit_skin(self, name: str):
        dlg = OfflineSkinDialog(self.backend, name, self.window())
        if not dlg.exec():
            return
        try:
            message = dlg.apply()
        except Exception as exc:  # noqa: BLE001
            InfoBar.error(tr("皮肤没能保存"), str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)
            return
        if message:
            InfoBar.success(tr("皮肤已更新"), message, parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
        self.reload()

    def restyle(self):
        self.skin.setStyleSheet(f"background: {Theme.hover}; border-radius: 8px;")
        self.reload()

    def _load_skin(self, url: str):
        if not url:
            return
        self._pix_token += 1
        token = self._pix_token

        def fetch():
            import requests
            resp = requests.get(url, timeout=12)
            resp.raise_for_status()
            return resp.content

        def ok(data):
            if token != self._pix_token:
                return
            pix = QPixmap()
            if pix.loadFromData(data):
                self.skin.setPixmap(pix.scaled(140, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.backend.call_async(fetch, ok, lambda *_: None)

    def _delete(self, name):
        from qfluentwidgets import MessageBox
        box = MessageBox(
            tr("删除账号"),
            tr("将删除账号「{name}」。若为微软账号，刷新令牌也会一并丢失，需重新走设备码 / 浏览器登录。").format(
                name=name),
            self,
        )
        box.yesButton.setText(tr("删除"))
        box.cancelButton.setText(tr("取消"))
        if not box.exec():
            return
        self.backend.remove_account(name)
        self.reload()

    def _use(self, name):
        self.backend.set_active_account(name)
        self.reload()

    def _set_auth_busy(self, busy: bool):
        self._auth_busy = busy
        self.yg_btn.setEnabled(not busy)
        self.n8_btn.setEnabled(not busy)
        self.yg_btn.setText(tr("登录中…") if busy else tr("登录皮肤站"))
        self.n8_btn.setText(tr("登录中…") if busy else tr("登录通行证"))

    def _offline(self):
        name = self.offline.text().strip()
        if not name:
            InfoBar.error(tr("缺少名字"), tr("请填写离线角色名"), parent=self,
                          position=InfoBarPosition.TOP, duration=2500)
            return
        self.backend.add_offline_account(
            name, {"Steve": "steve", "Alex": "alex"}.get(self.skin_box.currentText(), "default"))
        self.reload()

    def _ms(self):
        if self._login_dlg:
            return
        self._login_dlg = DeviceCodeDialog(self.window())
        self._login_task = self.backend.start_microsoft_login()
        self._login_dlg.exec()
        self._login_dlg = None
        self.reload()

    def _ygg(self):
        if self._auth_busy:
            return
        api = self.api.text().strip()
        if not api:
            InfoBar.error(tr("缺少地址"), tr("请填写 Yggdrasil API"), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)
            return
        self._set_auth_busy(True)
        self._login_task = self.backend.start_authlib_login(
            api, self.user.text().strip(), self.pw.text())

    def _nide8(self):
        if self._auth_busy:
            return
        sid = self.nide8_id.text().strip()
        if not sid:
            InfoBar.error(tr("缺少服务器 ID"), tr("请填写统一通行证服务器 ID"), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)
            return
        self._set_auth_busy(True)
        self._login_task = self.backend.start_nide8_login(
            sid, self.nide8_user.text().strip(), self.nide8_pw.text())

    def _on_login_code(self, code, uri):
        if self._login_dlg:
            self._login_dlg.show_code(code, uri)

    def _on_login_status(self, text):
        if self._login_dlg:
            self._login_dlg.show_status(text)

    def _on_finished(self, task_id, success, message):
        if task_id != self._login_task:
            return
        if self._auth_busy:
            self._set_auth_busy(False)
        if self._login_dlg and success:
            self._login_dlg.accept()
        if success:
            InfoBar.success(tr("登录成功"), message, parent=self,
                            position=InfoBarPosition.TOP, duration=2500)
            self.reload()
        elif message != tr("已取消"):
            InfoBar.error(tr("登录失败"), message, parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
