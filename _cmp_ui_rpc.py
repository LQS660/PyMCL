from pathlib import Path
import re
root = Path(r"c:\Users\Administrator\Downloads\新建文件夹 (5)")
# WinUI Rpc calls
cs = list((root/"winui3").rglob("*.cs"))
calls=set()
for p in cs:
    t=p.read_text(encoding="utf-8", errors="replace")
    calls |= set(re.findall(r'RpcAsync(?:<[^>]+>)?\(\s*"([a-z][a-z0-9_]*)"', t))
    calls |= set(re.findall(r'\.Call(?:Async)?\(\s*"([a-z][a-z0-9_]*)"', t))
    calls |= set(re.findall(r'method:\s*"([a-z][a-z0-9_]*)"', t))
print("WinUI unique RPC:", len(calls))
for m in sorted(calls): print(m)
be=(root/"native/src/backend.c").read_text(encoding="utf-8", errors="replace")
c=set(re.findall(r'strcmp\(\s*method\s*,\s*"([a-z][a-z0-9_]+)"\s*\)', be))
miss=sorted(calls-c)
print("\nWinUI missing in C:", len(miss))
for m in miss: print("-", m)
# eziapp
ts=list((root/"eziapp/src").rglob("*.ts"))
ecalls=set()
for p in ts:
    t=p.read_text(encoding="utf-8", errors="replace")
    ecalls |= set(re.findall(r'rpc\(\s*[\'"]([a-z][a-z0-9_]*)[\'"]', t))
    ecalls |= set(re.findall(r'\.call\(\s*[\'"]([a-z][a-z0-9_]*)[\'"]', t))
print("\neziapp RPC:", len(ecalls))
emiss=sorted(ecalls-c)
print("eziapp missing in C:", len(emiss))
for m in emiss: print("-", m)
