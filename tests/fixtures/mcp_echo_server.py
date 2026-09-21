# -*- coding: utf-8 -*-
"""最小 MCP server 测试夹具：stdio 上 newline-delimited JSON-RPC，提供 echo 工具。"""
import json
import sys


def read_msg():
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def write_msg(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    while True:
        try:
            msg = read_msg()
        except Exception:
            return
        if msg is None:
            return
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            write_msg({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo", "version": "0.1"},
            }})
        elif method == "tools/list":
            write_msg({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{
                "name": "echo",
                "description": "原样返回输入文本",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            }]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            write_msg({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}],
            }})
        elif rid is not None:
            write_msg({"jsonrpc": "2.0", "id": rid,
                       "error": {"code": -32601, "message": "unknown method"}})


if __name__ == "__main__":
    main()
