# C 桥去 Python 化：进度报告

目标与验收标准见 [GOAL-c-bridge-no-python.md](GOAL-c-bridge-no-python.md)。本文件按里程碑追加记录，每一项都附执行的命令与结果。

## M0 基建（2026-09-25）

### 做了什么

| 项 | 文件 |
|---|---|
| 无 Python 构建：`native\build.bat nopy` 产出 `build\pymcl-bridge-nopy.exe`，编译开关 `PYMCL_NO_PY` 关掉全部 Python 回落（`py_rpc_call_ex` 直接返回 `NOT_NATIVE` 错误；崩溃分析与 `export_crash_report` 不再起 Python） | `native/build.bat`、`native/src/rpc_extra.c`、`native/src/backend.c` |
| 覆盖率脚本：静态扫 WPF 调用与 C 分发，再用无 Python 构建在临时数据根、去掉 Python 的 PATH 里动态探测 | `_c_rpc_coverage.py` |
| 对拍框架：两份夹具拷贝分别起 Python 桥与 C 桥，比较成功/失败与错误文案、返回值、数据目录文件变化 | `_c_py_parity.py` |
| 固定数据根目录（单目录模式，含两个版本、两个模组、一个存档）的生成脚本。产物 `tests/fixtures/parity_root/` 命中 `.gitignore` 的 `config.json`、`.minecraft/` 规则，不入库；两个验收脚本发现缺失会自动生成 | `tests/fixtures/build_parity_root.py` |
| 首批对拍用例 59 个（55 个方法，均为不碰本机其它位置的读操作） | `tests/fixtures/parity_cases.json` |

### 顺手修掉的 C 桥基础问题

这三处不修，覆盖率和对拍的结果都不可信：

1. `rpc_align_call` 里的原生分支失败返回 NULL 时，`backend_call` 会当成「没处理」继续落到 Python 回落，真实错误被盖成 `unknown method`（`enable_mod`、`disable_mod`、`add_server` 传错参数时就是这样）。现在加了 `handled` 出参，原生分支失败直接返回原生错误。
2. 错误信息缓冲区 `g_err` 是全局共享的，多线程下 A 请求的错误可能回给 B 请求。改为线程局部（`_Thread_local`）。
3. 每个 RPC 开始前清空错误信息，避免上一次调用的残留错误被当成这一次的原因。

默认构建（`native\build.bat`）的行为只受第 1–3 条影响，其余改动都在 `PYMCL_NO_PY` 开关后面。

### 基线结果

覆盖率（`python _c_rpc_coverage.py`）：

- WPF 调用的 RPC 方法 188 个：C 原生 55，显式转发 37，隐式转发 96。
- C 源码里直接起 Python 进程的位置 3 处：`backend.c` 崩溃分析、`backend.c` 的 `export_crash_report`、`rpc_extra.c` 的 `py_rpc_call_ex`。
- `backend.c` 的通用 Python 回落仍在。
- 动态探测：49 个成功，9 个原生报参数错误（算原生），74 个 `NOT_NATIVE / unknown method`，56 个因会动到本机其它位置而跳过（只做静态判定）。
- 验收 4.A：**FAIL**（55/188），符合 M0 预期。

对拍（`python _c_py_parity.py`）：用例 9/59 通过，方法 9/55 通过。

- 通过：`get_version_settings`、`get_java_list`、`get_instance_java`、`list_servers`、`get_layout`、`get_accounts`、`get_account_rows`、`authlib_presets`、`get_crash`。
- 已有原生方法里就不一致的：
  - `get_instances` / `get_installed_versions` / `get_installed_mod_entries`：C 按旧的 `.minecraft/<实例名>/` 找游戏目录，Python 已是单目录模式，C 看到 0 个版本、0 个模组；
  - `get_settings`：C 缺 `ai_api_key`、`ai_base_url`、`ai_confirm_writes` 等一批默认键；
  - `format_playtime`：C 输出「1 小时 2 分」，Python 是「1 小时 2 分钟」；
  - `get_all_playtime`：返回结构不同；
  - `ai_list_chats`：Python 首次读取时会建一个默认对话并返回 `busy`、`pending_card`，C 返回空。
- 其余失败都是方法尚未原生实现，或是显式转发的假兜底（如 `help_articles` 返回空列表、`lan_hint` 返回「请安装 Python」）。

### 调整

- mock 服务不在 M0 做，挪到真正用到它们的阶段：HTTP 录制回放与 Yggdrasil 放 M2 开头，OpenAI 兼容服务放 M5 开头（MCP stub 复用现成的 `tests/fixtures/mcp_echo_server.py`）。GOAL 文件第 5 节已同步。

## M1 本地功能（进行中，2026-09-25）

### 基础对齐（影响面最大的几处）

- **配置**：`native/src/config.c` 按 `mclauncher/config.py` 重写：出厂键表逐键一致（含顺序），读盘合并、未知键保留、两个迁移（旧 `instances/` 目录、默认隔离档位）与缺键即落盘的规则一致。
- **落盘格式**：`pymcl_write_json` 改为与 `utils.write_json` 相同的 `indent=2, ensure_ascii=False` 格式并原子替换；读 JSON 兼容 UTF-8 BOM。两个桥交替写同一份 `config.json` 时内容逐字节一致。
- **单目录模式**：`native/src/instances.c` 按 `mclauncher/instances.py` 重写 `instance_path` / `instance_list` / 建删改名：`.minecraft` 本身带 `.instance.json` 时 `default` 等旧名一律落到游戏目录，旧子实例只保留读取；新增 `instance_open()` 对应 Python 的 `_instance()`（不存在就建、存在就补齐标准子目录）。
- **Python 语义工具**：`native/src/pyval.c`（`bool(x)`、`int(x)`、`x or default`、`str(x)`、`list(x)` 等），移植时照着 Python 表达式逐个套用。
- **i18n**：`native/src/i18n.c`，读 `mclauncher/locales/*.json`（打包后放 `native/data/locales/`），启动时按 `PYMCL_LANG` 或 `config.json` 的 `language` 初始化，行为与 `mclauncher/i18n.py` 一致。

### 已原生实现（新增文件）

| 文件 | 方法 |
|---|---|
| `settings.c` | `get_settings`（全部键）、`get_setting` |
| `rpc_local.c` | 语言与翻译、收藏、mods/存档目标、Java 偏好与发行版标签、游戏时长、游戏目录名与路径、多开开关、下载任务判定、加载器标签、版本隔离查询、版本管理页数据、已装模组列表、删除整合包标记、导出目录、壁纸历史/撤销/重置、帮助、局域网地址、系统信息 |
| `rpc_content.c` | 存档列表/删除/打开/备份列表/还原/删除备份/导出、截图与日志列表、打开媒体与 mods 目录、全局模组、主题包六件套、清理预览与执行、皮肤地址、账号皮肤读取、上传暂存、设置游戏目录 |
| `servers.c` | 服务器列表增删改查、批量导入导出（`servers.dat` NBT 读写） |
| `rpc_versions.c` | 版本改名/复制/隐藏/打开目录、切换隔离（含 `mklink /J` 联接与种子复制）、内容导出（单个/批量）、官方启动器探测与版本扫描、缩略图路径与下载缓存 |
| `sysinfo.c` | `collect_sysinfo`、`sysinfo_text`、`get_smart_recommendation`（CPU/显卡同样走 PowerShell 的 WMI 查询） |
| `backend.c`（补） | `task_title`、`list_tasks`、`wait_task`、`is_game_running`、`instance_java_label` |
| `rpc_net.c`（M2 先行） | `fetch_news`、`cached_news`、`check_update`、`list_loader_versions` |

支撑代码：`zip.c` 新增 zip 写入（zlib deflate）与目录遍历；`util.c` 新增有序目录列举、`str(Path)` 规范化、base64、URL 编码、mtime。

### 对拍

- 离线用例 `tests/fixtures/parity_cases.json`（182 个，读写都有，含异常用例）：`python _c_py_parity.py` → **182/182 通过，方法 101/101**。
- 联网用例单独放 `tests/fixtures/parity_cases_net.json`（新闻、更新检查、加载器版本、缩略图），`python _c_py_parity.py --cases tests/fixtures/parity_cases_net.json` 手动跑：网络正常时全部通过；Python 端的 requests 在本机会偶发超时并卡住整个参考桥，所以不放进默认用例表，等录制回放 mock 就位后并回去。
- 覆盖率（静态，`python _c_rpc_coverage.py --static-only`）：**C 原生 148 / 188**（M0 时 55）。还剩 40 个：
  - M5 AI 回合：`ai_send`、`ai_stop`、`ai_confirm`、`ai_answer`、`ai_steer`、`ai_rewind`（对话存储、权限规则、测试连接已完成）；
  - M4 陶瓦联机 11 个；
  - M3 后台任务 10 个：`backup_save`、`export_launch_script`、`export_modpack`、`install_java`、`migrate_official_launcher`、`repair_version`、`start_authlib_login`、`start_nide8_login`、`start_mod_updates`、`start_self_update`；
  - M2 联网 7 个：`list_catalog_files`、`check_mod_updates`、`apply_mod_update`、`submit_feedback`、`feedback_history`、`submit_crash_feedback`、`submit_crash_report`；
  - M1 本地 6 个：`preflight_launch`、`apply_crash_action`、`build_launch_command`、`get_launch_command`、`set_account_skin`、`create_desktop_shortcut`；
  - 另有 3 处直接起 Python（崩溃分析、`export_crash_report`、`py_rpc_call_ex`）与 `backend.c` 的通用回落，M6 移除。
- 体积：`pymcl-bridge.exe` 1,016,129 B（M0 时 817,039 B，预算 1.6 MB）。

### 已完成的 M5 部分

`ai_store.c`：`ai_list_chats`、`ai_new_chat`、`ai_delete_chat`、`ai_set_active`（`ai_chats.json` 格式与 `mclauncher/ai/store.py` 一致）、`ai_permission_rules` / `ai_permission_rule_add` / `ai_permission_rule_remove`（`ai_permissions.json` 与 `permission.py` 一致；规则 key 里的 `\0` 分隔符由 `server.c` 在进出桥时转换）、`test_ai_connection`（`resolve_endpoint` 的各种报错文案一致）。

### 发现并记录的问题

1. **Python 参考实现把 `servers.dat` 按 gzip 读写**（`terracotta._read_servers/_write_servers`），而原版游戏读的是未压缩 NBT：启动器写进去的服务器在游戏的多人列表里读不出来。C 端为保持一致照搬了这一行为，建议两边一起修。
2. `official_launcher_dir` 在找不到官方目录时 Python 返回 `"."`（`Path("")` 恒为真），C 端照搬。
3. 实时联网对拍会受网络影响：本机环境下 Python 的 requests 连不上 `maven.neoforged.net`（连接被重置），C 端走 WinHTTP 能取到数据，所以 `list_loader_versions(1.21.1, neoforge)` 两边不一致——是环境问题不是实现问题，这条用例暂时移出默认用例表，等 M2 的录制回放 mock 服务搭好后改用回放数据。
4. 桌面快捷方式在 Python 里指向 Python CLI（`python main.py -i … launch …`）。无 Python 的打包版需要一个 C 端的命令行启动入口才能等价实现，放到 M6 与打包一起做。

### M1 剩余

`preflight_launch`、`apply_crash_action`、`build_launch_command`、`get_launch_command`、`set_account_skin`、`create_desktop_shortcut`，以及崩溃分析 / `export_crash_report`（`mclauncher/crash.py`，约 1300 行）。

## 复验（2026-09-25 23:10，新会话接手时对照 GOAL 文档实扫）

GOAL 文档第 1 节的 55 / 37 / 96 是 M0 基线旧数，已在 GOAL 顶部加「当前实况」横幅并在附录口径下重扫。本次重建两版桥后实测：

- 覆盖率（`python _c_rpc_coverage.py`，动态探测含重建后的 nopy exe）：**原生 159 / 显式转发 14 / 隐式转发 15**（共 188）。相比本报告上文「148/188」，差额是陶瓦 11 个方法（`terracotta.c`，22:44 落地）已原生化但当时未记入。
- 构建（`native\build.bat` 与 `build.bat nopy`）：成功。产物 `pymcl-bridge.exe` 1,054,612 B、`pymcl-bridge-nopy.exe` 1,049,316 B（预算 1.6 MB 内）。`-Wall` 下有 3 条既有警告待清（`server.c:6` pragma comment、`server.c:347` strncpy 截断、另 1 处 `%lu` 格式），GOAL 4.F 要求新代码 0 警告。
- 对拍（`python _c_py_parity.py`）：用例 206 个（新增 24 个陶瓦用例）通过 198，方法 110 通过 107。失败集中在 3 个陶瓦方法（`terracotta_host`、`terracotta_direct_connect`、`terracotta_snapshot`）：**Python 参考桥在本机起不来陶瓦内核，全部以 `TimeoutError: timed out` 收场**，属环境性超时而非文案差异，C 端返回的是正常业务错误。与 `list_loader_versions(neoforge)` 同类，需要 stub / 录制回放才能对齐，M4 验收（B/C）未完成。
- 动态探测 110 ok / 12 native_error（均为故意的非法参数业务报错，正常）/ 10 not_native / 56 skipped（会动本机的 unsafe 方法只做静态判定）。
- M5 现状：`ai_store.c` 620 行（对话存储、权限规则、`test_ai_connection` 已对拍通过），`ai_agent.c` 仅 13 行 stub，agent 循环 / 36 工具 / 确认卡 / 检查点未开始。
- 接手基线：工作区含大量未提交改动（11 个修改 + 13 个新文件），是上一个会话 M4/M5 进行中的工作，本会话继续。

## M1 续：启动命令两个方法原生化（2026-09-26 00:15）

### 实现

- `build_launch_command`、`get_launch_command` 落地 C（`rpc_extra.c` 分发 + `launcher.c` 构建器扩展 + `rpc_versions.c` 隔离助手公开 + `rpc_content.c` 全局模组 apply + `auth.c` 账号/props 补齐）：
  - 构建器新增 `build_launch_command_ex`：`${game_directory}` 覆盖、`CONFIG default_jvm_args` 与 `extra_jvm_args` 前置、内存旗标二次应用、authlib / nide8 `-javaagent` 注入（含 `normalize_api` / `normalize_server_id` 移植）、游戏附加参数尾部追加，语义逐条对齐 `mclauncher/launcher.py`；
  - `get_launch_command` 完整移植 `launch_flow.prepare`：隔离档位联接、全局模组链接进游戏 mods、服务器直连参数、全屏档位、GC 预设 JVM 参数、版本设置内存优先级；
  - `account_offline_skin`：补 `offline_skin` 配置与 steve / alex 固定 UUID（同 `auth.py offline_account`）；`launch_props` 补 authlib / nide8 / 离线 skin_file 分支；`add_offline_account` 改走带皮肤的构造（此前无 skin 键、无固定 UUID）。
- 对拍：新增 7 个用例全部通过；`_c_py_parity.py` 全量 **213 用例 198 通过，方法 108/112**。
- 覆盖率：**原生 161 / 显式 14 / 隐式 13**（M0 基线 55/37/96）。`pymcl-bridge.exe` 1,067,955 B（预算内），新增代码 `-Wall` 0 警告。
- WPF（修复计入 §2.2 前端修复清单）：`LaunchPage.ShowLaunchCommandAsync` 原按 `string` 反序列化 `build_launch_command` 的数组返回，永远拿到 null 弹空命令；改按 `List<string>` 取值后拼接（`dotnet build` 0 警 0 错）。

### 顺手修掉的两处基建偏差

1. **启动器版本常量**：C 的 `-Dminecraft.launcher.version=1.0.0` 与 Python `LAUNCHER_VERSION=1.0.1` 不一致（影响全部启动命令对拍），已对齐。
2. **根目录短路径**：`TMP` 是 8.3 短路径（`ADMINI~1`）时 C 桥拼出的绝对路径与 Python `Path.resolve()` 展开后的长路径对不上；`pymcl_set_root` 补 `GetLongPathNameW`。

### 对拍用例表的一个结构性问题（记录）

陶瓦用例会以长超时卡住 Python 参考桥（等待陶瓦内核），排在其后的所有用例跟着 60s 超时误报。已把 24 个陶瓦用例移到用例表末尾隔离影响。剩余 15 个失败全部是陶瓦：Python 侧 `TimeoutError: timed out`（环境起不来内核），C 端返回正常业务错误——与 neoforge 用例同类，待 M4 的 stub / 录制回放就位后对齐，M4 验收（B/C）未完成。
