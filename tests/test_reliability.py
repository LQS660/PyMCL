from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from mclauncher import auth, updater, utils


class AtomicJsonTests(unittest.TestCase):
    def test_concurrent_writers_leave_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            errors: list[Exception] = []
            stop = threading.Event()

            def writer(worker: int):
                try:
                    for index in range(40):
                        utils.write_json(path, {"worker": worker, "index": index})
                except Exception as exc:  # pragma: no cover - assertion below
                    errors.append(exc)

            def reader():
                while not stop.is_set():
                    value = utils.read_json(path, None)
                    if value is not None:
                        self.assertIsInstance(value, dict)

            read_thread = threading.Thread(target=reader)
            read_thread.start()
            writers = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for thread in writers:
                thread.start()
            for thread in writers:
                thread.join()
            stop.set()
            read_thread.join(timeout=2)

            self.assertFalse(errors)
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            self.assertIn("worker", value)
            self.assertIn("index", value)


class UpdateIntegrityTests(unittest.TestCase):
    class FakeDownloadManager:
        def __init__(self, payload: bytes):
            self.payload = payload
            self.calls = []

        def download(self, url, dest, **kwargs):
            self.calls.append((url, Path(dest), kwargs))
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(self.payload)
            return Path(dest)

        def fetch_json(self, _url, timeout=0):
            return {
                "version": "9.9.9",
                "url": "https://example.invalid/PyMCL.exe",
                "sha256": "f" * 64,
            }

    def test_unsigned_update_is_not_offered(self):
        class UnsignedDM:
            def fetch_json(self, _url, timeout=0):
                return {"version": "9.9.9", "url": "https://example.invalid/PyMCL.exe"}

        info = updater.check(UnsignedDM())
        self.assertFalse(info["ok"])
        self.assertFalse(info["has_update"])
        self.assertIn("SHA-256", info["message"])

    def test_update_download_requires_and_verifies_sha256(self):
        payload = b"verified update package"
        digest = hashlib.sha256(payload).hexdigest()
        dm = self.FakeDownloadManager(payload)
        original_root = updater.utils.ROOT
        with tempfile.TemporaryDirectory() as td:
            updater.utils.ROOT = Path(td)
            try:
                out = updater.download(
                    {"latest": "9.9.9", "url": "https://example.invalid/update", "sha256": digest},
                    dm,
                )
            finally:
                updater.utils.ROOT = original_root
        self.assertEqual(dm.calls[0][2]["sha256"], digest)
        self.assertTrue(out.endswith("PyMCL-9.9.9.bin"))

    def test_update_download_rejects_missing_hash(self):
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            updater.download({"url": "https://example.invalid/update"}, self.FakeDownloadManager(b"x"))


class TokenStorageTests(unittest.TestCase):
    class FakeKeyring:
        def __init__(self):
            self.values = {}

        def set_password(self, service, name, value):
            self.values[(service, name)] = value

        def get_password(self, service, name):
            return self.values.get((service, name))

        def delete_password(self, service, name):
            self.values.pop((service, name), None)

    def test_non_windows_token_uses_keyring_reference(self):
        keyring = self.FakeKeyring()
        with mock.patch.object(auth.os, "name", "posix"), mock.patch.object(auth, "_keyring_backend", return_value=keyring):
            sealed = auth.seal_secret("super-secret-token")
            self.assertTrue(sealed.startswith("keyring:"))
            self.assertNotIn("super-secret-token", sealed)
            self.assertEqual(auth.open_secret(sealed), "super-secret-token")

    def test_non_windows_never_falls_back_to_plaintext(self):
        with mock.patch.object(auth.os, "name", "posix"), mock.patch.object(auth, "_keyring_backend", return_value=None):
            sealed = auth.seal_secret("super-secret-token")
            self.assertEqual(sealed, "unavailable:")
            self.assertEqual(auth.open_secret(sealed), "")


if __name__ == "__main__":
    unittest.main()
