# AI 行为契约补充：给 C 桥 M5 移植对照

> 2026-09-25，来自提交 `cb35b73`（WPF AI 对齐 Qt）与 `c79947c`（插话入库），分支 `fix-8items`。
> 行为以 Python 参考实现为准（`bridge/api.py`、`mclauncher/ai/`），见 [GOAL-c-bridge-no-python.md](GOAL-c-bridge-no-python.md)。
> 本文只列这两次提交**新增或改变**的契约；C 桥实现 M5 时必须与之一致。

## 0. 速查

| 项 | C 桥要实现 | 所在位置（Python） |
|---|---|---|
| `ai.confirm` 带 `allow_always` | 是 | `bridge/api.py` `_ai_run` 里的 `confirm_fn` |
| `ai.done` / `ai.fail` 带 `unsent` | 是 | `bridge/api.py` `_ai_run` 的 `release()` / `fail()` |
| 每回合只放一次 busy，锁内交还插话 | 是 | 同上 |
| 读到的插话带 `steer_` id 导出、按原位置入库 | 是（内核 + 存储） | `mclauncher/ai/agent.py`、`bridge/api.py` `_turn_compact_and_trajectory` |
| 撤回跳过插话 | 是 | `mclauncher/ai/rewind.py` |
| 续发 `unsent`、后台任务回报、重试跳过插话 | 否（前端逻辑），但 C 桥要给出所需字段与事件 | `wpf/PyMCL.Wpf/Pages/AiPage.cs`、`AiFixWindow.cs` |

## 1. 事件字段

与 `tests/test_bridge_parity.py::BridgeAiPayloadParityTests` 钉死的键集合一致：

- `ai.done`：`text`、`store`、`stop_reason`、`detail`、`pending_tasks`、`note`、`plan`、`usage`、`chat_id`、`unsent`
- `ai.fail`：`text`、`stopped`、`chat_id`、`unsent`
- `ai.confirm`：`name`、`args`、`label`、`reason`、`rule_content`、`preview`、`allow_always`、`chat_id`

`ai_pending_card` 以及 `ai_list_chats` 的 `pending_card` 是 `{kind: "confirm", …ai.confirm 同一份字段}`，所以断线补画的卡片也带 `allow_always`。

## 2. 「始终允许」判据：`allow_always`

- 规则：`allow_always = 工具在 TOOL_META 里 且 side_effect != "delete"`。
- 当前结果：`delete_instance`、`delete_mod` → `false`；`plan_approval`（计划审批，不在 `TOOL_META`）→ `false`；其余需要确认的写工具（如 `install_mod`）→ `true`。
- 原因：删除类工具的参数键不在 `RULE_CONTENT_KEYS` 里，记一次规则就等于整个工具放行；计划审批是一次性的，内核收到 `Rule` 也只当作一次批准（`agent.py` 的 plan_approval 分支把 `Rule` 转成 `True`，不落盘）。
- 前端：WPF 用 `ConfirmCard.AllowAlways(ev)` 读这一位决定显隐；字段缺失（旧版桥）时按名字兜底。

## 3. 插话（steering）全链路

### 3.1 RPC

- `ai_send(text, chat_id, launch, context)`：在 `_ai_lock` 里检查并置位：`busy=true`、`cancel=false`、清空插话队列。
- `ai_steer(text)`：
  - 文本为空 → `{ok: false, message: "内容为空"}`（按界面语言翻译）；
  - 没有回合在跑 → `{ok: false, message: "当前没有在跑的回合"}`；
  - 否则在 `_ai_lock` 里追加进队列 → `{ok: true, queued: <队列长度>}`。

### 3.2 内核取插话

- 每一轮开头、调模型之前调用 `drain_inputs_fn`：在 `_ai_lock` 里取走队列全部内容并清空。
- 每条非空插话作为 `{"role": "user", "content": text}` 追加进本回合的 messages，并发 status `steer`（`text` 截到 200 字）。
- **发给模型的这条消息不带 `id`**：请求内容与改动前完全一样。

### 3.3 收尾交还：`unsent`

内核只在每轮开头取插话，最后一轮开始之后才到的插话它读不到。收尾时：

1. 清掉本回合的 HTTP 取消句柄；
2. 进 `_ai_lock`：`busy=false`，把队列里剩下的话挪进本回合的 `unsent`，清空队列；
3. 出锁后发 `ai.done` 或 `ai.fail`，都带 `unsent`（成功、失败、用户停止都一样）。

`ai_steer` 检查 busy 与收尾放 busy 用的是同一把锁，所以每句插话只有两种结局：收尾之前入队的，一定进 `unsent`；收尾之后才到的，`ai_steer` 回 `ok=false`。不存在「入了队却没人处理」的窗口。

**每回合只放一次 busy**：成功路径、`fail()`、`finally` 都会调用收尾，只有第一次生效。前端收到 `ai.done` 往往立刻开下一回合；如果旧回合在 `finally` 里再放一次，会把新回合的 busy 和它刚收到的插话一起清掉。

### 3.4 前端怎么用（参考，C 桥不用实现）

- WPF 运行中发话走 `ai_steer`；桥回 `ok=false` 时，先等旧回合的 `ai.done` 把界面复位（最多 3 秒）再 `ai_send`，避免迟到的收尾事件把新回合的状态复位。
- 收到非空 `unsent`：用空行拼成一句，当下一回合发出，不再贴用户气泡（插话时已经贴过）。事件属于别的对话、或回合是因切换对话被掐掉的，不续发。

## 4. 插话入库

### 4.1 内核导出 `turn_messages`

- 内核记下本回合读到的每条插话（按对象身份认，不靠内容比较）。
- 导出时给插话的**副本**补上 `id = "steer_<turn.id>_<序号>"`，序号是本回合第几条插话（从 0 起）。
- 没压缩过：`turn_messages` 是本回合新增的全部消息（不含 system），按原顺序，插话就在它被读到的位置——总是在上一轮全部工具结果之后、下一轮模型回复之前，不会插进 `assistant.tool_calls` 和它的 tool 结果之间。
- 压缩过：`turn_messages` = `[用户这句]` + 压缩摘要 + 仍留在 messages 里的插话（已被压进摘要的不再单独导出）。

### 4.2 存储

- `mclauncher/ai/store.py`：`STEER_ID_PREFIX = "steer_"`；`is_steer_message(m)` = `role == "user"` 且 `id` 以 `steer_` 开头。
- 桥的入库顺序：压缩摘要（`id=compact_*`）→ 用户这句 → 本回合轨迹（`assistant.tool_calls`、`tool`、插话，按 `turn_messages` 原顺序）→ 最终 assistant（「为什么停」放在单独的 `note` 字段）。
- 存储保留 `id` 字段；`api_messages` 转成请求时 user 消息只带 `role` / `content`，所以下一回合模型看到的是普通用户消息。
- 重开程序后，插话渲染成普通用户气泡（只有 `compact_*` 会渲染成「较早的对话已压缩成摘要」）。

### 4.3 撤回与重试

- `rewind_last_round`：从后往前找第一条 `role == "user"` 且**不是插话**的消息，当作最近一回合的开头，截到它之前。插话随整个回合一起撤掉。
- 重试（前端逻辑，Qt `_retry`、WPF `LastUserText`）：同样跳过插话，重发回合开头那句。

## 5. 后台任务回报（前端逻辑，C 桥给数据即可）

- `ai.done` 的 `stop_reason` 为 `pending_task` 时，`pending_tasks` 是 `[{task_id, name}, …]`。
- 前端登记这些任务；等到对应的 `finished` 事件（`task_id`、`success`、`message`）时，发一条新回合（不显示用户气泡）：`[后台任务回报] {name} {成功|失败}：{message}`。「成功 / 失败」按界面语言翻译，`[后台任务回报]` 前缀是给模型的原文，不翻译。回合还在跑时改走 `ai_steer`。
- C 桥要保证：`ai.done` 带 `pending_tasks`；后台任务结束时发 `finished` 事件。
- 内核里已有同样文案的回合内短等待（`agent.py` 的 `_await_pending(20)`），移植内核时一并实现。

## 6. 对应测试

M5 对拍时可以照这些场景补 C 桥用例：

- `tests/test_bridge_parity.py::BridgeAiPayloadParityTests`：三个事件的键集合。
- `tests/test_bridge_parity.py::BridgeAiRunSteerTests`：尾部插话进 `unsent`；失败也带 `unsent`；新回合不被旧回合的 `finally` 清掉；`allow_always` 按 `TOOL_META` 判定；读到的插话按原位置入库。
- `tests/test_ai_agent_state.py::test_drained_steer_is_exported_in_place_for_persistence`：导出位置与 `steer_` id，发给模型的消息不带 id。
- `tests/test_ai_preview.py::RewindTests::test_rewind_takes_whole_turn_with_steer`：撤回撤整个回合。
- `tests/test_ai_compact_note_ui.py`：Qt 端入库顺序、重试跳过插话。
