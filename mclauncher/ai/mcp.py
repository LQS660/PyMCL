# -*- coding: utf-8 -*-
"""MCP 客户端（批次 3.2）：stdio JSON-RPC 直连，不引第三方 SDK。

为什么不用 MCP SDK：本工程只需 stdio 传输上的 initialize / tools/list /
tools/call 三个方法，SDK 带来的依赖树（anyio/httpx 等）远超收益，而且会被
PyInstaller 打进产物。等价路径就是这里的 ~200 行手写 JSON-RPC 客户端。

协议：MCP stdio 传输 = 换行分隔的 JSON-RPC 2.0。initialize 握手 +
notifications/initialized 之后即可 tools/list、tools/call。

隔离性：任何 server 连不上 / 握手超时 / 中途崩掉，只影响它自己的工具；
内置工具与对话不受影响（连接全程 try/except，agent 侧每次调用也有兜底）。
"""

from __future__ import annotations

import json
import subprocess
import threading

from mclauncher import utils

from . import trace

PROTOCOL_VERSION = "2024-11-05"
CONNECT_TIMEOUT = 10.0
CALL_TIMEOUT = 60.0


class McpError(Exception):
    pass


class McpClient:
    """一个 MCP server 的 stdio 连接。"""

    def __init__(self, name: str, command: str, args: list | None = None,
                 env: dict | None = None):
        self.name = str(name)
        self.command = str(command)
        self.args = [str(a) for a in (args or [])]
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    # ---- 低层 ----
    def _send(self, payload: dict) -> None:
        assert self._proc is not None and self._proc.stdin
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _recv(self, want_id: int, timeout: float) -> dict:
        assert self._proc is not None and self._proc.stdout
        import time
        deadline = time.monotonic() + timeout
        timed_out = [False]

        def _watchdog():
            # readline 是无超时阻塞读：server 进程活着但不回话时，必须由
            # 看门狗在 deadline 杀掉进程，readline 才会以 EOF 返回，否则
            # 整个 agent 线程永久挂死（停止按钮也打断不了阻塞中的 readline）
            time.sleep(max(0.1, deadline - time.monotonic()))
            timed_out[0] = True
            try:
                if self._proc is not None and self._proc.poll() is None:
                    self._proc.kill()
            except Exception:  # noqa: BLE001
                pass

        dog = threading.Thread(target=_watchdog, daemon=True)
        dog.start()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                if timed_out[0]:
                    raise McpError(f"MCP server {self.name} 响应超时")
                raise McpError(f"MCP server {self.name} 已退出"
                               f"（exit={self._proc.poll()}）")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == want_id:
                return msg
            if time.monotonic() > deadline:
                raise McpError(f"MCP server {self.name} 响应超时")

    def _request(self, method: str, params: dict | None, timeout: float) -> dict:
        with self._lock:
            if self._proc is None:
                raise McpError(f"MCP server {self.name} 未连接")
            rid = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                        "params": params or {}})
            msg = self._recv(rid, timeout)
        if isinstance(msg.get("error"), dict):
            raise McpError(f"MCP {method} 失败: {msg['error'].get('message')}")
        return msg.get("result") or {}

    # ---- 生命周期 ----
    def connect(self) -> None:
        import os
        env = None
        if self.env:
            # server 常需要自己的环境变量（API_KEY / NODE_PATH…）：
            # 在系统环境之上覆盖配置给的值
            env = {**os.environ, **{str(k): str(v) for k, v in self.env.items()}}
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", cwd=str(utils.ROOT),
            env=env,
        )
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "PyMCL", "version": "1.0"},
        }, CONNECT_TIMEOUT)
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def close(self) -> None:
        try:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        except Exception:  # noqa: BLE001
            pass
        self._proc = None

    # ---- MCP 方法 ----
    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {}, CONNECT_TIMEOUT)
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}},
                               CALL_TIMEOUT)
        if result.get("isError"):
            raise McpError(str(result.get("content") or "tool error")[:300])
        parts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)


def _server_configs(settings: dict) -> list[dict]:
    """settings['ai_mcp_servers'] = [{name, command, args?, env?}, ...]；配置坏项直接跳过。

    name 只允许 [A-Za-z0-9_-]：它会被拼进工具名（mcp_<name>_<tool>）并参与
    前缀路由，混入其他字符会造成路由歧义 / 非法 function 名。
    """
    raw = (settings or {}).get("ai_mcp_servers")
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        command = str(row.get("command") or "").strip()
        if not name or not command:
            continue
        if not all(ch.isalnum() or ch in "-_" for ch in name):
            trace.record("mcp_config_skipped", tool_name=name,
                         reason="server 名只允许字母数字-_")
            continue
        env = row.get("env")
        out.append({"name": name, "command": command,
                    "args": row.get("args") if isinstance(row.get("args"), list) else [],
                    "env": {str(k): str(v) for k, v in env.items()}
                    if isinstance(env, dict) else None})
    return out


def connect_servers(settings: dict) -> list[McpClient]:
    """连配置里所有 MCP server，坏的跳过（隔离性：坏 server 不影响其他）。"""
    clients: list[McpClient] = []
    for cfg in _server_configs(settings):
        client = McpClient(cfg["name"], cfg["command"], cfg["args"], cfg.get("env"))
        try:
            client.connect()
            clients.append(client)
        except Exception as exc:  # noqa: BLE001
            client.close()
            trace.record("mcp_connect_failed", tool_name=cfg["name"], exc=exc)
    return clients


def close_all(clients: list[McpClient]) -> None:
    for c in clients or []:
        c.close()


def mcp_tool_schemas(clients: list[McpClient]) -> list[dict]:
    """把各 server 的 tools/list 转成 OpenAI function schema，名字加 mcp_<server>_ 前缀。"""
    schemas: list[dict] = []
    for client in clients or []:
        try:
            tools = client.list_tools()
        except Exception as exc:  # noqa: BLE001
            trace.record("mcp_list_tools_failed", tool_name=client.name, exc=exc)
            continue
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            name = f"mcp_{client.name}_{t['name']}"
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(t.get("description") or name)[:800],
                    "parameters": t.get("inputSchema") if isinstance(t.get("inputSchema"), dict)
                                  else {"type": "object", "properties": {}},
                },
            })
    return schemas


def route_call(clients: list[McpClient], name: str, args: dict) -> str | None:
    """按前缀路由 mcp_<server>_<tool>；不是 MCP 工具返回 None（继续走内置）。

    有 server `a` 与 `a_b` 时，`mcp_a_b_x` 必须路由到 `a_b`：按前缀长度
    降序取最长匹配，短名 server 不会截胡长名 server 的调用。
    """
    if not name.startswith("mcp_"):
        return None
    rest = name[len("mcp_"):]
    for client in sorted(clients or [], key=lambda c: len(c.name), reverse=True):
        prefix = f"{client.name}_"
        if rest.startswith(prefix):
            return client.call_tool(rest[len(prefix):], args)
    raise McpError(f"没有叫 {name} 的 MCP 工具（server 可能已崩）")
