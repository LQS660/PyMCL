# 单文件打包

## WPF / PCL UI 方案（推荐）

与 PCL 同技术路线：**WPF + 系统 .NET**，不打包 WinUI/WASDK，不套浏览器。

```bat
python _pack_pcl_ui.py
```

或 `pack\build-pcl-ui.bat`

产物：`dist\PyMCL.exe`

- 界面：`wpf/PyMCL.Wpf`（侧栏 + 启动/实例/下载/设置）
- 后端：`pymcl-bridge`（C）
- 首次解压到 `%LOCALAPPDATA%\PyMCL\runtime\<ver>\`

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
