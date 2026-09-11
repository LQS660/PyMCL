# -*- coding: utf-8 -*-
"""皮肤头像 / 全身预览 URL，以及离线账号的自定义皮肤文件管理。"""
from __future__ import annotations

import shutil
import struct
from pathlib import Path
from urllib.parse import quote, urlparse

from . import utils

STEVE = "https://mc-heads.net/avatar/Steve/128"
BODY = "https://mc-heads.net/body/{}/180"

CLASSIC = "classic"
SLIM = "slim"
# 皮肤贴图只有这两种尺寸：64x32 是 1.8 以前的老格式，之后一律 64x64
VALID_SIZES = {(64, 64), (64, 32)}


def _site_origin(api: str) -> str:
    raw = str(api or "").rstrip("/")
    for suffix in ("/api/yggdrasil", "/yggdrasil"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return raw


def avatar_url(account: dict | None) -> str:
    acc = account or {}
    uuid = utils.dashed_uuid(acc.get("uuid") or "").replace("-", "")
    name = acc.get("name") or "Steve"
    kind = acc.get("type") or "offline"
    if kind == "authlib" and acc.get("api"):
        origin = _site_origin(acc["api"])
        if name:
            return f"{origin}/avatar/{quote(name)}"
        if uuid:
            return f"{origin}/avatar/{uuid}"
    if uuid and kind == "microsoft":
        return f"https://crafatar.com/avatars/{uuid}?overlay=true&size=128"
    return f"https://mc-heads.net/avatar/{quote(name)}/128"


def body_url(account: dict | None) -> str:
    acc = account or {}
    uuid = utils.dashed_uuid(acc.get("uuid") or "").replace("-", "")
    name = acc.get("name") or "Steve"
    if acc.get("type") == "authlib" and acc.get("api") and name:
        origin = _site_origin(acc["api"])
        return f"{origin}/preview/{quote(name)}"
    if acc.get("type") == "microsoft" and uuid:
        return f"https://crafatar.com/renders/body/{uuid}?overlay=true&scale=6"
    return BODY.format(quote(name))


def steve_url() -> str:
    return STEVE


# ------------------------------------------------------- 离线自定义皮肤文件

class SkinError(ValueError):
    pass


def skins_dir() -> Path:
    d = utils.ROOT / "skins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def png_size(data: bytes) -> tuple[int, int]:
    """只读 PNG 头拿宽高，不为了这点事引入 Pillow。"""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SkinError("这不是一个有效的 PNG 文件")
    return struct.unpack(">II", data[16:24])


def validate_skin(data: bytes) -> tuple[int, int]:
    w, h = png_size(data)
    if (w, h) not in VALID_SIZES:
        raise SkinError(f"皮肤尺寸必须是 64x64 或 64x32，这张是 {w}x{h}")
    return w, h


def _dest_for(account_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (account_name or "player"))
    return skins_dir() / f"{safe or 'player'}.png"


def save_skin_bytes(account_name: str, data: bytes) -> str:
    """存一段已经校验过的 PNG，返回文件名。"""
    dest = _dest_for(account_name)
    dest.write_bytes(data)
    return dest.name


def import_skin(account_name: str, src: str | Path) -> str:
    """把用户挑的 PNG 收进 ROOT/skins，返回存起来的文件名。"""
    path = Path(src).expanduser()
    if not path.is_file():
        raise SkinError(f"找不到文件：{path}")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise SkinError("皮肤文件过大（上限 2 MB）")
    data = path.read_bytes()
    validate_skin(data)
    dest = _dest_for(account_name)
    if path.resolve() != dest.resolve():
        shutil.copyfile(path, dest)
    return dest.name


def skin_file_for(account: dict | None) -> Path | None:
    """账号绑定的自定义皮肤文件；没设或文件没了都返回 None。"""
    name = ((account or {}).get("skin_file") or "").strip()
    if not name:
        return None
    # 只认 skins 目录下的文件名，别让配置里一个 ../ 把任意文件读出去
    path = skins_dir() / Path(name).name
    return path if path.is_file() else None


def load_skin_png(account: dict | None) -> bytes | None:
    path = skin_file_for(account)
    if path is None:
        return None
    try:
        data = path.read_bytes()
        validate_skin(data)
        return data
    except (OSError, SkinError):
        return None


def skin_model(account: dict | None) -> str:
    return SLIM if ((account or {}).get("skin_model") or "").lower() == SLIM else CLASSIC


def remove_skin(account: dict | None) -> None:
    path = skin_file_for(account)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass
