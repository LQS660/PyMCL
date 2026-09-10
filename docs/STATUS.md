# PyMCL 构建状态与审计归档

> 快照时间：2026-09-10 · 分支 `claude` · 基线 `4146a5a`

## 1. 验证结果

下表每一行都是本机实跑出来的，命令原样可复制。

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 测试 | `python -m pytest tests/ -q` | 65 passed + 10 subtests，0 失败 |
| 自检脚本 | `python selftest.py` | 全 OK（Mojang 清单 912 个版本，Modrinth API 可用） |
| eziapp 类型检查 | `cd eziapp && npx tsc --noEmit` | exit 0，零错误 |
| WPF | `cd wpf && dotnet build PyMCL.Wpf.sln` | 0 错误 0 警告 |
| WinUI 3 | `cd winui3 && dotnet build PyMCL.WinUI.sln` | 0 错误 0 警告 |
| C 桥 | `native\build.bat` | 编译通过，10 条 warning，产物 `native/build/pymcl-bridge.exe` 0.67 MB |

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

仍然有效的是各报告的**规格/协议部分**（Qt 行为清单、RPC 协议参考）和 §E 的 **P1/P2**，尤其是两条最大功能鸿沟：启动页自由布局画布、侧栏自定义 —— 两套新前端都还没做。

## 3. 分支现状

| 分支 | 工作树 | 说明 |
|---|---|---|
| `claude` | `PyMCL-main/` | 主线。本次把 91 项未提交改动整理成 7 个 commit |
| `claude-opus-4.5` | `wt-opus45/` | 未提交：`bridge/api.py` +1046 行的独立改法 |
| `claude-sonnet-4.5` | `wt-sonnet45/` | 有一个 commit `1368681`；工作区的 eziapp 重写处于半路，编译不过 |
| `kimi` | — | 停在基线 |

三条线都独立改过 `bridge/api.py`，合并前需要三方对比。

## 4. 刻意留在版本控制之外

- `default/` —— PYMCL_HOME 落在仓库根时生成的 `.minecraft`，5150 个文件 582 MB，已加进 `.gitignore`
- `wpf-ui.json` —— WPF 前端的本地 UI 状态，同上
- `wpf32/` —— 与 `wpf/` 同为 31 个源文件但早一天的副本，另含 1.6 MB 的 `bin/obj` 和一批截图。**未提交也未忽略**，留在 `git status` 里等人决定
- `_rpc_crosscheck.py` —— 同上，一次性探针
