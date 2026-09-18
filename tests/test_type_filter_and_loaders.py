"""审计回归：分类筛选的本地化归一 + NeoForge 版本表过滤。

全部离线：不联网、不碰 .minecraft、不起进程。
"""
from __future__ import annotations

import unittest
from unittest import mock

from mclauncher import i18n
from mclauncher import loader_meta
from mclauncher.catalog_files import (
    TYPE_FACETS, category_facets, cf_category_tokens, reset_alias_cache, type_key,
)

# 下拉框里出现过的全部类型标签（catalog_page 的 *_SPEC["types"]）
UI_TYPE_LABELS = [
    "优化", "科技", "魔法", "冒险",
    "生存", "空岛", "装饰", "创造",
    "写实", "卡通", "高性能", "光追",
    "现代风", "动态效果",
]
# 这几个是纯数字标签，不进 i18n
UI_RAW_LABELS = ["16x", "32x", "64x"]


class TypeFilterLocalizationTests(unittest.TestCase):
    def setUp(self):
        # i18n.set_language() 会 CONFIG.save()；测试不该改用户的 config.json
        self._patch = mock.patch.object(i18n.CONFIG, "save", lambda: None)
        self._patch.start()
        self._lang = i18n.current_language()
        reset_alias_cache()

    def tearDown(self):
        i18n.set_language(self._lang)
        self._patch.stop()
        reset_alias_cache()

    def _dead(self, lang: str) -> list[str]:
        i18n.set_language(lang)
        dead = []
        for zh in UI_TYPE_LABELS:
            shown = i18n.tr(zh)
            if not category_facets(shown) and not cf_category_tokens(shown):
                dead.append(f"{zh}->{shown}")
        return dead

    def test_every_language_maps_all_type_labels(self):
        """UI 传的是 tr() 之后的文案，任何语言下都不能查不到 facet。"""
        for lang in i18n.available_languages():
            with self.subTest(lang=lang):
                self.assertEqual(
                    self._dead(lang), [],
                    f"这些类型筛选在 {lang} 下会被静默丢弃",
                )

    def test_english_labels_hit_the_right_canonical_key(self):
        i18n.set_language("en")
        expected = {
            "Tech": "technology",
            "Decor": "decoration",
            "High performance": "performance",
            "Ray Tracing": "path-tracing",
            "Motion Effects": "animated",
            "Creative": "creation",
        }
        for label, key in expected.items():
            with self.subTest(label=label):
                self.assertEqual(type_key(label), key)
                self.assertEqual(category_facets(label), TYPE_FACETS[key])

    def test_raw_and_canonical_labels_still_work(self):
        for lang in ("zh_CN", "en"):
            i18n.set_language(lang)
            for raw in UI_RAW_LABELS:
                self.assertTrue(category_facets(raw), f"{raw} @ {lang}")
            self.assertEqual(type_key("optimization"), "optimization")

    def test_all_label_means_no_filter_in_every_language(self):
        for lang in i18n.available_languages():
            i18n.set_language(lang)
            with self.subTest(lang=lang):
                self.assertEqual(type_key(i18n.tr("全部")), "")
                self.assertEqual(category_facets(i18n.tr("全部")), [])

    def test_unknown_label_is_passed_through(self):
        self.assertEqual(type_key("no-such-category"), "no-such-category")
        self.assertEqual(category_facets("no-such-category"), [])


class NeoforgeVersionFilterTests(unittest.TestCase):
    # 真实 maven 里长这样：老号段 `1.20.1-47.x`，新号段 `21.4.x`
    VERSIONS = [
        "1.20.1-47.1.0", "1.20.1-47.1.99",
        "20.2.88", "20.4.190",
        "21.0.167", "21.1.95", "21.1.209",
        "21.4.10", "21.4.140",
    ]

    def test_mapped_version_only_takes_its_own_prefix(self):
        rows = loader_meta.filter_neoforge_versions(self.VERSIONS, "1.21")
        self.assertTrue(rows)
        self.assertTrue(all(v.startswith("21.0.") for v in rows),
                        f"1.21 不该混进 21.1/21.4 的构建: {rows}")

    def test_version_newer_than_the_hardcoded_map_is_derived(self):
        """1.21.4 不在 NEOFORGE_MC_MAP 里，必须按 1.21.4 -> 21.4 推导。"""
        self.assertNotIn("1.21.4", loader_meta.NEOFORGE_MC_MAP)
        rows = loader_meta.filter_neoforge_versions(self.VERSIONS, "1.21.4")
        self.assertEqual(set(rows), {"21.4.10", "21.4.140"})

    def test_unknown_version_returns_empty_not_everything(self):
        """prefix=None 不得退化成「不过滤」把所有 MC 的构建都列出来。"""
        rows = loader_meta.filter_neoforge_versions(self.VERSIONS, "1.19.2")
        self.assertEqual(rows, [])

    def test_legacy_dash_scheme_still_matches(self):
        rows = loader_meta.filter_neoforge_versions(
            ["1.20.1-47.1.0", "1.20.1-47.1.99"], "1.20.1")
        self.assertEqual(set(rows), {"1.20.1-47.1.0", "1.20.1-47.1.99"})

    def test_newest_first(self):
        rows = loader_meta.filter_neoforge_versions(self.VERSIONS, "1.21.4")
        self.assertEqual(rows[0], "21.4.140")

    def test_prefix_matches_installer_rules(self):
        self.assertEqual(loader_meta.neoforge_prefix("1.20.1"), "47.1")
        self.assertEqual(loader_meta.neoforge_prefix("1.21.4"), "21.4")
        self.assertEqual(loader_meta.neoforge_prefix("1.19.2"), "")
        self.assertEqual(loader_meta.neoforge_prefix(""), "")

    def test_empty_input_is_safe(self):
        self.assertEqual(loader_meta.filter_neoforge_versions([], "1.21.4"), [])
        self.assertEqual(loader_meta.filter_neoforge_versions(self.VERSIONS, ""), [])


if __name__ == "__main__":
    unittest.main()
