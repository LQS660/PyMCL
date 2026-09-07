# -*- coding: utf-8 -*-
"""把源码里新出现、语言包还没有的词条补进 zh_CN / en。

`test_pcl_quality.py` 要求 zh_CN 覆盖 app/ 下全部 tr() 字面量，
新增 UI 文案时忘了同步语言包就会红。跑一次本脚本即可对齐。
"""
import ast
import json
from pathlib import Path

EN = {
    "删除世界存档": "Delete world save",
    "删除确认": "Confirm deletion",
    "建议先在「存档管理」里备份。": "Consider making a backup in Save Manager first.",
    "永久删除": "Delete permanently",
    "扫描中…": "Scanning...",
    "检测中…": "Checking...",
    "检测失败": "Check failed",
    "清理中…": "Cleaning...",
    "清理失败": "Cleanup failed",
    "清除已完成": "Clear finished",
    "游戏目录无效": "Invalid game directory",
}


def source_keys() -> set[str]:
    keys = set()
    for src in sorted(Path("app").rglob("*.py")):
        tree = ast.parse(src.read_bytes())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def main() -> int:
    base = Path("mclauncher/locales")
    zh_path, en_path = base / "zh_CN.json", base / "en.json"
    zh = json.loads(zh_path.read_text("utf-8"))
    en = json.loads(en_path.read_text("utf-8"))

    for key in sorted(source_keys()):
        zh.setdefault(key, key)
        if key in EN:
            en.setdefault(key, EN[key])

    zh_path.write_text(json.dumps(dict(sorted(zh.items())), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    en_path.write_text(json.dumps(dict(sorted(en.items())), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    missing_en = sorted(k for k in source_keys() if k not in en)
    print(f"zh_CN entries: {len(zh)} | en entries: {len(en)}")
    print(f"still untranslated in en: {len(missing_en)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
