from pathlib import Path
import re
root = Path(r"c:\Users\Administrator\Downloads\新建文件夹 (5)")
calls=set()
for p in (root/"winui3/PyMCL.WinUI").rglob("*.cs"):
    t=p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'CallAsync(?:<[^>]+>)?\(\s*"([a-z][a-z0-9_]*)"', t):
        calls.add(m.group(1))
    for m in re.finditer(r'StartTaskAsync\(\s*"([a-z][a-z0-9_]*)"', t):
        calls.add(m.group(1))
# CatalogPage SearchMethod / InstallMethod
for p in (root/"winui3/PyMCL.WinUI").rglob("*.cs"):
    t=p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'(?:Search|Install)Method\s*=\s*"([a-z][a-z0-9_]*)"', t):
        calls.add(m.group(1))
    for m in re.finditer(r'"([a-z]+_(?:mods|modpacks|shaders|resourcepacks|datapacks|worlds|java))"', t):
        calls.add(m.group(1))
be=(root/"native/src/backend.c").read_text(encoding="utf-8", errors="replace")
c=set(re.findall(r'strcmp\(\s*method\s*,\s*"([a-z][a-z0-9_]+)"\s*\)', be))
print("WINUI CALLS", len(calls))
for m in sorted(calls):
    mark = "OK" if m in c else "MISS"
    print(f"  [{mark}] {m}")
print("MISS COUNT", len(calls-c))
