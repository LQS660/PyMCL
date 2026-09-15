# -*- coding: utf-8 -*-
"""认一认用户拖进来的是什么东西。

主窗口的拖放以前只有一条路：一律当整合包，认不出来就弹一句「这不是整合包」。
于是拖个 mp4 进来得到的是一句莫名其妙的拒绝——而动态壁纸这个功能明明就在
设置页里躺着。

判定尽量看内容、不看后缀：改过名的 .mrpack、CurseForge 导出的 zip、只是换了
扩展名的资源包都认得出来。一个文件同时像两样东西时（64x64 的 PNG 既可能是
皮肤也可能是壁纸），两种都列出来交给用户挑——猜错比多问一句烦人得多。

这里只做判定，不碰界面也不落盘；怎么分派见 app/pages/file_drop.py。
"""
from __future__ import annotations

import os
import struct
import zipfile
from pathlib import Path

from .background import IMAGE_SUFFIXES, VIDEO_SUFFIXES

MODPACK = "modpack"
MOD = "mod"
RESOURCEPACK = "resourcepack"
SHADERPACK = "shaderpack"
DATAPACK = "datapack"
WORLD = "world"
SKIN = "skin"
WALLPAPER = "wallpaper"

# 拿不准时给用户看的选项顺序，也是「全都不像」时的兜底菜单
ALL_KINDS = (MODPACK, MOD, RESOURCEPACK, SHADERPACK, DATAPACK, WORLD, SKIN, WALLPAPER)

KIND_LABELS = {
    MODPACK: "整合包",
    MOD: "模组",
    RESOURCEPACK: "资源包",
    SHADERPACK: "光影包",
    DATAPACK: "数据包",
    WORLD: "存档",
    SKIN: "离线皮肤",
    WALLPAPER: "启动器壁纸",
}
# 选项旁边那句「选了会发生什么」
KIND_ACTIONS = {
    MODPACK: "装成一个新版本",
    MOD: "装进当前版本的 mods",
    RESOURCEPACK: "装进 resourcepacks",
    SHADERPACK: "装进 shaderpacks",
    DATAPACK: "装进 datapacks",
    WORLD: "装进存档列表",
    SKIN: "设为离线账号的皮肤",
    WALLPAPER: "设为启动器背景",
}
# 皮肤贴图只有这两种尺寸，跟 mclauncher/skin.py 的 VALID_SIZES 同一套
SKIN_SIZES = {(64, 64), (64, 32)}
# 目录当包看时只扫这么深、这么多条：拖进来的可能是一整个 .minecraft
_SCAN_DEPTH = 3
_SCAN_LIMIT = 4000


def identify(path) -> dict:
    """认一下这是什么。

    返回 {path, name, kinds, sure, detail}：kinds 是候选类型（最像的在前），
    sure=True 表示可以直接照办，否则要问一句。
    """
    p = Path(str(path))
    out = {"path": str(p), "name": p.name or str(p), "kinds": [], "sure": False,
           "detail": ""}
    if not p.exists():
        out["detail"] = "这个路径不存在"
        return out
    suffix = p.suffix.lower()

    if suffix in VIDEO_SUFFIXES:
        return {**out, "kinds": [WALLPAPER], "sure": True, "detail": "视频 · 可以当动态壁纸"}
    if suffix in IMAGE_SUFFIXES:
        size = _png_size(p) if suffix == ".png" else None
        if size in SKIN_SIZES:
            # 皮肤贴图也是一张能当壁纸的 PNG，光看文件分不出来
            return {**out, "kinds": [SKIN, WALLPAPER],
                    "detail": f"{size[0]}x{size[1]} 的 PNG，尺寸正好是皮肤贴图"}
        return {**out, "kinds": [WALLPAPER], "sure": True, "detail": "图片"}

    # jar 先判：它也是个 zip，交给整合包那套探针只是白读一遍
    if suffix == ".jar":
        return {**out, **_identify_jar(p)}

    pack = _probe_modpack(p)
    if pack:
        mc = pack.get("mc_version") or "未知版本"
        return {**out, "kinds": [MODPACK], "sure": True,
                "detail": f"{pack.get('format') or '整合包'} · Minecraft {mc}"}

    names = _entry_names(p)
    if names is None:
        return {**out, "detail": "打不开，也认不出是什么"}
    return {**out, **_identify_archive(names)}


# ---------------------------------------------------------------- 各类判定
def _identify_jar(path: Path) -> dict:
    names = _entry_names(path) or []
    flat = set(names)
    if "install_profile.json" in flat:
        # Forge / NeoForge 的安装器：装加载器要走「游戏」页，丢进 mods 只会启动失败
        return {"kinds": [], "detail": "这是加载器安装器，不是模组；装加载器请到「游戏」页"}
    marks = ("fabric.mod.json", "quilt.mod.json", "meta-inf/mods.toml",
             "meta-inf/neoforge.mods.toml", "mcmod.info")
    if any(m in flat for m in marks):
        return {"kinds": [MOD], "sure": True, "detail": "Minecraft 模组"}
    return {"kinds": [MOD], "detail": "jar 包，但里面没有模组描述文件"}


def _identify_archive(names: list[str]) -> dict:
    """压缩包 / 目录：按里面有什么认。"""
    if _has_entry(names, "level.dat"):
        return {"kinds": [WORLD], "sure": True, "detail": "带 level.dat，是一个存档"}
    if _has_dir(names, "shaders"):
        return {"kinds": [SHADERPACK], "sure": True, "detail": "带 shaders 目录"}
    if _has_entry(names, "pack.mcmeta"):
        assets, data = _has_dir(names, "assets"), _has_dir(names, "data")
        if assets and not data:
            return {"kinds": [RESOURCEPACK], "sure": True, "detail": "带 pack.mcmeta 与 assets"}
        if data and not assets:
            return {"kinds": [DATAPACK], "sure": True, "detail": "带 pack.mcmeta 与 data"}
        return {"kinds": [RESOURCEPACK, DATAPACK],
                "detail": "有 pack.mcmeta，但资源包和数据包的目录都在"}
    return {"kinds": [], "detail": "压缩包里没有认得出来的标志文件"}


# ---------------------------------------------------------------- 读取工具
def _png_size(path: Path) -> tuple[int, int] | None:
    """只读 PNG 头拿宽高。不是 PNG、读不动都返回 None。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def _probe_modpack(path: Path):
    """整合包判定复用拖放那一套（索引文件 / .minecraft 目录，只读不解压）。"""
    from .pages.modpack_drop import probe
    return probe(path)


def _entry_names(path: Path) -> list[str] | None:
    """包里（或目录里）的相对路径，统一成小写正斜杠。读不了返回 None。"""
    if path.is_dir():
        return _walk_names(path)
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.namelist()[:_SCAN_LIMIT]
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return None
    return [n.replace("\\", "/").lower() for n in raw]


def _walk_names(root: Path) -> list[str]:
    out: list[str] = []
    for base, dirs, files in os.walk(root):
        rel = Path(base).relative_to(root)
        depth = 0 if str(rel) == "." else len(rel.parts)
        if depth >= _SCAN_DEPTH:
            dirs[:] = []          # 再深就不看了，标志文件都在前两层
        prefix = "" if depth == 0 else str(rel).replace("\\", "/").lower() + "/"
        for name in list(dirs) + files:
            out.append(prefix + name.lower())
            if len(out) >= _SCAN_LIMIT:
                return out
    return out


def _has_entry(names, target: str) -> bool:
    """根目录、或恰好裹了一层目录的位置上有这个文件。

    只认前两层：资源包里 assets/minecraft/… 底下也可能躺着同名文件，
    按「任意深度」判会把一堆包认错。
    """
    return any(n.split("/")[-1] == target and n.count("/") <= 1 for n in names)


def _has_dir(names, target: str) -> bool:
    return any(target in n.split("/")[:2] for n in names)
