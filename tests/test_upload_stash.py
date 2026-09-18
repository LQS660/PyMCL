"""前端上传暂存：stash_upload 把 base64 换成后端能打开的真实路径。

浏览器的文件选择器只给文件名不给路径，导入模组 / 主题 / 本地整合包那几个 RPC
收的却都是路径。这里守住这一步的三件事：内容一字节不差、文件名是前端给的
所以不能让它跳出暂存目录、暂存区不能无限长大。
"""
from __future__ import annotations

import base64
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import bridge.api as bridge_api
from mclauncher import utils

BackendAPI = bridge_api.BackendAPI


class _Shim:
    """只借这两个方法，不碰 BackendAPI.__init__（会拉起下载线程等）。"""
    stash_upload = BackendAPI.stash_upload
    # 取下来的 staticmethod 已经是裸函数，直接挂上去会被当成实例方法
    _prune_uploads = staticmethod(BackendAPI._prune_uploads)


class TestStashUpload(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(utils, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.api = _Shim()

    def stash(self, name: str, payload: bytes) -> Path:
        return Path(self.api.stash_upload(name, base64.b64encode(payload).decode("ascii")))

    def test_roundtrip_is_byte_exact(self):
        payload = bytes(range(256)) * 40
        dest = self.stash("sodium.jar", payload)
        self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(dest.parent, self.root / "uploads")
        self.assertEqual(dest.name, "sodium.jar")

    def test_accepts_data_url_prefix(self):
        raw = base64.b64encode(b"{}").decode("ascii")
        dest = Path(self.api.stash_upload("theme.json", f"data:application/json;base64,{raw}"))
        self.assertEqual(dest.read_bytes(), b"{}")

    def test_same_name_twice_keeps_both(self):
        first = self.stash("mod.jar", b"one")
        second = self.stash("mod.jar", b"two")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertEqual(second.read_bytes(), b"two")

    def test_path_traversal_stays_inside(self):
        """文件名是前端给的：`../` 一旦生效就能往任意目录写文件。"""
        for name in ("../../evil.jar", r"..\..\evil.jar", "C:/Windows/evil.jar", "sub/dir/x.jar"):
            with self.subTest(name=name):
                dest = self.stash(name, b"x")
                self.assertEqual(dest.parent, self.root / "uploads")

    def test_blank_name_still_lands(self):
        self.assertEqual(self.stash("", b"x").name, "upload.bin")

    def test_rejects_garbage_and_empty(self):
        with self.assertRaises(ValueError):
            self.api.stash_upload("x.jar", "这不是 base64！")
        with self.assertRaises(ValueError):
            self.api.stash_upload("x.jar", "")

    def test_prunes_yesterdays_leftovers(self):
        """暂存目录是中转站，导入完那份拷贝就没用了。"""
        stale = self.stash("old.jar", b"old")
        old_time = time.time() - 48 * 3600
        import os
        os.utime(stale, (old_time, old_time))
        fresh = self.stash("new.jar", b"new")
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
