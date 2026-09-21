# -*- coding: utf-8 -*-
"""桥的 save_settings / get_settings 白名单要跟上 Qt 门面（审计 WPF-P1-1 / P1-2 / P2-14 / P2-17）。

WPF 写 ui_background* / theme_color / ui_motion / ui_fly_* / first_run，桥以前的白名单
没有这些键：写进来被静默丢、读出去也没有，两端都提示「已保存」。
"""
from __future__ import annotations

import unittest
from unittest import mock

import bridge.api as bridge_api

BackendAPI = bridge_api.BackendAPI

APPEARANCE_KEYS = (
    "theme_color", "ui_background", "ui_background_folder", "ui_background_shuffle",
    "ui_background_interval", "ui_background_blur", "ui_background_dim",
    "ui_motion", "ui_fly_animation", "ui_fly_duration_ms", "first_run",
)


def _save(data: dict) -> dict:
    patch: dict = {}
    api = BackendAPI(mock.MagicMock())
    with mock.patch.object(bridge_api.CONFIG, "update", side_effect=patch.update), \
         mock.patch.object(bridge_api.CONFIG, "save"):
        api.save_settings(data)
    return patch


class BridgeAppearanceWhitelistTests(unittest.TestCase):
    def test_get_settings_exposes_appearance_and_first_run_keys(self):
        api = BackendAPI(mock.MagicMock())
        settings = api.get_settings()
        for key in APPEARANCE_KEYS:
            self.assertIn(key, settings, key)
        # 与 app/backend.py 的键集对齐：Qt 门面回的每个键桥都得回
        import app.backend as qt_backend  # noqa: WPS433
        import inspect
        src = inspect.getsource(qt_backend.BackendAPI.get_settings)
        import re
        qt_keys = set(re.findall(r'^\s+"([a-z_]+)":', src, re.M))
        missing = sorted(k for k in qt_keys if k not in settings)
        self.assertEqual([], missing, f"桥 get_settings 少了 Qt 门面有的键：{missing}")

    def test_save_settings_writes_wallpaper_keys(self):
        patch = _save({"ui_background": "C:/pics/a.jpg", "ui_background_folder": "",
                       "ui_background_blur": 12, "ui_background_dim": 30,
                       "ui_background_shuffle": True, "ui_background_interval": 99999})
        self.assertEqual(patch["ui_background"], "C:/pics/a.jpg")
        self.assertEqual(patch["ui_background_folder"], "")
        self.assertEqual(patch["ui_background_blur"], 12)
        self.assertEqual(patch["ui_background_dim"], 30)
        self.assertTrue(patch["ui_background_shuffle"])
        self.assertEqual(patch["ui_background_interval"], 1440, "上限与 Qt 一样是 1440 分钟")

    def test_save_settings_pushes_wallpaper_history_like_qt(self):
        vals = {"ui_background": "old.jpg", "ui_background_folder": "",
                "ui_background_history": [], "ui_background_folder_history": []}
        patch: dict = {}
        api = BackendAPI(mock.MagicMock())
        with mock.patch.object(bridge_api.CONFIG, "get",
                               side_effect=lambda k, d=None: vals.get(k, d)), \
             mock.patch.object(bridge_api.CONFIG, "update", side_effect=patch.update), \
             mock.patch.object(bridge_api.CONFIG, "save"):
            api.save_settings({"ui_background": "new.jpg"})
        self.assertEqual(patch["ui_background"], "new.jpg")
        self.assertEqual(patch["ui_background_history"][-1], "old.jpg")

    def test_save_settings_writes_theme_motion_first_run(self):
        patch = _save({"theme_color": "#112233", "ui_motion": False, "ui_fly_animation": False,
                       "ui_fly_duration_ms": 300, "first_run": False})
        self.assertEqual(patch["theme_color"], "#112233")
        self.assertFalse(patch["ui_motion"])
        self.assertFalse(patch["ui_fly_animation"])
        self.assertEqual(patch["ui_fly_duration_ms"], 300)
        self.assertIs(patch["first_run"], False)

    def test_untouched_keys_stay_untouched(self):
        patch = _save({"ai_model": "m"})
        for key in APPEARANCE_KEYS:
            self.assertNotIn(key, patch)


class BridgeReconcileTests(unittest.TestCase):
    """SSE 断线期间丢掉的事件要能对账回来。"""

    def test_list_tasks_reports_running_and_finished(self):
        api = BackendAPI(mock.MagicMock())
        worker = mock.MagicMock()
        api._workers["task-1"] = worker
        api._titles["task-1"] = "安装游戏 1.21"
        api._task_results["task-0"] = (True, "完成")
        out = api.list_tasks()
        self.assertEqual(out["running"], [{"task_id": "task-1", "title": "安装游戏 1.21"}])
        self.assertEqual(out["finished"], [{"task_id": "task-0", "success": True, "message": "完成"}])

    def test_pending_card_only_while_busy(self):
        api = BackendAPI(mock.MagicMock())
        api._ai_pending_card = {"kind": "confirm", "name": "install_mod"}
        self.assertIsNone(api.ai_pending_card(), "没在跑就没有待回答的卡")
        api._ai_busy = True
        self.assertEqual(api.ai_pending_card()["kind"], "confirm")
        with mock.patch.object(bridge_api, "tr", side_effect=lambda s: s):
            with mock.patch("mclauncher.ai.store.load", return_value={"active_id": "", "chats": []}):
                out = api.ai_list_chats()
        self.assertTrue(out["busy"])
        self.assertEqual(out["pending_card"]["kind"], "confirm")

    def test_get_instances_is_cached_and_invalidated_on_ui_changed(self):
        api = BackendAPI(mock.MagicMock())
        with mock.patch.object(bridge_api, "list_instances", return_value=[]) as li:
            api.get_instances()
            per_scan = li.call_count          # 一次全量扫描要调几次 list_instances
            self.assertGreater(per_scan, 0)
            api.get_instances()
            self.assertEqual(li.call_count, per_scan, "2.5s 内第二次读要走缓存")
            api._emit("ui_changed", {})
            api.get_instances()
            self.assertEqual(li.call_count, per_scan * 2, "ui_changed 后缓存要失效")
            api.invalidate_instances()
            api.get_instances()
            self.assertEqual(li.call_count, per_scan * 3)


if __name__ == "__main__":
    unittest.main()
