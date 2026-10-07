# -*- coding: utf-8 -*-
"""联网方法录制回放服务器（GOAL 4.B：联网对拍必须可重复）。

用法：
    python tests/fixtures/http_replay_server.py --db tests/fixtures/http_replay_db.json --mode record
    python tests/fixtures/http_replay_server.py --db tests/fixtures/http_replay_db.json --mode play

配合环境变量 PYMCL_HTTP_REPLAY=http://127.0.0.1:18771 使用：
被测桥（C 与 Python）出网请求被钩子改写到本服务器，并带上
X-PyMCL-Replay-Url: <原始URL> 头。record 模式由本服务器代发真实请求并落库；
play 模式按 (method, url, body-hash) 查库回放。数据库是普通 JSON，可入库复用。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_LOCK = threading.Lock()
DB: dict = {}
DB_PATH = ""
MODE = "play"
HOP_HEADERS = {"content-length", "host", "connection", "accept-encoding",
               "x-pymcl-replay-url", "transfer-encoding"}
# 直连转发：系统代理会把 127.0.0.1 也劫持走（与 mclauncher/net.py 强制直连同因）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def db_key(method: str, url: str, body: bytes) -> str:
    # key 归一：URL 百分号解码（两侧桥编码习惯不同：requests 编码 ["]，WinHTTP 原样发）；
    # 不掺 body hash——POST 体里有 device_id/sysinfo 等两侧必然不同的动态内容，
    # 对拍场景同一 URL 的响应都来自同一个 mock，回放同一条即可。
    from urllib.parse import unquote
    return f"{method} {unquote(url)}"


def persist() -> None:
    # 调用方必须已持有 DB_LOCK（threading.Lock 不可重入，这里绝不能再抢）
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=1, sort_keys=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静默
        pass

    def _handle(self):
        import faulthandler
        faulthandler.dump_traceback_later(4, exit=False, file=sys.stderr)
        print("[replay] handle enter", self.command, self.path, file=sys.stderr, flush=True)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        orig_url = self.headers.get("X-PyMCL-Replay-Url") or self.path
        print("[replay] forward to", orig_url, file=sys.stderr, flush=True)
        clean_headers = {k: v for k, v in self.headers.items()
                         if k.lower() not in HOP_HEADERS}
        key = db_key(self.command, orig_url, body)

        with DB_LOCK:
            cached = DB.get(key)
        if MODE == "record" and cached is not None:
            # 幂等录制：库里有就直接回放，两侧桥不因网络抖动产生差异
            status, payload = cached["status"], base64.b64decode(cached["body"])
            print(f"[replay:record-hit] {key[:100]}", file=sys.stderr, flush=True)
        elif MODE == "record":
            req = urllib.request.Request(orig_url, data=body if body else None,
                                         method=self.command)
            for k, v in clean_headers.items():
                req.add_header(k, v)
            try:
                with OPENER.open(req, timeout=30) as resp:
                    payload = resp.read()
                    entry = {"status": resp.status, "body": base64.b64encode(payload).decode()}
            except urllib.error.HTTPError as e:
                payload = e.read()
                entry = {"status": e.code, "body": base64.b64encode(payload).decode()}
            except Exception as e:
                entry = {"status": 0, "body": base64.b64encode(str(e).encode()).decode()}
            with DB_LOCK:
                DB[key] = entry
                persist()
            status, payload = entry["status"], base64.b64decode(entry["body"])
            print(f"[replay:record] {key} -> {status} ({len(payload)}B)", file=sys.stderr, flush=True)
        else:
            with DB_LOCK:
                entry = DB.get(key)
            if entry is None:
                status, payload = 599, f"replay miss: {key}".encode()
                print(f"[replay:play] MISS {key}", file=sys.stderr, flush=True)
            else:
                status, payload = entry["status"], base64.b64decode(entry["body"])

        self.send_response(status if status >= 200 else 502)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = _handle


def main() -> int:
    global DB_PATH, MODE
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--mode", choices=("record", "play"), default="play")
    ap.add_argument("--port", type=int, default=18771)
    args = ap.parse_args()
    DB_PATH, MODE = args.db, args.mode
    try:
        with open(DB_PATH, encoding="utf-8") as f:
            DB.update(json.load(f))
    except Exception:
        pass
    print(f"[replay] mode={MODE} db={DB_PATH} entries={len(DB)}", file=sys.stderr, flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
