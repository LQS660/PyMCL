> 2026-09-30 文档核对轮（分支 `fix-8items` @ `8c3aea7`，工作区 98 项未提交）：本轮不改代码，只把文档拉回与代码一致。**实跑基线 769 passed / 10 skipped / 0 failed**（`python -m pytest tests -q --timeout=300`，77.9s；用例总数 779 收集）。**重写** `android/ANDROID.md`——原文停在 `0.1.0-skeleton`「不能启动游戏」，实际代码已是 `0.2.0-runtime`（`versionCode 2`），有完整 FCLBridge JNI 启动链、83 个 data 模块、29 个 Compose 页面、843 个 JVM 单测；同时补记三项真实缺口：**零文字输入/虚拟键盘**（`pushEventChar`/`InputConnection`/`ImeBridge` 全工程命中 0）、**AI 工具 19 vs 桌面 36**（`scripts/check_tool_parity.py` 实测）、**i18n 词表 1037 vs 桌面 2161**。**修正** `对接说明.md`（原文称 `*_impl` 均为「内存模拟」，实际 1.9 万行真实实现；删除 `instance_page.py`/`modpack_page.py`/`content_page.py`/`run.bat` 等已不存在的文件引用，设置键表按 `config.py` 重校）、`新手教程.md`（文件清单里的 `gui.py` 不存在，改为 `app/`）、`README.md`（Android 条目按实际状态改写）。**未执行**：Android 端未重新编译（无 FoldCraftLauncher 并排源码时配置不起来）；GUI 未做真机/真窗口实拍，仅离屏构造 `MainWindow()` 成功；C 桥未跑完整 RPC 会话。

> 2026-09-23 agent 修复轮（分支 `fix-8items`）：三路并行审查（内核/Qt/WPF+bridge）确认 2 P0 + 6 P1 + ~20 P2/P3 并全部修复。**P0×2**：①checkpoint 目录快照在 MAX_DIR_FILES=20000 截断后仍当完整 known 集合回滚清扫——超 2 万文件实例回滚会把老文件当「新增」整批误删（现截断即整轮拒快照）；②WPF AiPage 构造把 `_usageLabel` 加进两个容器，AI 页构造即抛异常打不开（上轮 WPF 冒烟未复跑漏网）。**P1×6**：幽灵目录（快照时不存在、回滚 unlink 目录静默失败谎报已还原→改 rmtree 整树删+失败计数）；回滚失败操作连同 blob 被清（不可重试→失败 op 留 journal，恢复幂等可重试）；子代理被 MCP 打穿（mcp_schemas 无条件追加+confirm_fn None 把 ASK 当 ALLOW→子代理不连 MCP、无确认通道即拒绝）；hooks 改写入参绕过判权/快照（run_before 提前到 decide 之前）；MCP readline 无超时挂死整回合（看门狗 deadline 杀进程）；WPF ui_changed 刷新清掉进行中回合 + 迟到 ai.done/ai.fail 杀新回合状态（busy 时不重画消息区+chat_id 守卫）。**P2/P3 要点**：rewind 会话日志缺失时不再硬回滚 journal 旧轮（误删未要求撤销的改动）；client.py 工具轮 usage 先于 tool_calls 产出（此前凡调工具必落估算）；压缩后 token 基线重置（防连环误触发 compact）；MCP 最长前缀路由（`a`/`a_b` 串号）+ env 透传 + server 名字符校验；write_mod_config path 带盘符/NTFS 流拒绝（防检查点越界复制任意文件）；write_mod_config content 不再被 strip；审计钩子按 side_effect 判（launch_game 入审计）；usage 每 step 只记一次估算（重试不虚增）；Qt：rewind 三态反馈补全、用量标签随会话刷新、计划卡 wrapper 残留、_send 重入守卫（定时器续发与手速发送撞车）、_STOP 运行期求值（切语言后停止不再误判为错误）；WPF：checkpoint_warn/model_fallback 告警 toast、计划卡持久化恢复（AiPlanDto）、pending_card 断线补画、rewind ok=false 不再谎报已撤回、BridgeClient 字符串型 error 解析崩溃、think after_tools 文案、AbandonRun 静默复位、用量混合来源标注估算；bridge ai.delta/ai.status 补带 chat_id；permission 规则行 behavior_label/scope 走 tr()。回归 `tests/test_ai_fixround_20260923.py` 17 例（含真 ai_chats.json 写穿事故的隔离修复：STORE_FILE 未隔离致 test_root_checks 子进程探针连锁红）。en.json +31 / zh_CN +4 词条。基线 **612 passed / 1 skipped / 0 failed**（+17，offscreen 36.2s）；check_qt_parent 253 构造点 OK；WPF 构建 0 警 0 错。**未执行**：WPF `--smoke` 复跑、确认卡 diff 双端截图证据（本轮改动均有单测/构建覆盖但未做 UI 实拍）；MCP 看门狗只做了代码路径验证、未起真挂死 server 实测。

> 2026-09-22 UI 缺陷修复（分支 `fix-8items`）：按《PyMCL-UI缺陷猎捕清单与提示词.md》复核 `docs/audit/ui-audit-findings-2026-09-19.md` 全部 19 条疑点并出账本 `docs/audit/ui-bugs-2026-09-22.md`（P0:1·P1:1·P2:7·P3:8；P0/P1/P2 关闭率 100%）。上条记录的「并行 agent 留下 13 项未提交改动」已按主题拆 8 个 commit 入库（motion 闭包摘表、launch preflight 异步化、pick_color crc32、tr() 默认参数哨兵、任务取消诚实性/删除确认/版本竞态三组回归）；本轮新修：servers_page 4 处 + settings_page 主目录标签裸中文补 tr()（en.json +5 词条）、冻结 exe 重启 argv 去重，新增页面级 i18n 门禁 `tests/test_ui_text_wrapped.py`（HEAD 旧码 4 处红→修复 0 绿）。复核后修正 3 条旧结论：ai_session_id「共享缓存污染」不成立（get_settings 每次新建 dict）、download_threads 吞 0 属良性（UI 下限 1 + 下载器 max(1,·) 双钳制）、模块级 tr() 属受控设计（init_language 先于 app.* import + 切语言提示重启）。基线 **595 passed / 1 skipped / 0 failed**（+3 用例，offscreen 33.9s）；check_qt_parent 252 构造点 OK 白名单未增。**未执行**：主题矩阵/可访问性遍历/首帧耗时表/WPF 冒烟复跑（清单见账本「待观测与未执行」）；en.json 尚有 93 条历史缺口（翻译债，需裁决）。

> 2026-09-21 改造收官（分支 `fix-8items` @ `3206a5f`）：按《PyMCL-agent-改造清单与提示词.md》完成阶段 0–7 共 24 个 commit。脏工作区 21 项已按主题拆 8 个 commit；审计报告 `docs/audit/agent-gap-20260921.md`（A:11·B:15·C:6·D:14）；改造后基线 **592 passed / 1 skipped / 0 failed**（+101 用例）；WPF 构建 0 警 0 错；check_qt_parent 251 构造点 OK；评测集 12/12 PASS。落地：文件检查点+字节级回滚+rewind 方案甲、确认卡变更预览（Qt/WPF 同源）、上下文窗口可配置（128k 保守默认）、工具按需声明（-56%）、真实 usage 采集与模型降级、hooks/MCP/子代理/计划/记忆五件扩展、内置令牌移除+来源标注+网关 TLS/可插拔鉴权计量、参数校验+错误码、跨端差集进 CI、用量展示+turn_summary+本地聚合。全程详情见 `docs/agent-upgrade-report-20260921.md`。**注意**：改造期间另有并行 agent 在本工作区留下 13 项未提交改动（app 页面与 7 个新测试），本改造未触碰；桌面发行包当前不存在（见审计 D6）。

> 2026-09-19 续验（分支 `fix-8items` @ `60cc011` + 工作区未提交改动）：`python -m pytest -q` 476 passed / 1 skipped（此前红灯 `test_bridge_i18n` 缺 4 词条、`test_bridge_parity` 的 `note` 键、`test_wpf_i18n` 缺 27 条权限文案均已修）；`dotnet build -c Release` 0 警告 0 错误。AI 权限 UI 已 Qt / WPF 对齐（五档模式、自定义规则表、允许 / 始终允许 / 拒绝 + 实例 / 全局范围，删除类工具不给「始终允许」）；Qt 对话切换回归 `tests/test_ai_chat_switch.py` 已补；Qt 确认 / 提问等待可取消、关窗主动停 AI 回合。两份发行包已更新到桌面：`Desktop\PyMCL-Qt\PyMCL.exe`（PyInstaller onefile，离屏沙盒起跑 15 s 无报错）与 `Desktop\PyMCL-WPF\`（`dotnet publish -c Release -r win-x64` 依赖框架 + Python 桥；`--i18n-check / --consent-check / --ime-check` 退码 0，`--smoke` 退码 0：44 次点击 / 24 个对话框 / 0 问题）。**仍未做**：这批改动（24 个文件 +1642/−247，含 5 个未跟踪文件）尚未按主题拆分提交；`wpf32/` 内部 `Services/Motion.cs` 的同款修复未提交；NAS MP4 插件只做了只读核验（服务 active、两个群与 100 MB 上限已加载、sqlite-web 已停），真实群视频触发转码仍无日志证据。
>
> 2026-09-17 接手续验：Android JVM 653 测试通过，但标准 Gradle 仍阻塞于 AAPT2；WPF 构建通过，严格静默冒烟覆盖达标但有在线目录加载超时。详见 `docs/audit/continuation-2026-09-17.md`。下面历史快照不能替代本次证据。

# PyMCL 构建状态与审计归档

> 快照时间：2026-09-10 · 分支 `claude` · 基线 `4146a5a`
>
> ⚠️ **本节（§1–§4）是 2026-09-10 的历史快照，已不代表当前状态。** 分支已从
> `claude` 切到 `fix-8items`，测试数从 433 涨到 769，WPF 已迁出本仓，`wt-*`
> 工作树已不在。要当前状态请看文首那条 2026-09-30 记录。保留本节是为了留存
> 当时可复现的命令与工具链版本。

## 1. 验证结果（历史快照 2026-09-10）

下表每一行都是本机实跑出来的，命令原样可复制。

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 测试 | `python -m pytest tests/ -q` | 433 passed + 90 subtests，1 skipped（慢门禁，`PYMCL_SLOW_CHECKS=1` 才跑），2 失败（`test_root_checks[_bg_visual.py]` 与 `test_wpf_i18n`，均为工作区他人未提交 WIP 自带的探针/文案，与 AI 改造无关；排除后 AI 相关用例 0 失败）（2026-09-18 AI 改造六批次后复跑，分支 `fix-8items`；慢门禁全量 434 passed） |
| 自检脚本 | `python selftest.py` | 全 OK（Mojang 清单 912 个版本，Modrinth API 可用） |
| eziapp 类型检查 | `cd eziapp && npx tsc --noEmit` | exit 0，零错误 |
| WPF | `cd wpf && dotnet build PyMCL.Wpf.sln` | 0 错误 0 警告（**已失效**：`wpf/` 于 2026-09-29 迁出本仓，见 §5） |
| WinUI 3 | `cd winui3 && dotnet build PyMCL.WinUI.sln` | 0 错误 0 警告（路径有效，未复验） |
| C 桥 | `native\build.bat` | 编译通过，10 条 warning，产物 `native/build/pymcl-bridge.exe` 0.67 MB（未复验） |

工具链版本：Python 3.12.10 / pytest 9.1.1 · Node v22.23.2 · .NET SDK 9.0.317（WinUI 工程 target `net8.0-windows10.0.19041.0`）· gcc 16.1.0（MSYS2 mingw64）。

**未验证**：GUI 实际运行（`python main.py` 需要长驻进程）、`android/` 未编译、C 桥只做了「无参数应退出并打印用法」的冒烟，没跑过完整 RPC 会话。

## 2. `docs/audit/` 里那四份报告怎么用

它们由并行分支上的 agent 在 2026-09-07 22:48–22:58 生成，原文件名是 `_inv_*.md` / `_audit.md`，散落在 `wt-opus45` 和 `wt-sonnet45` 两个工作树里且从未提交。这里收进仓库是为了防止 `git clean` 把它们抹掉。

| 文件 | 原名 | 内容 |
|---|---|---|
| `qt-ui-inventory-part1.md` | `_inv_82185126.md` | Qt 版行为规格：主窗、侧栏、自由布局画布、启动页、版本页、安装向导 |
| `qt-ui-inventory-part2.md` | `_inv_part2.md` | Qt 版行为规格：账号、联机、服务器、时长、反馈、设置、AI、任务、崩溃弹窗、动画、i18n |
| `bridge-protocol-and-gap.md` | `_inv_bridge.md` | JSON-RPC + SSE 协议参考，以及 bridge 与 `app/backend.py` 的逐方法差异 |
| `feature-parity-matrix.md` | `_audit.md` | 三方对等矩阵（Qt / eziapp / WPF）+ P0/P1/P2 优先级清单 |

**准确度**：抽查了 8 条可验证断言（方法计数 169/165、缺失方法集合、`MAX_REQUEST_BYTES`、SSE 队列 `maxsize=800`、keepalive 超时、`_TOP_KEYS` 字面量、`ai/tools.py` 三处调用的行号、基线缺 `ui_changed`），全部命中，行号也对。

**但两章已经过期**：

- `bridge-protocol-and-gap.md` §2c 的 11 条 bug —— 写完之后被同一批 agent 修掉了，其中的行号引用现在指向无关代码；
- `feature-parity-matrix.md` §E 的 P0 —— eziapp 编译不过、WPF 跑不起来这两条在 `claude` 上已全部修复（见上表）。审计原文描述的状态在 `wt-sonnet45` 上仍可复现（`tsc` 报 15 个 TS2307，`dotnet build` 报 2 个 CS0234）。

仍然有效的是各报告的**规格/协议部分**（Qt 行为清单、RPC 协议参考）和 §E 的 **P1/P2**。

⚠️ **但这条结论已过期**：原文称「启动页自由布局画布、侧栏自定义 —— 两套新前端都还没做」。
2026-09-30 核对时，WPF 前端已有 `Pages/Dashboard.cs` 自由画布与完整的 `ui_nav_*` 侧栏编排
（`Shell/NavModel.cs`），三端（Qt / WPF / eziapp）在这些键上是对齐的。仅 **WinUI3** 仍是
11 项静态侧栏、无自由画布。审计原文描述的缺口现在只适用于 WinUI3。

## 3. 分支现状（历史快照 2026-09-10，已失效）

> 下表描述的是 09-10 的工作树布局。当前实际只有 `fix-8items` 一个工作树
> （`git worktree list` 仅 `PyMCL-main/` 一条），`wt-*` 目录仍留在外层磁盘上但
> 已不是 git 工作树。分支 `claude` 已不存在于本仓，现为 `main` / `fix-8items`。

| 分支 | 工作树 | 说明 |
|---|---|---|
| `claude` | `PyMCL-main/` | 主线。本次把 91 项未提交改动整理成 7 个 commit |
| `claude-opus-4.5` | `wt-opus45/` | 未提交：`bridge/api.py` +1046 行的独立改法 |
| `claude-sonnet-4.5` | `wt-sonnet45/` | 有一个 commit `1368681`；工作区的 eziapp 重写处于半路，编译不过 |
| `kimi` | — | 停在基线 |

三条线都独立改过 `bridge/api.py`，合并前需要三方对比。

## 4. 刻意留在版本控制之外

- `.minecraft/` —— PYMCL_HOME 落在仓库根时生成的游戏目录，已加进 `.gitignore`
  （历史快照里写作 `default/`；当前实测该目录只剩空骨架，`versions/` 里没有任何已装版本）
- `wpf-ui.json` —— WPF 前端的本地 UI 状态，同上
- `_rpc_crosscheck.py` —— 一次性探针

## 5. WPF 前端已独立成仓（2026-09-29）

`wpf/` 目录连同 21 笔历史迁出本仓，独立为 [LQS660/PyMCL.Wpf](https://github.com/LQS660/PyMCL.Wpf)
（历史用 `git subtree split` 抽取，树哈希与迁出前一致）。本仓不再包含 WPF 源码。

- 两个仓建议并排克隆（`PyMCL-main/` 与 `PyMCL.Wpf/`），`tests/_wpf_repo.py` 与
  `_pack_common.wpf_src()` 会自动找到同级那份；也可以用 `PYMCL_WPF_SRC` 显式指定。
- 找不到 WPF 源码时，跨端一致性测试（i18n 词表 / 反馈页文案 / 侧栏键表）整组跳过，
  而不是报 FileNotFoundError。
- 原先 `wpf32/` 那个悬空 gitlink 一并移除：它只记了一个本地 commit，从未有 remote。
