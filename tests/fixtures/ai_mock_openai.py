# -*- coding: utf-8 -*-
"""脚本化 OpenAI 兼容 mock（AI 对拍用，GOAL 4.C）。

按脚本顺序逐个响应 /chat/completions：
- {"deltas": ["Hello", " world"]}                     → 流式正文
- {"reasoning": ["想", "一下"]}                        → DeepSeek 风格思考流（<think> 由桥包）
- {"tool_calls": [{"id": "call_1", "name": "...", "arguments": "..."}], "fragments": 3}
                                                      → 流式工具调用（参数切 fragments 段）
- {"nonstream": {"content": "...", "tool_calls": [...]}} → 非流式整体响应
- {"status": 401, "json": {"error": {"message": "..."}}} → HTTP 错误
- {"drop_after": 2, "deltas": [...]}                  → 发 N 个块后掐断连接
- {"chunk_delay": 0.4}                                → 每块间隔（配合 ai_stop 场景）

GET /reset 复位脚本指针；GET /served 返回已处理请求数。
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
SCRIPT: list[dict] = []
IDX = 0


def next_response() -> dict | None:
    global IDX
    with LOCK:
        if IDX >= len(SCRIPT):
            return None
        r = SCRIPT[IDX]
        IDX += 1
        return r


def sse_chunk(model: str, delta: dict, finish=None, usage=None) -> bytes:
    obj = {"id": "chatcmpl-mock", "object": "chat.completion.chunk",
           "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        obj["usage"] = usage
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n"


def build_stream(resp: dict, model: str):
    out = bytearray()
    out += sse_chunk(model, {"role": "assistant"})
    delay = float(resp.get("chunk_delay") or 0)
    if resp.get("drop_after"):
        n = 0
        for piece in resp.get("deltas") or []:
            out += sse_chunk(model, {"content": piece})
            n += 1
            if n >= resp["drop_after"]:
                return bytes(out), True   # 掐断标记
        return bytes(out), True
    for piece in resp.get("reasoning") or []:
        out += sse_chunk(model, {"reasoning_content": piece})
        if delay:
            time.sleep(delay)
    for piece in resp.get("deltas") or []:
        out += sse_chunk(model, {"content": piece})
        if delay:
            time.sleep(delay)
    tcs = resp.get("tool_calls")
    if tcs:
        for i, tc in enumerate(tcs):
            frags = max(1, int(resp.get("fragments") or 1))
            args = tc.get("arguments") or ""
            step = max(1, (len(args) + frags - 1) // frags)
            for fi in range(0, max(1, len(args) and frags or 0) or 1):
                piece = args[fi * step:(fi + 1) * step]
                if piece or fi == 0:
                    out += sse_chunk(model, {"tool_calls": [{
                        "index": i, "id": tc.get("id") or f"call_{i + 1}",
                        "function": {"name": tc.get("name") or "", "arguments": piece}}]})
    usage = {"prompt_tokens": 12, "completion_tokens": 34} if resp.get("usage") else None
    out += sse_chunk(model, {}, finish="tool_calls" if tcs else resp.get("finish") or "stop",
                     usage=usage)
    out += b"data: [DONE]\n\n"
    return bytes(out), False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # noqa: N802
        pass

    def do_GET(self):  # noqa: N802
        global IDX
        if self.path.startswith("/reset"):
            with LOCK:
                IDX = 0
            self._send_json(200, {"ok": True})
        elif self.path.startswith("/served"):
            with LOCK:
                self._send_json(200, {"served": IDX})
        else:
            self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):  # noqa: N802
        global SCRIPT, IDX
        if self.path.startswith("/script"):
            n = int(self.headers.get("Content-Length") or 0)
            with LOCK:
                SCRIPT = json.loads(self.rfile.read(n).decode("utf-8"))
                IDX = 0
            self._send_json(200, {"ok": True, "count": len(SCRIPT)})
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(body.decode("utf-8"))
        except ValueError:
            req = {}
        model = str(req.get("model") or "mock-model")
        resp = next_response()
        if resp is None:
            self._send_json(500, {"error": {"message": "mock script exhausted"}})
            return
        if resp.get("status"):
            self._send_json(int(resp["status"]), resp.get("json") or {"error": {"message": "mock error"}})
            return
        if resp.get("nonstream") is not None or not req.get("stream"):
            ns = resp.get("nonstream")
            if ns is None:
                ns = {"content": "".join(resp.get("deltas") or []),
                      "tool_calls": [{"id": tc.get("id") or f"call_{i + 1}",
                                      "type": "function",
                                      "function": {"name": tc.get("name"), "arguments": tc.get("arguments") or ""}}
                                     for i, tc in enumerate(resp.get("tool_calls") or [])]}
            msg = {"role": "assistant", "content": ns.get("content") or ""}
            if ns.get("tool_calls"):
                msg["tool_calls"] = ns["tool_calls"]
            payload = {"id": "chatcmpl-mock", "object": "chat.completion",
                       "created": int(time.time()), "model": model,
                       "choices": [{"index": 0, "message": msg,
                                    "finish_reason": "tool_calls" if msg["tool_calls"] else "stop"}],
                       "usage": {"prompt_tokens": 12, "completion_tokens": 34}}
            self._send_json(200, payload)
            return
        data, dropped = build_stream(resp, model)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()
        if dropped:
            self.close_connection = True

    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18769)
    ap.add_argument("--script", required=True)
    args = ap.parse_args()
    global SCRIPT
    SCRIPT = json.loads(open(args.script, encoding="utf-8").read())
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AI mock listening on {args.port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
