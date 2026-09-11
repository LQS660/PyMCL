"""离线账号自定义皮肤：文件校验、本地 Yggdrasil 服务、启动参数注入。

1.19.3 起内置默认皮肤从 Steve/Alex 两种扩到九种，靠挑 UUID 凑默认皮肤的老办法
在 1.20.1 上已经失效。这里守住新方案的三段：皮肤文件收得对、本地 Yggdrasil 返回
的 textures 能被验签、启动命令真的挂上了 authlib-injector。
"""
from __future__ import annotations

import base64
import json
import struct
import unittest
import urllib.request
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from mclauncher import launcher, skin as skin_mod, skinserver, utils


def make_png(width: int = 64, height: int = 64, rgba: bytes = b"\x3c\x8d\x6e\xff") -> bytes:
    """手搓一张纯色 PNG，省得为测试引入 Pillow。"""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + rgba * width          # 每行前缀 0 = 不过滤
    idat = zlib.compress(row * height, 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class _IsolatedRoot(unittest.TestCase):
    """把 utils.ROOT 挪到临时目录，别让测试往仓库里写 skins/。"""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(utils, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)


class TestSkinFile(_IsolatedRoot):
    def test_accepts_both_legal_sizes(self):
        for w, h in ((64, 64), (64, 32)):
            with self.subTest(size=f"{w}x{h}"):
                self.assertEqual(skin_mod.validate_skin(make_png(w, h)), (w, h))

    def test_rejects_wrong_size(self):
        with self.assertRaises(skin_mod.SkinError):
            skin_mod.validate_skin(make_png(32, 32))

    def test_rejects_non_png(self):
        with self.assertRaises(skin_mod.SkinError):
            skin_mod.validate_skin(b"GIF89a this is not a png")

    def test_import_copies_into_skins_dir(self):
        src = self.root / "outside.png"
        src.write_bytes(make_png())
        name = skin_mod.import_skin("Steve", src)
        self.assertTrue((skin_mod.skins_dir() / name).is_file())
        self.assertEqual(skin_mod.load_skin_png({"skin_file": name}), src.read_bytes())

    def test_import_sanitises_account_name(self):
        src = self.root / "s.png"
        src.write_bytes(make_png())
        name = skin_mod.import_skin("../../evil name", src)
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)

    def test_skin_file_never_escapes_skins_dir(self):
        # 配置里塞相对路径也只能落在 skins/ 里，取不到外面的文件
        (self.root / "secret.png").write_bytes(make_png())
        self.assertIsNone(skin_mod.skin_file_for({"skin_file": "../secret.png"}))

    def test_missing_file_degrades_to_none(self):
        self.assertIsNone(skin_mod.load_skin_png({"skin_file": "nope.png"}))
        self.assertIsNone(skin_mod.load_skin_png({}))

    def test_model_defaults_to_classic(self):
        self.assertEqual(skin_mod.skin_model({}), skin_mod.CLASSIC)
        self.assertEqual(skin_mod.skin_model({"skin_model": "SLIM"}), skin_mod.SLIM)


class TestSkinServer(_IsolatedRoot):
    """跑一个真的 HTTP 服务，按 Yggdrasil 规范逐个断言响应。"""

    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        # 4096 位生成太慢，测试里塞一把小钥匙；签名路径本身不关心位数
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(skinserver, "_private_key", self.key)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(skinserver.shutdown)
        self.png = make_png()
        self.uuid = utils.offline_uuid("Steve")
        self.api = skinserver.api_for(self.uuid, "Steve", self.png, skinserver.SLIM)

    def get(self, path: str):
        with urllib.request.urlopen(self.api + path, timeout=10) as resp:
            return resp.status, resp.read()

    def test_metadata_advertises_key_and_loopback_domain(self):
        status, body = self.get("/")
        meta = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("BEGIN PUBLIC KEY", meta["signaturePublickey"])
        # authlib-injector 拿材质 URL 的主机名比对这张白名单，缺了就不加载皮肤
        self.assertIn("127.0.0.1", meta["skinDomains"])

    def test_profile_carries_signed_textures(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        undashed = self.uuid.replace("-", "")
        status, body = self.get(f"/sessionserver/session/minecraft/profile/{undashed}")
        self.assertEqual(status, 200)
        doc = json.loads(body)
        self.assertEqual(doc["id"], undashed)
        self.assertEqual(doc["name"], "Steve")

        prop = doc["properties"][0]
        self.assertEqual(prop["name"], "textures")
        # 签名是对 base64 后的字符串算的，验不过客户端会直接忽略这张皮肤
        self.key.public_key().verify(
            base64.b64decode(prop["signature"]), prop["value"].encode("ascii"),
            padding.PKCS1v15(), hashes.SHA1())

        textures = json.loads(base64.b64decode(prop["value"]))
        self.assertEqual(textures["profileName"], "Steve")
        self.assertEqual(textures["textures"]["SKIN"]["metadata"]["model"], "slim")
        self.assertTrue(textures["textures"]["SKIN"]["url"].startswith(self.api + "/textures/"))

    def test_texture_url_serves_the_actual_png(self):
        _, body = self.get("/sessionserver/session/minecraft/profile/"
                           + self.uuid.replace("-", ""))
        url = json.loads(base64.b64decode(
            json.loads(body)["properties"][0]["value"]))["textures"]["SKIN"]["url"]
        with urllib.request.urlopen(url, timeout=10) as resp:
            self.assertEqual(resp.headers["Content-Type"], "image/png")
            self.assertEqual(resp.read(), self.png)

    def test_has_joined_resolves_by_username(self):
        status, body = self.get("/sessionserver/session/minecraft/hasJoined?username=Steve")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["name"], "Steve")

    def test_unknown_profile_returns_204(self):
        status, _ = self.get("/sessionserver/session/minecraft/hasJoined?username=Nobody")
        self.assertEqual(status, 204)

    def test_classic_model_omits_metadata(self):
        # 经典模型必须不写 metadata，写了 slim 以外的值客户端会当成宽臂以外的东西
        uuid = utils.offline_uuid("Wide")
        skinserver.api_for(uuid, "Wide", self.png, skinserver.CLASSIC)
        _, body = self.get("/sessionserver/session/minecraft/profile/"
                           + uuid.replace("-", ""))
        textures = json.loads(base64.b64decode(json.loads(body)["properties"][0]["value"]))
        self.assertNotIn("metadata", textures["textures"]["SKIN"])


class TestLaunchInjection(_IsolatedRoot):
    def test_no_skin_means_no_agent(self):
        self.assertEqual(launcher._offline_skin_api({}), "")
        self.assertEqual(launcher._offline_skin_api({"skin_file": ""}), "")

    def test_broken_skin_never_blocks_launch(self):
        # 文件不在了 / 起服务炸了，都只能是没皮肤，不能让启动失败
        self.assertEqual(launcher._offline_skin_api({"skin_file": "gone.png"}), "")
        with mock.patch.object(skinserver, "api_for", side_effect=RuntimeError("boom")):
            (skin_mod.skins_dir() / "ok.png").write_bytes(make_png())
            self.assertEqual(
                launcher._offline_skin_api({"skin_file": "ok.png", "name": "A"}), "")

    def test_configured_skin_produces_loopback_api(self):
        (skin_mod.skins_dir() / "ok.png").write_bytes(make_png())
        self.addCleanup(skinserver.shutdown)
        with mock.patch("mclauncher.authlib.ensure_injector", return_value=Path("x.jar")), \
             mock.patch.object(skinserver, "_private_key", mock.MagicMock()):
            api = launcher._offline_skin_api({
                "skin_file": "ok.png", "name": "Steve",
                "uuid": utils.offline_uuid("Steve"), "skin_model": "classic"})
        self.assertTrue(api.startswith("http://127.0.0.1:"))


class _AccountsStub:
    """够用的 AccountManager 替身：只要 get_account / save 两件事。"""

    def __init__(self, *accounts):
        self.accounts = list(accounts)
        self.active = accounts[0]["name"] if accounts else None
        self.saved = 0

    def get_account(self, name):
        return next((a for a in self.accounts if a.get("name") == name), None)

    def save(self):
        self.saved += 1


class TestSkinRpc(_IsolatedRoot):
    """桥接与 Qt 两套后端都得提供同一组皮肤方法，且语义一致。"""

    def _shim(self, backend_cls, *accounts):
        shim = type("Shim", (), {
            "set_account_skin": backend_cls.set_account_skin,
            "get_account_skin": backend_cls.get_account_skin,
            "_emit": lambda self, *a, **k: None,
            "_emit_ui_changed": lambda self, *a, **k: None,
        })()
        shim.accounts = _AccountsStub(*accounts)
        return shim

    def _backends(self):
        import bridge.api as bridge_api
        import app.backend as qt_backend
        return {"bridge": bridge_api.BackendAPI, "qt": qt_backend.BackendAPI}

    def test_both_backends_expose_the_same_methods(self):
        for label, cls in self._backends().items():
            with self.subTest(backend=label):
                self.assertTrue(callable(getattr(cls, "set_account_skin", None)))
                self.assertTrue(callable(getattr(cls, "get_account_skin", None)))

    def test_round_trip_via_base64(self):
        png = make_png()
        for label, cls in self._backends().items():
            with self.subTest(backend=label):
                api = self._shim(cls, {"name": "Zoe", "type": "offline"})
                out = api.set_account_skin(
                    "Zoe", data=base64.b64encode(png).decode(), model="slim")
                self.assertEqual(out["skin_model"], "slim")
                got = api.get_account_skin("Zoe")
                self.assertTrue(got["data_url"].startswith("data:image/png;base64,"))
                self.assertEqual(
                    base64.b64decode(got["data_url"].split(",", 1)[1]), png)

    def test_clearing_removes_file_and_keys(self):
        api = self._shim(self._backends()["bridge"], {"name": "Zoe", "type": "offline"})
        api.set_account_skin("Zoe", data=base64.b64encode(make_png()).decode())
        stored = skin_mod.skins_dir() / "Zoe.png"
        self.assertTrue(stored.is_file())
        api.set_account_skin("Zoe")
        self.assertFalse(stored.is_file())
        self.assertEqual(api.get_account_skin("Zoe")["skin_file"], "")

    def test_rejects_non_offline_accounts(self):
        api = self._shim(self._backends()["bridge"], {"name": "Real", "type": "microsoft"})
        with self.assertRaises(ValueError):
            api.set_account_skin("Real", data=base64.b64encode(make_png()).decode())

    def test_rejects_bad_payloads(self):
        api = self._shim(self._backends()["bridge"], {"name": "Zoe", "type": "offline"})
        with self.assertRaises(ValueError):
            api.set_account_skin("Ghost", data=base64.b64encode(make_png()).decode())
        with self.assertRaises(ValueError):
            api.set_account_skin("Zoe", data="not base64 at all!!")
        with self.assertRaises(skin_mod.SkinError):
            api.set_account_skin("Zoe", data=base64.b64encode(make_png(16, 16)).decode())

    def test_accepts_data_url_prefix(self):
        png = make_png()
        api = self._shim(self._backends()["bridge"], {"name": "Zoe", "type": "offline"})
        api.set_account_skin(
            "Zoe", data="data:image/png;base64," + base64.b64encode(png).decode())
        self.assertEqual(api.get_account_skin("Zoe")["skin_file"], "Zoe.png")


if __name__ == "__main__":
    unittest.main()
