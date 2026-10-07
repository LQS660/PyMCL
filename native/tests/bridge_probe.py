# -*- coding: utf-8 -*-
"""P0-5 / P0-6 / P1-13 的端到端验证：起真 C 桥，走真 HTTP。

  P0-5  set_version_isolation 传带 `&` 的版本名 → 旧版经 cmd.exe 注入，会写出文件
  P0-6  GET /C:/Windows/win.ini（不带 token）→ 旧版原样返回系统文件
  P1-13 POST /rpc save_settings 提交 14 个键 → 旧版只落 8 个 + ui_*

用法：python native/tests/bridge_probe.py <bridge.exe> <root> [--expect-fixed]
  --expect-fixed：断言修复后的行为（注入不生效 / 越权读失败 / 14 键全部落盘）
  不带：只打印实测，供人工对比（用在旧 exe 上）
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

EXE = sys.argv[1]
ROOT = os.path.abspath(sys.argv[2])
FIXED = "--expect-fixed" in sys.argv

INJ_FILE = os.path.join(ROOT, "INJECTED_BY_CMD.txt")
if os.path.exists(INJ_FILE):
    os.unlink(INJ_FILE)

token = secrets.token_urlsafe(32)
proc = subprocess.Popen(
    [EXE, "--root", ROOT, "--host", "127.0.0.1", "--port", "0", "--token", token],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    encoding="utf-8", errors="replace", cwd=ROOT,
)
line = proc.stdout.readline().strip()
print("BOOT:", line)
port = None
for part in line.split():
    if part.startswith("port="):
        port = int(part.split("=", 1)[1])
if not port:
    proc.kill()
    raise SystemExit("no port in banner: " + line)
base = f"http://127.0.0.1:{port}"
hdr = {"Content-Type": "application/json", "X-PyMCL-Bridge-Token": token}
results = {}


def rpc(method, params=None, timeout=120):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(base + "/rpc", data=body, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------------- P0-5 命令注入 ----------------
# 版本名里的 & 让旧版的 `cmd /c mklink /J <link> <target>` 把后半截当新命令执行。
# 名字里不带空格，旧 quote_arg 不会加引号，payload 直接生效。
payload = f"x&whoami>{INJ_FILE}&y"
print(f"\n=== P0-5 payload 版本名 = {payload!r} ===")
# 先造出这个版本目录（set_version_isolation 要求版本存在）
vdir = os.path.join(ROOT, ".minecraft", "versions", "MyVersion")
try:
    r = rpc("set_version_isolation", {"instance": "default", "version": payload, "mode": "mods"})
    print("set_version_isolation ->", json.dumps(r, ensure_ascii=False)[:200])
except Exception as e:  # noqa: BLE001
    print("set_version_isolation EXC:", e)
time.sleep(1.5)
inj_exists = os.path.exists(INJ_FILE)
print(f"INJECTION FILE CREATED = {inj_exists}  ({INJ_FILE})")
results["P0-5 injection file created"] = inj_exists
if inj_exists:
    os.unlink(INJ_FILE)

# ---------------- P0-6 未认证任意文件读 ----------------
print("\n=== P0-6 未认证任意文件读 ===")
for target in ("/C:/Windows/win.ini", "/C:/Windows/System32/drivers/etc/hosts",
               "/../config.json", "/sub/../config.json"):
    url = base + target
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    except Exception as e:  # noqa: BLE001
        body, code = str(e).encode(), 0
    leaked = code == 200 and b"[fonts]" in body or (code == 200 and b"PYMCL" not in body and len(body) > 0)
    print(f"GET {target:42s} -> HTTP {code} len={len(body)} body[:60]={body[:60]!r}")
    results[f"P0-6 {target}"] = code
# 对照组：带 token 且文件确实在 www/ 下的正常静态资源（如果 root 里有 www）
www_idx = os.path.join(ROOT, "www", "index.html")
if os.path.exists(www_idx):
    try:
        with urllib.request.urlopen(base + "/index.html", timeout=20) as r:
            print(f"GET /index.html (对照) -> HTTP {r.status} len={len(r.read())}")
    except Exception as e:  # noqa: BLE001
        print("GET /index.html (对照) EXC:", e)

# ---------------- P1-13 save_settings 键白名单 ----------------
print("\n=== P1-13 save_settings 14 键 ===")
MISSING_14 = {
    "ai_mode": "custom",
    "ai_api_key": "sk-test-key-123",
    "ai_base_url": "https://api.example.com/v1",
    "ai_model": "my-model-x",
    "ai_gateway_url": "https://gw.example.com",
    "launcher_visibility": "hide",
    "gc_preset": "zgc",
    "download_source": "bmclapi",
    "download_limit_kbps": 4321,
    "homepage_mode": "custom",
    "custom_homepage": "https://home.example.com",
    "auto_check_update": False,
    "default_isolation": "mods",
    "default_jvm_args": "-XX:+UseG1GC -Xmx2G",
}
r = rpc("save_settings", {"data": MISSING_14})
print("save_settings ->", json.dumps(r, ensure_ascii=False)[:120])

cfg_path = os.path.join(ROOT, "config.json")
with open(cfg_path, encoding="utf-8") as f:
    cfg = json.load(f)
print(f"\n落盘检查 ({cfg_path}):")
ok = 0
for k, want in MISSING_14.items():
    got = cfg.get(k, "<MISSING>")
    hit = got == want
    ok += hit
    print(f"  {'OK  ' if hit else 'MISS'} {k:24s} want={want!r:32s} got={got!r}")
print(f"落盘 {ok}/{len(MISSING_14)}")

back = rpc("get_settings")
bs = back.get("result") or {}
print("\nget_settings 回读：")
ok2 = 0
for k, want in MISSING_14.items():
    got = bs.get(k, "<MISSING>")
    hit = got == want
    ok2 += hit
    print(f"  {'OK  ' if hit else 'MISS'} {k:24s} want={want!r:32s} got={got!r}")
print(f"回读 {ok2}/{len(MISSING_14)}")
results["P1-13 persisted"] = ok
results["P1-13 roundtrip"] = ok2

proc.kill()
proc.wait(timeout=10)

print("\n================ 汇总 ================")
for k, v in results.items():
    print(f"{k}: {v}")
if FIXED:
    bad = []
    if results["P0-5 injection file created"]:
        bad.append("P0-5 注入仍然生效")
    if results.get("P0-6 /C:/Windows/win.ini") == 200:
        bad.append("P0-6 仍能未认证读绝对路径")
    if results["P1-13 persisted"] != len(MISSING_14):
        bad.append(f"P1-13 落盘 {results['P1-13 persisted']}/{len(MISSING_14)}")
    if results["P1-13 roundtrip"] != len(MISSING_14):
        bad.append(f"P1-13 回读 {results['P1-13 roundtrip']}/{len(MISSING_14)}")
    print("VERDICT:", "FAIL — " + "; ".join(bad) if bad else "PASS")
    sys.exit(1 if bad else 0)
