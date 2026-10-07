# 单文件打包

## WPF / PCL UI 方案（推荐）

与 PCL 同技术路线：**WPF + 系统 .NET**，不打包 WinUI/WASDK，不套浏览器。

```bat
python _pack_pcl_ui.py
```

或 `pack\build-pcl-ui.bat`

产物：`dist\PyMCL.exe`

- 界面：`PyMCL.Wpf`（侧栏 + 启动/实例/下载/设置）——**独立仓** [LQS660/PyMCL.Wpf](https://github.com/LQS660/PyMCL.Wpf)，需与本仓并排克隆，或用 `PYMCL_WPF_SRC` 指定
- 后端：`pymcl-bridge`（C）

## 运行时的两个目录（别把它们合成一个）

stub 把「程序文件」和「用户数据」分开放，两者生命周期完全不同：

| 目录 | 内容 | 生命周期 |
| --- | --- | --- |
| `%LOCALAPPDATA%\PyMCL\runtime\<载荷字节数>\` | 解包出来的程序文件：`ui/`、`native/`、`www/`、`ai_gateway/` | 每个包一份。目录名是载荷字节数（内容指纹），`marker` 比对命中就跳过解包 |
| `%LOCALAPPDATA%\PyMCL\home\` | 用户数据：`config.json`、`accounts.json`、`ai_chats.json`、`wpf-ui.json`、`wpf-theme.json`、`.minecraft/`、`cache/`… | 固定名，跨版本连续。`PYMCL_HOME` 与桥的 `--root` 都指向它 |

老版本把两者合在 `runtime\<指纹>\` 下，于是**每次重新打包都等于换一个数据目录**：用户的设置、账号、AI 对话全部留在上一个目录里读不到（表现就是「升级一次设置全丢」，而且每打包一次就多堆一个目录）。

- 首次用新版启动时会自动迁移：从 `runtime\` 下挑 `config.json` 修改时间最新的那个目录，把用户数据 `MoveFile` 过来（目标已存在的不覆盖），并写下 `.migrated` 标记，只迁一次。
- `home\www` 与 `home\ai_gateway` 是指回当前缓存目录的**目录联接**（junction）。C 桥只从 `--root` 找 `www`（`native/src/server.c` 的 `g_root/www` 没有 exe 相对兜底），而 `--root` 现在指向 `home`，所以 slim 包必须靠这个联接才能打开界面。联接失效（被删/被占）时下一次启动会自动重建并指向新指纹。
- 迁移是尽力而为：任何一步失败都只跳过，不会拦住启动。

系统依赖：

1. [.NET 8 Desktop Runtime](https://aka.ms/dotnet/download)（x64）——**不需要** Windows App Runtime

体积通常明显小于 WinUI 包（无 `Microsoft.Windows.SDK.NET.dll`）。

## 原生 WinUI（旧备选）

```bat
python _pack_native_ui.py
```

另需 Windows App Runtime；体积更大。

## 精简包（Edge 壳，仅体积优先）

```bat
pack\build-slim.bat
```

&lt;5MB，系统 Edge `--app`。默认请用上面的 WPF 包。

## 完整自包含 WinUI（旧）

```bat
pack\build-single.bat
```
