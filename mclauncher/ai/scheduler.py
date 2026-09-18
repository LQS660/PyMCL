# -*- coding: utf-8 -*-
"""工具并行分组调度：只读组可并行；写/删除/启动/ask_user 各自独占一组。

⚠️ ask_user / confirm_fn 是跨线程等 UI 信号的操作，绝不能进并行组——
分组规则第一条就把它排除（name == "ask_user" 恒独占），组间严格串行。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

EXCLUSIVE_SIDE_EFFECTS = ("delete", "launch")
PARALLEL_SIDE_EFFECTS = ("none", "read", "network")


def _meta_of(metas, name: str):
    if metas is None:
        return None
    if hasattr(metas, "get"):
        return metas.get(name)
    return metas(name)


def is_exclusive(tc, metas) -> bool:
    """delete/launch 或 ask_user：必须独占一组（一组仅 1 个）。"""
    if getattr(tc, "name", "") == "ask_user":
        return True
    meta = _meta_of(metas, getattr(tc, "name", ""))
    return getattr(meta, "side_effect", "") in EXCLUSIVE_SIDE_EFFECTS


def is_parallelizable(tc, metas) -> bool:
    """只读且无副作用：可以进并行组。"""
    meta = _meta_of(metas, getattr(tc, "name", ""))
    if meta is None:
        return False
    return bool(getattr(meta, "readonly", False)) and \
        getattr(meta, "side_effect", "") in PARALLEL_SIDE_EFFECTS


def group(tool_calls, metas, max_concurrency: int = 4) -> list:
    """按规则分组成 list[list[ToolCall]]：
    1. delete/launch/ask_user → 每组仅 1 个
    2. readonly → 累积进当前并行组，超过 max_concurrency 开新组
    3. 其余（写）→ 每组 1 个，不与只读组混排
    4. 组间严格串行由 run_groups 保证
    """
    groups: list = []
    current: list = []

    def flush():
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for tc in tool_calls:
        if is_exclusive(tc, metas):
            flush()
            groups.append([tc])
        elif is_parallelizable(tc, metas):
            if len(current) >= max(1, max_concurrency):
                flush()
            current.append(tc)
        else:
            flush()
            groups.append([tc])
    flush()
    return groups


def run_groups(groups, execute, max_concurrency: int = 4) -> dict:
    """组间严格串行；只读组内并行。execute(tc) -> result（不得抛异常）。

    返回 {tc.id: result}。ask_user / confirm_fn 只会出现在独占组里，
    因此永远不会与其他工具并发。
    """
    out: dict = {}
    for grp in groups:
        if not grp:
            continue
        if len(grp) == 1:
            tc = grp[0]
            out[tc.id] = execute(tc)
            continue
        workers = min(max(1, max_concurrency), len(grp))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [(tc, pool.submit(execute, tc)) for tc in grp]
            for tc, fut in futures:
                out[tc.id] = fut.result()
    return out
