# -*- coding: utf-8 -*-
"""每版本设置：隔离、内存、Java、JVM、启动前后命令、直连服务器。对齐 PCL 版本设置。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import utils
from .config import CONFIG

FILE_NAME = "pymcl.json"
ISOLATION_NONE = "none"
ISOLATION_SAVES = "saves"
ISOLATION_MODS = "mods"
ISOLATION_ALL = "all"
ISOLATION_LABELS = {
    ISOLATION_NONE: "大锅饭（与其他版本共用）",
    ISOLATION_SAVES: "隔离存档",
    ISOLATION_MODS: "隔离 Mod 与配置",
    ISOLATION_ALL: "完全独立",
}
SHARED_LINKS = ("mods", "config", "resourcepacks", "shaderpacks", "downloads")
SAVES_LINKS = ("saves",)
# 版本卡上的一键开关只在这两档之间翻，四档细分留在版本设置里
ISOLATED_DEFAULT = ISOLATION_ALL
# 转独立时从大锅饭里带一份过去的内容
SEED_DIRS = ("mods", "config", "resourcepacks", "shaderpacks")

DEFAULTS = {
    "isolation": ISOLATION_NONE,
    "memory_mb": None,
    "java": "自动选择",
    "jvm_args": "",
    "game_args": "",
    "pre_launch": "",
    "post_launch": "",
    "pre_launch_wait": True,
    "server": "",
    "port": "",
    "process_priority": "normal",
    "icon": "",
    "hidden": False,
    "login_account": "",
    "auth_server": "",
    "auth_server_name": "",
    "nide8_id": "",
    "gc": "",
    "window_title": "",
    "window_mode": "window",
    "window_width": None,
    "window_height": None,
    "skip_assets": False,
    "offline_skin": "default",
}

# UI 历史上写过 "maximize"，启动链早期只认 "fullscreen"，两边对不上导致全屏静默失效。
# 以 "maximize" 为准，另一个作为别名容错。
FULLSCREEN_MODES = ("maximize", "fullscreen")


def _file(instance, version_id) -> Path:
    return instance.versions_dir() / version_id / FILE_NAME


def load(instance, version_id) -> dict:
    data = dict(DEFAULTS)
    stored = utils.read_json(_file(instance, version_id), None)
    if isinstance(stored, dict):
        data.update(stored)
    iso = data.get("isolation") or CONFIG.get("default_isolation") or ISOLATION_NONE
    if iso not in ISOLATION_LABELS:
        iso = ISOLATION_NONE
    data["isolation"] = iso
    return data


def save(instance, version_id, data: dict) -> dict:
    cur = load(instance, version_id)
    cur.update(data or {})
    if cur.get("isolation") not in ISOLATION_LABELS:
        cur["isolation"] = ISOLATION_NONE
    utils.write_json(_file(instance, version_id), cur)
    return cur


def is_isolated(settings) -> bool:
    """这个版本是否有自己的 mods 目录（而不是吃大锅饭）。"""
    iso = (settings or {}).get("isolation") or ISOLATION_NONE
    return iso in (ISOLATION_MODS, ISOLATION_ALL)


def set_isolation(instance, version_id, mode, seed=False) -> dict:
    """切隔离模式。`seed=True` 时把大锅饭里现有的模组/配置复制一份过去。

    转独立那一下版本目录是空的，不带种子的话用户会以为模组丢了；
    但整合包版本转独立时又不该把别人的模组拖进来，所以交给调用方决定。
    """
    if mode not in ISOLATION_LABELS:
        raise ValueError(f"未知的隔离模式: {mode!r}")
    before = load(instance, version_id)
    data = save(instance, version_id, {"isolation": mode})
    if seed and is_isolated(data) and not is_isolated(before):
        _seed_from_shared(instance, version_id)
    apply_isolation(instance, version_id, data)
    return data


def _seed_from_shared(instance, version_id):
    import shutil

    src_root = Path(instance.path)
    dest_root = instance.versions_dir() / version_id
    for name in SEED_DIRS:
        src = src_root / name
        if not src.is_dir():
            continue
        dest = dest_root / name
        utils.ensure_dir(dest)
        for child in src.iterdir():
            target = dest / child.name
            if target.exists() or child.is_symlink():
                continue
            try:
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)
            except OSError:
                continue


def game_dir(instance, version_id, settings=None) -> Path:
    settings = settings or load(instance, version_id)
    iso = settings.get("isolation") or ISOLATION_NONE
    if iso in (ISOLATION_ALL, ISOLATION_SAVES, ISOLATION_MODS):
        return instance.versions_dir() / version_id
    return Path(instance.path)


def mods_dir(instance, version_id, settings=None) -> Path:
    root = game_dir(instance, version_id, settings)
    return root / "mods"


def _junction(link: Path, target: Path):
    target = Path(target)
    link = Path(link)
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink() and any(link.iterdir()):
            return
        try:
            if link.is_symlink() or link.is_file():
                link.unlink()
            elif link.is_dir() and not any(link.iterdir()):
                link.rmdir()
        except OSError:
            return
    utils.ensure_dir(target)
    utils.ensure_dir(link.parent)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pass


def apply_isolation(instance, version_id, settings=None) -> Path:
    """按隔离模式准备游戏目录。返回 game_dir。"""
    settings = settings or load(instance, version_id)
    gdir = game_dir(instance, version_id, settings)
    utils.ensure_dir(gdir)
    iso = settings.get("isolation") or ISOLATION_NONE
    if iso == ISOLATION_SAVES:
        for name in SHARED_LINKS:
            _junction(gdir / name, Path(instance.path) / name)
        utils.ensure_dir(gdir / "saves")
    elif iso == ISOLATION_MODS:
        for name in SAVES_LINKS + ("resourcepacks", "shaderpacks", "screenshots"):
            _junction(gdir / name, Path(instance.path) / name)
        for name in ("mods", "config"):
            utils.ensure_dir(gdir / name)
    elif iso == ISOLATION_ALL:
        # 从「隔离存档 / 隔离 Mod」切过来时，之前建的联接还指着共享池，
        # 不摘掉的话「完全独立」写进去的东西照样落在大锅饭里。
        for name in set(SHARED_LINKS) | set(SAVES_LINKS) | {"screenshots"}:
            _drop_link(gdir / name)
        for name in ("mods", "config", "saves", "resourcepacks", "shaderpacks"):
            utils.ensure_dir(gdir / name)
    return gdir


def _drop_link(path: Path):
    from .single_root import drop_link

    drop_link(path)
