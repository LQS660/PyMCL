# -*- coding: utf-8 -*-
"""Start Edge TTS MCP (yuppie-mcp-tts)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(str(ROOT.parent))
os.execv(sys.executable, [sys.executable, "-m", "yuppie_mcp_tts"])
