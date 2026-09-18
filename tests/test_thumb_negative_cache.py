# -*- coding: utf-8 -*-
"""缩略图下载失败要进冷却期，别每次重建列表都重新排队。

`ensure_thumb` 失败只返回空串、不落盘，于是账号页每 reload 一次就给每个头像
重新排一个下载：每条 20s 超时、线程池只有 4 条，crafatar / mc-heads 不通时
四条全挂住，目录页的图标排在后面干等。现在失败记进 `_recent_failures`，
`_FAIL_TTL` 内同一个 url 直接回空、磁贴也不排队。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import thumbnails  # noqa: E402

_URL = "https://example.invalid/face/steve.png"


class _FailingDM:
    def __init__(self):
        self.calls = 0

    def download(self, url, dest, **kwargs):
        self.calls += 1
        raise OSError("connection refused")


class _OkDM:
    def __init__(self):
        self.calls = 0

    def download(self, url, dest, **kwargs):
        self.calls += 1
        Path(dest).write_bytes(b"\x89PNG stub")
        return Path(dest)


def _age(url: str, seconds: float) -> None:
    """把这条失败记录往过去拨 seconds 秒，模拟冷却期走完。"""
    thumbnails._recent_failures[url] -= seconds


class NegativeCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_dir = thumbnails._thumb_dir
        thumbnails._thumb_dir = lambda: Path(self._tmp.name)
        thumbnails._recent_failures.clear()

    def tearDown(self):
        thumbnails._thumb_dir = self._real_dir
        thumbnails._recent_failures.clear()
        self._tmp.cleanup()

    def test_failure_is_remembered_and_not_retried(self):
        dm = _FailingDM()
        self.assertEqual(thumbnails.ensure_thumb(_URL, dm), "")
        self.assertTrue(thumbnails.recently_failed(_URL))
        for _ in range(5):
            self.assertEqual(thumbnails.ensure_thumb(_URL, dm), "")
        self.assertEqual(dm.calls, 1, "冷却期内不该再碰网络")

    def test_cooldown_expires(self):
        dm = _FailingDM()
        thumbnails.ensure_thumb(_URL, dm)
        _age(_URL, thumbnails._FAIL_TTL + 1)
        self.assertFalse(thumbnails.recently_failed(_URL))
        thumbnails.ensure_thumb(_URL, dm)
        self.assertEqual(dm.calls, 2, "过了冷却期该再试一次")

    def test_success_clears_the_mark(self):
        thumbnails.ensure_thumb(_URL, _FailingDM())
        self.assertTrue(thumbnails.recently_failed(_URL))
        _age(_URL, thumbnails._FAIL_TTL + 1)
        ok = _OkDM()
        path = thumbnails.ensure_thumb(_URL, ok)
        self.assertTrue(path and Path(path).is_file())
        self.assertFalse(thumbnails.recently_failed(_URL))
        # 落了盘之后走的是磁盘缓存，一次网络都不该有
        self.assertEqual(thumbnails.ensure_thumb(_URL, ok), path)
        self.assertEqual(ok.calls, 1)

    def test_other_urls_are_not_affected(self):
        thumbnails.ensure_thumb(_URL, _FailingDM())
        self.assertFalse(thumbnails.recently_failed(_URL + "?other"))
        self.assertFalse(thumbnails.recently_failed(""))

    def test_table_is_bounded(self):
        dm = _FailingDM()
        total = thumbnails._FAIL_CAP + 40
        for i in range(total):
            thumbnails.ensure_thumb(f"{_URL}?i={i}", dm)
            # 刚记下的这一条不管怎么裁都得在
            self.assertTrue(thumbnails.recently_failed(f"{_URL}?i={i}"))
        self.assertLessEqual(len(thumbnails._recent_failures), thumbnails._FAIL_CAP)
        # 裁掉的是最早那批
        self.assertFalse(thumbnails.recently_failed(f"{_URL}?i=0"))
        self.assertTrue(thumbnails.recently_failed(f"{_URL}?i={total - 1}"))


if __name__ == "__main__":
    unittest.main()
