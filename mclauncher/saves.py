# -*- coding: utf-8 -*-
"""存档 / 截图 / 崩溃报告 / 日志浏览。"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import utils
from . import version_settings as vs
from .crash import open_path
from .instances import Instance


class SaveError(Exception):
    pass


def _game_dir(instance: Instance, version_id: str = "") -> Path:
    if version_id:
        return vs.game_dir(instance, version_id)
    return Path(instance.path)


def list_saves(instance: Instance, version_id: str = "") -> list[dict]:
    folder = _game_dir(instance, version_id) / "saves"
    if not folder.is_dir():
        return []
    rows = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir():
            continue
        icon = p / "icon.png"
        rows.append({
            "name": p.name,
            "path": str(p),
            "icon": str(icon) if icon.is_file() else "",
            "bytes": _dir_size(p),
            "mtime": int(p.stat().st_mtime),
        })
    return rows


def delete_save(instance: Instance, name: str, version_id: str = ""):
    folder = (_game_dir(instance, version_id) / "saves").resolve()
    target = (folder / name).resolve()
    if target.parent != folder:
        raise SaveError(f"非法存档名: {name}")
    if not target.exists():
        raise SaveError(f"存档不存在: {name}")
    utils.remove_tree(target)


def open_save(instance: Instance, name: str, version_id: str = "") -> str:
    folder = _game_dir(instance, version_id) / "saves" / name
    if not folder.is_dir():
        raise SaveError(f"存档不存在: {name}")
    open_path(folder)
    return str(folder)


def install_datapack_into_save(instance: Instance, filename: str, save_name: str,
                               version_id: str = "") -> str:
    src = (instance.path / "datapacks" / filename).resolve()
    root = (instance.path / "datapacks").resolve()
    if src.parent != root or not src.is_file():
        raise SaveError(f"数据包不存在: {filename}")
    dest_dir = _game_dir(instance, version_id) / "saves" / save_name / "datapacks"
    utils.ensure_dir(dest_dir)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return str(dest)


def list_media(instance: Instance, kind: str, version_id: str = "") -> list[dict]:
    mapping = {
        "screenshots": ("screenshots", (".png", ".jpg", ".jpeg")),
        "crash-reports": ("crash-reports", (".txt",)),
        "logs": ("logs", (".log", ".gz", ".txt")),
    }
    if kind not in mapping:
        raise SaveError(f"未知类型: {kind}")
    sub, exts = mapping[kind]
    folder = _game_dir(instance, version_id) / sub
    if not folder.is_dir():
        return []
    rows = []
    for p in sorted(folder.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix.lower() in exts:
            rows.append({
                "name": p.name,
                "path": str(p),
                "bytes": p.stat().st_size,
                "mtime": int(p.stat().st_mtime),
            })
    return rows[:200]


def _dir_size(path: Path, limit=80) -> int:
    total = 0
    n = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
                n += 1
                if n >= limit:
                    break
    except OSError:
        pass
    return total
