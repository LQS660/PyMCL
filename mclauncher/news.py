# -*- coding: utf-8 -*-
"""启动页新闻：Mojang launchercontent，失败走缓存。"""
from __future__ import annotations

from . import utils
from .downloader import DownloadManager

URLS = [
    "https://launchercontent.mojang.com/v2/javaPatchNotes.json",
    "https://launchercontent.mojang.com/javaPatchNotes.json",
]
CACHE = utils.ROOT / "cache" / "news.json"


def _rows_from(payload) -> list:
    entries = []
    if isinstance(payload, dict):
        entries = payload.get("entries") or payload.get("patchNotes") or []
    elif isinstance(payload, list):
        entries = payload
    rows = []
    for item in entries[:12]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("version") or item.get("id") or ""
        body = item.get("shortText") or item.get("body") or item.get("subtitle") or ""
        if isinstance(body, str) and len(body) > 160:
            body = body[:160] + "…"
        image = ""
        img = item.get("image") or item.get("cardBackground") or {}
        if isinstance(img, dict):
            image = img.get("url") or ""
        elif isinstance(img, str):
            image = img
        rows.append({
            "title": str(title),
            "body": str(body).strip(),
            "version": str(item.get("version") or item.get("id") or ""),
            "image": image,
            "date": str(item.get("date") or item.get("updated_at") or "")[:10],
        })
    return rows


def load_cached() -> list:
    data = utils.read_json(CACHE, None)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return _rows_from(data)
    return []


def fetch(dm: DownloadManager | None = None) -> list:
    dm = dm or DownloadManager(threads=2)
    last = None
    for url in URLS:
        try:
            payload = dm.fetch_json(url, timeout=15)
            rows = _rows_from(payload)
            if rows:
                utils.write_json(CACHE, rows)
                return rows
        except Exception as exc:
            last = exc
    cached = load_cached()
    if cached:
        return cached
    if last:
        raise last
    return []
