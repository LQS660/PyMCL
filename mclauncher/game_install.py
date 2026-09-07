# -*- coding: utf-8 -*-
"""原版 + 加载器组合安装（Forge+OptiFine / LiteLoader）。"""
from __future__ import annotations

from .installer import InstallError, Installer


def parse_optifine_token(raw: str) -> tuple[str, str]:
    s = (raw or "").strip().replace("-", "_")
    if not s:
        return "", ""
    parts = [p for p in s.replace(" ", "_").split("_") if p]
    if len(parts) >= 2:
        return parts[0], "_".join(parts[1:])
    return s, ""


def install_game(installer: Installer, version: str, loader: str = "无",
                 loader_version: str = "", extra: dict | None = None) -> str:
    extra = dict(extra or {})
    installer.skip_assets = bool(extra.get("skip_assets"))
    mc = (version or "").strip()
    if not mc:
        raise InstallError("缺少 Minecraft 版本")
    primary = (loader or extra.get("loader") or "无").strip().lower()
    want_of = bool(extra.get("optifine")) or primary == "optifine"
    want_ll = bool(extra.get("liteloader")) or primary == "liteloader"
    if primary in ("optifine", "liteloader"):
        primary = "无"
    lv = extra.get("loader_version") or loader_version or None
    of_typ = extra.get("optifine_type") or ""
    of_patch = extra.get("optifine_patch") or ""
    if extra.get("optifine_version") and not (of_typ or of_patch):
        of_typ, of_patch = parse_optifine_token(str(extra.get("optifine_version")))

    vid = mc
    if primary == "fabric":
        vid = installer.install_fabric(mc, extra.get("fabric_version") or lv)
    elif primary == "quilt":
        vid = installer.install_quilt(mc, extra.get("quilt_version") or lv)
    elif primary == "forge":
        vid = installer.install_forge(mc, extra.get("forge_version") or lv)
    elif primary == "neoforge":
        vid = installer.install_neoforge(mc, extra.get("neoforge_version") or lv)
    elif primary not in ("", "无", "none"):
        raise InstallError(f"未知加载器: {loader}")
    else:
        installer.install_version(mc)
        vid = mc

    if want_ll:
        try:
            ll_id = installer.install_liteloader(mc)
            if primary in ("", "无", "none"):
                vid = ll_id
            else:
                installer._note(f"LiteLoader 版本已写入: {ll_id}")
        except Exception as exc:
            installer._note(f"LiteLoader 安装失败: {exc}")
            if primary in ("", "无", "none"):
                raise

    if want_of:
        if primary in ("fabric", "quilt", "neoforge"):
            installer._note("OptiFine 不能与 Fabric / Quilt / NeoForge 同装，已跳过")
        elif primary == "forge":
            from . import optifine as optifine_mod
            mods = installer.instance.path / "mods"
            name = optifine_mod.install_as_mod(installer, mc, mods, typ=of_typ, patch=of_patch)
            installer._note(f"OptiFine 已作为 Forge 模组放入 mods/{name}")
        else:
            vid = installer.install_optifine(mc, typ=of_typ, patch=of_patch)
    return vid
