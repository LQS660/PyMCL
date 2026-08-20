# -*- coding: utf-8 -*-
"""清理未引用 libraries / 损坏 .part / 过期 cache。"""
from __future__ import annotations

from pathlib import Path

from . import utils
from .config import CONFIG
from .instances import Instance, list_instances
from .manifest import resolve_inherits


def _lib_paths(instance: Instance) -> set:
    used = set()
    libs = instance.libraries_dir()

    def load_parent(pid):
        return instance.version_json(pid)

    for vid in instance.installed_ids():
        vjson = instance.version_json(vid) or {}
        try:
            resolved = resolve_inherits(vjson, load_parent)
        except Exception:
            resolved = vjson
        for lib in resolved.get("libraries") or []:
            downloads = lib.get("downloads") or {}
            artifact = downloads.get("artifact") or {}
            path = artifact.get("path")
            if not path and lib.get("name") and not lib.get("natives"):
                path = utils.maven_artifact_path(lib["name"])
            if path:
                used.add(str((libs / path).resolve()).lower())
            for clf in (downloads.get("classifiers") or {}).values():
                if isinstance(clf, dict) and clf.get("path"):
                    used.add(str((libs / clf["path"]).resolve()).lower())
    return used


def preview() -> dict:
    lib_files = []
    parts = []
    cache_files = []
    used = set()
    seen_libs = set()
    for name in list_instances():
        inst = Instance(name)
        used |= _lib_paths(inst)
        libs = inst.libraries_dir()
        if str(libs) in seen_libs:
            continue
        seen_libs.add(str(libs))
        if libs.is_dir():
            for p in libs.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() == ".part":
                    parts.append(p)
                    continue
                if str(p.resolve()).lower() not in used:
                    lib_files.append(p)
    cache = CONFIG.cache_dir
    if cache.is_dir():
        for p in cache.rglob("*.part"):
            parts.append(p)
        for p in cache.glob("PyMCL-*.bin"):
            cache_files.append(p)
    def _stat(paths):
        total = 0
        rows = []
        for p in paths:
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            total += sz
            rows.append({"path": str(p), "bytes": sz})
        return rows, total
    unused, unused_bytes = _stat(lib_files)
    part_rows, part_bytes = _stat(parts)
    cache_rows, cache_bytes = _stat(cache_files)
    return {
        "unused_libraries": unused,
        "parts": part_rows,
        "cache": cache_rows,
        "bytes": unused_bytes + part_bytes + cache_bytes,
        "count": len(unused) + len(part_rows) + len(cache_rows),
    }


def apply(kinds=None) -> dict:
    kinds = set(kinds or ("parts", "cache", "unused_libraries"))
    info = preview()
    removed = 0
    bytes_ = 0
    mapping = {
        "unused_libraries": info["unused_libraries"],
        "parts": info["parts"],
        "cache": info["cache"],
    }
    for kind in kinds:
        for row in mapping.get(kind) or []:
            p = Path(row["path"])
            try:
                sz = p.stat().st_size
                p.unlink()
                removed += 1
                bytes_ += sz
            except OSError:
                pass
    return {"removed": removed, "bytes": bytes_}
