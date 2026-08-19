# -*- coding: utf-8 -*-
"""本机 HTTP JSON-RPC + SSE。不依赖 PySide6 / qfluentwidgets。"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def _prepare_root(root: Path):
    root = root.resolve()
    os.environ["PYMCL_HOME"] = str(root)
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(type(obj).__name__)


class BridgeState:
    def __init__(self, api, bus):
        self.api = api
        self.bus = bus


def make_handler(state: BridgeState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("[bridge] " + (fmt % args) + "\n")

        def _send(self, code: int, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj):
            raw = json.dumps(obj, ensure_ascii=False, default=_json_default).encode("utf-8")
            self._send(code, raw, "application/json; charset=utf-8")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/health", "/"):
                self._send_json(200, {"ok": True, "name": "pymcl-bridge"})
                return
            if path == "/events":
                self._sse()
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/rpc", "/"):
                self._send_json(404, {"error": "not found"})
                return
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                req = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}})
                return
            rid = req.get("id")
            method = req.get("method")
            params = req.get("params") or {}
            if not method or not isinstance(method, str):
                self._send_json(400, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "method required"}})
                return
            if method.startswith("_"):
                self._send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "hidden method"}})
                return
            fn = getattr(state.api, method, None)
            if not callable(fn):
                self._send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method: {method}"}})
                return
            try:
                if isinstance(params, list):
                    result = fn(*params)
                elif isinstance(params, dict):
                    result = _call_kwargs(fn, params)
                else:
                    raise TypeError("params must be object or array")
            except Exception as exc:  # noqa: BLE001
                self._send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(exc)}})
                return
            self._send_json(200, {"jsonrpc": "2.0", "id": rid, "result": result})

        def _sse(self):
            q = state.bus.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                hello = json.dumps({"ok": True}, ensure_ascii=False)
                self.wfile.write(f"event: hello\ndata: {hello}\n\n".encode("utf-8"))
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    ev = payload.get("event") or "message"
                    data = json.dumps(payload.get("data") or {}, ensure_ascii=False, default=_json_default)
                    self.wfile.write(f"event: {ev}\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                state.bus.unsubscribe(q)

    return Handler


def _call_kwargs(fn, params: dict):
    sig = inspect.signature(fn)
    accepted = {}
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        if name in params:
            accepted[name] = params[name]
        elif p.kind == inspect.Parameter.VAR_KEYWORD:
            accepted.update({k: v for k, v in params.items() if k not in accepted})
    return fn(**accepted)


def main(argv=None):
    parser = argparse.ArgumentParser(description="PyMCL WinUI bridge")
    parser.add_argument("--root", required=True, help="启动器根目录，与 Qt 版共用 .minecraft/java/config.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = 自动分配")
    args = parser.parse_args(argv)

    root = _prepare_root(Path(args.root))
    from mclauncher.guard import install as install_guard
    install_guard(root / "pymcl-error.log")
    from bridge.api import BackendAPI, EventBus  # noqa: WPS433

    bus = EventBus()
    api = BackendAPI(bus)
    state = BridgeState(api, bus)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    host, port = httpd.server_address[:2]
    banner = f"PYMCL_BRIDGE port={port} host={host} root={root}\n"
    sys.stdout.write(banner)
    sys.stdout.flush()
    sys.stderr.write(banner)
    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
