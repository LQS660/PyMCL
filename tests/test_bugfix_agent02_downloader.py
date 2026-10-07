from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from requests.exceptions import ReadTimeout

from mclauncher.downloader import DownloadError, DownloadManager


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status_code = status
        self.is_redirect = False
        self.headers = {"Content-Length": str(len(payload))} if headers is None else headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"Unexpected status {self.status_code}")

    def iter_content(self, chunk_size):
        yield self.payload


class DownloaderAgent02Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dm = DownloadManager(threads=1)
        self.addCleanup(self.dm.session.close)
        for target, options in (
            ("socket.socket.connect", {"side_effect": AssertionError("Network disabled")}),
            ("mclauncher.downloader.time.sleep", {}),
            ("mclauncher.downloader._free_bytes", {"return_value": 1024**4}),
        ):
            patcher = patch(target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def download(self, target, response, **options):
        with patch.object(self.dm.session, "get", return_value=response) as get:
            result = self.dm.download(
                "http://127.0.0.1:1/artifact", target, expand=False, **options,
            )
        return result, get

    def test_sha512_only_replaces_corrupt_cache(self):
        expected = b"correct cached payload" * 4
        target = self.root / "cache.bin"
        target.write_bytes(b"corrupt cached payload" * 4)
        result, get = self.download(
            target, Response(expected), sha512=hashlib.sha512(expected).hexdigest(),
        )
        self.assertEqual(result.read_bytes(), expected)
        self.assertEqual(get.call_count, 1)

    def test_sha512_only_reuses_verified_tiny_cache(self):
        expected = b"{}"
        target = self.root / "cache.json"
        target.write_bytes(expected)
        result, get = self.download(
            target, Response(expected), sha512=hashlib.sha512(expected).hexdigest().upper(),
        )
        self.assertEqual(result.read_bytes(), expected)
        get.assert_not_called()

    def test_matching_hashes_accept_tiny_empty_and_text_payloads(self):
        for algorithm in ("sha1", "sha256", "sha512"):
            for payload in (b"", b"{}", b"error rate is a valid configuration value", b"<html>verified document</html>"):
                with self.subTest(algorithm=algorithm, payload=payload):
                    target = self.root / (algorithm + str(len(payload)) + ".bin")
                    result, _ = self.download(
                        target, Response(payload), size=len(payload),
                        **{algorithm: hashlib.new(algorithm, payload).hexdigest()},
                    )
                    self.assertEqual(result.read_bytes(), payload)

    def test_size_is_enforced_even_with_matching_hash(self):
        payload = b"verified bytes with inconsistent metadata" * 2
        for algorithm in ("sha1", "sha256", "sha512"):
            with self.subTest(algorithm=algorithm):
                target = self.root / (algorithm + ".bin")
                target.write_bytes(b"old destination must remain unchanged")
                with self.assertRaises(DownloadError):
                    self.download(
                        target, Response(payload), force=True, size=len(payload) + 1,
                        **{algorithm: hashlib.new(algorithm, payload).hexdigest()},
                    )
                self.assertEqual(target.read_bytes(), b"old destination must remain unchanged")
                self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_all_supplied_hashes_must_match(self):
        payload = b"bytes checked by all supplied hashes" * 2
        good = {name: hashlib.new(name, payload).hexdigest() for name in ("sha1", "sha256", "sha512")}
        for bad_algorithm in good:
            with self.subTest(bad_algorithm=bad_algorithm):
                target = self.root / (bad_algorithm + ".bin")
                hashes = dict(good)
                hashes[bad_algorithm] = "0" * len(hashes[bad_algorithm])
                with self.assertRaises(DownloadError):
                    self.download(target, Response(payload), size=len(payload), **hashes)
                self.assertFalse(target.exists())
        result, _ = self.download(self.root / "all.bin", Response(payload), size=len(payload), **good)
        self.assertEqual(result.read_bytes(), payload)

    def test_unverified_archive_checks_destination_suffix(self):
        for suffix in (".jar", ".ZIP"):
            for size in (None, 40):
                with self.subTest(suffix=suffix, size=size):
                    target = self.root / (str(size) + suffix)
                    payload = b"not an archive but a successful response"
                    self.assertEqual(len(payload), 40)
                    with self.assertRaises(DownloadError):
                        self.download(target, Response(payload), size=size)
                    self.assertFalse(target.exists())
                    self.assertFalse(target.with_name(target.name + ".part").exists())

    def test_unverified_archive_accepts_zip_signature(self):
        payload = b"PK" + b"archive content" * 4
        result, _ = self.download(self.root / "valid.jar", Response(payload))
        self.assertEqual(result.read_bytes(), payload)

    def test_unverified_html_is_rejected(self):
        with self.assertRaises(DownloadError):
            self.download(self.root / "error.bin", Response(b"<html>upstream error page</html>"))

    def test_valid_content_range_resumes(self):
        payload = b"0123456789abcdef" * 3
        for algorithm in (None, "sha1", "sha256", "sha512"):
            with self.subTest(algorithm=algorithm):
                target = self.root / (str(algorithm) + ".bin")
                target.with_name(target.name + ".part").write_bytes(payload[:16])
                hashes = {algorithm: hashlib.new(algorithm, payload).hexdigest()} if algorithm else {}
                response = Response(payload[16:], status=206, headers={
                    "Content-Length": "32", "Content-Range": "bytes 16-47/48",
                })
                result, get = self.download(target, response, size=len(payload), **hashes)
                self.assertEqual(result.read_bytes(), payload)
                self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=16-")

    def test_invalid_ranges_are_rejected_before_body_is_appended(self):
        bad_headers = (
            {"Content-Length": "16", "Content-Range": "bytes 0-15/32"},
            {"Content-Length": "16"},
            {"Content-Length": "16", "Content-Range": "bytes 16-31/64"},
            {"Content-Length": "16", "Content-Range": "bytes 16-63/64"},
            {"Content-Length": "16", "Content-Range": "bytes 16-15/32"},
            {"Content-Length": "16", "Content-Range": "bytes 16-32/32"},
            {"Content-Length": "16", "Content-Range": "bytes 16-31/*"},
            {"Content-Length": "16", "Content-Range": "invalid"},
        )
        for index, headers in enumerate(bad_headers):
            with self.subTest(headers=headers):
                target = self.root / (str(index) + ".bin")
                part = target.with_name(target.name + ".part")
                part.write_bytes(b"a" * 16)
                response = Response(b"b" * 16, status=206, headers=headers)
                with patch.object(response, "iter_content", wraps=response.iter_content) as body:
                    with self.assertRaises(DownloadError):
                        self.download(target, response, size=32)
                    body.assert_not_called()
                self.assertFalse(target.exists())
                self.assertFalse(part.exists())

    def test_range_total_and_length_checked_without_metadata_size(self):
        prefix, suffix = b"a" * 16, b"b" * 16
        digest = hashlib.sha1(prefix + suffix).hexdigest()
        for index, headers in enumerate((
            {"Content-Length": "16", "Content-Range": "bytes 16-31/64"},
            {"Content-Length": "15", "Content-Range": "bytes 16-31/32"},
        )):
            with self.subTest(headers=headers):
                target = self.root / (str(index) + ".bin")
                target.with_name(target.name + ".part").write_bytes(prefix)
                response = Response(suffix, status=206, headers=headers)
                with patch.object(response, "iter_content", wraps=response.iter_content) as body:
                    with self.assertRaises(DownloadError):
                        self.download(target, response, sha1=digest)
                    body.assert_not_called()
                self.assertFalse(target.exists())

    def test_range_without_content_length_uses_content_range(self):
        payload = b"a" * 16 + b"b" * 16
        target = self.root / "chunked.bin"
        target.with_name(target.name + ".part").write_bytes(payload[:16])
        response = Response(payload[16:], status=206, headers={"Content-Range": "bytes 16-31/32"})
        result, _ = self.download(target, response, size=32)
        self.assertEqual(result.read_bytes(), payload)

    def test_range_body_length_is_enforced_even_with_matching_hash(self):
        for suffix, total in ((b"b" * 16, 48), (b"b" * 32, 32)):
            with self.subTest(total=total):
                payload = b"a" * 16 + suffix
                target = self.root / (str(total) + ".bin")
                target.with_name(target.name + ".part").write_bytes(payload[:16])
                response = Response(suffix, status=206, headers={
                    "Content-Length": str(total - 16),
                    "Content-Range": f"bytes 16-{total - 1}/{total}",
                })
                with self.assertRaises(DownloadError):
                    self.download(target, response, sha1=hashlib.sha1(payload).hexdigest())
                self.assertFalse(target.exists())

    def test_unsolicited_partial_response_is_rejected(self):
        target = self.root / "unsolicited.bin"
        response = Response(b"a" * 16, status=206, headers={
            "Content-Length": "16", "Content-Range": "bytes 0-15/16",
        })
        with patch.object(response, "iter_content", wraps=response.iter_content) as body:
            with self.assertRaises(DownloadError):
                self.download(target, response, size=16)
            body.assert_not_called()
        self.assertFalse(target.exists())

    def test_cancellation_preserves_partial_and_destination(self):
        payload = b"0123456789abcdef" * 3
        target = self.root / "cancelled.bin"
        original = b"old file must survive cancellation"
        target.write_bytes(original)
        response = Response(payload)
        cancelled = False
        def chunks(chunk_size):
            nonlocal cancelled
            yield payload[:16]
            cancelled = True
            yield payload[16:]
        self.dm.cancel = lambda: cancelled
        with patch.object(response, "iter_content", side_effect=chunks):
            with self.assertRaisesRegex(DownloadError, "用户取消"):
                self.download(target, response, size=len(payload), force=True)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.with_name(target.name + ".part").read_bytes(), payload[:16])

    def test_200_response_ignores_range_and_restarts(self):
        payload = b"new complete payload" * 4
        target = self.root / "restart.bin"
        target.with_name(target.name + ".part").write_bytes(b"stale bytes")
        result, get = self.download(
            target, Response(payload), size=len(payload), sha1=hashlib.sha1(payload).hexdigest(),
        )
        self.assertEqual(result.read_bytes(), payload)
        self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=11-")

    def test_timeout_keeps_partial_and_retries_with_range(self):
        payload = b"0123456789abcdef" * 3
        target = self.root / "timeout.bin"
        first = Response(payload)
        second = Response(payload[16:], status=206, headers={
            "Content-Length": "32", "Content-Range": "bytes 16-47/48",
        })
        def interrupted(chunk_size):
            yield payload[:16]
            raise ReadTimeout("simulated read timeout")
        with patch.object(first, "iter_content", side_effect=interrupted), patch.object(
            self.dm.session, "get", side_effect=[first, second],
        ) as get:
            result = self.dm.download(
                "http://127.0.0.1:1/artifact", target, size=len(payload), expand=False,
                sha1=hashlib.sha1(payload).hexdigest(), timeout=(2, 7),
            )
        self.assertEqual(result.read_bytes(), payload)
        self.assertEqual(get.call_count, 2)
        self.assertNotIn("Range", get.call_args_list[0].kwargs["headers"])
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["Range"], "bytes=16-")
        self.assertEqual(get.call_args_list[1].kwargs["timeout"], (2.0, 7.0))


if __name__ == "__main__":
    unittest.main()
