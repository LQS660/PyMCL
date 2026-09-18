# -*- coding: utf-8 -*-
"""强制启动：预检 error 不再一票否决。

· backend / bridge 的 launch_game 增加 force：预检不过时 force=False 照旧 raise，
  force=True 放行，任务日志头记一行 [预检:强制启动]（忽略了哪几条，崩溃归因用）。
· preflight 两条误报治本：mods 里解压成文件夹的降为 warn；
  fabric-api 在全局 Mod 池里能找到时不再报缺失。
"""
from __future__ import annotations

import inspect
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app.backend as backend_mod
import bridge.api as bridge_api
from mclauncher import preflight
from mclauncher.launcher import LaunchError

_ERR_ITEMS = [
    {"level": "error", "code": "java_too_old", "title": "Java 版本过低（需要 17+）", "detail": "当前是 Java 11"},
    {"level": "warn", "code": "disk_warn", "title": "磁盘空间偏低", "detail": "剩余约 1024 MB"},
]


def _pf_result(items):
    return {"ok": not any(i.get("level") == "error" for i in items), "items": items}


class _Inst:
    """check_launch / _launch_game_impl 要的 duck-type（preflight 认 .path 即可）。"""

    def __init__(self, path):
        self.path = Path(path)
        self.name = "default"

    def version_json(self, version):
        return None

    def java_pref(self):
        return "自动选择"


class ForceLaunchTests(unittest.TestCase):
    """直接驱动 _launch_game_impl 走预检闸门。

    force=True 的放行验证：预检 mock 成不通过，闸门之后第一步 launch_flow.prepare
    抛哨兵 RuntimeError——哨兵被抛出而预检没拦，即闸门确实被 force 打开了。
    """

    def _drive(self, api_module, force):
        log_lines = []
        fake = SimpleNamespace(
            is_game_running=lambda: False,
            _instance=lambda name: _Inst("unused"),
            normalize_java_pref=lambda j: "自动选择",
            accounts=SimpleNamespace(
                offline_account=lambda *a, **k: {"name": "Player"},
                launch_props=lambda acc: {"name": "Player"},
            ),
        )
        if api_module is backend_mod:
            fake._account_kind = lambda props, acc=None: "离线"
        else:
            fake._is_offline_account = lambda text: not text or text == "离线模式"
        sentinel = RuntimeError("after-gate-sentinel")
        with mock.patch.object(preflight, "check_launch", return_value=_pf_result(_ERR_ITEMS)), \
             mock.patch.object(api_module, "CONFIG"), \
             mock.patch("mclauncher.version_settings.load", return_value={}), \
             mock.patch("mclauncher.launch_flow.prepare", side_effect=sentinel):
            try:
                api_module.BackendAPI._launch_game_impl(
                    fake, lambda *a, **k: None,
                    lambda line: log_lines.append(str(line)),
                    "default", "1.20.1", "", "Player", 4096, 854, 480,
                    "", None, force)
            except RuntimeError as exc:
                self.assertIs(exc, sentinel)
        return log_lines

    def test_bridge_force_false_still_raises(self):
        with self.assertRaises(LaunchError):
            self._drive(bridge_api, force=False)

    def test_backend_force_false_still_raises(self):
        # _drive 里哨兵靠 RuntimeError 透传，force=False 时预检先 raise，
        # 这里包一层把 LaunchError 原样放出来
        with self.assertRaises(LaunchError):
            self._drive(backend_mod, force=False)

    def test_bridge_force_true_logs_header_and_passes_gate(self):
        lines = self._drive(bridge_api, force=True)
        self.assertTrue(any("[预检:强制启动]" in ln for ln in lines), lines)
        self.assertTrue(any("java_too_old" in ln for ln in lines), lines)

    def test_backend_force_true_logs_header_and_passes_gate(self):
        lines = self._drive(backend_mod, force=True)
        self.assertTrue(any("[预检:强制启动]" in ln for ln in lines), lines)

    def test_launch_game_force_signature_mirrored(self):
        for fn in (backend_mod.BackendAPI.launch_game, bridge_api.BackendAPI.launch_game):
            param = inspect.signature(fn).parameters.get("force")
            self.assertIsNotNone(param, fn)
            self.assertIs(param.default, False)


class PreflightFalsePositiveTests(unittest.TestCase):
    def test_mod_unzipped_downgraded_to_warn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mods = root / "mods"
            mods.mkdir()
            (mods / "unpacked-mod").mkdir()
            pf = preflight.check_launch(_Inst(root), "", memory_mb=0, java_exe="")
            codes = {i["code"]: i["level"] for i in pf["items"]}
            self.assertEqual(codes.get("mod_unzipped"), "warn")

    @staticmethod
    def _make_jar(path: Path, data: dict):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("fabric.mod.json", json.dumps(data))

    def _check_with_global_pool(self, global_dir):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mods = root / "mods"
            mods.mkdir()
            self._make_jar(mods / "mymod.jar",
                           {"id": "mymod", "name": "My Mod", "depends": {"fabric-api": "*"}})
            cfg = SimpleNamespace(get=lambda k, default=None: str(global_dir))
            with mock.patch("mclauncher.global_mods.CONFIG", cfg):
                return preflight.check_launch(_Inst(root), "1.0.0", memory_mb=0, java_exe="")

    def test_fabric_api_found_in_global_pool_not_reported(self):
        with tempfile.TemporaryDirectory() as gd:
            gdir = Path(gd)
            self._make_jar(gdir / "fabric-api.jar", {"id": "fabric-api", "name": "Fabric API"})
            pf = self._check_with_global_pool(gdir)
            codes = {i["code"] for i in pf["items"]}
            self.assertNotIn("mod_missing_fabric_api", codes)

    def test_fabric_api_absent_still_reported(self):
        with tempfile.TemporaryDirectory() as gd:
            pf = self._check_with_global_pool(Path(gd))
            codes = {i["code"] for i in pf["items"]}
            self.assertIn("mod_missing_fabric_api", codes)


if __name__ == "__main__":
    unittest.main()
