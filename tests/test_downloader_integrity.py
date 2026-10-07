from __future__ import annotations

import hashlib
import http.server
import os
import tempfile
import threading
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from mclauncher.downloader import DownloadError, DownloadManager
from mclauncher.installer import Installer


@contextmanager
def local_file_server(directory: Path):
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    old_cwd = os.getcwd()
    os.chdir(directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        os.chdir(old_cwd)


class DownloaderIntegrityTests(unittest.TestCase):
    def test_sha256_download_accepts_matching_file(self):
        payload = b"PyMCL verified file content" * 64
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "source.bin").write_bytes(payload)
            with local_file_server(root) as base:
                target = root / "out.bin"
                got = DownloadManager(threads=1).download(
                    f"{base}/source.bin", target, sha256=digest, size=len(payload), expand=False,
                )
            self.assertEqual(got.read_bytes(), payload)

    def test_sha256_download_rejects_tampered_file(self):
        payload = b"PyMCL tampered file content" * 64
        bad_digest = hashlib.sha256(b"different file").hexdigest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "source.bin").write_bytes(payload)
            with local_file_server(root) as base:
                target = root / "out.bin"
                with self.assertRaises(DownloadError):
                    DownloadManager(threads=1).download(
                        f"{base}/source.bin", target, sha256=bad_digest, size=len(payload), expand=False,
                    )
            self.assertFalse(target.exists())

    def test_size_only_jar_replaces_same_size_html_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.jar"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("package/Demo.class", b"compiled class")
            expected = source.read_bytes()
            target = root / "downloaded.jar"
            target.write_bytes(b"<html>download failed</html>".ljust(len(expected), b"x"))
            with local_file_server(root) as base:
                dm = DownloadManager(threads=1)
                self.addCleanup(dm.session.close)
                dm.download(f"{base}/source.jar", target, size=len(expected), expand=False)
            self.assertEqual(target.read_bytes(), expected)

    def test_install_library_rechecks_size_only_jar_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.jar"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("package/Demo.class", b"compiled class")
            expected = source.read_bytes()
            target = root / "libraries" / "org" / "example" / "demo" / "demo.jar"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"<html>download failed</html>".ljust(len(expected), b"x"))
            instance = SimpleNamespace(
                libraries_dir=lambda: root / "libraries",
                natives_dir=lambda version, resolved: root / "versions" / version / "natives",
            )
            with local_file_server(root) as base:
                dm = DownloadManager(threads=1)
                self.addCleanup(dm.session.close)
                installer = Installer(instance, dm=dm)
                installer._install_libraries({"libraries": [{
                    "name": "org.example:demo:1.0",
                    "downloads": {"artifact": {
                        "url": f"{base}/source.jar",
                        "path": "org/example/demo/demo.jar",
                        "size": len(expected),
                    }},
                }]}, "1.20.1")
            self.assertEqual(target.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
