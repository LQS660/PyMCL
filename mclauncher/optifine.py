# -*- coding: utf-8 -*-
"""OptiFine 列表与安装。走 BMCLAPI，生成 inheritsFrom 版本。"""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from . import utils
from .downloader import DownloadManager

BMCL = "https://bmclapi2.bangbang93.com"


def list_builds(dm: DownloadManager, mc_version: str) -> list:
    mc_version = (mc_version or "").strip()
    if not mc_version:
        return []
    try:
        data = dm.fetch_json(f"{BMCL}/optifine/{mc_version}", timeout=30)
    except Exception as exc:
        from .installer import InstallError
        raise InstallError(f"无法获取 OptiFine 列表 ({mc_version}): {exc}") from exc
    rows = data if isinstance(data, list) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        typ = row.get("type") or "HD_U"
        patch = row.get("patch") or ""
        filename = row.get("filename") or f"OptiFine_{mc_version}_{typ}_{patch}.jar"
        out.append({
            "mc": row.get("mcversion") or mc_version,
            "type": typ,
            "patch": patch,
            "filename": filename,
            "id": f"{mc_version}-OptiFine_{typ}_{patch}".rstrip("_"),
        })
    return out


def _latest(rows: list) -> dict:
    from .installer import InstallError
    if not rows:
        raise InstallError("该 Minecraft 版本没有 OptiFine")
    return rows[0]


def _extract_launchwrapper(opti_jar: Path, libs_dir: Path) -> str | None:
    """从安装器里抽出 launchwrapper，返回 maven 坐标。"""
    try:
        zf = zipfile.ZipFile(opti_jar)
    except zipfile.BadZipFile as exc:
        from .installer import InstallError
        raise InstallError(f"OptiFine 包损坏: {exc}") from exc
    names = zf.namelist()
    wrapped = [n for n in names if n.lower().endswith(".jar") and "launchwrapper" in n.lower()]
    if not wrapped:
        zf.close()
        return None
    inner = wrapped[0]
    raw = zf.read(inner)
    zf.close()
    base = Path(inner).name
    ver = "2.3"
    for token in base.replace(".jar", "").split("-"):
        if token and token[0].isdigit():
            ver = token
            break
    dest = libs_dir / "net" / "minecraft" / "launchwrapper" / ver / f"launchwrapper-{ver}.jar"
    utils.ensure_dir(dest.parent)
    dest.write_bytes(raw)
    return f"net.minecraft:launchwrapper:{ver}"


def _has_tweaker(opti_jar: Path) -> bool:
    try:
        with zipfile.ZipFile(opti_jar) as zf:
            names = zf.namelist()
        return any("OptiFineTweaker.class" in n or "OptiFineForgeTweaker.class" in n for n in names)
    except zipfile.BadZipFile:
        return False


def _profile(mc_version: str, typ: str, patch: str, wrapper: str | None) -> dict:
    vid = f"{mc_version}-OptiFine_{typ}_{patch}".rstrip("_")
    maven = f"optifine:OptiFine:{mc_version}_{typ}_{patch}".rstrip("_")
    libs = [{"name": maven}]
    if wrapper:
        libs.append({"name": wrapper})
    else:
        libs.append({"name": "net.minecraft:launchwrapper:1.12"})
    profile = {
        "id": vid,
        "inheritsFrom": mc_version,
        "jar": mc_version,
        "type": "release",
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "libraries": libs,
    }
    # 1.13+ 用 arguments；更老用 minecraftArguments，启动器两边都能吃
    from .manifest import mc_version_tuple
    tup = mc_version_tuple(mc_version) or (1, 0)
    if tup >= (1, 13):
        profile["arguments"] = {"game": ["--tweakClass", "optifine.OptiFineTweaker"]}
    else:
        profile["minecraftArguments"] = (
            "--username ${auth_player_name} --version ${version_name} "
            "--gameDir ${game_directory} --assetsDir ${assets_root} "
            "--assetIndex ${assets_index_name} --uuid ${auth_uuid} "
            "--accessToken ${auth_access_token} --userType ${user_type} "
            "--tweakClass optifine.OptiFineTweaker"
        )
    return profile


def _java_exe() -> str | None:
    from . import java as java_mod
    for j in java_mod.list_installed_javas() + java_mod.find_system_javas():
        exe = j.get("exe")
        if exe and Path(exe).is_file():
            return str(exe)
    return None


def _run_patcher(installer, opti_jar: Path, mc_version: str, vid: str) -> bool:
    """1.21+ 安装器往往没有 Tweaker，改走 optifine.Patcher 生成客户端 jar。"""
    vanilla = installer.instance.versions_dir() / mc_version / f"{mc_version}.jar"
    if not vanilla.is_file():
        return False
    java_exe = _java_exe()
    if not java_exe:
        installer._note("没有可用 Java，跳过 OptiFine Patcher")
        return False
    vdir = installer.instance.versions_dir() / vid
    utils.ensure_dir(vdir)
    dest = vdir / f"{vid}.jar"
    installer._note("运行 OptiFine Patcher")
    try:
        proc = subprocess.run(
            [java_exe, "-cp", str(opti_jar), "optifine.Patcher",
             str(vanilla), str(dest), str(opti_jar)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        installer._note(f"Patcher 失败: {exc}")
        return False
    if dest.is_file() and dest.stat().st_size > 1024:
        return True
    tail = ((proc.stderr or "") + (proc.stdout or ""))[-240:]
    installer._note(f"Patcher 未生成客户端 jar {tail}")
    return False


def install_as_mod(installer, mc_version: str, dest_dir, typ: str = "", patch: str = "") -> str:
    """把 OptiFine jar 放进 mods，供 Forge 版本加载。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dm = installer.dm
    rows = list_builds(dm, mc_version)
    if typ or patch:
        chosen = next(
            (r for r in rows if (not typ or r["type"] == typ) and (not patch or r["patch"] == patch)),
            None,
        ) or _latest(rows)
    else:
        chosen = _latest(rows)
    typ, patch = chosen["type"], chosen["patch"]
    url = f"{BMCL}/optifine/{mc_version}/{typ}/{patch}"
    dest = dest_dir / chosen["filename"]
    installer._note(f"下载 OptiFine {typ}_{patch} 到 mods")
    dm.download(url, dest, force=False)
    if not dest.is_file() or dest.stat().st_size < 1024:
        from .installer import InstallError
        raise InstallError("OptiFine 下载失败或文件过小")
    return dest.name


def install(installer, mc_version: str, typ: str = "", patch: str = "",
            force: bool = False) -> str:
    from .installer import InstallError
    dm = installer.dm
    mc_version = (mc_version or "").strip()
    rows = list_builds(dm, mc_version)
    if typ or patch:
        chosen = next(
            (r for r in rows if (not typ or r["type"] == typ) and (not patch or r["patch"] == patch)),
            None,
        )
        if not chosen:
            chosen = _latest(rows)
            installer._note(f"未精确匹配 OptiFine {typ} {patch}，改用 {chosen['type']} {chosen['patch']}")
    else:
        chosen = _latest(rows)
    typ, patch = chosen["type"], chosen["patch"]
    vid = chosen["id"]
    if installer.instance.has_version(vid) and not force:
        installer._note(f"已安装 {vid}")
        return vid

    installer._note(f"安装原版 {mc_version}（OptiFine 依赖）")
    installer.install_version(mc_version, force=False)

    url = f"{BMCL}/optifine/{mc_version}/{typ}/{patch}"
    libs = installer.instance.libraries_dir()
    artifact = f"{mc_version}_{typ}_{patch}".rstrip("_")
    dest = libs / "optifine" / "OptiFine" / artifact / f"OptiFine-{artifact}.jar"
    installer._note(f"下载 OptiFine {typ}_{patch}")
    dm.download(url, dest, force=force)
    if not dest.is_file() or dest.stat().st_size < 1024:
        raise InstallError("OptiFine 下载失败或文件过小")
    if not _has_tweaker(dest):
        patched = _run_patcher(installer, dest, mc_version, vid)
        if patched:
            profile = {
                "id": vid,
                "inheritsFrom": mc_version,
                "jar": vid,
                "type": "release",
            }
            installer._note(f"写入 Patcher 版本 {vid}")
            installer._install_json(vid, profile, force=force)
            return vid
        installer._note("未找到 OptiFineTweaker，仍按 Tweaker 结构写入版本")

    wrapper = _extract_launchwrapper(dest, libs)
    profile = _profile(mc_version, typ, patch, wrapper)
    installer._note(f"写入版本 {profile['id']}")
    installer._install_json(profile["id"], profile, force=force)
    return profile["id"]
