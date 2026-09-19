# -*- coding: utf-8 -*-
"""Qt AI 对话切换回归：旧回合不能污染新对话。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from app.pages.ai_page import AiPage  # noqa: E402
from mclauncher.ai import store as chat_store  # noqa: E402
from mclauncher.ai.result import AgentResult  # noqa: E402


class FakeBackend(QObject):
    progress = Signal(str, int, int, str)
    finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.settings = {"ai_confirm_writes": True, "ai_permission_mode": "default"}
        self.saved = []

    def get_settings(self):
        return dict(self.settings)

    def save_settings(self, data):
        self.settings.update(data)
        self.saved.append(dict(data))


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


class AiChatSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_store = chat_store.STORE_FILE
        chat_store.STORE_FILE = Path(self.tmp.name) / "ai_chats.json"
        chat_store.save({
            "active_id": "old",
            "chats": [
                {"id": "old", "title": "旧对话", "updated": 2, "messages": []},
                {"id": "new", "title": "新对话", "updated": 1,
                 "messages": [{"role": "user", "content": "已有内容"}]},
            ],
        })
        self.page = AiPage(FakeBackend())

    def tearDown(self):
        self.page.deleteLater()
        self.app.processEvents()
        chat_store.STORE_FILE = self.old_store
        self.tmp.cleanup()

    def _running(self):
        worker = FakeWorker()
        self.page._worker = worker
        self.page._pending_user = "旧回合内容"
        self.page._busy(True)
        return worker

    def test_switch_chat_abandons_worker_and_resets_busy(self):
        worker = self._running()
        item = next(self.page.chat_list.item(i)
                    for i in range(self.page.chat_list.count())
                    if self.page.chat_list.item(i).data(Qt.UserRole) == "new")

        self.page._on_pick_chat(item)
        self.app.processEvents()

        self.assertTrue(worker.cancelled)
        self.assertEqual(worker.waited, [2500])
        self.assertIsNone(self.page._worker)
        self.assertIsNone(self.page._pending_user)
        self.assertEqual(self.page._store["active_id"], "new")
        self.assertTrue(self.page.send_btn.isEnabled())
        self.assertFalse(self.page.stop_btn.isEnabled())

    def test_new_chat_abandons_worker(self):
        worker = self._running()
        old_id = self.page._store["active_id"]

        self.page._new_chat()
        self.app.processEvents()

        self.assertTrue(worker.cancelled)
        self.assertNotEqual(self.page._store["active_id"], old_id)
        self.assertIsNone(self.page._worker)
        self.assertTrue(self.page.send_btn.isEnabled())

    def test_delete_chat_abandons_worker(self):
        worker = self._running()
        old_id = self.page._store["active_id"]

        self.page._delete_chat()
        self.app.processEvents()

        self.assertTrue(worker.cancelled)
        self.assertNotEqual(self.page._store["active_id"], old_id)
        self.assertIsNone(self.page._worker)
        self.assertTrue(self.page.send_btn.isEnabled())

    def test_old_finish_cannot_write_into_new_chat(self):
        worker = self._running()
        item = next(self.page.chat_list.item(i)
                    for i in range(self.page.chat_list.count())
                    if self.page.chat_list.item(i).data(Qt.UserRole) == "new")
        self.page._on_pick_chat(item)
        self.app.processEvents()

        self.page._on_done(AgentResult("旧回合答案"))
        data = chat_store.load()
        new_chat = chat_store.get_chat(data, "new")
        self.assertIsNotNone(new_chat)
        self.assertNotIn("旧回合内容", [m.get("content") for m in new_chat["messages"]])
        self.assertNotIn("旧回合答案", [m.get("content") for m in new_chat["messages"]])
        self.assertTrue(worker.cancelled)


if __name__ == "__main__":
    unittest.main()
