"""启动页自定义布局：数据层下沉 + 桥接 RPC。

eziapp 通过 bridge/api.py 的 *_layout 方法读写与 Qt 版同一组 config.json 键，
这里守住三件事：数据层与 Qt 旧入口等价、RPC 语义对齐 Qt 的 layout_settings、
两套后端方法面同名。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

import bridge.api as bridge_api
from mclauncher import ui_layout as lm
from mclauncher.config import CONFIG

BackendAPI = bridge_api.BackendAPI

LAYOUT_METHODS = (
    "get_layout", "save_layout", "save_layout_profile", "activate_layout_profile",
    "delete_layout_profile", "reset_layout", "import_layout",
)


class _Shim:
    """只借 BackendAPI 的布局方法，不碰它的 __init__（会拉起下载线程等）。"""
    get_layout = BackendAPI.get_layout
    save_layout = BackendAPI.save_layout
    save_layout_profile = BackendAPI.save_layout_profile
    activate_layout_profile = BackendAPI.activate_layout_profile
    delete_layout_profile = BackendAPI.delete_layout_profile
    reset_layout = BackendAPI.reset_layout
    import_layout = BackendAPI.import_layout


def _doc(*types: str, grid: int = 8) -> dict:
    items = []
    for i, t in enumerate(types):
        items.append({"id": f"{t}-{i}", "type": t, "x": 0.1 * i, "y": 0.0,
                      "w": 0.3, "h": 0.3, "z": i, "hidden": False, "settings": {}})
    return {"version": 1, "grid": grid, "items": items}


class _IsolatedConfig(unittest.TestCase):
    """每条用例都在一份拷贝出来的 CONFIG.data 上跑，落盘被拦掉。"""

    def setUp(self):
        data = dict(CONFIG.data)
        data.update({"ui_layout": None, "ui_layouts": {}, "ui_layout_profile": ""})
        self._p_data = mock.patch.object(CONFIG, "data", data)
        self._p_save = mock.patch.object(CONFIG, "save")
        self._p_data.start()
        self.save = self._p_save.start()
        self.api = _Shim()

    def tearDown(self):
        self._p_save.stop()
        self._p_data.stop()


class DataLayerTests(_IsolatedConfig):
    def test_app_layout_model_is_the_same_module(self):
        from app import layout_model
        for name in lm.__all__:
            self.assertIs(getattr(layout_model, name), getattr(lm, name), name)
        # 冒烟脚本 / dashboard 还会碰到的私有名也得在
        self.assertIs(layout_model._cfg, lm._cfg)

    def test_parse_doc_rejects_garbage_and_drops_unknown_types(self):
        self.assertIsNone(lm.parse_doc(None))
        self.assertIsNone(lm.parse_doc({"grid": 8}))
        self.assertIsNone(lm.parse_doc({"items": "nope"}))
        self.assertIsNone(lm.parse_doc(_doc("alien")), "全是未知类型 → 无效")
        doc = lm.parse_doc(_doc("banner", "alien", "notes"))
        self.assertEqual([it.type for it in doc.items], ["banner", "notes"])

    def test_skin_is_a_known_type_for_import(self):
        doc = lm.parse_doc(_doc("skin"))
        self.assertIsNotNone(doc)
        self.assertEqual(doc.items[0].type, "skin")

    def test_default_doc_unchanged(self):
        d = lm.default_doc().to_dict()
        self.assertEqual([it["type"] for it in d["items"]], ["banner", "config", "log", "news"])
        self.assertEqual(d["grid"], 8)
        self.assertEqual(d["version"], 1)


class LayoutRpcTests(_IsolatedConfig):
    def test_get_layout_default_state(self):
        out = self.api.get_layout()
        self.assertEqual(out["profile"], "")
        self.assertEqual(out["profiles"], [])
        self.assertEqual(out["doc"], out["default"])
        self.assertEqual(out["min_sizes"]["banner"], [340, 150])
        self.assertIn("skin", out["min_sizes"])

    def test_save_layout_persists_and_roundtrips(self):
        self.api.save_layout(_doc("banner", "notes", grid=16))
        out = self.api.get_layout()
        self.assertEqual(out["doc"]["grid"], 16)
        self.assertEqual([it["type"] for it in out["doc"]["items"]], ["banner", "notes"])
        self.assertTrue(self.save.called, "必须落盘")

    def test_save_layout_rejects_invalid(self):
        with self.assertRaises(ValueError):
            self.api.save_layout({"grid": 8})
        self.assertIsNone(CONFIG.get("ui_layout"), "无效文档不得覆盖现有布局")

    def test_profile_lifecycle(self):
        self.api.save_layout(_doc("banner", "log"))
        out = self.api.save_layout_profile("工作台")
        self.assertEqual(out["profile"], "工作台")
        self.assertEqual(out["profiles"], ["工作台"])
        self.assertEqual([it["type"] for it in out["doc"]["items"]], ["banner", "log"])

        # 命名方案生效中：save_layout 要同步写回方案表（对齐 Qt LaunchPage）
        self.api.save_layout(_doc("banner", "log", "news"))
        self.assertEqual(len(CONFIG.get("ui_layouts")["工作台"]["items"]), 3)

        # 切回默认再切回方案
        out = self.api.activate_layout_profile("")
        self.assertEqual(out["profile"], "")
        self.assertEqual(out["doc"], out["default"])
        out = self.api.activate_layout_profile("工作台")
        self.assertEqual(out["profile"], "工作台")
        self.assertEqual(len(out["doc"]["items"]), 3)

        # 删除生效中的方案 → 回默认
        out = self.api.delete_layout_profile("工作台")
        self.assertEqual(out["profiles"], [])
        self.assertEqual(out["profile"], "")
        self.assertEqual(out["doc"], out["default"])
        with self.assertRaises(ValueError):
            self.api.delete_layout_profile("不存在")

    def test_save_layout_profile_with_explicit_doc_and_blank_name(self):
        out = self.api.save_layout_profile("A", _doc("news"))
        self.assertEqual([it["type"] for it in out["doc"]["items"]], ["news"])
        with self.assertRaises(ValueError):
            self.api.save_layout_profile("   ")
        with self.assertRaises(ValueError):
            self.api.save_layout_profile("B", {"items": []})

    def test_reset_layout(self):
        self.api.save_layout(_doc("notes"))
        out = self.api.reset_layout()
        self.assertEqual(out["doc"], out["default"])
        self.assertIsNone(CONFIG.get("ui_layout"))

    def test_import_layout_drops_unknown_keeps_profile(self):
        self.api.save_layout_profile("P", _doc("banner"))
        out = self.api.import_layout(_doc("config", "alien", "quick"))
        self.assertEqual([it["type"] for it in out["doc"]["items"]], ["config", "quick"])
        self.assertEqual(out["profile"], "P", "导入不改当前方案名（对齐 Qt import_layout_file）")
        with self.assertRaises(ValueError):
            self.api.import_layout({"items": [{"type": "alien"}]})
        with self.assertRaises(ValueError):
            self.api.import_layout("not a dict")


class BackendParityTests(unittest.TestCase):
    def test_qt_backend_exposes_same_layout_methods(self):
        """app/backend.py 拉 PySide6，这里用 ast 读源码核对方法名，不真 import。"""
        src = Path(__file__).resolve().parents[1] / "app" / "backend.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        names = {
            node.name
            for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == "BackendAPI"
            for node in cls.body if isinstance(node, ast.FunctionDef)
        }
        for m in LAYOUT_METHODS:
            self.assertIn(m, names, f"app/backend.py 缺 {m}")
            self.assertTrue(callable(getattr(BackendAPI, m)), f"bridge/api.py 缺 {m}")


if __name__ == "__main__":
    unittest.main()
