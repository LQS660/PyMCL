# GOAL：C 桥去 Python 化——前端调用的全部 RPC 由 C 原生实现

> 统计时间：2026-09-25。方法数量由脚本实扫得出（口径见附录 C），代码变动后以重新扫描为准。

> **当前实况（2026-09-26 00:15 复扫，重建两版桥后实测）**：第 1 节的 55 / 37 / 96 与附录 A 的「现状」列只是 M0 基线，已经过时。实测：**原生 161 / 显式转发 14 / 隐式转发 13**（共 188）。进度：M0 完成；M1 完成 83/87（剩 `preflight_launch`、`apply_crash_action`、`set_account_skin`、`create_desktop_shortcut`，另有崩溃分析 / `export_crash_report` 两处内嵌 Python 未除）；M2 完成 4/11（剩 `list_catalog_files`、`check_mod_updates`、`apply_mod_update`、`submit_feedback`、`feedback_history`、`submit_crash_feedback`、`submit_crash_report`）；M3 剩 10 个全部未动；M4 陶瓦 11 个已原生化但对拍未收敛（Python 参考桥在本机起不来陶瓦内核，15 个用例超时报错无法对齐，已把陶瓦用例移到用例表末尾隔离）；M5 已完成对话存储 / 权限规则 / 测试连接 8 个，agent 循环未开始（`ai_agent.c` 仅 13 行 stub）。M6 未动：`backend.c:57/874`、`rpc_extra.c:43` 三处起 Python 与通用回落仍在。对拍 213 用例 198 过、方法 108/112。逐项证据见 [c-bridge-no-python-report.md](c-bridge-no-python-report.md)。

## 0. 目标（一句话）

让 `native/` 下的 C 桥（`pymcl-bridge.exe`）**原生实现 WPF 前端调用的全部 RPC 方法**，运行时完全不需要 Python；
`_pack_net48.py` 打出的桌面单文件 `PyMCL.exe` 在一台**没有 Python** 的 Windows 10/11 上，功能与 Python 桥版一致，安装包体积基本不变。

## 1. 背景与现状

- 前端 `wpf/PyMCL.Wpf`（net48）通过 HTTP JSON-RPC（`POST /rpc`，带 token）+ SSE 事件流与桥通信。
- C 桥：`native/src/*.c`，MinGW gcc 静态链接，运行时只依赖系统 DLL，当前 `pymcl-bridge.exe` 为 817,039 B；桌面 `PyMCL.exe` 为 2,331,618 B。
- WPF 一共调用 **188** 个不同的 RPC 方法，其中：
  - **55 个**已由 C 原生实现；
  - **37 个显式转发**：`native/src/rpc_extra.c` 里先 `py_rpc_call()`，失败再给降级兜底。不少兜底是「假成功」，例如 `test_ai_connection`（`rpc_extra.c:580`）把一句错误文字当成功结果返回，界面就弹出「AI 连接成功 / AI 需要 Python 桥」这种自相矛盾的提示；
  - **96 个隐式转发**：C 里完全没有实现，落到 `native/src/backend.c:824` 的通用 `py_rpc_call_ex()`，没有 Python 就直接报错。
- `py_rpc_call` 的机制：每次调用起一个 `python native/tools/py_rpc.py` 进程，`import bridge.api` 执行一次后退出（超时 120 秒）。桌面包里只有 `py_rpc.py`，没有 `bridge/`、`mclauncher/`，所以在用户机器上这 **133 个方法**全部不可用。开发机上看不出问题，是因为 exe 向上找到了项目根目录和开发用 Python。
- 最初说的「30 多个」只是显式转发那 37 个。要做到完整功能，隐式转发的 96 个也必须重写——其中包括 `get_setting`、`get_language`、`translate`、`list_themes`、`list_saves`、`is_game_running` 这类基础功能。
- 「原生」的方法里还藏着两处直接起 Python 进程：游戏崩溃分析（`backend.c` 的 `analyze_game_crash` → `python -m mclauncher.crash`）和 `export_crash_report`。这两处也在范围内（归 M1，参考实现 `mclauncher/crash.py`）。
- 已有的 55 个原生方法跟 Python 也不完全一致（M0 对拍基线里只有 9 个通过）：最大的差异是 C 桥还按旧的多实例结构（`.minecraft/<实例名>/`）找游戏目录，而 Python 已改为单目录模式（`.minecraft` 本身就是游戏目录，见 `mclauncher/instances.py`）；另有设置默认值、文案格式等差异。验收 B 要求这 55 个同样对拍通过，所以这些差异在 M1 一并修掉。
- **行为参考实现**（一切以它为准）：`bridge/api.py`（`BackendAPI`）+ `mclauncher/**`（约 2.2 万行）+ `mclauncher/locales/{zh_CN,en}.json`。

## 2. 范围

### 2.1 必须完成

1. 附录 A 列出的 133 个方法全部在 C 桥中原生实现。
2. AI 内核（`mclauncher/ai/`，约 5,500 行）在 C 中完整实现：OpenAI 兼容接口的流式对话、附录 B 的 36 个内置工具、权限规则与确认卡、`ask_user` 选择卡、检查点与撤回（rewind）、上下文压缩（compact）、子代理（`dispatch_subagent`）、计划（`update_plan`）、MCP stdio 客户端、对话存储。AI 工具要用到的 `search_worlds`、`install_world` 也在此一并实现（它们在显式转发列表里，但前端不直接调用）。
3. i18n：C 桥读取 `mclauncher/locales/*.json`，返回给界面的所有文字与 Python 版一样按当前语言翻译。
4. 移除 Python 回落路径：`py_rpc_call`、`py_rpc_call_ex`、`find_python` 及 `native/tools/py_rpc.py` 不再参与运行；打包产物中不含任何 `.py` 文件。

### 2.2 不做

- 不改 WPF 前端的调用方式和界面。确实需要修的前端 bug 可以修，但要在报告里单独列出。
- 不删除 Python 桥（`bridge/`、`mclauncher/`），它继续作为参考实现和开发调试后端（`PYMCL_BRIDGE=python`）。
- 不动 Qt、WinUI3、wpf32、eziapp 等其他前端。
- 不改任何磁盘数据格式（`config.json`、`accounts.json`、`ai_chats.json`、`playtime.json`、实例目录结构等）。C 桥与 Python 桥必须能交替读写同一份数据而不出错。

## 3. 硬约束

1. **语言与工具链**：C11，通过 `native/build.bat`（MinGW gcc，`-static`）构建。第三方代码只能以单文件库形式放进 `native/vendor/`（现有 cJSON、miniz），许可证须为 MIT / BSD / zlib / 公有领域。
2. **运行时依赖**：只允许 Windows 自带 DLL，不带任何旁路 DLL；HTTP/TLS 继续使用 WinHTTP。
3. **体积预算**：`pymcl-bridge.exe` ≤ 1.6 MB；桌面 `PyMCL.exe` ≤ 2.8 MB（现为 2.33 MB）。超出预算必须在报告中逐项说明来源。
4. **协议契约不变**：方法名、参数名与默认值、返回 JSON 结构、错误语义（失败时返回 JSON-RPC error，文案与 Python 一致）、SSE 事件名与字段，全部与 `bridge/api.py` 一致。
5. **禁止假成功**：做不到就返回错误，不许返回一句错误文字当成功结果。
6. **并发安全**：桥是多线程 HTTP 服务，共享状态（配置、任务表、AI 会话状态等）必须加锁；AI 同一时间只允许一个回合，语义与 Python 的 `_ai_busy` 一致。

## 4. 验收标准（全部满足才算通过）

每一条都必须有可重复执行的命令和机器可判定的结果。验证脚本放在项目根目录并以 `_c_` 开头（已被 `.gitignore` 的 `/_*.py` 覆盖；需要入库的放 `tests/`）。

### A. 覆盖率：每个方法都由 C 自己处理

- 编写 `_c_rpc_coverage.py`：用附录 C 的口径从 `wpf/PyMCL.Wpf/**/*.cs` 抽出全部 RPC 方法名，在「无 Python 环境」（见 E）里启动 C 桥，逐个用最小合法参数调用。
- **通过条件**：188/188 个方法的响应都不是 `unknown method`，也不含 `需要 Python`、`py_rpc`、`PYMCL_PYTHON` 字样。
- **静态检查**：`rg -n "py_rpc|find_python" native/src` 无输出。

### B. 行为一致：与 Python 桥逐个对拍

- 编写 `_c_py_parity.py`：准备一份固定测试数据根目录 `tests/fixtures/parity_root/`（含实例、版本、模组、存档、主题、账号、AI 对话等），各复制一份，分别启动 Python 桥（`bridge/server.py`）和 C 桥。按用例表 `tests/fixtures/parity_cases.json` 调用附录 A 的每个方法（每个方法至少 1 个正常用例 + 1 个异常用例），比较：
  1. 成功或失败一致；失败时错误文案一致；
  2. 返回值的 JSON 类型一致、对象键集合递归一致、确定性字段的值一致。时间戳、随机 id、临时路径等不确定字段写进白名单 `parity_ignore`，每一项都要写明理由；
  3. 调用后数据目录的文件变化一致：新增、删除、修改的文件列表相同，JSON 文件内容按同样规则比较。
- 联网方法一律用本地 mock 服务（录制回放）保证可重复：新闻、更新检查、加载器版本、CurseForge/Modrinth、皮肤站、Yggdrasil（authlib / 统一通行证）、反馈服务器。另保留 `--live` 模式跑真实网络，作为补充参考而不是门槛。
- **通过条件**：附录 A 的 133 个方法全部 PASS；原有 55 个原生方法也纳入对拍并全部 PASS（防回归）。

### C. 事件一致：后台任务与 AI

- **任务类方法**（附录 A 中调用形态为「任务」的）：录下两边的 SSE 事件流，比较事件名序列和字段键集合（`task_added` → `progress`… → `finished`，以及 `task_count_changed` 等），`finished` 的成功标志与文案一致；中途 `cancel_task` 时两边行为一致。
- **AI**：用本地 mock 的 OpenAI 兼容服务按脚本回放流式输出（普通文本、思考内容、工具调用、错误、超时、中途断流），对以下场景比对 `ai.status`、`ai.delta`、`ai.confirm`、`ai.ask`、`ai.done`、`ai.fail` 事件序列和最终的 `ai_chats.json`：
  1. 普通问答；
  2. 需要确认的工具调用：同意、拒绝、「始终允许」（写入权限规则）；
  3. `ask_user` 选择卡；
  4. 回合进行中 `ai_stop`；
  5. `ai_steer` 中途插话；
  6. 写文件后 `ai_rewind`，文件被检查点还原；
  7. 超长历史触发 compact；
  8. `dispatch_subagent` 子代理；
  9. `update_plan` 计划；
  10. 调用本地 stub MCP 服务器提供的工具；
  11. 上游返回 401 / 429 / 5xx、网络断开时的失败提示。
- 现有 Python 测试 `tests/test_ai_*.py` 覆盖的场景，在 C 版对拍用例里都要有对应项，并附一张对照表；不许只挑简单的场景。

### D. 界面端到端

- 在「无 Python 环境」里运行打包产物：`PyMCL.Wpf.exe --smoke` 全部页面通过，0 失败页、0 issues、i18n 缺词为空。
- 以下流程逐项实测并截图留证（可复用 `_wpf_smoke` 机制或 UI 自动化）：
  - 设置页 AI 测试连接：mock 正常时显示绿色成功；地址错误时显示红色失败，并说明原因；
  - AI 对话：发送、停止、确认卡；
  - 新闻、帮助、检查更新、清理；
  - 陶瓦联机：准备 → 房主 / 加入 → 快照状态变化；
  - 导出整合包，产物能被本启动器重新导入；
  - 外置登录（mock Yggdrasil）、模组更新检查、存档备份与恢复、主题导入导出；
  - 切换语言后界面文字正确。

### E. 「无 Python 环境」的定义

测试时必须同时满足：

- `where python` 无结果（PATH 中去掉所有 Python）；
- 未设置 `PYMCL_PYTHON`；
- `C:\Users\Administrator\.workbuddy\binaries\python` 不可访问（改名，或换一个新建的 Windows 用户）；
- 桥的工作根目录中没有 `bridge/`、`mclauncher/`。

推荐直接在 Windows 沙盒里运行桌面 `PyMCL.exe`。

### F. 构建、体积与依赖

- `native\build.bat` 构建成功，新增代码在 `-Wall` 下 0 警告。
- 满足第 3 节的体积预算；`objdump -p native\build\pymcl-bridge.exe | findstr "DLL Name"` 只列出系统 DLL。
- `_pack_net48.py` 出包成功，载荷中不含 `.py` 文件。

### G. 稳定性

- `--smoke` 连续跑 3 轮全部通过。
- AI mock 连续 50 个回合（含工具调用）：桥不崩溃、无句柄泄漏、内存增长 < 20 MB。
- 并发 20 个 RPC 请求不出现结果串台（参考 `rpc_extra.c` 注释里 py_rpc 临时文件串台的历史 bug）。

## 5. 里程碑

每个阶段单独过验收，再进入下一阶段。

| 阶段 | 内容 | 方法数 | 本阶段验收 |
|---|---|---|---|
| M0 基建 | 覆盖率脚本、对拍框架、固定数据根目录与用例表、无 Python 运行器；给 C 桥加编译开关 `PYMCL_NO_PY` 关闭 Python 回落 | 0 | 跑出基线报告：静态 55 原生 / 133 转发，对拍基线 |
| M1 本地功能 | 设置、语言与翻译、主题、背景、存档与备份、媒体、版本操作与隔离、收藏、缩略图、服务器导入导出、Java 标签、启动命令、快捷方式、系统信息、清理、帮助、启动预检与崩溃修复动作、崩溃分析与导出、官方启动器探测等；并把已有 55 个原生方法对齐到 Python（单目录模式等） | 87 | 这 87 个方法 + 原有 55 个 A、B 全过 |
| M2 联网功能 | 先搭 HTTP 录制回放与 Yggdrasil mock 服务；新闻、更新检查、加载器版本、资源文件列表、模组更新检查与应用、反馈提交与历史、崩溃上报 | 11 | A、B 全过（mock 模式） |
| M3 后台任务 | 修复版本、导出整合包、备份存档、安装 Java、官方启动器迁移、导出启动脚本、authlib / 统一通行证登录、模组批量更新、自更新 | 10 | A、B、C（任务事件）全过 |
| M4 陶瓦联机 | 陶瓦核心进程的下载与启停、状态机与快照、房主 / 加入 / 直连、防火墙放行 | 11 | A、B、C 全过，并完成 D 中的联机实测 |
| M5 AI | 先搭 OpenAI 兼容 mock 服务（MCP stub 复用 `tests/fixtures/mcp_echo_server.py`）；流式客户端、对话存储、agent 循环、36 个工具、权限与确认、ask 卡、检查点与撤回、压缩、子代理、计划、MCP、测试连接 | 14 + 内核 | A、B、C（AI 11 个场景）全过 |
| M6 收尾 | 删除 Python 回落代码与 `py_rpc.py`、重新打包、无 Python 环境端到端、体积与依赖检查、稳定性 | — | 第 4 节 A–G 全部通过 |

## 6. 怎么算「做完」

- 第 4 节 A–G 每一项都给出：执行的命令、原始输出或日志路径、PASS / FAIL。**任何一项 FAIL 都不算完成。**
- 交付报告 `docs/c-bridge-no-python-report.md`：通过情况总表、改前改后的体积对比、对拍白名单全文及理由、已知差异（功能性差异必须为 0）、新增和修改的文件清单。
- 不许用「跳过用例 / 放宽比较 / 删除测试」换取通过。确实无法对齐的差异，停下来报给人决定。

## 附录 A：需要在 C 中重写的 133 个方法

「显式转发」= `rpc_extra.c` 里先调 Python、失败再兜底；「隐式转发」= C 里没有实现，走 `backend.c:824` 的通用 Python 回落。

| 阶段 | 方法 | 现状 | 调用形态 | Python 参考实现 | 主要依赖模块 |
|---|---|---|---|---|---|
| M1 本地功能 | `allow_multi_instance` | 隐式转发 | 同步 | `bridge/api.py:2594` | — |
| M1 本地功能 | `apply_crash_action` | 显式转发 | 同步 | `bridge/api.py:1285` | crash, version_settings |
| M1 本地功能 | `available_languages` | 隐式转发 | 同步 | `bridge/api.py:2377` | i18n |
| M1 本地功能 | `background_history` | 隐式转发 | 同步 | `bridge/api.py:3246` | config |
| M1 本地功能 | `build_launch_command` | 隐式转发 | 同步 | `bridge/api.py:733` | launcher, version_settings |
| M1 本地功能 | `can_undo_background` | 隐式转发 | 同步 | `bridge/api.py:3251` | config |
| M1 本地功能 | `catalog_favorites` | 隐式转发 | 同步 | `bridge/api.py:613` | — |
| M1 本地功能 | `cleaner_apply` | 显式转发 | 同步 | `bridge/api.py:1395` | cleaner |
| M1 本地功能 | `cleaner_preview` | 显式转发 | 同步 | `bridge/api.py:1391` | cleaner |
| M1 本地功能 | `collect_sysinfo` | 隐式转发 | 同步 | `bridge/api.py:1123` | sysinfo |
| M1 本地功能 | `copy_version` | 隐式转发 | 同步 | `bridge/api.py:497` | version_ops |
| M1 本地功能 | `create_desktop_shortcut` | 隐式转发 | 同步 | `bridge/api.py:512` | shortcut |
| M1 本地功能 | `default_export_dir` | 隐式转发 | 同步 | `bridge/api.py:3096` | content_export |
| M1 本地功能 | `delete_modpack` | 隐式转发 | 同步 | `bridge/api.py:589` | — |
| M1 本地功能 | `delete_save` | 隐式转发 | 同步 | `bridge/api.py:554` | saves |
| M1 本地功能 | `delete_save_backup` | 隐式转发 | 同步 | `bridge/api.py:541` | saves |
| M1 本地功能 | `delete_theme` | 隐式转发 | 同步 | `bridge/api.py:2447` | themes |
| M1 本地功能 | `detect_official_launcher` | 隐式转发 | 同步 | `bridge/api.py:2537` | official_migrate |
| M1 本地功能 | `ensure_thumb` | 隐式转发 | 同步 | `bridge/api.py:2336` | thumbnails, thumb |
| M1 本地功能 | `export_content` | 隐式转发 | 同步 | `bridge/api.py:3104` | content_export |
| M1 本地功能 | `export_contents` | 隐式转发 | 同步 | `bridge/api.py:3110` | content_export |
| M1 本地功能 | `export_save` | 隐式转发 | 同步 | `bridge/api.py:546` | saves |
| M1 本地功能 | `export_servers` | 隐式转发 | 同步 | `bridge/api.py:2298` | servers |
| M1 本地功能 | `export_theme` | 隐式转发 | 同步 | `bridge/api.py:2455` | themes |
| M1 本地功能 | `game_root_name` | 隐式转发 | 同步 | `bridge/api.py:3117` | instances |
| M1 本地功能 | `game_root_path` | 隐式转发 | 同步 | `bridge/api.py:3122` | — |
| M1 本地功能 | `get_account_skin` | 隐式转发 | 同步 | `bridge/api.py:1226` | skin |
| M1 本地功能 | `get_language` | 隐式转发 | 同步 | `bridge/api.py:2369` | i18n |
| M1 本地功能 | `get_launch_command` | 隐式转发 | 同步 | `bridge/api.py:2617` | launch_flow, launcher, manifest, java |
| M1 本地功能 | `get_mods_targets` | 隐式转发 | 同步 | `bridge/api.py:1437` | version_settings |
| M1 本地功能 | `get_playtime` | 隐式转发 | 同步 | `bridge/api.py:2307` | playtime |
| M1 本地功能 | `get_saves_targets` | 隐式转发 | 同步 | `bridge/api.py:3126` | version_settings |
| M1 本地功能 | `get_setting` | 隐式转发 | 同步 | `bridge/api.py:842` | — |
| M1 本地功能 | `get_smart_recommendation` | 隐式转发 | 同步 | `bridge/api.py:2660` | sysinfo |
| M1 本地功能 | `get_total_playtime` | 隐式转发 | 同步 | `bridge/api.py:2316` | playtime |
| M1 本地功能 | `get_version_isolation` | 隐式转发 | 同步 | `bridge/api.py:3138` | version_settings |
| M1 本地功能 | `get_version_rows` | 隐式转发 | 同步 | `bridge/api.py:3187` | version_settings |
| M1 本地功能 | `help_article` | 显式转发 | 同步 | `bridge/api.py:1150` | help_content |
| M1 本地功能 | `help_articles` | 显式转发 | 同步 | `bridge/api.py:1146` | help_content |
| M1 本地功能 | `hide_version` | 隐式转发 | 同步 | `bridge/api.py:501` | version_ops |
| M1 本地功能 | `import_servers` | 隐式转发 | 同步 | `bridge/api.py:2293` | servers |
| M1 本地功能 | `import_theme` | 隐式转发 | 同步 | `bridge/api.py:2451` | themes |
| M1 本地功能 | `install_datapack_into_save` | 隐式转发 | 同步 | `bridge/api.py:562` | saves |
| M1 本地功能 | `instance_java_label` | 隐式转发 | 同步 | `bridge/api.py:1838` | java |
| M1 本地功能 | `is_download_title` | 隐式转发 | 同步 | `bridge/api.py:3222` | — |
| M1 本地功能 | `is_game_running` | 隐式转发 | 同步 | `bridge/api.py:2589` | — |
| M1 本地功能 | `java_vendor_label` | 隐式转发 | 同步 | `bridge/api.py:2348` | java |
| M1 本地功能 | `java_vendor_list` | 隐式转发 | 同步 | `bridge/api.py:2344` | java |
| M1 本地功能 | `lan_hint` | 显式转发 | 同步 | `bridge/api.py:1411` | lan |
| M1 本地功能 | `list_global_mods` | 隐式转发 | 同步 | `bridge/api.py:602` | global_mods |
| M1 本地功能 | `list_media` | 隐式转发 | 同步 | `bridge/api.py:567` | saves |
| M1 本地功能 | `list_save_backups` | 隐式转发 | 同步 | `bridge/api.py:529` | saves |
| M1 本地功能 | `list_saves` | 隐式转发 | 同步 | `bridge/api.py:550` | saves |
| M1 本地功能 | `list_themes` | 隐式转发 | 同步 | `bridge/api.py:2435` | themes |
| M1 本地功能 | `load_theme` | 隐式转发 | 同步 | `bridge/api.py:2443` | themes |
| M1 本地功能 | `loader_of` | 隐式转发 | 同步 | `bridge/api.py:3165` | i18n |
| M1 本地功能 | `local_ips` | 隐式转发 | 同步 | `bridge/api.py:1415` | lan |
| M1 本地功能 | `normalize_java_pref` | 隐式转发 | 同步 | `bridge/api.py:1800` | java |
| M1 本地功能 | `official_launcher_dir` | 隐式转发 | 同步 | `bridge/api.py:2541` | official_migrate |
| M1 本地功能 | `open_media` | 隐式转发 | 同步 | `bridge/api.py:571` | — |
| M1 本地功能 | `open_mods_folder` | 隐式转发 | 同步 | `bridge/api.py:1447` | — |
| M1 本地功能 | `open_save` | 隐式转发 | 同步 | `bridge/api.py:558` | saves |
| M1 本地功能 | `open_version_folder` | 隐式转发 | 同步 | `bridge/api.py:505` | version_ops |
| M1 本地功能 | `preflight_launch` | 显式转发 | 同步 | `bridge/api.py:1273` | instances, preflight |
| M1 本地功能 | `remember_export_dir` | 隐式转发 | 同步 | `bridge/api.py:3100` | content_export |
| M1 本地功能 | `rename_version` | 隐式转发 | 同步 | `bridge/api.py:493` | version_ops |
| M1 本地功能 | `reset_background` | 隐式转发 | 同步 | `bridge/api.py:3273` | config |
| M1 本地功能 | `restore_save_backup` | 隐式转发 | 同步 | `bridge/api.py:533` | saves |
| M1 本地功能 | `save_theme` | 隐式转发 | 同步 | `bridge/api.py:2439` | themes |
| M1 本地功能 | `scan_official_versions` | 隐式转发 | 同步 | `bridge/api.py:2546` | official_migrate |
| M1 本地功能 | `set_account_skin` | 隐式转发 | 同步 | `bridge/api.py:1188` | skin |
| M1 本地功能 | `set_game_dir` | 隐式转发 | 同步 | `bridge/api.py:574` | — |
| M1 本地功能 | `set_global_mod_enabled` | 隐式转发 | 同步 | `bridge/api.py:606` | global_mods |
| M1 本地功能 | `set_language` | 隐式转发 | 同步 | `bridge/api.py:2373` | i18n |
| M1 本地功能 | `set_multi_instance` | 隐式转发 | 同步 | `bridge/api.py:2597` | — |
| M1 本地功能 | `set_version_isolation` | 隐式转发 | 同步 | `bridge/api.py:3142` | version_settings |
| M1 本地功能 | `skin_urls` | 隐式转发 | 同步 | `bridge/api.py:1419` | skin |
| M1 本地功能 | `stash_upload` | 隐式转发 | 同步 | `bridge/api.py:2389` | — |
| M1 本地功能 | `sysinfo_text` | 隐式转发 | 同步 | `bridge/api.py:1127` | sysinfo |
| M1 本地功能 | `task_title` | 隐式转发 | 同步 | `bridge/api.py:317` | — |
| M1 本地功能 | `thumb_path` | 隐式转发 | 同步 | `bridge/api.py:2332` | thumbnails, thumb |
| M1 本地功能 | `toggle_favorite` | 隐式转发 | 同步 | `bridge/api.py:616` | — |
| M1 本地功能 | `toggle_version_isolation` | 隐式转发 | 同步 | `bridge/api.py:3149` | version_settings |
| M1 本地功能 | `translate` | 隐式转发 | 同步 | `bridge/api.py:2381` | i18n |
| M1 本地功能 | `undo_background` | 隐式转发 | 同步 | `bridge/api.py:3255` | config |
| M1 本地功能 | `update_server` | 显式转发 | 同步 | `bridge/api.py:2283` | servers |
| M1 本地功能 | `wait_task` | 隐式转发 | 同步 | `bridge/api.py:849` | — |
| M2 联网功能 | `apply_mod_update` | 隐式转发 | 同步 | `bridge/api.py:1385` | mod_update |
| M2 联网功能 | `cached_news` | 显式转发 | 同步 | `bridge/api.py:1407` | news |
| M2 联网功能 | `check_mod_updates` | 隐式转发 | 同步 | `bridge/api.py:1378` | mod_update |
| M2 联网功能 | `check_update` | 显式转发 | 同步 | `bridge/api.py:1399` | updater |
| M2 联网功能 | `feedback_history` | 隐式转发 | 同步 | `bridge/api.py:1142` | feedback |
| M2 联网功能 | `fetch_news` | 显式转发 | 同步 | `bridge/api.py:1403` | news |
| M2 联网功能 | `list_catalog_files` | 显式转发 | 同步 | `bridge/api.py:479` | catalog_files |
| M2 联网功能 | `list_loader_versions` | 显式转发 | 同步 | `bridge/api.py:483` | loader_meta |
| M2 联网功能 | `submit_crash_feedback` | 隐式转发 | 同步 | `bridge/api.py:1138` | feedback |
| M2 联网功能 | `submit_crash_report` | 隐式转发 | 同步 | `bridge/api.py:2605` | feedback |
| M2 联网功能 | `submit_feedback` | 显式转发 | 同步 | `bridge/api.py:1131` | feedback |
| M3 后台任务 | `backup_save` | 隐式转发 | 任务 | `bridge/api.py:517` | — |
| M3 后台任务 | `export_launch_script` | 隐式转发 | 任务 | `bridge/api.py:509` | — |
| M3 后台任务 | `export_modpack` | 显式转发 | 任务 | `bridge/api.py:1375` | — |
| M3 后台任务 | `install_java` | 隐式转发 | 任务 | `bridge/api.py:2352` | — |
| M3 后台任务 | `migrate_official_launcher` | 隐式转发 | 任务 | `bridge/api.py:2553` | — |
| M3 后台任务 | `repair_version` | 显式转发 | 任务 | `bridge/api.py:1270` | — |
| M3 后台任务 | `start_authlib_login` | 显式转发 | 任务 | `bridge/api.py:1257` | — |
| M3 后台任务 | `start_mod_updates` | 显式转发 | 任务 | `bridge/api.py:1382` | — |
| M3 后台任务 | `start_nide8_login` | 显式转发 | 任务 | `bridge/api.py:610` | — |
| M3 后台任务 | `start_self_update` | 显式转发 | 任务 | `bridge/api.py:1477` | — |
| M4 陶瓦联机 | `terracotta_allow_firewall` | 显式转发 | 同步 | `bridge/api.py:664` | terracotta |
| M4 陶瓦联机 | `terracotta_direct_connect` | 隐式转发 | 同步 | `bridge/api.py:680` | terracotta |
| M4 陶瓦联机 | `terracotta_enter_world` | 隐式转发 | 同步 | `bridge/api.py:673` | terracotta |
| M4 陶瓦联机 | `terracotta_host` | 显式转发 | 同步 | `bridge/api.py:655` | terracotta |
| M4 陶瓦联机 | `terracotta_idle` | 显式转发 | 同步 | `bridge/api.py:661` | terracotta |
| M4 陶瓦联机 | `terracotta_join` | 显式转发 | 同步 | `bridge/api.py:658` | terracotta |
| M4 陶瓦联机 | `terracotta_open_firewall_settings` | 显式转发 | 同步 | `bridge/api.py:667` | terracotta |
| M4 陶瓦联机 | `terracotta_player` | 隐式转发 | 同步 | `bridge/api.py:642` | — |
| M4 陶瓦联机 | `terracotta_prepare` | 显式转发 | 任务 | `bridge/api.py:652` | — |
| M4 陶瓦联机 | `terracotta_shutdown` | 显式转发 | 同步 | `bridge/api.py:670` | terracotta |
| M4 陶瓦联机 | `terracotta_snapshot` | 显式转发 | 同步 | `bridge/api.py:648` | terracotta |
| M5 AI | `ai_answer` | 显式转发 | 同步 | `bridge/api.py:2809` | — |
| M5 AI | `ai_confirm` | 显式转发 | 同步 | `bridge/api.py:2770` | ai |
| M5 AI | `ai_delete_chat` | 显式转发 | 同步 | `bridge/api.py:2706` | ai |
| M5 AI | `ai_list_chats` | 显式转发 | 同步 | `bridge/api.py:2669` | ai |
| M5 AI | `ai_new_chat` | 显式转发 | 同步 | `bridge/api.py:2700` | ai |
| M5 AI | `ai_permission_rule_add` | 隐式转发 | 同步 | `bridge/api.py:2791` | ai |
| M5 AI | `ai_permission_rule_remove` | 隐式转发 | 同步 | `bridge/api.py:2804` | ai |
| M5 AI | `ai_permission_rules` | 隐式转发 | 同步 | `bridge/api.py:2787` | ai |
| M5 AI | `ai_rewind` | 隐式转发 | 同步 | `bridge/api.py:2718` | ai |
| M5 AI | `ai_send` | 显式转发 | 异步（ai.* 事件） | `bridge/api.py:2814` | — |
| M5 AI | `ai_set_active` | 显式转发 | 同步 | `bridge/api.py:2712` | ai |
| M5 AI | `ai_steer` | 隐式转发 | 同步 | `bridge/api.py:2829` | — |
| M5 AI | `ai_stop` | 显式转发 | 同步 | `bridge/api.py:2755` | — |
| M5 AI | `test_ai_connection` | 显式转发 | 同步 | `bridge/api.py:2664` | ai |

## 附录 B：AI 内置工具（36 个，定义见 `mclauncher/ai/tools.py` 的 `TOOL_META`）

`ask_user` `get_launcher_state` `list_instances` `list_installed_versions` `search_versions` `search_mods` `search_modpacks` `list_mods` `install_game` `install_mod` `install_modpack` `install_shader` `install_resourcepack` `install_datapack` `search_content` `search_worlds` `install_world` `create_instance` `delete_instance` `delete_mod` `disable_mod` `enable_mod` `get_java_list` `download_java` `launch_game` `diagnose_launch` `get_latest_log` `get_crash_report` `scan_mod_conflicts` `inspect_mod` `list_mod_configs` `read_mod_config` `write_mod_config` `read_artifact` `dispatch_subagent` `update_plan`

其中不少工具可以直接复用 C 桥已有的实现（安装游戏 / 模组 / 整合包、搜索、Java、启动等），但工具的参数校验、只读标记、权限判定和返回文案必须与 Python 版一致。

## 附录 C：统计口径

- **WPF 调用的方法**：用正则 `(CallAsync|TryCallAsync|StartTaskAsync|CallRawAsync|Call)(<…>)?\("name"` 扫描 `wpf/PyMCL.Wpf/**/*.cs`（排除 `bin/`、`obj/`），共 188 个，且全部能在 `bridge/api.py` 中找到。
- **C 原生**：`native/src/*.c` 中出现 `strcmp(method, "name") == 0`，且不在调用 `py_rpc_call` 的 if 分支条件里。
- **显式转发**：`rpc_extra.c` 中调用 `py_rpc_call(method, …)` 的 if 分支所列方法（共 39 个，其中 37 个被 WPF 调用；`install_world`、`search_worlds` 由 AI 工具使用，归入 M5）。
- **隐式转发**：WPF 调用、C 中没有、`bridge/api.py` 中有的方法（96 个）。
- 附录 A 的「阶段」「调用形态」「主要依赖模块」由脚本按 `bridge/api.py` 方法体自动归类，实施时可按实际依赖调整顺序，但总范围不能缩小。
