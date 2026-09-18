# -*- coding: utf-8 -*-
"""AI 异常与关键流程落盘：cache/ai_trace/<yyyymmdd>.jsonl。

trace 本身绝不能抛异常 —— 所有写文件操作都包在 try/except 里，
失败了就静默放弃（顶多丢一条日志，不能反过来弄死对话）。
"""

from __future__ import annotations

import datetime
import json
import threading

from mclauncher import utils

# 测试可以把它指到临时目录；None = 默认 utils.ROOT/cache/ai_trace
TRACE_DIR = None

_LOCK = threading.Lock()


def _dir():
    if TRACE_DIR is not None:
        return utils.ensure_dir(TRACE_DIR)
    return utils.ensure_dir(utils.ROOT / "cache" / "ai_trace")


def record(event: str, *, round_=None, phase="", tool_name="", exc=None,
           stream_failed=None, text_len=None, **extra):
    """追加一条结构化记录。任何失败都吞掉，绝不影响主流程。"""
    try:
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": str(event or ""),
            "round": round_,
            "phase": str(phase or ""),
            "tool_name": str(tool_name or ""),
        }
        if exc is not None:
            entry["exc_type"] = type(exc).__name__
            entry["exc_msg"] = str(exc)[:800]
        if stream_failed is not None:
            entry["stream_failed"] = bool(stream_failed)
        if text_len is not None:
            entry["text_len"] = int(text_len)
        if extra:
            entry.update(extra)
        day = datetime.date.today().strftime("%Y%m%d")
        path = _dir() / f"{day}.jsonl"
        line = json.dumps(entry, ensure_ascii=False)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def record_exception(exc: BaseException, event: str = "exception", **kw):
    record(event, exc=exc, **kw)
