# -*- coding: utf-8 -*-
"""工具执行 hooks：前置/后置拦截点，支持入参改写与结果改写（批次 3.1）。

契约：
- ``before(tool_name, args) -> dict | None``：返回新 args 即改写入参；
- ``after(tool_name, result) -> str | None``：返回新字符串即改写结果；
- 钩子抛异常**绝不**中断对话：该钩子本次跳过，异常写 trace，工具照常返回；
- ``enabled`` 关闭后 run_before/run_after 原样透传，行为与没有 hook 机制一致
  （回归用 tests/test_ai_hooks.py 钉死）。

内置真实用例：写审计文件 —— 所有写/删工具执行前把 (工具, 参数摘要, 时间)
追加进 cache/ai_hooks/audit.jsonl，可随时用 ai_write_audit=False 关掉。
"""

from __future__ import annotations

import datetime
import json
import threading

from pathlib import Path

from mclauncher import utils

from . import trace

HOOKS_DIR = None      # 测试可覆盖；None = utils.ROOT/cache/ai_hooks
_LOCK = threading.Lock()
_enabled = True

_hooks: list = []     # list[Hook]


class Hook:
    """单个钩子：名字 + 可选的 before/after 回调。"""

    def __init__(self, name: str, before=None, after=None):
        self.name = str(name)
        self.before = before
        self.after = after


def register(hook: Hook) -> None:
    with _LOCK:
        _hooks.append(hook)


def unregister(name: str) -> None:
    with _LOCK:
        _hooks[:] = [h for h in _hooks if h.name != name]


def clear() -> None:
    with _LOCK:
        _hooks.clear()


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def run_before(tool_name: str, args: dict) -> tuple[dict, list[str]]:
    """跑前置钩子。返回 (最终 args, 错误列表)；args 以最后一位改写者为准。"""
    current = dict(args or {})
    if not _enabled:
        return current, []
    errors: list[str] = []
    with _LOCK:
        hooks = list(_hooks)
    for hook in hooks:
        if hook.before is None:
            continue
        try:
            out = hook.before(tool_name, current)
            if isinstance(out, dict):
                current = out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{hook.name}: {exc}")
            trace.record("hook_error", tool_name=tool_name, phase="before", exc=exc)
    return current, errors


def run_after(tool_name: str, result: str) -> tuple[str, list[str]]:
    """跑后置钩子。返回 (最终结果, 错误列表)。"""
    current = result
    if not _enabled:
        return current, []
    errors: list[str] = []
    with _LOCK:
        hooks = list(_hooks)
    for hook in hooks:
        if hook.after is None:
            continue
        try:
            out = hook.after(tool_name, current)
            if isinstance(out, str):
                current = out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{hook.name}: {exc}")
            trace.record("hook_error", tool_name=tool_name, phase="after", exc=exc)
    return current, errors


# ---------------------------------------------------------------- 内置审计钩子

WRITE_AUDIT_TOOLS = None   # None = 按 ToolMeta.side_effect 判（write_local/delete/launch）


def _audit_dir() -> Path:
    d = HOOKS_DIR if HOOKS_DIR is not None else utils.ROOT / "cache" / "ai_hooks"
    return utils.ensure_dir(d)

# 审计范围动态取自 TOOL_META.side_effect（写盘 / 删除 / 启动进程都算高危），
# 新增写类工具自动覆盖，不再依赖这份硬编码清单；清单只作 fallback
_WRITE_FALLBACK = {"write_mod_config", "delete_mod", "delete_instance", "create_instance",
                   "install_game", "install_mod", "install_modpack", "install_shader",
                   "install_resourcepack", "install_datapack", "install_world",
                   "download_java", "disable_mod", "enable_mod"}


def _audit_worthy(tool_name: str) -> bool:
    try:
        from .tools import TOOL_META
        meta = TOOL_META.get(tool_name)
        if meta is not None:
            return meta.side_effect in ("write_local", "write_external", "delete", "launch")
    except Exception:  # noqa: BLE001
        pass
    return tool_name in _WRITE_FALLBACK


def _audit_before(tool_name: str, args: dict) -> dict | None:
    if not _audit_worthy(tool_name):
        return None
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "tool": tool_name,
        "args_digest": json.dumps(args or {}, ensure_ascii=False,
                                  default=str)[:500],
    }
    with _LOCK:
        try:
            with open(_audit_dir() / "audit.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
    return None


register(Hook("write_audit", before=_audit_before))
