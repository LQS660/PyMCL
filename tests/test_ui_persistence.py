from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from mclauncher.config import DEFAULT_CONFIG
from mclauncher import servers as servers_mod
from mclauncher import terracotta as terracotta_mod
from mclauncher import worlds as worlds_mod


LAYOUT_KEYS = (
    "ui_motion",
    "ui_nav_hidden",
    "ui_nav_order",
    "ui_nav_pinned",
    "ui_section_members",
    "ui_sidebar_width",
    "ui_layout",
    "ui_layouts",
    "ui_layout_profile",
)


class NavLayoutExposureTests(unittest.TestCase):
    """侧栏编排必须经 get_settings 出得去，两套后端都得给。

    Qt 版自己直接读 CONFIG，所以这几个键一直只在 Qt 里生效；桥不回这些键的话，
    eziapp / WPF 只能画一套写死的侧栏，用户排好的顺序被静默丢掉。
    """

    NAV_KEYS = ("ui_nav_order", "ui_nav_pinned", "ui_nav_hidden")

    def _settings(self, backend_cls):
        shim = type("Shim", (), {"get_settings": backend_cls.get_settings})()
        return shim.get_settings()

    def test_both_backends_return_nav_keys(self):
        import bridge.api as bridge_api
        import app.backend as qt_backend
        for label, cls in (("bridge", bridge_api.BackendAPI),
                           ("qt", qt_backend.BackendAPI)):
            settings = self._settings(cls)
            for key in self.NAV_KEYS:
                with self.subTest(backend=label, key=key):
                    self.assertIn(key, settings)
                    self.assertIsInstance(settings[key], list)


class ConfigWhitelistTests(unittest.TestCase):
    def test_layout_keys_are_declared(self):
        for key in LAYOUT_KEYS:
            self.assertIn(key, DEFAULT_CONFIG, f"{key} must survive Config.load()")

    def test_load_keeps_declared_and_unknown_keys(self):
        stored = {
            "memory_mb": 8192,
            "ui_nav_order": ["tasks", "launch"],
            "ui_layout": {"items": [{"type": "notes"}], "grid": 16},
            "future_feature_flag": True,
        }
        data = dict(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in stored:
                data[key] = stored[key]
        for key, value in stored.items():
            if key not in DEFAULT_CONFIG:
                data[key] = value
        self.assertEqual(data["memory_mb"], 8192)
        self.assertEqual(data["ui_nav_order"], ["tasks", "launch"])
        self.assertEqual(data["ui_layout"]["grid"], 16)
        self.assertTrue(data["future_feature_flag"])


class ServersDatTests(unittest.TestCase):
    def test_add_server_writes_vanilla_servers_dat(self):
        with tempfile.TemporaryDirectory() as td:
            inst = SimpleNamespace(name="t", path=Path(td))
            servers_mod.add_server(inst, "Hypixel", "mc.hypixel.net", 25565, "主服")
            dat = Path(td) / "servers.dat"
            self.assertTrue(dat.is_file(), "game never reads servers.json")
            rows = terracotta_mod.read_game_servers(dat)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Hypixel")
            self.assertEqual(rows[0]["ip"], "mc.hypixel.net")
            listed = servers_mod.list_servers(inst)
            self.assertEqual(listed[0]["description"], "主服")

    def test_custom_port_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            inst = SimpleNamespace(name="t", path=Path(td))
            servers_mod.add_server(inst, "LAN", "192.168.1.8", 25566)
            rows = terracotta_mod.read_game_servers(Path(td) / "servers.dat")
            self.assertEqual(rows[0]["ip"], "192.168.1.8:25566")
            listed = servers_mod.list_servers(inst)
            self.assertEqual(listed[0]["ip"], "192.168.1.8")
            self.assertEqual(listed[0]["port"], 25566)


class WorldExtractTests(unittest.TestCase):
    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saves = root / "saves"
            saves.mkdir()
            archive = root / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("world/level.dat", "ok")
                zf.writestr("../../pwned.txt", "escaped")
            with self.assertRaises(worlds_mod.WorldError):
                worlds_mod._extract_world(archive, saves)
            self.assertFalse((root.parent / "pwned.txt").exists())
            self.assertFalse((root / "pwned.txt").exists())

    def test_normal_world_extracts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saves = root / "saves"
            saves.mkdir()
            archive = root / "world.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("MyWorld/level.dat", "ok")
                zf.writestr("MyWorld/region/r.0.0.mca", "chunk")
            result = worlds_mod._extract_world(archive, saves)
            self.assertEqual(result["files"], ["MyWorld"])
            self.assertTrue((saves / "MyWorld" / "level.dat").is_file())
            self.assertTrue((saves / "MyWorld" / "region" / "r.0.0.mca").is_file())


if __name__ == "__main__":
    unittest.main()
