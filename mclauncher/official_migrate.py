# -*- coding: utf-8 -*-
"""从官方 Minecraft 启动器迁移版本 / 账号。

官方启动器数据目录：
- Windows: %APPDATA%\\.minecraft
- macOS: ~/Library/Application Support/minecraft
- Linux: ~/.minecraft
"""
from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from . import utils
from .instances import Instance, _STANDARD_DIRS

_ISO_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})")


def official_dir() -> Path:
    """返回官方启动器的 .minecraft 目录（若存在）。"""
    if utils.IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", ""))
        candidates = [base / ".minecraft"]
    elif utils.IS_MAC:
        base = Path.home() / "Library" / "Application Support"
        candidates = [base / "minecraft"]
    else:
        candidates = [Path.home() / ".minecraft"]
    for c in candidates:
        if c.is_dir():
            return c
    return Path("")


def detect_official() -> bool:
    """检测是否存在官方启动器数据目录。"""
    d = official_dir()
    return d.is_dir() and (d / "versions").is_dir()


def scan_versions(src: Path) -> list[str]:
    """扫描官方目录下的版本。"""
    vdir = src / "versions"
    if not vdir.is_dir():
        return []
    result = []
    for child in sorted(vdir.iterdir()):
        if child.is_dir() and (child / f"{child.name}.json").is_file():
            result.append(child.name)
    return result


def _load_version_json(src: Path, version_id: str) -> dict:
    return utils.read_json(src / "versions" / version_id / f"{version_id}.json", {}) or {}


def _inherit_chain(src: Path, version_id: str) -> list[str]:
    """版本本身 + inheritsFrom 祖先。

    Forge/Fabric 版本的 jar 和大半依赖都挂在被继承的原版上，只搬自己那层
    等于搬了个空壳。
    """
    chain: list[str] = []
    seen: set[str] = set()
    cur = version_id
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = str(_load_version_json(src, cur).get("inheritsFrom") or "").strip()
    return chain


def _library_relpaths(src: Path, version_id: str) -> list[str]:
    """该版本用到的库在 libraries/ 下的相对路径（含本平台 natives）。"""
    from .installer import select_native_classifier

    rels: list[str] = []
    seen: set[str] = set()
    for vid in _inherit_chain(src, version_id):
        for lib in _load_version_json(src, vid).get("libraries") or []:
            if not isinstance(lib, dict):
                continue
            name = str(lib.get("name") or "")
            downloads = lib.get("downloads") or {}
            artifact = downloads.get("artifact") or {}
            path = artifact.get("path") or (utils.maven_artifact_path(name) if name else "")
            if path and path not in seen:
                seen.add(path)
                rels.append(path)
            nkey = select_native_classifier(lib)
            if not nkey:
                continue
            entry = (downloads.get("classifiers") or {}).get(nkey) or {}
            npath = entry.get("path") or (
                utils.maven_artifact_path(f"{name}:{nkey}") if name else "")
            if npath and npath not in seen:
                seen.add(npath)
                rels.append(npath)
    return rels


def copy_libraries(src: Path, dest: Instance, version_id: str) -> int:
    """按版本 JSON 把官方 libraries/ 里用得上的库搬过来，返回复制数量。

    官方共享库是 Maven 布局，路径必须原样保留，启动器和预检都按这个路径找。
    """
    lib_src = Path(src) / "libraries"
    if not lib_src.is_dir():
        return 0
    lib_dest = dest.libraries_dir()
    copied = 0
    for rel in _library_relpaths(Path(src), version_id):
        f = lib_src / rel
        if not f.is_file():
            continue
        tgt = lib_dest / rel
        if tgt.is_file() and tgt.stat().st_size == f.stat().st_size:
            continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(f, tgt)
            copied += 1
        except OSError as exc:
            utils.log.warning("复制依赖库失败 %s: %s", rel, exc)
    return copied


def _copy_version(src: Path, dest: Instance, version_id: str) -> str:
    """复制单个版本（连同它继承的原版）到实例。"""
    s = src / "versions" / version_id
    if not s.is_dir():
        return ""
    for vid in _inherit_chain(src, version_id):
        vs = src / "versions" / vid
        if not vs.is_dir():
            continue
        d = dest.versions_dir() / vid
        d.mkdir(parents=True, exist_ok=True)
        for name in (f"{vid}.json", f"{vid}.jar"):
            f = vs / name
            if f.is_file():
                shutil.copy2(f, d / name)
    copy_libraries(src, dest, version_id)
    return version_id


def _copy_tree(src: Path, dest: Path, exts=None):
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        if exts and f.suffix.lower() not in exts:
            continue
        rel = f.relative_to(src)
        tgt = dest / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(f, tgt)
        except OSError:
            pass


def import_versions(src: Path, instance_name: str = "default", versions: list[str] | None = None) -> list[str]:
    """从官方目录导入版本到指定实例。返回导入成功的版本列表。"""
    src = Path(src)
    inst = Instance(instance_name)
    if not inst.path.is_dir():
        inst.create()
    wanted = versions or scan_versions(src)
    imported = []
    for vid in wanted:
        try:
            _copy_version(src, inst, vid)
            imported.append(vid)
        except Exception as e:
            utils.log.warning("导入版本失败 %s: %s", vid, e)
    if imported:
        inst.set_meta("mc_version", imported[-1])
    return imported


def _expires_at(acc: dict) -> float:
    """官方写的是纳秒精度 ISO 串，解析不了就当已过期（宁可要求重登）。"""
    match = _ISO_TS.search(str(acc.get("accessTokenExpiresAt") or ""))
    if not match:
        return 0.0
    try:
        parts = [int(x) for x in match.groups()]
        return datetime(*parts, tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def read_official_accounts(src: Path) -> list[dict]:
    """解析官方 launcher_accounts.json 里的正版档案。"""
    data = utils.read_json(Path(src) / "launcher_accounts.json", None)
    if not isinstance(data, dict):
        return []
    rows = []
    for local_id, acc in (data.get("accounts") or {}).items():
        if not isinstance(acc, dict):
            continue
        profile = acc.get("minecraftProfile") or {}
        name = str(profile.get("name") or "").strip()
        uuid = str(profile.get("id") or "").strip()
        if not name or not uuid:
            continue
        rows.append({
            "type": "microsoft",
            "name": name,
            "uuid": utils.dashed_uuid(uuid),
            "access_token": str(acc.get("accessToken") or ""),
            # 官方只落 MC 访问令牌，没有微软 refresh_token。过期后
            # ensure_valid 会明确要求重新登录，而不是拿空令牌去启动。
            "refresh_token": "",
            "xuid": "",
            "expires_at": _expires_at(acc),
            "updated_at": time.time(),
            "imported_from": "official-launcher",
            "local_id": str(local_id),
        })
    return rows


def import_accounts(src: Path, manager=None) -> list[str]:
    """把官方启动器的正版档案真正写进账号库，返回导入的角色名。

    必须真的写进账号库，不能只 `len()` 一下返回数字：UI 说的是
    「导入版本和账号」，账号那半得真落地。
    """
    rows = read_official_accounts(src)
    if not rows:
        return []
    if manager is None:
        from .auth import AccountManager
        manager = AccountManager()
    names = []
    for acc in rows:
        try:
            manager.add_account(acc)
            names.append(acc["name"])
        except Exception as exc:  # noqa: BLE001
            utils.log.warning("导入账号失败 %s: %s", acc.get("name"), exc)
    return names


def migrate(official_root: str, instance_name: str = "default",
            want_versions: bool = True, want_assets: bool = True,
            want_accounts: bool = True) -> dict:
    """执行完整迁移。返回统计信息。

    参数不能叫 import_versions：那会遮蔽上面的模块级同名函数，
    函数体里再调用它就成了 `True(...)` —— TypeError。
    """
    src = Path(official_root)
    if not src.is_dir():
        raise FileNotFoundError(f"官方启动器目录不存在: {src}")
    inst = Instance(instance_name)
    if not inst.path.is_dir():
        inst.create()
    result: dict = {"versions": [], "accounts": []}

    if want_versions:
        result["versions"] = import_versions(src, instance_name)

    if want_assets:
        # 复制全局 assets
        assets_src = src / "assets"
        if assets_src.is_dir() and assets_src != inst.assets_dir():
            _copy_tree(assets_src, inst.assets_dir())

    if want_accounts:
        result["accounts"] = import_accounts(src)
    return result