# -*- coding: utf-8 -*-
from pathlib import Path
import shutil
import subprocess
import os

root = Path(r"C:\Users\Administrator\Downloads\新建文件夹 (5)").resolve()
pack = Path(r"D:\pymcl-pack")
slim = pack / "slim-stage"
dist = root / "dist"

if slim.exists():
    shutil.rmtree(slim)
(slim / "www").mkdir(parents=True)
(slim / "native" / "build").mkdir(parents=True)
(slim / "native" / "data").mkdir(parents=True)
(slim / "native" / "tools").mkdir(parents=True)

shutil.copytree(root / "eziapp" / "dist", slim / "www", dirs_exist_ok=True)
# C 桥动态生成 bridge-config.json；删掉静态占位，避免缓存干扰
cfg = slim / "www" / "bridge-config.json"
if cfg.exists():
    cfg.unlink()
shutil.copy2(root / "native" / "build" / "pymcl-bridge.exe", slim / "native" / "build")
shutil.copy2(root / "native" / "data" / "catalog.json", slim / "native" / "data")
py_rpc = root / "native" / "tools" / "py_rpc.py"
if py_rpc.exists():
    shutil.copy2(py_rpc, slim / "native" / "tools")

dlls = [
    "libcurl-4.dll", "zlib1.dll", "libwinpthread-1.dll", "libssl-3-x64.dll",
    "libcrypto-3-x64.dll", "libzstd.dll", "libbrotlidec.dll", "libbrotlicommon.dll",
    "libnghttp2-14.dll", "libidn2-0.dll", "libpsl-5.dll", "libssh2-1.dll",
    "libiconv-2.dll", "libintl-8.dll", "libgcc_s_seh-1.dll", "curl-ca-bundle.crt",
]
for d in dlls:
    src = root / "native" / "build" / d
    if src.exists():
        shutil.copy2(src, slim / "native" / "build" / d)

raw = sum(p.stat().st_size for p in slim.rglob("*") if p.is_file())
print(f"stage_bytes={raw} MB={raw/1024/1024:.2f}")

tmp = pack / "tmp"
tmp.mkdir(exist_ok=True)
os.environ["TEMP"] = str(tmp)
os.environ["TMP"] = str(tmp)

subprocess.check_call(
    [r"C:\Python312\python.exe", str(root / "pack" / "pack.py"), "--root", str(root), "--stage", str(slim), "--dist", str(dist)],
    cwd=str(root),
)
exe = dist / "PyMCL.exe"
print(f"EXE={exe} bytes={exe.stat().st_size} MB={exe.stat().st_size/1024/1024:.2f}")
under = exe.stat().st_size <= 5 * 1024 * 1024
print("UNDER_5MB" if under else "OVER_5MB")
