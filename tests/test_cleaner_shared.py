from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher import cleaner


class CleanerSharedLibrariesTests(unittest.TestCase):
    def test_shared_library_used_by_later_instance_is_not_unused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            libs = root / "shared" / "libraries"
            library = libs / "org" / "example" / "lib" / "1.0" / "lib-1.0.jar"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"jar")
            first = SimpleNamespace(
                libraries_dir=lambda: libs,
                installed_ids=lambda: [],
                version_json=lambda _vid: None,
            )
            second = SimpleNamespace(
                libraries_dir=lambda: libs,
                installed_ids=lambda: ["1.0"],
                version_json=lambda _vid: {
                    "libraries": [{
                        "downloads": {"artifact": {
                            "path": "org/example/lib/1.0/lib-1.0.jar",
                        }},
                    }],
                },
            )
            instances = {"first": first, "second": second}
            with mock.patch.object(cleaner, "list_instances", return_value=list(instances)), \
                 mock.patch.object(cleaner, "Instance", side_effect=instances.__getitem__), \
                 mock.patch.object(cleaner, "CONFIG", SimpleNamespace(cache_dir=root / "cache")):
                result = cleaner.preview()

            self.assertEqual(result["unused_libraries"], [])
            self.assertTrue(library.is_file())

    def test_legacy_native_classifier_without_download_path_is_used(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            libs = root / "libraries"
            native = libs / "org" / "lwjgl" / "lwjgl" / "2.9.4" / "lwjgl-2.9.4-natives-windows.jar"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"native")
            instance = SimpleNamespace(
                libraries_dir=lambda: libs,
                installed_ids=lambda: ["1.7.10"],
                version_json=lambda _vid: {
                    "libraries": [{
                        "name": "org.lwjgl:lwjgl:2.9.4",
                        "natives": {"windows": "natives-windows"},
                    }],
                },
            )
            with mock.patch.object(cleaner, "list_instances", return_value=["game"]), \
                 mock.patch.object(cleaner, "Instance", return_value=instance), \
                 mock.patch.object(cleaner, "CONFIG", SimpleNamespace(cache_dir=root / "cache")):
                result = cleaner.preview()

            self.assertEqual(result["unused_libraries"], [])


if __name__ == "__main__":
    unittest.main()
