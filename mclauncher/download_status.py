# -*- coding: utf-8 -*-
"""PCL 风格下载状态：DNS / TCP 握手 / TLS / HTTP / 速度 / 进度。"""
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.connection import create_connection

from .utils import format_size

PHASE_LABELS = {
    "idle": "就绪",
    "prepare": "准备下载",
    "dns": "正在解析 DNS",
    "dns_ok": "DNS 解析成功",
    "dns_fail": "DNS 解析失败",
    "tcp": "正在 TCP 握手",
    "tcp_ok": "TCP 握手成功",
    "tcp_fail": "TCP 握手失败",
    "tls": "正在 TLS 握手",
    "tls_ok": "TLS 握手成功",
    "tls_fail": "TLS 握手失败",
    "reuse": "复用已有 TCP 连接",
    "http": "正在发送 HTTP 请求",
    "http_ok": "已收到 HTTP 响应",
    "transfer": "下载中",
    "verify": "正在校验文件",
    "skip": "已存在，跳过",
    "done": "下载完成",
    "fail": "下载失败",
}


def format_speed(bps) -> str:
    try:
        bps = float(bps)
    except (TypeError, ValueError):
        return "0 B/s"
    if bps < 0:
        bps = 0
    return f"{format_size(bps)}/s"


def format_eta(seconds) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"剩余 {seconds} 秒"
    mins, sec = divmod(seconds, 60)
    if mins < 60:
        return f"剩余 {mins}:{sec:02d}"
    hours, mins = divmod(mins, 60)
    return f"剩余 {hours}:{mins:02d}:{sec:02d}"


class SpeedMeter:
    """滑动窗口速度计（多线程安全）。"""

    def __init__(self, window=1.5):
        self.window = float(window)
        self._lock = threading.Lock()
        self._samples = deque()

    def add(self, n):
        if n <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._samples.append((now, int(n)))
            self._trim(now)

    def reset(self):
        with self._lock:
            self._samples.clear()

    def speed(self) -> float:
        now = time.monotonic()
        with self._lock:
            self._trim(now)
            if not self._samples:
                return 0.0
            dt = now - self._samples[0][0]
            total = sum(b for _, b in self._samples)
            if dt <= 0.05:
                return float(total) / 0.05
            return total / dt

    def _trim(self, now):
        cutoff = now - self.window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


@dataclass
class DownloadSnapshot:
    phase: str
    phase_label: str
    detail: str
    filename: str
    host: str
    ip: str
    port: int
    http_status: int
    tls_version: str
    handshake: str
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    speed_bps: float
    error: str
    active: bool

    @property
    def percent(self) -> float:
        if self.bytes_total > 0:
            return min(100.0, self.bytes_done * 100.0 / self.bytes_total)
        if self.files_total > 0:
            return min(100.0, self.files_done * 100.0 / self.files_total)
        return 0.0

    @property
    def status_line(self) -> str:
        parts = []
        if self.handshake:
            parts.append(self.handshake)
        if self.tls_version and self.phase in (
            "tls_ok", "http", "http_ok", "reuse", "transfer", "verify", "done",
        ):
            parts.append(self.tls_version)
        if self.http_status and self.phase in (
            "http_ok", "transfer", "verify", "done",
        ):
            parts.append(f"HTTP {self.http_status}")
        label = self.phase_label
        if self.phase == "transfer" and self.filename:
            label = f"下载中 {self.filename}"
        elif self.detail and self.phase not in ("transfer", "idle"):
            label = self.detail
        if label and label not in parts:
            parts.append(label)
        if self.error and self.phase == "fail":
            parts.append(self.error)
        return " · ".join(p for p in parts if p) or "就绪"

    @property
    def meta_line(self) -> str:
        bits = [f"速度 {format_speed(self.speed_bps)}"]
        if self.bytes_total > 0:
            bits.append(f"{format_size(self.bytes_done)} / {format_size(self.bytes_total)}")
        elif self.bytes_done > 0:
            bits.append(format_size(self.bytes_done))
        if self.files_total > 0:
            bits.append(f"{self.files_done}/{self.files_total} 个文件")
        if self.bytes_total > self.bytes_done and self.speed_bps > 256:
            bits.append(format_eta((self.bytes_total - self.bytes_done) / self.speed_bps))
        return "    ".join(bits)


class DownloadTracker:
    """线程安全的下载 HUD 状态。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._speed = SpeedMeter()
        self._active = 0
        self._in_batch = False
        self._inflight = {}
        self._completed_bytes = 0
        self._tls = threading.local()
        self._reset_locked()

    def _reset_locked(self):
        self.phase = "idle"
        self.detail = "就绪"
        self.filename = ""
        self.url = ""
        self.host = ""
        self.ip = ""
        self.port = 0
        self.http_status = 0
        self.tls_version = ""
        self.handshake = ""
        self.bytes_done = 0
        self.bytes_total = 0
        self.files_done = 0
        self.files_total = 0
        self.error = ""
        self.saw_connect = False
        self._inflight.clear()
        self._completed_bytes = 0
        self._speed.reset()

    def reset_connect(self):
        self._tls.saw = False

    def mark_connect(self):
        self._tls.saw = True
        self.saw_connect = True

    def did_connect(self) -> bool:
        return bool(getattr(self._tls, "saw", False))

    def watching(self) -> bool:
        return self._active > 0

    def begin_batch(self, message, file_count, total_bytes=0):
        with self._lock:
            self._in_batch = True
            self._active += 1
            self._inflight.clear()
            self._completed_bytes = 0
            self._speed.reset()
            self.phase = "prepare"
            self.detail = message or "准备下载"
            self.filename = ""
            self.files_done = 0
            self.files_total = int(file_count or 0)
            self.bytes_done = 0
            self.bytes_total = int(total_bytes or 0)
            self.error = ""
            self.http_status = 0
            self.reset_connect()

    def end_batch(self, ok=True, message=None):
        with self._lock:
            self._in_batch = False
            self._active = max(0, self._active - 1)
            if ok:
                self.phase = "done"
                self.detail = message or "下载完成"
                if self.bytes_total:
                    self.bytes_done = self.bytes_total
                if self.files_total:
                    self.files_done = self.files_total
            else:
                self.phase = "fail"
                self.detail = message or "下载失败"

    def start_file(self, key, filename, url, size=None):
        host = ""
        try:
            host = urlparse(str(url)).hostname or ""
        except Exception:
            host = ""
        with self._lock:
            if not self._in_batch:
                if self._active == 0:
                    self._inflight.clear()
                    self._completed_bytes = 0
                    self._speed.reset()
                    self.files_done = 0
                    self.files_total = 1
                    self.bytes_done = 0
                    self.bytes_total = int(size or 0)
                self._active += 1
            self._inflight[key] = 0
            self.filename = filename or ""
            self.url = str(url or "")
            self.host = host
            self.http_status = 0
            self.error = ""
            self.reset_connect()
            self.phase = "prepare"
            self.detail = f"准备下载 {self.filename}" if self.filename else "准备下载"
            if size:
                # 单文件或已知大小时补总量
                if not self._in_batch:
                    self.bytes_total = max(self.bytes_total, int(size))
            self._recompute_bytes_locked()

    def finish_file(self, key, size=None, skipped=False):
        with self._lock:
            got = self._inflight.pop(key, 0)
            add = int(size or got or 0)
            self._completed_bytes += add
            self.files_done += 1
            if not self._in_batch:
                self._active = max(0, self._active - 1)
            if skipped:
                self.phase = "skip"
                self.detail = f"已存在，跳过 {self.filename}"
            elif self._active == 0 and not self._in_batch:
                self.phase = "done"
                self.detail = f"下载完成 {self.filename}"
            self._recompute_bytes_locked()

    def fail_file(self, key, err):
        with self._lock:
            self._inflight.pop(key, None)
            self.files_done += 1
            if not self._in_batch:
                self._active = max(0, self._active - 1)
            self.phase = "fail"
            self.error = str(err)
            self.detail = f"下载失败: {err}"
            self._recompute_bytes_locked()

    def dns(self, host):
        if not self.watching():
            return
        with self._lock:
            self.mark_connect()
            self.host = host or self.host
            self.phase = "dns"
            self.detail = f"正在解析 DNS {host}"
            self.handshake = f"正在解析 DNS {host}"

    def dns_ok(self, host, ip, ms=None):
        if not self.watching():
            return
        with self._lock:
            self.host = host or self.host
            self.ip = ip or ""
            self.phase = "dns_ok"
            extra = f"（{ms} ms）" if ms is not None else ""
            self.detail = f"DNS 解析成功 {host} → {ip}{extra}"
            self.handshake = self.detail

    def dns_fail(self, err):
        if not self.watching():
            return
        with self._lock:
            self.phase = "dns_fail"
            self.error = str(err)
            self.detail = f"DNS 解析失败: {err}"
            self.handshake = self.detail

    def tcp(self, ip, port):
        if not self.watching():
            return
        with self._lock:
            self.ip = ip or self.ip
            self.port = int(port or 0)
            self.phase = "tcp"
            self.detail = f"正在 TCP 握手 {ip}:{port}"
            self.handshake = self.detail

    def tcp_ok(self, ip, port, ms=None):
        if not self.watching():
            return
        with self._lock:
            self.ip = ip or self.ip
            self.port = int(port or 0)
            self.phase = "tcp_ok"
            extra = f"（{ms} ms）" if ms is not None else ""
            self.detail = f"TCP 握手成功 {ip}:{port}{extra}"
            self.handshake = self.detail

    def tcp_fail(self, err):
        if not self.watching():
            return
        with self._lock:
            self.phase = "tcp_fail"
            self.error = str(err)
            self.detail = f"TCP 握手失败: {err}"
            self.handshake = self.detail

    def tls_begin(self, host):
        if not self.watching():
            return
        with self._lock:
            self.phase = "tls"
            self.detail = f"正在 TLS 握手 {host}"

    def tls_ok(self, version=""):
        if not self.watching():
            return
        with self._lock:
            ver = str(version or "").strip()
            if ver.upper().startswith("TLS"):
                self.tls_version = ver
            elif ver:
                self.tls_version = f"TLS {ver}"
            else:
                self.tls_version = "TLS 握手成功"
            self.phase = "tls_ok"
            self.detail = self.tls_version

    def tls_fail(self, err):
        if not self.watching():
            return
        with self._lock:
            self.phase = "tls_fail"
            self.error = str(err)
            self.detail = f"TLS 握手失败: {err}"

    def reuse(self):
        if not self.watching():
            return
        with self._lock:
            self.phase = "reuse"
            self.detail = "复用已有 TCP 连接"
            if not self.handshake:
                self.handshake = "复用已有 TCP 连接"

    def http_ok(self, status, content_length=0):
        if not self.watching():
            return
        with self._lock:
            self.http_status = int(status or 0)
            if content_length:
                if not self._in_batch:
                    self.bytes_total = max(self.bytes_total, int(content_length))
                elif self.bytes_total <= 0:
                    self.bytes_total = int(content_length)
            self.phase = "http_ok"
            self.detail = f"已收到 HTTP {self.http_status}"

    def transfer(self, key, got, expected=0):
        if not self.watching():
            return
        with self._lock:
            prev = self._inflight.get(key, 0)
            self._inflight[key] = int(got or 0)
            delta = int(got or 0) - prev
            if delta > 0:
                self._speed.add(delta)
            if expected and not self._in_batch:
                self.bytes_total = max(self.bytes_total, int(expected))
            self.phase = "transfer"
            n = len(self._inflight)
            if n > 1:
                self.detail = f"下载中（{n} 个并发）{self.filename}"
            else:
                self.detail = f"下载中 {self.filename}" if self.filename else "下载中"
            self._recompute_bytes_locked()

    def verify(self, filename=""):
        if not self.watching():
            return
        with self._lock:
            self.phase = "verify"
            self.detail = f"正在校验 {filename or self.filename}"

    def snapshot(self) -> DownloadSnapshot:
        with self._lock:
            return DownloadSnapshot(
                phase=self.phase,
                phase_label=PHASE_LABELS.get(self.phase, self.phase),
                detail=self.detail,
                filename=self.filename,
                host=self.host,
                ip=self.ip,
                port=self.port,
                http_status=self.http_status,
                tls_version=self.tls_version,
                handshake=self.handshake,
                bytes_done=self.bytes_done,
                bytes_total=self.bytes_total,
                files_done=self.files_done,
                files_total=self.files_total,
                speed_bps=self._speed.speed(),
                error=self.error,
                active=self._active > 0,
            )

    def _recompute_bytes_locked(self):
        self.bytes_done = self._completed_bytes + sum(self._inflight.values())


def _connect_timeout(conn):
    timeout = getattr(conn, "timeout", None)
    if timeout is None:
        return 30
    connect = getattr(timeout, "connect_timeout", None)
    if connect is not None and connect is not socket.getdefaulttimeout():
        try:
            if connect != float("inf"):
                return connect
        except TypeError:
            return connect
    if isinstance(timeout, (int, float)):
        return timeout
    return 30


def _make_connection_classes(tracker: DownloadTracker):
    def _new_conn(conn):
        host = getattr(conn, "_dns_host", None) or conn.host
        port = conn.port
        tracker.dns(host)
        t0 = time.monotonic()
        try:
            infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
            ip = infos[0][4][0]
        except OSError as e:
            tracker.dns_fail(e)
            raise NameResolutionError(conn.host, conn, e) from e
        tracker.dns_ok(host, ip, int((time.monotonic() - t0) * 1000))
        tracker.tcp(ip, port)
        t1 = time.monotonic()
        try:
            sock = create_connection(
                (ip, port),
                _connect_timeout(conn),
                source_address=conn.source_address,
                socket_options=conn.socket_options,
            )
        except socket.timeout as e:
            tracker.tcp_fail(f"超时: {e}")
            raise ConnectTimeoutError(
                conn, f"TCP 握手超时 {ip}:{port} (timeout={_connect_timeout(conn)})",
            ) from e
        except OSError as e:
            tracker.tcp_fail(e)
            raise NewConnectionError(conn, f"TCP 握手失败: {e}") from e
        tracker.tcp_ok(ip, port, int((time.monotonic() - t1) * 1000))
        return sock

    class StatusHTTPConnection(HTTPConnection):
        def _new_conn(self):
            return _new_conn(self)

    class StatusHTTPSConnection(HTTPSConnection):
        def _new_conn(self):
            sock = _new_conn(self)
            self._pymcl_tcp_ok = True
            tracker.tls_begin(self.host)
            return sock

        def connect(self):
            try:
                super().connect()
            except Exception as e:
                if getattr(self, "_pymcl_tcp_ok", False):
                    tracker.tls_fail(e)
                raise
            ver = ""
            try:
                if self.sock is not None and hasattr(self.sock, "version"):
                    ver = self.sock.version() or ""
            except Exception:
                ver = ""
            tracker.tls_ok(ver)

    return StatusHTTPConnection, StatusHTTPSConnection


class StatusHTTPAdapter(HTTPAdapter):
    """带握手状态上报的 HTTPAdapter，保留原有连接池与重试。"""

    def __init__(self, tracker: DownloadTracker, *args, **kwargs):
        self._tracker = tracker
        super().__init__(*args, **kwargs)

    def _patch_manager(self, manager):
        http_cls, https_cls = _make_connection_classes(self._tracker)

        class StatusHTTPPool(HTTPConnectionPool):
            ConnectionCls = http_cls

        class StatusHTTPSPool(HTTPSConnectionPool):
            ConnectionCls = https_cls

        manager.pool_classes_by_scheme = {
            "http": StatusHTTPPool,
            "https": StatusHTTPSPool,
        }
        return manager

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
        self._patch_manager(self.poolmanager)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        if hasattr(manager, "pool_classes_by_scheme"):
            self._patch_manager(manager)
        return manager
