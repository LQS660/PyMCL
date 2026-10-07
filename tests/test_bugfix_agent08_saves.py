# -*- coding: utf-8 -*-
"""Offline save backup/restore regressions; only pytest temporary worlds are used."""
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from mclauncher import saves


@pytest.fixture
def instance(tmp_path):
    world = tmp_path / "saves" / "world"
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"original-world")
    (world / "keep.txt").write_bytes(b"original-only")
    (tmp_path / "backups").mkdir()
    return SimpleNamespace(path=tmp_path)


def _archive(instance, members=None, name="world-20261001-120000.zip"):
    archive = instance.path / "backups" / name
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        for member, data in (members or {}).items():
            zf.writestr(member, data)
    return archive


def _original_intact(instance):
    world = instance.path / "saves" / "world"
    assert world.is_dir()
    assert (world / "level.dat").read_bytes() == b"original-world"
    assert (world / "keep.txt").read_bytes() == b"original-only"


def _no_staging(instance):
    assert not list((instance.path / "saves").glob(".restore-*"))


@pytest.mark.parametrize("damage", [
    "corrupt", "empty", "parent-traversal", "absolute-path",
    "directory-traversal", "crc",
])
def test_overwrite_rejects_bad_archive_without_losing_world(instance, damage):
    members = {"world/level.dat": b"restore-world"}
    if damage == "empty":
        members = {}
    elif damage == "parent-traversal":
        members["../escape.dat"] = b"no"
    elif damage == "absolute-path":
        members[(instance.path / "escape.dat").as_posix()] = b"no"
    elif damage == "directory-traversal":
        members["../escape/"] = b""
    archive = _archive(instance, members)
    if damage == "corrupt":
        archive.write_bytes(b"not a zip")
    elif damage == "crc":
        data = archive.read_bytes()
        assert data.count(b"restore-world") == 1
        archive.write_bytes(data.replace(b"restore-world", b"Restore-world", 1))

    with pytest.raises((saves.SaveError, zipfile.BadZipFile)):
        saves.restore_backup(instance, archive.name, overwrite=True)

    _original_intact(instance)
    assert not (instance.path / "escape.dat").exists()
    _no_staging(instance)


def test_partial_extraction_failure_preserves_original(instance, monkeypatch):
    archive = _archive(instance, {
        "world/level.dat": b"restored",
        "world/region/r.0.0.mca": b"region",
    })

    def fail_partway(zf, path, *args, **kwargs):
        zf.extract(zf.namelist()[0], path)
        raise OSError("injected extraction failure")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", fail_partway)
    with pytest.raises(OSError, match="injected extraction failure"):
        saves.restore_backup(instance, archive.name, overwrite=True)

    _original_intact(instance)
    _no_staging(instance)


def test_valid_restore_replaces_world_only_after_extraction(instance):
    archive = _archive(instance, {
        "world/level.dat": b"restored",
        "world/region/r.0.0.mca": b"region",
    })
    out = saves.restore_backup(instance, archive.name, overwrite=True)
    world = instance.path / "saves" / "world"
    assert Path(out["path"]) == world
    assert (world / "level.dat").read_bytes() == b"restored"
    assert (world / "region/r.0.0.mca").read_bytes() == b"region"
    assert not (world / "keep.txt").exists()
    _no_staging(instance)


def test_default_restore_does_not_overwrite(instance):
    archive = _archive(instance, {"world/level.dat": b"restored"})
    first = saves.restore_backup(instance, archive.name)
    second = saves.restore_backup(instance, archive.name)
    _original_intact(instance)
    assert first["name"] == "world-还原"
    assert second["name"] == "world-还原2"
    assert (Path(first["path"]) / "level.dat").read_bytes() == b"restored"
    assert (Path(second["path"]) / "level.dat").read_bytes() == b"restored"
    _no_staging(instance)


def test_flat_single_file_archive_restores_as_directory(instance):
    archive = _archive(instance, {"level.dat": b"flat-world"})
    out = saves.restore_backup(instance, archive.name, target_name="flat")
    world = Path(out["path"])
    assert world.is_dir()
    assert (world / "level.dat").read_bytes() == b"flat-world"
    _no_staging(instance)


def test_publication_failure_rolls_back_original(instance, monkeypatch):
    import os

    archive = _archive(instance, {"world/level.dat": b"restored"})
    destination = instance.path / "saves" / "world"
    replace = os.replace
    calls = []

    def fail_publish(src, dst, *args, **kwargs):
        calls.append((Path(src), Path(dst)))
        if Path(dst) == destination and Path(src).parent.name == "unpacked":
            raise OSError("injected publication failure")
        return replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_publish)
    with pytest.raises(OSError, match="injected publication failure"):
        saves.restore_backup(instance, archive.name, overwrite=True)

    _original_intact(instance)
    assert len(calls) == 3  # retain old world, publish, roll back
    _no_staging(instance)


def test_rollback_failure_keeps_recoverable_original(instance, monkeypatch):
    import os

    archive = _archive(instance, {"world/level.dat": b"restored"})
    destination = instance.path / "saves" / "world"
    replace = os.replace

    def fail_publish_and_rollback(src, dst, *args, **kwargs):
        if Path(dst) == destination:
            raise OSError("injected destination lock")
        return replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_publish_and_rollback)
    with pytest.raises(saves.SaveError) as caught:
        saves.restore_backup(instance, archive.name, overwrite=True)

    previous = list((instance.path / "saves").glob(".restore-*/previous"))
    assert len(previous) == 1
    assert (previous[0] / "level.dat").read_bytes() == b"original-world"
    assert (previous[0] / "keep.txt").read_bytes() == b"original-only"
    assert str(previous[0]) in str(caught.value)


def test_same_second_backups_are_listed_for_original_save(instance, monkeypatch):
    monkeypatch.setattr(saves.time, "strftime", lambda *_: "20261001-120000")
    created = [saves.backup_save(instance, "world") for _ in range(3)]
    assert [row["name"] for row in created] == [
        "world-20261001-120000.zip", "world-20261001-120000-1.zip",
        "world-20261001-120000-2.zip",
    ]
    rows = saves.list_backups(instance, save_name="world")
    assert {row["name"] for row in rows} == {row["name"] for row in created}
    assert {row["save"] for row in rows} == {"world"}


def test_same_second_backup_restores_to_original_name(instance, monkeypatch):
    monkeypatch.setattr(saves.time, "strftime", lambda *_: "20261001-120000")
    saves.backup_save(instance, "world")
    second = saves.backup_save(instance, "world")
    out = saves.restore_backup(instance, second["name"])
    assert out["name"] == "world-还原"
    assert (Path(out["path"]) / "level.dat").read_bytes() == b"original-world"
    _original_intact(instance)


def test_independent_restore_staging_does_not_remove_existing_stage(instance, monkeypatch):
    archive = _archive(instance, {"world/level.dat": b"restored"})
    monkeypatch.setattr(saves.time, "time", lambda: 1234567890)
    occupied = instance.path / "saves" / ".restore-1234567890"
    occupied.mkdir()
    marker = occupied / "other-operation.dat"
    marker.write_bytes(b"keep")

    saves.restore_backup(instance, archive.name, target_name="restored-copy")

    assert marker.read_bytes() == b"keep"
    assert sorted(p.name for p in (instance.path / "saves").glob(".restore-*")) == [occupied.name]
