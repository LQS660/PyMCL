# 单文件打包

```bat
pack\build-single.bat
```

产物：`dist\PyMCL.exe`

- WinUI 目录发布（**不用** `PublishSingleFile`），自带 Windows App SDK，只需本机 **.NET 8 桌面运行时**
- 外层 7z LZMA2，首次运行解压到 `%LOCALAPPDATA%\PyMCL\runtime\<ver>\`
- `instances` / `config.json` / `java` / `cache` 写在 **exe 同目录**
