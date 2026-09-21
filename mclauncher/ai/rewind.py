# -*- coding: utf-8 -*-
"""「撤回最近一轮」的共享实现：截断对话 + 回滚该轮写操作（方案甲）。

Qt 进程内（app/pages/ai_page.py）与桥 RPC（bridge/api.py ai_rewind）都走这里，
保证两端行为一致。语义：
- 对话截到最近一条用户消息之前（与旧行为一致）；
- 该轮对磁盘的写/删改动用 checkpoint 回滚（字节级还原；快照失败的轮次
  回不来，返回值里带 not_rollbackable 提示）；
- 判断「最近一轮写没写」用 cache/ai_sessions/<chat_id>.jsonl 里最后一个
  TurnStarted 的 turn_id 对 checkpoint journal 里的 turn_id：对不上说明
  最近一轮没有写操作，磁盘不动。会话日志缺失时退回「journal 最近一组」。
"""

from __future__ import annotations

import json
import time

from mclauncher import utils

from . import checkpoint
from . import store as chat_store


def _turn_candidates(chat_id: str) -> list[str]:
    """会话事件日志里的回合 id 列表（按开始顺序），已撤回的回合剔除。

    每次 rewind 都会往日志里补一条 TurnRewound，于是连续撤回时目标逐轮前移。
    日志缺失（被 30 天清理 / 老版本）返回空列表，调用方退回 checkpoint journal。
    """
    try:
        d = chat_store.SESSIONS_DIR if chat_store.SESSIONS_DIR is not None \
            else utils.ROOT / "cache" / "ai_sessions"
        path = d / f"{str(chat_id or 'active')}.jsonl"
        if not path.is_file():
            return []
        started: list[str] = []
        rewound: set[str] = set()
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                tid = str(entry.get("turn_id") or "")
                if not tid:
                    continue
                event = entry.get("event")
                if event == "TurnStarted":
                    started.append(tid)
                elif event == "TurnRewound":
                    rewound.add(tid)
        return [t for t in started if t not in rewound]
    except Exception:  # noqa: BLE001
        return []


def _mark_rewound(chat_id: str, turn_id: str) -> None:
    try:
        chat_store.log_event(chat_id, "TurnRewound", turn_id=str(turn_id or ""))
    except Exception:  # noqa: BLE001
        pass


def rewind_last_round(chat_id: str) -> dict:
    """撤回 chat_id 会话的最近一轮。返回给 UI 的字段：

    ok / truncated / restored_files / restored_bytes / rollbackable /
    disk_changed（该轮是否有磁盘改动被还原）
    """
    chat_id = str(chat_id or "active")
    data = chat_store.load()
    chat = chat_store.get_chat(data, chat_id)
    if not chat:
        return {"ok": False, "truncated": False, "restored_files": 0,
                "restored_bytes": 0, "rollbackable": False, "disk_changed": False}
    msgs = chat.get("messages") or []
    idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            idx = i
            break
    if idx is None:
        return {"ok": True, "truncated": False, "restored_files": 0,
                "restored_bytes": 0, "rollbackable": False, "disk_changed": False}
    chat["messages"] = msgs[:idx]
    chat["updated"] = int(time.time())
    chat_store.save(data)

    # 磁盘回滚目标：这一轮的 turn_id（会话日志给出；日志缺失退回 journal 最近一组）
    candidates = _turn_candidates(chat_id)
    journaled = checkpoint.last_turn_id(chat_id)
    target = ""
    if candidates:
        # 从最近一轮往前找：该轮没写过磁盘（journal 里没有）也要标记已撤，
        # 否则下一轮撤回永远卡在同一个纯聊天回合上
        for tid in reversed(candidates):
            target = tid
            break
    else:
        target = journaled
    res = {"ok": True, "truncated": True, "restored_files": 0,
           "restored_bytes": 0, "rollbackable": bool(journaled),
           "disk_changed": False}
    if not target:
        return res
    has_ops = checkpoint.turn_has_ops(chat_id, target)
    if not has_ops and candidates:
        # 最近一轮没有磁盘改动：只标记，不动磁盘
        _mark_rewound(chat_id, target)
        return res
    if has_ops:
        rb = checkpoint.rollback(chat_id, turn_id=target)
        res.update(restored_files=rb.get("restored_files") or 0,
                   restored_bytes=rb.get("restored_bytes") or 0,
                   ok=bool(rb.get("ok")), disk_changed=True)
    _mark_rewound(chat_id, target)
    return res
