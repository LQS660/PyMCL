from pathlib import Path
import re
root = Path(r"c:\Users\Administrator\Downloads\新建文件夹 (5)")
calls=set()
for p in (root/"winui3/PyMCL.WinUI").rglob("*.cs"):
    t=p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'(?:CallAsync(?:<[^>]+>)?|StartTaskAsync)\(\s*"([a-z][a-z0-9_]*)"', t):
        calls.add(m.group(1))
# enums for search/install
t=(root/"winui3/PyMCL.WinUI/Models/Models.cs").read_text(encoding="utf-8", errors="replace")
calls |= set(re.findall(r'SearchMethod\s*=>\s*"([a-z_]+)"', t))
calls |= set(re.findall(r'InstallMethod\s*=>\s*"([a-z_]+)"', t))
be=(root/"native/src/backend.c").read_text(encoding="utf-8", errors="replace")
c=set(re.findall(r'strcmp\(\s*method\s*,\s*"([a-z][a-z0-9_]+)"\s*\)', be))
miss=sorted(calls-c)
print("total",len(calls),"miss",len(miss))
print("\n".join(miss))
