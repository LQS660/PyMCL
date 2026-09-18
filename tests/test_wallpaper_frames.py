# -*- coding: utf-8 -*-
"""动态壁纸取帧：转换必须留在发帧的那个线程上。

`videoFrameChanged` 是 FFmpeg 的渲染线程发的。以前这个槽按自动连接排队投递
到主线程，等主线程轮到这一帧，它背后那块后备缓冲（硬解时在显卡那边）早就
不归我们管了 —— pymcl-error.log 里连着三次
`Windows fatal exception: access violation`，faulthandler 指的都是
`app/background.py` 里 `frame.toImage()` 那一行。

所以这里盯三件事：取帧槽跑在发帧线程上、过给主线程的已经是拷好的 QImage、
收掉播放器之后解码线程再也打不进来。
"""
from __future__ import annotations

import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

try:
    from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
    HAVE_MULTIMEDIA = True
except ImportError:  # pragma: no cover - 这套 PySide6 没带 QtMultimedia
    HAVE_MULTIMEDIA = False

from app.background import BackgroundLayer  # noqa: E402


def _make_frame(w: int = 64, h: int = 48):
    fmt = QVideoFrameFormat(QSize(w, h), QVideoFrameFormat.PixelFormat.Format_RGBX8888)
    frame = QVideoFrame(fmt)
    if frame.map(QVideoFrame.MapMode.WriteOnly):
        frame.unmap()
    return frame


class ProbeLayer(BackgroundLayer):
    """记下取帧与贴图各自跑在哪个线程上。覆写而不是改连接，`_start_video`
    连的就是这两个覆写，`stop()` 也照样摘得干净。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grab_thread = None
        self.accept_thread = None
        self.images: list[QImage] = []

    def _grab_frame(self, frame):
        self.grab_thread = threading.get_ident()
        return super()._grab_frame(frame)

    def _accept_frame(self, img):
        self.accept_thread = threading.get_ident()
        self.images.append(img)
        return super()._accept_frame(img)


@unittest.skipUnless(HAVE_MULTIMEDIA, "这套 PySide6 没带 QtMultimedia")
class GrabFrameThreadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.host.resize(320, 240)
        self.layer = ProbeLayer(self.host)
        self.layer.resize(320, 240)
        self.host.show()
        self.layer.show()
        self.app.processEvents()
        self.addCleanup(self.host.deleteLater)
        self.addCleanup(self.layer.stop)

    def _start(self):
        """真走一遍 `_start_video` 的接线。片源不存在无所谓，sink 是真的。

        `_start_video` 会把节流表按下去，紧接着打进来的第一帧本来就该被挡；
        这里把它作废，让每个用例的第一帧稳定放行。
        """
        self.layer._start_video("nope.mp4")
        self.assertIsNotNone(self.layer._sink, self.layer.error)
        self.layer._gate.invalidate()
        return self.layer._sink

    def test_frame_is_converted_on_the_emitting_thread(self):
        """取帧跑在发帧线程上，贴图回到主线程——转换在那一跳之前就做完了。"""
        sink = self._start()
        frame = _make_frame()
        worker = threading.Thread(target=lambda: sink.setVideoFrame(frame))
        worker.start()
        worker.join(5)
        self.app.processEvents()

        self.assertIsNotNone(self.layer.grab_thread, "取帧槽没被调到")
        self.assertNotEqual(self.layer.grab_thread, threading.get_ident(),
                            "取帧槽跑回主线程了，等于没改")
        self.assertEqual(self.layer.accept_thread, threading.get_ident(),
                         "贴图那一半必须回到主线程")
        self.assertEqual(len(self.layer.images), 1)
        img = self.layer.images[0]
        self.assertIsInstance(img, QImage)
        self.assertFalse(img.isNull())
        self.assertEqual(img.size(), QSize(64, 48))

    def test_throttle_drops_before_converting(self):
        """节流挡在转换之前：连着打两帧，只有第一帧值得花钱转。"""
        sink = self._start()
        self.layer._pace = 10_000  # 间隔拉到十秒，第二帧必被挡下
        for _ in range(2):
            sink.setVideoFrame(_make_frame())
        self.app.processEvents()
        self.assertEqual(len(self.layer.images), 1, "节流没拦住第二帧")

    def test_stop_unhooks_the_decoder(self):
        """收掉播放器之后，解码线程再打帧进来也走不到转换那一步。"""
        sink = self._start()
        self.layer.stop()
        self.assertIsNone(self.layer._player)
        sink.setVideoFrame(_make_frame())
        self.app.processEvents()
        self.assertIsNone(self.layer.grab_thread, "停掉之后还在取帧")
        self.assertEqual(self.layer.images, [])


if __name__ == "__main__":
    unittest.main()
