# -*- coding: utf-8 -*-
"""Build a source-only zip of the project: git-tracked files + new untracked source.

Excludes: .git, build outputs (bin/obj/build/dist/cache), local runtime data,
logs, and sensitive local files (accounts.json, config.json).
"""
from __future__ import annotations

import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / (datetime.now().strftime("%m%d%H%M") + ".zip")

SKIP_DIRS = {"bin", "obj", "__pycache__", ".pytest_cache", ".git", "node_modules"}

# 1) git-tracked files (gitignore already filters local config/secrets/artifacts)
tracked = subprocess.check_output(
    ["git", "ls-files", "-z"], cwd=ROOT
).decode("utf-8").split("\0")
tracked = [p for p in tracked if p]

# 2) untracked source that matters (new WPF UI, native additions, build scripts)
extra = [
    "_audit_slim.py",
    "_c_bridge_smoke.py",
    "_cmp_rpc.py",
    "_cmp_ui_rpc.py",
    "_need.py",
    "_need2.py",
    "_pack_native_ui.py",
    "_pack_pcl_ui.py",
    "_pack_slim.py",
    "_slim_smoke.py",
    "_winui_rpc2.py",
    "_layout_smoke.py",
    "_layout_visual.py",
    "app/dashboard.py",
    "app/layout_model.py",
    "app/pages/home_cards.py",
    "app/pages/layout_settings.py",
    "native/src/rpc_extra.c",
    "native/tools/py_rpc.py",
    "pack/build-native-ui.bat",
    "pack/build-pcl-ui.bat",
    "pack/build-slim.bat",
]
for sub in ("wpf", "native/tools"):
    base = ROOT / sub
    if not base.is_dir():
        continue
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        extra.append(p.relative_to(ROOT).as_posix())

files = sorted(set(tracked) | set(extra))

if OUT.exists():
            OUT.unlink()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for rel in files:
        f = ROOT / rel
        if f.is_file():
            z.write(f, "PyMCL/" + rel)

size = OUT.stat().st_size
print(f"files={len(files)} zip={OUT} size={size} ({size/1024/1024:.2f} MB)")
