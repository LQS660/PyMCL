# -*- coding: utf-8 -*-
"""拖进窗口的文件往哪儿放。

认类型的活在 app/file_kinds.py，这里只负责「认准了就直接办、拿不准就问一句」
以及真正的落地动作。整合包仍旧走主窗口那条老路（认包 → 确认 → 建新版本），
两个入口的行为必须是同一套。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, InfoBar, InfoBarPosition, MessageBoxBase, RadioButton,
    StrongBodyLabel, SubtitleLabel,
)

from ..file_kinds import (
    ALL_KINDS, DATAPACK, KIND_ACTIONS, KIND_LABELS, MOD, MODPACK, RESOURCEPACK,
    SHADERPACK, SKIN, WALLPAPER, WORLD, identify,
)
from mclauncher.i18n import tr

# 走 backend.install_<x>(name, instance, extra) 那一套的类型
_INSTALLERS = {
    MOD: "install_mod",
    RESOURCEPACK: "install_resourcepack",
    SHADERPACK: "install_shader",
    DATAPACK: "install_datapack",
    WORLD: "install_world",
}


class FileKindDialog(MessageBoxBase):
    """拿不准这个文件是什么时，让用户指一下。"""

    def __init__(self, info: dict, others: int = 0, parent=None):
        super().__init__(parent)
        self._kind = ""
        kinds = list(info.get("kinds") or []) or list(ALL_KINDS)

        self.viewLayout.addWidget(SubtitleLabel(tr("这个文件放哪儿？"), self))
        self.viewLayout.addWidget(StrongBodyLabel(info.get("name") or "", self))
        detail = CaptionLabel(info.get("detail") or "", self)
        detail.setWordWrap(True)
        self.viewLayout.addWidget(detail)

        host = QWidget(self)
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(6)
        self._group = QButtonGroup(self)
        for index, kind in enumerate(kinds):
            radio = RadioButton(
                f"{tr(KIND_LABELS.get(kind, kind))} — {tr(KIND_ACTIONS.get(kind, ''))}", host)
            radio.setProperty("kind", kind)
            if index == 0:
                radio.setChecked(True)
            self._group.addButton(radio)
            box.addWidget(radio)
        self.viewLayout.addWidget(host)

        if others:
            note = CaptionLabel(
                tr("这一批里还有 {0} 个同样认不准的文件，会照同一个选择处理。").format(others), self)
            note.setWordWrap(True)
            self.viewLayout.addWidget(note)

        self.yesButton.setText(tr("就这么放"))
        self.cancelButton.setText(tr("算了"))
        self.widget.setMinimumWidth(420)

    def kind(self) -> str:
        button = self._group.checkedButton()
        return str(button.property("kind")) if button else ""


def handle_dropped_files(window, paths: list[str]) -> None:
    """拖进主窗口的一批文件：认准的直接办，拿不准的问一句再办。"""
    infos = [identify(p) for p in paths if p]
    if not infos:
        return
    buckets: dict[str, list[str]] = {}
    unsure: list[dict] = []
    for info in infos:
        if info["sure"] and len(info["kinds"]) == 1:
            buckets.setdefault(info["kinds"][0], []).append(info["path"])
        else:
            unsure.append(info)

    if unsure:
        # 只问一次：剩下候选完全相同的那些照这个答案办，别连弹 N 个框
        head = unsure[0]
        same = [i for i in unsure if i["kinds"] == head["kinds"]]
        dialog = FileKindDialog(head, len(same) - 1, window)
        if dialog.exec() and dialog.kind():
            buckets.setdefault(dialog.kind(), []).extend(i["path"] for i in same)
        skipped = [i for i in unsure if i not in same]
        if skipped:
            InfoBar.info(
                tr("有文件没处理"),
                tr("这些认不出来，可以单独拖进来再选：") + "、".join(
                    i["name"] for i in skipped[:3]),
                parent=window, position=InfoBarPosition.TOP_RIGHT, duration=5000)

    for kind, group in buckets.items():
        _dispatch(window, kind, group)


def _dispatch(window, kind: str, paths: list[str]) -> None:
    try:
        message = _apply(window, kind, paths)
    except Exception as exc:  # noqa: BLE001
        InfoBar.error(tr("没能处理"), f"{os.path.basename(paths[0])} — {exc}",
                      parent=window, position=InfoBarPosition.TOP_RIGHT, duration=6000)
        return
    if message:
        InfoBar.success(tr(KIND_LABELS.get(kind, kind)), message, parent=window,
                        position=InfoBarPosition.TOP_RIGHT, duration=3500)


def _apply(window, kind: str, paths: list[str]) -> str:
    if kind == MODPACK:
        # 一次只处理一个：每个包都要单独确认版本名，连弹 N 个框没法用
        window.import_modpack_file(paths[0])
        return ""
    if kind == WALLPAPER:
        return _set_wallpaper(window, paths[0])
    if kind == SKIN:
        return _set_skin(window, paths[0])
    method = _INSTALLERS.get(kind)
    if not method:
        raise ValueError(tr("还不支持这种文件"))
    backend = window.backend
    instance = backend.game_root_name()
    for path in paths:
        getattr(backend, method)(path, instance, extra={
            "path": path, "instance": instance, "source": tr("本地")})
    return tr("已加入下载任务，装完在「{0}」里").format(tr(KIND_LABELS.get(kind, kind)))


def _set_wallpaper(window, path: str) -> str:
    """设为启动器壁纸。文件夹轮播优先级更高，得一起关掉才看得见这一张。"""
    from mclauncher.config import CONFIG
    from ..background import is_video
    had_folder = bool(str(CONFIG.get("ui_background_folder") or "").strip())
    window.backend.save_settings({"ui_background": path, "ui_background_folder": ""})
    kind = tr("动态壁纸") if is_video(path) else tr("背景图")
    if had_folder:
        return tr("已设为{0}，文件夹轮播一并停掉了").format(kind)
    return tr("已设为{0}").format(kind)


def _set_skin(window, path: str) -> str:
    """给离线账号换皮肤。挑哪个账号、宽臂还是细臂，交给账号页那个框。"""
    from .account_page import OfflineSkinDialog
    rows = window.backend.get_account_rows()
    offline = [r for r in rows if r.get("type") == "offline"]
    if not offline:
        raise ValueError(tr("还没有离线账号；先到「账号」页建一个，再把皮肤拖进来"))
    target = next((r for r in offline if r.get("active")), offline[0])
    dialog = OfflineSkinDialog(window.backend, target["name"], window)
    dialog.preset(path)
    if not dialog.exec():
        return ""
    return dialog.apply()
