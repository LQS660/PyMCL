# -*- coding: utf-8 -*-
"""Pack native WinUI (framework-dependent, PCL-style) + C bridge. No Edge/www shell."""
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
PUB = PACK / "publish-fd"
STAGE = PACK / "native-ui-stage"
DIST = ROOT / "dist"
PY = Path(r"C:\Python312\python.exe")

DROP = {
    "Microsoft.Windows.Widgets.Projection.dll",
    "Microsoft.Windows.AI.Imaging.Projection.dll",
    "Microsoft.Windows.AI.Text.Projection.dll",
    "Microsoft.Windows.AI.ContentSafety.Projection.dll",
    "Microsoft.Windows.AI.Projection.dll",
    "Microsoft.Windows.PushNotifications.Projection.dll",
    "Microsoft.Windows.BadgeNotifications.Projection.dll",
    "Microsoft.Security.Authentication.OAuth.Projection.dll",
    "Microsoft.Windows.Management.Deployment.Projection.dll",
    "Microsoft.Windows.Media.Capture.Projection.dll",
    "Microsoft.Windows.Storage.Projection.dll",
    "Microsoft.Graphics.Imaging.Projection.dll",
}


def main():
    PACK.mkdir(parents=True, exist_ok=True)
    (PACK / "tmp").mkdir(exist_ok=True)
    os.environ["TEMP"] = str(PACK / "tmp")
    os.environ["TMP"] = str(PACK / "tmp")

    print("[1] publish WinUI framework-dependent (no WASDK in package)")
    if PUB.exists():
        shutil.rmtree(PUB)
    subprocess.check_call(
        [
            str(DOTNET),
            "publish",
            str(ROOT / "winui3" / "PyMCL.WinUI" / "PyMCL.WinUI.csproj"),
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "false",
            "-p:Platform=x64",
            "-p:PublishSingleFile=false",
            "-p:WindowsAppSDKSelfContained=false",
            "-p:WindowsPackageType=None",
            "-o",
            str(PUB),
        ],
        cwd=str(ROOT),
    )

    print("[2] stage ui + native bridge (no www/Edge)")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "ui").mkdir(parents=True)
    (STAGE / "native" / "build").mkdir(parents=True)
    (STAGE / "native" / "data").mkdir(parents=True)
    (STAGE / "native" / "tools").mkdir(parents=True)

    for p in PUB.iterdir():
        if p.name in DROP:
            continue
        dest = STAGE / "ui" / p.name
        if p.is_dir():
            shutil.copytree(p, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(p, dest)

    shutil.copy2(ROOT / "native" / "build" / "pymcl-bridge.exe", STAGE / "native" / "build")
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
    print("NOTE: needs .NET 8 Desktop Runtime + Windows App Runtime (like PCL uses system .NET)")


if __name__ == "__main__":
    main()
