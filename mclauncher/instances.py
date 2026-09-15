# -*- coding: utf-8 -*-
"""游戏目录管理。

对齐 PCL/HMCL：只有一个游戏目录（`.minecraft`），版本平铺在它的 `versions/`
下面，谁装了哪些模组由每个版本自己的隔离开关决定（见 `version_settings`）。

`Instance` 这个类保留下来当「游戏目录句柄」用——启动链、安装器、模组管理
都拿它当参数，换名字要动两千行。历史上它还能指向 `.minecraft/<子目录>`
形式的多实例，那套结构现在由 `single_root.migrate()` 在启动时并进根目录，
这里只留下读旧结构的能力，供迁移期与命令行兜底。
"""
import re
from pathlib import Path

from . import utils
from .config import CONFIG

INSTANCE_META = ".instance.json"
JAVA_AUTO = "自动选择"
_MAX_INSTANCE_NAME = 48
_ILLEGAL_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_STANDARD_DIRS = [
    "mods", "config", "saves", "resourcepacks", "shaderpacks",
    "datapacks",
    "screenshots", "crash-reports", "logs", "options",
    "screenshots", "crash-reports", "logs", "options",
    "servers", "texturepacks", "versions", "libraries",
]


class InstanceError(Exception):
    pass


def root_dir() -> Path:
    """唯一的游戏目录。默认是启动器主目录下的 `.minecraft`。"""
    return CONFIG.instances_dir


def root_name() -> str:
    """游戏目录的展示名。UI 里凡是要一个「实例名」的地方都用它。"""
    return root_dir().name or ".minecraft"


def single_root_mode() -> bool:
    """游戏目录本身已经是版本容器（迁移完成）。"""
    return (root_dir() / INSTANCE_META).is_file()


def list_legacy_instances() -> list:
    """旧结构里 `.minecraft/<实例名>/` 那一层的子实例名。"""
    root = root_dir()
    if not root.is_dir():
        return []
    names = []
    for child in root.iterdir():
        if child.is_dir() and (child / INSTANCE_META).is_file():
            names.append(child.name)
    return sorted(names)


def list_instances() -> list:
    """可用的游戏目录名。单目录模式下就是游戏目录本身那一个。"""
    legacy = list_legacy_instances()
    if single_root_mode() or not legacy:
        return [root_name()] + legacy
    return legacy


def resolve_name(name) -> str:
    """把外部传进来的实例名归一到真实目录名。

    单目录模式下，`default` 这类已经并进根目录的旧名字一律落到游戏目录，
    否则调用方随手传的 `instance="default"` 会在 `.minecraft` 里重新长出
    一个空实例来。
    """
    s = str(name or "").strip()
    if not s or s == root_name():
        return ""
    if single_root_mode() and not (root_dir() / s / INSTANCE_META).is_file():
        return ""
    return s


def sanitize_instance_name(raw, fallback="游戏") -> str:
    """去掉 Windows 非法字符，得到可用的实例名。"""
    s = _ILLEGAL_NAME.sub("-", str(raw or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s:
        s = fallback
    if s.upper() in _WIN_RESERVED:
        s = f"{s}-游戏"
    if len(s) > _MAX_INSTANCE_NAME:
        s = s[:_MAX_INSTANCE_NAME].rstrip(" .")
    if not s:
        s = fallback
    return s


def unique_instance_name(raw, fallback="游戏") -> str:
    """在已有实例名上自动加 -2、-3，避免覆盖。"""
    base = sanitize_instance_name(raw, fallback)
    existing = set(list_instances())
    root = CONFIG.instances_dir
    name = base
    n = 2
    while name in existing or (root / name).exists():
        suffix = f"-{n}"
        trimmed = base
        limit = _MAX_INSTANCE_NAME - len(suffix)
        if len(trimmed) > limit:
            trimmed = trimmed[:limit].rstrip(" .") or fallback
        name = f"{trimmed}{suffix}"
        n += 1
    return name


def get_instance_path(name) -> Path:
    root = CONFIG.instances_dir.resolve()
    if not name or str(name) == root.name:
        return root
    if name in (".", "..") or not re.fullmatch(r"[^\\/:*?\"<>|]+", name):
        raise InstanceError(f"非法实例名: {name!r}")
    path = (root / name).resolve()
    # 防路径穿越：实例必须直接位于实例目录之下
    if path.parent != root:
        raise InstanceError(f"非法实例名: {name!r}")
    return path


class Instance:
    def __init__(self, name=None):
        if name is None:
            name = CONFIG.get("default_instance", "")
        self.name = resolve_name(name) or root_name()
        self.path = get_instance_path(self.name)
        self.is_root = self.path == CONFIG.instances_dir.resolve()

    # ---- 创建 / 删除 / 重命名
    def create(self, meta=None):
        if self.is_root:
            # 游戏目录本身不存在「已存在」这回事，补齐结构即可
            self.ensure_standard_dirs()
            if not (self.path / INSTANCE_META).is_file():
                utils.write_json(self.path / INSTANCE_META, {
                    "name": self.name, "mc_version": None, "modpack": None,
                    "java": JAVA_AUTO, **({} if not meta else meta),
                })
            return
        if self.path.is_dir():
            raise InstanceError(f"实例 {self.name} 已存在。")
        utils.ensure_dir(self.path)
        for d in _STANDARD_DIRS:
            utils.ensure_dir(self.path / d)
        data = {"name": self.name, "mc_version": None, "modpack": None, "java": JAVA_AUTO, **({} if not meta else meta)}
        utils.write_json(self.path / INSTANCE_META, data)

    def delete(self):
        if self.is_root:
            raise InstanceError("游戏目录不能删除，请到「版本管理」里逐个卸载版本。")
        if not self.path.is_dir():
            raise InstanceError(f"实例 {self.name} 不存在。")
        utils.remove_tree(self.path)
        if CONFIG.get("default_instance") == self.name:
            CONFIG.set("default_instance", "")
            CONFIG.save()

    def rename(self, new_name):
        if self.is_root:
            raise InstanceError("游戏目录不能重命名，请到设置里改「游戏目录」。")
        new_path = get_instance_path(new_name)
        if new_path.exists():
            raise InstanceError(f"实例 {new_name} 已存在。")
        self.path.rename(new_path)
        if CONFIG.get("default_instance") == self.name:
            CONFIG.set("default_instance", new_name)
            CONFIG.save()
        self.name = new_name
        self.path = new_path
        self.set_meta("name", new_name)

    def meta(self):
        return utils.read_json(self.path / INSTANCE_META, {}) or {}

    def set_meta(self, key, value):
        data = self.meta()
        data[key] = value
        utils.write_json(self.path / INSTANCE_META, data)

    def java_pref(self) -> str:
        """该实例指定的 Java：自动选择，或 java.exe 路径 / 显示名。"""
        v = (self.meta() or {}).get("java")
        if v is None or str(v).strip() in ("", JAVA_AUTO, "auto", "default"):
            return JAVA_AUTO
        return str(v).strip()

    def set_java_pref(self, value):
        v = (value or "").strip() or JAVA_AUTO
        if v in ("auto", "default"):
            v = JAVA_AUTO
        self.set_meta("java", v)

    # ---- 路径
    def versions_dir(self):
        return self.path / "versions"

    def libraries_dir(self):
        return CONFIG.libraries_dir(self.path)

    def assets_dir(self):
        return CONFIG.assets_dir(self.path)

    def natives_dir(self, version_id, version_json=None):
        """旧版本（<1.6）natives 放在 bin/natives，其余放版本目录下。"""
        from .manifest import is_legacy_version
        if version_json and is_legacy_version(version_json):
            return self.path / "bin" / "natives"
        return self.versions_dir() / version_id / f"{version_id}-natives"

    def ensure_standard_dirs(self):
        for d in _STANDARD_DIRS:
            utils.ensure_dir(self.path / d)

    # ---- 已安装版本
    def installed_versions(self):
        """返回 [(版本id, version json路径), ...]"""
        vdir = self.versions_dir()
        result = []
        if not vdir.is_dir():
            return result
        for child in sorted(vdir.iterdir()):
            if not child.is_dir():
                continue
            jfile = child / f"{child.name}.json"
            if jfile.is_file():
                result.append((child.name, jfile))
        return result

    def installed_ids(self):
        return [vid for vid, _ in self.installed_versions()]

    def version_json(self, version_id):
        jfile = self.versions_dir() / version_id / f"{version_id}.json"
        return utils.read_json(jfile, None)

    def has_version(self, version_id) -> bool:
        return (self.versions_dir() / version_id / f"{version_id}.json").is_file()


def create_unique_instance(raw, fallback="游戏", meta=None) -> Instance:
    """按版本/整合包名称新建一个空实例。"""
    inst = Instance(unique_instance_name(raw, fallback))
    inst.create(meta=meta)
    return inst
