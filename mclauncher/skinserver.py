# -*- coding: utf-8 -*-
"""离线账号的自定义皮肤：一个只听回环的 Yggdrasil 服务 + authlib-injector。

为什么需要它
------------
离线账号没有正版会话，客户端拿不到任何皮肤材质，只能按 UUID 落到内置默认皮肤。
1.19.3（22w45a）起内置默认皮肤从 Steve/Alex 两种扩到九种，选哪一种由
``DefaultPlayerSkin.getDefaultSkin(UUID)`` 的九路映射决定——老办法「挑一个奇偶性
合适的 UUID 来凑 Steve 或 Alex」在 1.20.1 上已经不成立了。

正经做法跟 HMCL / PCL2 一致：用 authlib-injector 把客户端对 Mojang 会话服务的请求
劫持到我们自己的 Yggdrasil 实现上，由它返回带签名的 textures 属性。皮肤图片也由
同一个服务发出去，全程不出本机。

边界
----
这个服务只听 127.0.0.1，**别的机器访问不到**。所以它解决的是单机和本机自己看到的
皮肤；联机时要让别人也看见，服务端必须挂同一个外置验证站，那不是启动器能代劳的。
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import utils

LOOPBACK = "127.0.0.1"
CLASSIC = "classic"
SLIM = "slim"


def skins_dir() -> Path:
    d = utils.ROOT / "skins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_path() -> Path:
    return skins_dir() / "yggdrasil_key.pem"


class SkinServerError(RuntimeError):
    pass


# ---------------------------------------------------------------- 签名密钥

_key_lock = threading.Lock()
_private_key = None


def _load_key():
    """RSA 私钥：生成一次就落盘复用（4096 位生成要几秒，不能每次启动都来一遍）。"""
    global _private_key
    with _key_lock:
        if _private_key is not None:
            return _private_key
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError as exc:  # pragma: no cover - 取决于运行环境
            raise SkinServerError(
                "自定义离线皮肤需要 cryptography 库：pip install cryptography"
            ) from exc

        path = _key_path()
        if path.is_file():
            try:
                _private_key = serialization.load_pem_private_key(
                    path.read_bytes(), password=None)
                return _private_key
            except Exception:
                # 密钥损坏就重新生成，没必要让用户手动删文件
                pass
        _private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        path.write_bytes(_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        return _private_key


def _public_key_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    return _load_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _sign(payload: str) -> str:
    """Yggdrasil 规范：对 base64 后的属性值做 SHA1withRSA，再 base64。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = _load_key().sign(payload.encode("ascii"), padding.PKCS1v15(), hashes.SHA1())
    return base64.b64encode(sig).decode("ascii")


# ---------------------------------------------------------------- 角色注册表

class Profile:
    __slots__ = ("uuid", "name", "png", "model", "digest")

    def __init__(self, uuid: str, name: str, png: bytes, model: str):
        self.uuid = utils.dashed_uuid(uuid).replace("-", "")
        self.name = name or "Player"
        self.png = png
        self.model = SLIM if str(model).lower() == SLIM else CLASSIC
        self.digest = hashlib.sha256(png).hexdigest()


_profiles: dict[str, Profile] = {}       # 无连字符 uuid -> Profile
_by_name: dict[str, Profile] = {}        # 小写名 -> Profile
_textures: dict[str, bytes] = {}         # digest -> png
_registry_lock = threading.Lock()


def register(uuid: str, name: str, png: bytes, model: str = CLASSIC) -> Profile:
    prof = Profile(uuid, name, png, model)
    with _registry_lock:
        _profiles[prof.uuid] = prof
        _by_name[prof.name.lower()] = prof
        _textures[prof.digest] = png
    return prof


def _find(uuid: str = "", name: str = "") -> Profile | None:
    key = utils.dashed_uuid(uuid or "").replace("-", "").lower()
    with _registry_lock:
        if key and key in _profiles:
            return _profiles[key]
        if name:
            return _by_name.get(name.lower())
    return None


# ---------------------------------------------------------------- HTTP

_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


def _texture_payload(prof: Profile, port: int) -> str:
    skin: dict = {"url": f"http://{LOOPBACK}:{port}/textures/{prof.digest}"}
    if prof.model == SLIM:
        # 经典模型不写 metadata，客户端按宽臂处理
        skin["metadata"] = {"model": SLIM}
    doc = {
        "timestamp": int(time.time() * 1000),
        "profileId": prof.uuid,
        "profileName": prof.name,
        "textures": {"SKIN": skin},
    }
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _profile_json(prof: Profile, port: int, signed: bool = True) -> dict:
    value = _texture_payload(prof, port)
    prop: dict = {"name": "textures", "value": value}
    if signed:
        prop["signature"] = _sign(value)
    return {"id": prof.uuid, "name": prof.name, "properties": [prop]}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PyMCLSkin/1"

    # 这个服务每局游戏要被客户端打好几次，默认的 stderr 日志纯属噪音
    def log_message(self, fmt, *args):
        pass

    # -- 输出小工具 ----------------------------------------------------
    def _send(self, code: int, body: bytes = b"", ctype: str = "application/json"):
        self.send_response(code)
        if body:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, doc):
        self._send(code, json.dumps(doc, ensure_ascii=False).encode("utf-8"))

    def _port(self) -> int:
        return int(self.server.server_address[1])

    # -- 路由 ----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/":
            self._json(200, {
                "meta": {
                    "serverName": "PyMCL 本地皮肤",
                    "implementationName": "pymcl-skinserver",
                    "implementationVersion": "1",
                },
                # authlib-injector 会拿材质 URL 的主机名比对这张白名单
                "skinDomains": [LOOPBACK, "localhost"],
                "signaturePublickey": _public_key_pem(),
            })
            return

        if path.startswith("/textures/"):
            digest = path.rsplit("/", 1)[-1]
            with _registry_lock:
                png = _textures.get(digest)
            if png is None:
                self._send(404)
                return
            self._send(200, png, "image/png")
            return

        if path.startswith("/sessionserver/session/minecraft/profile/"):
            prof = _find(uuid=path.rsplit("/", 1)[-1])
            if prof is None:
                self._send(204)
                return
            signed = (query.get("unsigned", ["false"])[0] or "").lower() != "true"
            self._json(200, _profile_json(prof, self._port(), signed))
            return

        if path == "/sessionserver/session/minecraft/hasJoined":
            prof = _find(name=(query.get("username") or [""])[0])
            if prof is None:
                self._send(204)
                return
            self._json(200, _profile_json(prof, self._port()))
            return

        self._send(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}

        if path == "/api/profiles/minecraft":
            names = body if isinstance(body, list) else []
            out = []
            for n in names:
                prof = _find(name=str(n))
                if prof is not None:
                    out.append({"id": prof.uuid, "name": prof.name})
            self._json(200, out)
            return

        # 加入服务器：本地服务不做校验，直接放行
        if path == "/sessionserver/session/minecraft/join":
            self._send(204)
            return

        if path.startswith("/authserver/"):
            action = path.rsplit("/", 1)[-1]
            if action in ("validate", "invalidate", "signout"):
                self._send(204)
                return
            prof = _find(name=str(body.get("username") or "")) or _first_profile()
            if prof is None:
                self._json(403, {"error": "ForbiddenOperationException",
                                 "errorMessage": "没有可用的离线角色"})
                return
            selected = {"id": prof.uuid, "name": prof.name}
            self._json(200, {
                "accessToken": body.get("accessToken") or "pymcl-offline",
                "clientToken": body.get("clientToken") or "pymcl",
                "selectedProfile": selected,
                "availableProfiles": [selected],
            })
            return

        self._send(404)


def _first_profile() -> Profile | None:
    with _registry_lock:
        return next(iter(_profiles.values()), None)


def ensure_running() -> str:
    """起服务（幂等），返回 authlib-injector 要用的 API 根地址。"""
    global _server
    with _server_lock:
        if _server is None:
            srv = ThreadingHTTPServer((LOOPBACK, 0), _Handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2},
                             daemon=True, name="pymcl-skinserver").start()
            _server = srv
        port = _server.server_address[1]
    return f"http://{LOOPBACK}:{port}"


def api_for(uuid: str, name: str, png: bytes, model: str = CLASSIC) -> str:
    """注册一个角色并确保服务在跑，返回 API 根地址。"""
    if not png:
        raise SkinServerError("皮肤数据为空")
    # 先摸一下密钥：缺 cryptography 要在这里就报出来，别等游戏起来了才发现没皮肤
    _load_key()
    register(uuid, name, png, model)
    return ensure_running()


def shutdown():
    global _server
    with _server_lock:
        srv, _server = _server, None
    if srv is not None:
        srv.shutdown()
        srv.server_close()
