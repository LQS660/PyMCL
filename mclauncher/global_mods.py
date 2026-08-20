# -*- coding: utf-8 -*-
"""全局 Mod：shared/mods 里的 jar 启动前链到当前游戏 mods。"""
from __future__ import annotations

import os
from pathlib import Path

from . import utils
from .config import CONFIG


def root() -> Path:
    custom = str(CONFIG.get("global_mods_dir") or "").strip()
    if custom:
        return Path(custom)
    return utils.ROOT / "shared" / "mods"


def list_entries() -> list:
    d = root()
    if not d.is_dir():
        return []
    rows = []
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        low = p.name.lower()
        if low.endswith(".jar"):
            rows.append({"filename": p.name, "enabled": True, "bytes": p.stat().st_size})
        elif low.endswith(".jar.disabled") or low.endswith(".disabled"):
            rows.append({"filename": p.name, "enabled": False, "bytes": p.stat().st_size})
    return rows


def _link_file(dest: Path, src: Path):
    if dest.exists() or dest.is_symlink():
        return
    utils.ensure_dir(dest.parent)
    try:
        if os.name == "nt":
            import ctypes
            flags = 0x2  # SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE
            ok = ctypes.windll.kernel32.CreateSymbolicLinkW(str(dest), str(src), flags)
            if ok:
                return
        dest.symlink_to(src)
    except OSError:
        try:
            import shutil
            shutil.copy2(src, dest)
        except OSError:
            pass


def apply(game_mods_dir: Path) -> int:
    """把已启用的全局 jar 放进游戏 mods。返回链接/复制数量。"""
    src_dir = root()
    dest = Path(game_mods_dir)
    utils.ensure_dir(dest)
    if not src_dir.is_dir():
        return 0
    n = 0
    for p in src_dir.iterdir():
        if not p.is_file() or not p.name.lower().endswith(".jar"):
            continue
        _link_file(dest / p.name, p)
        n += 1
    return n
