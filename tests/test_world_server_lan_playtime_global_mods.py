"""Isolated regressions for world installs, server lists, LAN, playtime and global mods."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher import global_mods, lan, playtime, servers, terracotta, worlds


class WorldRegressionTests(unittest.TestCase):
    def test_zip_with_level_dat_at_root_becomes_a_playable_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "MyWorld.zip"
            saves = root / "saves"
            saves.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("level.dat", b"world data")
                zf.writestr("region/r.0.0.mca", b"chunks")
            result = worlds._extract_world(archive, saves)
            self.assertEqual(result["files"], ["MyWorld"])
            self.assertEqual((saves / "MyWorld" / "level.dat").read_bytes(), b"world data")
            self.assertEqual((saves / "MyWorld" / "region" / "r.0.0.mca").read_bytes(), b"chunks")
            self.assertFalse((saves / "level.dat").exists())

    def test_dot_prefixed_root_level_dat_is_a_playable_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "MyWorld.zip"
            saves = root / "saves"
            saves.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("./level.dat", b"world data")
            result = worlds._extract_world(archive, saves)
            self.assertEqual(result["files"], ["MyWorld"])
            self.assertTrue((saves / "MyWorld" / "level.dat").is_file())

    def test_invalid_zip_member_does_not_leave_partial_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "unsafe.zip"
            saves = root / "saves"
            saves.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("world/level.dat", b"data")
                zf.writestr("../outside.txt", b"oops")
            with self.assertRaises(worlds.WorldError):
                worlds._extract_world(archive, saves)
            self.assertFalse((saves / "world").exists())
            self.assertFalse((root / "outside.txt").exists())


class ServerRegressionTests(unittest.TestCase):
    def test_empty_game_list_does_not_resurrect_stale_json(self):
        with tempfile.TemporaryDirectory() as td:
            inst = SimpleNamespace(path=Path(td))
            servers.add_server(inst, "Old", "old.example")
            terracotta.write_game_servers(inst.path / "servers.dat", [])
            self.assertEqual(servers.list_servers(inst), [])
            servers.add_server(inst, "New", "new.example")
            self.assertEqual([row["name"] for row in servers.list_servers(inst)], ["New"])

    def test_inline_port_with_default_port_is_not_written_twice(self):
        with tempfile.TemporaryDirectory() as td:
            inst = SimpleNamespace(path=Path(td))
            added = servers.add_server(inst, "Custom", "example.test:25566")
            self.assertEqual((added["ip"], added["port"]), ("example.test", 25566))
            self.assertEqual(terracotta.read_game_servers(inst.path / "servers.dat")[0]["ip"],
                             "example.test:25566")
            self.assertEqual((servers.list_servers(inst)[0]["ip"], servers.list_servers(inst)[0]["port"]),
                             ("example.test", 25566))
            self.assertEqual(servers._read_json_rows(inst)[0]["ip"], "example.test")
            self.assertEqual(servers._read_json_rows(inst)[0]["port"], 25566)
            self.assertEqual(servers.import_servers_txt(inst, "example.test:25566"), 0)

    def test_custom_port_and_ipv6_not_split_twice(self):
        with tempfile.TemporaryDirectory() as td:
            inst = SimpleNamespace(path=Path(td))
            servers.add_server(inst, "Explicit", "example.test:25566", 25567)
            servers.add_server(inst, "IPv6", "2001:db8::1")
            self.assertEqual([(s["ip"], s["port"]) for s in servers.list_servers(inst)],
                             [("example.test", 25567), ("2001:db8::1", 25565)])
            self.assertEqual([s["ip"] for s in terracotta.read_game_servers(inst.path / "servers.dat")],
                             ["example.test:25567", "2001:db8::1"])


class LanRegressionTests(unittest.TestCase):
    def test_failed_udp_connect_closes_socket(self):
        class FailingSocket:
            closed = False

            def connect(self, address):
                raise OSError("no route")

            def close(self):
                self.closed = True

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        sock = FailingSocket()
        with mock.patch.object(lan.socket, "gethostname", return_value="offline"), \
             mock.patch.object(lan.socket, "getaddrinfo", return_value=[]), \
             mock.patch.object(lan.socket, "socket", return_value=sock):
            self.assertEqual(lan.local_ips(), ["127.0.0.1"])
        self.assertTrue(sock.closed)


class PlaytimeRegressionTests(unittest.TestCase):
    def test_clearing_version_preserves_totals_when_sessions_are_truncated(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(playtime.utils, "ROOT", Path(td)):
            playtime._save({"instances": {"default": {
                "total": 800, "versions": {"old": 500, "new": 300},
                "sessions": [
                    {"start": 1, "duration": 1, "version": "old"},
                    {"start": 2, "duration": 2, "version": "new"},
                ],
            }}})
            playtime.clear_playtime("default", "old")
            data = playtime.get_playtime("default")
            self.assertEqual(data["total"], 300)
            self.assertEqual(data["versions"], {"new": 300})
            self.assertEqual([s["version"] for s in data["sessions"]], ["new"])

    def test_stopping_tracker_twice_does_not_record_same_session_twice(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(playtime.utils, "ROOT", Path(td)), \
             mock.patch.object(playtime.time, "time", side_effect=[100, 130, 130, 160]):
            tracker = playtime.PlaytimeTracker("default", "1.21")
            tracker.start()
            self.assertEqual(tracker.stop(), 30)
            self.assertEqual(tracker.stop(), 0)
            data = playtime.get_playtime("default")
            self.assertEqual(data["total"], 30)
            self.assertEqual(len(data["sessions"]), 1)


class GlobalModsRegressionTests(unittest.TestCase):
    def test_apply_counts_only_newly_installed_mods(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "shared"
            source.mkdir()
            (source / "mod.jar").write_bytes(b"mod")
            dest = root / "game" / "mods"
            with mock.patch.object(global_mods, "root", return_value=source):
                self.assertEqual(global_mods.apply(dest), 1)
                self.assertEqual(global_mods.apply(dest), 0)
            self.assertTrue((dest / "mod.jar").is_file())

    def test_apply_does_not_count_failed_link_or_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "shared"
            source.mkdir()
            (source / "mod.jar").write_bytes(b"mod")
            dest = root / "game" / "mods"
            win_link = (mock.patch("ctypes.windll.kernel32.CreateSymbolicLinkW", return_value=0)
                        if global_mods.os.name == "nt" else nullcontext())
            with mock.patch.object(global_mods, "root", return_value=source), \
                 mock.patch.object(Path, "symlink_to", side_effect=OSError("symlink denied")), \
                 mock.patch("shutil.copy2", side_effect=OSError("copy denied")), win_link:
                self.assertEqual(global_mods.apply(dest), 0)
            self.assertFalse((dest / "mod.jar").exists())


if __name__ == "__main__":
    unittest.main()
