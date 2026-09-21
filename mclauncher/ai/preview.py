# -*- coding: utf-8 -*-
"""写工具的变更预览：权限确认卡上展示「将要发生的实际变更」。

Qt 与 WPF 的确认卡都渲染这里返回的 ``lines``（逐行原样展示），所以两端
信息量天然一致；预览行里除标签外的正文（diff 行、路径、数字）不做翻译，
标签走 tr()，界面语言切到 en 时整个区块就是英文。

变更过大时降级：diff 超过 MAX_PREVIEW_LINES 只给前若干行 + 一条
「变更过大，完整内容见 <artifact 路径>」，绝不卡死确认卡。
"""

from __future__ import annotations

import difflib

from pathlib import Path

from mclauncher.i18n import tr

from . import artifacts

MAX_PREVIEW_LINES = 200


def _fmt_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _instance_dir(backend, args: dict) -> Path | None:
    try:
        from .tools import _inst
        return _inst(backend, args).path
    except Exception:  # noqa: BLE001
        return None


def _config_target(inst_dir: Path | None, args: dict) -> Path | None:
    if inst_dir is None:
        return None
    rel = str(args.get("path") or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        return None
    return inst_dir / "config" / rel


def _dir_stats(path: Path, cap: int = 5000) -> tuple[int, int, bool]:
    """(文件数, 总字节, 是否超 cap)。"""
    n = 0
    total = 0
    truncated = False
    try:
        for p in path.rglob("*"):
            if p.is_file():
                n += 1
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
                if n >= cap:
                    truncated = True
                    break
    except OSError:
        pass
    return n, total, truncated


def change_preview(backend, name: str, args: dict) -> dict | None:
    """按工具名生成确认卡预览。返回 None = 该工具没有结构化预览（回退一句话）。"""
    args = args or {}
    lines: list[str] = []
    kind = "info"
    too_large = False
    head = ""

    if name == "write_mod_config":
        kind = "diff"
        head = tr("将要写入的变更：")
        inst_dir = _instance_dir(backend, args)
        target = _config_target(inst_dir, args)
        if target is None:
            return None
        old = ""
        existed = target.is_file()
        if existed:
            try:
                old = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                old = ""
        new = str(args.get("content") or "")
        diff = list(difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile="a/" + str(args.get("path") or "config"),
            tofile="b/" + str(args.get("path") or "config"), lineterm=""))
        if not existed:
            lines.append(tr("（新建文件）"))
        if len(diff) > MAX_PREVIEW_LINES:
            too_large = True
            rel = artifacts.store("\n".join(diff), name)
            lines += diff[:MAX_PREVIEW_LINES]
            if rel:
                lines.append(tr("变更过大，完整内容见 {path}").format(path=rel))
            else:
                lines.append(tr("变更过大，仅显示前 {n} 行").format(n=MAX_PREVIEW_LINES))
        else:
            lines += diff
        return {"kind": kind, "head": head, "lines": lines, "too_large": too_large}

    if name in ("delete_mod", "disable_mod", "enable_mod"):
        kind = "summary"
        inst_dir = _instance_dir(backend, args)
        if inst_dir is None:
            return None
        fname = str(args.get("filename") or "")
        mods_dir = inst_dir / "mods"
        if name == "delete_mod":
            head = tr("将被删除：")
            targets = [mods_dir / fname, mods_dir / (fname + ".disabled")]
        elif name == "disable_mod":
            head = tr("将被改名：")
            targets = [mods_dir / fname]
        else:
            head = tr("将被改名：")
            targets = [mods_dir / (fname + ".disabled")]
        total = 0
        found = 0
        for t in targets:
            if t.is_file():
                try:
                    size = t.stat().st_size
                except OSError:
                    size = 0
                total += size
                found += 1
                if name == "delete_mod":
                    lines.append(f"- mods/{t.name}（{_fmt_bytes(size)}）")
                else:
                    new_name = t.name + ".disabled" if name == "disable_mod" \
                        else t.name[:-len(".disabled")] if t.name.endswith(".disabled") else t.name
                    lines.append(f"- mods/{t.name} → mods/{new_name}")
        if not found:
            lines.append(tr("（没找到这个文件，执行时可能报「不存在」）"))
        else:
            lines.append(tr("共 {n} 个文件，{size}").format(n=found, size=_fmt_bytes(total)))
        return {"kind": kind, "head": head, "lines": lines, "too_large": False}

    if name == "delete_instance":
        kind = "summary"
        inst_dir = _instance_dir(backend, {"instance": args.get("name")})
        if inst_dir is None:
            return None
        head = tr("将被删除：")
        n, total, trunc = _dir_stats(inst_dir)
        prefix = ">" if trunc else ""
        lines.append(f"- {inst_dir.name}/")
        lines.append(tr("共 {n} 个文件，{size}（不可恢复）")
                     .format(n=prefix + str(n), size=_fmt_bytes(total)))
        return {"kind": kind, "head": head, "lines": lines, "too_large": False}

    if name in ("install_mod", "install_modpack", "install_shader",
                "install_resourcepack", "install_datapack", "install_world",
                "install_game", "download_java"):
        kind = "summary"
        head = tr("安装目标：")
        inst_dir = _instance_dir(backend, args)
        sub = {
            "install_mod": "mods", "install_shader": "shaderpacks",
            "install_resourcepack": "resourcepacks", "install_datapack": "datapacks",
            "install_world": "saves",
        }.get(name)
        if name == "download_java":
            target = None
            lines.append(tr("Java 运行时目录（由启动器管理）"))
            lines.append(tr("预计新增文件数：多个（安装时确定）"))
        elif inst_dir is None:
            return None
        else:
            target = inst_dir / sub if sub else inst_dir
            lines.append(str(target))
            if name == "install_mod":
                lines.append(tr("预计新增文件数：{n}").format(n=1))
            elif name in ("install_shader", "install_resourcepack", "install_datapack"):
                lines.append(tr("预计新增文件数：{n}").format(n=1))
            elif name == "install_world":
                lines.append(tr("预计新增文件数：存档目录（含 level.dat 等多个文件）"))
            else:
                lines.append(tr("预计新增文件数：安装时确定（多于 1 个）"))
        return {"kind": kind, "head": head, "lines": lines, "too_large": False}

    if name == "create_instance":
        kind = "summary"
        head = tr("安装目标：")
        inst_dir = _instance_dir(backend, {})
        if inst_dir is not None:
            parent = inst_dir.parent
            lines.append(str(parent / str(args.get("name") or "")))
        lines.append(tr("预计新增文件数：安装时确定（多于 1 个）"))
        return {"kind": kind, "head": head, "lines": lines, "too_large": False}

    if name == "launch_game":
        kind = "info"
        head = tr("启动目标：")
        inst = str(args.get("instance") or "")
        ver = str(args.get("version") or "")
        if inst:
            lines.append(tr("实例：{name}").format(name=inst))
        if ver:
            lines.append(tr("版本：{ver}").format(ver=ver))
        return {"kind": kind, "head": head, "lines": lines, "too_large": False}

    return None
