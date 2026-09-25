# -*- coding: utf-8 -*-
"""压缩摘要在 Qt 端的可见性回归（2026-09-25）：

- 入库的历史里 id=compact_* 的摘要渲染成一行小字，不是用户气泡；
- agent 发 compact 状态事件时对话流里出现同一行小字（不再静默）；
- _finish 把摘要插在用户这句之前入库，下一轮 agent 才能复用。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.pages.ai_page import AiPage  # noqa: E402
from mclauncher.ai import store as chat_store  # noqa: E402
from mclauncher.ai.result import StopReason  # noqa: E402


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


def _texts(page) -> list:
    """对话流里所有可见文本（气泡与小字行）。"""
    out = []
    for i in range(page.chat.count()):
        wrap = page.chat.itemAt(i)
        if wrap is None or wrap.widget() is None:   # 末尾 stretch 没有 widget
            continue
        for lab in wrap.widget().findChildren(QLabel):
            out.append(lab.text())
    return out


class CompactNoteUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_store = chat_store.STORE_FILE
        chat_store.STORE_FILE = Path(self.tmp.name) / "ai_chats.json"
        chat_store.save({
            "active_id": "cur",
            "chats": [{"id": "cur", "title": "当前", "updated": 1, "messages": []}],
        })

    def tearDown(self):
        chat_store.STORE_FILE = self._old_store
        self.tmp.cleanup()

    def _page(self, messages: list) -> AiPage:
        chat_store.save({
            "active_id": "cur",
            "chats": [{"id": "cur", "title": "当前", "updated": 1,
                       "messages": messages}],
        })
        page = AiPage(FakeBackend())
        self.addCleanup(page.deleteLater)
        return page

    def test_history_compact_message_renders_as_note(self):
        summary = {"role": "user", "content": "[历史摘要]\n早前在装钠",
                   "id": "compact_h30"}
        page = self._page([
            summary,
            {"role": "user", "content": "继续装"},
            {"role": "assistant", "content": "好的"},
        ])
        texts = _texts(page)
        joined = "\n".join(texts)
        self.assertIn("较早的对话已压缩成摘要", joined)
        self.assertNotIn("[历史摘要]", joined, "摘要原文不该以用户气泡形态出现")

    def test_compact_status_shows_note(self):
        page = self._page([])
        before = _texts(page).count("较早的对话已压缩成摘要")
        page._on_status("compact", {"reason": "history_trim"})
        self.assertEqual(_texts(page).count("较早的对话已压缩成摘要"), before + 1)

    def test_finish_persists_summary_before_user(self):
        page = self._page([])
        page._pending_user = "然后呢"
        result = SimpleNamespace(
            stop_reason=StopReason.COMPLETED,
            turn_messages=[
                {"role": "user", "content": "然后呢"},
                {"role": "user", "content": "[历史摘要]\n早前在装钠",
                 "id": "compact_h30"},
                {"role": "assistant", "content": "好的"},
            ],
            usage={"requests": 1},
            plan=[],
        )
        page._finish("好的", True, result)
        roles_ids = [(m.get("role"), str(m.get("id") or ""))
                     for m in page._history]
        self.assertEqual(roles_ids[0], ("user", "compact_h30"),
                         "摘要必须插在用户这句之前入库")
        self.assertEqual(roles_ids[1], ("user", ""))
        self.assertEqual(roles_ids[-1], ("assistant", ""))


if __name__ == "__main__":
    unittest.main()
