# -*- coding: utf-8 -*-
import argparse
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

MAGIC = b"PML1PACK"
KEEP_CULTURES = {
    "zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh", "en", "en-US",
}
SEVEN = Path(r"C:\Program Files\7-Zip\7z.exe")
SEVEN_DLL = Path(r"C:\Program Files\7-Zip\7z.dll")


def prune_cultures(root: Path) -> None:
    for p in root.rglob("*"):
        if not p.is_dir():
            continue
        name = p.name
        if name in KEEP_CULTURES:
            continue
        # satellite folders look like "de", "fr", "ja", "pt-BR"
        if "-" in name or name.isalpha() and 2 <= len(name) <= 3:
            if any((p / x).exists() for x in (
                "Microsoft.Windows.ApplicationModel.Resources.dll",
                "Microsoft.Windows.ApplicationModel.Resources.pri",
                "PyMCL.WinUI.resources.dll",
            )) or list(p.glob("*.resources.dll")) or list(p.glob("*.pri")):
                shutil.rmtree(p, ignore_errors=True)


def drop_junk(root: Path) -> None:
    for pat in ("*.pdb", "*.xml", "createdump.exe"):
        for p in root.rglob(pat):
            try:
                p.unlink()
            except OSError:
                pass


def make_7z(stage: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    cmd = [
        str(SEVEN), "a", "-t7z",
        "-mx=9", "-m0=lzma2", "-mfb=273", "-md=32m", "-ms=on",
        str(dest), "*",
    ]
    subprocess.check_call(cmd, cwd=str(stage))


def zip_bundle(app7z: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as zf:
        zf.write(SEVEN, "tools/7z.exe", compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        zf.write(SEVEN_DLL, "tools/7z.dll", compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        zf.write(app7z, "app.7z", compress_type=zipfile.ZIP_STORED)


def zip_dir(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            zf.write(p, p.relative_to(src).as_posix())


def build_stub(root: Path, out: Path) -> None:
    gcc = Path(r"C:\msys64\mingw64\bin\gcc.exe")
    if not gcc.exists():
        gcc = Path("gcc")
    cmd = [
        str(gcc),
        "-O2",
        "-s",
        "-mwindows",
        "-municode",
        "-DUNICODE",
        "-D_UNICODE",
        "-o",
        str(out),
        str(root / "pack" / "stub.c"),
        str(root / "pack" / "zipmin.c"),
        "-lz",
        "-lshell32",
        "-lgdi32",
        "-luser32",
        "-lwininet",
        "-lws2_32",
    ]
    subprocess.check_call(cmd)


def append_payload(stub: Path, zpath: Path, dest: Path) -> None:
    data = zpath.read_bytes()
    dest.write_bytes(stub.read_bytes() + data + len(data).to_bytes(8, "little") + MAGIC)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--dist", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    stage = Path(args.stage)
    dist = Path(args.dist)
    dist.mkdir(parents=True, exist_ok=True)
    drop_junk(stage)
    prune_cultures(stage / "ui")
    work = stage.parent
    zpath = work / "payload.zip"
    stub = work / "stub.exe"
    if SEVEN.exists() and SEVEN_DLL.exists():
        app7z = work / "payload.7z"
        make_7z(stage, app7z)
        zip_bundle(app7z, zpath)
        try:
            app7z.unlink()
        except OSError:
            pass
    else:
        zip_dir(stage, zpath)
    build_stub(root, stub)
    append_payload(stub, zpath, dist / "PyMCL.exe")
    try:
        zpath.unlink()
        stub.unlink()
    except OSError:
        pass
    out = dist / "PyMCL.exe"
    print("OK", out, "bytes", out.stat().st_size)


if __name__ == "__main__":
    main()
