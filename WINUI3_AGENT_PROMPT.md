# 一次性任务：用正统 WinUI 3（C#）重写 PyMCL 全部 UI，并接到现有 Python 后端

你是能改代码、装环境、跑命令、自己排错的编程代理。本任务必须 **一次做完** 才向用户汇报。中途不要问、不要求确认、不要发进度、不要说「先搭壳再继续」。缺 C# / .NET / WinApp SDK / VS Build Tools 就自己装。现有 Qt 启动器必须还能用。

---

## 0. 完成前禁止

- 禁止中途 ping 用户、禁止半成品演示、禁止「环境缺 XX 请你安装」。
- 禁止改写 `mclauncher/` 里的安装/启动/下载算法（除非为暴露 IPC 加薄封装）。
- 禁止动现有 `app/` Qt UI 的默认入口：`python main.py` 仍打开现在的 Fluent/Qt 窗。
- 禁止用 Python 画 WinUI、禁止 pythonnet 嵌 WinUI、禁止 Uno/Avalonia 冒充 WinUI 3。
- 禁止只做空窗或假数据交差。必须真实调用本仓库 Python 后端。

全部做完后 **只发一次** 最终报告：路径、如何运行、已覆盖功能、已知缺口（应接近空）。

---

## 1. 目标（对应原先 6–8 周的成果）

在本仓库新增 **C# WinUI 3 前端**，功能对齐当前 Qt 启动器（白底、绿点缀 `#2E9B6B`），后端继续用 Python 包 `mclauncher/` + `app/backend.py` 的能力。

对照实现（只读，当规格）：

| 现有文件 | 职责 |
|----------|------|
| `app/main_window.py` | 主窗、侧栏、页面切换、任务徽章、下载坞 |
| `app/pcl_chrome.py` | 细顶栏、侧栏 5 项、下载任务钉底 |
| `app/pages/launch_page.py` | 启动 |
| `app/pages/instance_page.py` | 实例 |
| `app/pages/download_hub.py` | 下载区：顶部分类横条 |
| `app/pages/version_page.py` | 原版+加载器 |
| `app/pages/catalog_page.py` | Mod/整合包/数据包/资源包/光影 |
| `app/pages/java_page.py` | Java |
| `app/pages/settings_page.py` | 设置 |
| `app/pages/tasks_page.py` | 下载任务 + 底部 DownloadDock |
| `app/backend.py` | UI 唯一后端门面，全部方法必须能从 C# 调到 |

产品名：`PyMCL 启动器`，版本可标 `WinUI 3`。

---

## 2. 仓库与环境

- 工作区：`C:\Users\Administrator\Downloads\新建文件夹 (5)`
- OS：Windows 10 19045 x64
- **不要**把工程建到 Program Files。建在工作区内：`winui3/`（C# 工程）+ `bridge/`（Python IPC 服务，若需要）
- 现有 Python（优先）：`C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe`  
  若缺 `requests` / `PySide6`：IPC 服务 **不要依赖 Qt**。服务只用标准库 + `mclauncher` + `requests`。缺 `requests` 就 `pip install requests urllib3`。
- 自己补齐 C# 环境，静默安装，例如：
  1. `winget install Microsoft.DotNet.SDK.8 --accept-package-agreements --accept-source-agreements`
  2. `winget install Microsoft.WindowsAppRuntime.1.6`（或当前稳定 WinApp SDK Runtime）
  3. 若 `dotnet new winui` 不可用：安装 `Microsoft.WindowsAppSDK.CSharp` 工作负载 / `dotnet new install` 对应模板
  4. 需要编译原生：`winget install Microsoft.VisualStudio.2022.BuildTools`，加工作负载 `Microsoft.VisualStudio.Workload.VCTools` 与 Windows 10/11 SDK、.NET desktop
  5. 长期循环直到 `dotnet --version` ≥ 8 且工程能 `dotnet build`
- 目标框架：`net8.0-windows10.0.19041.0`（必须能在 Win10 19045 跑）
- 包：`Microsoft.WindowsAppSDK` 正式版，**Unpackaged**（`windowsAppSDKSelfContained` 或框架依赖 + 启动脚本），用户双击就能开，不必先 sideload MSIX。若 Unpackaged 失败再做 MSIX，但必须附带一键运行脚本。

---

## 3. 架构（必须）

```
[WinUI 3 C# 进程]  --stdin/stdout JSON-RPC 或 127.0.0.1 本地 HTTP-->  [Python 桥接进程]
                                                                      |
                                                                      +-- mclauncher.* （真实下载安装启动）
```

推荐：**本机 HTTP + SSE/chunk 推送进度**（好调试），或 **newline-delimited JSON over stdio**。选一种做完，文档写清。

Python 桥：

- 新文件例如 `bridge/server.py`，**不要 import PySide6 / qfluentwidgets**。
- 把 `app/backend.py` 的业务抽到无 Qt 的函数，或在桥里直接调 `mclauncher`（安装/启动/搜索），行为与 `BackendAPI` 一致。
- 工作目录 = 启动器根目录（与现在 `mclauncher.utils.ROOT` 相同），这样 `instances/`、`java/`、`config.json` 和 Qt 版共用。
- 启动：C# 启动时拉起  
  `pymcl5\python.exe bridge\server.py --root <仓库根>`  
  退出时杀掉子进程。

C# 侧：所有耗时走异步；进度回到 UI 线程（`DispatcherQueue`）。

---

## 4. 必须实现的 IPC 方法

与 `app/backend.py` 对齐。任务类返回 `task_id`，随后推送事件。

**任务（异步，带进度）：**

- `install_game(version, loader="无", loader_version="", instance="")`
- `install_modpack(name, source="Modrinth", extra={})`
- `install_mod(name, instance, extra={})`
- `install_shader` / `install_resourcepack` / `install_datapack`（name, instance, extra）
- `download_java(major)`
- `launch_game(instance, version, account, username, memory_mb, width, height, java="自动选择")`
- `start_microsoft_login()` → 推送 `login_code(code, uri)` + `login_status(text)`
- `cancel_task(task_id)`（启动中的游戏也要能杀进程，对标 `BackendAPI.cancel_task`）

**事件：**

- `task_added(task_id, title)`
- `progress(task_id, current, total, message)`
- `log(task_id, text)`
- `finished(task_id, success, message)`
- `task_count_changed(count)`
- `ui_changed`
- `login_code` / `login_status`

**同步查询：**

- `get_version_list` / `fetch_version_list`
- `get_installed_versions(instance)`
- `uninstall_version(spec)`  # 可能是 `"实例 / 版本"`
- `get_instances` / `create_instance` / `delete_instance` / `rename_instance` / `open_instance_folder`
- `search_mods` / `search_modpacks` / `search_shaders` / `search_resourcepacks` / `search_datapacks` `(query, source)`
- `get_installed_mods/shaders/resourcepacks/datapacks` + 对应 `delete_*`
- `get_java_list(scan_system)` / `java_combo_options` / `java_combo_label_for` / `get_instance_java` / `set_instance_java`
- `get_accounts` / `get_settings` / `save_settings`

`extra` 至少：`name, source, slug, id, path, url, instance, game_version`。  
`source` 必须用结果行的来源，不能把筛选框「全部」覆盖成唯一来源。

---

## 5. UI 规格（对齐当前 Qt，用正统 WinUI 3 控件）

视觉：浅色、白底 `#FFFFFF`、点缀绿 `#2E9B6B`、细顶栏约 40px、侧栏约 188px。用 `NavigationView` / 自定义侧栏均可，但信息架构必须如下。

**侧栏仅 5 项：**

- 上：启动、实例、下载、设置
- 弹簧 + 分隔线
- 底：**下载任务**（单独钉底，可有未完成数徽章）

点「下载」= 主区内打开下载页（**不要弹独立窗口**），顶部 **分类横条**（不是小方格）：

`原版游戏 | Mod | 整合包 | 数据包 | 资源包 | 光影包 | Java`

选中项绿字 + 下划线。

**启动页：** Banner、大按钮启动/停止、进度、实例/版本/账号/用户名/Java/内存滑条/分辨率、微软登录、实时日志。无版本时提示先去下载原版。Java 列表不要卡 UI，后台扫。

**实例页：** 卡片网格、新建/重命名/删除/开文件夹/每实例选 Java。

**原版页：** 搜索、正式版/快照、加载器（无/Fabric/Forge/Quilt/NeoForge）、安装、已安装勾选卸载。版本清单后台拉，缩放不要疯狂重建。

**目录页（五种）：** 名称/来源(全部|Modrinth|CurseForge)/版本/类型 + 搜索/重置 + 链接安装 + 本地导入。空闲文案「输入名称后点击搜索」，**禁止进入页面就全网搜索**。结果列表：名、简介、来源、下载量、安装。

**Java 页：** 本机环境列表、下载 8/11/17/21；系统扫描后台。

**设置页：** 共享 libraries/assets、下载线程、默认内存、分辨率、微软 Client ID、CurseForge key、保存到现有 `config.json`。

**下载任务页：** 任务卡片、进度、日志、取消。其它页进行中的下载可用底部坞（可选，对标 `DownloadDock`），在任务页则隐藏坞。

**微软登录：** 设备代码 + URI，能开浏览器。

交互：安装/启动走真实后端；失败用 InfoBar/TeachingTip；不要假进度冒充成功。

---

## 6. 运行与验收（自己做完并自测）

做完必须同时具备：

1. `winui3/` 能 `dotnet build` 成功。
2. 脚本 `winui3/run.bat`（或仓库根 `run-winui.bat`）：启动 Python 桥 + WinUI 程序。
3. README：`winui3/README.md` 写清环境、运行、与 Qt 版如何并存。
4. 自测（在最终报告里写证据：命令、退出码、日志摘要）。至少：
   - 冷启动窗体，侧栏 5 项、任务在底部
   - `get_instances` / `fetch_version_list` 有真实数据（可走 BMCLAPI/Mojang）
   - 搜索 Modrinth 模组有结果（允许镜像）
   - 点安装会创建 task 并刷进度（可用小文件：Java 或已缓存版本；不要假装成功）
   - Qt 的 `python main.py` 仍能启动（不要破坏）
5. 不要提交/上传密钥；沿用 `mclauncher/config.py` 已有 CurseForge key 逻辑即可。

覆盖清单（最终报告必须逐项 DONE/FAIL）：

- [ ] 环境自动安装
- [ ] Unpackaged WinUI 3 工程
- [ ] Python 无 Qt 桥 + JSON API
- [ ] 启动/停止游戏
- [ ] 实例 CRUD
- [ ] 原版+四加载器安装
- [ ] Mod/整合包/数据包/资源包/光影搜索安装
- [ ] Java 检测与下载
- [ ] 设置读写
- [ ] 任务列表+取消
- [ ] 微软登录 UI
- [ ] 与 Qt 数据目录共用
- [ ] run 脚本 + README

有 FAIL 就自己修到 DONE，再汇报。

---

## 7. 工作方式

1. 先读 `app/backend.py`、`app/main_window.py`、`mclauncher/installer.py` 入口，再写代码。
2. 先打通「C# 按钮 → Python `get_instances` → 列表显示」，再铺页面。
3. 大文件下载不要在最终验收里强制装完整 1.21；但安装任务路径必须真接到 `Installer`。
4. 代码用 UTF-8；C# 可空引用打开。
5. 全部完成后才发最终消息。
