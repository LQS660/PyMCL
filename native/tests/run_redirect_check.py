# -*- coding: utf-8 -*-
"""P2-5 端到端判别：HTTPS 源被 302 到明文 HTTP 时，WinHTTP 是否跟随降级。

拓扑（真实 HTTPS 源，不是本地模拟）：
    harness --https--> httpbin.org/redirect-to?url=http://127.0.0.1:<port>/leak
                       └─ 302 Location: http://127.0.0.1:<port>/leak
    harness --http-->  本地明文服务器（若跟随了降级就会命中，日志里能看到请求）

改前 policy=ALWAYS(2)：跟随降级 → rc=0 status=200，正文是本地明文服务器的内容，
                        且本地服务器日志里出现 /leak
改后 policy=DISALLOW_HTTPS_TO_HTTP(1)：不跟随 → 拿到 302 本身（WinHTTP 把 302 原样返回），
                        本地服务器日志里**没有**任何请求

用法：python native/tests/run_redirect_check.py <harness.exe> [--expect-fixed]
"""
from __future__ import annotations

import http.server
import subprocess
import sys
import threading
import time

HARNESS = sys.argv[1]
FIXED = "--expect-fixed" in sys.argv

hits: list[str] = []


class Plain(http.server.BaseHTTPRequestHandler):
    """明文 HTTP 目标：跟随降级才会命中它。"""
    def do_GET(self):  # noqa: N802
        hits.append(self.path)
        body = b"PLAINTEXT-DOWNGRADE-TARGET"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Plain)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

target = f"http://127.0.0.1:{port}/leak"
# 注意：这里故意**不做 percent-encoding**。http.c 的 parse_url 用
# WinHttpCrackUrl(..., ICU_ESCAPE, ...) 解析 URL，会把 %3A%2F%2F 解错，
# 导致 httpbin 收到一个畸形 url 参数并回 404（实测）。用裸的 : 和 / 才能
# 让 httpbin 正确发出 302 Location —— 这是被 WinHTTP 客户端真实使用的形态。
url = "https://httpbin.org/redirect-to?url=" + target
print(f"plaintext target : {target}")
print(f"https redirector : {url}")

p = subprocess.run([HARNESS, url, "30"], capture_output=True, text=True, timeout=120)
print("\n--- harness ---")
print(p.stdout.strip())
if p.stderr.strip():
    print("[stderr]", p.stderr.strip()[:400])

time.sleep(1.0)
print(f"\nplaintext server hits = {len(hits)} {hits}")

srv.shutdown()
followed = len(hits) > 0
print("\n=== 结论 ===")
if followed:
    print("降级被跟随：请求落到了明文 http:// 目标（改前的 ALWAYS 行为）")
else:
    print("降级被拦截：没有请求落到明文 http:// 目标")

# ---- 回归：合法的同协议 / HTTP→HTTPS 重定向必须仍然跟随 ----
# 注意 DISALLOW_HTTPS_TO_HTTP 只拦「安全源 → 明文目标」，正常重定向不受影响。
# 用一个 302 到 https://example.com 的 HTTPS 源来确认没有把重定向整体关掉。
print("\n=== 回归：HTTPS→HTTPS 同协议重定向 ===")
# 目标页正文开头就带 marker，harness 只打印前 120 字节也能看到；
# 若没有跟随重定向，harness 会拿到 302 而不是 200。
up = subprocess.run([HARNESS, "https://httpbin.org/redirect-to?url=https://httpbin.org/get?marker=same-scheme-ok",
                     "30"], capture_output=True, text=True, timeout=120)
print(up.stdout.strip())
up_ok = "rc=0" in up.stdout and "status=200" in up.stdout and "same-scheme-ok" in up.stdout
print("HTTPS→HTTPS 跟随:", "OK" if up_ok else "FAILED")

print("\n=== 回归：HTTP→HTTPS 升级重定向（本地明文源 302 到 https）===")
class Up(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(302)
        self.send_header("Location", "https://httpbin.org/get?marker=http-upgrade-ok")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


us = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up)
uport = us.server_address[1]
threading.Thread(target=us.serve_forever, daemon=True).start()
p3 = subprocess.run([HARNESS, f"http://127.0.0.1:{uport}/up", "30"],
                    capture_output=True, text=True, timeout=120)
print(p3.stdout.strip())
us.shutdown()
upg_ok = "rc=0" in p3.stdout and "status=200" in p3.stdout and "http-upgrade-ok" in p3.stdout
print("HTTP→HTTPS 跟随:", "OK" if upg_ok else "FAILED")

if FIXED:
    ok = (not followed) and up_ok and upg_ok
    print("RESULT:", "PASS" if ok else
          f"FAIL(followed={followed} same_scheme_ok={up_ok} upgrade_ok={upg_ok})")
    sys.exit(0 if ok else 1)
else:
    print("RESULT:", "REPRODUCED" if followed else "not reproduced")
    sys.exit(0)
