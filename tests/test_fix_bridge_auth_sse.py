# -*- coding: utf-8 -*-
"""审计 #1 P1-1 / P1-2 回归：桥的鉴权与 SSE 订阅生命周期。

P1-1：HTTP 头按 latin-1 解码，任意字节都能变成非 ASCII `str`；`hmac.compare_digest`
对含非 ASCII 的 `str` 抛 `TypeError`（不是返回 False），异常发生在 `_authorize` 内、
不在 `do_GET`/`do_POST` 的 try 覆盖范围里 —— 客户端拿到的是 `RemoteDisconnected`
而不是 401，服务端 stderr 每次一份完整 traceback。

P1-2：`state.bus.subscribe()` 在 try 之外，握手期（send_response / end_headers）
断开时 finally 不执行，订阅者永久留在 `EventBus._subs` 里。

全部离线：只连 127.0.0.1 上自建的临时端口，不联网。
"""
from __future__ import annotations

import json
import socket
import threading

import pytest

from bridge import server as srv
from bridge.api import EventBus


class _Api:
    def ping(self):
        return "pong"


def _state(token: str = "t" * 32):
    return srv.BridgeState(_Api(), EventBus(), token=token)


@pytest.fixture()
def bridge():
    """起一个真实 loopback 桥，返回 (host, port, state)。"""
    state = _state()
    httpd = srv.create_http_server("127.0.0.1", 0, state)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    host, port = httpd.server_address[:2]
    try:
        yield host, port, state
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def _raw_request(host: str, port: int, payload: bytes, read_bytes: int = 4096) -> bytes:
    """用裸 socket 发请求，好把任意非 ASCII 字节塞进请求头。"""
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(payload)
        s.settimeout(5)
        out = b""
        try:
            while len(out) < read_bytes:
                chunk = s.recv(4096)
                if not chunk:
                    break
                out += chunk
        except (socket.timeout, ConnectionResetError, OSError):
            pass
        return out


class TestNonAsciiTokenHeader:
    def test_non_ascii_header_gets_401_not_disconnect(self, bridge):
        """修前：服务端 TypeError → 连接被直接关掉，一个字节响应都没有。"""
        host, port, _ = bridge
        resp = _raw_request(
            host, port,
            b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"X-PyMCL-Bridge-Token: \xff\xfe\r\nConnection: close\r\n\r\n",
        )
        assert resp, "客户端收到断连（无任何响应），而不是 401"
        assert b"401" in resp.split(b"\r\n", 1)[0], resp[:120]

    def test_non_ascii_query_token_gets_401(self, bridge):
        """SSE 的 query 通道同源：`?token=%C3%A9` percent-decode 后是 `é`。"""
        host, port, _ = bridge
        resp = _raw_request(
            host, port,
            b"GET /events?token=%C3%A9 HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Connection: close\r\n\r\n",
        )
        assert resp, "客户端收到断连，而不是 401"
        assert b"401" in resp.split(b"\r\n", 1)[0], resp[:120]

    def test_non_ascii_header_does_not_crash_server(self, bridge):
        """打一发恶意头之后，桥必须还能正常服务带正确令牌的请求。"""
        host, port, state = bridge
        _raw_request(
            host, port,
            b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"X-PyMCL-Bridge-Token: \xff\xfe\r\nConnection: close\r\n\r\n",
        )
        resp = _raw_request(
            host, port,
            f"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"X-PyMCL-Bridge-Token: {state.token}\r\nConnection: close\r\n\r\n".encode("ascii"),
        )
        assert b"200" in resp.split(b"\r\n", 1)[0], resp[:160]

    def test_correct_token_still_authorizes(self, bridge):
        host, port, state = bridge
        resp = _raw_request(
            host, port,
            f"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"X-PyMCL-Bridge-Token: {state.token}\r\nConnection: close\r\n\r\n".encode("ascii"),
        )
        assert b"200" in resp.split(b"\r\n", 1)[0]
        assert b'"ok": true' in resp.replace(b'"ok":true', b'"ok": true')

    def test_wrong_ascii_token_gets_401(self, bridge):
        host, port, _ = bridge
        resp = _raw_request(
            host, port,
            b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"X-PyMCL-Bridge-Token: nope\r\nConnection: close\r\n\r\n",
        )
        assert b"401" in resp.split(b"\r\n", 1)[0]


class _FailingWriter:
    """握手就断的客户端：第一次写就 BrokenPipeError。"""

    def write(self, _data):
        raise BrokenPipeError("client went away during handshake")

    def flush(self):
        raise BrokenPipeError("client went away during handshake")


class TestSseSubscribeLeak:
    def _handler(self, state):
        handler_cls = srv.make_handler(state)
        h = handler_cls.__new__(handler_cls)
        h.wfile = _FailingWriter()
        return h

    def test_handshake_disconnect_unsubscribes(self):
        """修前：subscribe() 在 try 之外，握手期断开 → 订阅者永久泄漏。"""
        state = _state()
        h = self._handler(state)

        # 握手写响应头时就断：pre-fix 的 send_response 抛 BrokenPipeError，
        # 那时 q 已经进 _subs，而 finally 还没生效
        def _boom(*_a, **_k):
            raise BrokenPipeError("client went away during handshake")

        h.send_response = _boom
        h.send_header = _boom
        h.end_headers = _boom

        h._sse(None)

        assert state.bus._subs == [], f"SSE 订阅者泄漏了 {len(state.bus._subs)} 个"

    def test_handshake_disconnect_does_not_propagate(self):
        """握手断开是客户端行为，不该让异常逃出 _sse（否则 handler 线程打栈）。"""
        state = _state()
        h = self._handler(state)

        def _boom(*_a, **_k):
            raise ConnectionResetError("reset")

        h.send_response = _boom
        h.send_header = _boom
        h.end_headers = _boom

        h._sse(None)  # 不抛 = 通过

        assert state.bus._subs == []

    def test_body_write_disconnect_unsubscribes(self):
        """老路径（try 内断开）本来就对，别改坏。"""
        state = _state()
        h = self._handler(state)
        h.send_response = lambda *a, **k: None
        h.send_header = lambda *a, **k: None
        h.end_headers = lambda *a, **k: None

        h._sse(None)

        assert state.bus._subs == []

    def test_emit_after_leak_free_disconnect_reaches_nobody(self):
        state = _state()
        h = self._handler(state)
        h.send_response = lambda *a, **k: None
        h.send_header = lambda *a, **k: None
        h.end_headers = lambda *a, **k: None
        h._sse(None)

        state.bus.emit("ui_changed", {"x": 1})  # 没有订阅者也不该抛


class TestSseQueryTokenStillWorks:
    def test_valid_query_token_starts_sse(self, bridge):
        """SSE 的 query 令牌通道不能因为这次加固被关掉。"""
        host, port, state = bridge
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(
                f"GET /events?token={state.token} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii"))
            s.settimeout(5)
            buf = b""
            # 一直读到 hello 事件为止（响应头之后还有正文）
            try:
                while b"event: hello" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            except (socket.timeout, OSError):
                pass
            assert b"200" in buf.split(b"\r\n", 1)[0], buf[:160]
            assert b"event: hello" in buf, buf[:300]
            s.close()

        # 服务端只在**下一次写**时才会发现对端已断（q.get 阻塞在 15s keepalive 上），
        # 所以这里主动 emit 把它唤醒，再等订阅者被清掉。
        import time
        deadline = time.time() + 20
        while state.bus._subs and time.time() < deadline:
            state.bus.emit("ui_changed", {"x": 1})
            time.sleep(0.2)
        assert state.bus._subs == [], "SSE 正常路径断开后订阅者没清掉"


class TestRpcStillWorks:
    def test_rpc_round_trip(self, bridge):
        host, port, state = bridge
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).encode()
        req = (
            f"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"X-PyMCL-Bridge-Token: {state.token}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii") + body
        resp = _raw_request(host, port, req)
        assert b'"result": "pong"' in resp or b'"result":"pong"' in resp, resp[:300]
