# -*- coding: utf-8 -*-
"""启动页 preflight 不许在 UI 线程同步跑。

preflight_launch 会起 `java -version` 子进程并扫盘，弱机上秒级耗时；
旧 `_on_launch` 在 UI 线程直接调它，点「启动游戏」整窗卡死。现在经
backend.call_async 进后台线程，UI 线程只收结果弹框。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import qfluentwidgets  # noqa: E402
from mclauncher.config import CONFIG  # noqa: E402


class LaunchPreflightAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.pages.launch_page import LaunchPage
        self._old_box = qfluentwidgets.MessageBox
        qfluentwidgets.MessageBox = _FakeBox
        _FakeBox.result = False
        _FakeBox.last_title = None
        self._p_save = mock.patch.object(CONFIG, "save")
        self._p_save.start()
        self.backend = mock.MagicMock()
        # reload() 会把这些返回值直接塞进下拉框，必须给真实类型
        self.backend.game_root_name.return_value = "default"
        self.backend.get_accounts.return_value = ["离线模式"]
        self.backend.get_account_rows.return_value = []
        self.backend.get_settings.return_value = {}
        self.backend.get_setting.return_value = ""
        self.backend.list_versions.return_value = []
        self.backend.list_java.return_value = []
        self.page = LaunchPage(self.backend)
        self.page.resize(980, 640)

    def tearDown(self):
        self.page.deleteLater()
        self.app.processEvents()
        qfluentwidgets.MessageBox = self._old_box
        self._p_save.stop()

    def _fire(self):
        self.page._on_launch()
        self.assertTrue(self.backend.call_async.called,
                        "preflight 必须经 call_async 进后台线程")
        self.assertFalse(self.backend.preflight_launch.called,
                         "preflight 不许在 UI 线程同步执行")
        args = self.backend.call_async.call_args[0]
        self.assertFalse(self.page.launch_btn.isEnabled(),
                         "预检期间启动按钮该禁用防连点")
        return args[0], args[1], (args[2] if len(args) > 2 else None)

    def test_preflight_runs_via_call_async_then_launches(self):
        fn, on_ok, _on_err = self._fire()
        on_ok({"items": []})
        self.assertTrue(self.backend.launch_game.called, "预检通过后该发起启动")
        self.assertTrue(self.page.launch_btn.isEnabled() is False)

    def test_preflight_error_shows_failure_not_success(self):
        from mclauncher.i18n import tr
        fn, _on_ok, on_err = self._fire()
        self.assertIsNotNone(on_err, "必须给 call_async 传 on_err")
        on_err(RuntimeError("java 没找到"))
        self.assertEqual(_FakeBox.last_title, tr("启动预检失败"))
        self.assertFalse(self.backend.launch_game.called,
                         "预检失败不许继续启动")
        self.assertTrue(self.page.launch_btn.isEnabled(),
                        "预检失败后启动按钮要恢复可用")

    def test_warn_dialog_cancel_does_not_launch(self):
        _fn, on_ok, _on_err = self._fire()
        on_ok({"items": [{"level": "warn", "title": "内存偏大", "detail": "4096MB"}]})
        self.assertFalse(self.backend.launch_game.called,
                         "警告框点了取消，不许静默启动")


class _FakeBox:
    result = False
    last_title = None

    def __init__(self, title, body, parent):
        _FakeBox.last_title = title
        self.yesButton = _FakeBtn()
        self.cancelButton = _FakeBtn()

    def exec(self):
        return _FakeBox.result


class _FakeBtn:
    def setText(self, text):
        pass

    def setDefault(self, on):
        pass

    def setFocus(self):
        pass


if __name__ == "__main__":
    unittest.main()
