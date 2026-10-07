# -*- coding: utf-8 -*-
"""Offline regressions: legacy launch arguments and preferred Java locations."""
from __future__ import annotations

import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mclauncher import java, launcher


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(
            prefix="test_bugfix_agent04_", dir=Path(__file__).parent)
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        for target, attribute in (
            (subprocess, "Popen"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
            (java, "find_system_javas"),
            (java, "list_installed_javas"),
        ):
            self.patch(target, attribute, side_effect=AssertionError(
                "External execution/discovery is forbidden"))

    def patch(self, target, attribute, **kwargs):
        patcher = mock.patch.object(target, attribute, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value


class LegacyLaunchArgumentsTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.version_id = "1.12.2"
        self.main_class = "net.minecraft.client.main.Main"
        self.game_dir = self.root / "游戏 folder with spaces"
        versions = self.root / "versions"
        vdir = versions / self.version_id
        vdir.mkdir(parents=True)
        (vdir / (self.version_id + ".jar")).write_bytes(b"fixture; never executed")
        self.instance = mock.Mock()
        self.instance.path = self.game_dir
        self.instance.versions_dir.return_value = versions
        self.instance.libraries_dir.return_value = self.root / "libraries with spaces"
        self.instance.assets_dir.return_value = self.root / "assets with spaces"
        self.patch(java, "java_usable_for", return_value=True)
        self.patch(java, "get_java_major", return_value=8)
        self.patch(launcher, "extract_natives", return_value=self.root / "native libraries")
        self.patch(launcher, "_version_type", return_value="release")
        self.patch(launcher.CONFIG, "get", return_value="")

    def command(self, raw="", *, modern=None, player="Player"):
        version = {
            "id": self.version_id,
            "mainClass": self.main_class,
            "assetIndex": {"id": "1.12"},
            "libraries": [],
            "minecraftArguments": raw,
        }
        if modern is not None:
            version["arguments"] = modern
        self.instance.version_json.return_value = version
        cmd, _natives, _version, game_dir = launcher.build_launch_command(
            self.instance, self.version_id, {"name": player},
            self.root / "fake java" / "bin" / "java.exe")
        self.assertEqual(game_dir, self.game_dir)
        return cmd

    def game_args(self, *args, **kwargs):
        cmd = self.command(*args, **kwargs)
        return cmd[cmd.index(self.main_class) + 1:]

    def test_quoted_placeholder_and_multiword_argument(self):
        self.assertEqual(
            self.game_args('--username ${auth_player_name} --gameDir "${game_directory}" --title "hello world"'),
            ["--username", "Player", "--gameDir", str(self.game_dir), "--title", "hello world"])

    def test_unquoted_placeholder_with_spaces_remains_one_argument(self):
        self.assertEqual(
            self.game_args("--gameDir ${game_directory} --username ${auth_player_name}"),
            ["--gameDir", str(self.game_dir), "--username", "Player"])

    def test_windows_literal_paths_keep_backslashes(self):
        self.assertEqual(
            self.game_args(r'--gameDir C:\Games\Minecraft --assetsDir "C:\Program Files\Minecraft Assets"'),
            ["--gameDir", r"C:\Games\Minecraft", "--assetsDir", r"C:\Program Files\Minecraft Assets"])

    def test_unc_path_keeps_both_leading_backslashes(self):
        unc = chr(92) * 2 + r"server\share\Minecraft"
        self.assertEqual(self.game_args("--gameDir " + unc), ["--gameDir", unc])

    def test_quoted_trailing_backslash_is_preserved(self):
        path = "C:" + chr(92) + "Game Folder" + chr(92)
        self.assertEqual(self.game_args('--gameDir "' + path + '"'),
                         ["--gameDir", path])

    def test_mixed_quoted_property_value(self):
        self.assertEqual(self.game_args('--setting=name="two words"'),
                         ["--setting=name=two words"])

    def test_whitespace_separates_legacy_arguments(self):
        self.assertEqual(self.game_args("--username\tPlayer\n--version 1.12.2"),
                         ["--username", "Player", "--version", "1.12.2"])

    def test_repeated_spaces_do_not_create_empty_arguments(self):
        self.assertEqual(self.game_args("   --username   Player    --width 854  "),
                         ["--username", "Player", "--width", "854"])

    def test_empty_quoted_argument_is_passed_as_empty_value(self):
        self.assertEqual(self.game_args('--title "" --username Player'),
                         ["--title", "", "--username", "Player"])

    def test_empty_argument_string_is_empty(self):
        self.assertEqual(self.game_args(""), [])
        self.assertEqual(self.game_args("    "), [])

    def test_hash_inside_value_is_not_a_comment(self):
        self.assertEqual(self.game_args('--title "Save #1" --width 854'),
                         ["--title", "Save #1", "--width", "854"])

    def test_placeholder_value_is_not_reparsed_as_command_text(self):
        player = "Player O'Brien with \"quotes\""
        self.assertEqual(self.game_args("--username ${auth_player_name}", player=player),
                         ["--username", player])

    def test_unknown_placeholder_filter_stays_compatible(self):
        self.assertEqual(self.game_args("${unknown} --username ${auth_player_name}"),
                         ["--username", "Player"])

    def test_unbalanced_quote_keeps_legacy_fallback(self):
        self.assertEqual(self.game_args('--title "unterminated'),
                         ["--title", '"unterminated'])

    def test_modern_argument_list_is_not_resplit(self):
        modern = {
            "jvm": ["-cp", "${classpath}"],
            "game": ["--title", "hello world", "--gameDir", "${game_directory}"],
        }
        self.assertEqual(self.game_args(modern=modern),
                         ["--title", "hello world", "--gameDir", str(self.game_dir)])

    def test_classpath_with_spaces_is_one_argument(self):
        cmd = self.command("--username Player")
        cp = cmd[cmd.index("-cp") + 1]
        self.assertEqual(cp, str(self.instance.versions_dir() / self.version_id /
                                 (self.version_id + ".jar")))
        self.assertFalse(cp.startswith('"'))


class PreferredJavaTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.catalog = self.patch(java, "all_javas", return_value=[])
        self.home = self.root / "自定义 Java 17"
        self.exe = self.home / "bin" / "java.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not executable; do not run")

    def test_jdk_home_is_resolved_without_global_discovery(self):
        self.assertEqual(java._prefer_to_exe(str(self.home)), str(self.exe))
        self.catalog.assert_not_called()

    def test_bin_directory_remains_supported(self):
        self.assertEqual(java._prefer_to_exe(str(self.exe.parent)), str(self.exe))
        self.catalog.assert_not_called()

    def test_explicit_executable_remains_supported(self):
        self.assertEqual(java._prefer_to_exe(str(self.exe)), str(self.exe))
        self.catalog.assert_not_called()

    def test_nested_jre_home_is_supported(self):
        home = self.root / "jdk with nested jre"
        exe = home / "jre" / "bin" / "java.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"not executable; do not run")
        self.assertEqual(java._prefer_to_exe(str(home)), str(exe))
        self.catalog.assert_not_called()

    def test_registered_directory_alias_remains_supported(self):
        self.catalog.return_value = [{"dir": "registered-java-17", "exe": str(self.exe)}]
        self.assertEqual(java._prefer_to_exe("registered-java-17"), str(self.exe))
        self.catalog.assert_called_once_with()

    def test_registered_executable_alias_remains_supported(self):
        self.catalog.return_value = [{"exe": "registered-java-executable"}]
        self.assertEqual(java._prefer_to_exe("registered-java-executable"),
                         "registered-java-executable")

    def test_missing_and_empty_preferences_remain_safe(self):
        self.assertIsNone(java._prefer_to_exe(None))
        self.assertIsNone(java._prefer_to_exe(""))
        self.catalog.assert_not_called()
        self.assertIsNone(java._prefer_to_exe(str(self.root / "does not exist")))

    def test_empty_directory_falls_back_to_catalog(self):
        folder = self.root / "empty jdk"
        folder.mkdir()
        self.assertIsNone(java._prefer_to_exe(str(folder)))
        self.catalog.assert_called_once_with()

    def test_runtime_selection_uses_explicit_jdk_home(self):
        probe = self.patch(java, "get_java_major", return_value=17)
        selected = java.pick_java_for_version(
            {"javaVersion": {"majorVersion": 17}}, prefer=str(self.home))
        self.assertEqual(selected, str(self.exe))
        probe.assert_called_once_with(str(self.exe))
        self.catalog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
