# -*- coding: utf-8 -*-
"""PyMCL 公益网关。

启动器只打这里，NewAPI 的 sk 只放在本机环境变量，不进 exe。
小白日常用量碰不到防刷阈值；对外文案永远是「网络繁忙」，不提额度。

  set NEWAPI_BASE_URL=https://your-newapi.example/v1
  set NEWAPI_API_KEY=sk-...
  set NEWAPI_MODEL=pymcl-assistant
  python ai_gateway/server.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def _load_env():
    p = ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

NEWAPI_BASE = os.environ.get("NEWAPI_BASE_URL", "").rstrip("/")
NEWAPI_KEY = os.environ.get("NEWAPI_API_KEY", "")
NEWAPI_MODEL = os.environ.get("NEWAPI_MODEL", "pymcl-assistant")
DEGRADE_MODEL = os.environ.get("NEWAPI_DEGRADE_MODEL", "") or NEWAPI_MODEL
BIND = os.environ.get("BIND", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787") or 8787)
RATE_PER_MIN = int(os.environ.get("RATE_PER_MIN", "40"))
RATE_PER_DAY = int(os.environ.get("RATE_PER_DAY", "800"))
MAX_INFLIGHT = int(os.environ.get("MAX_INFLIGHT", "4"))
MAX_BODY = int(os.environ.get("MAX_BODY", str(512 * 1024)))
# 单次回复上限：原来硬夹 2048，客户端改大也没用；改可配并默认放宽
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "8192") or 8192)
DEGRADE_AFTER = max(8, RATE_PER_MIN // 2)

# ---- 4.3 传输安全：TLS 或明确声明前置反代 ----
TLS_CERT = os.environ.get("GATEWAY_TLS_CERT", "")
TLS_KEY = os.environ.get("GATEWAY_TLS_KEY", "")
TRUST_PROXY = os.environ.get("GATEWAY_TRUST_PROXY", "") == "1"
# 仅本机调试逃生口：BIND 必须是回环地址才生效
ALLOW_INSECURE = os.environ.get("GATEWAY_ALLOW_INSECURE", "") == "1"


# ---------------------------------------------------------------- 4.3 可插拔鉴权

class Authenticator:
    """鉴权接口：check(headers) -> bool。headers 是 email.message.Message 风格。"""

    name = "base"

    def check(self, headers) -> bool:
        raise NotImplementedError


class ClientHeaderAuthenticator(Authenticator):
    """默认实现（向后兼容）：要求 X-PyMCL-Client: PyMCL/… 头，与改造前一致。"""

    name = "client_header"

    def check(self, headers) -> bool:
        client = headers.get("X-PyMCL-Client") or ""
        return client.startswith("PyMCL/")


AUTHENTICATOR: Authenticator = ClientHeaderAuthenticator()
_AUTH_LOCK = threading.Lock()


def set_authenticator(impl: Authenticator) -> None:
    """注入自定义鉴权实现（令牌桶 / JWT / 内网白名单…）。"""
    global AUTHENTICATOR
    with _AUTH_LOCK:
        AUTHENTICATOR = impl


# ---------------------------------------------------------------- 4.3 可插拔计量

class Meter:
    """计量接口：每个 /pymcl/chat 请求记一条。实现必须自己吞异常、不阻塞转发。"""

    name = "base"

    def record(self, *, ip: str, model: str, degraded: bool,
               prompt_tokens: int = 0, completion_tokens: int = 0,
               stream: bool = True, status: str = "ok") -> None:
        raise NotImplementedError


class LocalFileMeter(Meter):
    """默认实现：逐条 JSONL 追加进 ai_gateway/usage.jsonl（本机日志）。"""

    name = "local_file"

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else ROOT / "usage.jsonl"
        self._lock = threading.Lock()

    def record(self, *, ip: str, model: str, degraded: bool,
               prompt_tokens: int = 0, completion_tokens: int = 0,
               stream: bool = True, status: str = "ok") -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "ip": ip, "model": model, "degraded": bool(degraded),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "stream": bool(stream), "status": status,
        }
        try:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


METER: Meter = LocalFileMeter()


def set_meter(impl: Meter) -> None:
    global METER
    with _AUTH_LOCK:
        METER = impl


_USAGE_RE = re.compile(rb'"usage"\s*:\s*\{[^{}]*\}')


def _extract_usage(raw: bytes) -> tuple[int, int]:
    """尽力从响应字节里抓 usage（非流式整包 / 流式 SSE 都扫）。"""
    try:
        for match in _USAGE_RE.findall(raw):
            # 匹配到的是 "usage": {…} 片段，包一层大括号才是合法 JSON
            data = json.loads("{" + match.decode("utf-8", errors="replace") + "}")
            data = data.get("usage") or {}
            prompt = int(data.get("prompt_tokens") or 0)
            completion = int(data.get("completion_tokens") or 0)
            if prompt or completion:
                return prompt, completion
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


class _Limiter:
    def __init__(self):
        self._lock = threading.Lock()
        self.minu = defaultdict(list)
        self.day = defaultdict(list)
        self.inflight = defaultdict(int)

    def allow(self, ip: str):
        now = time.time()
        with self._lock:
            self.minu[ip] = [t for t in self.minu[ip] if now - t < 60]
            self.day[ip] = [t for t in self.day[ip] if now - t < 86400]
            if self.inflight[ip] >= MAX_INFLIGHT:
                return False, "busy"
            if len(self.minu[ip]) >= RATE_PER_MIN:
                return False, "busy"
            if len(self.day[ip]) >= RATE_PER_DAY:
                return False, "busy"
            degrade = len(self.minu[ip]) >= DEGRADE_AFTER
            self.minu[ip].append(now)
            self.day[ip].append(now)
            self.inflight[ip] += 1
            return True, ("degrade" if degrade else "ok")

    def done(self, ip: str):
        with self._lock:
            self.inflight[ip] = max(0, self.inflight[ip] - 1)


LIMITER = _Limiter()


def _json_bytes(obj, code=200):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return code, raw


class Handler(BaseHTTPRequestHandler):
    server_version = "PyMCL-AI-Gateway/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body: bytes, content_type="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg="网络繁忙，请稍后再试"):
        payload, _ = None, None
        raw = json.dumps({"error": {"message": msg}}, ensure_ascii=False).encode("utf-8")
        self._send(code, raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/pymcl/health"):
            self._send(200, json.dumps({
                "ok": True,
                "service": "pymcl-ai-gateway",
                "model": NEWAPI_MODEL,
            }, ensure_ascii=False).encode("utf-8"))
            return
        self._err(404, "not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/pymcl/chat":
            self._err(404, "not found")
            return
        # 4.3 鉴权走可插拔接口；默认 ClientHeaderAuthenticator 行为与改造前一致
        if not AUTHENTICATOR.check(self.headers):
            self._err(403)
            return
        if not NEWAPI_BASE or not NEWAPI_KEY:
            self._err(503, "网关未配置 NewAPI")
            return
        ip = self.client_address[0]
        ok, flag = LIMITER.allow(ip)
        if not ok:
            self._err(429)
            return
        try:
            self._proxy(flag == "degrade")
        finally:
            LIMITER.done(ip)

    def _proxy(self, degrade: bool):
        ip = self.client_address[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            self._err(413, "请求太大")
            return
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._err(400, "请求格式不对")
            return
        if not isinstance(body, dict):
            self._err(400, "请求格式不对")
            return
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._err(400, "请求格式不对")
            return
        want_stream = bool(body.get("stream", True))
        try:
            temperature = min(float(body.get("temperature") or 0.3), 0.8)
            max_tokens = min(int(body.get("max_tokens") or MAX_OUTPUT_TOKENS),
                             MAX_OUTPUT_TOKENS)
        except (TypeError, ValueError):
            # 4.3：非数字直接回 400，别让 ValueError 裸抛把连接掐了还没响应
            self._err(400, "temperature / max_tokens 必须是数字")
            return
        out = {
            "model": DEGRADE_MODEL if degrade else NEWAPI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "stream": want_stream,
            "max_tokens": max_tokens,
        }
        if body.get("tools"):
            out["tools"] = body["tools"]
            out["tool_choice"] = body.get("tool_choice") or "auto"
        target = NEWAPI_BASE + "/chat/completions"
        req = Request(
            target,
            data=json.dumps(out, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer " + NEWAPI_KEY,
                "Content-Type": "application/json",
            },
        )
        try:
            resp = urlopen(req, timeout=180)
        except HTTPError as exc:
            # 错误体放宽到 2000：客户端要靠 "maximum context length" 这类
            # 关键词触发 reactive compact，截太短关键词就被切掉了
            err = exc.read()[:2000]
            try:
                msg = json.loads(err.decode("utf-8", errors="replace"))
                text = ((msg.get("error") or {}).get("message") if isinstance(msg, dict) else None) or "上游繁忙"
            except Exception:
                text = err.decode("utf-8", errors="replace") or "上游繁忙"
            self._err(502, str(text)[:800])
            return
        except URLError:
            self._err(502, "连不上上游")
            return
        if not want_stream:
            ctype = resp.headers.get("Content-Type") or "application/json; charset=utf-8"
            try:
                raw = resp.read()
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            # 4.3 计量：非流式整包直接解析 usage
            pt, ct = _extract_usage(raw)
            try:
                METER.record(ip=ip, model=out["model"], degraded=degrade,
                             prompt_tokens=pt, completion_tokens=ct,
                             stream=False, status="ok")
            except Exception:  # noqa: BLE001
                pass
            self._send(200, raw, ctype)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        collected = bytearray()
        try:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                if len(collected) < 4 * 1024 * 1024:
                    collected += chunk
        except Exception:
            pass
        finally:
            try:
                resp.close()
            except Exception:
                pass
            # 4.3 计量：流式从已转发字节里尽力抓 usage（SSE 最后一个包带 usage）
            try:
                pt, ct = _extract_usage(bytes(collected[-65536:]))
                METER.record(ip=ip, model=out["model"], degraded=degrade,
                             prompt_tokens=pt, completion_tokens=ct,
                             stream=True, status="ok")
            except Exception:  # noqa: BLE001
                pass


def main():
    if not NEWAPI_BASE or not NEWAPI_KEY:
        sys.stderr.write(
            "请先设置 NEWAPI_BASE_URL 与 NEWAPI_API_KEY（或写 ai_gateway/.env）\n"
        )
        sys.exit(2)
    # 4.3 传输安全门禁：TLS，或声明前置反代，或显式的本机调试逃生口——
    # 一个都没有就拒绝启动。明文 HTTP 挂在 0.0.0.0 上等于把所有用户的
    # 对话内容（可能带令牌、路径）裸奔到局域网。
    loopback = BIND in ("127.0.0.1", "localhost", "::1")
    if TLS_CERT and TLS_KEY:
        pass          # 下面包 TLS
    elif TRUST_PROXY:
        sys.stderr.write(
            "⚠️  GATEWAY_TRUST_PROXY=1：假定前面有 HTTPS 反向代理终止 TLS。\n"
            "   如果没有，请立即停止并改配 GATEWAY_TLS_CERT/GATEWAY_TLS_KEY。\n")
    elif ALLOW_INSECURE and loopback:
        sys.stderr.write(
            "⚠️  GATEWAY_ALLOW_INSECURE=1：仅回环地址的明文调试模式，勿用于公网。\n")
    else:
        sys.stderr.write(
            "拒绝启动：既没有 TLS，也没有声明前置反向代理。\n"
            "  - 正式部署：设 GATEWAY_TLS_CERT / GATEWAY_TLS_KEY 指向证书；\n"
            "  - 有反代终止 TLS：设 GATEWAY_TRUST_PROXY=1；\n"
            "  - 本机调试：BIND=127.0.0.1 且 GATEWAY_ALLOW_INSECURE=1。\n")
        sys.exit(2)
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    if TLS_CERT and TLS_KEY:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        sys.stderr.write("PyMCL AI 网关 https://%s:%s  →  %s  model=%s\n" % (
            BIND, PORT, NEWAPI_BASE, NEWAPI_MODEL))
    else:
        sys.stderr.write("PyMCL AI 网关 http://%s:%s  →  %s  model=%s\n" % (
            BIND, PORT, NEWAPI_BASE, NEWAPI_MODEL))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
