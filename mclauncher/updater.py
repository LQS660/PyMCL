# -*- coding: utf-8 -*-
"""启动器自更新：查清单、下包、写替换脚本。"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import APP_VERSION, utils
from .config import CONFIG
from .downloader import DownloadManager

DEFAULT_URL = "https://pymcl.dev/update.json"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _parse(ver: str) -> tuple:
    bits = []
    for part in str(ver or "0").replace("-", ".").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        bits.append(int(num or 0))
    while len(bits) < 3:
        bits.append(0)
    return tuple(bits[:4])


def newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse(remote) > _parse(local)


def manifest_url() -> str:
    return str(CONFIG.get("update_url") or DEFAULT_URL).strip()


def valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value or "").strip()))


def check(dm: DownloadManager | None = None) -> dict:
    url = manifest_url()
    dm = dm or DownloadManager(threads=2)
    try:
        data = dm.fetch_json(url, timeout=12)
    except Exception as exc:
        return {
            "ok": False,
            "current": APP_VERSION,
            "latest": APP_VERSION,
            "has_update": False,
            "message": f"检查更新失败: {exc}",
            "notes": "",
            "url": "",
        }
    latest = str((data or {}).get("version") or (data or {}).get("latest") or "")
    has = bool(latest and newer(latest))
    sha256 = str((data or {}).get("sha256") or "").strip().lower()
    # Auto-update is a code-execution boundary. Refuse unsigned or malformed
    # manifests instead of downloading an arbitrary executable from the URL.
    signed_update = has and valid_sha256(sha256)
    integrity_error = has and not signed_update
    return {
        "ok": not integrity_error,
        "current": APP_VERSION,
        "latest": latest or APP_VERSION,
        "has_update": signed_update,
        "message": (
            "更新清单缺少有效 SHA-256，已拒绝自动更新"
            if integrity_error else (f"发现 {latest}" if has else "已是最新版本")
        ),
        "notes": str((data or {}).get("notes") or (data or {}).get("changelog") or ""),
        "url": str((data or {}).get("url") or (data or {}).get("download") or ""),
        "sha256": sha256,
    }


def download(info: dict, dm: DownloadManager | None = None) -> str:
    url = str((info or {}).get("url") or "")
    if not url:
        raise RuntimeError("更新清单没有下载地址")
    sha256 = str((info or {}).get("sha256") or "").strip().lower()
    if not valid_sha256(sha256):
        raise RuntimeError("更新包缺少有效 SHA-256，已拒绝下载")
    dm = dm or DownloadManager(threads=4)
    dest = utils.ROOT / "cache" / f"PyMCL-{info.get('latest') or 'update'}.bin"
    dm.download(url, dest, sha256=sha256)
    # DownloadManager verifies while streaming. Keep an explicit final check
    # here as a guard for custom DownloadManager implementations.
    if utils.sha256_file(dest).lower() != sha256:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("更新包 SHA-256 校验失败")
    return str(dest)


def write_apply_script(package: str, exe: Path) -> Path:
    """生成替换脚本：等本进程真的退出再覆盖，而不是盲等 2 秒。"""
    src = Path(package)
    bat = exe.with_name("pymcl-apply-update.bat")
    pid = os.getpid()
    bat.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        ":waitloop\r\n"
        f'tasklist /fi "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto waitloop\r\n"
        ")\r\n"
        f'copy /Y "{src}" "{exe}"\r\n'
        f'start "" "{exe}"\r\n'
        'del "%~f0"\r\n',
        encoding="gbk",
        errors="replace",
    )
    return bat


def apply_exe(package: str, spawn: bool = True) -> str:
    """写替换脚本并把它拉起来。

    以前这里只写了个 bat 就返回路径，没人执行、进程也不退出：
    「检查更新」下完一个包，然后什么都没发生。
    """
    exe = Path(sys.argv[0]).resolve()
    if exe.suffix.lower() != ".exe":
        return "当前不是打包版，请用新压缩包覆盖源码目录。"
    bat = write_apply_script(package, exe)
    if not spawn:
        return str(bat)
    import subprocess
    creationflags = 0
    if utils.IS_WINDOWS:
        creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    return "UPDATE_STAGED"
