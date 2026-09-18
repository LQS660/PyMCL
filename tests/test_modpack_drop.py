"""拖进窗口的文件到底是不是整合包：probe() 的识别与误判防线。

只认内容不认后缀，所以这里既要证明三种整合包都能认出来，也要证明模组 jar、
资源包这些「同样是 zip」的东西不会被当成整合包弹框。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.pages.modpack_drop import probe, suggest_version_name

MRPACK_INDEX = {
    "formatVersion": 1,
    "game": "minecraft",
    "versionId": "1.4.2",
    "name": "Fabulously Optimized",
    "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.11"},
    "files": [{"path": "mods/a.jar"}, {"path": "mods/b.jar"}],
}
CF_MANIFEST = {
    "manifestType": "minecraftModpack",
    "name": "创造与魔法",
    "version": "2.7",
    "minecraft": {
        "version": "1.20.1",
        "modLoaders": [{"id": "forge-47.2.0", "primary": True}],
    },
    "files": [{"projectID": 1, "fileID": 2}],
}


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_drop_")
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def zip_with(self, name: str, members: dict) -> str:
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as z:
            for rel, content in members.items():
                z.writestr(rel, content if isinstance(content, str) else json.dumps(content))
        return str(path)

    # ---- 认得出来 ----
    def test_mrpack_at_root(self):
        info = probe(self.zip_with("pack.mrpack", {"modrinth.index.json": MRPACK_INDEX}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "mrpack")
        self.assertEqual(info["name"], "Fabulously Optimized")
        self.assertEqual(info["version"], "1.4.2")
        self.assertEqual(info["mc_version"], "1.20.1")
        self.assertEqual(info["loader"], "fabric-loader")
        self.assertEqual(info["loader_version"], "0.15.11")
        self.assertEqual(info["files"], 2)

    def test_mrpack_nested_one_folder_deep(self):
        info = probe(self.zip_with("nested.zip", {"FO-1.4.2/modrinth.index.json": MRPACK_INDEX}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "mrpack")

    def test_mrpack_detected_by_content_not_suffix(self):
        info = probe(self.zip_with("downloaded.bin", {"modrinth.index.json": MRPACK_INDEX}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "mrpack")

    def test_curseforge_manifest(self):
        info = probe(self.zip_with("cf.zip", {"manifest.json": CF_MANIFEST,
                                              "overrides/config/a.toml": "x"}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "curseforge")
        self.assertEqual(info["name"], "创造与魔法")
        self.assertEqual(info["mc_version"], "1.20.1")
        self.assertEqual(info["loader"], "forge")
        self.assertEqual(info["loader_version"], "47.2.0")

    def test_plain_minecraft_dir(self):
        info = probe(self.zip_with("plain.zip", {"mods/a.jar": "x", "config/t.toml": "y",
                                                 "options.txt": "z"}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "plain")
        # 没有 versions/ 就推不出版本，留空交给安装流程去解析
        self.assertEqual(info["mc_version"], "")

    def test_plain_dir_reads_version_and_loader(self):
        info = probe(self.zip_with("plain2.zip", {
            "MyPack/mods/a.jar": "x",
            "MyPack/versions/1.20.1-forge-47.2.0/1.20.1-forge-47.2.0.json": {"id": "x"},
        }))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "plain")
        self.assertEqual(info["mc_version"], "1.20.1")
        self.assertEqual(info["loader"], "forge")

    def test_name_falls_back_to_filename(self):
        info = probe(self.zip_with("我的整合包.zip", {"mods/a.jar": "x", "saves/w/level.dat": "y"}))
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "我的整合包")

    # ---- 不该认 ----
    def test_mod_jar_rejected(self):
        self.assertIsNone(probe(self.zip_with("jei.jar", {
            "fabric.mod.json": "{}", "META-INF/mods.toml": "", "assets/jei/lang/en.json": "{}"})))

    def test_mod_with_bare_manifest_rejected(self):
        # 模组也可能带 manifest.json，但里面没有 minecraft 这一段
        self.assertIsNone(probe(self.zip_with("mod.zip", {"manifest.json": {"name": "x"}})))

    def test_resourcepack_rejected(self):
        self.assertIsNone(probe(self.zip_with("pack.zip", {
            "pack.mcmeta": "{}", "assets/minecraft/textures/a.png": "x"})))

    def test_not_a_zip_rejected(self):
        path = self.tmp / "readme.txt"
        path.write_text("hello", encoding="utf-8")
        self.assertIsNone(probe(str(path)))

    def test_missing_rejected(self):
        self.assertIsNone(probe(str(self.tmp / "nope.mrpack")))

    def test_random_folder_rejected(self):
        folder = self.tmp / "照片"
        (folder / "假期").mkdir(parents=True)
        (folder / "a.png").write_text("x", encoding="utf-8")
        self.assertIsNone(probe(str(folder)))


class ProbeFolderTests(unittest.TestCase):
    """解开的包目录也要认——三种格式各来一个。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_drop_dir_")
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def dir_with(self, name: str, members: dict) -> str:
        root = self.tmp / name
        for rel, content in members.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if isinstance(content, str) else json.dumps(content),
                         encoding="utf-8")
        return str(root)

    def test_unpacked_mrpack_folder(self):
        info = probe(self.dir_with("FO", {"modrinth.index.json": MRPACK_INDEX,
                                          "overrides/config/a.toml": "x"}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "mrpack")
        self.assertEqual(info["mc_version"], "1.20.1")
        self.assertIn("已解开的目录", info["format"])

    def test_unpacked_curseforge_folder(self):
        info = probe(self.dir_with("CF", {"manifest.json": CF_MANIFEST,
                                          "overrides/mods/a.jar": "x"}))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "curseforge")
        self.assertEqual(info["loader"], "forge")

    def test_minecraft_folder(self):
        info = probe(self.dir_with("整合包", {
            "mods/a.jar": "x",
            "config/t.toml": "y",
            "versions/1.20.1-forge-47.2.0/1.20.1-forge-47.2.0.json": {"id": "x"},
        }))
        self.assertIsNotNone(info)
        self.assertEqual(info["kind"], "plain")
        self.assertEqual(info["name"], "整合包")
        self.assertEqual(info["mc_version"], "1.20.1")
        self.assertEqual(info["loader"], "forge")


class ConfirmDialogTests(unittest.TestCase):
    """确认框交出去的那两个值：版本名和隔离开关。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QWidget

        cls.app = QApplication.instance() or QApplication([])
        # MessageBoxBase 会照着 parent 的尺寸铺遮罩，没有 parent 直接崩
        cls.host = QWidget()
        cls.host.resize(900, 600)

    def info(self, **over) -> dict:
        base = {
            "kind": "mrpack", "format": "Modrinth .mrpack", "name": "Fabulously Optimized",
            "version": "1.4.2", "mc_version": "1.20.1", "loader": "fabric-loader",
            "loader_version": "0.15.11", "files": 2, "path": "x.mrpack",
        }
        base.update(over)
        return base

    def test_suggested_name_is_pack_plus_version(self):
        self.assertEqual(suggest_version_name(self.info()), "Fabulously Optimized 1.4.2")

    def test_suggested_name_drops_illegal_chars(self):
        self.assertEqual(
            suggest_version_name(self.info(name="Pack: v2/x", version="")), "Pack- v2-x")

    def test_dialog_hands_back_name_and_isolation(self):
        from app.pages.modpack_drop import ModpackDropDialog

        dlg = ModpackDropDialog(self.info(), self.host)
        self.assertEqual(dlg.version_name(), "Fabulously Optimized 1.4.2")
        self.assertTrue(dlg.isolate(), "整合包默认独立成一版")
        dlg.name_edit.setText("  我的包  ")
        dlg.isolate_box.setChecked(False)
        self.assertEqual(dlg.version_name(), "我的包")
        self.assertFalse(dlg.isolate())


if __name__ == "__main__":
    unittest.main()
