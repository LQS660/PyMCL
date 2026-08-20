# -*- coding: utf-8 -*-
"""LiteLoader 安装（1.7.2–1.12.2）。"""
from __future__ import annotations

from .downloader import DownloadManager

BMCL = "https://bmclapi2.bangbang93.com"
OFFICIAL = "http://dl.liteloader.com/versions/versions.json"


def list_versions(dm: DownloadManager) -> dict:
    try:
        data = dm.fetch_json(f"{BMCL}/liteloader/list", timeout=20)
        if isinstance(data, dict) and data.get("versions"):
            return data["versions"]
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    data = dm.fetch_json(OFFICIAL, timeout=20)
    return (data or {}).get("versions") or {}


def install(installer, mc_version: str, force: bool = False) -> str:
    from .installer import InstallError
    mc_version = (mc_version or "").strip()
    versions = list_versions(installer.dm)
    info = versions.get(mc_version)
    if not info:
        raise InstallError(f"LiteLoader 不支持 Minecraft {mc_version}")
    repo = info.get("repo") or info.get("artefacts") or {}
    snap = None
    if isinstance(repo, dict):
        artefacts = repo.get("com.mumfrey:liteloader") or repo
        if isinstance(artefacts, dict):
            snap = artefacts.get("latest") or artefacts.get("snapshot")
            if not snap:
                for key in ("1.12.2-SNAPSHOT", "1.8.9-SNAPSHOT"):
                    if key in artefacts:
                        snap = artefacts[key]
                        break
    ll_ver = ""
    url = ""
    if isinstance(snap, dict):
        ll_ver = snap.get("version") or f"{mc_version}-SNAPSHOT"
        url = snap.get("url") or snap.get("file") or ""
        tweak = snap.get("tweakClass") or "com.mumfrey.liteloader.launch.LiteLoaderTweaker"
    else:
        ll_ver = f"{mc_version}-SNAPSHOT"
        tweak = "com.mumfrey.liteloader.launch.LiteLoaderTweaker"
    if not url:
        url = f"{BMCL}/maven/com/mumfrey/liteloader/{ll_ver}/liteloader-{ll_ver}.jar"

    vid = f"{mc_version}-LiteLoader{mc_version}"
    if installer.instance.has_version(vid) and not force:
        return vid

    installer._note(f"安装原版 {mc_version}（LiteLoader 依赖）")
    installer.install_version(mc_version, force=False)

    dest = installer.instance.libraries_dir() / "com" / "mumfrey" / "liteloader" / ll_ver / f"liteloader-{ll_ver}.jar"
    installer._note(f"下载 LiteLoader {ll_ver}")
    installer.dm.download(url, dest, force=force)
    if not dest.is_file():
        raise InstallError("LiteLoader 下载失败")
    _ensure_launchwrapper(installer)

    profile = {
        "id": vid,
        "inheritsFrom": mc_version,
        "jar": mc_version,
        "type": "release",
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "minecraftArguments": (
            "--username ${auth_player_name} --version ${version_name} "
            "--gameDir ${game_directory} --assetsDir ${assets_root} "
            "--assetIndex ${assets_index_name} --uuid ${auth_uuid} "
            "--accessToken ${auth_access_token} --userType ${user_type} "
            f"--tweakClass {tweak}"
        ),
        "libraries": [
            {"name": f"com.mumfrey:liteloader:{ll_ver}"},
            {"name": "net.minecraft:launchwrapper:1.12"},
        ],
    }
    installer._install_json(vid, profile, force=force)
    return vid


def _ensure_launchwrapper(installer):
    dest = installer.instance.libraries_dir() / "net" / "minecraft" / "launchwrapper" / "1.12" / "launchwrapper-1.12.jar"
    if dest.is_file() and dest.stat().st_size > 1000:
        return
    url = f"{BMCL}/maven/net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar"
    installer._note("下载 launchwrapper 1.12")
    installer.dm.download(url, dest)
