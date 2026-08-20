# -*- coding: utf-8 -*-
"""启动器自更新：查清单、下包、写替换脚本。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_VERSION, utils
from .config import CONFIG
from .downloader import DownloadManager

DEFAULT_URL = "https://pymcl.dev/update.json"


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
    return {
        "ok": True,
        "current": APP_VERSION,
        "latest": latest or APP_VERSION,
        "has_update": has,
        "message": f"发现 {latest}" if has else "已是最新版本",
        "notes": str((data or {}).get("notes") or (data or {}).get("changelog") or ""),
        "url": str((data or {}).get("url") or (data or {}).get("download") or ""),
        "sha256": str((data or {}).get("sha256") or ""),
    }


def download(info: dict, dm: DownloadManager | None = None) -> str:
    url = str((info or {}).get("url") or "")
    if not url:
        raise RuntimeError("更新清单没有下载地址")
    dm = dm or DownloadManager(threads=4)
    dest = utils.ROOT / "cache" / f"PyMCL-{info.get('latest') or 'update'}.bin"
    dm.download(url, dest)
    return str(dest)


def apply_exe(package: str) -> str:
    """下载完成后写 bat，退出后替换当前 exe。"""
    src = Path(package)
    exe = Path(sys.argv[0]).resolve()
    if exe.suffix.lower() != ".exe":
        return "当前不是打包版，请用新压缩包覆盖源码目录。"
    bat = exe.with_name("pymcl-apply-update.bat")
    bat.write_text(
        "@echo off\n"
        "timeout /t 2 /nobreak >nul\n"
        f'copy /Y "{src}" "{exe}"\n'
        f'start "" "{exe}"\n'
        f'del "%~f0"\n',
        encoding="gbk",
        errors="replace",
    )
    return str(bat)
