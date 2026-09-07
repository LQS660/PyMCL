# -*- coding: utf-8 -*-
"""找出「会被写进 config.json、但重启后必然丢失」的配置键。

`Config.save()` 落盘的是整份 `self.data`，而 `Config.load()` 只按
`DEFAULT_CONFIG` 的键名回读 —— 任何没在 DEFAULT_CONFIG 里声明过的键
都是「这次改了有效、重开启动器就没了」。
"""
import ast
from pathlib import Path

from mclauncher.config import DEFAULT_CONFIG

WRITE_CALLS = {"set", "update"}


def written_keys(path: Path) -> set[str]:
    """收集 CONFIG.set("k", ...) 与 CONFIG.update({...}) 里出现的字面量键名。"""
    keys: set[str] = set()
    tree = ast.parse(path.read_bytes())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Name) and target.id == "CONFIG"):
            continue
        if node.func.attr not in WRITE_CALLS or not node.args:
            continue
        arg = node.args[0]
        if node.func.attr == "set" and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            keys.add(arg.value)
        elif node.func.attr == "update" and isinstance(arg, ast.Dict):
            for k in arg.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def main() -> int:
    roots = [Path("app"), Path("bridge"), Path("mclauncher")]
    found: dict[str, set[str]] = {}
    for root in roots:
        for src in sorted(root.rglob("*.py")):
            for key in written_keys(src):
                found.setdefault(key, set()).add(str(src))

    orphans = {k: v for k, v in found.items() if k not in DEFAULT_CONFIG}
    print(f"CONFIG 写入的键共 {len(found)} 个，DEFAULT_CONFIG 声明了 {len(DEFAULT_CONFIG)} 个")
    if not orphans:
        print("没有会丢失的键")
        return 0
    print(f"\n重启后会丢失的键（{len(orphans)} 个）：")
    for key in sorted(orphans):
        print(f"  {key:<28} 写入处: {', '.join(sorted(orphans[key]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
