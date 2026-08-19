# -*- coding: utf-8 -*-
"""通用工具函数。"""
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import sys
import zipfile
import tarfile
from pathlib import Path

from . import APP_NAME, APP_VERSION

# ---------------------------------------------------------------- 路径与平台

def _resolve_root() -> Path:
    """启动器“主目录”：所有实例 / Java / 配置 / 缓存都放在这里。"""
    env = os.environ.get("PYMCL_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：优先 exe 所在目录（便携模式，数据跟着 exe 走）
        exe_dir = Path(sys.executable).resolve().parent
        try:
            probe = exe_dir / ".pymcl_wtest"
            probe.write_text("1", encoding="utf-8")
            probe.unlink()
            return exe_dir
        except OSError:
            pass
        # exe 目录不可写（如 Program Files）：退回用户数据目录
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
            return base / "PyMCL"
        return Path.home() / ".pymcl"
    # 源码运行：项目根目录
    return Path(__file__).resolve().parent.parent


ROOT = _resolve_root()


def os_name() -> str:
    """返回 Minecraft 启动器使用的系统名: windows / osx / linux。"""
    s = sys.platform
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "osx"
    return "linux"


def arch_name() -> str:
    """返回架构名: x64 / x86 / arm64。"""
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x64"
    if m in ("x86", "i386", "i686"):
        return "x86"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return "x64"


OS_NAME = os_name()
OS_VERSION = platform.version() or ""
ARCH = arch_name()
IS_WINDOWS = OS_NAME == "windows"
IS_MAC = OS_NAME == "osx"


def java_executable_name() -> str:
    return "javaw.exe" if IS_WINDOWS else "java"


# ---------------------------------------------------------------- 目录与文件

def ensure_dir(path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as e:
        log.warning("读取 JSON 失败 %s: %s", path, e)
        return default


def write_json(path, data):
    p = Path(path)
    ensure_dir(p.parent)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def remove_tree(path, missing_ok=True):
    p = Path(path)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        try:
            p.unlink()
        except OSError:
            pass
    elif not missing_ok:
        raise FileNotFoundError(path)


# ---------------------------------------------------------------- 哈希

def sha1_file(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha512_file(path) -> str:
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def file_matches(path, sha1=None, size=None) -> bool:
    """无 sha1 且无 size 时不把“文件存在”当成校验通过。"""
    p = Path(path)
    if not p.is_file():
        return False
    if size is not None and p.stat().st_size != int(size):
        return False
    if sha1:
        try:
            return sha1_file(p).lower() == str(sha1).lower()
        except OSError:
            return False
    return size is not None


def dashed_uuid(value: str) -> str:
    """把 32 位 hex 或已带连字符的 UUID 规范成 8-4-4-4-12。"""
    raw = (value or "").strip()
    hex_str = raw.replace("-", "")
    if len(hex_str) != 32 or any(c not in "0123456789abcdefABCDEF" for c in hex_str):
        return raw
    hex_str = hex_str.lower()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def offline_uuid(username: str) -> str:
    """根据离线用户名生成标准 UUID（与官方离线模式一致）。"""
    digest = hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest()
    b = bytearray(digest)
    b[6] = (b[6] & 0x0F) | 0x30  # version 3
    b[8] = (b[8] & 0x3F) | 0x80  # variant 1
    return dashed_uuid(b.hex())


def format_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return "?"


# ---------------------------------------------------------------- 压缩包

def safe_extract_zip(zip_path, dest):
    """解压 zip，带 zip-slip 防护；符号链接条目真正跳过（不走 extractall）。"""
    dest = Path(dest)
    ensure_dir(dest)
    dest_root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest_root) + os.sep) and target != dest_root:
                raise ValueError(f"压缩包包含非法路径: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                log.warning("压缩包中的符号链接被跳过: %s", info.filename)
                continue
            if info.is_dir() or info.filename.endswith("/"):
                ensure_dir(target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def safe_extract_targz(path, dest):
    """解压 tar.gz，带路径穿越防护（兼容 Python 3.9+）。"""
    dest = Path(dest)
    ensure_dir(dest)
    with tarfile.open(path, "r:gz") as tf:
        members = []
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep) and target != dest.resolve():
                raise ValueError(f"压缩包包含非法路径: {member.name}")
            members.append(member)
        for member in members:
            if member.issym() or member.islnk():
                continue  # 跳过符号/硬链接，避免安全问题
            tf.extract(member, dest)


def find_executable(root: Path, name_hint=None) -> Path:
    """在目录树中查找 java 可执行文件。"""
    names = [name_hint] if name_hint else ["java.exe", "java", "javaw.exe"]
    for sub in ("bin", "jre/bin", "jre\\bin", ""):
        base = Path(root) / sub if sub else Path(root)
        for n in names:
            p = base / n
            if p.is_file():
                return p
    skip = {"legal", "lib", "include", "man", "sample", "src", "jmods"}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith(".")]
        for f in files:
            if f in names:
                return Path(base) / f
    return None


# ---------------------------------------------------------------- Maven 坐标

def parse_maven_name(name: str):
    """解析 Maven 坐标 group:artifact:version[:classifier]，返回四元组。"""
    parts = name.split(":")
    if len(parts) < 3:
        raise ValueError(f"非法 Maven 坐标: {name}")
    return parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else None


def maven_artifact_path(name: str, suffix="jar") -> str:
    """把 Maven 坐标转成仓库相对路径。"""
    group, artifact, version, classifier = parse_maven_name(name)
    base = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}"
    if classifier:
        base += f"-{classifier}"
    return base + "." + suffix


# ---------------------------------------------------------------- 占位符替换

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def replace_placeholders(text: str, mapping: dict) -> str:
    """替换 ${key}；未知 key 保留原样。"""
    def _rep(m):
        key = m.group(1)
        if key in mapping and mapping[key] is not None:
            return str(mapping[key])
        return m.group(0)
    return _PLACEHOLDER.sub(_rep, text)


def has_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.search(text))


# ---------------------------------------------------------------- 规则判断

def check_rules(rules, features=None) -> bool:
    """判断 version JSON 中的 rules 数组是否允许当前平台。"""
    if not rules:
        return True
    features = features or {}
    allow = False
    for rule in rules:
        matched = True
        if "os" in rule:
            os_def = rule["os"]
            if "name" in os_def and os_def["name"] != OS_NAME:
                matched = False
            if "arch" in os_def and os_def["arch"] != ARCH:
                matched = False
            if "version" in os_def:
                try:
                    pat = os_def["version"]
                    # 官方语义为全串匹配；旧 JSON 中也有不带 $ 的前缀锚定写法，两者都接受
                    if not (re.match(pat, OS_VERSION) or re.fullmatch(pat, OS_VERSION)):
                        matched = False
                except re.error:
                    matched = False
        if "features" in rule and matched:
            for fk, fv in rule["features"].items():
                if bool(features.get(fk)) != bool(fv):
                    matched = False
        if matched:
            allow = rule.get("action", "allow") == "allow"
    return allow


# ---------------------------------------------------------------- 子进程

def run_process(cmd, cwd=None, on_line=None, timeout=None, env=None) -> int:
    """运行子进程并转发输出，返回退出码。"""
    import subprocess
    import threading

    log.debug("执行命令: %s", " ".join(map(str, cmd)))
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def _reader():
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        pass
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1
    finally:
        t.join(timeout=5)


# ---------------------------------------------------------------- 日志

log = logging.getLogger(APP_NAME)
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False
