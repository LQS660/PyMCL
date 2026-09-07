# -*- coding: utf-8 -*-
"""启动 / 导航性能基准（离屏）。

测量：解释器 import 链、主窗口构造（懒加载后=首屏 4 页）、首屏显示、
逐页首次进入耗时（构造+reload）、连续切页延迟、全部页面建完后的工作集。
结果写 _perf_probe_out.txt。跑法：python _perf_probe.py
"""
import ctypes
import os
import sys
import time
import traceback
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LOG = open("_perf_probe_out.txt", "w", encoding="utf-8")


def say(*a):
    print(*a)
    print(*a, file=LOG)
    sys.stdout.flush()
    LOG.flush()


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_mb() -> float:
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD)
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        h = k32.GetCurrentProcess()
        if h and k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    try:
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD)
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if psapi.GetProcessMemoryInfo(-1, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return -1.0


t0 = time.perf_counter()
from PySide6.QtWidgets import QApplication  # noqa: E402
t_qt = time.perf_counter()

app = QApplication([])

t1 = time.perf_counter()
from app.main_window import MainWindow  # noqa: E402
t_import = time.perf_counter()

# feedback 链会顺带把 Qt/网络栈全部拉起来，必须放在计时之后；
# 心跳起 powershell 采硬件信息，与被测 UI 无关，一并挡掉。
from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

try:
    win = MainWindow()
except Exception:
    say("CONSTRUCT FAILED")
    say(traceback.format_exc())
    raise SystemExit(1)
t_construct = time.perf_counter()

win.resize(1180, 760)
win.show()
app.processEvents()
t_shown = time.perf_counter()

mem_boot = working_set_mb()

say(f"PySide6 import       : {(t_qt - t0) * 1000:8.1f} ms")
say(f"app.main_window import: {(t_import - t1) * 1000:8.1f} ms")
say(f"MainWindow construct  : {(t_construct - t_import) * 1000:8.1f} ms  (首屏页 {len(win._pages)} 个, 懒加载子页 {len(win._built)} 个)")
say(f"show + processEvents  : {(t_shown - t_construct) * 1000:8.1f} ms")
say(f"首屏可用总耗时(import 起): {(t_shown - t0) * 1000:8.1f} ms")
say(f"首屏工作集            : {mem_boot:8.1f} MB")
say("")

# 逐页首次进入（构造 + reload 都算进去）
for key in ("download", "ai", "more", "tasks"):
    t = time.perf_counter()
    win.side.set_current(key, emit=True)
    app.processEvents()
    say(f"首次进入 {key:10s}: {(time.perf_counter() - t) * 1000:8.1f} ms")

for sec_name in ("download_section", "more_section"):
    sec = getattr(win, sec_name)
    for title, getter in sec.pending_specs():
        t = time.perf_counter()
        page = getter()
        sec.show_page(page)
        app.processEvents()
        say(f"  子页 {title:10s}: {(time.perf_counter() - t) * 1000:8.1f} ms")

mem_all = working_set_mb()
say("")
say(f"全部页面建完工作集    : {mem_all:8.1f} MB  (增量 {mem_all - mem_boot:+.1f} MB)")

# 连续切页延迟（全部已构造，含 fade 动画截图）
keys = ["launch", "download", "ai", "more", "tasks"]
worst = 0.0
total = 0.0
for i in range(10):
    key = keys[i % len(keys)]
    t = time.perf_counter()
    win.side.set_current(key, emit=True)
    app.processEvents()
    dt = (time.perf_counter() - t) * 1000
    total += dt
    worst = max(worst, dt)
say(f"切页平均 {total / 10:.1f} ms / 最差 {worst:.1f} ms（10 次，含首刷）")

# 主题切换成本（表面刷新守卫生效后的重刷）
t = time.perf_counter()
for dark in (True, False):
    win.backend.save_settings({"ui_dark": dark})
    win.apply_theme()
    app.processEvents()
say(f"深浅主题往返          : {(time.perf_counter() - t) * 1000:.1f} ms")

# 二次主题切换（无变更路径）
t = time.perf_counter()
win.apply_theme()
app.processEvents()
say(f"重复 apply_theme      : {(time.perf_counter() - t) * 1000:.1f} ms")

# 单次真翻转（不经过 save_settings，只测 apply_theme 本体）
from mclauncher.config import CONFIG as _CFG
for dark in (True, False):
    _CFG.set("ui_dark", dark)
    t = time.perf_counter()
    win.apply_theme()
    app.processEvents()
    say(f"真翻转 apply_theme({dark}): {(time.perf_counter() - t) * 1000:.1f} ms")

try:
    win.close()
    app.processEvents()
except Exception:
    say(traceback.format_exc())

say("DONE")
LOG.close()
del win
app.quit()
app.processEvents()
del app
sys.exit(0)
