# -*- coding: utf-8 -*-
"""审计 #1 路径穿越回归用例：P0-1 / P0-2 / P1-3 / P1-4 + 远端 filename（待查第 5 条）。

修前这些用例全部失败：`rename_version` 会整棵删掉版本目录之外的目录、
`version_settings` 能在游戏目录外建目录写 pymcl.json、`open_folder` 会越界建目录、
`install_datapack_into_save` 把数据包复制到 saves/ 之外、Modrinth/CurseForge
返回的 `filename` 含 `../` 时下载落到目标目录之外。

全部离线：临时目录 + 打桩 DownloadManager，不联网、不碰真实 .minecraft。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mclauncher import mods as mods_mod
from mclauncher import saves as saves_mod
from mclauncher import version_ops
from mclauncher import version_settings as vs


def _inst(root: Path, versions=()):
    """只提供被测函数会用到的那几样。"""
    inst = SimpleNamespace(name="t", path=root)
    inst.versions_dir = lambda: root / "versions"
    inst.ensure_standard_dirs = lambda: None
    inst.installed_ids = lambda: list(versions)
    inst.meta = lambda: {}
    return inst


# ---------------------------------------------------------------- P0-1

class TestRenameVersionTraversal:
    def test_rename_version_rejects_old_id_escape(self, tmp_path: Path):
        """`old_id="../../OUTSIDE"` 修前会把 OUTSIDE 整棵复制后原地删除。"""
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        inst = _inst(root)

        with pytest.raises(version_ops.VersionOpError):
            version_ops.rename_version(inst, "../../OUTSIDE", "stolen")

        assert outside.is_dir(), "版本目录之外的目录被整棵删掉了"
        assert (outside / "keep.txt").is_file(), "版本目录之外的文件被删掉了"
        assert not (root / "versions" / "stolen").exists()

    def test_rename_version_rejects_absolute_old_id(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        outside = tmp_path / "ABS_OUTSIDE"
        outside.mkdir()
        inst = _inst(root)

        with pytest.raises(version_ops.VersionOpError):
            version_ops.rename_version(inst, str(outside), "stolen")

        assert outside.is_dir()

    def test_rename_version_still_works_for_normal_id(self, tmp_path: Path):
        root = tmp_path / "root"
        vdir = root / "versions" / "1.20.1"
        vdir.mkdir(parents=True)
        (vdir / "1.20.1.json").write_text('{"id": "1.20.1"}', encoding="utf-8")
        inst = _inst(root)

        assert version_ops.rename_version(inst, "1.20.1", "1.20.1-forge") == "1.20.1-forge"
        assert (root / "versions" / "1.20.1-forge" / "1.20.1-forge.json").is_file()
        assert not vdir.exists()


# ---------------------------------------------------------------- P0-2

class TestVersionSettingsTraversal:
    def test_save_rejects_escape_and_writes_nothing(self, tmp_path: Path):
        """修前：versions/../../pwned/pymcl.json 被真的建出来。"""
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        inst = _inst(root)

        with pytest.raises(ValueError):
            vs.save(inst, "../../pwned", {"isolation": vs.ISOLATION_ALL})

        assert not (tmp_path / "pwned").exists(), "在游戏目录之外建了目录"
        assert not (tmp_path / "pwned" / "pymcl.json").exists()

    def test_load_rejects_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        inst = _inst(root)
        outside_json = tmp_path / "pymcl.json"
        outside_json.write_text('{"isolation": "all"}', encoding="utf-8")

        with pytest.raises(ValueError):
            vs.load(inst, "..")

    def test_save_still_works_for_normal_id(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "versions" / "1.20.1").mkdir(parents=True)
        inst = _inst(root)

        out = vs.save(inst, "1.20.1", {"isolation": vs.ISOLATION_ALL})
        assert out["isolation"] == vs.ISOLATION_ALL
        assert (root / "versions" / "1.20.1" / "pymcl.json").is_file()
        assert vs.load(inst, "1.20.1")["isolation"] == vs.ISOLATION_ALL

    def test_game_dir_rejects_escape(self, tmp_path: Path):
        """game_dir 是版本目录的公共入口，穿越名在这里就该被挡掉。"""
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        inst = _inst(root)

        with pytest.raises(ValueError):
            vs.game_dir(inst, "../../ESCAPED")

        assert not (tmp_path / "ESCAPED").exists()


# ---------------------------------------------------------------- P1-4

class TestOpenFolderTraversal:
    def test_open_folder_rejects_escape(self, tmp_path: Path, monkeypatch):
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        inst = _inst(root)
        opened: list = []
        monkeypatch.setattr(version_ops, "open_path", lambda p: opened.append(p) or True)

        with pytest.raises(version_ops.VersionOpError):
            version_ops.open_folder(inst, "../../ESCAPED2", "version")

        assert not (tmp_path / "ESCAPED2").exists(), "越界目录被 ensure_dir 建出来了"
        assert opened == [], "越界目录仍然被打开了"

    def test_folder_map_rejects_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "versions").mkdir(parents=True)
        inst = _inst(root)

        with pytest.raises(version_ops.VersionOpError):
            version_ops.folder_map(inst, "../../ESCAPED3")

    def test_open_folder_still_works_for_normal_id(self, tmp_path: Path, monkeypatch):
        root = tmp_path / "root"
        (root / "versions" / "1.20.1").mkdir(parents=True)
        inst = _inst(root)
        monkeypatch.setattr(version_ops, "open_path", lambda p: True)

        assert version_ops.open_folder(inst, "1.20.1", "version").endswith("1.20.1")
        assert (root / "versions" / "1.20.1").is_dir()


# ---------------------------------------------------------------- P1-3

class TestDatapackIntoTraversal:
    def test_install_datapack_rejects_save_name_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "datapacks").mkdir(parents=True)
        (root / "datapacks" / "pack.zip").write_bytes(b"PK\x03\x04")
        (root / "saves").mkdir()
        inst = _inst(root)

        with pytest.raises(saves_mod.SaveError):
            saves_mod.install_datapack_into_save(inst, "pack.zip", "../../ESCAPE_SAVE")

        assert not (root / "ESCAPE_SAVE").exists(), "数据包被写到 saves/ 之外"

    def test_install_datapack_still_works_for_normal_name(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "datapacks").mkdir(parents=True)
        (root / "datapacks" / "pack.zip").write_bytes(b"PK\x03\x04")
        (root / "saves" / "world").mkdir(parents=True)
        inst = _inst(root)

        dest = Path(saves_mod.install_datapack_into_save(inst, "pack.zip", "world"))
        assert dest.is_file()
        assert dest.parent == (root / "saves" / "world" / "datapacks").resolve()


# ---------------------------------------------------------------- 远端 filename

class _StubDM:
    """只回答被测函数会问的端点，download 落一个空文件并记下目标路径。"""

    def __init__(self, *, version=None, cf_detail=None, versions_list=None):
        self.version = version
        self.cf_detail = cf_detail
        self.versions_list = versions_list or []
        self.downloaded: list[Path] = []

    def fetch_json(self, url, **kwargs):
        if "/version/" in url:
            return self.version
        if "/mods/" in url:
            return self.cf_detail
        return self.versions_list

    def download(self, url, dest, **kwargs):
        dest = Path(dest)
        self.downloaded.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jar")
        return dest


def _mr_version(filename: str) -> dict:
    return {
        "id": "abc123",
        "version_number": "1.0",
        "files": [{
            "url": "https://cdn.modrinth.com/data/x/versions/abc123/x.jar",
            "filename": filename,
            "primary": True,
            "size": 3,
            "hashes": {"sha1": "aa", "sha512": "bb"},
        }],
        "dependencies": [],
    }


def _cf_mod(file_name: str) -> dict:
    return {
        "data": {
            "id": 4321,
            "name": "Demo",
            "latestFiles": [{
                "id": 777,
                "fileName": file_name,
                "downloadUrl": "https://mediafilez.forgecdn.net/files/777/x.jar",
                "gameVersions": ["1.20.1", "Fabric"],
            }],
        }
    }


class TestRemoteFilenameTraversal:
    def test_modrinth_mod_rejects_escape_filename(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        inst = _inst(root)
        dm = _StubDM(version=_mr_version("../../../ESCAPE_MOD.jar"))

        with pytest.raises(mods_mod.ModError):
            mods_mod.install_modrinth_mod(
                dm, "demo", inst, mc_version="1.20.1", loader="fabric", version_id="abc123")

        assert not (tmp_path / "ESCAPE_MOD.jar").exists()

    def test_modrinth_content_rejects_escape_filename(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "shaderpacks").mkdir(parents=True)
        inst = _inst(root)
        dm = _StubDM(version=_mr_version("../../ESCAPE_SHADER.zip"))

        with pytest.raises(mods_mod.ModError):
            mods_mod.install_modrinth_content(
                dm, "demo", inst, "shaderpacks", version_id="abc123")

        assert not (tmp_path / "ESCAPE_SHADER.zip").exists()

    def test_cf_content_rejects_escape_filename(self, tmp_path: Path):
        root = tmp_path / "root"
        (root / "resourcepacks").mkdir(parents=True)
        inst = _inst(root)
        dm = _StubDM(cf_detail=_cf_mod("../../ESCAPE_CF.zip"))

        with pytest.raises(mods_mod.ModError):
            mods_mod.install_cf_content(dm, 4321, inst, "resourcepacks", mc_version="1.20.1")

        assert not (tmp_path / "ESCAPE_CF.zip").exists()

    def test_curseforge_mod_rejects_escape_filename(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        inst = _inst(root)
        dm = _StubDM(cf_detail=_cf_mod("../../../ESCAPE_CF_MOD.jar"))

        with pytest.raises(mods_mod.ModError):
            mods_mod.install_curseforge_mod(
                dm, 4321, inst, mc_version="1.20.1", loader="fabric")

        assert not (tmp_path / "ESCAPE_CF_MOD.jar").exists()

    def test_normal_filename_still_downloads(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        inst = _inst(root)
        dm = _StubDM(version=_mr_version("demo-1.0.jar"))

        out = mods_mod.install_modrinth_mod(
            dm, "demo", inst, mc_version="1.20.1", loader="fabric", version_id="abc123")

        assert out["files"] == ["demo-1.0.jar"]
        assert (root / "mods" / "demo-1.0.jar").is_file()
