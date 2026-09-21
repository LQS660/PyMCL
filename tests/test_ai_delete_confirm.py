# -*- coding: utf-8 -*-
"""删除对话必须有确认框：一键误触就丢整段历史，不可恢复。

原 `_delete_chat` 直接 delete_chat 落盘。现在先弹确认：取消 = 什么都没发生
（连正在跑的回合都不许动），确认 = 先收掉回合再删。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import qfluentwidgets  # noqa: E402
from app.pages.ai_page import AiPage  # noqa: E402
from mclauncher.ai import store as chat_store  # noqa: E402
from mclauncher.i18n import tr  # noqa: E402


class FakeBackend(QObject):
    progress = Signal(str, int, int, str)
    finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.settings = {"ai_confirm_writes": True, "ai_permission_mode": "default"}

    def get_settings(self):
        return dict(self.settings)

    def save_settings(self, data):
        self.settings.update(data)


class FakeWorker(QObject):
    delta = Signal(str)
    status = Signal(str, dict)
    need_confirm = Signal(str, dict, str, str)
    need_ask = Signal(list, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.cancelled = False
        self.waited = []

    def cancel(self):
        self.cancelled = True

    def wait(self, timeout):
        self.waited.append(timeout)
        return True


class FakeButton:
    def setText(self, text):
        pass

    def setDefault(self, on):
        pass

    def setFocus(self):
        pass


class FakeMessageBox:
    """记录构造参数，exec() 返回预设值。"""
    last_title = None
    last_body = None
    result = False

    def __init__(self, title, body, parent):
        FakeMessageBox.last_title = title
        FakeMessageBox.last_body = body
        self.yesButton = FakeButton()
        self.cancelButton = FakeButton()

    def exec(self):
        return FakeMessageBox.result


class AiDeleteConfirmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeMessageBox.last_title = None
        FakeMessageBox.last_body = None
        FakeMessageBox.result = False
        self.tmp = tempfile.TemporaryDirectory()
        self._old_box = qfluentwidgets.MessageBox
        qfluentwidgets.MessageBox = FakeMessageBox
        self._old_store = chat_store.STORE_FILE
        chat_store.STORE_FILE = Path(self.tmp.name) / "ai_chats.json"
        chat_store.save({
            "active_id": "cur",
            "chats": [
                {"id": "cur", "title": "当前", "updated": 2, "messages": []},
                # keep 必须非空：页面构造时会 prune_empty 清掉空对话
                {"id": "keep", "title": "别删", "updated": 1,
                 "messages": [{"role": "user", "content": "留着别删"}]},
            ],
        })
        self.page = AiPage(FakeBackend())

    def tearDown(self):
        self.page.deleteLater()
        self.app.processEvents()
        qfluentwidgets.MessageBox = self._old_box
        chat_store.STORE_FILE = self._old_store
        self.tmp.cleanup()

    def _ids(self):
        return [c["id"] for c in chat_store.load()["chats"]]

    def test_cancel_deletes_nothing(self):
        worker = FakeWorker()
        self.page._worker = worker
        FakeMessageBox.result = False
        self.page._delete_chat()
        data = chat_store.load()
        self.assertIn("cur", self._ids())
        self.assertEqual(data["active_id"], "cur")
        self.assertFalse(worker.cancelled, "取消了删除，不该收掉正在跑的回合")
        self.assertIsNotNone(self.page._worker)

    def test_confirm_deletes_active_chat_and_abandons_run(self):
        worker = FakeWorker()
        self.page._worker = worker
        FakeMessageBox.result = True
        self.page._delete_chat()
        data = chat_store.load()
        self.assertNotIn("cur", self._ids())
        self.assertIn("keep", self._ids())
        self.assertNotEqual(data["active_id"], "cur")
        self.assertTrue(worker.cancelled)
        self.assertIsNone(self.page._worker)

    def test_confirm_dialog_is_irreversibility_aware(self):
        FakeMessageBox.result = False
        self.page._delete_chat()
        self.assertEqual(FakeMessageBox.last_title, tr("删除对话"))
        self.assertIn(tr("无法恢复").rstrip("。"),
                      FakeMessageBox.last_body.replace("，", "").replace("。", ""))

    def test_no_active_chat_is_noop_without_dialog(self):
        # 不走 _load_active（它会把 store 重新从盘上拉齐），直接摆一个空 store
        self.page._store = {"active_id": None, "chats": []}
        FakeMessageBox.result = True
        self.page._delete_chat()
        self.assertIsNone(FakeMessageBox.last_title, "没有对话可删，不该弹框")
        self.assertIn("keep", self._ids(), "空 store 上误删不许落盘")


if __name__ == "__main__":
    unittest.main()
