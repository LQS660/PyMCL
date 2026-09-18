"""整合包装成「一个新版本」的那一步：改名、开隔离、内容往哪写。

`_prepare_target_version` 在加载器刚装完、版本目录还只有一个 json 时被调用，
之后整合包的模组才开始下载——所以这里验证的是「模组落地之前」的状态。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.backend as backend_mod
from mclauncher import modpack as mp
from mclauncher import version_ops
from mclauncher import version_settings as vs


class _FakeInstance:
    """只提供整合包装版本这一路上用得到的那几样。"""

    def __init__(self, root: Path):
        self.path = root
        self.name = root.name
        self.metas: dict = {}

    def versions_dir(self) -> Path:
        return self.path / "versions"

    def ensure_standard_dirs(self):
        self.versions_dir().mkdir(parents=True, exist_ok=True)

    def create(self):
        self.ensure_standard_dirs()

    def set_meta(self, key, value):
        self.metas[key] = value


def _write_version_json(instance, vid: str) -> Path:
    vdir = instance.versions_dir() / vid
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"{vid}.json").write_text(
        json.dumps({"id": vid, "inheritsFrom": "1.20.1"}), encoding="utf-8")
    return vdir


class TargetVersionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_target_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / ".minecraft"
        self.inst = _FakeInstance(self.root)
        (self.root / "mods").mkdir(parents=True)
        (self.root / "mods" / "shared.jar").write_text("x", encoding="utf-8")

    def make_version(self, vid: str) -> Path:
        vdir = self.inst.versions_dir() / vid
        vdir.mkdir(parents=True)
        (vdir / f"{vid}.json").write_text(
            json.dumps({"id": vid, "inheritsFrom": "1.20.1"}), encoding="utf-8")
        return vdir

    def test_unique_id_bumps_on_collision(self):
        self.make_version("我的整合包")
        self.assertEqual(version_ops.unique_id(self.inst, "我的整合包"), "我的整合包-2")
        self.assertEqual(version_ops.unique_id(self.inst, "别的包"), "别的包")

    def test_rename_and_isolate(self):
        self.make_version("1.20.1-forge-47.2.0")
        vid, content = mp._prepare_target_version(
            self.inst, "1.20.1-forge-47.2.0", "我的整合包", isolate=True)

        self.assertEqual(vid, "我的整合包")
        self.assertEqual(content, self.inst.versions_dir() / "我的整合包")
        self.assertFalse((self.inst.versions_dir() / "1.20.1-forge-47.2.0").exists(),
                         "改名之后旧版本目录不该留着")
        # 版本 json 跟着改名，里面的 id 也重写了
        jfile = content / "我的整合包.json"
        self.assertTrue(jfile.is_file())
        self.assertEqual(json.loads(jfile.read_text(encoding="utf-8"))["id"], "我的整合包")
        # 完全独立：自己的 mods 目录，而且没把大锅饭里的模组带过来
        self.assertTrue((content / "mods").is_dir())
        self.assertEqual(list((content / "mods").iterdir()), [])
        self.assertEqual(vs.load(self.inst, vid)["isolation"], vs.ISOLATION_ALL)

    def test_name_collision_gets_suffix(self):
        self.make_version("我的整合包")
        self.make_version("1.20.1-forge-47.2.0")
        vid, content = mp._prepare_target_version(
            self.inst, "1.20.1-forge-47.2.0", "我的整合包", isolate=True)
        self.assertEqual(vid, "我的整合包-2")
        self.assertTrue((self.inst.versions_dir() / "我的整合包").is_dir(), "别把同名的旧版本冲了")

    def test_isolate_without_rename(self):
        self.make_version("1.20.1-forge-47.2.0")
        vid, content = mp._prepare_target_version(
            self.inst, "1.20.1-forge-47.2.0", "", isolate=True)
        self.assertEqual(vid, "1.20.1-forge-47.2.0")
        self.assertEqual(content, self.inst.versions_dir() / vid)

    def test_no_isolate_writes_to_game_root(self):
        self.make_version("1.20.1-forge-47.2.0")
        vid, content = mp._prepare_target_version(
            self.inst, "1.20.1-forge-47.2.0", "", isolate=False)
        self.assertEqual(vid, "1.20.1-forge-47.2.0")
        self.assertEqual(content, self.root)
        self.assertEqual(vs.load(self.inst, vid)["isolation"], vs.ISOLATION_NONE)

    def test_same_name_is_a_noop(self):
        self.make_version("1.20.1-forge-47.2.0")
        vid, _ = mp._prepare_target_version(
            self.inst, "1.20.1-forge-47.2.0", "1.20.1-forge-47.2.0", isolate=False)
        self.assertEqual(vid, "1.20.1-forge-47.2.0")

    def test_no_version_id_falls_back_to_root(self):
        # 包里没有可识别的版本信息时，内容还是进游戏目录
        vid, content = mp._prepare_target_version(self.inst, "", "随便起个名", isolate=True)
        self.assertEqual(vid, "")
        self.assertEqual(content, self.root)


class _FakeDM:
    def __init__(self):
        self.tasks = []

    def on_progress(self, *a, **k):
        pass

    def cancel(self):
        return False

    def download_all(self, tasks, message=""):
        self.tasks.extend(tasks)
        for task in tasks:
            dest = Path(task[1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("x", encoding="utf-8")


class _BackendShim:
    """借 BackendAPI 的方法但不构造 QObject（真 __init__ 会扫盘、起线程）。"""

    _install_modpack_impl = backend_mod.BackendAPI._install_modpack_impl

    def __init__(self, inst):
        self._inst = inst
        self._last_installed = {}

    def _instance(self, name=None):
        return self._inst

    def _dm(self, progress, log):
        return _FakeDM()


class BackendPassThroughTests(unittest.TestCase):
    """界面上勾的那两项要原样送到安装器，别在半路掉了。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_pack_be_")
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / ".minecraft"
        root.mkdir(parents=True)
        self.api = _BackendShim(_FakeInstance(root))
        self.pack = root / "p.mrpack"
        self.pack.write_text("x", encoding="utf-8")

    def run_install(self, extra):
        meta = {"name": "Pack", "version_id": "我的整合包", "instance": ".minecraft"}
        with mock.patch.object(backend_mod.modpack_mod, "install_local_pack",
                               return_value=meta) as installer:
            self.api._install_modpack_impl(
                lambda *a, **k: None, lambda *a, **k: None,
                str(self.pack), "本地", extra)
        self.assertEqual(installer.call_count, 1)
        return installer.call_args.kwargs

    def test_defaults_to_isolated(self):
        kwargs = self.run_install({"path": str(self.pack)})
        self.assertTrue(kwargs["isolate"], "整合包默认独立成一版")
        self.assertEqual(kwargs["version_name"], "")

    def test_passes_dialog_choices(self):
        kwargs = self.run_install({"path": str(self.pack),
                                   "version_name": "  我的整合包 ", "isolate": True})
        self.assertEqual(kwargs["version_name"], "我的整合包")
        self.assertTrue(kwargs["isolate"])

    def test_isolation_can_be_turned_off(self):
        kwargs = self.run_install({"path": str(self.pack), "isolate": False})
        self.assertFalse(kwargs["isolate"])

    def test_remembers_installed_version_id(self):
        self.run_install({"path": str(self.pack)})
        self.assertEqual(self.api._last_installed.get("version"), "我的整合包")


class LocalPackDispatchTests(unittest.TestCase):
    """本地包挑哪个安装器：按包里的索引文件认，不按后缀。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_pack_pick_")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def zip_with(self, name: str, members: dict) -> Path:
        import zipfile

        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as z:
            for rel, content in members.items():
                z.writestr(rel, content)
        return path

    def picked(self, source) -> str:
        with mock.patch.object(mp, "install_mrpack", return_value={}) as mr, \
             mock.patch.object(mp, "install_cf_zip", return_value={}) as cf:
            mp.install_local_pack(None, str(source), None, isolate=True, version_name="x")
        self.assertEqual(mr.call_count + cf.call_count, 1)
        picked = mr if mr.call_count else cf
        self.assertTrue(picked.call_args.kwargs["isolate"])
        self.assertEqual(picked.call_args.kwargs["version_name"], "x")
        return "mrpack" if mr.call_count else "cf"

    def test_mrpack_file(self):
        self.assertEqual(self.picked(
            self.zip_with("p.mrpack", {"modrinth.index.json": "{}"})), "mrpack")

    def test_mrpack_renamed_to_zip(self):
        self.assertEqual(self.picked(
            self.zip_with("p.zip", {"modrinth.index.json": "{}"})), "mrpack")

    def test_curseforge_zip(self):
        self.assertEqual(self.picked(
            self.zip_with("p.zip", {"manifest.json": "{}"})), "cf")

    def test_unpacked_mrpack_folder(self):
        folder = self.tmp / "unpacked"
        (folder / "overrides").mkdir(parents=True)
        (folder / "modrinth.index.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.picked(folder), "mrpack")

    def test_minecraft_folder(self):
        folder = self.tmp / "整合包"
        (folder / "mods").mkdir(parents=True)
        self.assertEqual(self.picked(folder), "cf")

    def test_missing_path(self):
        with self.assertRaises(mp.ModpackError):
            mp.install_local_pack(None, str(self.tmp / "nope.zip"), None)

    def test_folder_inside_game_dir_refused(self):
        root = self.tmp / ".minecraft"
        (root / "mods").mkdir(parents=True)
        inst = _FakeInstance(root)
        for target in (root, root / "mods"):
            with self.assertRaises(mp.ModpackError):
                mp.install_local_pack(None, str(target), inst)

    def test_folder_holding_game_dir_refused(self):
        # 反过来套：游戏目录在拖进来的文件夹里面，拷贝的落点就在源里
        root = self.tmp / "MC" / ".minecraft"
        (root / "mods").mkdir(parents=True)
        with self.assertRaises(mp.ModpackError):
            mp.install_local_pack(None, str(self.tmp / "MC"), _FakeInstance(root))


class _StubInstaller:
    """替掉真安装器：把版本 json 摆好就行，不联网、不下载。"""

    def __init__(self, instance, dm, on_progress=None, cancel=None):
        self.instance = instance

    def install_version(self, mc_version, force=False, java=None):
        _write_version_json(self.instance, mc_version)
        return mc_version

    def _note(self, *a, **k):
        pass


class UnpackedFolderInstallTests(unittest.TestCase):
    """拖进来的是已经解开的包目录：内容进新版本，人家的文件夹一个字节都不许动。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pymcl_unpacked_")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / ".minecraft"
        self.root.mkdir(parents=True)
        self.inst = _FakeInstance(self.root)
        self.dm = _FakeDM()
        for patch in (
            mock.patch.object(mp, "Installer", _StubInstaller),
            mock.patch.object(mp, "install_loader", self.fake_loader),
            mock.patch.object(mp, "_resolve_pack_minecraft",
                              lambda dm, declared, on_progress=None: declared or None),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def fake_loader(self, installer, loader, version, mc_version, force=False):
        vid = f"{mc_version}-{loader}-{version}"
        _write_version_json(self.inst, vid)
        return vid

    def unpacked_mrpack(self) -> Path:
        src = self.tmp / "Test Pack 1.0"
        (src / "overrides" / "config").mkdir(parents=True)
        (src / "overrides" / "config" / "a.toml").write_text("x", encoding="utf-8")
        (src / "modrinth.index.json").write_text(json.dumps({
            "formatVersion": 1, "name": "Test Pack", "versionId": "1.0",
            "dependencies": {"minecraft": "1.20.1", "forge": "47.2.0"},
            "files": [{"path": "mods/a.jar", "downloads": ["https://example.invalid/a.jar"]}],
        }), encoding="utf-8")
        return src

    def minecraft_folder(self) -> Path:
        src = self.tmp / "整合包"
        (src / "mods").mkdir(parents=True)
        (src / "mods" / "a.jar").write_text("x", encoding="utf-8")
        (src / "config").mkdir()
        (src / "config" / "t.toml").write_text("y", encoding="utf-8")
        vdir = src / "versions" / "1.20.1-forge-47.2.0"
        vdir.mkdir(parents=True)
        (vdir / "1.20.1-forge-47.2.0.json").write_text(
            json.dumps({"id": "1.20.1-forge-47.2.0", "inheritsFrom": "1.20.1"}),
            encoding="utf-8")
        return src

    def snapshot(self, folder: Path) -> list[str]:
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))

    def test_unpacked_mrpack_lands_in_the_new_version(self):
        src = self.unpacked_mrpack()
        meta = mp.install_local_pack(self.dm, str(src), self.inst,
                                     isolate=True, version_name="我的整合包")
        content = self.inst.versions_dir() / "我的整合包"

        self.assertEqual(meta["version_id"], "我的整合包")
        self.assertEqual(vs.load(self.inst, "我的整合包")["isolation"], vs.ISOLATION_ALL)
        # 索引里的模组下进这一版自己的 mods，不是公共 .minecraft/mods
        self.assertEqual([Path(t[1]) for t in self.dm.tasks],
                         [(content / "mods" / "a.jar").resolve()])
        self.assertTrue((content / "config" / "a.toml").is_file(), "overrides 也归这一版")
        self.assertFalse((self.root / "config" / "a.toml").exists())

    def test_unpacked_minecraft_folder_lands_in_the_new_version(self):
        src = self.minecraft_folder()
        meta = mp.install_local_pack(self.dm, str(src), self.inst,
                                     isolate=True, version_name="我的整合包")
        content = self.inst.versions_dir() / "我的整合包"

        self.assertEqual(meta["source"], "plain-zip")
        self.assertEqual(meta["version_id"], "我的整合包")
        self.assertTrue((content / "mods" / "a.jar").is_file())
        self.assertTrue((content / "config" / "t.toml").is_file())
        self.assertFalse((self.root / "mods" / "a.jar").exists(), "别倒进公共 mods")

    def test_source_folder_is_left_alone(self):
        for make in (self.unpacked_mrpack, self.minecraft_folder):
            with self.subTest(make.__name__):
                src = make()
                before = self.snapshot(src)
                mp.install_local_pack(self.dm, str(src), self.inst,
                                      isolate=True, version_name=f"包-{make.__name__}")
                self.assertEqual(self.snapshot(src), before,
                                 "解开的包目录是用户自己的文件夹，装完不能少东西")


if __name__ == "__main__":
    unittest.main()
