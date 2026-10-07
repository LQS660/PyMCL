# -*- coding: utf-8 -*-
"""侧栏自定义：无论怎么勾，都不能把侧栏清空到没有入口。

`SidebarEditorDialog.accept()` 有两条写 `ui_nav_hidden` 的路径——精简档那条
（走混合序列合并）和分组档那条（直接 `sorted(self._hidden_now())`）。「至少留
一项」的护栏以前只加在前者上。实测（offscreen）：分组档 + 全部一级项取消勾选
+ 逐个「取消固定」→ `ui_nav_hidden` 收进全部一级键、`ui_nav_pinned` 写 None，
`nav_items_from_config()` 的 item 数 = 0，侧栏一个入口都不剩，连「设置」都点
不到，只能手改 config.json。

现在两条路径都过 `_ensure_visible`：一级项全隐藏且没有任何固定子页时，把排序
里第一个放出来。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app import main_window as mw  # noqa: E402
from app.pages.layout_settings import SidebarEditorDialog  # noqa: E402
from mclauncher.config import CONFIG  # noqa: E402


class _FakeWin:
    def _rebuild_sections(self):
        pass

    def _rebuild_sidebar(self):
        pass


class SidebarNeverEmptyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._data = {}
        self._real = CONFIG.data
        CONFIG.data = self._data          # nav_items_from_config 读的是同一个 dict
        self._save = mock.patch.object(CONFIG, "save")
        self._save.start()
        self.host = QWidget()
        self.host.resize(600, 400)
        self.addCleanup(self.host.deleteLater)

    def tearDown(self):
        self._save.stop()
        CONFIG.data = self._real

    def _run(self, style: str, *, unpin_all: bool = False):
        self._data.clear()
        self._data["ui_nav_style"] = style
        dlg = SidebarEditorDialog(_FakeWin(), parent=self.host)
        if unpin_all:
            dlg._pinned = []
            dlg._pinned_at_open = []
        for cb in dlg._boxes.values():
            cb.setChecked(False)
        dlg.accept()
        dlg.deleteLater()
        hidden = set(self._data.get("ui_nav_hidden") or [])
        pinned = self._data.get("ui_nav_pinned") or []
        items = [it for it in mw.nav_items_from_config() if it[0] == "item"]
        return hidden, pinned, items

    def _assert_has_entry(self, hidden, pinned, items, where: str):
        self.assertTrue(items, f"{where}：侧栏一个入口都不剩（hidden={sorted(hidden)}）")
        # 放出来的那一项必须真的在最终可见项里
        self.assertFalse(hidden >= set(mw._TOP_KEYS) and not pinned,
                         f"{where}：一级键全隐藏且无固定子页")

    def test_compact_style_keeps_one_entry(self):
        hidden, pinned, items = self._run(mw.NAV_STYLE_COMPACT)
        self._assert_has_entry(hidden, pinned, items, "精简档全不勾")

    def test_grouped_style_keeps_one_entry(self):
        hidden, pinned, items = self._run(mw.NAV_STYLE_GROUPED)
        self._assert_has_entry(hidden, pinned, items, "分组档全不勾")

    def test_grouped_style_with_everything_unpinned_keeps_one_entry(self):
        """原始复现路径：分组档 + 全不勾 + 全部取消固定（这条以前能清空）。"""
        hidden, pinned, items = self._run(mw.NAV_STYLE_GROUPED, unpin_all=True)
        self._assert_has_entry(hidden, pinned, items, "分组档全不勾+全取消固定")

    def test_compact_style_with_everything_unpinned_keeps_one_entry(self):
        hidden, pinned, items = self._run(mw.NAV_STYLE_COMPACT, unpin_all=True)
        self._assert_has_entry(hidden, pinned, items, "精简档全不勾+全取消固定")

    def test_switching_style_after_hiding_everything_still_has_entry(self):
        for first, second in ((mw.NAV_STYLE_GROUPED, mw.NAV_STYLE_COMPACT),
                              (mw.NAV_STYLE_COMPACT, mw.NAV_STYLE_GROUPED)):
            hidden, pinned, _items = self._run(first, unpin_all=True)
            self._data["ui_nav_style"] = second
            items = [it for it in mw.nav_items_from_config() if it[0] == "item"]
            self._assert_has_entry(hidden, pinned, items, f"{first}→{second}")


if __name__ == "__main__":
    unittest.main()
