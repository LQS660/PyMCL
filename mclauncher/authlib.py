# -*- coding: utf-8 -*-
"""authlib-injector + Yggdrasil 皮肤站登录。"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import utils
from .auth import AuthError
from .downloader import DownloadManager

LATEST = "https://authlib-injector.yushi.moe/artifact/latest.json"
BMCL_LATEST = "https://bmclapi2.bangbang93.com/mirrors/authlib-injector/artifact/latest.json"
PRESETS = [
    ("Little Skin", "https://littleskin.cn/api/yggdrasil"),
    ("Blessing Skin（自填）", ""),
]


def normalize_api(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        raise AuthError("请填写皮肤站 Yggdrasil API 地址")
    if not raw.startswith("http"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        raise AuthError("皮肤站地址无效")
    return raw


def injector_path() -> Path:
    return utils.ROOT / "authlib-injector.jar"


def ensure_injector(dm: DownloadManager | None = None, on_note=None) -> Path:
    dest = injector_path()
    if dest.is_file() and dest.stat().st_size > 10_000:
        return dest
    dm = dm or DownloadManager(threads=2)
    last = None
    for url in (BMCL_LATEST, LATEST):
        try:
            meta = dm.fetch_json(url, timeout=20)
            download = (meta or {}).get("download_url") or (meta or {}).get("url")
            if not download:
                continue
            if on_note:
                on_note("下载 authlib-injector")
            dm.download(download, dest)
            if dest.is_file():
                return dest
        except Exception as exc:
            last = exc
    raise AuthError(f"无法下载 authlib-injector: {last}")


def javaagent_arg(api: str) -> str:
    return f"-javaagent:{injector_path()}={normalize_api(api)}"


def _post(api: str, path: str, payload: dict) -> dict:
    url = normalize_api(api) + path
    try:
        resp = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        raise AuthError(f"皮肤站无法连接: {exc}") from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        err = data.get("errorMessage") or data.get("error") or resp.text[:200]
        raise AuthError(f"皮肤站登录失败: {err}")
    return data


def login(api: str, username: str, password: str) -> dict:
    api = normalize_api(api)
    username = (username or "").strip()
    if not username or not password:
        raise AuthError("请输入皮肤站账号和密码")
    data = _post(api, "/authserver/authenticate", {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username,
        "password": password,
        "requestUser": True,
    })
    profile = data.get("selectedProfile") or {}
    if not profile:
        profiles = data.get("availableProfiles") or []
        if profiles:
            profile = profiles[0]
    if not profile.get("name"):
        raise AuthError("皮肤站没有可用角色，请先在网站创建角色")
    return {
        "type": "authlib",
        "name": profile.get("name"),
        "uuid": utils.dashed_uuid(profile.get("id") or ""),
        "access_token": data.get("accessToken") or "0",
        "client_token": data.get("clientToken") or "",
        "api": api,
        "username": username,
        "expires_at": time.time() + 7 * 24 * 3600,
        "updated_at": time.time(),
    }


def refresh(account: dict) -> dict:
    api = normalize_api(account.get("api") or "")
    token = account.get("access_token")
    if not token:
        raise AuthError("皮肤站令牌缺失，请重新登录")
    payload = {"accessToken": token, "requestUser": True}
    if account.get("client_token"):
        payload["clientToken"] = account["client_token"]
    data = _post(api, "/authserver/refresh", payload)
    profile = data.get("selectedProfile") or {}
    account.update({
        "access_token": data.get("accessToken") or token,
        "client_token": data.get("clientToken") or account.get("client_token") or "",
        "name": profile.get("name") or account.get("name"),
        "uuid": utils.dashed_uuid(profile.get("id") or account.get("uuid") or ""),
        "expires_at": time.time() + 7 * 24 * 3600,
        "updated_at": time.time(),
    })
    return account
