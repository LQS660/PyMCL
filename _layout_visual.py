# -*- coding: utf-8 -*-
"""布局功能视觉核验：离屏截图保存 PNG（默认布局 / 编辑模式 / 自定义布局 / 深色）。"""

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = "_layout_visual_out"
os.makedirs(OUT, exist_ok=True)

app = QApplication([])

try:
    from app.main_window import MainWindow
    from mclauncher.config import CONFIG
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    QTimer.singleShot(600, app.quit)
    app.exec()
    app.processEvents()

    lp = win.launch_page

    def snap(name):
        app.processEvents()
        ok = win.grab().save(f"{OUT}/{name}.png")
        print(("saved " if ok else "FAILED ") + name)

    snap("1-default")

    # 编辑模式
    lp.canvas.set_edit_mode(True)
    app.processEvents()
    snap("2-edit-mode")
    lp.canvas.set_edit_mode(False)

    # 自定义：加便签/快捷入口/时长/任务卡，缩小横幅
    lp.canvas.set_edit_mode(True)
    lp.canvas.add_card("notes")
    lp.canvas.add_card("quick")
    lp.canvas.add_card("playtime")
    lp.canvas.add_card("tasks")
    banner_it = lp.canvas.doc.get("banner-main")
    if banner_it:
        banner_it.h = 0.2
    lp.canvas._apply_geometry()
    lp.canvas.set_edit_mode(False)
    app.processEvents()
    snap("3-custom")

    # 深色
    CONFIG.set("ui_dark", True)
    CONFIG.save()
    win.apply_theme()
    app.processEvents()
    snap("4-dark")

    # 侧栏自定义（宽度+隐藏 AI）
    CONFIG.set("ui_sidebar_width", 240)
    CONFIG.set("ui_nav_hidden", ["ai"])
    CONFIG.save()
    win._rebuild_sidebar()
    app.processEvents()
    snap("5-sidebar")

    # 还原配置
    CONFIG.set("ui_sidebar_width", None)
    CONFIG.set("ui_nav_hidden", None)
    CONFIG.set("ui_dark", False)
    CONFIG.save()
    win._rebuild_sidebar()
    win.apply_theme()
    lp.canvas.reset_layout()
    lp._persist_layout_now()
    from app import layout_model as lm
    lm.reset_to_default()
    print("DONE")
except Exception:
    traceback.print_exc()
    print("FAIL")
