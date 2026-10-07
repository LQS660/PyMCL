# -*- coding: utf-8 -*-
"""启动前组装：隔离、全局 Mod、版本设置、启动脚本。"""
from __future__ import annotations

import os
import subprocess

from . import global_mods, utils, version_settings
from .argsplit import split_args
from .config import CONFIG


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
    mode = settings.get("window_mode") or CONFIG.get("window_mode") or "window"
    if mode in version_settings.FULLSCREEN_MODES and "--fullscreen" not in extras:
        extras.append("--fullscreen")
    from . import gc as gc_mod
    jvm = gc_mod.apply(settings.get("gc") or CONFIG.get("gc_preset") or "auto",
                       settings.get("jvm_args") or "")
    return {
        "settings": settings,
        "game_dir": gdir,
        "memory_mb": mem,
        "extra_game_args": extras,
        "jvm_args": jvm,
        "priority": settings.get("process_priority") or CONFIG.get("default_priority") or "normal",
        "global_mods": n,
        "pre_launch_wait": settings.get("pre_launch_wait", True),
        "login_account": settings.get("login_account") or "",
        "nide8_id": settings.get("nide8_id") or "",
        "auth_server": settings.get("auth_server") or "",
        "window_mode": mode,
        "window_width": _positive(settings.get("window_width")),
        "window_height": _positive(settings.get("window_height")),
        "window_title": (settings.get("window_title") or "").strip(),
    }


def _positive(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def resolve_resolution(prep, width=None, height=None):
    """版本设置的窗口大小优先于调用方传入的全局分辨率；全屏时兜底到 1280x720。"""
    w = prep.get("window_width") or width
    h = prep.get("window_height") or height
    if (prep.get("window_mode") or "window") in version_settings.FULLSCREEN_MODES:
        w = max(int(w or 0), 1280)
        h = max(int(h or 0), 720)
    return w, h


def _split_hook(command: str) -> list:
    """拆启动脚本命令行。

    Windows 上反斜杠是路径分隔符，POSIX 规则会把它当转义符吃掉
    （`C:\\tools\\run.bat` → `C:toolsrun.bat`），所以走 `posix=False`，
    再把 shlex 留在参数两端的引号剥掉。
    """
    import shlex

    if os.name != "nt":
        return split_args(command)
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return command.split()
    out = []
    for a in parts:
        if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'":
            a = a[1:-1]
        if a:
            out.append(a)
    return out


# cmd.exe 的内建命令（不是磁盘上的可执行文件，shell=False 直接跑会 FileNotFoundError）。
# 老版本把整条字符串交给 shell，`cd` / `copy` / `dir` 这类写法是能用的，这里保留兼容。
_CMD_BUILTINS = frozenset({
    "assoc", "break", "call", "cd", "chcp", "chdir", "cls", "color", "copy", "date",
    "del", "dir", "echo", "endlocal", "erase", "exit", "for", "ftype", "goto", "if",
    "md", "mkdir", "mklink", "move", "path", "pause", "popd", "prompt", "pushd",
    "rd", "rem", "ren", "rename", "rmdir", "set", "setlocal", "shift", "start",
    "time", "title", "type", "ver", "verify", "vol",
})

# cmd.exe 的命令分隔 / 重定向 / 转义 / 变量展开字符。
# 一个都不许出现在内建命令的原文里 —— 去掉它们之后 `cmd /c <字符串>` 既不能再起
# 一条命令，也不能重定向、不能展开变量（引号只做分词，安全）。
_CMD_UNSAFE = frozenset("&|<>^()%!\r\n")


def _cmd_builtin_argv(command: str) -> list | None:
    """内建命令的兼容通道；原文含任何 cmd 元字符就返回 None（拒绝执行）。

    审计 #1 P1-5：这条通道**不**恢复旧行为。旧实现是 `shell=True` 把整条字符串
    交给 cmd.exe 二次解析，`&` 就能执行任意命令；这里只放行「一个元字符都没有」
    的内建命令（`cd /d C:\\x`、`copy a b`、`dir` 之类），保证注入面为零。
    """
    if os.name != "nt":
        return None
    parts = _split_hook(command)
    if not parts or parts[0].lower() not in _CMD_BUILTINS:
        return None
    if any(ch in command for ch in _CMD_UNSAFE):
        return None
    return ["cmd", "/c", command]


def run_hook(command: str, cwd, log=None, wait: bool = True) -> int:
    """执行版本设置里的「启动前 / 退出后命令」。

    审计 #1 P1-5：这里以前用 `shell=True` 把整条字符串交给 cmd.exe。命令本身来自
    用户自己的版本设置（设计如此，PCL 同类功能），但和 P0-2 的版本 ID 穿越组合后
    就是一条任意命令执行链：只要能写一份 pymcl.json 到穿越位置，`pre_launch` 就会
    在启动器权限下被 shell 执行。

    现在 `shell=False` + argv 拆分：`&` / `|` / `>` 只是普通参数，不再是 shell 语法。
    脚本 / .bat 照旧能跑（Windows 上 CreateProcess 自己会处理 .bat）；cmd 内建命令
    走 `_cmd_builtin_argv` 的零元字符通道，`cmd /c ... & ...` 这类注入串会被直接拒绝。
    """
    cmd = (command or "").strip()
    if not cmd:
        return 0
    argv = _split_hook(cmd)
    if not argv:
        return 0
    if log:
        log(f"运行启动脚本: {cmd}")
    builtin = _cmd_builtin_argv(cmd)
    if builtin is None and argv[0].lower() in _CMD_BUILTINS:
        # 是内建命令但原文带元字符：拒绝执行，不让它回到 cmd.exe 二次解析
        if log:
            log("启动脚本包含 shell 元字符，已拒绝执行（改用 .bat / .cmd 脚本）")
        return -1
    if builtin is not None:
        argv = builtin
    try:
        if not wait:
            subprocess.Popen(
                argv, cwd=str(cwd),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return 0
        proc = subprocess.run(
            argv, cwd=str(cwd),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        # 命令不存在 / 不是可执行文件：启动链不该被一条脚本打断
        if log:
            log(f"启动脚本无法执行: {exc}")
        return -1
    if log and proc.stdout:
        for line in proc.stdout.splitlines()[:40]:
            log(line)
    if proc.returncode and log:
        log(f"脚本退出码 {proc.returncode}: {(proc.stderr or '')[:300]}")
    return proc.returncode
