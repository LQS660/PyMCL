# -*- coding: utf-8 -*-
"""Launch the EziApp UI with an authenticated, per-process PyMCL bridge."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, urlunparse


ROOT = Path(__file__).resolve().parent
LOOPBACK_HOST = "127.0.0.1"


def _ui_origin(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != LOOPBACK_HOST
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"UI URL must be served from http://{LOOPBACK_HOST}: {url!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid UI URL port: {url!r}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"invalid UI URL port: {url!r}")
    return f"http://{LOOPBACK_HOST}" + (f":{port}" if port is not None else "")


def _runtime_fragment(config: dict[str, str]) -> str:
    raw = json.dumps(config, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return "pymcl_bridge=" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _with_runtime_config(url: str, config: dict[str, str]) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=_runtime_fragment(config)))


def _safe_display_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _make_static_handler(directory: Path, bridge_config: dict[str, str]):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, fmt, *args):
            # Keep diagnostics useful without ever logging a configuration URL
            # or its launch token.
            sys.stderr.write(f"[eziapp] {self.command} {urlparse(self.path).path}\n")

        def do_GET(self):
            if urlparse(self.path).path != "/bridge-config.json":
                super().do_GET()
                return
            raw = json.dumps(bridge_config, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def _start_static(directory: Path, bridge_config: dict[str, str]):
    httpd = ThreadingHTTPServer((LOOPBACK_HOST, 0), _make_static_handler(directory, bridge_config))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name="eziapp-static")
    thread.start()
    return httpd


def _start_bridge(token: str, allowed_origin: str):
    from bridge.server import BridgeState, _prepare_root, create_http_server

    _prepare_root(ROOT)
    from bridge.api import BackendAPI, EventBus

    bus = EventBus()
    api = BackendAPI(bus)
    state = BridgeState(api, bus, token=token, allowed_origins=[allowed_origin])
    httpd = create_http_server(LOOPBACK_HOST, 0, state)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name="pymcl-bridge")
    thread.start()
    return httpd


def _shutdown(httpd):
    if not httpd:
        return
    try:
        httpd.shutdown()
    finally:
        httpd.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Launch PyMCL EziApp with a private local bridge")
    parser.add_argument("--ui-url", help="已运行的本机开发 UI 地址；省略时启动 eziapp/dist")
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器")
    args = parser.parse_args(argv)

    static_server = None
    bridge_server = None
    token = secrets.token_urlsafe(32)
    bridge_config: dict[str, str] = {}
    try:
        dist_dir = ROOT / "eziapp" / "dist"
        if args.ui_url:
            ui_url = args.ui_url
            ui_origin = _ui_origin(ui_url)
        elif dist_dir.is_dir():
            static_server = _start_static(dist_dir, bridge_config)
            _, static_port = static_server.server_address[:2]
            ui_url = f"http://{LOOPBACK_HOST}:{static_port}/"
            ui_origin = _ui_origin(ui_url)
        else:
            # Vite's regular development address. The launch config is passed
            # in the fragment so it is never sent to, or stored by, Vite.
            ui_url = f"http://{LOOPBACK_HOST}:5178/"
            ui_origin = _ui_origin(ui_url)
            print("[EziApp] 未找到构建产物 dist/，请先启动开发服务器: cd eziapp && npm run dev")

        bridge_server = _start_bridge(token, ui_origin)
        _, bridge_port = bridge_server.server_address[:2]
        bridge_config.update({"rpc_url": f"http://{LOOPBACK_HOST}:{bridge_port}", "token": token})
        launch_url = _with_runtime_config(ui_url, bridge_config) if args.ui_url or static_server is None else ui_url

        print(f"PYMCL_BRIDGE port={bridge_port} host={LOOPBACK_HOST} root={ROOT} auth=token")
        print(f"EziApp UI: {_safe_display_url(launch_url)}")
        if not args.no_browser:
            webbrowser.open(launch_url)
        print("按 Ctrl+C 退出")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("退出")
    finally:
        _shutdown(bridge_server)
        _shutdown(static_server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
