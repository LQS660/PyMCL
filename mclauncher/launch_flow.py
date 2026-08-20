# -*- coding: utf-8 -*-
"""启动前组装：隔离、全局 Mod、版本设置、启动脚本。"""
from __future__ import annotations

import os
import subprocess

from . import global_mods, utils, version_settings
from .argsplit import split_args


def prepare(instance, version_id, extra_game_args=None, memory_mb=None):
    settings = version_settings.load(instance, version_id)
    gdir = version_settings.apply_isolation(instance, version_id, settings)
    n = global_mods.apply(gdir / "mods")
    mem = settings.get("memory_mb") or memory_mb
    extras = [str(a) for a in (extra_game_args or []) if a not in (None, "")]
    extras += split_args(settings.get("game_args"))
    if settings.get("server") and "--server" not in extras:
        extras += ["--server", str(settings["server"])]
        extras += ["--port", str(settings.get("port") or 25565)]
    return {
        "settings": settings,
        "game_dir": gdir,
        "memory_mb": mem,
        "extra_game_args": extras,
        "jvm_args": settings.get("jvm_args") or "",
        "priority": settings.get("process_priority") or "normal",
        "global_mods": n,
    }


def run_hook(command: str, cwd, log=None) -> int:
    cmd = (command or "").strip()
    if not cmd:
        return 0
    if log:
        log(f"运行启动脚本: {cmd}")
    proc = subprocess.run(
        cmd, cwd=str(cwd), shell=True,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if log and proc.stdout:
        for line in proc.stdout.splitlines()[:40]:
            log(line)
    if proc.returncode and log:
        log(f"脚本退出码 {proc.returncode}: {(proc.stderr or '')[:300]}")
    return proc.returncode
