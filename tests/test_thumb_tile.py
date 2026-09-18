# -*- coding: utf-8 -*-
"""缩略图磁贴：下载回来的图要贴上，磁贴先没了也不能把报错甩到日志里。

原来每块磁贴自己连 `_ThumbHub.loaded`，再用 `destroyed` 里的 lambda 断开。
`destroyed` 发出来时 C++ 那半边已经析构，PySide 拿 self 找不到接收者，
抛的是 `SystemError`（内层 `RuntimeError: Internal C++ object already deleted`
被包了一层）——旧代码 `except (TypeError, RuntimeError)` 一个都接不住，
于是关一次搜索结果就往 pymcl-error.log 里刷一批，连接也一条都没断成。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import shiboken6  # noqa: E402

from app import widgets  # noqa: E402
from mclauncher import thumbnails  # noqa: E402

_URL = "https://example.invalid/thumb-a.png"
_URL2 = "https://example.invalid/thumb-b.png"


class ThumbTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.png = os.path.join(cls._tmp.name, "thumb.png")
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(Qt.red)
        assert img.save(cls.png, "PNG")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._real = (thumbnails.thumb_path, thumbnails.ensure_thumb)
        # 本地缓存一律算作没有，逼每个用例都走「线程池下载」那条路
        thumbnails.thumb_path = lambda url: ""
        thumbnails.ensure_thumb = lambda url, dm=None: self.png
        thumbnails._recent_failures.clear()
        widgets._THUMB_WAITERS.clear()
        widgets._THUMB_PIXCACHE.clear()
        self.escaped: list[str] = []
        self._hooks = (sys.excepthook, sys.unraisablehook)
        sys.excepthook = lambda t, v, tb: self.escaped.append(f"{t.__name__}: {v}")
        sys.unraisablehook = lambda a: self.escaped.append(
            f"unraisable {type(a.exc_value).__name__}: {a.exc_value}")

    def tearDown(self):
        sys.excepthook, sys.unraisablehook = self._hooks
        thumbnails.thumb_path, thumbnails.ensure_thumb = self._real
        thumbnails._recent_failures.clear()
        widgets._THUMB_WAITERS.clear()
        widgets._THUMB_PIXCACHE.clear()

    def _drain(self):
        """等线程池把活干完，再把跨线程排进来的那一拍信号跑掉。"""
        widgets._thumb_pool().waitForDone(5000)
        self.app.processEvents()

    def test_live_tile_gets_the_pixmap(self):
        host = QWidget()
        tile = widgets.ThumbnailTile("Fabric API", _URL, 52, host)
        self.assertIn(_URL, widgets._THUMB_WAITERS)
        self._drain()
        self.assertTrue(tile._loaded)
        self.assertIsNotNone(tile._pixmap)
        self.assertEqual(widgets._THUMB_WAITERS, {})
        self.assertEqual(self.escaped, [])

    def test_destroyed_tile_does_not_raise(self):
        """列表重建：行控件连同磁贴一起析构，下载晚一步才回来。"""
        host = QWidget()
        for i in range(5):
            widgets.ThumbnailTile(f"mod-{i}", _URL, 52, host)
        shiboken6.delete(host)
        self.app.processEvents()
        self._drain()
        self.assertEqual(self.escaped, [])
        self.assertEqual(widgets._THUMB_WAITERS, {})

    def test_same_url_starts_one_job(self):
        calls: list[str] = []

        def counting(url, dm=None):
            calls.append(url)
            return self.png

        thumbnails.ensure_thumb = counting
        host = QWidget()
        tiles = [widgets.ThumbnailTile("same", _URL, 52, host) for _ in range(4)]
        tiles.append(widgets.ThumbnailTile("other", _URL2, 52, host))
        self._drain()
        self.assertEqual(sorted(calls), [_URL, _URL2])
        self.assertTrue(all(t._loaded for t in tiles))
        self.assertEqual(self.escaped, [])

    def test_url_in_cooldown_is_not_queued(self):
        """刚下过没下成的图：冷却期内磁贴不排队、不占线程池，直接留字母底色。"""
        calls: list[str] = []

        def counting(url, dm=None):
            calls.append(url)
            return self.png

        thumbnails.ensure_thumb = counting
        thumbnails._note_failure(_URL)
        host = QWidget()
        tile = widgets.ThumbnailTile("Blocked", _URL, 52, host)
        other = widgets.ThumbnailTile("Fine", _URL2, 52, host)
        self.assertNotIn(_URL, widgets._THUMB_WAITERS)
        self._drain()
        self.assertEqual(calls, [_URL2], "冷却中的 url 不该再发起下载")
        self.assertFalse(tile._loaded)
        self.assertTrue(other._loaded)
        self.assertEqual(self.escaped, [])

    def test_waiters_do_not_pile_up(self):
        """搜十页就攒十页的连接 —— 旧写法漏的就是这个。"""
        for page in range(10):
            host = QWidget()
            for row in range(20):
                widgets.ThumbnailTile(f"r{row}", f"{_URL}?p={page}&r={row}", 52, host)
            shiboken6.delete(host)
            self.app.processEvents()
            self._drain()
        self.assertEqual(widgets._THUMB_WAITERS, {})
        self.assertEqual(self.escaped, [])


if __name__ == "__main__":
    unittest.main()
