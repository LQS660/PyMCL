from pathlib import Path
import re
root = Path(r"c:\Users\Administrator\Downloads\新建文件夹 (5)/winui3/PyMCL.WinUI")
calls=set()
for p in root.rglob("*.cs"):
    t=p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'(?:Rpc|Invoke|Call)(?:Async)?(?:<[^>]+>)?\(\s*"([^"]+)"', t):
        calls.add(m.group(1))
    for m in re.finditer(r'client\.(?:Get|Post|Call)\w*\(\s*"([^"]+)"', t):
        calls.add(m.group(1))
    # Bridge.Call("x"
    for m in re.finditer(r'Bridge\w*\.\w+\(\s*"([a-z][a-z0-9_]*)"', t):
        calls.add(m.group(1))
print(len(calls))
print("\n".join(sorted(calls)))
