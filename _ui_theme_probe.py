# -*- coding: utf-8 -*-
"""只跑主题切换，把原生崩溃的 Python 栈打出来。"""
import faulthandler
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
faulthandler.enable(sys.stderr, all_threads=True)


def say(*a):
    print(*a, flush=True)
    print(*a, file=sys.stderr, flush=True)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1180, 760)
win.show()
app.processEvents()
say("constructed")

say("step: Theme.apply(dark)")
from app.pcl_chrome import Theme  # noqa: E402
Theme.apply(True)
say("  ok")

say("step: page.restyle() one by one")
for key, page in win._pages.items():
    if not hasattr(page, "restyle"):
        say("  (no restyle)", key)
        continue
    try:
        page.restyle()
        app.processEvents()
        say("  restyle ok:", key)
    except Exception:
        say("  RESTYLE RAISED:", key)
        say(traceback.format_exc())

say("step: full apply_theme")
data = win.backend.get_settings()
data["ui_dark"] = True
win.backend.save_settings(data)
win.apply_theme()
app.processEvents()
say("  apply_theme ok")

data["ui_dark"] = False
win.backend.save_settings(data)
win.apply_theme()
app.processEvents()
say("  apply_theme back ok")

say("DONE")
os._exit(0)
