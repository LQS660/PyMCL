# -*- coding: utf-8 -*-
"""把旧的多实例结构并成单一游戏目录（启动时自动跑一次）。

旧结构：`.minecraft/<实例名>/versions/<版本>`，每个实例一套 mods/saves。
新结构：`.minecraft/versions/<版本>`，谁独占模组由每个版本的隔离开关决定。

合并时最要紧的是别把不同实例的模组倒进同一个 mods 里。所以：
被选作主目录的那个实例，它的共享池原样上浮，成为「大锅饭」；其余实例的
每个版本都改成独立隔离，并把原实例的共享内容复制进该版本自己的目录，
装过什么还是什么。
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import instances, utils
from .config import CONFIG
from .instances import INSTANCE_META

# 实例共享池：并进版本目录时要跟着走的内容
_CONTENT_DIRS = ("mods", "config", "saves", "resourcepacks", "shaderpacks",
                 "datapacks", "screenshots", "options")
# 按文件名去重即可安全合并的公共仓库
_POOL_DIRS = ("libraries", "assets")


def _versions_in(inst_dir: Path) -> list[str]:
    vdir = inst_dir / "versions"
    if not vdir.is_dir():
        return []
    out = []
    for child in sorted(vdir.iterdir()):
        if child.is_dir() and (child / f"{child.name}.json").is_file():
            out.append(child.name)
    return out


def is_link(path: Path) -> bool:
    """符号链接或 Windows 目录联接（隔离模式用 mklink /J 建的那种）。"""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return False
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None:
        try:
            return bool(is_junction(path))
        except OSError:
            return False
    try:
        attrs = path.lstat().st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def drop_link(path: Path) -> bool:
    """摘掉链接本身，不碰它指向的东西。"""
    if not is_link(path):
        return False
    for remove in (path.rmdir, path.unlink):
        try:
            remove()
            return True
        except OSError:
            continue
    return False


def strip_links(folder: Path):
    """清掉目录里一层链接。搬家之后它们还指着旧实例，留着就是脏数据。"""
    if not folder.is_dir() or is_link(folder):
        return
    for child in list(folder.iterdir()):
        drop_link(child)


def _move(src: Path, dst: Path):
    """跨盘 rename 会抛 OSError，退回复制＋删除。"""
    utils.ensure_dir(dst.parent)
    try:
        src.rename(dst)
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            utils.remove_tree(src)
        else:
            shutil.copy2(src, dst)
            src.unlink(missing_ok=True)


def _merge_into(src: Path, dst: Path):
    """把 src 目录的内容并进 dst，已存在的条目保留 dst 的。"""
    if not src.is_dir() or is_link(src):
        return
    utils.ensure_dir(dst)
    for child in list(src.iterdir()):
        if drop_link(child):
            continue
        target = dst / child.name
        if target.exists():
            if child.is_dir():
                _merge_into(child, target)
                _rmdir_if_empty(child)
            continue
        _move(child, target)
    _rmdir_if_empty(src)


def _copy_into(src: Path, dst: Path):
    if not src.is_dir() or is_link(src):
        return
    utils.ensure_dir(dst)
    for child in src.iterdir():
        target = dst / child.name
        if target.exists() or is_link(child):
            continue
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def _rmdir_if_empty(path: Path):
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def _unique_version_id(versions_dir: Path, vid: str, suffix: str) -> str:
    if not (versions_dir / vid).exists():
        return vid
    base = f"{vid}-{suffix}" if suffix else vid
    candidate = base
    n = 2
    while (versions_dir / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _rename_version_files(vdir: Path, old_id: str, new_id: str):
    """版本目录改名后，里面的 `<id>.json` / `<id>.jar` 也得跟着改。"""
    if old_id == new_id:
        return
    for ext in (".json", ".jar"):
        old = vdir / f"{old_id}{ext}"
        if old.is_file():
            old.rename(vdir / f"{new_id}{ext}")
    meta = utils.read_json(vdir / f"{new_id}.json", None)
    if isinstance(meta, dict) and meta.get("id") == old_id:
        meta["id"] = new_id
        utils.write_json(vdir / f"{new_id}.json", meta)


def _pick_primary(root: Path, names: list[str]) -> str:
    preferred = str(CONFIG.get("default_instance") or "").strip()
    if preferred in names:
        return preferred
    return max(names, key=lambda n: (len(_versions_in(root / n)), n))


def _relocate_bogus_root(log) -> Path:
    """游戏目录被指到启动器主目录本身时，挪回 `.minecraft`。

    这种配置下 `versions/` `libraries/` 会直接长在启动器源码/程序目录里，
    版本平铺之后更难收拾，所以先把它摆正。
    """
    root = CONFIG.instances_dir.resolve()
    if root != utils.ROOT.resolve():
        return root
    fixed = utils.ROOT / ".minecraft"
    utils.ensure_dir(fixed)
    for name in instances.list_legacy_instances():
        src = root / name
        dst = fixed / name
        if src.resolve() == fixed.resolve() or not src.is_dir():
            continue
        if dst.exists():
            _merge_into(src, dst)
            # 两边同名的 .instance.json 以目标那份为准，源的这份是空壳
            if src.is_dir():
                (src / INSTANCE_META).unlink(missing_ok=True)
                _rmdir_if_empty(src)
        else:
            _move(src, dst)
        log(f"游戏目录归位：{src} -> {dst}")
    CONFIG.set("instances_dir", ".minecraft")
    CONFIG.save()
    log(f"游戏目录已从启动器主目录改回 {fixed}")
    return fixed.resolve()


def migrate(log=None) -> dict:
    """幂等。返回本次做了什么，没事可做时各项为空。"""
    lines: list[str] = []

    def _log(msg):
        lines.append(str(msg))
        if callable(log):
            log(msg)

    report = {"merged": [], "versions": [], "isolated": [], "log": lines}

    root = _relocate_bogus_root(_log)
    utils.ensure_dir(root)
    legacy = instances.list_legacy_instances()
    if not legacy:
        _ensure_root_meta(root)
        return report

    primary = _pick_primary(root, legacy)
    _log(f"合并游戏目录：主目录取自实例「{primary}」，另有 {len(legacy) - 1} 个实例并入")

    _absorb_primary(root, root / primary, report, _log)
    for name in legacy:
        if name == primary:
            continue
        _absorb_secondary(root, root / name, name, report, _log)

    _ensure_root_meta(root)
    CONFIG.set("default_instance", "")
    CONFIG.save()
    _log(f"合并完成：共 {len(report['versions'])} 个版本，"
         f"其中 {len(report['isolated'])} 个转为独立模组目录")
    return report


def _ensure_root_meta(root: Path):
    if (root / INSTANCE_META).is_file():
        return
    utils.write_json(root / INSTANCE_META, {
        "name": root.name, "mc_version": None, "modpack": None,
        "java": instances.JAVA_AUTO,
    })


def _absorb_primary(root: Path, src: Path, report: dict, log):
    """主实例整个上浮：版本、共享池、元数据都原样接管。"""
    if not src.is_dir():
        return
    meta = utils.read_json(src / INSTANCE_META, None)
    versions_dir = root / "versions"
    utils.ensure_dir(versions_dir)
    for vid in _versions_in(src):
        target = _unique_version_id(versions_dir, vid, "")
        strip_links(src / "versions" / vid)
        _move(src / "versions" / vid, versions_dir / target)
        _rename_version_files(versions_dir / target, vid, target)
        report["versions"].append(target)
        log(f"  版本 {vid} -> versions/{target}")
    for child in list(src.iterdir()):
        if child.name == INSTANCE_META:
            child.unlink(missing_ok=True)
            continue
        if child.is_dir():
            _merge_into(child, root / child.name)
        elif not (root / child.name).exists():
            _move(child, root / child.name)
    _rmdir_if_empty(src / "versions")
    _rmdir_if_empty(src)
    if isinstance(meta, dict):
        merged = {k: v for k, v in meta.items() if k != "name"}
        merged["name"] = root.name
        utils.write_json(root / INSTANCE_META, merged)
    report["merged"].append(src.name)
    log(f"  实例「{src.name}」已成为游戏目录本体（大锅饭共享池）")


def _absorb_secondary(root: Path, src: Path, name: str, report: dict, log):
    """其余实例：每个版本转独立，把原实例的共享内容带进各自的版本目录。"""
    if not src.is_dir():
        return
    from . import version_settings as vs

    versions_dir = root / "versions"
    utils.ensure_dir(versions_dir)
    shared_users = []
    for vid in _versions_in(src):
        settings = utils.read_json(src / "versions" / vid / vs.FILE_NAME, None) or {}
        iso = settings.get("isolation") or vs.ISOLATION_NONE
        # 只隔离存档的版本，mods/config 也是从实例共享池链过来的，一样要带走
        was_shared = iso in (vs.ISOLATION_NONE, vs.ISOLATION_SAVES)
        target = _unique_version_id(versions_dir, vid, name)
        strip_links(src / "versions" / vid)
        _move(src / "versions" / vid, versions_dir / target)
        _rename_version_files(versions_dir / target, vid, target)
        report["versions"].append(target)
        log(f"  版本 {name}/{vid} -> versions/{target}")
        if was_shared:
            shared_users.append(target)

    for target in shared_users:
        vdir = versions_dir / target
        for sub in _CONTENT_DIRS:
            _copy_into(src / sub, vdir / sub)
        data = utils.read_json(vdir / vs.FILE_NAME, None) or {}
        data["isolation"] = vs.ISOLATION_ALL
        utils.write_json(vdir / vs.FILE_NAME, data)
        report["isolated"].append(target)
        log(f"    {target}：原实例共享模组已带入版本目录，隔离改为「独立全部」")

    for sub in _POOL_DIRS:
        _merge_into(src / sub, root / sub)
    for sub in _CONTENT_DIRS:
        utils.remove_tree(src / sub)
    (src / INSTANCE_META).unlink(missing_ok=True)
    _rmdir_if_empty(src / "versions")
    for child in list(src.iterdir()) if src.is_dir() else []:
        if child.is_dir():
            _rmdir_if_empty(child)
    _rmdir_if_empty(src)
    if src.is_dir():
        log(f"  实例「{name}」目录还有残留文件，已保留在 {src}")
    report["merged"].append(name)
