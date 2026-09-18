# -*- coding: utf-8 -*-
"""拖进来的文件分派到哪儿。

认类型的部分在 tests/test_file_kinds.py；这里盯的是分派本身：认准了不许弹框、
拿不准必须弹一次（而且只弹一次），以及每种类型真的落到了对应的那条后端调用上。
"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app import file_kinds as fk  # noqa: E402
from app.pages import file_drop  # noqa: E402


def _png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        payload = tag + body
        return struct.pack(">I", len(body)) + payload + struct.pack(">I", zlib.crc32(payload))

    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class FakeBackend:
    def __init__(self):
        self.installs = []
        self.settings = []

    def game_root_name(self) -> str:
        return ".minecraft"

    def save_settings(self, data):
        self.settings.append(dict(data))

    def get_account_rows(self):
        return []

    def _record(self, kind):
        def call(name, instance="", extra=None):
            self.installs.append((kind, name, instance, dict(extra or {})))
            return "task"
        return call

    def __getattr__(self, item):
        if item.startswith("install_"):
            return self._record(item)
        raise AttributeError(item)


class FakeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(900, 700)
        self.backend = FakeBackend()
        self.modpacks = []

    def import_modpack_file(self, path):
        self.modpacks.append(path)


class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = FakeWindow()
        self.asked = []

    def tearDown(self):
        self.win.deleteLater()

    def stub_dialog(self, answer: str):
        """把选择框换成「用户点了 answer」，记下被问了几次、问的是什么。"""
        asked = self.asked

        class Stub:
            def __init__(self, info, others=0, parent=None):
                asked.append((info, others))

            def exec(self):
                return bool(answer)

            def kind(self):
                return answer

        patcher = mock.patch.object(file_drop, "FileKindDialog", Stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def zip_at(self, name, entries):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as zf:
            for member, body in entries.items():
                zf.writestr(member, body)
        return str(path)

    # ------------------------------------------------------------ 认准了
    def test_mod_jar_goes_straight_to_install_mod(self):
        self.stub_dialog("")
        path = self.zip_at("a.jar", {"fabric.mod.json": "{}"})

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(self.asked, [], "认得出来的不该再问")
        self.assertEqual([c[0] for c in self.win.backend.installs], ["install_mod"])
        kind, name, instance, extra = self.win.backend.installs[0]
        self.assertEqual(name, path)
        self.assertEqual(instance, ".minecraft")
        self.assertEqual(extra.get("path"), path)

    def test_video_becomes_the_wallpaper_and_stops_rotation(self):
        self.stub_dialog("")
        path = str(self.root / "clip.mp4")
        Path(path).write_bytes(b"\x00" * 32)

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(self.asked, [])
        self.assertEqual(self.win.backend.settings, [
            {"ui_background": path, "ui_background_folder": ""}],
            "文件夹轮播优先级更高，不清掉这一张根本显示不出来")

    def test_modpack_still_goes_through_the_old_confirm_flow(self):
        self.stub_dialog("")
        path = self.zip_at("pack.mrpack", {"modrinth.index.json":
                                           '{"formatVersion":1,"dependencies":{"minecraft":"1.20.1"},"files":[]}'})

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(self.win.modpacks, [path])
        self.assertEqual(self.win.backend.installs, [], "整合包不能绕开确认框直接起任务")

    def test_same_kind_files_are_installed_in_one_batch(self):
        self.stub_dialog("")
        jars = [self.zip_at(f"m{i}.jar", {"fabric.mod.json": "{}"}) for i in range(3)]

        file_drop.handle_dropped_files(self.win, jars)

        self.assertEqual([c[1] for c in self.win.backend.installs], jars)

    # ------------------------------------------------------------ 得问的
    def test_ambiguous_png_asks_once_and_obeys(self):
        self.stub_dialog(fk.WALLPAPER)
        path = str(self.root / "zoe.png")
        Path(path).write_bytes(_png(64, 64))

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(len(self.asked), 1, "拿不准就该问，而且只问一次")
        self.assertEqual(self.asked[0][0]["kinds"], [fk.SKIN, fk.WALLPAPER])
        self.assertEqual(self.win.backend.settings[0]["ui_background"], path)

    def test_one_answer_covers_the_rest_of_the_same_batch(self):
        """一次拖三张同样拿不准的图，不能连弹三个框。"""
        self.stub_dialog(fk.WALLPAPER)
        paths = []
        for i in range(3):
            p = self.root / f"skin{i}.png"
            p.write_bytes(_png(64, 64))
            paths.append(str(p))

        file_drop.handle_dropped_files(self.win, paths)

        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.asked[0][1], 2, "得告诉用户这个选择还管着另外两个")

    def test_cancelling_the_dialog_does_nothing(self):
        self.stub_dialog("")
        path = str(self.root / "maybe.png")
        Path(path).write_bytes(_png(64, 64))

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(self.win.backend.settings, [])
        self.assertEqual(self.win.backend.installs, [])

    def test_unknown_file_offers_the_full_menu(self):
        self.stub_dialog("")
        path = str(self.root / "notes.txt")
        Path(path).write_bytes(b"hello")

        file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(len(self.asked), 1, "认不出来也要给用户一次决定的机会")

    def test_failures_surface_instead_of_vanishing(self):
        """没有离线账号时拖皮肤进来：要看得见原因，不能静默什么都不发生。"""
        self.stub_dialog(fk.SKIN)
        path = str(self.root / "skin.png")
        Path(path).write_bytes(_png(64, 64))
        seen = []
        with mock.patch.object(file_drop.InfoBar, "error",
                               lambda title, content, **kw: seen.append((title, content))):
            file_drop.handle_dropped_files(self.win, [path])

        self.assertEqual(len(seen), 1)
        self.assertIn("离线账号", seen[0][1])


class DialogTests(unittest.TestCase):
    """真正那个选择框自己也得立得住：选项画得出来、读得回来。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_the_candidates_and_returns_the_pick(self):
        host = QWidget()
        host.resize(800, 600)
        info = {"name": "zoe.png", "detail": "64x64", "kinds": [fk.SKIN, fk.WALLPAPER]}

        dialog = file_drop.FileKindDialog(info, 0, host)

        self.assertEqual(dialog.kind(), fk.SKIN, "默认选中最像的那个")
        buttons = dialog._group.buttons()
        self.assertEqual([b.property("kind") for b in buttons], [fk.SKIN, fk.WALLPAPER])
        buttons[1].setChecked(True)
        self.assertEqual(dialog.kind(), fk.WALLPAPER)
        host.deleteLater()

    def test_unknown_file_gets_the_whole_menu(self):
        host = QWidget()
        host.resize(800, 600)

        dialog = file_drop.FileKindDialog({"name": "x.bin", "detail": "", "kinds": []}, 0, host)

        self.assertEqual([b.property("kind") for b in dialog._group.buttons()],
                         list(fk.ALL_KINDS))
        host.deleteLater()


if __name__ == "__main__":
    unittest.main()
