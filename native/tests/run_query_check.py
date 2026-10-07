# -*- coding: utf-8 -*-
"""P2-8 端到端判别：http_get_query 超长时是否**真的把截断后的请求发出去了**。

起一个本地 http.server，把每个请求的路径长度记进日志，然后：
  1. 正常长度 query  → 期望 rc=0 且服务器收到请求（改前改后都应如此）
  2. 超长 query(5000) → 改前：rc=0 且服务器**收到**一个被截断的请求
                        改后：rc=-1 + error="URL 过长"，服务器**收不到**任何请求

用法：python native/tests/run_query_check.py <harness.exe> [--expect-fixed]
  不带 --expect-fixed 时只打印实测（给改前的 exe 用）
"""
from __future__ import annotations

import http.server
import os
import socket
import subprocess
import sys
import threading
import time

HARNESS = sys.argv[1]
FIXED = "--expect-fixed" in sys.argv

seen: list[tuple[str, int]] = []   # (method, path 长度)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        seen.append((self.command, len(self.path)))
        body = b'{"ok":true,"path_len":%d}' % len(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 静音
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}/api/v2/search"

print(f"local server on {base}")

results = {}


def run(label: str, query_bytes: int, fill: str = "a") -> tuple[int, int]:
    before = len(seen)
    p = subprocess.run([HARNESS, base, str(query_bytes), fill],
                       capture_output=True, text=True, timeout=60)
    out = (p.stdout or "").strip().replace("\n", " | ")
    time.sleep(0.4)   # 给服务器一点时间落日志
    new = len(seen) - before
    print(f"\n--- {label}: query_bytes={query_bytes} ---")
    print(f"harness: {out}")
    print(f"server requests received = {new}"
          + (f"  (path_len={seen[-1][1]})" if new else ""))
    results[label] = (p.returncode, new)
    return p.returncode, new


rc_ok, seen_ok = run("normal query", 60)
rc_big, seen_big = run("oversized query", 5000)
# 边界：刚好放得下（4095 - len("?") 的 URL 前缀之后）
rc_edge, seen_edge = run("edge query (fits)", 4000)

print("\n=== 汇总 ===")
for k, (rc, n) in results.items():
    print(f"{k:22s} rc={rc} requests_sent={n}")

srv.shutdown()

fail = 0
if rc_ok != 0 or seen_ok < 1:
    print("FAIL: 正常长度 query 未能正常请求")
    fail += 1
if FIXED:
    if rc_big == 0:
        print("FAIL: 超长 query 仍返回成功（应当报错）")
        fail += 1
    if seen_big != 0:
        print("FAIL: 超长 query 仍把（截断的）请求发了出去")
        fail += 1
else:
    if rc_big == 0 and seen_big >= 1:
        print("=> 复现：超长 query 被静默截断并发出（rc=0，服务器收到请求）")
    else:
        print("=> 本次未复现截断（异常）")
print("RESULT:", "PASS" if fail == 0 else f"FAIL({fail})")
sys.exit(1 if fail else 0)
