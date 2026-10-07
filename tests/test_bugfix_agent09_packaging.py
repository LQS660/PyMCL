# -*- coding: utf-8 -*-
"""Offline regressions for Python discovery and frozen multimedia resources."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
_module_spec = importlib.util.spec_from_file_location(
    "_agent09_pack_common", ROOT / "_pack_common.py"
)
pack_common = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(pack_common)


class PythonDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.launcher = "C:/test-python/py.exe"
        for patcher in (
            patch.object(pack_common.sys, "executable", ""),
            patch.object(pack_common.Path, "exists", return_value=False),
            patch.object(
                pack_common.shutil, "which",
                side_effect=lambda name: self.launcher if name == "py" else None,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(pack_common.subprocess, "run")
        self.run_probe = patcher.start()
        self.addCleanup(patcher.stop)

    def test_current_interpreter_stays_first(self):
        with patch.object(pack_common.sys, "executable", sys.base_prefix + "/python.exe"), \
                patch.object(pack_common.Path, "exists", return_value=True):
            self.assertEqual(pack_common.find_python(), [pack_common.sys.executable])
        self.run_probe.assert_not_called()

    def test_path_python_stays_before_launcher(self):
        with patch.object(pack_common.shutil, "which", return_value="C:/test-python/python.exe"):
            self.assertEqual(pack_common.find_python(), ["C:/test-python/python.exe"])
        self.run_probe.assert_not_called()

    def test_launcher_probes_313_before_accepting_it(self):
        self.run_probe.return_value = SimpleNamespace(returncode=0)
        self.assertEqual(pack_common.find_python(), [self.launcher, "-3.13"])
        self.run_probe.assert_called_once()

    def test_launcher_skips_missing_313_for_312(self):
        self.run_probe.side_effect = [SimpleNamespace(returncode=103), SimpleNamespace(returncode=0)]
        self.assertEqual(pack_common.find_python(), [self.launcher, "-3.12"])
        self.assertEqual([call.args[0][1] for call in self.run_probe.call_args_list], ["-3.13", "-3.12"])

    def test_launcher_reaches_311(self):
        self.run_probe.side_effect = [
            SimpleNamespace(returncode=103),
            SimpleNamespace(returncode=103),
            SimpleNamespace(returncode=0),
        ]
        self.assertEqual(pack_common.find_python(), [self.launcher, "-3.11"])
        self.assertEqual(self.run_probe.call_count, 3)

    def test_launcher_timeout_and_oserror_try_next_version(self):
        self.run_probe.side_effect = [
            subprocess.TimeoutExpired([self.launcher, "-3.13"], 5),
            OSError("launcher failed"),
            SimpleNamespace(returncode=0),
        ]
        self.assertEqual(pack_common.find_python(), [self.launcher, "-3.11"])
        self.assertEqual(self.run_probe.call_count, 3)

    def test_each_probe_has_bounded_noninteractive_stdio(self):
        self.run_probe.side_effect = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
        pack_common.find_python()
        for call in self.run_probe.call_args_list:
            self.assertEqual(call.args[0][2:], ["-c", "import sys"])
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 5)
            self.assertFalse(call.kwargs["check"])
            for stream in ("stdin", "stdout", "stderr"):
                self.assertEqual(call.kwargs[stream], subprocess.DEVNULL)

    def test_no_working_launcher_version_reports_no_python(self):
        self.run_probe.return_value = SimpleNamespace(returncode=103)
        with self.assertRaisesRegex(SystemExit, "Python"):
            pack_common.find_python()
        self.assertEqual(self.run_probe.call_count, 3)

    def test_failed_launcher_still_reaches_legacy_fallback(self):
        self.run_probe.return_value = SimpleNamespace(returncode=103)
        with patch.object(pack_common.Path, "exists", return_value=True):
            self.assertEqual(pack_common.find_python(), [r"C:\Python312\python.exe"])
        self.assertEqual(self.run_probe.call_count, 3)


# Common PyInstaller TOC destinations from the supported PySide6 layouts.
KEEP_MULTIMEDIA = (
    "PySide6/QtMultimedia.pyd",
    "PySide6/QtMultimedia.cp312-win_amd64.pyd",
    "PySide6/Qt6Multimedia.dll",
    r"PySide6\plugins\multimedia\ffmpegmediaplugin.dll",
    "PySide6/QtMultimedia.abi3.so",
    "PySide6/QtMultimedia.cpython-312-x86_64-linux-gnu.so",
    "PySide6/QtMultimedia.so",
    "PySide6/Qt/lib/libQt6Multimedia.so",
    "PySide6/Qt/lib/libQt6Multimedia.so.6",
    "PySide6/Qt/lib/libQt6Multimedia.so.6.11.1",
    "PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.so",
    "PySide6/Qt/lib/libQt6Multimedia.dylib",
    "PySide6/Qt/lib/libQt6Multimedia.6.dylib",
    "PySide6/Qt/lib/QtMultimedia.framework/Versions/A/QtMultimedia",
    "PySide6/Qt/lib/QtMultimedia.framework/QtMultimedia",
    "PySide6/Qt/lib/QtMultimedia.framework/Versions/A/Resources/Info.plist",
    "PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.dylib",
)
DROP_MULTIMEDIA = (
    "PySide6/QtMultimediaWidgets.pyd",
    "PySide6/QtMultimediaWidgets.abi3.so",
    "PySide6/Qt6MultimediaWidgets.dll",
    "PySide6/Qt/lib/libQt6MultimediaWidgets.so.6",
    "PySide6/Qt/lib/QtMultimediaWidgets.framework/Versions/A/QtMultimediaWidgets",
    "PySide6/Qt/lib/libQt6MultimediaQuick.so.6",
    "PySide6/Qt/lib/libQt6MultimediaQuick.6.dylib",
    "PySide6/Qt6MultimediaQuick.dll",
    "PySide6/Qt/lib/QtMultimediaQuick.framework/Versions/A/QtMultimediaQuick",
    "PySide6/Qt/qml/QtMultimedia/qmldir",
    "PySide6/Qt/qml/QtMultimedia/libquickmultimediaplugin.so",
    "PySide6/QtMultimedia.pyi",
)
OTHER_KEEP = ("PySide6/QtCore.pyd", "mclauncher/locales/en.json", "PySide6/translations/qt_zh_CN.qm")
OTHER_DROP = ("PySide6/Qt6WebEngineCore.dll", "PySide6/Qt/lib/libQt6Quick.so.6", "PySide6/translations/qt_en.qm")


def _evaluate_spec():
    """Run the actual spec using in-memory build objects, never a real build."""
    paths = KEEP_MULTIMEDIA + DROP_MULTIMEDIA + OTHER_KEEP + OTHER_DROP
    binaries = [(name, "unused-source", "BINARY") for name in paths]
    datas = [(name, "unused-source", "DATA") for name in paths]
    analysis = SimpleNamespace(binaries=binaries, datas=datas, pure=[], scripts=[])
    captured = {}

    def analyze(*args, **kwargs):
        captured.update(kwargs)
        return analysis

    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda package: []
    hooks.collect_submodules = lambda package: []
    modules = {
        "PyInstaller": ModuleType("PyInstaller"),
        "PyInstaller.utils": ModuleType("PyInstaller.utils"),
        "PyInstaller.utils.hooks": hooks,
    }
    namespace = {"Analysis": analyze, "PYZ": lambda *args: None, "EXE": lambda *args, **kwargs: None}
    filename = ROOT / "PyMCL.spec"
    with patch.dict(sys.modules, modules):
        exec(compile(filename.read_text(encoding="utf-8"), str(filename), "exec"), namespace)
    return namespace, analysis, captured


class FrozenMultimediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec, cls.analysis, cls.captured = _evaluate_spec()

    def test_core_multimedia_kept_on_all_platforms(self):
        for path in KEEP_MULTIMEDIA:
            with self.subTest(path=path):
                self.assertTrue(self.spec["_keep_bundle_path"](path))

    def test_multimedia_widgets_and_quick_still_excluded(self):
        for path in DROP_MULTIMEDIA:
            with self.subTest(path=path):
                self.assertFalse(self.spec["_keep_bundle_path"](path))

    def test_unrelated_filters_unchanged(self):
        for path in OTHER_KEEP:
            with self.subTest(path=path):
                self.assertTrue(self.spec["_keep_bundle_path"](path))
        for path in OTHER_DROP:
            with self.subTest(path=path):
                self.assertFalse(self.spec["_keep_bundle_path"](path))

    def test_actual_spec_filters_binaries_and_datas(self):
        expected = set(KEEP_MULTIMEDIA + OTHER_KEEP)
        self.assertEqual({item[0] for item in self.analysis.binaries}, expected)
        self.assertEqual({item[0] for item in self.analysis.datas}, expected)

    def test_hidden_binding_and_locale_data_stay_included(self):
        self.assertIn("PySide6.QtMultimedia", self.captured["hiddenimports"])
        self.assertIn("PySide6.QtMultimediaWidgets", self.captured["excludes"])
        self.assertIn(("mclauncher/locales", "mclauncher/locales"), self.captured["datas"])


if __name__ == "__main__":
    unittest.main()
