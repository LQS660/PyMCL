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


def include_docs(root: Path, stage: Path) -> None:
    """把 AI 网关搭建说明放进载荷，供 AI 报错文案指向。

    默认 stage 只拷 ui/ 与 native/，ai_gateway/README.md 不在其中；client.py 的报错
    会引导用户看说明文档，文件必须在包里用户才找得到。README.md 不是 .py，不违反
    「载荷不含 .py」的出包断言。
    """
    src = root / "ai_gateway" / "README.md"
    if not src.is_file():
        print("[warn] ai_gateway/README.md 不存在，跳过（报错文案会指向项目主页）")
        return
    dest = stage / "ai_gateway" / "README.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print("[docs] 已放入 ai_gateway/README.md")


def strip_bridge(stage: Path) -> None:
    """只剥打包目录里 C 桥副本的符号表：native/build.bat 没带 -s，符号表占了 exe 一半多。原件不动。

    strip 缺失只警告不中断：Windows 裸机默认既没有 C:\\msys64\\...\\strip.exe 也没有
    PATH 上的 strip，旧版 check_call 会在这里抛 FileNotFoundError，让打包在最后一步前失败。
    """
    exe = stage / "native" / "build" / "pymcl-bridge.exe"
    if not exe.is_file():
        return
    strip = str(STRIP) if STRIP.exists() else shutil.which("strip")
    if not strip:
        print("[warn] 找不到 strip（C:\\msys64\\mingw64\\bin\\strip.exe 与 PATH 都没有），跳过符号剥离，"
              "产物体积会偏大但不影响功能")
        return
    # strip 中途失败会在目标目录留下自己的临时文件（GNU strip 的 stXXXXXX），
    # 而 stage 目录随后整个被打进载荷 —— 不能让它进包。先记录目录内容，失败后清掉新增项。
    before = set(exe.parent.iterdir())
    try:
        subprocess.check_call([strip, "-s", str(exe)])
    except (OSError, subprocess.CalledProcessError) as e:
        for p in set(exe.parent.iterdir()) - before:
            try:
                p.unlink()
            except OSError:
                pass
        print(f"[warn] strip 失败（{type(e).__name__}: {e}），跳过符号剥离，继续打包")


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
    include_docs(root, stage)
    prune_cultures(stage / "ui")
    strip_bridge(stage)
    # 临时文件按 stage 名 + 进程 id 区分：_pack_net48.py 与 _pack_pcl_ui.py 的 PACK
    # 同为 pymcl-pack、stage.parent 相同，旧版固定名 payload.xz / stub.exe 会让两个
    # 打包并发/交叉执行时互相覆盖载荷，产出「MAGIC 校验能过但内容串台」的 exe。
    work = stage.parent
    tag = f"{stage.name}-{os.getpid()}"
    zpath = work / f"payload-{tag}.xz"
    stub = work / f"stub-{tag}.exe"
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
