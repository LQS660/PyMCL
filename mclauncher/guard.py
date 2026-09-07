# -*- coding: utf-8 -*-
"""启动器自身的全局异常捕捉：主线程、子线程、致命信号。"""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from mclauncher import utils

_installed = False
_log_path: Path | None = None
_ui_hook = None
_fault_fp = None


def log_path() -> Path:
    return _log_path or (utils.ROOT / "pymcl-error.log")


def write_log(kind: str, text: str) -> Path:
    path = log_path()
    block = (
        "=" * 64 + "\n"
        + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        + f" [{kind}]\n"
        + (text or "").rstrip()
        + "\n"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except OSError:
        pass
    return path


def _notify(kind: str, text: str):
    path = write_log(kind, text)
    try:
        sys.stderr.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass
    hook = _ui_hook
    if hook is None:
        return
    try:
        hook(kind, text, str(path))
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc, tb)
        return
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    _notify("unhandled", text)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    name = getattr(args.thread, "name", "?")
    _notify("thread", f"thread={name}\n{text}")


def install(path: Path | None = None, ui_hook=None) -> Path:
    """安装全局钩子。ui_hook(kind, text, log_path) 必须自己切回 UI 线程。"""
    global _installed, _log_path, _ui_hook, _fault_fp
    _log_path = Path(path) if path else (utils.ROOT / "pymcl-error.log")
    if ui_hook is not None:
        _ui_hook = ui_hook
    if _installed:
        return _log_path
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        _fault_fp = open(_log_path, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_fp, all_threads=True)
    except OSError:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass
    _installed = True
    write_log("guard", "global hooks installed")
    return _log_path
