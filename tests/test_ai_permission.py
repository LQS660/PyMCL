# -*- coding: utf-8 -*-
"""批次 1：权限模式 + 规则引擎 + 判权 + 旧配置映射 + 规则落盘。全部离线。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mclauncher.ai import permission as perm
from mclauncher.ai.permission import (
    Behavior, Decision, PermissionMode, Rule,
    decide, dedupe_rules, normalize_permission_mode, rule_content_from_input,
)
from mclauncher.ai.tools import TOOL_META


def _meta(name):
    return TOOL_META[name]


class RuleContentTests(unittest.TestCase):
    def test_extraction_order(self):
        """ruleContent 按固定优先级取第一个非空串（判定顺序照抄 ZCode）。"""
        self.assertEqual(
            rule_content_from_input({"url": "u", "command": "c"}),
            "c", "command 优先于 url")
        self.assertEqual(rule_content_from_input({"path": "p", "pattern": "x"}), "p")
        self.assertEqual(rule_content_from_input({"pattern": "x"}), "x")
        self.assertIsNone(rule_content_from_input({"path": "   "}),)
        self.assertIsNone(rule_content_from_input({"instance": "demo"}),
                          "instance 不是标识，不能当 ruleContent")

    def test_launcher_tool_args_are_identifiers(self):
        """启动器工具的标识键也算 ruleContent：勾「始终允许」记到同一项，不是整个工具。"""
        self.assertEqual(rule_content_from_input({"name": "钠", "slug": "sodium"}), "sodium",
                         "slug 比显示名稳定，优先")
        self.assertEqual(rule_content_from_input({"name": "钠"}), "钠")
        self.assertEqual(rule_content_from_input({"filename": "a.jar", "instance": "d"}), "a.jar")
        self.assertEqual(rule_content_from_input({"version": "1.20.1", "loader": "Fabric"}), "1.20.1")
        self.assertEqual(rule_content_from_input({"major": "17"}), "17")

    def test_always_allow_on_delete_mod_stays_per_file(self):
        """删一次 a.jar 勾了「始终允许」，删 b.jar 仍要问——这是改键表的理由。"""
        args = {"filename": "a.jar", "instance": "demo"}
        rule = Rule("delete_mod", rule_content_from_input(args), Behavior.ALLOW)
        same = decide(_meta("delete_mod"), args, "default", [rule])
        other = decide(_meta("delete_mod"), {"filename": "b.jar"}, "default", [rule])
        self.assertEqual(same.decision, Decision.ALLOW)
        self.assertEqual(other.decision, Decision.ASK)


class DecideTests(unittest.TestCase):
    def test_deny_rule_beats_allow_rule(self):
        """deny 压 allow：同工具同时有两条规则时 DENY 赢。"""
        rules = [
            Rule("install_mod", None, Behavior.ALLOW),
            Rule("install_mod", None, Behavior.DENY),
        ]
        res = decide(_meta("install_mod"), {"name": "钠"}, "yolo", rules)
        self.assertEqual(res.decision, Decision.DENY)

    def test_allow_rule_beats_mode_default(self):
        rules = [Rule("install_mod", None, Behavior.ALLOW)]
        res = decide(_meta("install_mod"), {"name": "钠"}, "default", rules)
        self.assertEqual(res.decision, Decision.ALLOW)

    def test_ask_rule_beats_yolo(self):
        rules = [Rule("delete_instance", None, Behavior.ASK)]
        res = decide(_meta("delete_instance"), {"name": "X"}, "yolo", rules)
        self.assertEqual(res.decision, Decision.ASK)

    def test_plan_mode_blocks_writes_even_with_allow_rule(self):
        """plan 模式下写工具必被拦，allow 规则也翻不过来。"""
        rules = [Rule("install_mod", None, Behavior.ALLOW)]
        res = decide(_meta("install_mod"), {"name": "钠"}, PermissionMode.PLAN, rules)
        self.assertEqual(res.decision, Decision.DENY)
        # 只读工具在 plan 下放行
        res = decide(_meta("list_mods"), {}, PermissionMode.PLAN, [])
        self.assertEqual(res.decision, Decision.ALLOW)

    def test_content_rule_matches_only_same_content(self):
        rules = [Rule("write_mod_config", "config/jei.toml", Behavior.ALLOW)]
        ok = decide(_meta("write_mod_config"),
                    {"path": "config/jei.toml", "content": "x"}, "default", rules)
        other = decide(_meta("write_mod_config"),
                       {"path": "config/other.toml", "content": "x"}, "default", rules)
        self.assertEqual(ok.decision, Decision.ALLOW)
        self.assertEqual(other.decision, Decision.ASK)

    def test_mode_defaults(self):
        cases = [
            ("default", "install_mod", Decision.ASK),
            ("acceptEdits", "install_mod", Decision.ALLOW),
            ("acceptEdits", "delete_mod", Decision.ASK),
            ("yolo", "delete_instance", Decision.ALLOW),
            ("bypassPermissions", "launch_game", Decision.ALLOW),
            ("build", "install_mod", Decision.ALLOW),
            ("build", "launch_game", Decision.ASK),
            ("edit", "write_mod_config", Decision.ALLOW),
            ("edit", "launch_game", Decision.ASK),
            ("dontAsk", "install_mod", Decision.DENY),
        ]
        for mode, tool, expect in cases:
            res = decide(_meta(tool), {}, mode, [])
            self.assertEqual(res.decision, expect, f"{mode}/{tool}")

    def test_dedupe_and_apply_updates(self):
        rules = dedupe_rules([
            Rule("a", None, Behavior.ALLOW),
            Rule("a", None, Behavior.ALLOW),
            Rule("a", "", Behavior.ALLOW),   # rule_content=None 与 "" 同 key
        ])
        self.assertEqual(len(rules), 1)
        merged = dedupe_rules(rules + [Rule("b", None, Behavior.DENY)])
        self.assertEqual(len(merged), 2)


class LegacyModeMappingTests(unittest.TestCase):
    def test_standard_maps_to_default(self):
        self.assertEqual(normalize_permission_mode("standard", True), "default")

    def test_full_maps_to_acceptEdits(self):
        self.assertEqual(normalize_permission_mode("full", True), "acceptEdits")

    def test_confirm_off_maps_to_yolo(self):
        """ai_confirm_writes=False → yolo，且优先于档位。"""
        self.assertEqual(normalize_permission_mode("standard", False), "yolo")
        self.assertEqual(normalize_permission_mode("full", False), "yolo")
        self.assertEqual(normalize_permission_mode(None, False), "yolo")

    def test_missing_mode_follows_confirm_switch(self):
        self.assertEqual(normalize_permission_mode(None, True), "default")
        self.assertEqual(normalize_permission_mode("", True), "default")

    def test_new_modes_pass_through(self):
        self.assertEqual(normalize_permission_mode("plan", True), "plan")
        self.assertEqual(normalize_permission_mode("custom", True), "custom")
        self.assertEqual(normalize_permission_mode("dontAsk", True), "dontAsk")
        self.assertEqual(normalize_permission_mode("bogus", True), "default")


class RuleStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = perm.PERMISSIONS_FILE
        perm.PERMISSIONS_FILE = Path(self._tmp.name) / "ai_permissions.json"

    def tearDown(self):
        perm.PERMISSIONS_FILE = self._old
        self._tmp.cleanup()

    def test_append_and_load_with_instance_merge(self):
        perm.append_rule(Rule("search_mods", None, Behavior.ALLOW))            # global
        perm.append_rule(Rule("install_mod", None, Behavior.ALLOW), "demo")    # per-instance
        rules = perm.load_rules("demo")
        names = {(r.tool_name, r.rule_content) for r in rules}
        self.assertIn(("search_mods", None), names)
        self.assertIn(("install_mod", None), names)
        # 换个实例只拿得到 global
        rules = perm.load_rules("other")
        self.assertEqual([r.tool_name for r in rules], ["search_mods"])

    def test_append_dedupes(self):
        perm.append_rule(Rule("search_mods", None, Behavior.ALLOW))
        perm.append_rule(Rule("search_mods", None, Behavior.ALLOW))
        self.assertEqual(len(perm.load_rules()), 1)

    def test_remove_rule(self):
        perm.append_rule(Rule("search_mods", None, Behavior.ALLOW))
        key = perm.load_rules()[0].key()
        self.assertTrue(perm.remove_rule(key))
        self.assertEqual(perm.load_rules(), [])
        self.assertFalse(perm.remove_rule(key))

    def test_remove_rule_scoped_to_one_section(self):
        """同一条规则全局、实例各存一份时，界面点删哪行只删哪行。"""
        perm.append_rule(Rule("install_mod", None, Behavior.ALLOW))
        perm.append_rule(Rule("install_mod", None, Behavior.ALLOW), "demo")
        key = Rule("install_mod", None, Behavior.ALLOW).key()
        self.assertTrue(perm.remove_rule(key, instance="demo"))
        rows = perm.list_stored_rules()
        self.assertEqual([r["instance"] for r in rows], [""], "全局那条得留着")
        self.assertTrue(perm.remove_rule(key, instance=""))
        self.assertEqual(perm.list_stored_rules(), [])

    def test_list_rows_carry_instance_for_frontends(self):
        perm.append_rule(Rule("write_mod_config", "config/a.toml", Behavior.DENY), "demo")
        row = perm.list_stored_rules()[0]
        self.assertEqual((row["toolName"], row["ruleContent"], row["behavior"], row["instance"]),
                         ("write_mod_config", "config/a.toml", "deny", "demo"))

    def test_rule_scope_default_is_instance(self):
        """Rule.scope 只影响落盘位置，不进 key，也不影响去重。"""
        a = Rule("install_mod", "sodium", Behavior.ALLOW)
        b = Rule("install_mod", "sodium", Behavior.ALLOW, scope=perm.SCOPE_GLOBAL)
        self.assertEqual(a.scope, perm.SCOPE_INSTANCE)
        self.assertEqual(a.key(), b.key())
        self.assertEqual(len(dedupe_rules([a, b])), 1)


if __name__ == "__main__":
    unittest.main()
