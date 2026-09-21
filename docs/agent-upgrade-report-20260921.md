# PyMCL AI Agent 改造报告 · 2026-09-21

> 执行依据：`PyMCL-agent-改造清单与提示词.md`（阶段 0–7 全部执行）。
> 分支 `fix-8items`，本次改造共 **24 个 commit**（阶段 0 的 8 个整理提交 + 16 个批次提交）。
> 全部数字均为本次实测，命令可复制复跑。

## 一、基线与门禁

| 门禁 | 通过判据 | 实测 |
|---|---|---|
| Gate 0 | 工作区干净 + failed==0 | `git status` 0 项；pytest **491 passed / 1 skipped**（基线） |
| Gate 1 | 审计报告存在、可机器核对、无禁词 | `docs/audit/agent-gap-20260921.md`；grep 行号 34（≈A/B/C 表 32 行）；「待确认/疑似」0 |
| Gate 2 | 回滚演示 sha256 一致 | 3 轮写操作回滚后清单 diff 无差异、非目标文件未动（`_stage2_rollback_demo.py` 实测输出留档） |
| Gate 3 | schema 降幅 ≥40% + 10 prompt 全对 | 全量 2769 tokens → 平均 1216（**降 56%**），10/10 场景选对；`_stage3_tool_tokens.py` 可复跑 |
| Gate 4 | 子代理常量引用 / MCP 隔离 / plan 拒绝零写 / 记忆一致性 | 全部落进 `tests/test_ai_subagent.py`、`test_ai_mcp.py`、`test_ai_plan_memory.py` 并通过 |
| Gate 5 | 令牌扫描命中 0 / 注入标注 / 可插拔鉴权 | mclauncher 源码面 85 文件 sk- 命中 **0**；tests/test_ai_security.py 13 用例 |
| Gate 6 | 5 组坏参数回执 / 原始异常串移除 / 跨端脚本 | 桌面 **36** / Android **19** 差集进 CI（scripts/check_tool_parity.py） |
| Gate 7（总） | pytest + qt_parent + WPF 构建 + 评测 | **592 passed / 1 skipped / 0 failed**；qt_parent 251 构造点 OK；WPF 0 警告 0 错误；评测 **12/12 PASS, failed==0** |

终态基线：**592 passed / 1 skipped / 0 failed**（较改造前基线 +101 用例；skip 仍只有需 `PYMCL_SLOW_CHECKS=1` 的慢速布局检查）。

## 二、批次落地对照（DoD）

- **D1 变更可逆**：`checkpoint.py`（文件级/目录级快照、sha256 内容寻址、字节级回滚、三级占用上限、失败降级不阻断）；确认卡 unified diff / 文件数字节 / 目标路径（Qt/WPF 同源 `preview.py`）；rewind 选**方案甲**（真回滚磁盘 + 对话截断，理由：1.1 已建检查点设施、用户预期即恢复原状；方案乙被否因为只改文案仍留磁盘风险），Qt 与桥 `ai_rewind` 共用 `rewind.py`。
- **D2 上下文成本**：窗口可配置（Qt/WPF 设置页 + 两端后端白名单，8192–2M 夹取）；默认 200k→128k 保守值，`tokens.py` 的「未实测」换成【待实测】+ 三步实测法；工具按需声明（核心常驻 + 关键词组 + artifact 跟随，漏选全量重发兜底）；真实 usage 记 trace + 事件日志，公益网关标「估算」；主模型连续 429/5xx 自动切 `ai_fallback_model`（可见提示；未配置则行为与改造前一致——有回归断言）。
- **D3 可扩展**：hooks（前置/后置、入参/结果改写、异常不中断、总闸关闭行为逐字一致、内置写审计钩子）；MCP 客户端（stdio JSON-RPC 手写实现不引 SDK，坏 server 隔离有真实崩溃夹具证据）；子代理（`MAX_TOOL_ROUNDS_SUBAGENT` 首次被实际引用、只读限制、上下文隔离、结构化失败）；计划工作流（update_plan 工具 + plan 档批准门禁 + 拒绝零写操作证明 + 会话持久化 + rewind 清计划）；记忆接口（NoopMemory 默认空实现，启用与否 messages 逐字一致）。
- **D4 安全**：内置令牌移除（占位不可用、诱饵 sk- 串删除、源码面扫描 0）；未配网关可读报错不静默；工具回执来源标注（网络/MCP→不可信，本地文件/日志/写操作分类）+ 系统提示词防注入硬规矩；网关 TLS/反代启动门禁 + 可插拔鉴权（默认向后兼容）+ 可插拔计量（默认写本地 usage.jsonl，含每请求 token）；顺手修审计 B4（temperature 非数字裸抛）。
- **D5 工程质量**：参数校验（5 组坏参数逐组回执、含字段名；模型自纠有对话证明）；错误面（ToolErrorCode 枚举 + 可读文案 + 堆栈只进 trace）；跨端门禁脚本进 CI（只报告不挡门）。
- **D6 可观测**：AI 页会话累计 token（输入/输出分开 + 估算标注，Qt/WPF 同源）；设置页用量明细（最近 30 条真实 usage）；turn_summary 埋点（停止原因/轮数/工具数/失败数/耗时）+ `scripts/usage_summary.py` 本地聚合；12 场景离线评测集。
- **D7 审计**：`docs/audit/agent-gap-20260921.md`（A:11 · B:15 · C:6 · D:14，无「无法判定」）。

## 三、依赖与打包

本轮**未引入任何新依赖**（hooks/MCP/子代理/计划/用量全部标准库实现；MCP 明确不引 SDK，理由见模块 docstring）→ `requirements.txt` 无变更、`PyMCL.spec` 无变更、无需重打包。回滚方式：逐 commit revert（见下一节）。

## 四、commit 清单与回滚顺序

回滚 = 按下表**从下往上**逐个 `git revert <hash>`（后提交者先回滚）：

| 主题 | commit |
|---|---|
| 阶段 0 整理（i18n/并发/权限/加固/内核/agent/桥/WPF 八笔） | d37adcb…eb83cd3 |
| 审计报告 | 9a25db8 |
| 1.1/1.2/1.3 可逆性 | 09a7edf → 1cd882a → 32685df |
| 2.1/2.3/2.4 + 2.2 | 6e9d370 → 34ee7ae |
| 3.1–3.5 | 52db6cd → 54b82e9 → d318716 → e59587c |
| 4.1–4.3 | 3982e23 → f955ea5 → 243f54e |
| 5.1/5.2 + 5.3 | 9a04ef9 → f60b17a |
| 6.1–6.3 | 3206a5f |

## 五、测试契约变更清单（未放宽任何断言）

| 文件 | 原断言 → 新断言 | 契约变化原因 |
|---|---|---|
| tests/test_bridge_parity.py | `_payload_keys` 只认字面量 dict → 解析变量赋值；CONFIRM_KEYS +chat_id,+preview；DONE_KEYS +plan,+usage | 桥 payload 变量化（断线对账复用）与功能键新增，为真实契约演进 |
| tests/test_ai_compact.py | 阈值 187000 → 118072；工具数 34→36 | 200k 抄来常量换 128k 保守默认；新增 dispatch_subagent/update_plan |
| tests/test_ai_stop_reason.py | `startswith("工具失败")` → 结构化 `error_code` | 批次 5.2 错误面规范化 |
| tests/test_ai_agent_state.py | _run 增 select_tool_schemas 全量打桩 | 2.2 按需声明下打桩调用可能不在核心集 |
| tests/test_ai_subagent.py / test_ai_mcp.py | 回执解析剥来源前缀 | 4.2 来源标注进回执 |

## 六、未完成 / 待实测（诚实清单）

1. **上下文窗口实测未做**：deepseek-v4-flash 真实窗口需真实网关流量，本机未跑；已按 128k 保守取值 + 【待实测】标记 + 三步实测法写入 `tokens.py`。设置页可改。
2. **打包产物级令牌扫描**：本机无 dist/ 产物且本轮未改 spec/依赖，按约束不强制重打包；已做 mclauncher 源码面 85 文件扫描命中 0。下次打包后请复跑 `strings dist/PyMCL.exe | grep -c "sk-"`。
3. **注入防护行为级验证**：4.2 的离线回归验证了标注与规则就位；「模型不执行注入指令」的端到端行为验证归入评测集后续（需打桩模型按注入剧本响应的扩展场景）。
4. **prompt caching 命中率**：观测方法（cached_tokens/prompt_tokens，Usage 事件已带缓存命中字段）已落地，数值需真实流量。
5. **B5（SSE 截断标 done）/ B2/B3（安装与钩子超时）/ B6/B7** 等审计缺陷不在本轮批次范围内，已在 `docs/audit/agent-gap-20260921.md` 挂账。
6. **Android 对齐**：A6/A7/A8 + 差集清单由 CI 每次输出，本轮范围外未动。

## 七、意外改动说明（应为空，实际 13 项，均非本改造所为）

改造期间有**另一并行 agent 在同一工作区工作**，其未提交改动（app/main_window.py、app/motion.py、app/pages/launch_page.py、app/pages/multiplayer_page.py、app/widgets.py、tests/test_ai_chat_switch.py 及 7 个新测试文件）与本次改造无关，本改造**未触碰、未提交、未回滚**这些文件；每次全量测试均在含其改动的状态下实跑且全绿。本改造的提交均逐文件 `git add`，与其改动零混入。
