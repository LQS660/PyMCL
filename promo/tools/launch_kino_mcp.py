# -*- coding: utf-8 -*-
"""Start Kinocut MCP with local ffmpeg/ffprobe on PATH."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FFMPEG_BIN = ROOT / "ffmpeg" / "bin"
os.environ["PATH"] = str(FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", "")
os.chdir(str(ROOT.parent.parent))

os.execv(sys.executable, [sys.executable, "-m", "kinocut", "--mcp"])
