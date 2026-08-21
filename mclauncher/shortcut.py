# -*- coding: utf-8 -*-
"""桌面快捷方式：双击直接启动某个实例的某个版本，对齐 PCL 的「创建桌面快捷方式」。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import utils

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BAD_NAME_CHARS = '\\/:*?"<>|'


class ShortcutError(Exception):
    pass


def safe_filename(name: str) -> str:
    out = "".join("_" if c in _BAD_NAME_CHARS else c for c in str(name or "").strip())
    return out.strip(". ") or "Minecraft"


_FOLDERID_DESKTOP = (0xB4BFCC3A, 0xDB2C, 0x424C,
                     (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))


def _windows_desktop() -> Path | None:
    """走 SHGetKnownFolderPath，OneDrive 重定向过的桌面也能拿对。"""
    import ctypes
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    d1, d2, d3, d4 = _FOLDERID_DESKTOP
    guid = _GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(out.value) if out.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def desktop_dir() -> Path:
    if utils.IS_WINDOWS:
        try:
            found = _windows_desktop()
        except OSError:
            found = None
        if found is not None and found.is_dir():
            return found
    home = Path.home()
    for name in ("Desktop", "桌面"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home


def launcher_command() -> list[str]:
    """返回能执行 CLI 子命令的程序。打包后优先用带控制台的 CLI exe。"""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        cli = exe.with_name("PyMCL-CLI.exe" if utils.IS_WINDOWS else "PyMCL-CLI")
        return [str(cli if cli.is_file() else exe)]
    entry = _PROJECT_ROOT / "main.py"
    if not entry.is_file():
        raise ShortcutError(f"找不到入口脚本: {entry}")
    return [sys.executable, str(entry)]


def launch_args(instance: str, version: str, username: str = "", account: str = "") -> list[str]:
    args = ["-i", str(instance), "launch", str(version)]
    if account:
        args += ["--account", str(account)]
    elif username:
        args += ["--username", str(username)]
    return args


def _quote(arg: str) -> str:
    arg = str(arg)
    return f'"{arg}"' if (" " in arg or not arg) else arg


def _ps_literal(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _decode_console(raw: bytes) -> str:
    """PowerShell 走控制台 OEM 代码页输出，不是 UTF-8。"""
    for codec in ("oem", "utf-8"):
        try:
            return raw.decode(codec, errors="replace")
        except LookupError:
            continue
    return raw.decode("latin-1", errors="replace")


def _create_windows(name: str, target: str, arguments: str, workdir: str,
                    icon: str, description: str) -> str:
    """用 WScript.Shell COM 生成 .lnk。目标路径在 Python 侧算好再传进去。"""
    path = desktop_dir() / f"{name}.lnk"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$sh = New-Object -ComObject WScript.Shell",
        f"$sc = $sh.CreateShortcut({_ps_literal(str(path))})",
        f"$sc.TargetPath = {_ps_literal(target)}",
        f"$sc.Arguments = {_ps_literal(arguments)}",
        f"$sc.WorkingDirectory = {_ps_literal(workdir)}",
        f"$sc.Description = {_ps_literal(description)}",
    ]
    if icon:
        lines.append(f"$sc.IconLocation = {_ps_literal(icon)}")
    lines.append("$sc.Save()")

    fd, script = tempfile.mkstemp(suffix=".ps1", prefix="pymcl_shortcut_")
    os.close(fd)
    script_path = Path(script)
    try:
        # 带 BOM，否则 Windows PowerShell 5.1 会把中文实例名读成乱码
        script_path.write_text("\n".join(lines), encoding="utf-8-sig")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            detail = _decode_console(proc.stderr or proc.stdout or b"").strip()
            raise ShortcutError(detail[:400] or "PowerShell 创建快捷方式失败")
    finally:
        script_path.unlink(missing_ok=True)
    if not path.is_file():
        raise ShortcutError(f"快捷方式未生成: {path}")
    return str(path)


def _create_linux(name: str, target: str, arguments: str, workdir: str,
                  icon: str, description: str) -> str:
    path = desktop_dir() / f"{name}.desktop"
    exec_line = f"{_quote(target)} {arguments}".strip()
    body = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Comment={description}",
        f"Exec={exec_line}",
        f"Path={workdir}",
        "Terminal=false",
        "Categories=Game;",
    ]
    if icon:
        body.append(f"Icon={icon}")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _create_macos(name: str, target: str, arguments: str, workdir: str,
                  icon: str, description: str) -> str:
    path = desktop_dir() / f"{name}.command"
    body = [
        "#!/bin/sh",
        f"# {description}",
        f"cd {_quote(workdir)}",
        f"exec {_quote(target)} {arguments}",
    ]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def create_launch_shortcut(instance: str, version: str, username: str = "",
                           account: str = "", name: str = "") -> str:
    """在桌面创建「直接启动某版本」的快捷方式，返回生成的文件路径。"""
    if not version:
        raise ShortcutError("请先选择要创建快捷方式的版本")
    cmd = launcher_command()
    target = cmd[0]
    args = cmd[1:] + launch_args(instance, version, username, account)
    arguments = " ".join(_quote(a) for a in args)
    label = safe_filename(name or f"{version} - {instance}" if instance else version)
    icon = ""
    for candidate in (_PROJECT_ROOT / "icon.ico", Path(sys.executable)):
        if utils.IS_WINDOWS and candidate.is_file():
            icon = str(candidate)
            break
    description = f"PyMCL 启动 {instance or 'default'} / {version}"
    workdir = str(_PROJECT_ROOT)

    if utils.IS_WINDOWS:
        return _create_windows(label, target, arguments, workdir, icon, description)
    if sys.platform == "darwin":
        return _create_macos(label, target, arguments, workdir, icon, description)
    return _create_linux(label, target, arguments, workdir, icon, description)


def remove_launch_shortcut(name: str) -> bool:
    label = safe_filename(name)
    suffix = ".lnk" if utils.IS_WINDOWS else (".command" if sys.platform == "darwin" else ".desktop")
    path = desktop_dir() / f"{label}{suffix}"
    if path.is_file():
        path.unlink()
        return True
    return False
