# -*- coding: utf-8 -*-
"""AI 页思考折叠与会话清理。

模型输出常带 <think>…</think>：不折叠的话思考原文直接铺满气泡，正文被顶到
看不见。这里离屏验证三件事——块摘取（含流式未闭合）、折叠默认收起、复制只
拿正文；以及 store.prune_empty 只清空会话不碰有内容的。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.pages.ai_page import Bubble, ThinkFold, _split_think  # noqa: E402
from mclauncher.ai import store as chat_store  # noqa: E402


class SplitThinkTests(unittest.TestCase):
    def test_closed_block(self):
        parts, answer = _split_think("<think>先查版本</think>装好了")
        self.assertEqual(parts, ["先查版本"])
        self.assertEqual(answer, "装好了")

    def test_unclosed_block_streams(self):
        parts, answer = _split_think("<think>正在想第一")
        self.assertEqual(parts, ["正在想第一"])
        self.assertEqual(answer, "")

    def test_no_think(self):
        parts, answer = _split_think("直接回答")
        self.assertEqual(parts, [])
        self.assertEqual(answer, "直接回答")


class BubbleThinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_final_folds_think(self):
        b = Bubble("assistant", "<think>很长的推理</think>这是答案")
        self.assertIsInstance(b._think, ThinkFold)
        self.assertFalse(b._think._open)          # 默认收起
        self.assertIn("这是答案", b.body.text())   # 正文只剩答案
        self.assertNotIn("很长的推理", b.body.text())
        self.assertNotIn("<think>", b.body.text())

    def test_copy_takes_answer_only(self):
        b = Bubble("assistant", "<think>推理</think>答案正文")
        self.assertEqual(b._answer, "答案正文")
        self.assertEqual(b._plain, "<think>推理</think>答案正文")

    def test_history_reload_also_folds(self):
        b = Bubble("assistant", "<think>a</think>b\nc")
        self.assertEqual(b._answer, "b\nc")
        self.assertIsInstance(b._think, ThinkFold)


class PruneEmptyTests(unittest.TestCase):
    def test_keeps_active_and_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_store.STORE_FILE = Path(tmp) / "ai_sessions.json"
            data = {
                "active_id": "c2",
                "chats": [
                    {"id": "c1", "title": "新对话", "updated": 3, "messages": []},
                    {"id": "c2", "title": "新对话", "updated": 2, "messages": []},
                    {"id": "c3", "title": "实聊", "updated": 1,
                     "messages": [{"role": "user", "content": "hi"}]},
                ],
            }
            chat_store.prune_empty(data)
            ids = [c["id"] for c in data["chats"]]
            self.assertEqual(ids, ["c2", "c3"])   # 空的只留激活那个
            self.assertEqual(data["active_id"], "c2")

    def test_single_empty_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_store.STORE_FILE = Path(tmp) / "ai_sessions.json"
            data = {
                "active_id": "c1",
                "chats": [
                    {"id": "c1", "title": "新对话", "updated": 3, "messages": []},
                    {"id": "c2", "title": "实聊", "updated": 1,
                     "messages": [{"role": "user", "content": "hi"}]},
                ],
            }
            chat_store.prune_empty(data)
            self.assertEqual(len(data["chats"]), 2)


if __name__ == "__main__":
    unittest.main()
