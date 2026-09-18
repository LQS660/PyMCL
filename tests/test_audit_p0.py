"""P0 审计缺陷的回归用例：BOM 配置被静默重置、模组「更新」跨 MC 版本 + 删旧文件。

全部离线：临时目录 + 打桩 DownloadManager，不联网、不碰真实 .minecraft。
"""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from mclauncher import mod_update, utils


class BomJsonTests(unittest.TestCase):
    """记事本 / VSCode / PowerShell 存出来的 BOM 文件必须能读回来。

    read_json 若用不带 -sig 的 encoding='utf-8'，遇到 BOM 会抛 JSONDecodeError 后返回
    default —— Config.load() 就会把整份 config.json 当成不存在并重置默认值。
    """

    def test_utf8_bom_config_is_readable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_bytes(b'\xef\xbb\xbf{"theme_color": "#123456", "memory_mb": 8192}')
            data = utils.read_json(path, None)
        self.assertIsInstance(data, dict, "BOM 文件被当成损坏 -> 配置会被静默重置")
        self.assertEqual(data["theme_color"], "#123456")
        self.assertEqual(data["memory_mb"], 8192)

    def test_plain_utf8_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.json"
            utils.write_json(path, {"k": "中文"})
            self.assertEqual(utils.read_json(path, None), {"k": "中文"})

    def test_missing_file_still_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(utils.read_json(Path(td) / "nope.json", {"d": 1}), {"d": 1})


def _fake_instance(root: Path, versions=("1.20.1-fabric",), meta=None):
    inst = SimpleNamespace(name="t", path=root)
    inst.installed_ids = lambda: list(versions)
    inst.meta = lambda: dict(meta or {})
    return inst


def _make_jar(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", '{"id": "demo", "name": "Demo", "version": "1.0"}')


class _StubDM:
    """只回答 mod_update 会问的两个 Modrinth 端点，并记录 URL 供断言。"""

    def __init__(self):
        self.urls: list[str] = []
        self.downloads: list[tuple] = []

    def fetch_json(self, url, timeout=0):
        self.urls.append(url)
        if "/version_file/" in url:
            return {"project_id": "PROJ", "id": "cur", "version_number": "1.0"}
        if "/project/PROJ/version" in url:
            return [{
                "id": "new",
                "version_number": "2.0",
                "game_versions": ["1.20.1"],
                "files": [{
                    "primary": True,
                    "url": "https://example.invalid/demo-2.0.jar",
                    "hashes": {"sha1": "0" * 40},
                    "size": 12,
                    "filename": "demo-2.0.jar",
                }],
            }]
        raise AssertionError(f"unexpected fetch: {url}")


class ModUpdateTargetTests(unittest.TestCase):
    def test_resolve_target_fills_from_instance(self):
        inst = _fake_instance(Path("."), versions=("1.20.1-fabric",))
        mc, loader = mod_update.resolve_target(inst)
        self.assertEqual(mc, "1.20.1")
        self.assertEqual(loader, "fabric")

    def test_explicit_values_win(self):
        inst = _fake_instance(Path("."), versions=("1.20.1-fabric",))
        self.assertEqual(mod_update.resolve_target(inst, "1.7.10", "forge"),
                         ("1.7.10", "forge"))

    def test_check_updates_constrains_query_to_instance_mc_version(self):
        """核心回归：调用方不传 mc_version 时也必须带上过滤条件。

        不带过滤时 Modrinth 返回该项目全部版本里最新的一条，
        apply_update 又会删掉旧 jar —— 1.20.1 的模组会被换成 1.21 的。
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mods = root / "mods"
            _make_jar(mods / "demo-1.0.jar")
            inst = _fake_instance(root, versions=("1.20.1-fabric",))
            dm = _StubDM()
            rows = mod_update.check_updates(inst, dm=dm, mods_path=mods)

        version_query = next((u for u in dm.urls if "/project/PROJ/version" in u), "")
        self.assertTrue(version_query, "没有查询版本列表")
        self.assertIn("game_versions", version_query,
                      "更新查询没有按 MC 版本过滤 -> 会跨版本升级")
        self.assertIn("1.20.1", version_query)
        self.assertIn("loaders", version_query)
        self.assertIn("fabric", version_query)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mc_version"], "1.20.1")
        self.assertIn("1.20.1", rows[0]["game_versions"])


class ApplyUpdateSafetyTests(unittest.TestCase):
    class _EmptyDM:
        """模拟 CurseForge 403 返回错误页 / 空文件（sha1 为空时不会被校验拦住）。"""

        def download(self, url, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"")
            return Path(dest)

    class _ShortDM:
        def download(self, url, dest, **kwargs):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"<html>403</html>")
            return Path(dest)

    def _row(self, size=0):
        return {
            "filename": "demo-1.0.jar",
            "filename_new": "demo-2.0.jar",
            "url": "https://example.invalid/demo-2.0.jar",
            "sha1": "",
            "size": size,
        }

    def test_empty_download_keeps_the_old_jar(self):
        with tempfile.TemporaryDirectory() as td:
            mods = Path(td) / "mods"
            old = mods / "demo-1.0.jar"
            _make_jar(old)
            inst = _fake_instance(Path(td))
            with self.assertRaises(RuntimeError):
                mod_update.apply_update(inst, self._row(), dm=self._EmptyDM(), mods_path=mods)
            self.assertTrue(old.is_file(), "下载失败却把旧 jar 删了")

    def test_size_mismatch_keeps_the_old_jar(self):
        with tempfile.TemporaryDirectory() as td:
            mods = Path(td) / "mods"
            old = mods / "demo-1.0.jar"
            _make_jar(old)
            inst = _fake_instance(Path(td))
            with self.assertRaises(RuntimeError):
                mod_update.apply_update(inst, self._row(size=999999),
                                        dm=self._ShortDM(), mods_path=mods)
            self.assertTrue(old.is_file(), "大小不符却把旧 jar 删了")


if __name__ == "__main__":
    unittest.main()
