# -*- coding: utf-8 -*-
"""已装模组更新：按 sha1 查 Modrinth，比出版本。"""
from __future__ import annotations

from pathlib import Path

from . import utils
from .ai.conflict import inspect_jar
from .downloader import DownloadManager
from .instances import Instance
from .mods import list_instance_mod_entries

API = "https://api.modrinth.com/v2"


def _game_mods(instance: Instance, mods_path: Path | None = None) -> Path:
    return Path(mods_path) if mods_path else instance.path / "mods"


def check_updates(instance: Instance, dm: DownloadManager | None = None,
                  mods_path: Path | None = None, mc_version: str = "",
                  loader: str = "") -> list:
    dm = dm or DownloadManager(threads=4)
    rows = []
    folder = _game_mods(instance, mods_path)
    if not folder.is_dir():
        return rows
    for entry in list_instance_mod_entries(instance) if mods_path is None else _entries(folder):
        path = folder / entry["filename"]
        if not path.is_file() or not entry.get("enabled"):
            continue
        digest = utils.sha1_file(path)
        try:
            current = dm.fetch_json(f"{API}/version_file/{digest}", timeout=12)
        except Exception:
            continue
        if not isinstance(current, dict):
            continue
        project = current.get("project_id")
        cur_ver = current.get("version_number") or current.get("name") or ""
        if not project:
            continue
        params = ""
        q = []
        if mc_version:
            q.append(f"game_versions=[\"{mc_version}\"]")
        if loader:
            q.append(f"loaders=[\"{loader}\"]")
        if q:
            params = "?" + "&".join(q)
        try:
            versions = dm.fetch_json(f"{API}/project/{project}/version{params}", timeout=12)
        except Exception:
            continue
        if not isinstance(versions, list) or not versions:
            continue
        latest = versions[0]
        latest_ver = latest.get("version_number") or latest.get("name") or ""
        if latest.get("id") == current.get("id"):
            continue
        primary = None
        for f in latest.get("files") or []:
            if f.get("primary") or not primary:
                primary = f
        info = inspect_jar(path)
        rows.append({
            "filename": path.name,
            "name": info.get("name") or path.stem,
            "current": cur_ver,
            "latest": latest_ver,
            "project": project,
            "url": (primary or {}).get("url") or "",
            "sha1": ((primary or {}).get("hashes") or {}).get("sha1") or "",
            "size": (primary or {}).get("size") or 0,
            "filename_new": (primary or {}).get("filename") or "",
        })
    return rows


def _entries(folder: Path) -> list:
    rows = []
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        low = p.name.lower()
        if low.endswith(".jar"):
            rows.append({"filename": p.name, "enabled": True})
        elif low.endswith(".jar.disabled"):
            rows.append({"filename": p.name, "enabled": False})
    return rows


def apply_update(instance: Instance, row: dict, dm: DownloadManager | None = None,
                 mods_path: Path | None = None) -> str:
    dm = dm or DownloadManager(threads=2)
    folder = _game_mods(instance, mods_path)
    url = row.get("url")
    if not url:
        raise RuntimeError("没有可下载的更新地址")
    new_name = row.get("filename_new") or row.get("filename")
    dest = folder / new_name
    dm.download(url, dest, sha1=row.get("sha1") or None, size=row.get("size") or None)
    old = folder / row["filename"]
    if old.resolve() != dest.resolve() and old.is_file():
        old.unlink()
    return dest.name
