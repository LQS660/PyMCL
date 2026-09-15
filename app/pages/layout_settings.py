# -*- coding: utf-8 -*-
"""个性化布局的设置侧 UI：侧栏编辑对话框 + 布局方案操作助手。"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, ComboBox, FluentIcon as FIF, InfoBar,
    InfoBarPosition, MessageBoxBase, PushButton, SpinBox, StrongBodyLabel,
    SubtitleLabel, ToolButton,
)

from mclauncher.config import CONFIG
from mclauncher.i18n import tr

from .. import layout_model
from ..main_window import (
    NAV_STYLE_COMPACT, NAV_STYLE_GROUPED, NAV_STYLE_LABELS, _NAV_SPECS, _TOP_KEYS,
    nav_items_from_config as nav_items, nav_style, pinned_from_config, sub_title,
)


class SidebarEditorDialog(MessageBoxBase):
    """侧栏自定义：一级项排序 / 显隐 / 宽度。确定后立即生效。"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.win = window
        self.viewLayout.addWidget(SubtitleLabel(tr("自定义侧栏"), self))
        hint = BodyLabel(tr("调整顶部导航的顺序与显示项，以及侧栏宽度。"), self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        style_row = QWidget(self)
        sl = QHBoxLayout(style_row)
        sl.setContentsMargins(0, 4, 0, 4)
        sl.addWidget(BodyLabel(tr("侧栏排法"), self))
        self.style_box = ComboBox(self)
        self._style_keys = {tr(v): k for k, v in NAV_STYLE_LABELS.items()}
        self.style_box.addItems(list(self._style_keys))
        self.style_box.setCurrentText(tr(NAV_STYLE_LABELS[nav_style()]))
        self.style_box.currentTextChanged.connect(self._on_style_changed)
        sl.addWidget(self.style_box, 1)
        self.viewLayout.addWidget(style_row)
        self.style_hint = CaptionLabel("", self)
        self.style_hint.setWordWrap(True)
        self.viewLayout.addWidget(self.style_hint)

        order = [k for k in (CONFIG.get("ui_nav_order") or []) if k in _TOP_KEYS]
        for k in _TOP_KEYS:
            if k not in order:
                order.append(k)
        self._order = order
        hidden = set(CONFIG.get("ui_nav_hidden") or [])
        self._boxes: dict[str, CheckBox] = {}

        self._rows_host = QWidget(self)
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setSpacing(2)
        self.viewLayout.addWidget(self._rows_host)
        self._rebuild_rows(hidden)

        # 固定到侧栏的分区子页（拖拽固定的入口在这里排序/取消）
        from ..main_window import pinned_from_config
        self._pinned = pinned_from_config()
        self._pinned_at_open = list(self._pinned)
        self._grouped_rows = nav_style() == NAV_STYLE_GROUPED
        self.viewLayout.addWidget(StrongBodyLabel(tr("固定到侧栏的子页"), self))
        pin_hint = BodyLabel(
            tr("把分区横条里的子页拖到侧栏即可固定，从侧栏拖回「下载」/「更多」就放回去；"
               "此处可调整顺序或取消固定。"), self)
        pin_hint.setWordWrap(True)
        self.viewLayout.addWidget(pin_hint)
        self._pin_host = QWidget(self)
        QVBoxLayout(self._pin_host).setSpacing(2)
        self.viewLayout.addWidget(self._pin_host)
        self._rebuild_pin_rows()

        width_row = QWidget(self)
        wl = QHBoxLayout(width_row)
        wl.setContentsMargins(0, 8, 0, 0)
        wl.addWidget(BodyLabel(tr("侧栏宽度"), self), 1)
        self.width_spin = SpinBox(self)
        self.width_spin.setRange(140, 320)
        self.width_spin.setSuffix(" px")
        try:
            w = int(CONFIG.get("ui_sidebar_width") or 188)
        except (TypeError, ValueError):
            w = 188
        self.width_spin.setValue(max(140, min(320, w)))
        wl.addWidget(self.width_spin)
        self.viewLayout.addWidget(width_row)

        self._on_style_changed()
        reset = PushButton(tr("恢复默认侧栏"), self)
        reset.clicked.connect(self._reset)
        self.viewLayout.addWidget(reset)
        self.yesButton.setText(tr("确定"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(460)

    def _selected_style(self) -> str:
        return self._style_keys.get(self.style_box.currentText(), NAV_STYLE_COMPACT)

    def _on_style_changed(self, *_a):
        """分组排法的顺序由分组决定，但固定项照样可以在这里取消。"""
        grouped = self._selected_style() == NAV_STYLE_GROUPED
        self._rows_host.setEnabled(not grouped)
        self.style_hint.setText(
            tr("分组排法按「账户 / 游戏 / 通用」分组，下面那份一级项排序不生效"
               "（顺序直接拖侧栏调整）；勾掉的项照样不显示。") if grouped else "")
        self._grouped_rows = grouped
        self._rebuild_pin_rows()

    def _rebuild_rows(self, hidden: set):
        while self._rows.count():
            it = self._rows.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._boxes.clear()
        for idx, key in enumerate(self._order):
            row = QWidget(self._rows_host)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            up = ToolButton(FIF.CARE_UP_SOLID if hasattr(FIF, "CARE_UP_SOLID") else FIF.UP, row)
            down = ToolButton(FIF.CARE_DOWN_SOLID if hasattr(FIF, "CARE_DOWN_SOLID") else FIF.DOWN, row)
            up.setFixedSize(24, 24)
            down.setFixedSize(24, 24)
            up.setEnabled(idx > 0)
            down.setEnabled(idx < len(self._order) - 1)
            up.clicked.connect(lambda _=False, i=idx: self._move(i, -1))
            down.clicked.connect(lambda _=False, i=idx: self._move(i, +1))
            cb = CheckBox(tr(_NAV_SPECS[key][1]), row)
            cb.setChecked(key not in hidden)
            hl.addWidget(up)
            hl.addWidget(down)
            hl.addWidget(cb, 1)
            self._boxes[key] = cb
            self._rows.addWidget(row)

    def _move(self, idx: int, delta: int):
        j = idx + delta
        if j < 0 or j >= len(self._order):
            return
        self._order[idx], self._order[j] = self._order[j], self._order[idx]
        self._rebuild_rows(self._hidden_now())

    def _hidden_now(self) -> set:
        return {k for k, cb in self._boxes.items() if not cb.isChecked()}

    def _rebuild_pin_rows(self):
        lay = self._pin_host.layout()
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not self._pinned:
            lay.addWidget(CaptionLabel(tr("暂无固定项")))
            return
        for idx, key in enumerate(self._pinned):
            row = QWidget(self._pin_host)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            # 分组排法下这里排不了序：顺序归各个分组管，留两颗按不动的箭头
            # 比留两颗按了没反应的强
            if not self._grouped_rows:
                up = ToolButton(FIF.UP, row)
                down = ToolButton(FIF.DOWN, row)
                up.setFixedSize(24, 24)
                down.setFixedSize(24, 24)
                up.setEnabled(idx > 0)
                down.setEnabled(idx < len(self._pinned) - 1)
                up.clicked.connect(lambda _=False, i=idx: self._move_pinned(i, -1))
                down.clicked.connect(lambda _=False, i=idx: self._move_pinned(i, +1))
                hl.addWidget(up)
                hl.addWidget(down)
            name = BodyLabel(sub_title(key), row)
            rm = PushButton(tr("取消固定"), row)
            rm.clicked.connect(lambda _=False, k=key: self._unpin(k))
            hl.addWidget(name, 1)
            hl.addWidget(rm)
            lay.addWidget(row)

    def _move_pinned(self, idx: int, delta: int):
        j = idx + delta
        if 0 <= j < len(self._pinned):
            self._pinned[idx], self._pinned[j] = self._pinned[j], self._pinned[idx]
            self._rebuild_pin_rows()

    def _unpin(self, key: str):
        if key in self._pinned:
            self._pinned.remove(key)
            self._rebuild_pin_rows()

    def _reset(self):
        """恢复出厂侧栏：分组排法；切回精简时是 启动 / 游戏 / 版本管理，其余沉底或收起。"""
        from ..main_window import (
            _DEFAULT_NAV_HIDDEN, _DEFAULT_NAV_ORDER, _DEFAULT_NAV_PINNED, _DEFAULT_NAV_STYLE,
        )
        self.style_box.setCurrentText(tr(NAV_STYLE_LABELS[_DEFAULT_NAV_STYLE]))
        self._order = [k for k in _DEFAULT_NAV_ORDER if k in _TOP_KEYS]
        for k in _TOP_KEYS:
            if k not in self._order:
                self._order.append(k)
        self._rebuild_rows(set(_DEFAULT_NAV_HIDDEN))
        self._pinned = list(_DEFAULT_NAV_PINNED)
        self._rebuild_pin_rows()
        self.width_spin.setValue(188)
        # accept() 平时要把用户拖出来的混排保住，那套合并逻辑会打乱出厂序列。
        # 点过「恢复默认」就绕开它，原样写默认值。
        self._force_defaults = True

    def accept(self):
        style_changed = self._selected_style() != nav_style()
        CONFIG.set("ui_nav_style", self._selected_style())
        if self._selected_style() == NAV_STYLE_GROUPED:
            from ..main_window import grouped_layout, save_grouped_layout
            if getattr(self, "_force_defaults", False):
                # 「恢复默认侧栏」：精简那一档的序列也一起写回出厂值，
                # 不然切过去看到的还是他上次排的那套
                from ..main_window import _DEFAULT_NAV_ORDER, _DEFAULT_NAV_PINNED
                CONFIG.set("ui_nav_order", list(_DEFAULT_NAV_ORDER))
                CONFIG.set("ui_nav_pinned", list(_DEFAULT_NAV_PINNED))
                CONFIG.set("ui_nav_groups", None)
            else:
                dropped = set(self._pinned_at_open) - set(self._pinned)
                if dropped:
                    groups = grouped_layout()
                    for _title, keys in groups:
                        keys[:] = [k for k in keys if k not in dropped]
                    save_grouped_layout(groups)
            CONFIG.set("ui_nav_hidden", sorted(self._hidden_now()))
            CONFIG.set("ui_sidebar_width", int(self.width_spin.value()))
            CONFIG.save()
            self.win._rebuild_sections()
            self.win._rebuild_sidebar()
            super().accept()
            return
        if style_changed:
            # 从分组切回精简：分组那档把一堆子页当成固定项，切回来得重建横条
            self.win._rebuild_sections()
        if getattr(self, "_force_defaults", False):
            from ..main_window import (
                _DEFAULT_NAV_HIDDEN, _DEFAULT_NAV_ORDER, _DEFAULT_NAV_PINNED,
            )
            CONFIG.set("ui_nav_order", list(_DEFAULT_NAV_ORDER))
            CONFIG.set("ui_nav_hidden", list(_DEFAULT_NAV_HIDDEN))
            CONFIG.set("ui_nav_pinned", list(_DEFAULT_NAV_PINNED))
            CONFIG.set("ui_nav_groups", None)
            CONFIG.set("ui_sidebar_width", int(self.width_spin.value()))
            CONFIG.save()
            self.win._rebuild_sections()
            self.win._rebuild_sidebar()
            super().accept()
            return
        hidden = self._hidden_now()
        visible = [k for k in self._order if k not in hidden]
        if not visible:
            # 至少留一项，否则侧栏空了没法导航
            first = self._order[0]
            hidden.discard(first)
            self._boxes[first].setChecked(True)
        # 写回混合序列：一级键换成对话框的新顺序，固定子页保持它们
        # 当前在侧栏里的相对位置（不把用户拖出来的混排压扁）
        from ..main_window import _ALL_SUB_KEYS
        cur = [it[1] for it in nav_items() if it[0] == "item"]
        new_order = list(self._order)
        merged = []
        for k in cur:
            if k in _ALL_SUB_KEYS:
                merged.append(k)
            elif new_order:
                merged.append(new_order.pop(0))
        merged.extend(new_order)
        CONFIG.set("ui_nav_order", merged)
        CONFIG.set("ui_nav_hidden", sorted(hidden))
        CONFIG.set("ui_sidebar_width", int(self.width_spin.value()))
        CONFIG.set("ui_nav_pinned", list(self._pinned) or None)
        CONFIG.save()
        # 取消固定的子页要重新长回分区横条上：只重建侧栏的话，它在侧栏
        # 没了、横条也没补回来，这一页本次运行内就再也点不到了。
        if set(self._pinned_at_open) != set(self._pinned):
            self.win._rebuild_sections()
        self.win._rebuild_sidebar()
        super().accept()


class SectionEditorDialog(MessageBoxBase):
    """分区内容自定义：子页在「下载」/「更多」之间移动，栏内排序。"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.win = window
        from ..main_window import (
            _SUB_DEFAULT_MEMBERS, section_members_from_config, sub_title,
        )
        self._defaults = _SUB_DEFAULT_MEMBERS
        members = section_members_from_config()
        self._members = {k: list(v) for k, v in members.items()}
        self._pinned_set = set(pinned_from_config())

        self.viewLayout.addWidget(SubtitleLabel(tr("自定义分区内容"), self))
        hint = BodyLabel(tr("在「下载」和「更多」之间移动子页，或调整分区内顺序；每栏至少保留一项。"), self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        self._titles = sub_title
        self._hosts: dict[str, QWidget] = {}
        for sec in ("download", "more"):
            head = StrongBodyLabel(tr("下载栏") if sec == "download" else tr("更多栏"), self)
            self.viewLayout.addWidget(head)
            host = QWidget(self)
            QVBoxLayout(host).setSpacing(2)
            self._hosts[sec] = host
            self.viewLayout.addWidget(host)
        self._rebuild_rows()

        reset = PushButton(tr("恢复默认分区"), self)
        reset.clicked.connect(self._reset)
        self.viewLayout.addWidget(reset)
        self.yesButton.setText(tr("确定"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(560)

    def _rebuild_rows(self):
        for sec in ("download", "more"):
            host = self._hosts[sec]
            lay = host.layout()
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.deleteLater()
            keys = self._members[sec]
            other = "more" if sec == "download" else "download"
            for idx, key in enumerate(keys):
                row = QWidget(host)
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(4)
                up = ToolButton(FIF.UP, row)
                down = ToolButton(FIF.DOWN, row)
                up.setFixedSize(24, 24)
                down.setFixedSize(24, 24)
                up.setEnabled(idx > 0)
                down.setEnabled(idx < len(keys) - 1)
                up.clicked.connect(lambda _=False, s=sec, i=idx: self._move(s, i, -1))
                down.clicked.connect(lambda _=False, s=sec, i=idx: self._move(s, i, +1))
                name = BodyLabel(self._titles(key), row)
                move = PushButton(tr("移到「{0}」").format(
                    tr("下载") if other == "download" else tr("更多")), row)
                move.setMinimumWidth(118)
                # 只剩一项时不许移走：移空的那栏点进去就是空壳
                move.setEnabled(len(keys) > 1)
                move.clicked.connect(lambda _=False, s=sec, k=key: self._swap(s, k))
                pin = PushButton(
                    tr("已固定到侧栏") if key in self._pinned_set else tr("固定到侧栏"), row)
                pin.setMinimumWidth(112)
                pin.clicked.connect(lambda _=False, k=key: self._toggle_pin(k))
                hl.addWidget(up)
                hl.addWidget(down)
                hl.addWidget(name, 1)
                hl.addWidget(pin)
                hl.addWidget(move)
                lay.addWidget(row)

    def _move(self, sec: str, idx: int, delta: int):
        keys = self._members[sec]
        j = idx + delta
        if j < 0 or j >= len(keys):
            return
        keys[idx], keys[j] = keys[j], keys[idx]
        self._rebuild_rows()

    def _swap(self, sec: str, key: str):
        other = "more" if sec == "download" else "download"
        if len(self._members[sec]) <= 1:
            return
        self._members[sec].remove(key)
        self._members[other].append(key)
        self._rebuild_rows()

    def _toggle_pin(self, key: str):
        if key in self._pinned_set:
            self._pinned_set.remove(key)
        else:
            self._pinned_set.add(key)
        self._rebuild_rows()

    def _reset(self):
        self._members = {k: list(v) for k, v in self._defaults.items()}
        self._pinned_set = set()
        self._rebuild_rows()

    def accept(self):
        # 移动语义：被固定到侧栏的子页从分区成员里剥离（拖出去就不留在原地）
        members = {sec: [k for k in self._members[sec] if k not in self._pinned_set]
                   for sec in ("download", "more")}
        if not all(members[s] for s in ("download", "more")):
            InfoBar.warning(tr("分区不能为空"), tr("每栏至少保留一个子页"),
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        CONFIG.set("ui_section_members", members)
        # 固定项顺序确定性合并：已有顺序优先，新增按分区成员顺序补
        # （_pinned_set 是 set，直接遍历顺序会随哈希随机化漂移）
        pinned = [k for k in pinned_from_config() if k in self._pinned_set]
        for k in self._members["download"] + self._members["more"]:
            if k in self._pinned_set and k not in pinned:
                pinned.append(k)
        CONFIG.set("ui_nav_pinned", pinned or None)
        CONFIG.save()
        self.win._rebuild_sections()
        self.win._rebuild_sidebar()
        super().accept()


# ----------------------------------------------------------------------
# 布局方案操作（设置页调用）
# ----------------------------------------------------------------------
def default_profile_label() -> str:
    return tr("默认布局")


def profile_labels() -> tuple[list[str], list[str]]:
    """(显示名列表, 方案名列表)；首项恒为「默认布局」。"""
    names = sorted(layout_model.list_profiles().keys())
    labels = [default_profile_label()] + names
    return labels, [""] + names


def switch_profile(name: str, window) -> bool:
    doc = layout_model.activate_profile(name)
    page = getattr(window, "launch_page", None)
    if page is not None:
        page.apply_doc(doc)
    return True


def save_current_as_profile(name: str, window) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    page = getattr(window, "launch_page", None)
    doc = page.canvas.current_doc() if page is not None else layout_model.load_active_doc()
    layout_model.save_profile(name, doc)
    return True


def delete_profile(name: str, window) -> bool:
    if not name:
        layout_model.reset_to_default()
        switch_profile("", window)
        return True
    ok = layout_model.delete_profile(name)
    if ok:
        switch_profile(layout_model.active_profile(), window)
    return ok


def export_current_layout(window, parent) -> bool:
    page = getattr(window, "launch_page", None)
    doc = page.canvas.current_doc() if page is not None else layout_model.load_active_doc()
    path, _ = QFileDialog.getSaveFileName(
        parent, tr("导出布局"), "pymcl-layout.json", "JSON (*.json)")
    if not path:
        return False
    if not layout_model.export_doc(doc, path):
        InfoBar.error(tr("导出失败"), path, parent=parent,
                      position=InfoBarPosition.TOP, duration=3000)
        return False
    InfoBar.success(tr("已导出"), path, parent=parent,
                    position=InfoBarPosition.TOP, duration=2500)
    return True


def import_layout_file(window, parent) -> bool:
    path, _ = QFileDialog.getOpenFileName(
        parent, tr("导入布局"), "", "JSON (*.json)")
    if not path:
        return False
    doc = layout_model.import_doc(path)
    if doc is None:
        InfoBar.error(tr("导入失败"), tr("不是有效的布局文件"), parent=parent,
                      position=InfoBarPosition.TOP, duration=3000)
        return False
    layout_model.save_active_doc(doc)
    page = getattr(window, "launch_page", None)
    if page is not None:
        page.apply_doc(doc)
    InfoBar.success(tr("已导入"), tr("布局已应用，可直接「另存为方案」保留"), parent=parent,
                    position=InfoBarPosition.TOP, duration=3000)
    return True
