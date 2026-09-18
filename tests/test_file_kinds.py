# -*- coding: utf-8 -*-
"""拖进来的文件到底是什么：认对了才谈得上放对地方。

主窗口以前把所有拖放一律当整合包，认不出来就回一句「这不是整合包」——
拖个 mp4 进来得到的就是这句话。这里逐类造一个最小样本，盯两件事：
认得出来的别问（sure=True），像两样东西的必须问（sure=False 且候选都在）。
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import file_kinds as fk  # noqa: E402


def _png(width: int, height: int) -> bytes:
    """最小合法 PNG：判定只读文件头里的宽高，像素内容无所谓。"""
    def chunk(tag: bytes, body: bytes) -> bytes:
        payload = tag + body
        return struct.pack(">I", len(body)) + payload + struct.pack(">I", zlib.crc32(payload))

    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class IdentifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def zip_at(self, name: str, entries: dict) -> str:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as zf:
            for member, body in entries.items():
                zf.writestr(member, body)
        return str(path)

    def file_at(self, name: str, body: bytes) -> str:
        path = self.root / name
        path.write_bytes(body)
        return str(path)

    def assertKinds(self, path: str, kinds: list, sure: bool):
        got = fk.identify(path)
        self.assertEqual(got["kinds"], kinds, got["detail"])
        self.assertEqual(got["sure"], sure, got["detail"])

    # ---------------------------------------------------------- 一眼认得出
    def test_video_is_a_wallpaper(self):
        self.assertKinds(self.file_at("clip.mp4", b"\x00" * 64), [fk.WALLPAPER], True)

    def test_ordinary_image_is_a_wallpaper(self):
        self.assertKinds(self.file_at("wall.png", _png(1920, 1080)), [fk.WALLPAPER], True)

    def test_mod_jar_is_a_mod(self):
        path = self.zip_at("cool-mod.jar", {"fabric.mod.json": "{}"})
        self.assertKinds(path, [fk.MOD], True)

    def test_mrpack_is_a_modpack(self):
        path = self.zip_at("pack.mrpack", {"modrinth.index.json": json.dumps({
            "formatVersion": 1, "name": "Test", "versionId": "1",
            "dependencies": {"minecraft": "1.20.1"}, "files": [],
        })})
        got = fk.identify(path)
        self.assertEqual(got["kinds"], [fk.MODPACK])
        self.assertTrue(got["sure"])
        self.assertIn("1.20.1", got["detail"], "认出来了就该把版本说给用户听")

    def test_resourcepack_needs_assets(self):
        path = self.zip_at("res.zip", {"pack.mcmeta": "{}", "assets/minecraft/x.json": "{}"})
        self.assertKinds(path, [fk.RESOURCEPACK], True)

    def test_datapack_needs_data(self):
        path = self.zip_at("dp.zip", {"pack.mcmeta": "{}", "data/ns/x.json": "{}"})
        self.assertKinds(path, [fk.DATAPACK], True)

    def test_shaderpack_needs_a_shaders_dir(self):
        path = self.zip_at("shader.zip", {"shaders/final.fsh": "void main(){}"})
        self.assertKinds(path, [fk.SHADERPACK], True)

    def test_world_zip_is_spotted_by_level_dat(self):
        path = self.zip_at("world.zip", {"MyWorld/level.dat": "x", "MyWorld/region/r.0.0.mca": "x"})
        self.assertKinds(path, [fk.WORLD], True)

    def test_world_folder_counts_too(self):
        folder = self.root / "DroppedWorld"
        (folder / "region").mkdir(parents=True)
        (folder / "level.dat").write_bytes(b"x")
        self.assertKinds(str(folder), [fk.WORLD], True)

    # ------------------------------------------------------------ 得问一句
    def test_skin_sized_png_offers_both(self):
        """64x64 的 PNG 既可能是皮肤也可能是壁纸，只能问。"""
        path = self.file_at("zoe.png", _png(64, 64))
        self.assertKinds(path, [fk.SKIN, fk.WALLPAPER], False)
        self.assertKinds(self.file_at("old.png", _png(64, 32)),
                         [fk.SKIN, fk.WALLPAPER], False)

    def test_pack_mcmeta_with_both_trees_is_ambiguous(self):
        path = self.zip_at("both.zip", {
            "pack.mcmeta": "{}", "assets/a.json": "{}", "data/b.json": "{}"})
        self.assertKinds(path, [fk.RESOURCEPACK, fk.DATAPACK], False)

    def test_bare_jar_is_probably_a_mod_but_not_certain(self):
        path = self.zip_at("mystery.jar", {"com/x/Main.class": "x"})
        self.assertKinds(path, [fk.MOD], False)

    # -------------------------------------------------------------- 不接的
    def test_loader_installer_is_refused_with_a_reason(self):
        """Forge 安装器丢进 mods 只会让游戏起不来，得说清楚该去哪儿装。"""
        path = self.zip_at("forge-installer.jar", {"install_profile.json": "{}"})
        got = fk.identify(path)
        self.assertEqual(got["kinds"], [])
        self.assertIn("安装器", got["detail"])

    def test_unknown_file_has_no_candidates(self):
        self.assertKinds(self.file_at("notes.txt", b"hello"), [], False)

    def test_missing_path_does_not_raise(self):
        got = fk.identify(str(self.root / "nope.zip"))
        self.assertEqual(got["kinds"], [])
        self.assertTrue(got["detail"])

    def test_every_kind_has_a_label_and_an_action(self):
        """对话框拿这两张表画选项，缺一条就会出现一个没名字的单选框。"""
        for kind in fk.ALL_KINDS:
            self.assertTrue(fk.KIND_LABELS.get(kind), kind)
            self.assertTrue(fk.KIND_ACTIONS.get(kind), kind)


if __name__ == "__main__":
    unittest.main()
