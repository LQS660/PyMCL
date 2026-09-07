# -*- coding: utf-8 -*-
"""实例 config 目录读写，限制在 config/ 内。"""

from __future__ import annotations

from pathlib import Path

from mclauncher.instances import Instance

_OK_SUFFIX = {
    ".toml", ".json", ".json5", ".cfg", ".txt", ".properties",
    ".conf", ".ini", ".snbt",
}
_MAX_BYTES = 512 * 1024
_MAX_LIST = 80


class ConfigEditError(Exception):
    pass


def _config_root(instance: Instance) -> Path:
    root = (instance.path / "config").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(instance: Instance, rel: str) -> Path:
    root = _config_root(instance)
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ConfigEditError("非法配置路径")
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ConfigEditError("路径必须在 config 目录内")
    return path


def list_configs(instance: Instance, prefix: str = "") -> list[dict]:
    root = _config_root(instance)
    base = _safe(instance, prefix) if prefix else root
    if base.is_file():
        return [{"path": str(base.relative_to(root)).replace("\\", "/"), "bytes": base.stat().st_size}]
    rows = []
    if not base.is_dir():
        return rows
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _OK_SUFFIX:
            continue
        rows.append({
            "path": str(p.relative_to(root)).replace("\\", "/"),
            "bytes": p.stat().st_size,
        })
        if len(rows) >= _MAX_LIST:
            break
    return rows


def read_config(instance: Instance, rel: str, max_chars: int = 8000) -> str:
    path = _safe(instance, rel)
    if not path.is_file():
        raise ConfigEditError(f"配置不存在: {rel}")
    if path.stat().st_size > _MAX_BYTES:
        raise ConfigEditError("配置文件过大")
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n…(已截断)"
    return text


def write_config(instance: Instance, rel: str, content: str) -> str:
    path = _safe(instance, rel)
    if path.suffix.lower() not in _OK_SUFFIX:
        raise ConfigEditError(f"不允许写这种后缀: {path.suffix}")
    data = content.encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise ConfigEditError("写入内容过大")
    path.parent.mkdir(parents=True, exist_ok=True)
    bak = path.with_name(path.name + ".bak")
    if path.is_file():
        bak.write_bytes(path.read_bytes())
    path.write_bytes(data)
    return f"已写入 {rel}"
