# -*- coding: utf-8 -*-
"""列出某 MC 版本可用的加载器构建号，供安装向导选择。"""
from __future__ import annotations

from .downloader import DownloadManager
from .installer import (
    BMCLAPI, FABRIC_META, FORGE_MAVEN, NEOFORGE_MAVEN, QUILT_META,
    Installer, bmcl_forge_artifacts, forge_sort_key, parse_maven_versions,
)

NEOFORGE_MC_MAP = {
    "1.20.1": "47.1", "1.20.2": "20.2", "1.20.3": "20.3", "1.20.4": "20.4",
    "1.20.5": "20.5", "1.20.6": "20.6", "1.21": "21.0", "1.21.1": "21.1",
}


def list_loader_versions(dm: DownloadManager | None, mc_version: str, loader: str) -> list[dict]:
    dm = dm or DownloadManager(threads=2)
    mc = (mc_version or "").strip()
    kind = (loader or "").strip().lower()
    if not mc or kind in ("", "无", "none"):
        return []
    if kind == "fabric":
        return _fabric(dm, mc)
    if kind == "quilt":
        return _quilt(dm, mc)
    if kind == "forge":
        return _forge(dm, mc)
    if kind == "neoforge":
        return _neoforge(dm, mc)
    if kind == "optifine":
        from . import optifine as optifine_mod
        rows = optifine_mod.list_builds(dm, mc)
        return [{
            "id": f"{r['type']}_{r['patch']}".rstrip("_"),
            "label": f"{r['type']} {r['patch']}".strip(),
            "type": r.get("type") or "",
            "patch": r.get("patch") or "",
            "stable": True,
        } for r in rows]
    if kind == "liteloader":
        from . import liteloader as ll
        vers = ll.list_versions(dm) or {}
        if mc in vers:
            return [{"id": mc, "label": mc, "stable": True}]
        return []
    return []


def _fabric(dm, mc):
    data = dm.fetch_json(f"{FABRIC_META}/versions/loader/{mc}", timeout=30)
    rows = []
    for d in data or []:
        ver = ((d or {}).get("loader") or {}).get("version")
        if not ver:
            continue
        rows.append({
            "id": ver,
            "label": ver,
            "stable": bool((d.get("loader") or {}).get("stable")),
        })
    return rows


def _quilt(dm, mc):
    data = dm.fetch_json(f"{QUILT_META}/versions/loader/{mc}", timeout=30)
    rows = []
    for d in data or []:
        ver = ((d or {}).get("loader") or {}).get("version")
        if not ver:
            continue
        rows.append({"id": ver, "label": ver, "stable": True})
    return rows


def _forge(dm, mc):
    found = []
    try:
        data = dm.fetch_json(f"{BMCLAPI}/forge/minecraft/{mc}", timeout=30)
        found = bmcl_forge_artifacts(data, mc)
    except Exception:
        found = []
    if not found:
        for url, expand in (
            (f"{BMCLAPI}/maven/net/minecraftforge/forge/maven-metadata.xml", True),
            (f"{FORGE_MAVEN}/maven-metadata.xml", False),
        ):
            try:
                xml = dm.fetch_text(url, timeout=40, expand=expand)
            except Exception:
                continue
            vers = parse_maven_versions(xml)
            found = [v for v in vers if v == mc or v.startswith(mc + "-")]
            if found:
                break
    found.sort(key=lambda v: forge_sort_key(v, mc), reverse=True)
    return [{"id": v, "label": v, "stable": "-pre" not in v.lower()} for v in found]


def neoforge_prefix(mc_version: str) -> str:
    """该 MC 版本对应的 NeoForge 版本号前缀，取不到返回空串。

    与 `Installer.install_neoforge` 同一套规则：先查 NEOFORGE_MC_MAP，
    表里没有再按「1.21.4 → 21.4」推导（NeoForge 从 1.20.2 起改用这套号）。
    """
    mc = (mc_version or "").strip()
    if not mc:
        return ""
    mapped = NEOFORGE_MC_MAP.get(mc)
    if mapped:
        return str(mapped)
    if Installer._mc_tuple(mc) >= (1, 20, 2):
        return ".".join(mc.split(".")[1:])
    return ""


def filter_neoforge_versions(versions, mc_version: str) -> list[str]:
    """从 maven 全量版本里挑出属于该 MC 版本的构建，挑不出就返回空。

    以前只认 NEOFORGE_MC_MAP（写死到 1.21.1），更新的 MC 会让 prefix=None
    从而**完全不过滤**，把所有 MC 版本的 NeoForge 构建都列进下拉框，
    用户随手选一条就是版本错配。宁可只留「最新」交给安装器自己解析。
    """
    vers = [str(v).strip() for v in (versions or []) if str(v).strip()]
    mc = (mc_version or "").strip()
    if not mc or not vers:
        return []
    prefix = neoforge_prefix(mc)
    picked = [v for v in vers if prefix and v.startswith(prefix + ".")]
    if not picked:
        # 1.20.1 之前的旧号段是 `<mc>-<build>`
        picked = [v for v in vers if v.startswith(mc + "-")]
    return list(reversed(picked[-80:]))


def _neoforge(dm, mc):
    try:
        xml = dm.fetch_text(f"{NEOFORGE_MAVEN}/maven-metadata.xml", timeout=30, expand=False)
        vers = parse_maven_versions(xml)
    except Exception:
        vers = []
    return [
        {"id": v, "label": v, "stable": "beta" not in v.lower()}
        for v in filter_neoforge_versions(vers, mc)
    ]
