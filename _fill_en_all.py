# -*- coding: utf-8 -*-
"""全量补齐 mclauncher/locales/en.json（源码 tr() + zh_CN 对照表）。"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCALES = ROOT / "mclauncher" / "locales"
CJK = re.compile(r"[\u4e00-\u9fff]")

# 手工优先译文（覆盖长句 / 易错词）
EXTRA: dict[str, str] = {
    "删除世界存档": "Delete world save",
    "删除确认": "Confirm deletion",
    "建议先在「存档管理」里备份。": "Consider backing up in Save Manager first.",
    "永久删除": "Delete permanently",
    "扫描中…": "Scanning…",
    "检测中…": "Checking…",
    "检测失败": "Check failed",
    "清理中…": "Cleaning…",
    "清理失败": "Cleanup failed",
    "清除已完成": "Clear finished",
    "游戏目录无效": "Invalid game directory",
    "服务器列表": "Server list",
    "实例": "Instance",
    "添加服务器": "Add server",
    "编辑": "Edit",
    "删除": "Delete",
    "导入": "Import",
    "导出": "Export",
    "游玩时长": "Playtime",
    "清除记录": "Clear records",
    "反馈": "Feedback",
    "发送反馈": "Send feedback",
    "附带本机配置": "Include system info",
    "本机配置预览": "System info preview",
    "登录中…": "Signing in…",
    "登录皮肤站": "Sign in to skin server",
    "登录通行证": "Sign in with pass",
    "删除账号": "Delete account",
    "取消": "Cancel",
    "版本列表加载失败": "Failed to load version list",
    "扫描 Java 失败": "Failed to scan Java",
    "未知错误": "Unknown error",
    "未检测到 Java，请从下方下载": "No Java detected. Download one below.",
    "还没有游玩记录\n启动游戏后会自动记录": "No playtime yet.\nIt will be recorded after you launch the game.",
    "发给开发者。第一次打开需手动同意后才会上传；可附带本机配置。": (
        "Send to the developer. First use requires consent before upload; system info can be attached."
    ),
    "联系方式（QQ / 邮箱，可选）": "Contact (QQ / email, optional)",
    "标题，例如：1.20.1 Fabric 启动黑屏": "Title, e.g. 1.20.1 Fabric black screen on launch",
    "发生了什么、怎么复现、期望结果。崩溃可直接从崩溃窗口点「发送给开发者」。": (
        "What happened, how to reproduce, and the expected result. For crashes, use Send to developer in the crash dialog."
    ),
}


def source_keys() -> set[str]:
    keys: set[str] = set()
    for src in sorted((ROOT / "app").rglob("*.py")):
        try:
            tree = ast.parse(src.read_bytes())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def load_json(name: str) -> dict:
    path = LOCALES / name
    if not path.is_file():
        return {}
    return json.loads(path.read_text("utf-8"))


def dump_json(name: str, data: dict) -> None:
    path = LOCALES / name
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: data[k] for k in sorted(data)}
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", "utf-8")


def rule_translate(text: str) -> str:
    pairs = [
        ("启动器", "Launcher"), ("启动", "Launch"), ("实例", "Instance"),
        ("版本", "Version"), ("模组", "Mod"), ("整合包", "Modpack"),
        ("资源包", "Resource pack"), ("光影", "Shader"), ("世界", "World"),
        ("存档", "Save"), ("备份", "Backup"), ("账号", "Account"),
        ("设置", "Settings"), ("下载", "Download"), ("安装", "Install"),
        ("卸载", "Uninstall"), ("删除", "Delete"), ("添加", "Add"),
        ("编辑", "Edit"), ("刷新", "Refresh"), ("搜索", "Search"),
        ("取消", "Cancel"), ("确定", "OK"), ("保存", "Save"),
        ("失败", " failed"), ("成功", " succeeded"), ("加载", "Load"),
        ("扫描", "Scan"), ("清理", "Clean"), ("清除", "Clear"),
        ("登录", "Sign in"), ("离线", "Offline"), ("正版", "Microsoft"),
        ("服务器", "Server"), ("联机", "Multiplayer"), ("反馈", "Feedback"),
        ("崩溃", "Crash"), ("内存", "Memory"), ("分辨率", "Resolution"),
        ("主题", "Theme"), ("语言", "Language"), ("自动", "Auto"),
        ("手动", "Manual"), ("默认", "Default"), ("全部", "All"),
        ("无", "None"), ("是", "Yes"), ("否", "No"), ("请", "Please "),
        ("中…", "…"), ("……", "…"),
    ]
    out = text
    for zh, en in pairs:
        out = out.replace(zh, en)
    return out


def try_google(batch: list[str]) -> dict[str, str]:
    try:
        from deep_translator import GoogleTranslator  # type: ignore
    except Exception:
        return {}
    out: dict[str, str] = {}
    tr = GoogleTranslator(source="zh-CN", target="en")
    for src in batch:
        try:
            dst = tr.translate(src)
            if dst and isinstance(dst, str):
                out[src] = dst
        except Exception:
            pass
    return out


def main() -> int:
    # 可选机翻
    try:
        import deep_translator  # noqa: F401
    except Exception:
        print("pip install deep-translator ...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "deep-translator"])

    keys = source_keys()
    zh = load_json("zh_CN.json")
    en = load_json("en.json")

    # 合并 catalog 里的 NEW_EN（若存在）
    try:
        sys.path.insert(0, str(ROOT))
        from _i18n_catalog import NEW_EN  # type: ignore
        EXTRA.update(NEW_EN)
    except Exception:
        pass

    catalog = sorted(keys | set(zh) | set(en) | set(EXTRA))
    zh_out = {k: (zh.get(k) or k) for k in catalog}

    need = [
        k for k in catalog
        if CJK.search(k) and (k not in en or not en.get(k) or en.get(k) == k) and k not in EXTRA
    ]
    print(f"need machine/rule translate: {len(need)}")
    machine = try_google(need) if need else {}
    print(f"machine translated: {len(machine)}")

    en_out = dict(en)
    added = 0
    for k in catalog:
        cur = en_out.get(k)
        if cur and (cur != k or not CJK.search(k)):
            continue
        if k in EXTRA:
            en_out[k] = EXTRA[k]
        elif k in machine:
            en_out[k] = machine[k]
        elif not CJK.search(k):
            en_out[k] = k
        else:
            en_out[k] = rule_translate(k)
        added += 1

    dump_json("zh_CN.json", zh_out)
    dump_json("en.json", en_out)

    still_cjk = sum(1 for k in keys if CJK.search(en_out.get(k, "")))
    print(f"source tr(): {len(keys)}")
    print(f"zh_CN: {len(zh_out)}")
    print(f"en: {len(en_out)} (filled ~{added})")
    print(f"en values still containing CJK (for source keys): {still_cjk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
