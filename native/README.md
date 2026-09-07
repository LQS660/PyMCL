# PyMCL C 桥

WinUI 3 默认启动 `native/build/pymcl-bridge.exe`，协议对齐 `bridge/server.py`。

## 编译

需要 MinGW-w64 gcc + libcurl + zlib（本机 `C:\msys64\mingw64`）。

```bat
native\build.bat
```

产物：`native/build/pymcl-bridge.exe`，旁路 DLL 与 `curl-ca-bundle.crt`。

```bat
pymcl-bridge.exe --root <仓库根> [--host 127.0.0.1] [--port 0]
```

stdout 第一行：`PYMCL_BRIDGE port=<n> host=127.0.0.1 root=...`

## 协议

- `GET /health` → `{"ok":true,"name":"pymcl-bridge"}`
- `POST /rpc` JSON-RPC 2.0
- `GET /events` SSE
