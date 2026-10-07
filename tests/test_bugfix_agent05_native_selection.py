# -*- coding: utf-8 -*-
"""Offline native selection regressions; run with an isolated PYMCL_HOME."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher import installer


def library(keys, natives=None):
    result = {
        "name": "org.lwjgl:lwjgl:3.3.1",
        "downloads": {"classifiers": {
            key: {"path": f"fixture/{key}.jar", "url": f"https://example.invalid/{key}.jar"}
            for key in keys
        }},
    }
    if natives is not None:
        result["natives"] = natives
    return result


class NativeSelectionTests(unittest.TestCase):
    def select(self, lib, os_name="windows", arch="x64"):
        with mock.patch.object(installer.utils, "OS_NAME", os_name), \
                mock.patch.object(installer.utils, "ARCH", arch):
            return installer.select_native_classifier(lib)

    def test_platform_filter_precedes_architecture_preference(self):
        for os_name, native, foreign in (
            ("windows", "windows", "linux"),
            ("linux", "linux", "windows"),
            ("osx", "macos", "linux"),
        ):
            for arch, bits in (("x64", "64"), ("x86", "32")):
                with self.subTest(os_name=os_name, arch=arch):
                    wanted = f"natives-{native}"
                    lib = library([wanted, f"natives-{foreign}-{bits}"])
                    self.assertEqual(self.select(lib, os_name, arch), wanted)

    def test_supported_platform_and_architecture_matrix(self):
        keys = [f"natives-{os_name}-{arch}"
                for os_name in ("windows", "linux", "macos")
                for arch in ("64", "32", "arm64")]
        for os_name, native in (("windows", "windows"), ("linux", "linux"), ("osx", "macos")):
            for arch, suffix in (("x64", "64"), ("x86", "32"), ("arm64", "arm64")):
                with self.subTest(os_name=os_name, arch=arch):
                    self.assertEqual(self.select(library(keys), os_name, arch),
                                     f"natives-{native}-{suffix}")

    def test_foreign_only_candidates_are_not_selected(self):
        for os_name, foreign in (("windows", "linux"), ("linux", "macos"), ("osx", "windows")):
            for arch in ("x64", "x86", "arm64"):
                with self.subTest(os_name=os_name, arch=arch):
                    keys = [f"natives-{foreign}-{suffix}" for suffix in ("32", "64", "arm64")]
                    self.assertIsNone(self.select(library(keys), os_name, arch))

    def test_incompatible_architecture_is_not_selected(self):
        for os_name, native in (("windows", "windows"), ("linux", "linux"), ("osx", "osx")):
            for arch, suffix in (("x64", "arm64"), ("x86", "64"), ("arm64", "x86")):
                with self.subTest(os_name=os_name, arch=arch):
                    self.assertIsNone(self.select(library([f"natives-{native}-{suffix}"]), os_name, arch))

    def test_architecture_aliases_are_preferred_to_generic(self):
        for arch, suffix in (("x64", "x64"), ("x64", "x86_64"),
                             ("x64", "amd64"), ("x86", "x86"),
                             ("arm64", "arm64"), ("arm64", "aarch64")):
            with self.subTest(arch=arch, suffix=suffix):
                wanted = f"natives-linux-{suffix}"
                self.assertEqual(self.select(library(["natives-linux", wanted]), "linux", arch), wanted)

    def test_arm64_does_not_use_unqualified_x86_native(self):
        self.assertIsNone(self.select(library(["natives-windows"]), arch="arm64"))

    def test_macos_platform_aliases_are_supported(self):
        for alias in ("osx", "macos"):
            wanted = f"natives-{alias}-arm64"
            self.assertEqual(self.select(library([wanted]), "osx", "arm64"), wanted)

    def test_explicit_compatible_mapping_keeps_priority(self):
        lib = library(["natives-windows-64", "natives-windows-x64"],
                      {"windows": "natives-windows-64"})
        self.assertEqual(self.select(lib), "natives-windows-64")

    def test_invalid_mapping_falls_back_to_compatible_candidate(self):
        for wanted in ("natives-linux-64", "natives-windows-32", "natives-windows-missing"):
            with self.subTest(wanted=wanted):
                lib = library([wanted, "natives-windows-64"], {"windows": wanted})
                self.assertEqual(self.select(lib), "natives-windows-64")

    def test_wrong_architecture_mapping_does_not_override_arm64_candidate(self):
        lib = library(["natives-windows-64", "natives-windows-arm64"],
                      {"windows": "natives-windows-64"})
        self.assertEqual(self.select(lib, arch="arm64"), "natives-windows-arm64")

    def test_absent_mapping_is_not_invented_when_classifiers_exist(self):
        lib = library(["natives-linux-64"], {"windows": "natives-windows-64"})
        self.assertIsNone(self.select(lib))

    def test_absent_mapping_can_use_existing_same_platform_candidate(self):
        lib = library(["natives-windows-x64"], {"windows": "natives-windows-64"})
        self.assertEqual(self.select(lib), "natives-windows-x64")

    def test_legacy_mapping_without_classifier_metadata_is_preserved(self):
        for arch, suffix in (("x64", "64"), ("x86", "32"), ("arm64", "arm64")):
            with self.subTest(arch=arch):
                wanted = "natives-windows-arm64" if arch == "arm64" else "natives-windows-${arch}"
                lib = {"natives": {"windows": wanted}}
                self.assertEqual(self.select(lib, arch=arch), f"natives-windows-{suffix}")

    def test_legacy_wrong_platform_or_architecture_is_rejected(self):
        for wanted in ("natives-linux-arm64", "natives-windows-${arch}"):
            with self.subTest(wanted=wanted):
                self.assertIsNone(self.select({"natives": {"windows": wanted}}, arch="arm64"))

    def test_placeholder_classifier_returns_existing_entry_path(self):
        lib = library(["natives-windows-${arch}"], {"windows": "natives-windows-${arch}"})
        with mock.patch.object(installer.utils, "OS_NAME", "windows"), \
                mock.patch.object(installer.utils, "ARCH", "x64"):
            key = installer.select_native_classifier(lib)
            self.assertEqual(key, "natives-windows-64")
            self.assertEqual(installer.natives_jar_relpath(lib, key), "fixture/natives-windows-${arch}.jar")

    def test_non_native_classifiers_and_unknown_platform_return_none(self):
        self.assertIsNone(self.select(library(["sources", "javadoc"])))
        self.assertIsNone(self.select(library(["natives-windows-64"]), "unknown"))
        self.assertIsNone(self.select({"name": "com.example:library:1.0"}))


class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent05-native-", dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.libs = root / "libraries"
        self.natives = root / "natives"
        instance = SimpleNamespace(libraries_dir=lambda: self.libs,
                                   natives_dir=lambda *args: self.natives)
        self.dm = mock.Mock()
        self.subject = installer.Installer(instance, dm=self.dm)
        for patcher in (mock.patch.object(installer.utils, "OS_NAME", "windows"),
                        mock.patch.object(installer.utils, "ARCH", "x64"),
                        mock.patch.object(installer.utils, "file_matches", return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_installation_only_schedules_current_platform_native(self):
        lib = library(["natives-windows", "natives-linux-64"])
        self.subject._install_libraries({"libraries": [lib]}, "fixture-version")
        self.dm.download_all.assert_called_once_with(
            [("https://example.invalid/natives-windows.jar",
              self.libs / "fixture/natives-windows.jar", None, None)], message="下载依赖库")
        self.dm.extract_jar_natives.assert_called_once_with(
            self.libs / "fixture/natives-windows.jar", self.natives, exclude=[])

    def test_installation_does_not_schedule_foreign_or_missing_native(self):
        lib = library(["natives-linux-64"], {"windows": "natives-windows-64"})
        self.subject._install_libraries({"libraries": [lib]}, "fixture-version")
        self.dm.download_all.assert_not_called()
        self.dm.extract_jar_natives.assert_not_called()


if __name__ == "__main__":
    unittest.main()
