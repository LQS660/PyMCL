"""bridge/api.py 必须和 app/backend.py 修得一样。

eziapp / WinUI 走的是这套后端，之前只修了 Qt 那套，同一批缺陷在这里原样存在。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bridge.api as bridge_api

BackendAPI = bridge_api.BackendAPI


class _Shim:
    _catalog_source = staticmethod(BackendAPI._catalog_source)
    _gather_hits = staticmethod(BackendAPI._gather_hits)
    _content_row = BackendAPI._content_row
    _modpack_row = BackendAPI._modpack_row
    search_mods = BackendAPI.search_mods
    search_modpacks = BackendAPI.search_modpacks
    _search_content = BackendAPI._search_content
    search_shaders = BackendAPI.search_shaders

    def __init__(self):
        self._mod_cache = []
        self._pack_cache = []


def _hit(name: str) -> dict:
    return {"title": name, "slug": name, "id": name, "downloads": 1}


class BridgeSearchTests(unittest.TestCase):
    def test_all_source_queries_both_sites(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_mods",
                               return_value=[_hit("mr")]) as mr, \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               return_value=[_hit("cf")]) as cf:
            rows = api.search_mods("jei", "全部", {})
        self.assertEqual(mr.call_count, 1)
        self.assertEqual(cf.call_count, 1)
        self.assertEqual({r["source"] for r in rows}, {"modrinth", "curseforge"})

    def test_type_filter_reaches_curseforge(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_mods", return_value=[]), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               return_value=[]) as cf:
            api.search_mods("x", "CurseForge", {"category": "优化"})
        self.assertIn("performance", cf.call_args.kwargs.get("categories") or [])

    def test_total_failure_raises(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_mods",
                               side_effect=RuntimeError("down")), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                api.search_mods("jei", "全部", {})

    def test_partial_failure_keeps_working_source(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_mods",
                               return_value=[_hit("mr")]), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               side_effect=RuntimeError("cf down")):
            rows = api.search_mods("jei", "全部", {})
        self.assertEqual([r["source"] for r in rows], ["modrinth"])

    def test_modpack_fallback_queries_both(self):
        api = _Shim()
        with mock.patch.object(bridge_api.modpack_mod, "search_modpacks_chinese",
                               return_value=[]), \
             mock.patch.object(bridge_api.modpack_mod, "modrinth_search",
                               return_value=[_hit("mr")]) as mr, \
             mock.patch.object(bridge_api.modpack_mod, "search_cf_modpacks",
                               return_value=[_hit("cf")]) as cf:
            rows = api.search_modpacks("rpg", "全部", {})
        self.assertEqual(mr.call_count, 1)
        self.assertEqual(cf.call_count, 1)
        self.assertEqual({r["source"] for r in rows}, {"modrinth", "curseforge"})

    def test_shader_type_filter_reaches_curseforge(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_modrinth_projects",
                               return_value=[]), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               return_value=[]) as cf:
            api.search_shaders("x", "全部", {"category": "写实"})
        self.assertIn("realistic", cf.call_args.kwargs.get("categories") or [])


class BridgeDestructiveDefaultTests(unittest.TestCase):
    def test_delete_modpack_keeps_instance_by_default(self):
        deleted = []
        meta_writes = []
        inst = SimpleNamespace(
            meta=lambda: {"modpack": {"name": "P"}},
            delete=lambda: deleted.append(True),
            set_meta=lambda k, v: meta_writes.append((k, v)),
        )
        api = SimpleNamespace(
            _instance=lambda _n: inst,
            _emit=lambda *_a: None,
            delete_modpack=BackendAPI.delete_modpack,
        )
        BackendAPI.delete_modpack(api, "inst")
        self.assertEqual(deleted, [], "default must not wipe the whole instance")
        self.assertEqual(meta_writes, [("modpack", None)])

        BackendAPI.delete_modpack(api, "inst", purge_instance=True)
        self.assertEqual(deleted, [True])


class BridgeGameDirTests(unittest.TestCase):
    def test_unwritable_dir_raises(self):
        api = SimpleNamespace()
        with mock.patch.object(Path, "mkdir", side_effect=OSError("denied")):
            with self.assertRaises(bridge_api.InstanceError):
                BackendAPI.set_game_dir(api, "Z:/nope/definitely")

    def test_writable_dir_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = []
            api = SimpleNamespace(_emit=lambda *a: emitted.append(a))
            with mock.patch.object(bridge_api.CONFIG, "set") as cset, \
                 mock.patch.object(bridge_api.CONFIG, "save"):
                BackendAPI.set_game_dir(api, td)
            cset.assert_called_once()
            self.assertFalse((Path(td) / ".pymcl-write-test").exists(),
                             "probe file must be cleaned up")


class BridgeSelfUpdateTests(unittest.TestCase):
    def test_bridge_does_not_spawn_replace_script(self):
        """bridge 的 sys.argv[0] 是 bridge 自己，不能用替换脚本自杀式更新。"""
        logs = []
        emitted = []
        api = SimpleNamespace(
            _dm=lambda *_a: None,
            _emit=lambda ev, data: emitted.append((ev, data)),
        )
        with mock.patch("mclauncher.updater.check",
                        return_value={"has_update": True, "latest": "9.9.9",
                                      "message": "发现 9.9.9"}), \
             mock.patch("mclauncher.updater.download", return_value="C:/tmp/new.exe"), \
             mock.patch("mclauncher.updater.apply_exe") as apply_exe:
            out = BackendAPI._self_update_impl(api, lambda *a: None, logs.append)
        apply_exe.assert_not_called()
        self.assertIn("update_staged", [e for e, _ in emitted])
        self.assertIn("new.exe", out)


if __name__ == "__main__":
    unittest.main()
