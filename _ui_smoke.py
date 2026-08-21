# -*- coding: utf-8 -*-
"""UI 冒烟测试：离屏构造主窗口、逐页切换，抓 Python 异常与 Qt 告警。"""
import faulthandler
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LOG = open("_ui_smoke_out.txt", "w", encoding="utf-8")
faulthandler.enable(LOG)


def say(*a):
    print(*a)
    print(*a, file=LOG)
    sys.stdout.flush()
    LOG.flush()


# 反馈心跳会在后台线程里反复起 powershell 采集硬件信息，脚本退出时容易撞上，
# 跟被测的 UI 无关，直接挡掉免得干扰结果。
from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtCore import qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

qt_msgs = []
qInstallMessageHandler(lambda t, ctx, m: qt_msgs.append((int(t), m)))

app = QApplication([])

try:
    from app.main_window import MainWindow
except Exception:
    say("IMPORT FAILED")
    say(traceback.format_exc())
    raise SystemExit(1)

try:
    win = MainWindow()
except Exception:
    say("CONSTRUCT FAILED")
    say(traceback.format_exc())
    raise SystemExit(1)

win.resize(1180, 760)
win.show()
app.processEvents()
say("MainWindow constructed, pages:", len(win._pages))

for key in list(win._pages):
    try:
        win.side.set_current(key, emit=True)
        app.processEvents()
        say("  nav ok:", key)
    except Exception:
        say("  NAV FAIL:", key)
        say(traceback.format_exc())

# 下载分区的子页逐个切
try:
    sec = win.download_section
    for page, title in list(sec._by_widget.items()):
        try:
            sec.show_page(page)
            app.processEvents()
            say("  sub ok:", title)
        except Exception:
            say("  SUB FAIL:", title)
            say(traceback.format_exc())
except Exception:
    say(traceback.format_exc())

# 深色模式往返
for dark in (True, False):
    try:
        data = win.backend.get_settings()
        data["ui_dark"] = dark
        win.backend.save_settings(data)
        win.apply_theme()
        app.processEvents()
        say("  theme ok, dark =", dark)
    except Exception:
        say("  THEME FAIL, dark =", dark)
        say(traceback.format_exc())

# 缩放
for w, h in ((820, 600), (1600, 900), (1180, 760)):
    try:
        win.resize(w, h)
        app.processEvents()
        say(f"  resize ok: {w}x{h}")
    except Exception:
        say(f"  RESIZE FAIL: {w}x{h}")
        say(traceback.format_exc())

# 关窗：走一遍真实的 closeEvent（含后台线程收拢）。
# 以前脚本直接 os._exit(0) 跳过退出链路，结果「关闭时后台线程还在跑」这类问题
# 一次都测不到——而它真实存在，表现是进程偶发以 0xC0000005 退出。
try:
    win.close()
    app.processEvents()
    say("  close ok")
except Exception:
    say("  CLOSE FAIL")
    say(traceback.format_exc())

say("--- Qt messages (deduped) ---")
seen = set()
for t, m in qt_msgs:
    if m in seen:
        continue
    seen.add(m)
    say(f"[{t}] {m}")

say("DONE")
LOG.close()

# 不要用 os._exit()。实测在 Windows 上带着已加载的 Qt 硬退出，约 1/4 的概率
# 在 DLL detach 阶段以 0xC0000005 结束进程 —— 那是脚本自己制造的假崩溃，
# 会让「退出码非 0」这个信号彻底失去意义。走正常析构，实测 4/4 干净。
del win
app.quit()
app.processEvents()
del app
sys.exit(0)
