# -*- coding: utf-8 -*-
"""首次运行向导：分步走得通，跳过不留痕。

它是新用户见到的第一个界面，也是唯一一次把「拖文件进窗口」「侧栏能排」
这些讲给他听的机会。两条底线：点「下一步」不能把窗口关掉（那样设置就只
写了一半），点「跳过向导」不能偷偷改任何设置。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from mclauncher import config as config_mod  # noqa: E402


class FakeBackend:
    def __init__(self, home: Path):
        self.home = home
        self.saved = None
        self.game_dirs = []

    def get_settings(self):
        return {"game_dir": str(self.home / ".minecraft")}

    def save_settings(self, data):
        self.saved = dict(data)

    def set_game_dir(self, path):
        self.game_dirs.append(path)


class FirstRunWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_file = config_mod.CONFIG_FILE
        config_mod.CONFIG_FILE = Path(self._tmp.name) / "config.json"
        self.host = QWidget()
        self.host.resize(900, 700)
        self.backend = FakeBackend(Path(self._tmp.name))
        from app.pages.first_run import FirstRunDialog
        self.dlg = FirstRunDialog(self.backend, self.host)

    def tearDown(self):
        self.dlg.deleteLater()
        self.host.deleteLater()
        config_mod.CONFIG_FILE = self._real_file
        self._tmp.cleanup()

    def test_next_walks_the_steps_without_closing(self):
        last = self.dlg.stack.count() - 1
        self.assertGreater(last, 0, "一页纸的向导不算向导")
        self.assertFalse(self.dlg.back_btn.isEnabled(), "第一步没有上一步")

        for expected in range(1, last + 1):
            self.dlg.accept()
            self.assertEqual(self.dlg.stack.currentIndex(), expected)
            # 中途 accept() 必须只翻页：真收下了 result 会变成 Accepted，
            # 窗口当场关掉，后面几步的设置一个都问不到
            self.assertEqual(self.dlg.result(), 0, f"第 {expected} 步就把向导关了")
        self.assertEqual(self.dlg.yesButton.text(), "开始使用")
        self.assertIsNone(self.backend.saved, "只是翻页，不该落盘")

    def test_back_returns_to_the_previous_step(self):
        self.dlg.accept()
        self.dlg.accept()
        self.dlg.back_btn.click()

        self.assertEqual(self.dlg.stack.currentIndex(), 1)
        self.assertTrue(self.dlg.back_btn.isEnabled())

    def test_apply_writes_the_three_answers(self):
        self.dlg.apply()

        self.assertIsNotNone(self.backend.saved)
        for key in ("download_source", "default_memory_mb", "default_isolation"):
            self.assertIn(key, self.backend.saved)
        self.assertIs(self.backend.saved["first_run"], False, "写完就别再弹了")
        self.assertEqual(len(self.backend.game_dirs), 1)

    def test_skipping_touches_nothing(self):
        """「跳过向导」走的是 reject：first_run 由主窗口那边落，向导自己别动设置。"""
        self.dlg.cancelButton.click()

        self.assertIsNone(self.backend.saved)
        self.assertEqual(self.backend.game_dirs, [])

    def test_isolation_box_starts_on_the_configured_default(self):
        """出厂默认已经是「完全独立」，向导里就该先选着它。"""
        self.assertEqual(self.dlg._iso_keys.get(self.dlg.iso.currentText()),
                         config_mod.CONFIG.get("default_isolation"))


class FakeSettingsBackend:
    """设置页要的那一整份 get_settings()；save_settings 按局部更新语义合进去。"""

    def __init__(self, home: Path):
        self.home = home
        self.saves = []
        self.game_dirs = []
        self.data = {
            "share_libraries": False, "share_assets": False, "download_threads": 8,
            "default_memory_mb": 4096, "default_resolution": [854, 480],
            "ms_client_id": "", "curseforge_api_key": "",
            "download_source": "auto", "default_isolation": "all",
            "game_dir": str(home / ".minecraft"), "root": str(home),
            "first_run": False,
        }

    def get_settings(self):
        return dict(self.data)

    def get_setting(self, key, default=None):
        return self.data.get(key, default)

    def save_settings(self, data):
        self.saves.append(dict(data))
        self.data.update(data)

    def set_game_dir(self, path):
        self.game_dirs.append(path)
        self.data["game_dir"] = path

    def available_languages(self):
        return {"zh_CN": "简体中文", "en": "English"}

    def get_language(self):
        return "zh_CN"

    def can_undo_background(self):
        return False


class SettingsRerunWizardTests(unittest.TestCase):
    """设置页「启动向导 → 重新运行」：跑完向导，页面控件必须跟着变。

    「保存设置」走的是 collect() 读控件；向导 apply() 直接落盘却不动控件的话，
    用户接着点一次保存，向导刚写的就被旧值悄悄盖回去。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_file = config_mod.CONFIG_FILE
        config_mod.CONFIG_FILE = Path(self._tmp.name) / "config.json"
        self.host = QWidget()
        self.host.resize(1100, 800)
        self.backend = FakeSettingsBackend(Path(self._tmp.name))
        from app.pages.settings_page import SettingsPage
        self.page = SettingsPage(self.backend, self.host)
        from app.pages import first_run
        self._mod = first_run
        self._real_exec = first_run.FirstRunDialog.exec

    def tearDown(self):
        self._mod.FirstRunDialog.exec = self._real_exec
        self.page.deleteLater()
        self.host.deleteLater()
        config_mod.CONFIG_FILE = self._real_file
        self._tmp.cleanup()

    def test_finishing_the_wizard_syncs_the_settings_controls(self):
        new_dir = str(Path(self._tmp.name) / "games")
        opened = []

        def walk_through(dlg):
            opened.append(dlg)
            from mclauncher.i18n import tr
            dlg.memory.setValue(6144)
            dlg.src.setCurrentText(tr("仅 BMCLAPI"))
            dlg.iso.setCurrentText(next(t for t, k in dlg._iso_keys.items() if k == "none"))
            dlg.game_dir.setText(new_dir)
            return 1

        self._mod.FirstRunDialog.exec = walk_through
        self.page.wizard_btn.click()
        self.app.processEvents()

        self.assertEqual(len(opened), 1, "按钮点一下就该弹向导")
        self.assertIs(opened[0].parent(), self.host, "向导挂在主窗口上，遮罩盖整窗")
        self.assertEqual(self.backend.data["download_source"], "bmclapi")
        self.assertEqual(self.backend.data["default_memory_mb"], 6144)
        self.assertEqual(self.backend.data["default_isolation"], "none")
        self.assertEqual(self.backend.game_dirs, [new_dir])

        page = self.page
        self.assertEqual(page.memory_spin.value(), 6144, "内存控件没跟上向导")
        self.assertEqual(page._src_keys.get(page.src_box.currentText()), "bmclapi", "下载源控件没跟上向导")
        self.assertEqual(page._iso_keys.get(page.iso_box.currentText()), "none", "隔离控件没跟上向导")
        self.assertEqual(page.game_dir.text(), new_dir, "目录控件没跟上向导")
        collected = page.collect()
        self.assertEqual(
            (collected["download_source"], collected["default_memory_mb"], collected["default_isolation"]),
            ("bmclapi", 6144, "none"),
            "再点「保存设置」不能把向导刚写的盖回去")

    def test_skipping_the_rerun_changes_nothing(self):
        self._mod.FirstRunDialog.exec = lambda dlg: 0
        before = dict(self.backend.data)

        self.page.wizard_btn.click()
        self.app.processEvents()

        self.assertEqual(self.backend.saves, [])
        self.assertEqual(self.backend.game_dirs, [])
        self.assertEqual(self.backend.data, before)
        self.assertEqual(self.page.memory_spin.value(), 4096)


if __name__ == "__main__":
    unittest.main()
