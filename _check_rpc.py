"""校验 WinUI3 侧调用的 RPC 方法名在 Python 桥接层真实存在。

方法名是字符串字面量，写错了照样编译通过，只在运行时报「方法不存在」。
还原受损文件之后尤其要查这一项。顺带把整个 winui3 都扫一遍。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINUI = ROOT / "winui3" / "PyMCL.WinUI"

# 泛型实参可能自带尖括号（CallAsync<List<HelpArticle>>），所以放宽到「非左括号的任意串」
CALL_RE = re.compile(r'(?:CallAsync|StartTaskAsync)\s*(?:<[^(]*?>)?\s*\(\s*"([a-z0-9_]+)"')
DEF_RE = re.compile(r"^\s{4}def\s+([a-z_][a-z0-9_]*)\s*\(", re.MULTILINE)


def main():
    api = (ROOT / "bridge" / "api.py").read_text(encoding="utf-8", errors="replace")
    known = set(DEF_RE.findall(api))
    print(f"桥接层公开方法 {len(known)} 个")

    missing, seen = [], set()
    for path in sorted(WINUI.rglob("*.cs")):
        if any(p in ("obj", "bin") for p in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in CALL_RE.finditer(text):
            name = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            seen.add(name)
            if name not in known:
                missing.append((path.name, line, name))

    print(f"C# 侧调用到的方法 {len(seen)} 个")
    if missing:
        print("\n后端找不到的调用:")
        for f, line, name in missing:
            print(f"  {f}:{line}  ->  {name}")
    else:
        print("\n全部命中，无悬空调用")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
