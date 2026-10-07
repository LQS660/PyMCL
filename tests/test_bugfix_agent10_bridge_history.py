"""Exercise bridge settings in a fresh process, with temporary config and no network."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = PROJECT_ROOT / "bridge" / "api.py"

BRIDGE_PROBE = r'''
import importlib.util
import json
import socket
import sys


def deny_network(*args, **kwargs):
    raise AssertionError("Network disabled for agent10 bridge regressions")


socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.socket.sendto = deny_network
spec = importlib.util.spec_from_file_location("_agent10_bridge_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from mclauncher.config import CONFIG, CONFIG_FILE
before = CONFIG_FILE.read_bytes()
settings = module.BackendAPI.get_settings(None)
assert CONFIG_FILE.read_bytes() == before, "Reading settings must not save config"
print(json.dumps(settings["ui_background_history"]))
'''


@pytest.mark.parametrize("raw, expected", [
    (None, []),
    (False, []),
    (True, []),
    (7, []),
    (2.5, []),
    ("", []),
    ("wall.png", []),
    ({"wrong": "walls"}, []),
    ([], []),
    (["wall.png"], ["wall.png"]),
    (["a.png", None, 7, ["nested.png"], {"path": "fake.png"}, ""], ["a.png", ""]),
])
def test_bridge_get_settings_sanitizes_persisted_history(tmp_path, raw, expected):
    pending = tmp_path / "config.json.tmp"
    pending.write_text(json.dumps({"ui_background_history": raw}), encoding="utf-8")
    os.replace(pending, tmp_path / "config.json")
    env = dict(os.environ, PYMCL_HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", BRIDGE_PROBE, str(BRIDGE_SOURCE)],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == expected
