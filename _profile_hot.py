# -*- coding: utf-8 -*-
"""热点剖析：主题翻转 / 首次进入下载区 / 子页构建。cProfile 输出 top 函数。"""
import cProfile
import io
import os
import pstats
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from app.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1180, 760)
win.show()
app.processEvents()


def top(profiler, tag, n=14):
    s = io.StringIO()
    st = pstats.Stats(profiler, stream=s)
    st.sort_stats("cumulative").print_stats(n)
    lines = s.getvalue().splitlines()
    keep = [ln for ln in lines if ln.strip()]
    print(f"\n===== {tag} =====")
    for ln in keep[4:4 + n + 2]:
        print(ln)


# 1) 首次进入下载分区（构造 VersionPage + reload + slide）
t = time.perf_counter()
p = cProfile.Profile()
p.enable()
win.side.set_current("download", emit=True)
app.processEvents()
p.disable()
print(f"\n首次进入 download 总耗时: {(time.perf_counter() - t) * 1000:.1f} ms")
top(p, "首次进入 download")

# 2) 整合包子页（第一次构造 PclCatalogPage + 热门列表）
sec = win.download_section
for title, getter in sec.pending_specs():
    if title != "整合包":
        continue
    t = time.perf_counter()
    p = cProfile.Profile()
    p.enable()
    page = getter()
    sec.show_page(page)
    app.processEvents()
    p.disable()
    print(f"\n整合包子页总耗时: {(time.perf_counter() - t) * 1000:.1f} ms")
    top(p, "整合包子页")

# 3) 设置子页
for title, getter in win.more_section.pending_specs():
    if title != "设置":
        continue
    t = time.perf_counter()
    p = cProfile.Profile()
    p.enable()
    page = getter()
    sec2 = win.more_section
    sec2.show_page(page)
    app.processEvents()
    p.disable()
    print(f"\n设置子页总耗时: {(time.perf_counter() - t) * 1000:.1f} ms")
    top(p, "设置子页")

# 4) 主题翻转（页面已大量构造的状态下）
from mclauncher.config import CONFIG as _CFG  # noqa: E402

t = time.perf_counter()
p = cProfile.Profile()
p.enable()
_CFG.set("ui_dark", True)
win.apply_theme()
app.processEvents()
p.disable()
print(f"\n真翻转 apply_theme(True) 总耗时: {(time.perf_counter() - t) * 1000:.1f} ms")
top(p, "真翻转 apply_theme(True)", 18)

t = time.perf_counter()
_CFG.set("ui_dark", False)
win.apply_theme()
app.processEvents()
print(f"真翻转 apply_theme(False): {(time.perf_counter() - t) * 1000:.1f} ms")

win.close()
app.processEvents()
sys.exit(0)
