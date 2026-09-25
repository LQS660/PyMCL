# -*- coding: utf-8 -*-
import argparse
import io
import lzma
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

MAGIC = b"PML1PACK"
KEEP_CULTURES = {
    "zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh", "en", "en-US",
}
STRIP = Path(r"C:\msys64\mingw64\bin\strip.exe")


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


def strip_bridge(stage: Path) -> None:
    """只剥打包目录里 C 桥副本的符号表：native/build.bat 没带 -s，符号表占了 exe 一半多。原件不动。"""
    exe = stage / "native" / "build" / "pymcl-bridge.exe"
    if exe.is_file():
        subprocess.check_call([str(STRIP if STRIP.exists() else "strip"), "-s", str(exe)])


def xz_bundle(stage: Path, dest: Path) -> None:
    """仓储 zip 当容器（stub 里的 zipmin 直接解），整包再做一次 xz 固实压缩，stub 静态链 liblzma 边读边解。"""
    # 按扩展名排，同类文件挨在一起，固实压缩更小
    files = sorted((p for p in stage.rglob("*") if p.is_file()), key=lambda p: (p.suffix.lower(), p.as_posix()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for p in files:
            zf.write(p, p.relative_to(stage).as_posix())
    filters = [
        {"id": lzma.FILTER_X86},
        {"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": 1 << 23},
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(lzma.compress(buf.getvalue(), format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, filters=filters))


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
        # 静态链接：zipmin.c 要 zlib，默认会去链 zlib1.dll，于是这个「单文件」
        # exe 拷到别的机器上就是一句「找不到 zlib1.dll」。多 50 KB 换真单文件。
        "-static",
        "-o",
        str(out),
        str(root / "pack" / "stub.c"),
        str(root / "pack" / "zipmin.c"),
        "-llzma",
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
    strip_bridge(stage)
    work = stage.parent
    zpath = work / "payload.xz"
    stub = work / "stub.exe"
    xz_bundle(stage, zpath)
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
