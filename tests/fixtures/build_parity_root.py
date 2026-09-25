# -*- coding: utf-8 -*-
"""生成 C 桥 / Python 桥对拍用的固定数据根目录 tests/fixtures/parity_root/。

    python tests/fixtures/build_parity_root.py

目录结构按 Python 桥（行为参考实现）的单目录模式来：`.minecraft` 本身就是游戏目录，
版本平铺在 `.minecraft/versions/` 下。模组 jar、level.dat 这类二进制文件由本脚本生成，
改动夹具请改这里再重跑，不要手改产物。
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import os
import shutil
import struct
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "parity_root"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_mod(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("fabric.mod.json", date_time=(2024, 1, 1, 0, 0, 0))
        z.writestr(info, json.dumps(meta, ensure_ascii=False, indent=2))
    path.write_bytes(buf.getvalue())


def nbt_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def nbt_string(name: str, value: str) -> bytes:
    raw = value.encode("utf-8")
    return b"\x08" + nbt_name(name) + struct.pack(">H", len(raw)) + raw


def nbt_int(name: str, value: int) -> bytes:
    return b"\x03" + nbt_name(name) + struct.pack(">i", value)


def nbt_long(name: str, value: int) -> bytes:
    return b"\x04" + nbt_name(name) + struct.pack(">q", value)


def nbt_compound(name: str, *items: bytes) -> bytes:
    return b"\x0a" + nbt_name(name) + b"".join(items) + b"\x00"


def write_level_dat(path: Path, level_name: str, version: str) -> None:
    data = nbt_compound(
        "",
        nbt_compound(
            "Data",
            nbt_string("LevelName", level_name),
            nbt_long("LastPlayed", 1700000000000),
            nbt_int("GameType", 0),
            nbt_int("hardcore", 0),
            nbt_compound("Version", nbt_string("Name", version), nbt_int("Id", 3465)),
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(data)
    path.write_bytes(buf.getvalue())


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    game = OUT / ".minecraft"

    write_json(OUT / "config.json", {"instances_dir": ".minecraft", "language": "zh_CN"})
    write_json(game / ".instance.json",
               {"name": ".minecraft", "mc_version": None, "modpack": None, "java": "自动选择"})

    write_json(game / "versions" / "1.20.1" / "1.20.1.json", {
        "id": "1.20.1",
        "type": "release",
        "time": "2023-06-12T13:25:51+00:00",
        "releaseTime": "2023-06-12T13:25:51+00:00",
        "mainClass": "net.minecraft.client.main.Main",
        "minimumLauncherVersion": 21,
        "javaVersion": {"component": "java-runtime-gamma", "majorVersion": 17},
        "assets": "5",
        "assetIndex": {"id": "5", "sha1": "0" * 40, "size": 1, "totalSize": 1,
                       "url": "https://example.invalid/5.json"},
        "libraries": [],
        "arguments": {
            "game": ["--username", "${auth_player_name}", "--version", "${version_name}",
                     "--gameDir", "${game_directory}"],
            "jvm": ["-cp", "${classpath}"],
        },
        "downloads": {},
    })
    # 空 jar 只参与存在性检查（启动命令构建要用），类路径里出现的是它的路径
    (game / "versions" / "1.20.1" / "1.20.1.jar").write_bytes(b"")
    fabric_id = "fabric-loader-0.15.11-1.20.1"
    write_json(game / "versions" / fabric_id / f"{fabric_id}.json", {
        "id": fabric_id,
        "inheritsFrom": "1.20.1",
        "type": "release",
        "time": "2024-05-20T00:00:00+00:00",
        "releaseTime": "2024-05-20T00:00:00+00:00",
        "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
        "arguments": {"game": [], "jvm": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
        "libraries": [
            {"name": "net.fabricmc:fabric-loader:0.15.11", "url": "https://maven.fabricmc.net/"},
        ],
    })

    write_mod(game / "mods" / "parity-mod-1.0.0.jar", {
        "schemaVersion": 1, "id": "paritymod", "version": "1.0.0", "name": "Parity Mod",
        "description": "对拍夹具模组", "authors": ["PyMCL"], "environment": "*",
        "depends": {"minecraft": "1.20.x", "fabricloader": ">=0.15.0"},
    })
    write_mod(game / "mods" / "old-mod-0.1.0.jar.disabled", {
        "schemaVersion": 1, "id": "oldmod", "version": "0.1.0", "name": "Old Mod",
        "description": "被禁用的夹具模组", "authors": ["PyMCL"], "environment": "client",
    })

    write_level_dat(game / "saves" / "Parity World" / "level.dat", "Parity World", "1.20.1")
    (game / "saves" / "Parity World" / "icon.png").write_bytes(TINY_PNG)
    (game / "logs").mkdir(parents=True, exist_ok=True)
    (game / "logs" / "latest.log").write_text(
        "[00:00:00] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.11\n", encoding="utf-8")
    (game / "crash-reports").mkdir(parents=True, exist_ok=True)
    (game / "crash-reports" / "crash-2024-01-01_00.00.00-client.txt").write_text(
        "---- Minecraft Crash Report ----\n// Fixture\n", encoding="utf-8")
    (game / "screenshots").mkdir(parents=True, exist_ok=True)
    (game / "screenshots" / "2024-01-01_00.00.00.png").write_bytes(TINY_PNG)
    (game / "screenshots" / "2024-01-02_00.00.00.png").write_bytes(TINY_PNG)
    (game / "screenshots" / "notes.txt").write_text("not a screenshot", encoding="utf-8")

    backup = game / "backups" / "Parity World-20240101-000000.zip"
    backup.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((game / "saves" / "Parity World").rglob("*")):
            if p.is_file():
                z.write(p, str(Path("Parity World") / p.relative_to(game / "saves" / "Parity World")))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("pack.mcmeta", date_time=(2024, 1, 1, 0, 0, 0)),
                   json.dumps({"pack": {"pack_format": 15, "description": "fixture"}}))
    (game / "datapacks").mkdir(parents=True, exist_ok=True)
    (game / "datapacks" / "fixture-pack.zip").write_bytes(buf.getvalue())

    write_json(OUT / "themes" / "Ocean.json", {
        "name": "Ocean", "theme_color": "#1E6FD9", "ui_dark": True, "ui_background": "",
        "ui_sidebar_opacity": 90, "ui_background_blur": 4, "ui_background_dim": 10,
        "ui_background_folder": "", "ui_background_shuffle": False, "ui_background_interval": 10,
        "window_mode": "window", "custom_homepage": "", "homepage_mode": "news",
    })
    write_mod(OUT / "shared" / "mods" / "global-a-1.0.jar", {"schemaVersion": 1, "id": "globala", "version": "1.0"})
    write_mod(OUT / "shared" / "mods" / "global-b-1.0.jar.disabled", {"schemaVersion": 1, "id": "globalb", "version": "1.0"})
    write_json(OUT / "playtime.json", {"instances": {".minecraft": {
        "total": 5400, "versions": {"1.20.1": 5400},
        "sessions": [{"start": 1700000000, "duration": 5400, "version": "1.20.1"}]}}})

    # 固定 mtime：按 mtime 排序的接口（截图、备份列表）两边才排得一样
    stamp = 1704067200
    for i, p in enumerate(sorted(x for x in OUT.rglob("*") if x.is_file())):
        os.utime(p, (stamp + i * 60, stamp + i * 60))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
