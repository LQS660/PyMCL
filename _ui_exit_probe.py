# -*- coding: utf-8 -*-
"""退出链路探针：量一量关闭主窗口后，后台线程到底还要跑多久。

用途是回答一个具体问题——`BackendAPI.shutdown()` 的等待预算该给多少，
以及卡住的到底是「慢但有限」的调用，还是真的永不返回。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from app.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1180, 760)
win.show()
app.processEvents()

for key in list(win._pages):
    win.side.set_current(key, emit=True)
    app.processEvents()

backend = win.backend
print("bg_threads after nav:", len(backend._bg_threads), flush=True)
print("workers after nav:", len(backend._workers), flush=True)

t0 = time.monotonic()
win.close()
app.processEvents()
print(f"close() took {time.monotonic() - t0:.2f}s", flush=True)

# 关完再等，看剩下的线程各自还要多久
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    live = [w for w in list(backend._bg_threads) if w.isRunning()]
    if not live:
        break
    app.processEvents()
    time.sleep(0.1)

print(f"all bg threads settled after {time.monotonic() - t0:.2f}s total", flush=True)
print("remaining bg:", [type(w).__name__ for w in backend._bg_threads if w.isRunning()], flush=True)

mode = sys.argv[1] if len(sys.argv) > 1 else "hard"
print(f"exiting via {mode}", flush=True)
sys.stdout.flush()
if mode == "hard":
    os._exit(0)
# 正常退出：先放掉 QApplication，再让解释器自己收尾
del win
app.quit()
app.processEvents()
del app
sys.exit(0)
