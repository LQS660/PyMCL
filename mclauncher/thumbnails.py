# -*- coding: utf-8 -*-
"""搜索结果的图标/缩略图缓存。

Modrinth / CurseForge 搜索结果的缩略图 URL 会被缓存到本地，
避免每次刷新都重新下载。
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import utils
from .downloader import DownloadManager
from .config import CONFIG

_THUMB_LOCK = threading.Lock()
_CACHE_TTL = 7 * 24 * 3600  # 7 天


def _thumb_dir() -> Path:
    p = CONFIG.cache_dir / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hash_url(url: str) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:24]


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico"):
        return suffix
    return ".png"


def thumb_path(url: str) -> str:
    """返回本地缓存路径（文件可能不存在）。"""
    if not url:
        return ""
    return str(_thumb_dir() / (_hash_url(url) + _ext_from_url(url)))


def ensure_thumb(url: str, dm: DownloadManager | None = None) -> str:
    """确保缩略图已缓存，返回本地路径（失败返回空串）。"""
    if not url:
        return ""
    local = thumb_path(url)
    p = Path(local)
    if p.is_file() and time.time() - p.stat().st_mtime < _CACHE_TTL:
        return local
    if dm is None:
        dm = DownloadManager(threads=2)
    try:
        dm.download(url, local, timeout=20)
        return local
    except Exception:
        return ""


def batch_ensure(urls: list[str], dm: DownloadManager | None = None) -> dict:
    """批量下载缩略图，返回 {url: local_path_or_empty}。"""
    out = {}
    if dm is None:
        dm = DownloadManager(threads=4)
    for u in urls:
        out[u] = ensure_thumb(u, dm)
    return out


def clear_cache():
    p = _thumb_dir()
    if p.is_dir():
        for f in p.iterdir():
            try:
                f.unlink()
            except OSError:
                pass


def cached_size() -> int:
    p = _thumb_dir()
    if not p.is_dir():
        return 0
    return sum(1 for f in p.iterdir() if f.is_file())