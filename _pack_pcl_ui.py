# -*- coding: utf-8 -*-
"""Pack WPF UI (PCL same stack) + C bridge. No WASDK, no Edge shell."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Downloads\新建文件夹 (5)").resolve()
DOTNET = Path(r"C:\Users\Administrator\dotnet\dotnet.exe")
if not DOTNET.exists():
    DOTNET = Path("dotnet")
PACK = Path(r"D:\pymcl-pack")
PUB = PACK / "publish-wpf"
STAGE = PACK / "pcl-ui-stage"
DIST = ROOT / "dist"
PY = Path(r"C:\Python312\python.exe")


def main():
    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "tmp").mkdir(exist_ok=True)
    os.environ["TEMP"] = str(PACK / "tmp")
    os.environ["TMP"] = str(PACK / "tmp")

    print("[1] publish WPF framework-dependent (PCL UI stack)")
    if PUB.exists():
        shutil.rmtree(PUB)
    subprocess.check_call(
        [
            str(DOTNET),
            "publish",
            str(ROOT / "wpf" / "PyMCL.Wpf" / "PyMCL.Wpf.csproj"),
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "false",
            "-p:PublishSingleFile=false",
            "-o",
            str(PUB),
        ],
        cwd=str(ROOT),
    )

    print("[2] stage ui + native bridge")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "ui").mkdir(parents=True)
    (STAGE / "native" / "build").mkdir(parents=True)
    (STAGE / "native" / "data").mkdir(parents=True)
    (STAGE / "native" / "tools").mkdir(parents=True)

    for p in PUB.iterdir():
        dest = STAGE / "ui" / p.name
        if p.is_dir():
            shutil.copytree(p, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(p, dest)

    bridge = ROOT / "native" / "build" / "pymcl-bridge.exe"
    if not bridge.exists():
        raise SystemExit("missing native/build/pymcl-bridge.exe — run native\\build.bat first")
    shutil.copy2(bridge, STAGE / "native" / "build")
    shutil.copy2(ROOT / "native" / "data" / "catalog.json", STAGE / "native" / "data")
    py_rpc = ROOT / "native" / "tools" / "py_rpc.py"
    if py_rpc.exists():
        shutil.copy2(py_rpc, STAGE / "native" / "tools")
    for d in [
        "libcurl-4.dll",
        "zlib1.dll",
        "libwinpthread-1.dll",
        "libssl-3-x64.dll",
        "libcrypto-3-x64.dll",
        "libzstd.dll",
        "libbrotlidec.dll",
        "libbrotlicommon.dll",
        "libnghttp2-14.dll",
        "libidn2-0.dll",
        "libpsl-5.dll",
        "libssh2-1.dll",
        "libiconv-2.dll",
        "libintl-8.dll",
        "libgcc_s_seh-1.dll",
        "curl-ca-bundle.crt",
    ]:
        src = ROOT / "native" / "build" / d
        if src.exists():
            shutil.copy2(src, STAGE / "native" / "build" / d)

    raw = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file())
    print(f"stage_mb={raw/1024/1024:.2f}")

    print("[3] pack stub")
    subprocess.check_call(
        [str(PY), str(ROOT / "pack" / "pack.py"), "--root", str(ROOT), "--stage", str(STAGE), "--dist", str(DIST)],
        cwd=str(ROOT),
    )
    exe = DIST / "PyMCL.exe"
    print(f"EXE={exe} bytes={exe.stat().st_size} MB={exe.stat().st_size/1024/1024:.2f}")
    print("NOTE: needs .NET 8 Desktop Runtime only (no Windows App Runtime / WASDK)")


if __name__ == "__main__":
    main()
