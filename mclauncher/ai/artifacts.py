# -*- coding: utf-8 -*-
"""超长工具结果落盘：cache/ai_results/<id>.txt，模型拿摘要 + 可 read_artifact 回读。"""

from __future__ import annotations

import datetime
import hashlib

from mclauncher import utils

# 测试可覆盖；None = 默认 utils.ROOT/cache/ai_results
ARTIFACTS_DIR = None

HEAD_LINES = 120
# 只增不删会把 cache 撑爆：保留最近 KEEP_DAYS 天、最多 KEEP_FILES 个，每个进程清一次
KEEP_DAYS = 7
KEEP_FILES = 300
_pruned = False


def _dir():
    if ARTIFACTS_DIR is not None:
        return utils.ensure_dir(ARTIFACTS_DIR)
    return utils.ensure_dir(utils.ROOT / "cache" / "ai_results")


def prune(days: int = KEEP_DAYS, keep: int = KEEP_FILES) -> int:
    """删过期 / 超量的 artifact，返回删掉的个数。任何失败都吞掉。"""
    removed = 0
    try:
        files = sorted(_dir().glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = datetime.datetime.now().timestamp() - days * 86400
        for i, p in enumerate(files):
            try:
                if i >= keep or p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return removed


def _prune_once() -> None:
    global _pruned
    if _pruned:
        return
    _pruned = True
    prune()


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n}B"


def artifact_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:8]


def save(text: str, tool_name: str = "") -> str:
    """把全文写盘，返回文件路径（供 read_artifact 用）。失败返回空串。"""
    try:
        _prune_once()
        day = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{day}-{artifact_id(text)}.txt"
        path = _dir() / name
        path.write_text(text or "", encoding="utf-8")
        return f"cache/ai_results/{name}"
    except Exception:  # noqa: BLE001
        return ""


def store(text: str, tool_name: str = "") -> str:
    """超限结果的替身文本：路径 + 总行数/字节 + 前 HEAD_LINES 行。"""
    rel = save(text, tool_name)
    lines = (text or "").splitlines()
    total_lines = len(lines)
    total_bytes = len((text or "").encode("utf-8", errors="replace"))
    if not rel:
        # 落盘失败：退回硬截断，信息至少不丢
        return text[:4000] + "\n…(已截断，落盘失败)"
    head = "\n".join(lines[:HEAD_LINES])
    return (
        f"[结果过长，已存文件] {rel}\n"
        f"总行数 {total_lines} / 总字节 {_fmt_size(total_bytes)}。"
        f"以下为前 {min(HEAD_LINES, total_lines)} 行：\n"
        f"{head}"
    )


def read_artifact(rel_or_name: str, offset: int = 0, limit: int = 200) -> str:
    """按行回读 artifact。offset/limit 都是行号（0 起）。"""
    name = str(rel_or_name or "").strip().replace("\\", "/").split("/")[-1]
    # 「D:xxx」这种盘符相对路径在 Windows 上会让 Path(dir) / name 直接换盘，
    # 只挡 / 和 .. 不够；名字里不许有冒号，拼出来的路径还要落在目录本身里。
    if not name or "/" in name or ".." in name or ":" in name:
        return "无效的 artifact 名"
    base = _dir().resolve()
    path = (base / name).resolve()
    if path.parent != base:
        return "无效的 artifact 名"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return f"找不到 artifact: {name}"
    lines = text.splitlines()
    start = max(0, int(offset or 0))
    end = min(len(lines), start + max(1, int(limit or 200)))
    if start >= len(lines):
        return f"起点超出范围（共 {len(lines)} 行）"
    body = "\n".join(lines[start:end])
    return f"[{name}] 第 {start + 1}-{end}/{len(lines)} 行：\n{body}"
