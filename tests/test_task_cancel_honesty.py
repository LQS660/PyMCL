# -*- coding: utf-8 -*-
"""BackendWorker 取消后不许把空结果兜成「任务完成」。

强杀游戏走的就是这条路：`_launch_game_impl` 里 `worker._cancelled` 为真时
直接 return（None），旧代码 emit (True, "任务完成") —— 玩家亲手停掉的游戏，
任务列表却记成功。取消后的空结果必须如实报「已取消」。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.backend import BackendWorker, TaskCancelled  # noqa: E402
from mclauncher.i18n import tr  # noqa: E402


class TaskCancelHonestyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancelled_none_result_reports_cancelled(self):
        w = BackendWorker("t1", lambda progress, log: None)
        seen: list[tuple[bool, str]] = []
        w.task_finished.connect(lambda tid, ok, msg: seen.append((ok, msg)))
        w.cancel()
        w.run()
        self.assertEqual(seen, [(False, tr("已取消"))])

    def test_not_cancelled_none_result_still_complete(self):
        w = BackendWorker("t2", lambda progress, log: None)
        seen: list[tuple[bool, str]] = []
        w.task_finished.connect(lambda tid, ok, msg: seen.append((ok, msg)))
        w.run()
        self.assertEqual(seen, [(True, tr("任务完成"))])

    def test_cancelled_with_real_string_keeps_message(self):
        w = BackendWorker("t3", lambda progress, log: "装完了")
        seen: list[tuple[bool, str]] = []
        w.task_finished.connect(lambda tid, ok, msg: seen.append((ok, msg)))
        w.cancel()
        w.run()
        self.assertEqual(seen, [(True, "装完了")])

    def test_task_cancelled_exception_path_unchanged(self):
        def target(progress, log):
            raise TaskCancelled()

        w = BackendWorker("t4", target)
        seen: list[tuple[bool, str]] = []
        w.task_finished.connect(lambda tid, ok, msg: seen.append((ok, msg)))
        w.run()
        self.assertEqual(seen, [(False, tr("已取消"))])


if __name__ == "__main__":
    unittest.main()
