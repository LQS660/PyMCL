import re, pathlib
root = pathlib.Path(r"c:\Users\Administrator\Downloads\新建文件夹 (5)")
api = (root/"bridge"/"api.py").read_text(encoding="utf-8")
be = (root/"native"/"src"/"backend.c").read_text(encoding="utf-8", errors="replace")
# Python: look for METHOD handlers like "name": handler or dispatch cases
py_methods = set(re.findall(r'["\']([a-z][a-z0-9_]{2,})["\']\s*:\s*(?:self\.)?[a-z_]+', api))
# also from @rpc or METHODS list
py_methods |= set(re.findall(r'method\s*==\s*["\']([a-z][a-z0-9_]+)["\']', api))
py_methods |= set(re.findall(r'["\']method["\']\s*:\s*["\']([a-z][a-z0-9_]+)["\']', api))
# BridgeApi class methods that are public RPC
funcs = re.findall(r'^\s{4}def\s+([a-z][a-z0-9_]*)\s*\(self', api, re.M)
# C: strcmp(method, "xxx")
c_methods = set(re.findall(r'strcmp\(\s*method\s*,\s*"([a-z][a-z0-9_]+)"\s*\)', be))
c_methods |= set(re.findall(r'strcmp\(\s*"([a-z][a-z0-9_]+)"\s*,\s*method\s*\)', be))
print("C methods:", len(c_methods))
for m in sorted(c_methods):
    print(" C", m)
print("Py BridgeApi defs:", len(funcs))
for m in sorted(funcs):
    print(" P", m)
miss = sorted(set(funcs) - c_methods)
extra = sorted(c_methods - set(funcs))
print("MISSING in C:", len(miss))
for m in miss: print(" -", m)
print("EXTRA in C:", len(extra))
for m in extra: print(" +", m)
