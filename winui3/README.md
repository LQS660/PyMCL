# PyMCL WinUI 3 前端

正统 C# WinUI 3 界面，通过本机 HTTP JSON-RPC + SSE 调用 C 后端（`native/build/pymcl-bridge.exe`）。没有 C 桥时回退到 Python（`mclauncher/` + `bridge/`）。**不改** Qt 入口：`python main.py` 仍打开原来的 Fluent/Qt 窗。

## 并存

| 入口 | 界面 |
|------|------|
| `python main.py` | 现有 Qt / qfluentwidgets |
| `winui3\run.bat` 或仓库根 `run-winui.bat` | WinUI 3（本工程） |

两边共用同一工作目录：`.minecraft/`、`java/`、`config.json`、`cache/`。桥进程设置 `PYMCL_HOME` 为仓库根，与 `mclauncher.utils.ROOT` 一致。

## 环境

- Windows 10 19041+（本机 19045）
- .NET 8 SDK（可装到 `%USERPROFILE%\dotnet`）
- Windows App SDK 1.6（工程 `WindowsAppSDKSelfContained=true`，Unpackaged，无需 sideload MSIX）
- C 桥：`native\build.bat`（MinGW gcc + libcurl，输出 `native\build\pymcl-bridge.exe`）
- Python 回退：优先 `C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe`，或环境变量 `PYMCL_PYTHON`

## 运行

单文件：`pack\build-single.bat` → `dist\PyMCL.exe`（首次运行解压到 `%LOCALAPPDATA%\PyMCL\runtime`，数据写在 exe 同目录）。

```bat
winui3\run.bat
```

C# 启动时优先拉起：

```text
native\build\pymcl-bridge.exe --root <仓库根>
```

没有 C 桥时回退，或设 `PYMCL_BRIDGE=python` 强制 Python：

```text
python -u bridge\server.py --root <仓库根>
```

退出主窗时杀掉桥进程。

协议：

- `POST http://127.0.0.1:<port>/rpc` JSON-RPC 2.0，方法名对齐 `app/backend.py` / `bridge/api.py`
- `GET /events` Server-Sent Events：`task_added` / `progress` / `log` / `finished` / `task_count_changed` / `ui_changed` / `login_code` / `login_status`
- 启动时 stdout 第一行：`PYMCL_BRIDGE port=<n> host=127.0.0.1 root=...`

## 编译

```bat
set PATH=%USERPROFILE%\dotnet;%PATH%
dotnet build winui3\PyMCL.WinUI\PyMCL.WinUI.csproj -c Release -p:Platform=x64
```

产品名：PyMCL 启动器（WinUI 3）。侧栏 5 项：启动、实例、下载、设置，底栏钉「下载任务」。下载区为顶部分类横条，不弹独立窗口。
