# -*- coding: utf-8 -*-
"""CurseForge 世界下载，安装到 saves/。"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from . import mods as mods_mod
from . import utils
from .catalog_files import CF_CLASS_WORLD, search_projects
from .downloader import DownloadManager
from .instances import Instance


class WorldError(Exception):
    pass


def search_worlds(dm: DownloadManager | None, query: str, extra: dict | None = None) -> list[dict]:
    extra = dict(extra or {})
    extra["kind"] = "world"
    return search_projects(dm, "world", query, extra.get("source") or "CurseForge", extra)


def install_world(dm: DownloadManager, extra: dict, instance: Instance, on_progress=None) -> dict:
    inst = instance
    inst.ensure_standard_dirs()
    dest_root = inst.path / "saves"
    dest_root.mkdir(parents=True, exist_ok=True)
    extra = dict(extra or {})
    path = extra.get("path")
    if path and Path(path).is_file():
        return _extract_world(Path(path), dest_root)
    url = extra.get("url")
    if url and str(url).startswith("http"):
        tmp = Path(utils.ROOT) / "cache" / (str(url).split("/")[-1].split("?")[0] or "world.zip")
        if on_progress:
            on_progress("下载世界", 0, 1)
        dm.download(str(url), tmp, timeout=900)
        return _extract_world(tmp, dest_root)
    addon_id = extra.get("id")
    if not addon_id:
        raise WorldError("缺少 CurseForge 世界项目 id")
    file_id = extra.get("file_id") or extra.get("version_id")
    if file_id:
        files = mods_mod.cf_files(dm, addon_id, page_size=50)
        chosen = next((f for f in files if str(f.get("id")) == str(file_id)), None)
        if not chosen:
            raise WorldError("找不到指定世界文件")
    else:
        gv = extra.get("game_version") or extra.get("mc_version")
        files = mods_mod.cf_files(dm, addon_id, game_version=gv or None, page_size=50)
        if not files:
            raise WorldError("该世界没有可下载文件")
        chosen = files[0]
    filename = chosen.get("fileName") or f"world-{addon_id}.zip"
    tmp = Path(utils.ROOT) / "cache" / filename
    urls = []
    if chosen.get("downloadUrl"):
        urls.append(chosen["downloadUrl"])
    urls.extend(mods_mod.cf_mod_download_urls(addon_id, chosen.get("id"), filename))
    last = None
    for u in urls:
        try:
            if on_progress:
                on_progress(f"下载世界 {filename}", 0, 1)
            dm.download(u, tmp, timeout=900)
            last = None
            break
        except Exception as e:
            last = e
    if last:
        raise WorldError(f"下载世界失败: {last}")
    return _extract_world(tmp, dest_root)


def _extract_world(archive: Path, dest_root: Path) -> dict:
    if archive.suffix.lower() not in (".zip",):
        dest = dest_root / archive.stem
        utils.ensure_dir(dest)
        shutil.copy2(archive, dest / archive.name)
        return {"files": [archive.stem], "source": "file"}
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise WorldError(f"世界压缩包损坏: {exc}") from exc
    names = [n.replace("\\", "/") for n in zf.namelist() if n and not n.endswith("/")]
    if not names:
        zf.close()
        raise WorldError("空的世界压缩包")
    top = set()
    for n in names:
        top.add(n.split("/")[0])
    zf.extractall(dest_root)
    zf.close()
    return {"files": sorted(top), "source": "zip"}
