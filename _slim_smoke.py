# -*- coding: utf-8 -*-
import json, os, secrets, shutil, subprocess, tempfile, urllib.request
from pathlib import Path

root = Path(r"C:\Users\Administrator\Downloads\新建文件夹 (5)")
exe = root / "native" / "build" / "pymcl-bridge.exe"
td = Path(tempfile.mkdtemp())
try:
    shutil.copytree(root / "eziapp" / "dist", td / "www")
    (td / "native" / "data").mkdir(parents=True)
    shutil.copy2(root / "native" / "data" / "catalog.json", td / "native" / "data" / "catalog.json")
    token = secrets.token_urlsafe(32)
    p = subprocess.Popen(
        [str(exe), "--root", str(td), "--host", "127.0.0.1", "--port", "0", "--token", token],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    line = p.stdout.readline().strip()
    print("BOOT", line)
    port = int([x for x in line.split() if x.startswith("port=")][0].split("=", 1)[1])
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read(200)
    cfg = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/bridge-config.json", timeout=5).read())
    print("html_snip", html[:60])
    print("cfg_ok", cfg.get("token") == token and "127.0.0.1" in cfg.get("rpc_url", ""))
    p.terminate()
finally:
    shutil.rmtree(td, ignore_errors=True)

exe_path = root / "dist" / "PyMCL.exe"
print("exe_mb", round(exe_path.stat().st_size / 1024 / 1024, 2))
