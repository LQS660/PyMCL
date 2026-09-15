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
# 下载失败的 url 冷却多久不再试。失败不落盘，以前每次重建列表都重新排队，
# 每条 20s 超时、线程池只有 4 条：crafatar / mc-heads 不通时账号页一刷就把
# 池子塞满，目录页的图标排在后面等。冷却期内直接当没有图，走字母底色。
_FAIL_TTL = 10 * 60
_FAIL_CAP = 512
_recent_failures: dict[str, float] = {}


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


def recently_failed(url: str) -> bool:
    """这个 url 刚下过没下成、还在冷却期，别再排队。"""
    if not url:
        return False
    with _THUMB_LOCK:
        stamp = _recent_failures.get(url)
        if stamp is None:
            return False
        if time.time() - stamp >= _FAIL_TTL:
            _recent_failures.pop(url, None)
            return False
        return True


def _note_failure(url: str) -> None:
    with _THUMB_LOCK:
        _recent_failures.pop(url, None)
        if len(_recent_failures) >= _FAIL_CAP:
            # 只留最近的一半，别让一个长会话把这张表攒成漏；先裁再记，这一条一定留下
            keep = sorted(_recent_failures.items(), key=lambda kv: kv[1])[-(_FAIL_CAP // 2):]
            _recent_failures.clear()
            _recent_failures.update(keep)
        _recent_failures[url] = time.time()


def _forget_failure(url: str) -> None:
    with _THUMB_LOCK:
        _recent_failures.pop(url, None)


def ensure_thumb(url: str, dm: DownloadManager | None = None) -> str:
    """确保缩略图已缓存，返回本地路径（失败返回空串）。

    失败会记进冷却表：`_FAIL_TTL` 内再问同一个 url 直接回空串，不碰网络。
    """
    if not url:
        return ""
    local = thumb_path(url)
    p = Path(local)
    if p.is_file() and time.time() - p.stat().st_mtime < _CACHE_TTL:
        return local
    if recently_failed(url):
        return ""
    if dm is None:
        dm = DownloadManager(threads=2)
    try:
        dm.download(url, local, timeout=20)
    except Exception:
        _note_failure(url)
        return ""
    _forget_failure(url)
    return local


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