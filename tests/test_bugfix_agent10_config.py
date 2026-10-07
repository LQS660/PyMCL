"""Config regressions with isolated module imports and temporary JSON files."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "mclauncher"
CONFIG_SOURCE = PACKAGE_ROOT / "config.py"


@pytest.fixture
def config_module(monkeypatch, tmp_path):
    # Avoid mclauncher.__init__ and its process-wide initialization. Load real
    # utils/config under a private package, with PYMCL_HOME set before import.
    package_name = "_bugfix_agent10_mclauncher"
    package = ModuleType(package_name)
    package.__path__ = [str(PACKAGE_ROOT)]
    package.APP_NAME = "PyMCL-agent10-test"
    package.APP_VERSION = "test"
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setenv("PYMCL_HOME", str(tmp_path))
    for name, source in (("utils", PACKAGE_ROOT / "utils.py"),
                         ("config", CONFIG_SOURCE)):
        spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", source)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        setattr(package, name, module)
        spec.loader.exec_module(module)
    assert package.utils.ROOT == tmp_path
    assert package.config.CONFIG_FILE == tmp_path / "config.json"
    return package.config


def test_all_mutable_defaults_are_owned_by_each_config(config_module, monkeypatch):
    monkeypatch.setattr(config_module.Config, "load", lambda self: None)
    first, second = config_module.Config(), config_module.Config()
    for key, default in config_module.DEFAULT_CONFIG.items():
        if isinstance(default, (dict, list)):
            assert first.get(key) == second.get(key) == default
            assert first.get(key) is not second.get(key), key
            assert first.get(key) is not default, key


def test_mutating_default_lists_does_not_pollute_factory(config_module, monkeypatch):
    monkeypatch.setattr(config_module.Config, "load", lambda self: None)
    first, second = config_module.Config(), config_module.Config()
    first.get("ui_nav_order").append("settings")
    assert second.get("ui_nav_order") == []
    assert config_module.DEFAULT_CONFIG["ui_nav_order"] == []
    assert config_module.Config().get("ui_nav_order") == []


def test_mutating_default_dicts_does_not_pollute_factory(config_module, monkeypatch):
    monkeypatch.setattr(config_module.Config, "load", lambda self: None)
    first, second = config_module.Config(), config_module.Config()
    first.get("ui_layouts")["custom"] = {"items": [{"keys": ["settings"]}]}
    assert second.get("ui_layouts") == {}
    assert config_module.DEFAULT_CONFIG["ui_layouts"] == {}
    assert config_module.Config().get("ui_layouts") == {}


@pytest.mark.parametrize("key, value", [
    ("ui_layouts", {"custom": [{"keys": ["settings"]}]}),
    ("ai_permission_rules", [{"rules": {"patterns": ["read"]}}]),
])
def test_nested_list_dict_defaults_are_deeply_isolated(config_module, monkeypatch, key, value):
    expected = deepcopy(value)
    monkeypatch.setitem(config_module.DEFAULT_CONFIG, key, value)
    monkeypatch.setattr(config_module.Config, "load", lambda self: None)
    first, second = config_module.Config(), config_module.Config()
    if key == "ui_layouts":
        first.get(key)["custom"][0]["keys"].append("launch")
    else:
        first.get(key)[0]["rules"]["patterns"].append("write")
    assert second.get(key) == expected
    assert config_module.DEFAULT_CONFIG[key] == expected
    assert config_module.Config().get(key) == expected


@pytest.mark.parametrize("stored", [None, {}, [], False, 7, "invalid", {"memory_mb": 8192}])
def test_missing_defaults_stay_isolated_on_load(config_module, monkeypatch, tmp_path, stored):
    configs = []
    for name in ("first.json", "second.json"):
        path = tmp_path / name
        config_module.utils.write_json(path, stored)
        monkeypatch.setattr(config_module, "CONFIG_FILE", path)
        configs.append(config_module.Config())
    first, second = configs
    first.get("ui_nav_order").append("settings")
    first.get("ui_section_members")["games"] = ["launch"]
    assert second.get("ui_nav_order") == []
    assert second.get("ui_section_members") == {}
    assert config_module.DEFAULT_CONFIG["ui_nav_order"] == []
    assert config_module.DEFAULT_CONFIG["ui_section_members"] == {}
    assert config_module.utils.read_json(tmp_path / "second.json")["ui_nav_order"] == []


def test_overrides_and_unknown_nested_keys_survive_reload(config_module, tmp_path):
    stored = {
        "ui_nav_order": ["settings", "launch"],
        "ui_layouts": {"custom": {"items": [{"keys": ["launch"]}]}},
        "future_setting": {"nested": [1, {"enabled": True}]},
    }
    config_module.utils.write_json(config_module.CONFIG_FILE, stored)
    first, second = config_module.Config(), config_module.Config()
    assert first.get("future_setting") == stored["future_setting"]
    first.get("ui_layouts")["custom"]["items"][0]["keys"].append("settings")
    assert second.get("ui_layouts") == stored["ui_layouts"]
    assert config_module.DEFAULT_CONFIG["ui_layouts"] == {}
    first.save()
    reloaded = config_module.Config()
    assert reloaded.get("ui_layouts") == first.get("ui_layouts")
    assert reloaded.get("future_setting") == stored["future_setting"]
    assert reloaded.cache_dir == tmp_path / "cache"


@pytest.mark.parametrize("raw", [None, True, False, 7, 2.5, "wall.png", "",
                                  {"wall.png": "folder"}, Path("wall.png")])
def test_malformed_history_containers_are_ignored(config_module, raw):
    assert config_module._history_paths(raw) == []


@pytest.mark.parametrize("container", [list, tuple])
def test_valid_history_sequences_keep_only_paths(config_module, container):
    raw = container(["a.png", Path("walls"), None, 7, ["nested.png"], {"path": "b.png"}, ""])
    assert config_module._history_paths(raw) == ["a.png", str(Path("walls")), ""]


@pytest.mark.parametrize("images, folders", [
    (True, False), (7, {"walls": "wrong"}), ("old.png", "walls"), (None, None),
])
def test_push_recovers_from_malformed_saved_histories(config_module, images, folders):
    config_module.utils.write_json(config_module.CONFIG_FILE, {
        "ui_background_history": images,
        "ui_background_folder_history": folders,
    })
    config_module.CONFIG.load()
    assert config_module.background_history() == ([], [])
    assert config_module.push_background_history("new.png", "new-walls") == (
        ["new.png"], ["new-walls"])


@pytest.mark.parametrize("folders, expected", [([], ["", ""]),
    (["walls"], ["walls", ""]), (["a", "b", "extra"], ["a", "b"]),
])
def test_valid_history_pair_alignment_is_preserved(config_module, folders, expected):
    config_module.CONFIG.set("ui_background_history", ["a.png", "b.png"])
    config_module.CONFIG.set("ui_background_folder_history", folders)
    assert config_module.background_history() == (["a.png", "b.png"], expected)


def test_history_cap_and_duplicate_suppression_are_preserved(config_module):
    images = [f"{i}.png" for i in range(config_module.BG_HISTORY_MAX)]
    folders = [f"walls-{i}" for i in range(config_module.BG_HISTORY_MAX)]
    config_module.CONFIG.set("ui_background_history", images)
    config_module.CONFIG.set("ui_background_folder_history", folders)
    assert config_module.push_background_history(images[-1], folders[-1]) == (images, folders)
    assert config_module.push_background_history("new.png", "new-walls") == (
        images[1:] + ["new.png"], folders[1:] + ["new-walls"])
