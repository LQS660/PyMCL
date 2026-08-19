# -*- coding: utf-8 -*-
"""反馈上报与心跳。启动器只打反馈中心，不带管理令牌。"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import requests

from . import APP_VERSION, utils
from .config import CONFIG
from .feedback_defaults import (
    CATEGORIES, CLIENT_HEADER, DEFAULT_FEEDBACK_URL, HEARTBEAT_SEC,
)
from . import sysinfo as sysinfo_mod

DEVICE_FILE = utils.ROOT / "device_id"
HISTORY_FILE = utils.ROOT / "feedback_history.json"
MAX_HISTORY = 30

_HB_LOCK = threading.Lock()
_HB_STOP = threading.Event()
_HB_THREAD = None
_LAST_HB = {"t": 0.0, "ok": False, "error": ""}


class FeedbackError(Exception):
    pass


def category_label(key: str) -> str:
    for k, label in CATEGORIES:
        if k == key:
            return label
    return key or "其他"


def device_id() -> str:
    stored = (CONFIG.get("device_id") or "").strip()
    if stored:
        return stored
    try:
        if DEVICE_FILE.is_file():
            text = DEVICE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    value = uuid.uuid4().hex
    try:
        utils.ensure_dir(DEVICE_FILE.parent)
        DEVICE_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass
    try:
        CONFIG.set("device_id", value)
        CONFIG.save()
    except Exception:
        pass
    return value


def resolve_url() -> str:
    url = (CONFIG.get("feedback_url") or "").strip()
    if not url:
        import os
        url = (os.environ.get("PYMCL_FEEDBACK_URL") or DEFAULT_FEEDBACK_URL or "").strip()
    return url.rstrip("/")


def heartbeat_enabled() -> bool:
    return has_consent() and bool(CONFIG.get("feedback_heartbeat", True))


def consent_asked() -> bool:
    return CONFIG.get("feedback_consent") is not None


def has_consent() -> bool:
    return CONFIG.get("feedback_consent") is True


def set_consent(ok: bool) -> bool:
    CONFIG.set("feedback_consent", bool(ok))
    try:
        CONFIG.save()
    except Exception:
        pass
    return bool(ok)


def _session():
    sess = requests.Session()
    try:
        from .net import apply_direct_to_session
        apply_direct_to_session(sess)
    except Exception:
        pass
    return sess


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-PyMCL-Client": CLIENT_HEADER,
        "User-Agent": CLIENT_HEADER,
    }


def _post(path: str, payload: dict, timeout=20) -> dict:
    base = resolve_url()
    if not base:
        raise FeedbackError("未配置反馈服务器。开发者请启动 feedback_hub，并在设置里填写地址。")
    url = base + path
    try:
        sess = _session()
        resp = sess.post(url, json=payload, headers=_headers(), timeout=timeout)
    except requests.RequestException as exc:
        raise FeedbackError(f"连不上反馈服务器: {exc}") from exc
    text = (resp.text or "")[:800]
    if resp.status_code >= 400:
        raise FeedbackError(f"反馈服务器 HTTP {resp.status_code}: {text}")
    try:
        data = resp.json()
    except Exception:
        raise FeedbackError("反馈服务器返回了无法解析的内容")
    if not isinstance(data, dict):
        raise FeedbackError("反馈服务器返回格式不对")
    if data.get("ok") is False:
        raise FeedbackError(str(data.get("error") or "提交失败"))
    return data


def _history_load() -> list:
    rows = utils.read_json(HISTORY_FILE, []) or []
    return rows if isinstance(rows, list) else []


def _history_add(row: dict):
    rows = _history_load()
    rows.insert(0, row)
    utils.write_json(HISTORY_FILE, rows[:MAX_HISTORY])


def history() -> list:
    return _history_load()


def submit(
    category: str,
    title: str,
    body: str,
    contact: str = "",
    include_sysinfo: bool = True,
    crash: dict | None = None,
    scan_system_java: bool = True,
) -> dict:
    if not has_consent():
        raise FeedbackError("需要先同意上传诊断数据。第一次打开启动器时会询问，也可在设置里开启。")
    cat = (category or "other").strip().lower()
    if cat not in {k for k, _ in CATEGORIES}:
        cat = "other"
    title = (title or "").strip()[:120]
    body = (body or "").strip()[:16000]
    contact = (contact or "").strip()[:120]
    if not title and not body:
        raise FeedbackError("请填写标题或内容")
    if not title:
        title = (body.splitlines()[0] if body else "未命名反馈")[:80]
    payload = {
        "device_id": device_id(),
        "category": cat,
        "title": title,
        "body": body,
        "contact": contact,
        "app_version": APP_VERSION,
        "crash": crash if isinstance(crash, dict) else None,
    }
    if include_sysinfo:
        payload["sysinfo"] = sysinfo_mod.collect(force=True, scan_system_java=scan_system_java)
    data = _post("/api/v1/feedback", payload, timeout=25)
    _history_add({
        "id": data.get("id") or "",
        "ts": time.time(),
        "category": cat,
        "title": title,
        "ok": True,
    })
    return data


def submit_crash(report: dict, extra: str = "") -> dict:
    report = report or {}
    title = (report.get("headline") or report.get("title") or report.get("summary") or "游戏崩溃")[:120]
    chunks = [
        extra.strip(),
        str(report.get("summary") or ""),
        str(report.get("detail") or report.get("output_tail") or "")[:8000],
    ]
    body = "\n\n".join(x for x in chunks if x).strip() or title
    crash = {
        "headline": report.get("headline") or "",
        "summary": report.get("summary") or "",
        "title": report.get("title") or "",
        "help": report.get("help") or "",
        "direct_file": report.get("direct_file") or "",
    }
    return submit("crash", title, body, include_sysinfo=True, crash=crash)


def heartbeat_once(status: str = "online") -> dict:
    if not has_consent():
        raise FeedbackError("需要先同意上传诊断数据")
    payload = {
        "device_id": device_id(),
        "status": status if status in ("online", "offline") else "online",
        "app_version": APP_VERSION,
        "sysinfo": sysinfo_mod.collect(scan_system_java=False) if status != "offline" else {},
    }
    return _post("/api/v1/heartbeat", payload, timeout=12)


def last_heartbeat() -> dict:
    return dict(_LAST_HB)


def _hb_loop(interval: float):
    while not _HB_STOP.is_set():
        if heartbeat_enabled() and resolve_url():
            try:
                heartbeat_once("online")
                _LAST_HB["t"] = time.time()
                _LAST_HB["ok"] = True
                _LAST_HB["error"] = ""
            except Exception as exc:
                _LAST_HB["t"] = time.time()
                _LAST_HB["ok"] = False
                _LAST_HB["error"] = str(exc)
                utils.log.debug("反馈心跳失败: %s", exc)
        _HB_STOP.wait(interval)


def start_heartbeat(interval: float | None = None):
    global _HB_THREAD
    sec = float(interval or HEARTBEAT_SEC)
    with _HB_LOCK:
        if _HB_THREAD and _HB_THREAD.is_alive():
            return
        _HB_STOP.clear()
        _HB_THREAD = threading.Thread(
            target=_hb_loop, args=(sec,), name="pymcl-feedback-hb", daemon=True)
        _HB_THREAD.start()


def stop_heartbeat(send_offline: bool = True):
    _HB_STOP.set()
    if send_offline and resolve_url() and heartbeat_enabled():
        try:
            heartbeat_once("offline")
        except Exception:
            pass
