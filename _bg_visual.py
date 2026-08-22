# -*- coding: utf-8 -*-
"""像素级验证：背景图设置后真的从页面底下透出来。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])
tmp = os.path.abspath("_bg_visual_tmp.png").replace(os.sep, "/")
img = QImage(600, 400, QImage.Format_RGB32)
img.fill(0xFF2E7D32)
img.save(tmp)

from app.main_window import MainWindow  # noqa: E402

win = MainWindow()
orig = win.backend.get_setting("ui_background") or ""
try:
    win.resize(1180, 760)
    win.show()
    app.processEvents()

    def corner_colors():
        pm = win.stackedWidget.grab()
        im = pm.toImage()
        w, h = im.width(), im.height()
        pts = [(4, 4), (w - 5, 4), (4, h - 5), (w - 5, h - 5), (w // 2, 8)]
        return [im.pixelColor(x, y).name() for x, y in pts]

    print("no-bg corners :", corner_colors())
    win.backend.save_settings({"ui_background": tmp})
    win.apply_theme()
    app.processEvents()
    cols = corner_colors()
    print("bg-on corners :", cols)
    green = sum(1 for c in cols if c.lower().lstrip("#").startswith("2")
                and abs(int(c[1:3], 16) - 0x2E) < 12
                and abs(int(c[3:5], 16) - 0x7D) < 12
                and abs(int(c[5:7], 16) - 0x32) < 12)
    print("green-ish pixels:", green, "/", len(cols))
    print("VISUAL", "OK" if green >= 3 else "FAIL")
    sys.exit(0 if green >= 3 else 1)
finally:
    win.backend.save_settings({"ui_background": orig})
    if os.path.isfile(tmp):
        os.remove(tmp)
