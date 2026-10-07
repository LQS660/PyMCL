# -*- coding: utf-8 -*-
"""Test the real settings field/helper without loading or rewriting user config."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = ast.parse((_ROOT / "app" / "backend.py").read_text(encoding="utf-8"))
_CONFIG = ast.parse((_ROOT / "mclauncher" / "config.py").read_text(encoding="utf-8"))
_CLASS = next(node for node in _BACKEND.body
              if isinstance(node, ast.ClassDef) and node.name == "BackendAPI")
_METHOD = next(node for node in _CLASS.body
               if isinstance(node, ast.FunctionDef) and node.name == "get_settings")
_SETTINGS = next(node.value for node in _METHOD.body if isinstance(node, ast.Return))
_HISTORY = next(value for key, value in zip(_SETTINGS.keys, _SETTINGS.values)
                if isinstance(key, ast.Constant) and key.value == "ui_background_history")
_HISTORY_CODE = compile(ast.Expression(_HISTORY), str(_ROOT / "app" / "backend.py"), "eval")
_HELPERS = ast.Module(body=[
    node for node in _CONFIG.body
    if isinstance(node, ast.FunctionDef)
    and node.name in {"_history_paths", "background_history"}
], type_ignores=[])
_HELPER_CODE = compile(_HELPERS, str(_ROOT / "mclauncher" / "config.py"), "exec")


def _settings_history(raw):
    config = {"ui_background_history": raw, "ui_background_folder_history": []}
    namespace = {"CONFIG": config, "Path": Path}
    exec(_HELPER_CODE, namespace)
    namespace["_bg_history"] = namespace["background_history"]
    return eval(_HISTORY_CODE, namespace), config


@pytest.mark.parametrize("raw", [None, 1, True, 2.5, "C:/wallpaper.png",
                                  {"C:/wallpaper.png": True}])
def test_bugfix_agent07_settings_rejects_non_history_containers(raw):
    result, config = _settings_history(raw)
    assert result == []
    assert config["ui_background_history"] is raw


def test_bugfix_agent07_settings_filters_history_items_without_mutating_config():
    raw = ["first.png", Path("wallpapers/second.png"), None, 5, ["bad"],
           {"path": "bad.png"}, ""]
    before = list(raw)
    result, config = _settings_history(raw)
    assert result == ["first.png", str(raw[1]), ""]
    assert config["ui_background_history"] is raw
    assert raw == before


def test_bugfix_agent07_settings_preserves_history_order_duplicates_and_empty():
    raw = ("first.png", "first.png", "", Path("second.png"))
    result, config = _settings_history(raw)
    assert result == ["first.png", "first.png", "", str(raw[3])]
    assert config["ui_background_history"] is raw


def test_bugfix_agent07_settings_history_is_a_fresh_list():
    raw = ["first.png"]
    result, _ = _settings_history(raw)
    result.append("new.png")
    assert raw == ["first.png"]
