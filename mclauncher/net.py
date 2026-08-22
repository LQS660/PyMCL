# -*- coding: utf-8 -*-
"""网络策略：默认跟随系统代理（和 PCL 一样）。关闭后才直连。"""

from __future__ import annotations

import os

_PROXY_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
)

_direct = False


def use_system_proxy() -> bool:
    try:
        from .config import CONFIG
        return bool(CONFIG.get("use_system_proxy", True))
    except Exception:
        return True


def force_direct() -> bool:
    return (not use_system_proxy()) or _direct


def apply_direct_to_session(session):
    if force_direct():
        session.trust_env = False
        session.proxies = {"http": None, "https": None}


def apply_proxy_policy():
    """按设置决定是否忽略系统/环境代理。"""
    global _direct
    if use_system_proxy():
        _direct = False
        return
    _install_direct()


def _patch_requests():
    """把直连策略打进 requests.Session（幂等）。"""
    import requests
    orig = requests.Session.__init__
    if getattr(orig, "_pymcl_direct", False):
        return

    def _init(self, *args, **kwargs):
        orig(self, *args, **kwargs)
        self.trust_env = False
        self.proxies = {"http": None, "https": None}

    _init._pymcl_direct = True
    requests.Session.__init__ = _init


class _RequestsDirectSpy:
    """直连模式下盯住 requests：它真正被导入时再打 Session 补丁。

    以前 _install_direct 里直接 `import requests`，导致 GUI 启动链
    （mclauncher/__init__ -> apply_proxy_policy）每次都把 requests
    整个拉起来。环境代理键已被清空 + NO_PROXY=*，补丁晚一点打没有窗口期。
    """

    def find_spec(self, name, path=None, target=None):
        if name != "requests":
            return None
        import sys
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        import importlib
        module = importlib.import_module("requests")
        _patch_requests()
        return module.__spec__


def _install_direct():
    global _direct
    if _direct:
        return
    _direct = True
    for key in _PROXY_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    import urllib.request
    urllib.request.getproxies = lambda: {}
    if hasattr(urllib.request, "getproxies_environment"):
        urllib.request.getproxies_environment = lambda: {}
    if hasattr(urllib.request, "getproxies_registry"):
        urllib.request.getproxies_registry = lambda: {}

    import sys
    if "requests" in sys.modules:
        _patch_requests()
        return
    sys.meta_path.insert(0, _RequestsDirectSpy())
