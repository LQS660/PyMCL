# -*- coding: utf-8 -*-
"""CurseForge 文件列表最小冒烟测试（走启动器真实代码路径，不下载整合包本体）。

用法: python test_cf_api.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mclauncher.downloader import DownloadManager
from mclauncher.mods import cf_by_slug, cf_files
from mclauncher.modpack import resolve_cf_modpack_file


GTNH_ID = 252507
GTNH_SLUG = "gt-new-horizons"
STALE_ID = 223708  # 旧目录误写成 friendly-mobs


def _fail(msg):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def _ok(msg):
    print(f"[OK] {msg}")


def main():
    dm = DownloadManager(threads=2)

    print("===== 1) slug 解析 GTNH =====")
    hit = cf_by_slug(dm, GTNH_SLUG)
    if not hit or hit.get("id") != GTNH_ID:
        _fail(f"slug={GTNH_SLUG} 解析结果异常: {hit}")
    _ok(f"gt-new-horizons -> id={hit['id']} name={hit.get('name')!r} mainFileId={hit.get('mainFileId')}")

    print("\n===== 2) cf_files 文件列表 + downloadUrl =====")
    files = cf_files(dm, GTNH_ID, page_size=10)
    if not files:
        _fail("cf_files(252507) 返回空列表")
    missing = [f.get("id") for f in files if not f.get("downloadUrl") or not f.get("fileName")]
    if missing:
        _fail(f"以下文件缺少 fileName/downloadUrl: {missing[:5]}")
    f0 = files[0]
    _ok(f"共 {len(files)} 个文件，最新: id={f0.get('id')} name={f0.get('fileName')}")
    _ok(f"downloadUrl={f0.get('downloadUrl')}")

    print("\n===== 3) 错误 addon_id + 正确 slug（复现用户安装路径）=====")
    info = resolve_cf_modpack_file(dm, STALE_ID, cf_slug=GTNH_SLUG)
    if info.get("addon_id") != GTNH_ID:
        _fail(f"未纠正错误 ID {STALE_ID}，得到 {info}")
    if not info.get("file_id") or not info.get("downloadUrl"):
        _fail(f"未拿到文件/下载地址: {info}")
    _ok(f"纠正 {STALE_ID} -> {info['addon_id']}")
    _ok(f"选中文件 {info.get('fileName')} id={info.get('file_id')}")
    _ok(f"下载地址 {info.get('downloadUrl')}")

    print("\n===== 4) HEAD 校验下载地址可访问 =====")
    url = info["downloadUrl"]
    resp = dm.session.head(url, timeout=30, allow_redirects=True)
    clen = resp.headers.get("Content-Length")
    ctype = resp.headers.get("Content-Type")
    if resp.status_code not in (200, 302):
        _fail(f"HEAD {url} -> HTTP {resp.status_code}")
    if clen is not None and int(clen) < 1024 * 1024:
        _fail(f"下载地址 Content-Length 过小: {clen}")
    _ok(f"HEAD {resp.status_code} final={resp.url}")
    _ok(f"Content-Type={ctype} Content-Length={clen}")

    print("\n全部通过：文件列表与下载地址可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
