# -*- coding: utf-8 -*-
"""存档 / 截图 / 崩溃报告 / 日志浏览 / 存档备份。"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PureWindowsPath

from . import utils
from . import version_settings as vs
from .crash import open_path
from .instances import Instance

BACKUP_DIR_NAME = "backups"
_STAMP_RE = re.compile(r"-(\d{8}-\d{6})(?:-\d+)?$")


class SaveError(Exception):
    pass


def _game_dir(instance: Instance, version_id: str = "") -> Path:
    if version_id:
        return vs.game_dir(instance, version_id)
    return Path(instance.path)


def _safe_child(folder: Path, name: str, what: str = "存档") -> Path:
    """只允许访问 folder 的直接子项，挡掉 ../ 之类的路径穿越。"""
    folder = folder.resolve()
    target = (folder / name).resolve()
    if target.parent != folder:
        raise SaveError(f"非法{what}名: {name}")
    return target


def list_saves(instance: Instance, version_id: str = "") -> list[dict]:
    folder = _game_dir(instance, version_id) / "saves"
    if not folder.is_dir():
        return []
    rows = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir() or p.name.startswith("."):
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
    target = _safe_child(_game_dir(instance, version_id) / "saves", name)
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
    # 审计 #1 P1-3：save_name 以前直接拼路径，`../../X` 能把数据包写到 saves/ 之外
    # （同函数的 filename 与 backup_save / restore_backup 早就走了 _safe_child）。
    save_dir = _safe_child(_game_dir(instance, version_id) / "saves", save_name)
    dest_dir = save_dir / "datapacks"
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


def backups_dir(instance: Instance, version_id: str = "") -> Path:
    """备份跟着存档走：版本隔离时进版本目录，否则进实例目录。"""
    return _game_dir(instance, version_id) / BACKUP_DIR_NAME


def backup_save(instance: Instance, name: str, version_id: str = "",
                on_progress=None) -> dict:
    """把一个存档打包成 zip 存到 backups/，返回备份信息。"""
    src = _safe_child(_game_dir(instance, version_id) / "saves", name)
    if not src.is_dir():
        raise SaveError(f"存档不存在: {name}")
    dest_dir = backups_dir(instance, version_id)
    utils.ensure_dir(dest_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{src.name}-{stamp}.zip"
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.name}-{stamp}-{n}.zip"
        n += 1

    files = [p for p in src.rglob("*") if p.is_file()]
    total = len(files) or 1
    tmp = dest.with_suffix(".zip.part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for i, p in enumerate(files, 1):
                zf.write(p, str(Path(src.name) / p.relative_to(src)))
                if on_progress:
                    on_progress(f"备份 {src.name}", i, total)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {
        "name": dest.name,
        "path": str(dest),
        "save": src.name,
        "bytes": dest.stat().st_size,
        "mtime": int(dest.stat().st_mtime),
    }


def list_backups(instance: Instance, save_name: str = "", version_id: str = "") -> list[dict]:
    folder = backups_dir(instance, version_id)
    if not folder.is_dir():
        return []
    rows = []
    for p in folder.glob("*.zip"):
        if not p.is_file():
            continue
        origin = _STAMP_RE.sub("", p.stem)
        if save_name and origin != save_name:
            continue
        rows.append({
            "name": p.name,
            "path": str(p),
            "save": origin,
            "bytes": p.stat().st_size,
            "mtime": int(p.stat().st_mtime),
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def restore_backup(instance: Instance, backup_name: str, version_id: str = "",
                   target_name: str = "", overwrite: bool = False) -> dict:
    """把备份还原回 saves/。默认不覆盖同名存档，而是加 -还原 后缀另存。"""
    archive = _safe_child(backups_dir(instance, version_id), backup_name, "备份")
    if not archive.is_file():
        raise SaveError(f"备份不存在: {backup_name}")
    saves_root = _game_dir(instance, version_id) / "saves"
    utils.ensure_dir(saves_root)
    origin = target_name or _STAMP_RE.sub("", archive.stem)
    dest = _safe_child(saves_root, origin)

    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise SaveError(f"备份文件损坏: {exc}") from exc
    with zf:
        members = zf.infolist()
        names = [m.filename for m in members
                 if not m.filename.replace("\\", "/").endswith("/")]
        if not names:
            raise SaveError("备份是空的")
        # 目录条目也必须校验；同时拒绝在不同平台上含义不同的 Windows 路径。
        for info in members:
            member = info.filename
            raw = member.replace("\\", "/")
            if (Path(member).is_absolute() or ".." in Path(member).parts
                    or raw.startswith("/") or ".." in raw.split("/")
                    or PureWindowsPath(member).drive):
                raise SaveError(f"备份包含非法路径: {member}")

        # 同盘唯一目录，不清理同一秒另一项恢复的临时数据。
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=saves_root))
        unpacked = staging / "unpacked"
        keep_staging = False
        try:
            utils.ensure_dir(unpacked)
            zf.extractall(unpacked)
            entries = list(unpacked.iterdir())
            # 标准备份剥掉世界目录；平铺 ZIP（甚至只有 level.dat）仍恢复成目录。
            inner = entries[0] if len(entries) == 1 and entries[0].is_dir() else unpacked
            if not overwrite:
                n = 1
                while dest.exists():
                    dest = _safe_child(saves_root, f"{origin}-还原{n if n > 1 else ''}")
                    n += 1

            # 校验、解压、CRC 检查全部成功后才动原存档；发布失败可原地回滚。
            previous = None
            if overwrite and dest.exists():
                previous = staging / "previous"
                os.replace(dest, previous)
            try:
                os.replace(inner, dest)
            except OSError:
                if previous is not None:
                    try:
                        os.replace(previous, dest)
                    except OSError as exc:
                        # 回滚也被文件锁挡住时保留旧数据，绝不随 staging 一起删掉。
                        keep_staging = True
                        raise SaveError(f"还原失败，原存档保留在 {previous}: {exc}") from exc
                raise
        finally:
            if not keep_staging:
                utils.remove_tree(staging)
    return {"name": dest.name, "path": str(dest), "from": archive.name}


def delete_backup(instance: Instance, backup_name: str, version_id: str = ""):
    archive = _safe_child(backups_dir(instance, version_id), backup_name, "备份")
    if not archive.is_file():
        raise SaveError(f"备份不存在: {backup_name}")
    archive.unlink()


def export_save(instance: Instance, name: str, dest: str, version_id: str = "",
                on_progress=None) -> str:
    """把存档导出成任意位置的 zip，便于分享或搬到别的启动器。"""
    src = _safe_child(_game_dir(instance, version_id) / "saves", name)
    if not src.is_dir():
        raise SaveError(f"存档不存在: {name}")
    out = Path(dest)
    if out.is_dir():
        out = out / f"{src.name}.zip"
    if out.suffix.lower() != ".zip":
        out = out.with_suffix(".zip")
    utils.ensure_dir(out.parent)
    files = [p for p in src.rglob("*") if p.is_file()]
    total = len(files) or 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, p in enumerate(files, 1):
            zf.write(p, str(Path(src.name) / p.relative_to(src)))
            if on_progress:
                on_progress(f"导出 {src.name}", i, total)
    return str(out)


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
