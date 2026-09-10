"""审计缺陷的回归用例：官方迁移、自更新落地、版本隔离、AI 工具表。

全部离线，用临时目录和打桩，不碰真实 .minecraft、不联网、不起进程。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher import official_migrate as om
from mclauncher import updater
from mclauncher import worlds as worlds_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.defaults import LONG_TOOLS, WRITE_TOOLS


def _fake_instance(root: Path) -> SimpleNamespace:
    inst = SimpleNamespace(name="t", path=root)
    inst.versions_dir = lambda: root / "versions"
    inst.libraries_dir = lambda: root / "libraries"
    inst.assets_dir = lambda: root / "assets"
    return inst


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class OfficialMigrateLibraryTests(unittest.TestCase):
    def _official_tree(self, root: Path):
        """一个 Forge 版本 + 它继承的原版，外加共享 libraries。"""
        _write_json(root / "versions" / "1.20.1" / "1.20.1.json", {
            "id": "1.20.1",
            "libraries": [{
                "name": "com.mojang:logging:1.1.1",
                "downloads": {"artifact": {
                    "path": "com/mojang/logging/1.1.1/logging-1.1.1.jar"}},
            }],
        })
        (root / "versions" / "1.20.1" / "1.20.1.jar").write_bytes(b"vanilla-jar")
        _write_json(root / "versions" / "1.20.1-forge" / "1.20.1-forge.json", {
            "id": "1.20.1-forge",
            "inheritsFrom": "1.20.1",
            "libraries": [{
                "name": "net.minecraftforge:forge:47.2.0",
                "downloads": {"artifact": {
                    "path": "net/minecraftforge/forge/47.2.0/forge-47.2.0.jar"}},
            }],
        })
        for rel in ("com/mojang/logging/1.1.1/logging-1.1.1.jar",
                    "net/minecraftforge/forge/47.2.0/forge-47.2.0.jar"):
            p = root / "libraries" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"lib")

    def test_shared_libraries_are_copied(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "official"
            dest_root = Path(td) / "inst"
            self._official_tree(src)
            inst = _fake_instance(dest_root)

            om._copy_version(src, inst, "1.20.1-forge")

            for rel in ("com/mojang/logging/1.1.1/logging-1.1.1.jar",
                        "net/minecraftforge/forge/47.2.0/forge-47.2.0.jar"):
                self.assertTrue((dest_root / "libraries" / rel).is_file(),
                                f"library not migrated: {rel}")

    def test_inherited_vanilla_json_and_jar_are_copied(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "official"
            dest_root = Path(td) / "inst"
            self._official_tree(src)
            inst = _fake_instance(dest_root)

            om._copy_version(src, inst, "1.20.1-forge")

            self.assertTrue((dest_root / "versions" / "1.20.1" / "1.20.1.jar").is_file())
            self.assertTrue((dest_root / "versions" / "1.20.1" / "1.20.1.json").is_file())
            self.assertTrue((dest_root / "versions" / "1.20.1-forge" / "1.20.1-forge.json").is_file())


class OfficialMigrateAccountTests(unittest.TestCase):
    def test_accounts_are_actually_imported(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            _write_json(src / "launcher_accounts.json", {
                "accounts": {
                    "abc": {
                        "accessToken": "tok-123",
                        "accessTokenExpiresAt": "2099-01-01T00:00:00.000000000Z",
                        "minecraftProfile": {"id": "1234567890abcdef1234567890abcdef",
                                             "name": "Steve"},
                        "type": "Xbox",
                    },
                    "broken": {"type": "Xbox"},
                },
            })
            added = []
            manager = SimpleNamespace(add_account=added.append)

            names = om.import_accounts(src, manager=manager)

        self.assertEqual(names, ["Steve"])
        self.assertEqual(len(added), 1, "profile without minecraftProfile must be skipped")
        self.assertEqual(added[0]["type"], "microsoft")
        self.assertEqual(added[0]["access_token"], "tok-123")
        self.assertGreater(added[0]["expires_at"], 0)

    def test_unparsable_expiry_counts_as_expired(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            _write_json(src / "launcher_accounts.json", {
                "accounts": {"a": {
                    "accessToken": "t",
                    "accessTokenExpiresAt": "not-a-date",
                    "minecraftProfile": {"id": "f" * 32, "name": "Alex"},
                }},
            })
            rows = om.read_official_accounts(src)
        self.assertEqual(rows[0]["expires_at"], 0.0)


class SelfUpdateApplyTests(unittest.TestCase):
    def test_apply_writes_script_that_waits_for_this_pid(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "PyMCL.exe"
            exe.write_bytes(b"old")
            pkg = Path(td) / "new.bin"
            pkg.write_bytes(b"new")

            bat = updater.write_apply_script(str(pkg), exe)
            body = bat.read_text(encoding="gbk")

        self.assertIn(str(pkg), body)
        self.assertIn(str(exe), body)
        self.assertIn("tasklist", body, "must wait for the launcher to exit")
        self.assertIn("start ", body, "must relaunch the new build")

    def test_apply_exe_spawns_the_script(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "PyMCL.exe"
            exe.write_bytes(b"old")
            pkg = Path(td) / "new.bin"
            pkg.write_bytes(b"new")
            with mock.patch.object(sys, "argv", [str(exe)]), \
                 mock.patch("subprocess.Popen") as popen:
                result = updater.apply_exe(str(pkg))
        self.assertEqual(result, "UPDATE_STAGED")
        self.assertEqual(popen.call_count, 1, "the script must actually be launched")

    def test_source_checkout_is_reported_not_staged(self):
        with mock.patch.object(sys, "argv", ["main.py"]), \
             mock.patch("subprocess.Popen") as popen:
            result = updater.apply_exe("whatever")
        self.assertNotEqual(result, "UPDATE_STAGED")
        self.assertEqual(popen.call_count, 0)


class WorldIsolationTests(unittest.TestCase):
    def test_saves_root_follows_version_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inst = _fake_instance(root)
            self.assertEqual(worlds_mod.saves_root(inst, ""), root / "saves")
            with mock.patch("mclauncher.version_settings.game_dir",
                            return_value=root / "versions" / "1.20.1"):
                self.assertEqual(
                    worlds_mod.saves_root(inst, "1.20.1"),
                    root / "versions" / "1.20.1" / "saves")

    def test_install_world_extracts_into_isolated_saves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inst = _fake_instance(root)
            inst.ensure_standard_dirs = lambda: None
            archive = root / "w.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("Cool/level.dat", "x")
            iso = root / "versions" / "1.20.1"
            with mock.patch("mclauncher.version_settings.game_dir", return_value=iso):
                worlds_mod.install_world(None, {"path": str(archive)}, inst,
                                         version_id="1.20.1")
            self.assertTrue((iso / "saves" / "Cool" / "level.dat").is_file())
            self.assertFalse((root / "saves" / "Cool").exists())


class AiToolTableTests(unittest.TestCase):
    def _names(self):
        return {s["function"]["name"] for s in ai_tools.TOOL_SCHEMAS}

    def test_content_and_world_tools_are_exposed(self):
        names = self._names()
        for tool in ("search_content", "search_worlds", "install_world"):
            self.assertIn(tool, names)

    def test_install_world_is_gated_and_backgrounded(self):
        self.assertIn("install_world", WRITE_TOOLS)
        self.assertIn("install_world", LONG_TOOLS)
        self.assertIn("安装地图", ai_tools.confirm_label("install_world", {"name": "X"}))

    def test_search_content_dispatches_by_kind(self):
        calls = {}

        def _shaders(q, src, extra):
            calls["shader"] = (q, src)
            return [{"name": "BSL", "slug": "bsl"}]

        backend = SimpleNamespace(
            search_shaders=_shaders,
            search_resourcepacks=lambda *a: [],
            search_datapacks=lambda *a: [],
            get_instances=lambda: [{"name": "default"}],
        )
        out = ai_tools.execute_tool(
            backend, "search_content", {"kind": "shader", "query": "bsl"})
        self.assertEqual(calls["shader"][0], "bsl")
        self.assertTrue(out)

    def test_search_content_rejects_unknown_kind(self):
        backend = SimpleNamespace(get_instances=lambda: [{"name": "default"}])
        out = ai_tools.execute_tool(backend, "search_content", {"kind": "nope", "query": "x"})
        self.assertIn("未知内容类型", str(out))


if __name__ == "__main__":
    unittest.main()
