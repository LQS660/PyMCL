# -*- coding: utf-8 -*-
"""拖进窗口的整合包：先认出它是什么，再问一句要不要装。

只读包里的索引文件（modrinth.index.json / manifest.json），不解压、不落盘；
真正的安装还是走 backend.install_modpack。
"""
import json
import re
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QFormLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, LineEdit, MessageBoxBase, StrongBodyLabel, SubtitleLabel,
)

from mclauncher.i18n import tr
from ..pcl_chrome import form_label, paint_theme_surfaces

# 压缩时多套了一层文件夹的包很常见，标志文件往下找几层
_MAX_NEST = 3
# 直接压缩的 .minecraft 目录：靠这几个标志性子目录认
_PLAIN_MARKERS = frozenset((
    "mods", "config", "versions", "saves", "resourcepacks", "shaderpacks",
))
_LOADER_LABELS = {
    "forge": "Forge", "neoforge": "NeoForge",
    "fabric": "Fabric", "fabric-loader": "Fabric",
    "quilt": "Quilt", "quilt-loader": "Quilt",
    "liteloader": "LiteLoader",
}


def loader_label(loader, version="") -> str:
    if not loader:
        return tr("原版（未声明加载器）")
    name = _LOADER_LABELS.get(str(loader).lower(), str(loader))
    return f"{name} {version}".strip()


def _member(names, marker: str):
    """在包里找标志文件，返回最浅的那个成员名；找不到给 None。"""
    best = None
    for n in names:
        parts = n.split("/")
        if parts[-1] != marker or len(parts) > _MAX_NEST + 1:
            continue
        if best is None or len(parts) < len(best.split("/")):
            best = n
    return best


def _read_json(zf, name):
    try:
        with zf.open(name) as f:
            return json.loads(f.read().decode("utf-8-sig", "replace"))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return None


def _probe_mrpack(zf, names):
    member = _member(names, "modrinth.index.json")
    if not member:
        return None
    idx = _read_json(zf, member)
    if not isinstance(idx, dict):
        return None
    deps = idx.get("dependencies") or {}
    loader = next((k for k in ("forge", "neoforge", "fabric-loader", "quilt-loader")
                   if deps.get(k)), None)
    return {
        "kind": "mrpack",
        "format": "Modrinth .mrpack",
        "name": idx.get("name") or "",
        "version": idx.get("versionId") or "",
        "mc_version": deps.get("minecraft") or "",
        "loader": loader,
        "loader_version": deps.get(loader) or "" if loader else "",
        "files": len(idx.get("files") or []),
    }


def _probe_curseforge(zf, names):
    member = _member(names, "manifest.json")
    if not member:
        return None
    mf = _read_json(zf, member)
    if not isinstance(mf, dict):
        return None
    mc = mf.get("minecraft")
    # 模组自己也可能带 manifest.json，但不会有 minecraft 这一段
    if not isinstance(mc, dict):
        return None
    loaders = [l for l in (mc.get("modLoaders") or []) if isinstance(l, dict)]
    primary = next((l for l in loaders if l.get("primary")), loaders[0] if loaders else {})
    loader, _, loader_version = str(primary.get("id") or "").partition("-")
    return {
        "kind": "curseforge",
        "format": "CurseForge .zip",
        "name": mf.get("name") or "",
        "version": mf.get("version") or "",
        "mc_version": mc.get("version") or "",
        "loader": loader or None,
        "loader_version": loader_version,
        "files": len(mf.get("files") or []),
    }


def _plain_version(names, prefix: str):
    """从 versions/<名>/<名>.json 的目录名推 MC 版本与加载器。"""
    head = f"{prefix}versions/"
    for n in names:
        if not n.startswith(head):
            continue
        parts = n[len(head):].split("/")
        if len(parts) != 2 or parts[1] != f"{parts[0]}.json":
            continue
        vid = parts[0]
        for key, loader in (("neoforge", "neoforge"), ("-forge-", "forge"),
                            ("fabric-loader-", "fabric-loader"),
                            ("quilt-loader-", "quilt-loader")):
            if key in vid:
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", vid)
                return (m.group(1) if m else ""), loader
        return vid, None
    return "", None


def _probe_plain(names):
    """直接压缩的 .minecraft 目录（可能还套了一层文件夹）。"""
    children: dict[str, set] = {}
    for n in names:
        parts = [p for p in n.split("/") if p]
        for depth in range(min(len(parts), _MAX_NEST)):
            children.setdefault("/".join(parts[:depth]), set()).add(parts[depth].lower())
    for root in sorted(children, key=len):
        hit = children[root] & _PLAIN_MARKERS
        # 一个资源包 / 模组 jar 顶多蹭到一个同名目录，两个以上才算数
        if len(hit) < 2 and "versions" not in hit:
            continue
        prefix = f"{root}/" if root else ""
        mc_version, loader = _plain_version(names, prefix)
        return {
            "kind": "plain",
            "format": tr("直接压缩的 .minecraft 目录"),
            "name": "",
            "version": "",
            "mc_version": mc_version,
            "loader": loader,
            "loader_version": "",
            "files": 0,
        }
    return None


class _DirArchive:
    """让一个目录也能按 zip 那套读，`_probe_*` 就不用写两遍。"""

    # 认包只看前几层，别为了一个判断把几千个模组文件全遍历一遍
    _MAX_ENTRIES = 4000

    def __init__(self, root: Path):
        self.root = root

    def namelist(self) -> list[str]:
        names = []
        stack = [(self.root, 0)]
        while stack and len(names) < self._MAX_ENTRIES:
            folder, depth = stack.pop()
            try:
                children = sorted(folder.iterdir())
            except OSError:
                continue
            for child in children:
                names.append(child.relative_to(self.root).as_posix())
                if child.is_dir() and depth + 1 < _MAX_NEST:
                    stack.append((child, depth + 1))
        return names

    def open(self, name: str):
        return (self.root / name).open("rb")


def probe(path) -> dict | None:
    """认一下这东西是不是整合包，不是就返回 None。

    只看内容不看后缀：改过名的 .mrpack、CurseForge 导出的 zip 都认；
    已经解开的包目录、`.minecraft` 目录同样认。
    """
    p = Path(path)
    try:
        if p.is_dir():
            arc = _DirArchive(p)
            names = arc.namelist()
            info = _probe_mrpack(arc, names) or _probe_curseforge(arc, names) or _probe_plain(names)
        elif p.is_file():
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                info = (_probe_mrpack(zf, names)
                        or _probe_curseforge(zf, names)
                        or _probe_plain(names))
        else:
            return None
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return None
    if info is None:
        return None
    info["path"] = str(p)
    info["name"] = info["name"] or (p.name if p.is_dir() else p.stem)
    if p.is_dir():
        info["format"] = f'{info["format"]} · {tr("已解开的目录")}'
    return info


def suggest_version_name(info: dict) -> str:
    """版本名的默认值：包名 + 包版本，去掉 Windows 不认的字符。"""
    from mclauncher import version_ops

    parts = [str(info.get("name") or "").strip(), str(info.get("version") or "").strip()]
    raw = " ".join(p for p in parts if p) or str(info.get("name") or "")
    try:
        return version_ops.sanitize_id(raw)
    except version_ops.VersionOpError:
        return ""


class ModpackDropDialog(MessageBoxBase):
    """拖进来之后的那一下确认：摆出认到的东西，顺手定版本名与隔离。"""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.viewLayout.addWidget(SubtitleLabel(tr("导入整合包"), self))
        self.viewLayout.addWidget(StrongBodyLabel(info.get("name") or "", self))

        form_host = QWidget(self)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 8, 0, 0)
        rows = [
            (tr("格式"), info.get("format") or ""),
            (tr("整合包版本"), info.get("version") or tr("未声明")),
            (tr("Minecraft"), info.get("mc_version") or tr("未声明，安装时再解析")),
            (tr("加载器"), loader_label(info.get("loader"), info.get("loader_version"))),
        ]
        if info.get("files"):
            rows.append((tr("索引文件"), str(info["files"])))
        for label, value in rows:
            form.addRow(form_label(label), BodyLabel(str(value), form_host))

        self.name_edit = LineEdit(form_host)
        self.name_edit.setText(suggest_version_name(info))
        self.name_edit.setPlaceholderText(tr("留空则用加载器给的版本号"))
        form.addRow(form_label(tr("版本名")), self.name_edit)
        self.viewLayout.addWidget(form_host)
        paint_theme_surfaces(form_host, allow_transparent=False)

        self.isolate_box = CheckBox(tr("这一版独立存放（模组、配置、存档都归自己）"), self)
        self.isolate_box.setChecked(True)
        self.viewLayout.addWidget(self.isolate_box)

        tip = CaptionLabel(
            tr("会在「版本管理」里建一个新版本，现有版本不受影响；关掉独立存放，"
               "这包模组会倒进公共 mods 目录，其他没隔离的版本也会跟着加载。"), self)
        tip.setWordWrap(True)
        self.viewLayout.addWidget(tip)
        path_label = CaptionLabel(info.get("path") or "", self)
        path_label.setWordWrap(True)
        self.viewLayout.addWidget(path_label)

        self.yesButton.setText(tr("创建新版本"))
        self.cancelButton.setText(tr("取消"))
        self.widget.setMinimumWidth(460)

    def version_name(self) -> str:
        return self.name_edit.text().strip()

    def isolate(self) -> bool:
        return bool(self.isolate_box.isChecked())
