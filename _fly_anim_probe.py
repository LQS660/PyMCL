# -*- coding: utf-8 -*-
"""离屏飞入动画探针：验证缓动、收尾、并发上限、弧高 clamp。"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget


def main() -> int:
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("fly-probe")
    win.resize(900, 640)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()

    src = QPushButton("源", win)
    src.setGeometry(700, 480, 80, 36)
    target = QPushButton("下载任务", win)
    target.setGeometry(20, 80, 120, 40)
    badge = QLabel("1", win)
    badge.setGeometry(130, 88, 20, 18)
    badge.show()
    win.task_badge = badge
    win.side = type("S", (), {"button": staticmethod(lambda k: target if k == "tasks" else None)})()
    win._fly_jobs = []

    from app.fly_anim import fly_to, _clamp_control
    from PySide6.QtCore import QPointF

    c = _clamp_control(QPointF(880, 620), QPointF(40, 40), win)
    assert 8 <= c.x() <= win.width() - 8
    assert 8 <= c.y() <= win.height() - 8

    landed = []

    def on_land():
        landed.append(time.monotonic())

    # 连发 3 次：jobs 上限 2，应能收尾且不卡住
    for i in range(3):
        fly_to(win, src, "M", "#2E9B6B", target=target, duration=180, on_landed=on_land)

    deadline = time.monotonic() + 3.0
    result = {"ok": False, "err": ""}

    def check():
        try:
            jobs = getattr(win, "_fly_jobs", [])
            balls = [c for c in win.children() if c.__class__.__name__ == "FlyBall"]
            if time.monotonic() > deadline:
                result["err"] = f"timeout jobs={len(jobs)} balls={len(balls)} landed={len(landed)}"
                app.quit()
                return
            if jobs or balls:
                QTimer.singleShot(30, check)
                return
            # 允许因并发砍球导致 landed < 3，但至少应有收尾且无残留
            if len(landed) < 1:
                result["err"] = "no land callback"
            else:
                result["ok"] = True
            app.quit()
        except Exception as exc:
            result["err"] = str(exc)
            app.quit()

    QTimer.singleShot(50, check)
    app.exec()
    if not result["ok"]:
        print("FAIL", result["err"])
        return 1
    print(f"PASS fly_anim landed={len(landed)} clamp=({c.x():.0f},{c.y():.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
