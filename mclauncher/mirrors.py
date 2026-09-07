# -*- coding: utf-8 -*-
"""下载镜像：GitHub 前缀 + 转交给 source 策略。"""

GITHUB_PROXY_PREFIXES = (
    "https://gitproxy.mrhjx.cn/",
    "https://ghproxy.vip/",
    "https://gh-proxy.com/",
    "https://v6.gh-proxy.org/",
    "https://cdn.gh-proxy.com/",
)


def _prefixes():
    try:
        from .config import CONFIG
        extra = CONFIG.get("github_proxy_prefixes") or []
        if extra:
            return tuple(extra)
    except Exception:
        pass
    return GITHUB_PROXY_PREFIXES


def github_candidates(url: str) -> list[str]:
    out, seen = [], set()
    for prefix in _prefixes():
        u = prefix + url
        if u not in seen:
            seen.add(u)
            out.append(u)
    if url not in seen:
        out.append(url)
    return out


def expand_download_urls(url):
    from . import source
    return source.expand_download_urls(url)
