"""bridge/api.py 必须和 app/backend.py 修得一样。

eziapp / WinUI 走的是这套后端：Qt 那套后端有的每一处修法这里都得有，
否则同一批缺陷在这边原样存在。
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


class BridgeAiPayloadParityTests(unittest.TestCase):
    """W0-7：把文件头那句「bridge/api.py 必须和 app/backend.py 修得一样」变成可执行门禁。

    Qt 侧没有事件 payload（进程内直调 AgentResult），两侧共同的锚点是内核
    AgentResult 的元数据面。所以这里钉死 bridge 事件 payload 的键集合：

    - 桥多发一个键：AgentResult 上取不到值，发出去的是永远为空的死键 → 红；
    - 桥少发一个键（比如内核给 Qt 加了新元数据、桥没跟上）→ 红，
      同一批缺陷在 WPF / eziapp / WinUI 上原样存在，这正是文件头那句规约。
    """

    # chat_id 不是内核元数据，是桥自己的路由键：回合属于哪条对话。用户中途切换 /
    # 新建 / 删除对话时，前端靠它判断「这帖收尾是不是我正看着的对话」，
    # 别把旧对话的报错气泡贴进新对话、也别在切走之后按钮还卡在「忙」上。
    ROUTING_KEYS = {"chat_id"}
    DONE_KEYS = {"text", "store", "stop_reason", "detail", "pending_tasks", "note"} | ROUTING_KEYS
    UI_KEYS = {"note"}
    FAIL_KEYS = {"text", "stopped"} | ROUTING_KEYS
    # rule_content：内核按 RULE_CONTENT_KEYS 从 args 里抽出来的那一项，前端「始终允许」
    # 的说明文案靠它，不用把键表抄进 C#。
    CONFIRM_KEYS = {"name", "args", "label", "reason", "rule_content"}

    def _payload_keys(self, event: str) -> set:
        """AST 抽出 bridge/api.py 里 emit("<event>", {字面量 dict}) 的键集合。"""
        import ast
        src = Path(bridge_api.__file__).read_text("utf-8")
        keys: set = set()
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "emit"):
                continue
            ev = node.args[0]
            if not (isinstance(ev, ast.Constant) and ev.value == event):
                continue
            payload = node.args[1] if len(node.args) > 1 else None
            if isinstance(payload, ast.Dict):
                keys |= {k.value for k in payload.keys if isinstance(k, ast.Constant)}
        return keys

    def test_done_payload_forwards_kernel_metadata(self):
        from mclauncher.ai.result import AgentResult
        result = AgentResult("ok", stop_reason="max_rounds", detail="d",
                             pending_tasks=[{"task_id": "t"}])
        for key in self.DONE_KEYS - {"text", "store"} - self.ROUTING_KEYS - self.UI_KEYS:
            self.assertTrue(hasattr(result, key),
                            f"AgentResult 缺 {key}：bridge 在 ai.done 里发的是死键")
        self.assertEqual(self._payload_keys("ai.done"), self.DONE_KEYS)

    def test_fail_payload_keeps_stopped_flag(self):
        self.assertEqual(self._payload_keys("ai.fail"), self.FAIL_KEYS)

    def test_confirm_payload_carries_reason(self):
        self.assertEqual(self._payload_keys("ai.confirm"), self.CONFIRM_KEYS)


class BridgeAlwaysAllowParityTests(unittest.TestCase):
    """确认卡「始终允许」：Qt 端把 Rule 直接回给内核，桥端得给 WPF 同一条路。

    ai_confirm(ok, always, scope) 靠 confirm_fn 那一刻存下的 (name, args) 拼 Rule；
    scope 决定内核落 per_instance 还是 global。规则增删列三条 RPC 是 WPF 权限面板的后端。
    """

    def setUp(self):
        import tempfile
        from mclauncher.ai import permission as perm
        self._perm = perm
        self._tmp = tempfile.TemporaryDirectory()
        self._old = perm.PERMISSIONS_FILE
        perm.PERMISSIONS_FILE = Path(self._tmp.name) / "ai_permissions.json"
        self.api = BackendAPI(mock.MagicMock())

    def tearDown(self):
        self._perm.PERMISSIONS_FILE = self._old
        self._tmp.cleanup()

    def test_always_builds_rule_from_pending_card(self):
        from mclauncher.ai.permission import Behavior, Rule
        self.api._ai_confirm_ctx = ("install_mod", {"name": "钠", "slug": "sodium"})
        self.api.ai_confirm(True, always=True, scope="global")
        rule = self.api._ai_confirm_ok
        self.assertIsInstance(rule, Rule)
        self.assertEqual((rule.tool_name, rule.rule_content, rule.behavior, rule.scope),
                         ("install_mod", "sodium", Behavior.ALLOW, "global"))

    def test_always_defaults_to_instance_scope_and_plain_ok_stays_bool(self):
        self.api._ai_confirm_ctx = ("delete_mod", {"filename": "a.jar"})
        self.api.ai_confirm(True, always=True)
        self.assertEqual(self.api._ai_confirm_ok.scope, "instance")
        self.api.ai_confirm(True)
        self.assertIs(self.api._ai_confirm_ok, True)
        # 拒绝时 always 无意义，不能拼出规则
        self.api.ai_confirm(False, always=True)
        self.assertIs(self.api._ai_confirm_ok, False)

    def test_rule_rpcs_round_trip(self):
        rows = self.api.ai_permission_rule_add("install_mod", "deny", "sodium", "demo")
        self.assertEqual([(r["toolName"], r["ruleContent"], r["behavior"], r["instance"]) for r in rows],
                         [("install_mod", "sodium", "deny", "demo")])
        rows = self.api.ai_permission_rule_add("launch_game", "ask")
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.api.ai_permission_rules(), rows)
        key = next(r["key"] for r in rows if r["toolName"] == "launch_game")
        rows = self.api.ai_permission_rule_remove(key, "")
        self.assertEqual([r["toolName"] for r in rows], ["install_mod"])
        with self.assertRaises(ValueError):
            self.api.ai_permission_rule_add("no_such_tool")
        with self.assertRaises(ValueError):
            self.api.ai_permission_rule_add("install_mod", "maybe")


class BridgePermissionModeParityTests(unittest.TestCase):
    """W-5：ai_permission_mode 的存取必须跟 app/backend.py 同一套词表。

    WPF / wpf32 的历史遗留值（trusted / strict / readonly）后端认不出；
    这边曾经既不校验也不透传——save_settings 白名单里压根没这几个键，
    前端选什么档位都被静默丢掉。
    """

    def _save(self, data: dict) -> dict:
        patch: dict = {}
        api = BackendAPI(mock.MagicMock())  # save_settings 不碰事件总线，给个空的即可
        with mock.patch.object(bridge_api.CONFIG, "update", side_effect=patch.update), \
             mock.patch.object(bridge_api.CONFIG, "save"):
            api.save_settings(data)
        return patch

    def test_known_mode_is_saved_verbatim(self):
        for mode in ("default", "acceptEdits", "plan", "yolo", "standard", "full"):
            self.assertEqual(self._save({"ai_permission_mode": mode})["ai_permission_mode"], mode)

    def test_unknown_mode_falls_back_like_backend(self):
        self.assertEqual(
            self._save({"ai_permission_mode": "trusted", "ai_confirm_writes": True})
            ["ai_permission_mode"], "default")
        self.assertEqual(
            self._save({"ai_permission_mode": "readonly", "ai_confirm_writes": False})
            ["ai_permission_mode"], "yolo")

    def test_mode_key_absent_is_not_touched(self):
        self.assertNotIn("ai_permission_mode", self._save({"ai_model": "m"}))

    def test_get_settings_returns_normalized_mode(self):
        api = BackendAPI(mock.MagicMock())
        vals = {"ai_permission_mode": "trusted", "ai_confirm_writes": True}
        with mock.patch.object(bridge_api.CONFIG, "get",
                               side_effect=lambda k, d=None: vals.get(k, d)):
            mode = api.get_settings()["ai_permission_mode"]
        from mclauncher.ai.permission import normalize_permission_mode
        self.assertEqual(mode, normalize_permission_mode("trusted", True))


if __name__ == "__main__":
    unittest.main()
