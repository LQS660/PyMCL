# -*- coding: utf-8 -*-
"""多对话持久化：重启后还在。工具调用轨迹与压缩摘要一并保留（批次 5）。"""

from __future__ import annotations

import datetime
import json
import threading
import time
import uuid

from mclauncher import utils

STORE_FILE = utils.ROOT / "ai_chats.json"
MAX_CHATS = 40
# 200 条 + 批次 3 的压缩共同控制真实体积；24 条会丢光工具上下文
MAX_MESSAGES = 200

# note = 「为什么停」的提示，只给界面渲染；api_messages 不会把它喂给模型
_KEEP_FIELDS = ("tool_calls", "tool_call_id", "name", "id", "note")

# 会话事件日志目录；测试可覆盖。None = 默认 utils.ROOT/cache/ai_sessions
SESSIONS_DIR = None
_EVENT_LOCK = threading.Lock()


def _empty():
    cid = _new_id()
    return {
        "active_id": cid,
        "chats": [_blank_chat(cid)],
    }


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _blank_chat(cid: str | None = None) -> dict:
    now = int(time.time())
    return {
        "id": cid or _new_id(),
        "title": "新对话",
        "updated": now,
        "messages": [],
    }


def _load_message(m: dict) -> dict:
    """保留工具轨迹字段（tool_calls / tool_call_id / name / id）。"""
    out = {"role": m.get("role"), "content": m.get("content") or ""}
    for key in _KEEP_FIELDS:
        if m.get(key) is not None:
            out[key] = m[key]
    return out


def load() -> dict:
    data = utils.read_json(STORE_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("chats"), list) or not data["chats"]:
        data = _empty()
        save(data)
        return data
    chats = []
    for raw in data["chats"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        entry = {
            "id": str(raw["id"]),
            "title": str(raw.get("title") or "对话")[:40],
            "updated": int(raw.get("updated") or 0),
            "messages": [
                _load_message(m)
                for m in (raw.get("messages") or [])
                if isinstance(m, dict)
                and m.get("role") in ("user", "assistant", "error", "tool")
            ][-MAX_MESSAGES:],
        }
        if isinstance(raw.get("plan"), dict):
            entry["plan"] = raw["plan"]     # 3.4 待办计划随会话持久化
        chats.append(entry)
    if not chats:
        data = _empty()
        save(data)
        return data
    active = str(data.get("active_id") or "")
    if not any(c["id"] == active for c in chats):
        active = chats[0]["id"]
    return {"active_id": active, "chats": chats}


def save(data: dict):
    chats = list(data.get("chats") or [])[:MAX_CHATS]
    active = str(data.get("active_id") or "")
    # 截断到 MAX_CHATS 之后 active 可能已经不在列表里：落盘时就校正，
    # 别等下次 load() 才自愈——中间这段 get_chat(active) 会一直拿到 None。
    if chats and not any(c.get("id") == active for c in chats):
        active = chats[0]["id"]
        data["active_id"] = active
    utils.write_json(STORE_FILE, {
        "active_id": active if chats else "",
        "chats": chats,
    })


def new_chat(data: dict) -> dict:
    chat = _blank_chat()
    data["chats"] = [chat] + list(data.get("chats") or [])
    data["chats"] = data["chats"][:MAX_CHATS]
    data["active_id"] = chat["id"]
    save(data)
    return chat


def get_chat(data: dict, cid: str) -> dict | None:
    for c in data.get("chats") or []:
        if c.get("id") == cid:
            return c
    return None


def set_active(data: dict, cid: str) -> dict | None:
    chat = get_chat(data, cid)
    if not chat:
        return None
    data["active_id"] = cid
    save(data)
    return chat


def api_messages(messages: list) -> list:
    """UI 历史 → 请求 messages。保留 assistant.tool_calls 与 tool 轨迹。"""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "error":
            role = "assistant"
        if role == "tool":
            entry = {"role": "tool", "content": m.get("content") or ""}
            if m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"]
            if m.get("name"):
                entry["name"] = m["name"]
            out.append(entry)
        elif role == "assistant":
            entry = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            out.append(entry)
        elif role == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
    # 切片可能把 tool 消息切到它前面的 assistant.tool_calls 之前，补丁在这里兜住
    while out and out[0].get("role") == "tool":
        out.pop(0)
    return out


def upsert_messages(data: dict, cid: str, messages: list, title: str | None = None):
    chat = get_chat(data, cid)
    if not chat:
        return
    chat["messages"] = [_load_message(m) if isinstance(m, dict) else m
                        for m in list(messages or [])][-MAX_MESSAGES:]
    chat["updated"] = int(time.time())
    if title:
        chat["title"] = str(title)[:40]
    elif chat.get("title") in ("", "新对话"):
        for m in chat["messages"]:
            if m.get("role") == "user" and (m.get("content") or "").strip():
                chat["title"] = (m["content"].strip().replace("\n", " "))[:24]
                break
    data["chats"].sort(key=lambda c: c.get("updated") or 0, reverse=True)
    save(data)


def prune_empty(data: dict) -> None:
    """清掉历史累积的空会话（没有一条消息的「新对话」）。

    最早因每次进页面都建新会话攒了一长串空条目。保留当前激活的空会话
    （没有就保留最新一个），其余全部丢弃。chats 列表由 upsert 按 updated
    倒序维护，empties[0] 即最新。
    """
    chats = data.get("chats") or []
    empties = [c for c in chats if not (c.get("messages") or [])]
    if len(empties) <= 1:
        return
    active = data.get("active_id")
    keep = next((c for c in empties if c.get("id") == active), empties[0])
    drop = {c["id"] for c in empties if c["id"] != keep["id"]}
    data["chats"] = [c for c in chats if c.get("id") not in drop]
    if data.get("active_id") in drop:
        data["active_id"] = (data["chats"][0]["id"] if data["chats"] else "")
    save(data)


def delete_chat(data: dict, cid: str) -> dict:
    data["chats"] = [c for c in (data.get("chats") or []) if c.get("id") != cid]
    if not data["chats"]:
        chat = _blank_chat()
        data["chats"] = [chat]
        data["active_id"] = chat["id"]
    elif data.get("active_id") == cid:
        data["active_id"] = data["chats"][0]["id"]
    save(data)
    return get_chat(data, data["active_id"])


def set_plan(data: dict, cid: str, plan: dict | None) -> None:
    """存/清一条对话的待办计划（批次 3.4）：{"turn_id", "items": [{title,status}]}。

    重开程序后 load() 原样带回，UI 恢复渲染。
    """
    chat = get_chat(data, cid)
    if not chat:
        return
    if plan is None:
        chat.pop("plan", None)
    else:
        chat["plan"] = plan
    save(data)


# ---------------------------------------------------------------- 会话事件日志

# 事件日志只增不删会一直长；每个进程第一次写的时候清一次 30 天前的、
# 单文件超过 EVENT_LOG_MAX_BYTES 的直接截掉重来（它是排障骨架，不是持久化）。
EVENT_LOG_KEEP_DAYS = 30
EVENT_LOG_MAX_BYTES = 4 * 1024 * 1024
_event_pruned = False


def _prune_event_logs(d) -> None:
    global _event_pruned
    if _event_pruned:
        return
    _event_pruned = True
    try:
        cutoff = time.time() - EVENT_LOG_KEEP_DAYS * 86400
        for p in d.glob("*.jsonl"):
            try:
                st = p.stat()
                if st.st_mtime < cutoff or st.st_size > EVENT_LOG_MAX_BYTES:
                    p.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


def log_event(session_id: str, event: str, **fields) -> None:
    """cache/ai_sessions/<session_id>.jsonl：正常流程骨架，与 trace 分工。

    绝不抛异常——日志坏了不能影响对话。
    """
    try:
        d = SESSIONS_DIR if SESSIONS_DIR is not None \
            else utils.ROOT / "cache" / "ai_sessions"
        utils.ensure_dir(d)
        _prune_event_logs(d)
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": str(event or ""),
        }
        entry.update(fields)
        path = d / f"{str(session_id or 'active')}.jsonl"
        with _EVENT_LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
