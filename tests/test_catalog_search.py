"""搜索页 → 后端的来源 / 分类 / 错误传播契约。

这些用例全部打桩，不联网：只验证「哪些源被调到、带了什么参数、失败怎么冒泡」。
"""
from __future__ import annotations

import unittest
from unittest import mock

import app.backend as backend_mod

BackendAPI = backend_mod.BackendAPI


class _Shim:
    """借用 BackendAPI 的方法但不构造 QObject（真 __init__ 会扫盘、起线程）。"""

    # 这两个在 BackendAPI 上是 staticmethod，直接赋值会被重新绑成实例方法。
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


class ModSearchSourceTests(unittest.TestCase):
    def test_all_source_queries_both_sites(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_mods",
                               return_value=[_hit("mr-mod")]) as mr, \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               return_value=[_hit("cf-mod")]) as cf:
            rows = api.search_mods("jei", "全部", {})
        self.assertEqual(mr.call_count, 1, "Modrinth must be queried")
        self.assertEqual(cf.call_count, 1, "CurseForge must be queried for 全部")
        self.assertEqual({r["source"] for r in rows}, {"modrinth", "curseforge"})

    def test_single_source_does_not_query_the_other(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_mods",
                               return_value=[_hit("mr-mod")]) as mr, \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               return_value=[_hit("cf-mod")]) as cf:
            api.search_mods("jei", "Modrinth", {})
        self.assertEqual(mr.call_count, 1)
        self.assertEqual(cf.call_count, 0)

    def test_type_filter_reaches_curseforge(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_mods", return_value=[]), \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               return_value=[]) as cf:
            api.search_mods("x", "CurseForge", {"category": "优化"})
        tokens = cf.call_args.kwargs.get("categories")
        self.assertTrue(tokens, "CF category filter must not be dropped")
        self.assertIn("performance", tokens)


class SearchErrorPropagationTests(unittest.TestCase):
    def test_total_failure_raises_instead_of_empty(self):
        api = _Shim()
        boom = RuntimeError("CF key rejected")
        with mock.patch.object(backend_mod.mods_mod, "search_mods", side_effect=boom), \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge", side_effect=boom):
            with self.assertRaises(RuntimeError):
                api.search_mods("jei", "全部", {})

    def test_partial_failure_keeps_working_source(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_mods",
                               return_value=[_hit("mr-mod")]), \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               side_effect=RuntimeError("cf down")):
            rows = api.search_mods("jei", "全部", {})
        self.assertEqual([r["source"] for r in rows], ["modrinth"])


class ContentSearchTests(unittest.TestCase):
    def test_shader_type_filter_reaches_curseforge(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_modrinth_projects",
                               return_value=[]), \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               return_value=[]) as cf:
            api.search_shaders("x", "全部", {"category": "写实"})
        tokens = cf.call_args.kwargs.get("categories")
        self.assertTrue(tokens)
        self.assertIn("realistic", tokens)

    def test_shader_total_failure_raises(self):
        api = _Shim()
        with mock.patch.object(backend_mod.mods_mod, "search_modrinth_projects",
                               side_effect=RuntimeError("mr down")), \
             mock.patch.object(backend_mod.mods_mod, "search_curseforge",
                               side_effect=RuntimeError("cf down")):
            with self.assertRaises(RuntimeError):
                api.search_shaders("x", "全部", {})


class ModpackFallbackTests(unittest.TestCase):
    def test_all_source_fallback_queries_both(self):
        api = _Shim()
        with mock.patch.object(backend_mod.modpack_mod, "search_modpacks_chinese",
                               return_value=[]), \
             mock.patch.object(backend_mod.modpack_mod, "modrinth_search",
                               return_value=[_hit("mr-pack")]) as mr, \
             mock.patch.object(backend_mod.modpack_mod, "search_cf_modpacks",
                               return_value=[_hit("cf-pack")]) as cf:
            rows = api.search_modpacks("rpg", "全部", {})
        self.assertEqual(mr.call_count, 1)
        self.assertEqual(cf.call_count, 1, "CF fallback must run for 全部")
        self.assertEqual({r["source"] for r in rows}, {"modrinth", "curseforge"})


if __name__ == "__main__":
    unittest.main()
