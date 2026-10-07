"""Instance/config/version migration/layout regressions; all filesystem effects stay in tmp_path."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from mclauncher import config as config_mod
from mclauncher import instances, single_root, ui_layout
from mclauncher import version_settings as vs


def _instance(root: Path):
    return SimpleNamespace(path=root, versions_dir=lambda: root / "versions")


def _legacy_version(root: Path, name: str, vid: str, isolation: str | None = None) -> Path:
    inst = root / name
    inst.mkdir(parents=True, exist_ok=True)
    (inst / instances.INSTANCE_META).write_text(json.dumps({"name": name}), encoding="utf-8")
    vdir = inst / "versions" / vid
    vdir.mkdir(parents=True)
    (vdir / f"{vid}.json").write_text(json.dumps({"id": vid}), encoding="utf-8")
    if isolation:
        (vdir / vs.FILE_NAME).write_text(json.dumps({"isolation": isolation}), encoding="utf-8")
    return vdir


def _file(root: Path, relative: str, text: str = "user content") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def isolated_config(tmp_path):
    with mock.patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
         mock.patch.object(config_mod.CONFIG, "data", copy.deepcopy(config_mod.CONFIG.data)):
        yield config_mod.CONFIG


def test_windows_device_names_with_extensions_are_not_valid_instances(tmp_path, isolated_config):
    isolated_config.set("instances_dir", str(tmp_path / ".minecraft"))
    for name in ("CON.txt", "com1.jar", "LPT9.zip"):
        assert instances.sanitize_instance_name(name).upper().split(".")[0] not in instances._WIN_RESERVED
        with pytest.raises(instances.InstanceError):
            instances.get_instance_path(name)
    with pytest.raises(instances.InstanceError):
        instances.get_instance_path("world.")
    assert instances.get_instance_path("world.txt") == (tmp_path / ".minecraft" / "world.txt").resolve()


def test_config_defaults_are_not_shared_and_reload_discards_unsaved_data(tmp_path):
    with mock.patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"):
        config = config_mod.Config()
        config.data["ui_nav_order"].append("accidental mutation")
        try:
            assert config_mod.DEFAULT_CONFIG["ui_nav_order"] == []
            config.set("memory_mb", 16384)
            config.set("unsaved_custom_key", "stale")
            config.load()
            assert config.get("memory_mb") == config_mod.DEFAULT_CONFIG["memory_mb"]
            assert config.get("unsaved_custom_key") is None
        finally:
            # A failing regression must not pollute another test via the mutable default.
            config_mod.DEFAULT_CONFIG["ui_nav_order"].clear()


def test_background_history_recovers_a_single_stored_path(isolated_config):
    isolated_config.set("ui_background_history", "C:/old.png")
    isolated_config.set("ui_background_folder_history", "D:/wallpapers")
    assert config_mod.background_history() == (["C:/old.png"], ["D:/wallpapers"])


def test_seed_from_shared_does_not_copy_into_a_shared_link(tmp_path):
    root = tmp_path / ".minecraft"
    inst = _instance(root)
    vdir = root / "versions" / "1.20.1"
    vdir.mkdir(parents=True)
    _file(root, "mods/user.jar")
    vs.save(inst, "1.20.1", {"isolation": vs.ISOLATION_SAVES})
    vs.apply_isolation(inst, "1.20.1")
    if not single_root.is_link(vdir / "mods"):
        pytest.skip("directory links unavailable on this filesystem")

    vs.set_isolation(inst, "1.20.1", vs.ISOLATION_ALL, seed=True)

    assert (vdir / "mods" / "user.jar").is_file(), "shared mod was lost when the link was removed"
    assert not single_root.is_link(vdir / "mods")
    assert (root / "mods" / "user.jar").is_file(), "the shared source must remain untouched"


def test_migration_preserves_secondary_mod_isolation_shared_worlds(tmp_path, isolated_config):
    root = tmp_path / ".minecraft"
    isolated_config.set("instances_dir", str(root))
    isolated_config.set("default_instance", "primary")
    _legacy_version(root, "primary", "base")
    vdir = _legacy_version(root, "secondary", "modded", vs.ISOLATION_MODS)
    _file(vdir, "mods/private.jar")
    _file(root / "secondary", "saves/SecondaryWorld/level.dat")
    _file(root / "secondary", "resourcepacks/private.zip")
    _file(root / "secondary", "screenshots/one.png")
    _file(root / "primary", "saves/PrimaryWorld/level.dat")

    single_root.migrate()

    moved = root / "versions" / "modded"
    assert vs.load(_instance(root), "modded")["isolation"] == vs.ISOLATION_ALL
    for rel in ("mods/private.jar", "saves/SecondaryWorld/level.dat",
                "resourcepacks/private.zip", "screenshots/one.png"):
        assert (moved / rel).is_file(), f"lost secondary instance content: {rel}"
    assert not (moved / "saves" / "PrimaryWorld").exists()
    assert not (root / "saves" / "SecondaryWorld").exists()
    single_root.migrate()
    assert (moved / "saves" / "SecondaryWorld" / "level.dat").is_file()


def test_migration_does_not_copy_shared_saves_into_save_isolated_version(tmp_path, isolated_config):
    root = tmp_path / ".minecraft"
    isolated_config.set("instances_dir", str(root))
    isolated_config.set("default_instance", "primary")
    _legacy_version(root, "primary", "base")
    vdir = _legacy_version(root, "secondary", "saves-only", vs.ISOLATION_SAVES)
    _file(vdir, "saves/OwnWorld/level.dat")
    _file(root / "secondary", "saves/OtherWorld/level.dat")
    _file(root / "secondary", "mods/shared.jar")

    single_root.migrate()

    moved = root / "versions" / "saves-only"
    assert (moved / "saves" / "OwnWorld" / "level.dat").is_file()
    assert not (moved / "saves" / "OtherWorld").exists()
    assert (moved / "mods" / "shared.jar").is_file()
    assert vs.load(_instance(root), "saves-only")["isolation"] == vs.ISOLATION_ALL


def test_layout_import_rejects_nonfinite_and_malformed_geometry(tmp_path):
    row = {"id": "notes-main", "type": "notes", "x": "NaN", "y": 0, "w": 0.3, "h": 0.3}
    assert ui_layout.parse_doc({"items": [row]}) is None
    row["x"] = "not a number"
    path = tmp_path / "layout.json"
    path.write_text(json.dumps({"items": [row]}), encoding="utf-8")
    assert ui_layout.import_doc(str(path)) is None


def test_layout_load_skips_malformed_items_but_preserves_valid_ones():
    valid = {"id": "good", "type": "notes", "x": 0.1, "y": 0, "w": 0.3, "h": 0.3}
    invalid = {"id": "bad", "type": "notes", "x": "broken", "y": 0, "w": 0.3, "h": 0.3}
    doc = ui_layout.LayoutDoc.from_dict({"items": [invalid, valid]})
    assert [item.id for item in doc.items] == ["good"]
    assert doc.to_dict()["items"][0]["x"] == 0.1
