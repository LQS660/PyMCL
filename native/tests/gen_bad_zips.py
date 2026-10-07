# -*- coding: utf-8 -*-
"""生成畸形 zip 喂给 native/tests/zip_harness.c（审计 02-native-c-bridge.md P0-2/3/4、P1-1/2）。

用法：python tests/gen_bad_zips.py <outdir>
产出：
  wrap_uncomp.zip    中央目录 uncomp=0xFFFFFFFF  → 旧版 malloc(0)+越界写
  bad_namelen.zip    中央目录 nl=65535 但 cd_size 只放 5 字节名字 → 旧版越界读
  abs_drive.zip      条目名 C:/... 绝对路径       → 旧版逃逸到 dest 之外
  abs_unc.zip        条目名 //host/share/... UNC  → 旧版逃逸到 dest 之外
  big_nrec.zip       110 字节但 EOCD nrec=65535   → 旧版 calloc 257 MB
  bomb.zip           高压缩比条目（约 1000:1）    → 旧版无上限解压
  ok.zip             正常 zip（对照组，必须解压成功）
"""
import os
import struct
import sys
import zipfile
import zlib


def _eocd(nrec, cd_size, cd_off):
    return struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, nrec, nrec, cd_size, cd_off, 0)


def _cd_entry(name, method, comp, uncomp, local_off, nl=None, el=0, cl=0):
    nl = len(name) if nl is None else nl
    return struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50, 20, 20, 0, method, 0, 0, 0, comp, uncomp,
        nl, el, cl, 0, 0, 0, local_off,
    ) + name


def _local(name, method, comp, uncomp, data):
    return struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0, 0, comp, uncomp,
        len(name), 0,
    ) + name + data


def wrap_uncomp(path):
    """P0-2：uncomp=0xFFFFFFFF。"""
    name = b"a.bin"
    raw = b"hello"
    comp = zlib.compress(raw)[2:-4]
    body = _local(name, 8, len(comp), 0xFFFFFFFF, comp)
    cd = _cd_entry(name, 8, len(comp), 0xFFFFFFFF, 0)
    with open(path, "wb") as f:
        f.write(body)
        f.write(cd)
        f.write(_eocd(1, len(cd), len(body)))


def bad_namelen(path):
    """P0-3：中央目录声明 nl=65535，实际只放 5 字节名字，cd_size 仅 51。"""
    name = b"a.bin"
    raw = b"hello"
    body = _local(name, 0, len(raw), len(raw), raw)
    cd = _cd_entry(name, 0, len(raw), len(raw), 0, nl=65535)
    with open(path, "wb") as f:
        f.write(body)
        f.write(cd)
        f.write(_eocd(1, len(cd), len(body)))


def abs_entry(path, arcname):
    """P0-4：条目名是绝对路径 / UNC。"""
    raw = b"ESCAPED"
    name = arcname.encode("utf-8")
    body = _local(name, 0, len(raw), len(raw), raw)
    cd = _cd_entry(name, 0, len(raw), len(raw), 0)
    with open(path, "wb") as f:
        f.write(body)
        f.write(cd)
        f.write(_eocd(1, len(cd), len(body)))


def big_nrec(path):
    """P1-1：110 字节的文件声明 65535 个条目。"""
    body = b"\x00" * 88
    cd = b""
    with open(path, "wb") as f:
        f.write(body)
        f.write(_eocd(65535, 0, len(body)))


def bomb(path, raw_size=200 * 1024 * 1024, ratio=1000):
    """P1-2：一个压缩比 ~1000:1 的条目。"""
    raw = b"\x00" * raw_size
    comp = zlib.compress(raw, 9)[2:-4]
    name = b"bomb.bin"
    body = _local(name, 8, len(comp), len(raw), comp)
    cd = _cd_entry(name, 8, len(comp), len(raw), 0)
    with open(path, "wb") as f:
        f.write(body)
        f.write(cd)
        f.write(_eocd(1, len(cd), len(body)))
    return len(comp), raw_size


def ok_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("hello.txt", "hello world")
        z.writestr("sub/inner.txt", "inner")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    p = lambda n: os.path.join(out, n)
    wrap_uncomp(p("wrap_uncomp.zip"))
    bad_namelen(p("bad_namelen.zip"))
    abs_entry(p("abs_drive.zip"), "C:/Windows/Temp/PYMCL_ESCAPED.txt")
    abs_entry(p("abs_unc.zip"), "//127.0.0.1/C$/Windows/Temp/PYMCL_ESCAPED2.txt")
    big_nrec(p("big_nrec.zip"))
    c, u = bomb(p("bomb.zip"))
    ok_zip(p("ok.zip"))
    for n in ("wrap_uncomp", "bad_namelen", "abs_drive", "abs_unc", "big_nrec", "bomb", "ok"):
        f = p(n + ".zip")
        print(f"{n}.zip {os.path.getsize(f)} bytes")
    print(f"bomb ratio = {u / c:.1f}x ({c} -> {u})")


if __name__ == "__main__":
    main()
