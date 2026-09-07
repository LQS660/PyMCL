# -*- coding: utf-8 -*-
"""背景图修复探针：离屏验证 ui_background 从「被页面盖住」到真正生效。"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])

FAILS = []


def check(cond, msg):
    tag = "ok" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILS.append(msg)


tmp_img = os.path.abspath("_bg_probe_tmp.png").replace("\\", "/")
QImage(64, 64, QImage.Format_RGB32).fill(0xFF3C7A3C)
img = QImage(64, 64, QImage.Format_RGB32)
img.fill(0xFF3C7A3C)
img.save(tmp_img)

from app.main_window import MainWindow  # noqa: E402
from app.pcl_chrome import Theme  # noqa: E402

win = MainWindow()
orig_bg = win.backend.get_setting("ui_background") or ""
try:
    # 1) 无背景图：标记关闭、stacked 纯色、页面不透明
    check(Theme.background_active is False, "默认无图时 background_active=False")
    check("border-image" not in win.stackedWidget.styleSheet(), "默认 stacked 无 border-image")
    for key, page in win._pages.items():
        check("transparent" not in page.styleSheet(), f"无图时页面实底: {key}")

    # 2) 设置背景图并 apply_theme：标记打开、stacked 带图、页面/视口透明
    win.backend.save_settings({"ui_background": tmp_img})
    win.apply_theme()
    check(Theme.background_active is True, "设图后 background_active=True")
    ss = win.stackedWidget.styleSheet()
    check("border-image" in ss, "stacked 设了 border-image")
    check(tmp_img in ss, "border-image 路径正确")
    for key, page in win._pages.items():
        check("transparent" in page.styleSheet(), f"页面表面透明: {key}")
        check(not page.autoFillBackground(), f"页面关掉 autoFill: {key}")
    # more 分区子页（设置页所在）宿主也透明
    check("transparent" in win.more_section.styleSheet(), "more 分区根透明")

    # 3) 模拟「选择文件」后手输提交（不走对话框）
    sp = win.settings_page
    check(hasattr(sp, "bg_pick") and sp.bg_pick.isEnabled(), "设置页有「选择文件」按钮")
    sp.bg_edit.setText(tmp_img)
    sp._on_bg_committed()
    check(win.backend.get_setting("ui_background") == tmp_img, "_on_bg_committed 落盘")
    check(Theme.background_active is True, "提交后立即生效")

    # 4) 指向不存在的文件：回退纯色，不崩
    win.backend.save_settings({"ui_background": "Z:/no/such/file.png"})
    win.apply_theme()
    check(Theme.background_active is False, "坏路径回退纯色")
    for key, page in win._pages.items():
        check("transparent" not in page.styleSheet(), f"坏路径时页面恢复实底: {key}")

    # 5) 清空：恢复纯色
    win.backend.save_settings({"ui_background": ""})
    win.apply_theme()
    check(Theme.background_active is False, "清空回退纯色")
finally:
    try:
        win.backend.save_settings({"ui_background": orig_bg})
    except Exception:
        traceback.print_exc()
    if os.path.isfile(tmp_img):
        os.remove(tmp_img)

print("BG PROBE", "FAILED" if FAILS else "OK", f"({len(FAILS)} failures)")
sys.exit(1 if FAILS else 0)
