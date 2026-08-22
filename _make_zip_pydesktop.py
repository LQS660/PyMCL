# -*- coding: utf-8 -*-
"""Pack the Python desktop version of PyMCL into a source zip.

Excludes non-Python desktop variants (winui3 / wpf / android), the promo
toolchain, build outputs, runtime data and local secrets.
"""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "08221424.zip"

# Non-Python variants / non-desktop tooling
SKIP_DIR_PREFIXES = (
    "winui3/",          # C# WinUI3 desktop
    "wpf/",             # C# WPF desktop (untracked)
    "android/",         # Kotlin mobile
    "promo/",           # promo toolchain (not desktop)
    "_app_backup_i18n/",  # old app backup
    "build/", "dist/", "cache/", ".minecraft/", "instances/", "java/",
    "node_modules/", "__pycache__/", ".pytest_cache/",
    ".git/", ".cursor/", ".vscode/",
    "native/build/", "eziapp/build/", "eziapp/dist/", "eziapp/node_modules/",
)

# Local runtime data / secrets / artifacts
SKIP_FILES = {
    "config.json", "accounts.json", "ai_chats.json", "device_id",
    "feedback_history.json", "playtime.json",
    "run-winui.bat", "WINUI3_AGENT_PROMPT.md",
    "08221203.zip", "08221231.exe", "pymcl-feedback-client-src.zip",
    "02-install-game.mp4", "eziapp/package-lock.json",
}

# git-tracked files (worktree state)
tracked = subprocess.check_output(
    ["git", "ls-files", "-z"], cwd=ROOT
).decode("utf-8").split("\0")

files: set[str] = set()
for p in tracked:
    if not p or p in SKIP_FILES:
        continue
    if any(p.startswith(prefix) for prefix in SKIP_DIR_PREFIXES):
        continue
    files.add(p)

# untracked source that belongs to the Python desktop build
extra = [
    # new UI modules
    "app/dashboard.py", "app/layout_model.py", "app/pages/home_cards.py",
    # native / packaging additions
    "native/src/rpc_extra.c", "native/tools/py_rpc.py",
    "pack/build-native-ui.bat", "pack/build-pcl-ui.bat", "pack/build-slim.bat",
    # build / audit scripts
    "_make_source_zip.py", "_make_zip_pydesktop.py",
    "_audit_slim.py", "_slim_func_audit.py", "_slim_smoke.py",
    "_c_bridge_smoke.py", "_cmp_rpc.py", "_cmp_ui_rpc.py",
    "_need.py", "_need2.py", "_winui_rpc2.py",
    "_pack_native_ui.py", "_pack_pcl_ui.py", "_pack_slim.py",
]
for rel in extra:
    files.add(rel)

files = sorted(files)

if OUT.exists():
    OUT.unlink()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for rel in files:
        f = ROOT / rel
        if f.is_file():
            z.write(f, "PyMCL/" + rel)

size = OUT.stat().st_size
print(f"files={len(files)} zip={OUT} size={size} ({size/1024/1024:.2f} MB)")
