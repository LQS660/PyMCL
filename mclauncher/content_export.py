# -*- coding: utf-8 -*-
"""把已安装的模组 / 光影 / 资源包 / 数据包 / 世界导出到本地。

默认落在启动器根目录的 exports/ 下，用户选过别的位置就记住，
下次的文件夹选择框从那儿开。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import utils
from .config import CONFIG

# 内容种类 -> 游戏目录下的子目录
CONTENT_DIRS = {
    "mod": "mods",
    "shader": "shaderpacks",
    "resourcepack": "resourcepacks",
    "datapack": "datapacks",
    "world": "saves",
}
# 世界是目录，导出时打成 zip；其余都是单个文件，直接复制
ARCHIVED_KINDS = ("world",)


class ExportError(Exception):
    pass


# 没选过位置时导出落在哪：启动器根目录下的这一层
EXPORT_DIR_NAME = "exports"


def default_export_dir() -> Path:
    """导出位置：记过的那个，没有就是启动器根目录下的 exports/。

    以前的兜底是桌面。导出的模组 / 光影 / 存档多半是要再拖回启动器里的，
    落在桌面上等于每导一次就往桌面扔一个文件，还得自己收拾。

    目录当场建出来：返回一个不存在的路径，文件选择框会退回上一次的位置，
    「默认就在启动器里」这句话在界面上就兑现不了。
    """
    saved = str(CONFIG.get("export_dir") or "").strip()
    if saved:
        p = Path(saved)
        if p.is_dir():
            return p
    fallback = utils.ROOT / EXPORT_DIR_NAME
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 启动器装在只读位置（绿色版放在 U 盘 / Program Files）：退回桌面，
        # 总比把导出这件事整个卡死强
        from .shortcut import desktop_dir
        return desktop_dir()
    return fallback


def remember_export_dir(path) -> str:
    p = Path(path)
    if not p.is_dir():
        return str(default_export_dir())
    CONFIG.set("export_dir", str(p))
    CONFIG.save()
    return str(p)


def content_dir(instance, kind: str, version: str = "") -> Path:
    """这一类内容此刻的真实目录。开了隔离的版本用它自己那一份。"""
    sub = CONTENT_DIRS.get(kind)
    if not sub:
        raise ExportError(f"不支持导出的类型: {kind!r}")
    if version:
        from . import version_settings as vs
        return vs.game_dir(instance, version) / sub
    return Path(instance.path) / sub


def source_path(instance, kind: str, name: str, version: str = "") -> Path:
    folder = content_dir(instance, kind, version).resolve()
    target = (folder / name).resolve()
    # 防路径穿越：只允许导出这一层里的东西
    if target.parent != folder:
        raise ExportError(f"非法的文件名: {name!r}")
    if not target.exists():
        raise ExportError(f"文件不存在: {name}")
    return target


# 禁用的模组是 foo.jar.disabled，改名时这两截要一起留在后面
_DOUBLE_SUFFIXES = (".jar.disabled", ".zip.disabled", ".tar.gz")


def _split_name(filename: str) -> tuple[str, str]:
    low = filename.lower()
    for suffix in _DOUBLE_SUFFIXES:
        if low.endswith(suffix):
            return filename[: -len(suffix)], filename[-len(suffix):]
    p = Path(filename)
    return p.stem, p.suffix


def _free_path(folder: Path, filename: str) -> Path:
    """同名文件不覆盖，改成 `foo (2).jar`。"""
    dest = folder / filename
    if not dest.exists():
        return dest
    stem, suffix = _split_name(filename)
    n = 2
    while True:
        candidate = folder / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def export_one(instance, kind: str, name: str, dest_dir="", version: str = "") -> str:
    """导出一个，返回落地的完整路径。"""
    src = source_path(instance, kind, name, version)
    folder = Path(dest_dir) if dest_dir else default_export_dir()
    utils.ensure_dir(folder)
    if kind in ARCHIVED_KINDS or src.is_dir():
        from .saves import export_save
        if kind == "world":
            return export_save(instance, name, str(folder), version)
        dest = _free_path(folder, f"{src.name}.zip")
        base = dest.with_suffix("")
        return shutil.make_archive(str(base), "zip", root_dir=str(src))
    dest = _free_path(folder, src.name)
    shutil.copy2(src, dest)
    return str(dest)


def export_many(instance, kind: str, names, dest_dir="", version: str = "") -> dict:
    """批量导出。单个失败不打断其余，失败的连原因一起带回去。"""
    folder = Path(dest_dir) if dest_dir else default_export_dir()
    utils.ensure_dir(folder)
    done, failed = [], []
    for name in names or []:
        try:
            done.append(export_one(instance, kind, name, str(folder), version))
        except Exception as exc:  # noqa: BLE001
            failed.append({"name": str(name), "error": str(exc)})
    return {"dir": str(folder), "exported": done, "failed": failed}
