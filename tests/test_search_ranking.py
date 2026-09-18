"""多源搜索结果的排序与「空查询 = 热门推荐」这条路。

全部打桩，不联网：验证两个平台的下载量被折算到同一把尺子上、上游参数没写错，
以及热门榜拉不回来时才退到内置清单。
"""
from __future__ import annotations

import unittest
from unittest import mock

import bridge.api as bridge_api
from mclauncher import mods as mods_mod

BackendAPI = bridge_api.BackendAPI


class _Shim:
    """借用 BackendAPI 的方法但不构造真实例（真 __init__ 会扫盘、起线程）。"""

    _catalog_source = staticmethod(BackendAPI._catalog_source)
    _gather_hits = staticmethod(BackendAPI._gather_hits)
    _popular_mods_offline = BackendAPI._popular_mods_offline
    search_mods = BackendAPI.search_mods

    def __init__(self):
        self._mod_cache = []


def _hit(title, source, downloads, **kw):
    row = {"title": title, "slug": title.lower(), "source": source, "downloads": downloads}
    row.update(kw)
    return row


class WeightingTests(unittest.TestCase):
    def test_curseforge_and_modrinth_counts_are_normalised(self):
        # mod：CF ×1 / MR ×5，所以 500 万 CF 与 100 万 MR 打平
        self.assertEqual(
            mods_mod.weighted_downloads(_hit("a", "curseforge", 5_000_000), "mod"),
            mods_mod.weighted_downloads(_hit("b", "modrinth", 1_000_000), "mod"))
        # 数据包反过来：CF ×10 / MR ×1
        self.assertEqual(
            mods_mod.weighted_downloads(_hit("a", "curseforge", 100), "datapack"),
            mods_mod.weighted_downloads(_hit("b", "modrinth", 1_000), "datapack"))

    def test_unknown_kind_and_source_fall_back_to_one(self):
        self.assertEqual(mods_mod.weighted_downloads(_hit("a", "elsewhere", 10), "mod"), 10.0)
        self.assertEqual(mods_mod.weighted_downloads(_hit("a", "modrinth", 10), "world"), 50.0)

    def test_missing_or_bad_download_counts_do_not_raise(self):
        for value in (None, "", "n/a", -5):
            self.assertEqual(
                mods_mod.weighted_downloads({"source": "modrinth", "downloads": value}, "mod"),
                0.0, f"downloads={value!r}")


class RankHitsTests(unittest.TestCase):
    def test_empty_query_sorts_purely_by_weighted_downloads(self):
        big_cf = _hit("Journeymap", "curseforge", 50_000_000)
        small_mr = _hit("Tiny", "modrinth", 500)
        # 拼接顺序里 CurseForge 在后，排序后必须翻到前面
        self.assertIs(mods_mod.rank_hits([small_mr, big_cf], "", "mod")[0], big_cf)

    def test_exact_name_beats_a_far_more_popular_stranger(self):
        jei = _hit("JEI", "modrinth", 10_000)
        sodium = _hit("Sodium", "modrinth", 1_000_000_000)
        self.assertIs(mods_mod.rank_hits([sodium, jei], "jei", "mod")[0], jei)

    def test_equal_names_fall_back_to_popularity(self):
        quiet = _hit("Create", "modrinth", 1_000)
        loud = _hit("Create", "modrinth", 100_000_000)
        self.assertIs(mods_mod.rank_hits([quiet, loud], "create", "mod")[0], loud)

    def test_chinese_alias_hits_get_a_bonus(self):
        plain = _hit("Some Mod", "modrinth", 5_000_000)
        alias = _hit("Some Mod", "curseforge", 5_000_000, matched_alias=True)
        self.assertIs(mods_mod.rank_hits([plain, alias], "some mod", "mod")[0], alias)

    def test_nothing_is_dropped_or_duplicated(self):
        batch = [_hit(f"m{i}", "modrinth" if i % 2 else "curseforge", i * 7) for i in range(40)]
        for query in ("", "m1", "沙漠"):
            out = mods_mod.rank_hits(list(batch), query, "mod")
            self.assertEqual(len(out), len(batch), query)
            self.assertEqual({id(h) for h in out}, {id(h) for h in batch}, query)

    def test_identical_hits_do_not_raise_on_tie_break(self):
        same = [{"title": "T", "source": "modrinth", "downloads": 7} for _ in range(20)]
        mods_mod.rank_hits(same, "t", "mod")  # 分数全等时不能掉到比较 dict 上

    def test_non_dicts_are_ignored(self):
        self.assertEqual(mods_mod.rank_hits([None, "x", 3], "", "mod"), [])


class UpstreamParamTests(unittest.TestCase):
    """上游参数写错时，返回的是「最冷门的一页」而不是报错，只能这样盯住。"""

    def test_curseforge_search_asks_for_descending_popularity(self):
        captured = {}

        def fake_fetch(dm, path, api_key=None, params=None):
            captured.update(params or {})
            return {"data": []}

        with mock.patch.object(mods_mod, "_cf_fetch", fake_fetch):
            mods_mod.search_curseforge(mock.Mock(), "sodium")
        self.assertEqual(captured.get("sortField"), 2)
        self.assertEqual(captured.get("sortOrder"), "desc")

    def test_curseforge_page_size_never_exceeds_the_api_cap(self):
        """分类筛选要多取一些，但过了 50 整个请求就是 400，分类页会全空。"""
        captured = {}

        def fake_fetch(dm, path, api_key=None, params=None):
            captured.update(params or {})
            return {"data": []}

        with mock.patch.object(mods_mod, "_cf_fetch", fake_fetch):
            mods_mod.search_curseforge(mock.Mock(), "sodium", limit=30, categories=["tech"])
        self.assertLessEqual(captured.get("pageSize"), mods_mod.CF_MAX_PAGE_SIZE)

    def test_blank_modrinth_query_is_truly_blank(self):
        # 传空格进去 Modrinth 会当成搜一个空格，稳定返回 0 条
        captured = {}
        dm = mock.Mock()

        def fake_json(url, params=None, **kw):
            captured.update(params or {})
            return {"hits": []}

        dm.fetch_json = fake_json
        mods_mod.search_mods(dm, "")
        self.assertEqual(captured.get("query"), "")
        self.assertEqual(captured.get("index"), "downloads")

        captured.clear()
        mods_mod.search_mods(dm, "sodium")
        self.assertEqual(captured.get("query"), "sodium")
        self.assertEqual(captured.get("index"), "relevance")


class PopularRecommendationTests(unittest.TestCase):
    def test_empty_query_pulls_the_live_top_list_and_ranks_it(self):
        api = _Shim()
        with mock.patch.object(bridge_api.mods_mod, "search_mods",
                               return_value=[_hit("Fabric API", "modrinth", 251_000_000)]), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge",
                               return_value=[_hit("JEI", "curseforge", 621_000_000)]):
            rows = api.search_mods("", "全部", {})
        self.assertEqual([r["name"] for r in rows], ["Fabric API", "JEI"],
                         "251M×5 应排在 621M×1 前面")
        self.assertTrue(all(r["downloads"] for r in rows),
                        "热门榜必须带真实下载量，不能再是写死的 0")

    def test_offline_falls_back_to_the_builtin_list(self):
        api = _Shim()
        boom = mock.Mock(side_effect=RuntimeError("no network"))
        with mock.patch.object(bridge_api.mods_mod, "search_mods", boom), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge", boom):
            rows = api.search_mods("", "全部", {})
        self.assertTrue(rows, "断网时仍要给出内置推荐")
        self.assertTrue(all(r["downloads"] == 0 for r in rows))

    def test_a_real_query_still_propagates_failures(self):
        api = _Shim()
        boom = mock.Mock(side_effect=RuntimeError("no network"))
        with mock.patch.object(bridge_api.mods_mod, "search_mods", boom), \
             mock.patch.object(bridge_api.mods_mod, "search_curseforge", boom):
            with self.assertRaises(RuntimeError):
                api.search_mods("sodium", "全部", {})


if __name__ == "__main__":
    unittest.main()
