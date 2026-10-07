# -*- coding: utf-8 -*-
"""Offline regression tests for download-dock completion signal routing."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from app.pages.tasks_page import DownloadDock, TasksPage
from mclauncher.i18n import tr


class _Backend(QObject):
    task_added = Signal(str, str)
    progress = Signal(str, int, int, str)
    log = Signal(str, str)
    finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.cancelled = []

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)


class DownloadDockCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for name in ("connect", "connect_ex"):
            guard = patch("socket.socket." + name,
                          side_effect=AssertionError("offline test: network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        motion = patch("app.motion.ui_motion_ok", return_value=False)
        motion.start()
        self.addCleanup(motion.stop)
        self.backend = _Backend()
        self.host = QWidget()
        self.dock = DownloadDock(self.backend, self.host)
        self.addCleanup(self.host.deleteLater)

    def _start(self, task_id="download-1", major="17"):
        title = tr("下载 Java") + " " + major
        self.backend.task_added.emit(task_id, title)
        self.backend.progress.emit(task_id, 37, 100, "downloading archive  |  2 MB/s")
        return title

    def _state(self):
        dock = self.dock
        return (dict(dock._active), dock._current, dock.title.text(),
                dock.status.text(), dock.speed.text(), dock.progress.value(),
                dock.log_edit.toPlainText(), dock.isHidden())

    def test_non_download_completion_does_not_change_active_download(self):
        self._start()
        for prefix in ("启动游戏", "微软登录", "皮肤站登录"):
            with self.subTest(prefix=prefix):
                self.backend.task_added.emit("other", tr(prefix) + " example")
                self.assertNotIn("other", self.dock._active)
                before = self._state()
                self.backend.finished.emit("other", True, "unrelated task finished")
                self.assertEqual(self._state(), before)

    def test_non_download_completion_does_not_switch_current_download(self):
        self._start()
        self._start("download-2", "21")
        before = self._state()
        self.backend.finished.emit("launch-1", True, "game stopped")
        self.assertEqual(self.dock._current, "download-2")
        self.assertEqual(self._state(), before)

    def test_unknown_completion_does_not_change_idle_dock(self):
        for success in (True, False):
            with self.subTest(success=success):
                before = self._state()
                self.backend.finished.emit("never-added", success, "unrelated result")
                self.assertEqual(self._state(), before)

    def test_duplicate_completion_does_not_rewrite_final_state(self):
        self._start()
        self.backend.finished.emit("download-1", True, "download finished")
        before = self._state()
        self.backend.finished.emit("download-1", False, "duplicate stale event")
        self.assertEqual(self._state(), before)

    def test_duplicate_completion_does_not_pollute_remaining_download(self):
        self._start()
        self._start("download-2", "21")
        self.backend.finished.emit("download-1", True, "first finished")
        self.backend.progress.emit("download-2", 68, 100, "second running  |  3 MB/s")
        before = self._state()
        self.backend.finished.emit("download-1", False, "duplicate stale event")
        self.assertEqual(self._state(), before)

    def test_active_success_still_completes_and_hides_dock(self):
        self._start()
        self.assertFalse(self.dock.isHidden())
        self.backend.finished.emit("download-1", True, "download finished")
        self.assertEqual(self.dock._active, {})
        self.assertEqual(self.dock.progress.value(), 100)
        self.assertEqual(self.dock.status.text(), tr("✔ 全部完成"))
        self.assertEqual(self.dock.speed.text(), "")
        self.assertTrue(self.dock.log_edit.toPlainText().endswith("download finished"))
        self.assertTrue(self.dock.isHidden())

    def test_active_failure_still_reports_error_without_success_progress(self):
        self._start()
        self.backend.finished.emit("download-1", False, "download failed")
        self.assertEqual(self.dock._active, {})
        self.assertEqual(self.dock.progress.value(), 37)
        self.assertEqual(self.dock.status.text(), "download failed")
        self.assertEqual(self.dock.speed.text(), "")
        self.assertTrue(self.dock.log_edit.toPlainText().endswith("download failed"))
        self.assertTrue(self.dock.isHidden())

    def test_active_cancellation_still_reports_cancellation(self):
        self._start()
        self.backend.finished.emit("download-1", False, tr("已取消"))
        self.assertEqual(self.dock._active, {})
        self.assertEqual(self.dock.status.text(), tr("已取消"))
        self.assertEqual(self.dock.progress.value(), 37)
        self.assertTrue(self.dock.isHidden())

    def test_current_completion_keeps_remaining_download_active(self):
        first = self._start()
        self._start("download-2", "21")
        self.backend.finished.emit("download-2", True, "second finished")
        self.assertEqual(self.dock._active, {"download-1": first})
        self.assertEqual(self.dock._current, "download-1")
        self.assertEqual(self.dock.status.text(), first)
        self.assertFalse(self.dock.isHidden())
        self.backend.progress.emit("download-1", 80, 100, "still downloading  |  4 MB/s")
        self.assertEqual(self.dock.status.text(), "still downloading")
        self.assertEqual(self.dock.progress.value(), 80)
        self.backend.finished.emit("download-1", True, "first finished")
        self.assertEqual(self.dock._active, {})
        self.assertTrue(self.dock.isHidden())

    def test_other_download_failure_does_not_remove_current_download(self):
        self._start()
        second = self._start("download-2", "21")
        self.backend.finished.emit("download-1", False, "first failed")
        self.assertEqual(self.dock._active, {"download-2": second})
        self.assertEqual(self.dock._current, "download-2")
        self.assertEqual(self.dock.status.text(), second)
        self.assertFalse(self.dock.isHidden())
        self.assertIn("first failed", self.dock.log_edit.toPlainText())

    def test_task_page_still_receives_completion_and_clears_finished_cards(self):
        page = TasksPage(self.backend, self.host)
        self._start()
        card = page._cards["download-1"]
        self.backend.finished.emit("download-1", True, "download finished")
        self.assertEqual(page._done, {"download-1"})
        self.assertEqual(card.progress.value(), 100)
        self.assertFalse(card.cancel_btn.isEnabled())
        self.assertTrue(page.clear_btn.isEnabled())
        page.clear_btn.click()
        self.assertEqual(page._cards, {})
        self.assertFalse(page.clear_btn.isEnabled())
        self.assertFalse(page.empty.isHidden())

    def test_task_page_cancel_remains_pending_until_completion(self):
        page = TasksPage(self.backend, self.host)
        self._start()
        card = page._cards["download-1"]
        card.cancel_btn.click()
        self.assertEqual(self.backend.cancelled, ["download-1"])
        self.assertFalse(card.cancel_btn.isEnabled())
        self.assertIn("download-1", self.dock._active)
        self.backend.finished.emit("download-1", False, tr("已取消"))
        self.assertEqual(self.dock._active, {})
        self.assertEqual(page._done, {"download-1"})
        self.assertTrue(card._expanded)


if __name__ == "__main__":
    unittest.main()
