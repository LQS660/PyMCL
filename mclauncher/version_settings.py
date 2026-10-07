# -*- coding: utf-8 -*-
"""每版本设置：隔离、内存、Java、JVM、启动前后命令、直连服务器。对齐 PCL 版本设置。"""
from __future__ import annotations

import os
from pathlib import Path

from . import utils
from .config import CONFIG

FILE_NAME = "pymcl.json"
ISOLATION_NONE = "none"
ISOLATION_SAVES = "saves"
ISOLATION_MODS = "mods"
ISOLATION_ALL = "all"
ISOLATION_LABELS = {
    ISOLATION_NONE: "大锅饭（与其他版本共用）",
    ISOLATION_SAVES: "隔离存档",
    ISOLATION_MODS: "隔离 Mod 与配置",
    ISOLATION_ALL: "完全独立",
}
SHARED_LINKS = ("mods", "config", "resourcepacks", "shaderpacks", "downloads")
SAVES_LINKS = ("saves",)
# 版本卡上的一键开关只在这两档之间翻，四档细分留在版本设置里
ISOLATED_DEFAULT = ISOLATION_ALL
# 转独立时从大锅饭里带一份过去的内容
SEED_DIRS = ("mods", "config", "resourcepacks", "shaderpacks")

DEFAULTS = {
    "isolation": ISOLATION_NONE,
    "memory_mb": None,
    "java": "自动选择",
    "jvm_args": "",
    "game_args": "",
    "pre_launch": "",
    "post_launch": "",
    "pre_launch_wait": True,
    "server": "",
    "port": "",
    "process_priority": "normal",
    "icon": "",
    "hidden": False,
    "login_account": "",
    "auth_server": "",
    "auth_server_name": "",
    "nide8_id": "",
    "gc": "",
    "window_title": "",
    "window_mode": "window",
    "window_width": None,
    "window_height": None,
    "skip_assets": False,
    "offline_skin": "default",
}

# UI 历史上写过 "maximize"，启动链早期只认 "fullscreen"，两边对不上导致全屏静默失效。
# 以 "maximize" 为准，另一个作为别名容错。
FULLSCREEN_MODES = ("maximize", "fullscreen")


def _file(instance, version_id) -> Path:
    """版本设置的落盘位置：`versions/<id>/pymcl.json`。

    审计 #1 P0-2：这里以前零校验，`version_id="../../pwned"` 会让
    `utils.write_json` 先在游戏目录之外建目录、再把 pymcl.json 写进去。
    `safe_child_path` 的语义与 `saves._safe_child` / `installer.uninstall_version`
    一致：`resolve()` 之后确认父目录就是 `versions/`。
    """
    vid = utils.safe_version_id(version_id)
    vdir = utils.safe_child_path(instance.versions_dir(), vid)
    return vdir / FILE_NAME


def load(instance, version_id) -> dict:
    data = dict(DEFAULTS)
    stored = utils.read_json(_file(instance, version_id), None)
    if isinstance(stored, dict):
        data.update(stored)
    iso = data.get("isolation") or CONFIG.get("default_isolation") or ISOLATION_NONE
    if iso not in ISOLATION_LABELS:
        iso = ISOLATION_NONE
    data["isolation"] = iso
    return data


def save(instance, version_id, data: dict) -> dict:
    cur = load(instance, version_id)
    cur.update(data or {})
    if cur.get("isolation") not in ISOLATION_LABELS:
        cur["isolation"] = ISOLATION_NONE
    target = _file(instance, version_id)  # 落盘前再校验一次（load 已过，这里是显式保险）
    utils.write_json(target, cur)
    return cur


def is_isolated(settings) -> bool:
    """这个版本是否有自己的 mods 目录（而不是吃大锅饭）。"""
    iso = (settings or {}).get("isolation") or ISOLATION_NONE
    return iso in (ISOLATION_MODS, ISOLATION_ALL)


def set_isolation(instance, version_id, mode, seed=False) -> dict:
    """切隔离模式。`seed=True` 时把大锅饭里现有的模组/配置复制一份过去。

    转独立那一下版本目录是空的，不带种子的话用户会以为模组丢了；
    但整合包版本转独立时又不该把别人的模组拖进来，所以交给调用方决定。
    """
    if mode not in ISOLATION_LABELS:
        raise ValueError(f"未知的隔离模式: {mode!r}")
    before = load(instance, version_id)
    data = save(instance, version_id, {"isolation": mode})
    if seed and is_isolated(data) and not is_isolated(before):
        _seed_from_shared(instance, version_id)
    apply_isolation(instance, version_id, data)
    return data


def _seed_from_shared(instance, version_id):
    import shutil

    src_root = Path(instance.path)
    dest_root = instance.versions_dir() / version_id
    for name in SEED_DIRS:
        src = src_root / name
        if not src.is_dir():
            continue
        dest = dest_root / name
        utils.ensure_dir(dest)
        for child in src.iterdir():
            target = dest / child.name
            if target.exists() or child.is_symlink():
                continue
            try:
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)
            except OSError:
                continue


def game_dir(instance, version_id, settings=None) -> Path:
    # 审计 #1：这里是版本目录的公共入口，调用方（worlds / content_export /
    # saves / modpack）都假定它返回的是 versions/ 下的真实目录。穿越名在这里挡住，
    # 免得每个调用方各挡一遍。
    utils.safe_version_id(version_id)
    settings = settings or load(instance, version_id)
    iso = settings.get("isolation") or ISOLATION_NONE
    if iso in (ISOLATION_ALL, ISOLATION_SAVES, ISOLATION_MODS):
        return utils.safe_child_path(instance.versions_dir(), version_id, "版本 ID")
    return Path(instance.path)


def mods_dir(instance, version_id, settings=None) -> Path:
    root = game_dir(instance, version_id, settings)
    return root / "mods"


def _junction(link: Path, target: Path):
    target = Path(target)
    link = Path(link)
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink() and any(link.iterdir()):
            return
        try:
            if link.is_symlink() or link.is_file():
                link.unlink()
            elif link.is_dir() and not any(link.iterdir()):
                link.rmdir()
        except OSError:
            return
    utils.ensure_dir(target)
    utils.ensure_dir(link.parent)
    # 审计 #1 P0-4：这里以前走 `cmd /c mklink /J <link> <target>`。subprocess 用
    # 列表参数看着安全，但 cmd.exe 会**二次解析**命令行：`&` 是命令分隔符，而
    # `subprocess.list2cmdline` 只在参数含空格/引号时才加引号 —— 版本 ID 里带
    # `&`（Windows 目录名的合法字符，sanitize_id 的黑名单里没有它）就能执行任意
    # 命令。现在全程不经过 cmd.exe：os.symlink → CreateSymbolicLinkW → junction。
    if os.name == "nt":
        _win_dir_link(link, target)
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pass


def _win_dir_link(link: Path, target: Path):
    """Windows 上建目录链接，按「不需要管理员」的顺序尝试三种实现。

    1. `os.symlink`（开发者模式 / 有 SeCreateSymbolicLinkPrivilege 时可用）
    2. `CreateSymbolicLinkW`（同上，但能显式要 `SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE`）
    3. junction（`FSCTL_SET_REPARSE_POINT`，**不需要任何特权**，老系统也能用）

    全部失败就静默返回：隔离降级成普通目录，与旧实现 `check=False` 的行为一致。
    """
    if _try_symlink(link, target):
        return
    _create_junction(link, target)


def _try_symlink(link: Path, target: Path) -> bool:
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateSymbolicLinkW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        k32.CreateSymbolicLinkW.restype = ctypes.c_ubyte
        flags = 0x1 | 0x2  # SYMBOLIC_LINK_FLAG_DIRECTORY | ALLOW_UNPRIVILEGED_CREATE
        return bool(k32.CreateSymbolicLinkW(str(link), str(target), flags))
    except (OSError, AttributeError):
        return False


def _create_junction(link: Path, target: Path) -> bool:
    """用 `FSCTL_SET_REPARSE_POINT` 建 junction（无特权要求）。

    布局照 Windows 自己 `mklink /J` 写出来的那份：MountPoint 头的
    ReparseDataLength 从结构体第 8 字节起算，SubstituteName 是 `\\??\\<绝对路径>`。
    """
    if os.name != "nt":
        return False
    import ctypes
    import struct
    from ctypes import wintypes

    FSCTL_SET_REPARSE_POINT = 0x000900A4
    IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
    GENERIC_WRITE = 0x40000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        k32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        k32.DeviceIoControl.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        target_abs = os.path.abspath(str(target))
        sub_b = ("\\??\\" + target_abs).encode("utf-16-le")
        print_b = target_abs.encode("utf-16-le")
        data_len = 8 + len(sub_b) + 2 + len(print_b) + 2
        total = 8 + data_len
        buf = ctypes.create_string_buffer(total)
        struct.pack_into(
            "<IHHHHHH", buf, 0, IO_REPARSE_TAG_MOUNT_POINT, data_len, 0,
            0, len(sub_b), len(sub_b) + 2, len(print_b),
        )
        off = 16
        buf[off:off + len(sub_b)] = sub_b
        off += len(sub_b)
        buf[off:off + 2] = b"\x00\x00"
        off += 2
        buf[off:off + len(print_b)] = print_b
        off += len(print_b)
        buf[off:off + 2] = b"\x00\x00"

        utils.ensure_dir(link)
        handle = k32.CreateFileW(
            str(link), GENERIC_WRITE, 0, None, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            return False
        try:
            returned = wintypes.DWORD(0)
            return bool(k32.DeviceIoControl(
                handle, FSCTL_SET_REPARSE_POINT, buf, total, None, 0,
                ctypes.byref(returned), None,
            ))
        finally:
            k32.CloseHandle(handle)
    except (OSError, ValueError, AttributeError):
        return False


def apply_isolation(instance, version_id, settings=None) -> Path:
    """按隔离模式准备游戏目录。返回 game_dir。"""
    settings = settings or load(instance, version_id)
    gdir = game_dir(instance, version_id, settings)
    utils.ensure_dir(gdir)
    iso = settings.get("isolation") or ISOLATION_NONE
    if iso == ISOLATION_SAVES:
        for name in SHARED_LINKS:
            _junction(gdir / name, Path(instance.path) / name)
        utils.ensure_dir(gdir / "saves")
    elif iso == ISOLATION_MODS:
        for name in SAVES_LINKS + ("resourcepacks", "shaderpacks", "screenshots"):
            _junction(gdir / name, Path(instance.path) / name)
        for name in ("mods", "config"):
            utils.ensure_dir(gdir / name)
    elif iso == ISOLATION_ALL:
        # 从「隔离存档 / 隔离 Mod」切过来时，之前建的联接还指着共享池，
        # 不摘掉的话「完全独立」写进去的东西照样落在大锅饭里。
        for name in set(SHARED_LINKS) | set(SAVES_LINKS) | {"screenshots"}:
            _drop_link(gdir / name)
        for name in ("mods", "config", "saves", "resourcepacks", "shaderpacks"):
            utils.ensure_dir(gdir / name)
    return gdir


def _drop_link(path: Path):
    from .single_root import drop_link

    drop_link(path)
