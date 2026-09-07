from __future__ import annotations

import hashlib
import http.server
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from mclauncher.downloader import DownloadError, DownloadManager


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


if __name__ == "__main__":
    unittest.main()
