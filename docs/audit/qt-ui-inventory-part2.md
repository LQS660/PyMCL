# PyMCL Python UI — Feature Inventory, Part 2

Worktree read: `C:\Users\Administrator\Downloads\Compressed\PyMCL-main\wt-opus45` (read-only; nothing modified).

Common conventions used below:
- All labels are the Chinese source strings exactly as passed to `tr()` in code (the `en.json` locale maps them to English at runtime).
- "Toast" = qfluentwidgets `InfoBar` (`success`/`error`/`info`/`warning`), with the given title/body/duration and position (`TOP` = top-centre of page, `TOP_RIGHT`).
- "Confirm box" = `MessageBox(title, body, parent)` with yes/cancel buttons; `exec()` truthy = yes.
- `InputDialog(title, label, text="", placeholder="")` = single line-edit modal, buttons 「确定」/「取消」, `.value()` = stripped text.
- `ComboDialog(title, label, items)` = dropdown modal, buttons 「确定」/「取消」.
- `EmptyState(icon, text)` = centred icon + text placeholder.
- `backend.call_async(fn, on_ok, on_err)` = run `fn` on a worker thread, deliver result / `str(exc)` back on UI thread.
- Backend signals (Qt) referenced: `task_added(task_id, title)`, `progress(task_id, current:int, total:int, message:str)`, `log(task_id, text)`, `finished(task_id, success:bool, message:str)`, `crash(task_id, report:dict)`, `login_code(code, uri)`, `login_status(text)`, `ui_changed()`, `theme_changed()`, `task_count_changed(int)`, `game_started()`, `game_exited(code)`.
- Task IDs are strings `"task-<n>"`. `progress.message` uses the format `"<status>  |  <speed>"` (two spaces, pipe, two spaces) when a speed segment exists.
- `MainWindow._reload_page(page)` calls `page.reload()` (no args) on every navigation to that page (throttled to once per 1.2 s unless data dirty). `ui_changed` → `_refresh_pages()` → `page.reload()` of the visible page.

---

## 1. `app/pages/account_page.py` — AccountPage (`objectName="accountPage"`)

### 1.1 Purpose / layout
Manage login identities. Vertical page:
1. Title `账号`, caption `微软正版、离线、Little Skin、统一通行证 / 自建 Yggdrasil`.
2. Top row:
   - **Skin card** (left): 140×260 body-skin preview (`BodyLabel` placeholder text `皮肤`, background `Theme.hover`, radius 8) + bold name label (initial `未登录`).
   - **已保存账号 card** (right, stretch): vertical list of account rows (see 1.2).
3. **微软账号 card**: bold label + primary button (icon PEOPLE) `设备码 / 浏览器登录`.
4. **皮肤站（authlib-injector） card**: row 1: preset `ComboBox` (180 px, items from `authlib_presets()` names) + API `LineEdit` (placeholder `https://littleskin.cn/api/yggdrasil`); row 2: user `LineEdit` (placeholder `邮箱 / 用户名`), `PasswordLineEdit` (placeholder `密码`), primary button `登录皮肤站`.
5. **统一通行证（Nide8） card**: bold label, caption `填 32 位服务器 ID，或把含该 ID 的链接贴进来`; row 1: server-id `LineEdit` (placeholder `服务器 ID / 链接`); row 2: username `LineEdit` (placeholder `用户名`), `PasswordLineEdit` (placeholder `密码`), primary button `登录通行证`.
6. **离线 card** (single row): bold label `离线`, name `LineEdit` (placeholder `离线角色名`), skin `ComboBox` (90 px; items `默认`, `Steve`, `Alex`), button `保存离线账号`.

Account row card (per saved account, `#accCard`, bordered, hover highlight):
- Avatar: if `row["body"]` non-empty → `ThumbnailTile(name, face_url, 36)` where `face_url = body.replace("/body", "/face")` if `"/body"` in url else body url; else `IconTile(name, 36)` (coloured letter tile).
- Bold name.
- Type pill: text by `row["type"]`: `microsoft`→`微软` (colour `#2E9B6B`), `authlib`→`皮肤站` (`#7C5CD6`), `nide8`→`统一通行证` (`#E8862E`), `offline`→`离线` (`#7C5CD6`), unknown→raw type.
- If `row["active"]`: extra pill `当前` (`#4C8BF5`).
- Stretch, then transparent buttons `使用` and (icon DELETE) `删除`.
- Empty state: caption `还没有正版或皮肤站账号`.

Skin card after reload: `active = first row with active==True, else rows[0], else None`; name label = `active["name"]` or `"Steve"`; body image fetched from `active["body"]` (HTTP GET, 12 s timeout, via `call_async`; a monotonically increasing token discards stale responses; pixmap scaled to 140×260 keep-aspect). If no active, nothing is loaded (placeholder text remains).

### 1.2 Controls / actions

| Control (label) | What it does | Backend call(s) | Result handling |
|---|---|---|---|
| Preset `ComboBox` (`currentTextChanged`) | Fill API field from preset | `authlib_presets()` (called at build and on every change) | For item whose `name` matches and `api` non-empty → `api.setText(item["api"])`. Preset `Blessing Skin（自填）` has empty api → field untouched. Called once on init too. |
| `设备码 / 浏览器登录` | Microsoft device-code login | `start_microsoft_login()` → task id | Guard: ignore if a dialog is already open. Opens modal `DeviceCodeDialog` (title `微软账号登录`, hint `正在获取登录代码…`, code label `------`, uri label, yes button `打开浏览器` opens `uri` in browser, cancel `关闭`). Stores task id. After dialog closes (any way) → `reload()`. **Closing the dialog does NOT cancel the task**; the backend also auto-opens the browser (`open_browser=True`). |
| `登录皮肤站` | Authlib/Yggdrasil login | `start_authlib_login(api, user, pw)` → task id | Ignore if busy. If API empty → toast error `缺少地址` / `请填写 Yggdrasil API` (TOP, 3000). Else set busy (both login buttons disabled, text `登录中…`). |
| `登录通行证` | Nide8 login | `start_nide8_login(sid, user, pw)` → task id | Ignore if busy. If sid empty → toast error `缺少服务器 ID` / `请填写统一通行证服务器 ID` (TOP, 3000). Else busy as above. |
| `保存离线账号` | Add offline account | `add_offline_account(name, skin)` where skin ∈ `"steve"`/`"alex"`/`"default"` mapped from combo text `Steve`/`Alex`/else | If name empty → toast error `缺少名字` / `请填写离线角色名` (TOP, 2500). Then `reload()`. |
| Row `使用` | Set active account | `set_active_account(name)` | `reload()` |
| Row `删除` | Remove account | `remove_account(name)` | Confirm box title `删除账号`, body `将删除账号「{name}」。若为微软账号，刷新令牌也会一并丢失，需重新走设备码 / 浏览器登录。`, yes text `删除`, cancel `取消`. On yes → remove + `reload()`. |

### 1.3 Signals / timers / persisted state
- `backend.finished(task_id, success, message)` → `_on_finished`: only if `task_id == self._login_task`. Clears busy state. If device dialog open and success → `dialog.accept()`. Success → toast `登录成功` / `message` (TOP, 2500) + `reload()`. Failure and `message != "已取消"` → toast error `登录失败` / `message` (TOP, 4000).
- `backend.login_code(code, uri)` → `dialog.show_code(code, uri)` (sets hint to `请在浏览器打开下面的地址并输入代码：`).
- `backend.login_status(text)` → `dialog.show_status(text)` (replaces hint). Status texts emitted by auth: `等待授权中…`, `网络错误，重试中…`.
- `restyle()` (theme change): re-apply skin placeholder bg + `reload()`.
- No timers. No config keys read directly (offline skin default `offline_skin` is used inside backend).

### 1.4 Backend data shapes
- `authlib_presets() -> list[{"name": str, "api": str}]`; from `mclauncher.authlib.PRESETS = [("Little Skin", "https://littleskin.cn/api/yggdrasil"), ("Blessing Skin（自填）", "")]`.
- `get_account_rows() -> list[dict]`: `{"name", "type" ("microsoft"|"authlib"|"nide8"|"offline"), "uuid", "api", "avatar": url, "body": url, "active": bool}`. Avatar/body URLs (`mclauncher/skin.py`): authlib with api → `<site_origin>/avatar/<name>` and `<site_origin>/preview/<name>`; microsoft with uuid → `https://crafatar.com/avatars/<uuid>?overlay=true&size=128` / `https://crafatar.com/renders/body/<uuid>?overlay=true&scale=6`; otherwise `https://mc-heads.net/avatar/<name>/128` / `https://mc-heads.net/body/<name>/180`.
- `remove_account(name)`: removes, if it was active → first remaining becomes active; emits `ui_changed`.
- `set_active_account(name) -> str` (new active); emits `ui_changed`.
- `add_offline_account(username, skin="") -> str name`; stored `{"type":"offline","name","uuid","skin"}`; uuid fixed for steve (`8667ba71-…`) / alex (`ec561538-…`), else offline-uuid of name; account becomes active; emits `ui_changed`.
- `start_microsoft_login() -> task_id`; task title `微软登录` (excluded from "download" tasks). Impl emits `login_code(code, uri)` (also `log("请打开 {uri} 并输入代码 {code}（{n} 分钟内有效）")`), `login_status(s)` + `progress(0,0,s)`; stores account `{"type":"microsoft","name","uuid","access_token","refresh_token","xuid","expires_at","updated_at"}`; finish message `任务完成`.
- `start_authlib_login(api, username, password) -> task_id`; title `皮肤站登录` (excluded from download tasks). Steps: `progress(0,0,"下载 authlib-injector")`, ensure injector jar, `progress(1,2,"登录皮肤站")`, login → account `{"type":"authlib","name","uuid","access_token",…,"api"}`; returns `"已登录 {name}"`.
- `start_nide8_login(server_id, username, password) -> task_id`; title `统一通行证登录` (**NOT excluded → shows in tasks page / dock / badge**). Steps `progress(0,0,"下载 nide8auth")`, `progress(1,2,"登录统一通行证")`; account `{"type":"nide8","name","uuid","access_token","client_token","server_id","api","username","expires_at","updated_at"}`; returns `"已登录 {name}"`. Server id: 32-hex or URL containing it (else error `服务器 ID 应为 32 位十六进制，或含该 ID 的链接`).
- `call_async(fn, ok, err)` used for skin download.

### 1.5 Edge behaviours
- Busy lock covers both authlib and nide8 buttons together.
- Success message for MS login is `任务完成` (generic), for others `已登录 <name>`.
- `已取消` failures are silent.
- The page reloads on every navigation and on `ui_changed`.

---

## 2. `app/pages/multiplayer_page.py` — MultiplayerPage (`objectName="multiplayerPage"`), Terracotta

### 2.1 Purpose / layout
Terracotta (EasyTier P2P) room hosting/joining. Vertical:
1. Header row: title `陶瓦联机` + state `Pill` (initial `未就绪`, grey `#888888`, solid). Caption (long): `输入邀请码即可加入。陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道；会和 HMCL 一样传官方节点，并带上本机 HMCL 用过的自定义会合节点。官方 PCL 联机大厅协议未开放，PCL 房间号无法互通；局域网请用下面地址。` Then LAN hint caption (selectable, word-wrap) = `backend.lan_hint()`.
2. Status `BodyLabel` (word-wrap; initial `正在检查联机内核…`).
3. **Firewall card**: `IconTile("墙", "#E8862E", 40)`, bold `防火墙通常不会弹窗`, caption `陶瓦在后台运行，Windows 不会提示。点「允许访问」后在 UAC 选是。若装了 360 / 电脑管家 / 火绒，还要在它们的名单里放行陶瓦和 EasyTier。`, primary button `允许访问` (110 px), button `打开设置` (90 px).
4. **Room card** (hidden until room/url): caption `邀请码（点击复制）`, `SubtitleLabel` room code (`—` default, selectable), caption url hint. Whole card `mousePressEvent` copies room code.
5. **Actions** vertical list of `ActionCard(letter, color, title, desc, button)` — rebuilt whenever state changes (see 2.3).
6. `房间成员` bold title (hidden until profiles) + member cards: `IconTile(name[:1], "#2E9B6B", 36)`, bold name (or `玩家`), caption `vendor` or kind, pill kind `房主`/`成员` (`#4C8BF5`). Kind: `HOST` (case-insens.) → `房主`, else `成员`.
7. Footer: transparent button `Terracotta 项目主页` → opens `https://github.com/burningtnt/Terracotta`; right caption `Terracotta | 陶瓦联机  © burningtnt  ·  基于 EasyTier`.

### 2.2 Controls / actions

| Control | Does | Backend | Result |
|---|---|---|---|
| `允许访问` | Add firewall rules via UAC | `terracotta_allow_firewall() -> str` | success toast `防火墙` / msg (TOP_RIGHT, 5000); exception → error toast `防火墙` / str(exc). |
| `打开设置` | Open Windows firewall CP | `terracotta_open_firewall_settings()` (fallback: open `ms-settings:windowsdefender`) | — |
| Room card click / `复制` action | Copy invite code | — (clipboard) | toast success `已复制` or `已将邀请码复制到剪贴板` with code as body (TOP_RIGHT, 2000). Empty text → no-op. |
| Action `下载` (state `missing`) / `启动` (state `idle`) / `重启` (exception/fatal) | Install+start kernel | `terracotta_prepare() -> task_id` | Sets `_busy`; calls `window.fly_to_tasks(sourceWidget, "联", "#2E9B6B")`; UI shows `installing` while busy. |
| Action `刷新` (launching/unknown/installing) | Re-poll | `reload()` | — |
| Action `创建` (state `waiting`, primary) | Become host | `terracotta_host()` | If snapshot `game_running` is false → confirm box title `您似乎忘记启动游戏了`, body `请先启动游戏，进入单人世界，按 ESC，选择对局域网开放。`, yes `游戏已启动`, cancel `取消`; cancel aborts. Exception → error toast `创建房间失败`. Then `reload()`. |
| Action `加入` (state `waiting`) | Join room | `terracotta_join(code)` | `InputDialog(我想当房客, 请输入房主提供的邀请码, placeholder "U/XXXX-XXXX-XXXX-XXXX")`; empty → abort. Exception → error toast `邀请码错误` / str(exc) (4000). `reload()`. |
| Action `退出` (host-scanning/host-starting/host-ok/guest-connecting/guest-starting/guest-ok) / `返回` (exception/fatal) | Back to waiting | `terracotta_idle()` | Exception → toast `返回失败`. `reload()`. |
| Action `进入` (state `guest-ok`, primary) | Launch game into lobby | `terracotta_enter_world() -> str` | Exception → error toast `进入世界失败` (5000). If result startswith `"task-"` → `fly_to_tasks(self, "进", "#2E9B6B")` + success toast `正在启动游戏` / `启动后会直接进入陶瓦联机大厅。`; else success toast `已加入房间` / result or `请到多人游戏双击「陶瓦联机大厅」。`. |
| Action `直连` (exception/fatal) | Direct connect | `terracotta_direct_connect(address) -> str` | `InputDialog(公网直连, 朋友需先对局域网开放世界，并在路由器映射该端口。然后输入他的公网地址。, placeholder "例如 1.2.3.4:25565")`. Missing backend method → error `直连失败`/`当前版本没有公网直连。`. Success toast `正在直连` / result or `启动后会进入该服务器。`; exception → `直连失败`. |
| Action `了解` (state `unsupported`) | Open project home | — | opens GitHub URL |

Action cards per state (`_fill_actions`), each `(letter, color, title, desc, buttonText, primary?)`:
- `unsupported`: `("!", "#D95568", 当前系统不支持, 陶瓦联机暂未提供此架构的官方内核。, 了解)`
- `missing`: `("瓦", "#2E9B6B", 下载陶瓦联机内核, 首次使用需要下载约 8 MB 的官方内核，之后可直接开房。, 下载, primary)`
- `idle`: `("▶", "#4C8BF5", 启动联机内核, 内核已安装，点一下即可开始联机。, 启动, primary)`
- `launching`/`unknown`/`installing`: `("…", "#888888", 请稍候, info.label or 正在准备联机内核。, 刷新)`
- `waiting`: `("房", "#2E9B6B", 我想当房主, 创建房间并生成邀请码，与好友一起畅玩。, 创建, primary)` + `("客", "#4C8BF5", 我想当房客, 输入房主提供的邀请码加入游戏世界。, 加入)`
- `host-scanning`/`host-starting`: `("扫", "#E8862E", 正在扫描局域网世界, 请启动游戏，进入单人世界，按 ESC，选择对局域网开放。, 退出)`
- `host-ok`: `("复", "#2E9B6B", 复制邀请码, 好友在联机页选择房客并输入该邀请码即可加入。, 复制, primary)` + `("返", "#888888", 退出, 这将同时彻底关闭房间，其他房客将退出。, 退出)`
- `guest-connecting`/`guest-starting`: `("连", "#4C8BF5", 正在加入房间, info.difficulty_hint or 正在与房主建立连接。, 退出)`
- `guest-ok`: `("进", "#2E9B6B", 进入世界, 启动游戏后到多人游戏双击「陶瓦联机大厅」，或点这里直接进入。, 进入, primary)` + `("返", "#888888", 退出, 这不会影响其他房客加入当前房间。, 退出)`
- `exception`/`fatal`: `("!", "#D95568", 联机失败, info.error_hint or info.error or 请返回后重试，或检查网络。, 返回)` + `("直", "#4C8BF5", 朋友是公网就直连, 让他把单人世界对局域网开放，并在路由映射该端口，然后填他的公网 IP:端口。, 直连)` + `("启", "#4C8BF5", 重新启动内核, 若内核已退出，点此重新拉起。, 重启)`

### 2.3 Polling / signals / rendering
- `QTimer` 1200 ms → `reload()`; started in `showEvent`, stopped in `hideEvent`. `reload()` runs `terracotta_snapshot()` via `call_async` with a `_polling` guard (one in flight). Failure → render `{"state":"fatal","label":msg,"error":msg}`.
- `showEvent` also calls `_maybe_prepare()`: once per page lifetime (`_auto_started`), if snapshot has `supported && installed && !running` → auto `terracotta_prepare()`.
- `backend.finished` → `_on_task`: only if `"陶瓦" in backend.task_title(task_id)`; clears `_busy`; failure → error toast `title` / message (TOP_RIGHT, 5000); `reload()`.
- `_render(info)`:
  - `state = info.state or "missing"`; if `_busy` and state in (`missing`,`idle`) → show as `installing`; if state in (`waiting`,`host-ok`,`guest-ok`) or (`idle` and not busy) → `_busy=False`.
  - Pill colours: `host-ok`/`guest-ok`/`waiting` `#2E9B6B`; `idle` `#4C8BF5`; `exception`/`fatal`/`unsupported` `#D95568`; `missing` `#E8862E`; else `#888888`. Pill text = `info.label or state`, but `加入失败` for exception/fatal.
  - Status text: `info.error or info.label`; if `error_hint` → `error + "\n" + error_hint`; elif `difficulty_hint` → `label + "\n" + difficulty_hint`.
  - Room card shown if `room or url`; room label = room or `陶瓦联机大厅`; url hint = `请启动游戏，选择多人游戏，双击进入陶瓦联机大厅。` if url else `请提醒好友在联机页选择「我想当房客」，并输入该邀请码。`
  - Actions rebuilt only when state changes; members rebuilt only when `(name, kind, vendor)` tuple signature changes.
  - On transition into `host-ok` with a room → auto-copy code to clipboard with toast `已将邀请码复制到剪贴板`.
- On main window close: `backend.terracotta_shutdown()`.

### 2.4 Backend data shapes
- `lan_hint(port=25565) -> str`: `"房主在游戏里「对局域网开放」后，把下面地址发给好友：\n" + "\n".join(f"{ip}:{port}")`. `local_ips() -> list[str]` (non-loopback IPv4s, preferred route first, fallback `["127.0.0.1"]`).
- `terracotta_snapshot() -> dict` (`terracotta.snapshot(player, game_running)`): keys `supported: bool, installed: bool, running: bool, port: int, state: str, label: str, room: str, url: str, difficulty: str ("EASIEST"|"SIMPLE"|"MEDIUM"|"TOUGH"|""), difficulty_hint: str, profiles: [{"name","vendor","kind"}], error: str, error_hint?: str, player: str, game_running: bool, copyright: str, home: str, version: str, nodes: [str], firewall_stale: bool`. States: `missing, unsupported, installing, launching, unknown, waiting, host-scanning, host-starting, host-ok, guest-connecting, guest-starting, guest-ok, exception, fatal, idle`. Labels `_STATE_LABEL`: missing `未下载联机核心`, unsupported `当前系统架构暂不支持陶瓦联机`, installing `正在下载联机核心…`, launching/unknown `正在初始化联机核心`, waiting `联机核心已就绪`, host-scanning `正在扫描局域网世界`, host-starting `正在启动房间`, host-ok `已启动房间`, guest-connecting/guest-starting `正在加入房间`, guest-ok `已加入房间`, exception `联机出错`, fatal `联机内核已停止`, idle `内核已安装，打开本页会自动启动`. Exception error texts (`_EXC[type]`): 0 `加入房间失败：找不到房主。房间已关闭，或尚未连上公共中继` (+ `error_hint` = `_PING_HOST_HINT`), 1 `房间连接断开：房间已关闭或网络不稳定`, 2 `加入房间失败：EasyTier 已崩溃，请向开发者反馈该问题`, 3 `创建房间失败：EasyTier 已崩溃，请向开发者反馈该问题`, 4 `房间已关闭：您已退出游戏世界，房间已自动关闭`, 5 `协议错误：房主发送了错误的响应数据，请向开发者反馈该问题`. Difficulty hints: EASIEST `当前网络状态极好：稍等一下就成功！`, SIMPLE `当前网络状态较好：建立连接需要一段时间……`, MEDIUM `当前网络状态中等：已启用抗干扰备用线路，连接可能失败`, TOUGH `当前网络状态极差：已启用抗干扰备用线路，连接可能失败`. Side effect: on `guest-ok` with url, writes `陶瓦联机大厅` into default instance `servers.dat`.
- `terracotta_player() -> str` (active account name or `Player`).
- `terracotta_prepare() -> task_id`; title `准备陶瓦联机`; impl: install (download ~8 MB), `progress(1,1,"启动内核")`, start; returns `陶瓦联机已就绪`. Counted as download task.
- `terracotta_host()` → HTTP `/state/scanning`; `terracotta_join(room)` → validates (`请输入邀请码。` / `room_error(...)`), `/state/guesting`; `terracotta_idle()` → `/state/ide`. All raise `TerracottaError` on failure.
- `terracotta_allow_firewall() -> str`: Windows only (else raises `当前系统请在系统防火墙里手动放行陶瓦联机。`); needs installed kernel (`还没找到陶瓦内核，请先点下载/启动，再允许防火墙。`); writes bat, runs elevated; UAC denied → `已取消管理员授权，防火墙规则没有写入。`; success `已允许 {names} 通过防火墙。若装着电脑管家/360/火绒，还要在它们里面放行。`
- `terracotta_open_firewall_settings()` → `control firewall.cpl` (Windows).
- `terracotta_enter_world() -> str`: requires `state == "guest-ok"` and url else raises `还没连上房间。请先输入邀请码加入。`; then `_launch_into_server(url, "请到游戏「多人游戏」双击「陶瓦联机大厅」。")`: remembers lobby in servers.dat; if game running → returns that message; else picks default instance's newest installed version (raises `请先到「启动」页安装一个版本。` if none), account = active MS account or `离线模式` with active name, memory/width/height from CONFIG (`memory_mb`,`width`,`height`), `extra_game_args=["--server", host, "--port", port]` → `launch_game(...)` → returns task id (`task-N`).
- `terracotta_direct_connect(address) -> str`: parses `host:port` (default 25565); rejects empty/localhost with `请输入房主的公网地址，例如 1.2.3.4:25565`; same `_launch_into_server`.
- `terracotta_shutdown()` stops kernel.
- `task_title(task_id) -> str`.

### 2.5 Edge behaviours
- Auto-start kernel once when page first shown (if installed & not running).
- Kernel-preparation while busy shows `installing` pseudo-state even if snapshot says missing/idle.
- All toasts TOP_RIGHT.
- Room code copy on host-ok is automatic once per transition.

---

## 3. `app/pages/servers_page.py` — ServerPage

### 3.1 Purpose / layout
Per-instance multiplayer server list (backed by instance `servers.dat` + `servers.json`).
- Top bar (56 px): title `服务器列表` (18 px), label `实例` + instance `ComboBox` (160 px), stretch, buttons `添加服务器` (icon ADD), `导入`, `导出`.
- Body `QStackedWidget`: table or `EmptyState(globe icon, "没有可用的服务器\n点击「添加服务器」开始添加")`.
- Table columns: `名称` (stretch), `地址` (fit), `端口` (fit), `描述` (stretch; text truncated to 40 chars), `操作` (last, stretch) with transparent buttons `编辑`, `删除`. Row select, no editing, alternating colours, vertical header hidden.

### 3.2 Controls

| Control | Does | Backend | Result |
|---|---|---|---|
| Instance combo change | Reload list for that instance | `get_instances()` (names), `list_servers(instance)` | Preference order when filling: explicit `prefer` arg > current combo text > `CONFIG["default_instance"]` > first name. |
| `添加服务器` | 3 sequential `InputDialog`s | `add_server(instance, name, ip, port)` | Dialogs: (`添加服务器`, `服务器名称`, placeholder `可选`) → (`添加服务器`, `服务器地址`, placeholder `example.com 或 IP`) → (`添加服务器`, `端口`, text `25565`, placeholder `默认 25565`). Cancel any → abort. Port parsed only if `^\d{1,5}$` else 25565. Success toast `已添加` / `服务器 {name or ip} 已添加` (2000) + reload; error toast `添加失败` / str(e) (3000). |
| Row `编辑` | 2 dialogs (name, ip) | `update_server(instance, index, name=, ip=, port=existing)` | Dialogs (`编辑服务器`, `服务器名称`, text=current) → (`编辑服务器`, `服务器地址`, text=current). Success toast `已更新` / `服务器已更新`; error `更新失败`. Port/description not editable in UI. |
| Row `删除` | Confirm & delete | `delete_server(instance, index)` | Confirm box (`确认删除`, `删除服务器 {name}？`). Success toast `已删除` (empty body); error `删除失败`. |
| `导入` | File open dialog | `import_servers(instance, text) -> int` | `QFileDialog.getOpenFileName(选择导入文件, filter "文本文件 (*.txt);;JSON (*.json)")`; reads UTF-8; toast `导入完成` / `已导入 {n} 个服务器`; error `导入失败`. |
| `导出` | Save dialog | `export_servers(instance) -> str` | Backend call first (error → `导出失败`); then `getSaveFileName(导出服务器, default "servers.txt", "文本文件 (*.txt)")`; write UTF-8; toast `已导出` / `已保存到 {path}`; write error → `导出失败`. |

### 3.3 Signals / state
- `reload(instance="")` invoked by navigation (`reload()` no-arg) and after every mutation. `list_servers` exceptions → empty list.
- Reads `CONFIG["default_instance"]`. `restyle()` refreshes top bar/table QSS.

### 3.4 Data shapes
- `get_instances() -> list[{"name", "versions": int, "mc": str, "pack": str, "pack_version": str, "mc_version": str, "java": str, "java_label": str}]` (2.5 s TTL cache).
- `list_servers(instance) -> list[{"name": str, "ip": str, "port": int, "icon": str, "description": str, "hidden": bool, "index": int}]` — reads `servers.dat` first (merged with `servers.json` extras), else json.
- `add_server(instance, name, ip, port=25565, description="") -> normalized row`; raises `ServerError("服务器地址不能为空")`, `"端口号必须在 1-65535 之间"`. name defaults to ip. Writes both json and dat.
- `update_server(instance, index, **kwargs{name, ip, port, description, icon, hidden}) -> row`; raises `服务器索引 {i} 不存在` etc.
- `delete_server(instance, index)`.
- `import_servers(instance, text) -> int`: if text starts with `[` → JSON array of `{ip, port?, name?...}` (dedupe by `ip:port`); else line format `名字\t地址:端口` | `地址:端口` | `地址`, `#` comments ignored; dedupe.
- `export_servers(instance) -> str`: lines `# PyMCL 服务器列表导出`, `# 共 N 个服务器`, blank, then `name\tip:port` or `ip:port`.

### 3.5 Edge
- Empty state replaces the table in the same slot.
- Toasts have no position (default) here.

---

## 4. `app/pages/playtime_page.py` — PlaytimePage

### 4.1 Layout
- Top bar: title `游玩时长` (18 px), stretch, button `清除记录`.
- Body stacked: scroll area of cards, or `EmptyState(clock icon, "还没有游玩记录\n启动游戏后会自动记录")`.
- If `_instance` set (single instance mode, `reload(instance)`): one card: `总时长` (16 px bold) + formatted total (20 px bold); then per version rows sorted by seconds desc (skip ≤0): version id label + `Pill(formatted)`.
- Else (all instances): one card per instance with `total > 0`: instance name (15 px bold) + formatted total; per version rows as above.
- Empty state if no rows with `total > 0`.

### 4.2 Controls

| Control | Does | Backend | Result |
|---|---|---|---|
| `清除记录` | Confirm box (`确认清除`, `清除所有游玩时长记录？此操作不可恢复。`) | `clear_playtime(instance)` (instance `""` = all) | toast `已清除` (2000) + reload; error `清除失败`. |

### 4.3 Data shapes
- `get_playtime(instance) -> {"total": int_secs, "versions": {version_id: secs}, "sessions": [{"start": epoch, "duration": secs, "version": id}]}` (instance `""` → default instance).
- `get_all_playtime() -> {instance_name: {"total","versions","sessions"}}`.
- `format_playtime(seconds) -> str`: `"{h} 小时 {m} 分钟"` if h>0; `"{m} 分钟 {s} 秒"` if m>0; else `"{s} 秒"`. UI fallback if call fails: `"{h} 小时 {m} 分钟"` / `"{m} 分钟"`.
- `clear_playtime(instance="", version="")`.
- Storage: `<ROOT>/playtime.json`; recorded automatically by the launch task (`PlaytimeTracker`).

### 4.4 Edge
- Page navigation calls `reload()` (no arg → all instances). `restyle()` re-renders.

---

## 5. `app/pages/feedback_page.py` — FeedbackPage (`objectName="feedbackPage"`)

### 5.1 Layout (scrollable)
1. Title `反馈`, caption `发给开发者。第一次打开需手动同意后才会上传；可附带本机配置。`
2. **Form card**: row: category `ComboBox` (160 px, labels from `CATEGORIES`) + contact `LineEdit` (placeholder `联系方式（QQ / 邮箱，可选）`); title `LineEdit` (placeholder `标题，例如：1.20.1 Fabric 启动黑屏`); body `PlainTextEdit` (min 160 px; placeholder `发生了什么、怎么复现、期望结果。崩溃可直接从崩溃窗口点「发送给开发者」。`); row: `CheckBox` `附带本机配置` (checked) + primary button (send icon) `发送反馈` (36 px).
3. **常见问题 card**: bold `常见问题`, caption `启动、Java、模组、账号、联机的快速说明（点击标题展开）`, list of transparent buttons (article titles).
4. Row: bold `本机配置预览` + transparent button (SYNC) `重新采集`.
5. Read-only `PlainTextEdit` (min 220 px) with sysinfo text (initial `正在采集本机配置…`).
6. `最近提交` label + caption list (initial `暂无`).

Categories (`feedback_defaults.CATEGORIES`, key → label): `bug`→`功能异常`, `crash`→`崩溃闪退`, `download`→`下载问题`, `multiplayer`→`联机`, `ai`→`AI 助手`, `ui`→`界面体验`, `suggest`→`建议`, `other`→`其他`.

### 5.2 Controls

| Control | Does | Backend | Result |
|---|---|---|---|
| `发送反馈` | Submit | `submit_feedback(category=, title=, body=, contact=, include_sysinfo=)` via `call_async` | Empty title AND body → warning toast `空内容` / `请填写标题或描述` (TOP, 2500). If `feedback.has_consent()` false → `prompt_feedback_consent(window)` (see 5.4); refused → warning `未同意` / `不同意上传则不会发送反馈` (3000) and abort. Button disabled + text `发送中…`. OK: re-enable, clear title/body, reload history, toast success `已发送` / `开发者会实时看到这条反馈 {id}` (3500). Error: re-enable, toast error `发送失败` / str(exc) (5000). |
| `重新采集` | Re-collect sysinfo | `collect_sysinfo(force=True, scan_system_java=True)` then `sysinfo_text(info)` | Sets text `正在采集本机配置…`, then result; also reloads history; error → text `采集失败：{exc}`. |
| Article button | Show article | `help_articles()` for list; `help_article(id)` if body missing | `MessageBox(title or 帮助, body or 暂无内容)`. Fallback to `mclauncher.help_content.search_articles("")` if backend lacks method. |
| `prefill(category="bug", title="", body="")` (called externally) | Pre-populate form | — | Sets combo by key, title, body. |

### 5.3 Behaviour on reload
`reload(force=False)`: called on navigation → `collect_sysinfo(force=False, scan_system_java=False)` (cached ≤120 s) → text + history. History: first 8 rows as `"{category_label}  {title}  ({id})"`.

### 5.4 Consent prompt (`app/widgets.prompt_feedback_consent`)
`MessageBox(是否上传诊断数据, "第一次打开需要你亲自选择。\n\n同意后才会向开发者上传：\n· 你提交的反馈内容\n· 本机配置（CPU / 内存 / 显卡 / Java / 实例）\n\n暂不同意则不会上传，以后可在设置里更改。")`, yes `同意`, cancel `暂不同意`. Result → `feedback.set_consent(ok)` (writes `feedback_consent` True/False and saves); if ok `start_heartbeat()` else `stop_heartbeat(send_offline=False)`. Main window shows it on boot if `feedback_consent is None`; if consent already true, starts heartbeat (30 s interval POST `/api/v1/heartbeat`).

### 5.5 Data shapes
- `collect_sysinfo(force, scan_system_java) -> dict`: `collected_at, hostname, os{}, cpu{name, cores_physical, cores_logical,…}, memory{total_bytes, total_mb, avail_mb, load_percent}, gpus[{name, vram_mb, driver}], disks[{path, free_gb, total_gb}], display{width, height, screens}, java[{major, path,…}], launcher{name, version, frozen, python, root, memory_mb, download_threads, download_source, community_source}, instances[{name, versions[], mod_count}], summary: str`.
- `sysinfo_text(info) -> str` multi-line summary (CPU/内存/显卡/分辩率/磁盘/Java/启动器/实例 lines).
- `submit_feedback(...) -> dict` server JSON (uses `id`); raises `FeedbackError` texts e.g. `需要先同意上传诊断数据。…`, `请填写标题或内容`, `未配置反馈服务器。…`, `连不上反馈服务器: …`, `反馈服务器 HTTP {code}: …`. Title trimmed 120, body 16000, contact 120; missing title → first body line[:80] or `未命名反馈`. Appends to history file `feedback_history.json` (max 30).
- `feedback_history() -> list[{"id", "ts", "category", "title", "ok": True}]` newest first.
- `help_articles(query="") -> list[{"id","title","body"}]` (ids: `launch-fail`, `java`, `mods`, `account`, `multiplayer`, `isolation`); `help_article(id) -> dict|{}`.
- Feedback URL resolution: `CONFIG.feedback_url` → env `PYMCL_FEEDBACK_URL` → `DEFAULT_FEEDBACK_URL = "http://114.66.28.184:53611"`.

---

## 6. `app/pages/settings_page.py` — SettingsPage (`objectName="settingsPage"`) + `layout_settings.py`

### 6.1 Layout
Scrollable `SettingCardGroup`s; title `设置`. Controls are `SettingCard(icon, title, desc)` with a right-aligned widget. Bottom row: primary `保存设置` (icon SAVE, 36 px) + `测试 AI 连接` (icon SYNC); caption `启动器主目录: {settings.root}`.

Initial values come from `backend.get_settings()` (shape in 6.5). The page does **not** reload on navigation (deliberately—`refresh_from_config()` exists and is only called after theme load; it refreshes `ui_dark`, `theme_color`, `ui_background`, `allow_multi_instance`).

### 6.2 Every setting control

Legend: **Apply** = `live` (takes effect immediately when changed), `save` (only when `保存设置` pressed; then live at next use), `restart`.

**Group `版本隔离与存储`**

| Label / desc | Widget | Settings key (get_settings) → CONFIG key | Type / range | Default | Apply |
|---|---|---|---|---|---|
| `共享 libraries` / `所有实例共享依赖库（节省空间，但会降低隔离性）` | Switch | `share_libraries` → `shared_libraries` | bool | False | save |
| `共享 assets 资源` / `所有实例共享资源文件（节省空间，但会降低隔离性）` | Switch | `share_assets` → `shared_assets` | bool | False | save |
| `新版本默认隔离` / `安装新版本时写入该版本的隔离模式，可稍后在版本设置改` | Combo: `关闭（共用实例目录）`=none, `隔离存档`=saves, `隔离 Mod 与配置`=mods, `隔离全部`=all | `default_isolation` | enum | `none` | save |
| `游戏目录` / `实例与版本所在文件夹` | LineEdit (220 px) + button `浏览` | `game_dir` (read) → `instances_dir` via `set_game_dir` | path | `.minecraft` under ROOT | `浏览`: live (`getExistingDirectory(选择游戏目录)` → `set_game_dir(path)`; toast `已切换目录`/path or error `切换失败`). Typed path: applied on `保存设置` (`set_game_dir(typed)` if differs; error toast `游戏目录无效`, field reverted, save aborted). |

**Group `界面`**

| Label / desc | Widget | Key | Type | Default | Apply |
|---|---|---|---|---|---|
| `界面动画` / `换页过渡、布局编辑、进度条、横幅微光等动效；关闭则全部瞬时` | Switch | `ui_motion` | bool | True | save (then live: read from CONFIG at each animation) |
| `下载飞入动画` / `点击安装时，图标抛物线飞入侧栏「下载任务」` | Switch | `ui_fly_animation` | bool | True | save (then live) |
| `飞入动画时长` / `毫秒，建议 400–800；越小越快` | SpinBox 200–1200 | `ui_fly_duration_ms` | int | 620 | save (then live) |
| `深色模式` / `立即生效，接近 PCL 夜间主题` | Switch | `ui_dark` | bool | False | **live**: `save_settings({"ui_dark": v})` + `window.apply_theme()` |
| `主题色` / `例如 #2E9B6B` | LineEdit | `theme_color` | `#RRGGBB` | `#2E9B6B` | **live on editingFinished**: `#` prepended if missing; empty → default; `save_settings({"theme_color"})` + apply_theme |
| `背景图` / `本地图片路径，留空为纯色` | LineEdit + button `选择文件` | `ui_background` | path or "" | "" | **live**: picker `getOpenFileName(选择背景图, filter "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*)")` → `save_settings({"ui_background"})` + apply_theme + toast `已应用`/`背景已更新`; editingFinished also applies if changed |
| `启动器可见性` / `游戏启动后启动器窗口怎么处理。关闭不会杀掉游戏进程。` | Combo: `保持显示`=keep, `最小化`=minimize, `隐藏`=hide, `隐藏，退出后重开`=hide_reopen, `关闭启动器`=close | `launcher_visibility` | enum | keep | save (read at `game_started`) |
| `启动页主页` / `右侧栏显示新闻、自定义 HTML 或留空` | Combo: `Minecraft 新闻`=news, `本地 HTML`=custom, `空白`=blank | `homepage_mode` | enum | news | save (launch page reload) |
| `自定义主页` / `本地 .html 文件路径` | LineEdit | `custom_homepage` | path | "" | save |
| `默认游戏窗口` / `可被版本设置覆盖` | Combo: `窗口`=window, `全屏`=maximize | `window_mode` | enum | window | save |
| `语言` / `切换界面语言，改后重启生效` | Combo of `available_languages().values()` (`简体中文`, `English`), current from `get_language()` | `language` (via `i18n.set_language`) | `zh_CN`/`en` | `zh_CN` | **restart** (see 6.3) |
| `主题包` / `保存/加载当前主题配色` | Buttons `保存当前主题`, `加载主题`, `删除主题` | themes dir | — | — | see 6.3 |

**Group `个性化布局`** (see 6.4 for dialogs)

| Label / desc | Widget | Effect |
|---|---|---|
| `启动页布局` / `卡片随意拖动 / 缩放 / 增删，自由摆放` | button `进入编辑` | `window.switchTo("launch")` + `launch_page.enter_edit_mode()` |
| `布局方案` / `切换整套布局；编辑后自动记住` | Combo (`默认布局` + sorted profile names) + buttons `另存为…`, `删除`, `重置默认` | combo change → `switch_profile(name)`; save-as → `InputDialog(另存为布局方案, 方案名称)` → `save_current_as_profile` → toast `已保存`/`布局方案「{0}」已保存`; delete → if default selected → info toast `默认布局`/`默认布局不能删除，可用「重置默认」恢复`, else `delete_profile` → toast `已删除`/`布局方案「{0}」已删除`; reset → `switch_profile("")` → toast `已重置`/`启动页布局已恢复默认` |
| `布局导入/导出` / `把布局存成 JSON 文件，换机或分享给朋友` | buttons `导出…`, `导入…` | export: `getSaveFileName(导出布局, "pymcl-layout.json", "JSON (*.json)")` → `layout_model.export_doc`; success toast `已导出`/path, failure `导出失败`/path. import: `getOpenFileName(导入布局, "JSON (*.json)")` → `import_doc`; invalid → error `导入失败`/`不是有效的布局文件`; ok → `save_active_doc(doc)`, `launch_page.apply_doc(doc)`, toast `已导入`/`布局已应用，可直接「另存为方案」保留` |
| `侧栏自定义` / `导航项排序 / 显示隐藏 / 侧栏宽度` | button `自定义侧栏…` | opens `SidebarEditorDialog` |
| `分区内容` / `子页在「下载」和「更多」之间移动、排序` | button `自定义分区…` | opens `SectionEditorDialog` |

**Group `下载与性能`**

| Label / desc | Widget | Key → CONFIG | Type/range | Default | Apply |
|---|---|---|---|---|---|
| `下载并发线程数` / `同时下载的文件数量` | Spin 1–64 | `download_threads` | int | 8 | save (next task) |
| `文件下载源` / `和 PCL 一样：自动测速，官方慢于 4 秒就改走 BMCLAPI` | Combo: `自动（官方>4秒改 BMCLAPI）`=auto, `仅官方`=official, `仅 BMCLAPI`=bmclapi | `download_source` | enum | auto | save (save_settings calls `invalidate_probe()`+`warmup_async()`) |
| `社区资源源` / `模组 / 整合包：MCIM 国内镜像，挂了可改官方` | Combo: `自动`=auto, `仅官方`=official, `仅 MCIM`=mcim | `community_source` | enum | auto | save |
| `跟随系统代理` / `默认开。Clash 7897 会生效；关掉才强制直连` | Switch | `use_system_proxy` | bool | True | save (save_settings calls `apply_proxy_policy()`) |
| `默认内存 (MB)` / `新实例的默认 JVM 内存` | Spin 512–32768 | `default_memory_mb` → `memory_mb` | int | 4096 | save |
| `内存回收器` / `启动时写入 JVM。版本设置可覆盖。` | Combo: `G1（推荐）`=auto, `G1`=g1, `调优 G1`=g1_tuned, `ZGC`=zgc, `不指定`=none | `gc_preset` | enum | auto | save |
| `下载限速 (KB/s)` / `0 表示不限制` | Spin 0–102400 | `download_limit_kbps` | int | 0 | save |
| `默认 JVM 参数` / `所有版本都会带上，版本设置可再追加` | LineEdit | `default_jvm_args` | str | "" | save |
| `默认分辨率` / `游戏窗口的默认宽高` | two Spins: width 320–7680, height 240–4320, separated by `×` | `default_resolution` → `width`,`height` | [int,int] | [854,480] | save |

**Group `账号与下载源`**

| Label / desc | Widget | Key → CONFIG | Default | Apply |
|---|---|---|---|---|
| `微软 OAuth 客户端 ID` / `一般无需修改` | LineEdit | `ms_client_id` → `microsoft_client_id` | `00000000402b5328` | save (empty keeps old value) |
| `CurseForge API 密钥` / `可选；仅在国内镜像不可用时用于搜索兜底` | PasswordLineEdit | `curseforge_api_key` | HMCL key `$2a$10$o8py…` | save |

**Group `维护`**

| Label / desc | Widget | Key | Default | Apply / action |
|---|---|---|---|---|
| `更新清单 URL` / `JSON：version / url / notes` | LineEdit | `update_url` | `https://pymcl.dev/update.json` | save |
| `启动时检查更新` / `打开启动器后在后台检查自更新清单` | Switch | `auto_check_update` | True | save (next boot) |
| `允许多开` / `取消勾选 = 游戏运行时再次启动会提示` | Switch | `allow_multi_instance` | False | save (checked at launch) |
| `官方启动器迁移` / `从官方 .minecraft 导入版本和账号` | button `检测并迁移` | — | — | see 6.3 |
| `智能推荐` / `根据硬件自动推荐内存和 Java 设置` | button `查看推荐` | — | — | see 6.3 |
| `维护工具` / `更新、清理、导出、全局 Mod` | primary `检查更新`, `清理`, `导出实例`, `全局 Mod` | — | — | see 6.3 |

**Group `AI 助手`**

| Label / desc | Widget | Key | Default | Visibility |
|---|---|---|---|---|
| `接入方式` / `公益接口已内置，小白不用填密钥` | Combo (180 px): `公益接口`=public, `自定义 NewAPI`=custom | `ai_mode` | public | always |
| `自建网关（可选）` / `一般留空，走内置公益接口` | LineEdit | `ai_gateway_url` | "" (DEFAULT_GATEWAY_URL="") | only when mode = public |
| `NewAPI Base URL` / `自定义模式：填到 /v1 为止` | LineEdit | `ai_base_url` | "" | only custom |
| `NewAPI 令牌` / `只在自定义模式使用，不要用站长无限额令牌` | PasswordLineEdit | `ai_api_key` | "" | only custom |
| `模型名` / `公益模式锁定 deepseek-v4-flash；自定义才改得了` | LineEdit | `ai_model` | `deepseek-v4-flash` | only custom |

All AI fields: save.

**Group `反馈与诊断`**

| Label / desc | Widget | Key | Default | Apply |
|---|---|---|---|---|
| `允许上传诊断数据` / `第一次打开会询问。未同意时不会上传反馈和电脑配置` | Switch | `feedback_consent` | None (unasked) → shown as False | save: also `feedback.set_consent(v)`; True → `start_heartbeat()`, False → `stop_heartbeat(send_offline=False)` |
| `反馈上报地址` / `指向上报口，不要填看板端口` | LineEdit | `feedback_url` | "" (falls back to default URL) | save |
| `定时上报本机配置` / `同意上传后，启动器打开时把电脑配置发到上报口` | Switch | `feedback_heartbeat` | True | save |

### 6.3 Buttons / flows

| Button | Flow | Backend |
|---|---|---|
| `保存设置` | (1) typed game dir → `set_game_dir` if changed (abort on error). (2) `save_settings(collect())` (35 keys, below). (3) consent/heartbeat. (4) language: map label→code (default `zh_CN`), `lang_changed = lang != i18n.current_language()`, `i18n.set_language(lang)`. Toast `已保存`/`设置已写入 config.json` (2500). If lang changed → restart prompt (`MessageBox(语言已切换, 界面文字要重启启动器才会全部变成新语言。是否现在重启？, yes 立即重启, cancel 稍后)`; cancel → info toast `语言已切换`/`下次启动启动器后界面才会变成新语言` (5000); yes → `QProcess.startDetached(sys.executable, sys.argv)` then quit; failure → error toast `重启失败`/`无法拉起新进程，请手动关闭后重新打开`). (5) `window.apply_theme()`, `launch_page.reload()`. | `set_game_dir`, `save_settings`, `available_languages` |
| `测试 AI 连接` | `probe = get_settings(); probe.update(collect())` (unsaved values!) → `test_ai_connection(probe)` async. Button disabled/`测试中…`. Success toast `AI 连接成功`/msg (4000); error `AI 连接失败`/str(exc) (5000). | `test_ai_connection(settings)` |
| `检查更新` | `call_async(check_update)`; if `has_update` → `start_self_update()` + toast `发现更新`/message; else info toast `检查更新`/message or `已是最新`; error `检查失败`. | `check_update`, `start_self_update` |
| `清理` | Button → `扫描中…`; `call_async(cleaner_preview)`; confirm box `清理文件` / `将删除 {count} 个未引用库 / 残留 .part / 更新缓存，约 {format_size(bytes)}`; yes → `清理中…` + `call_async(cleaner_apply)`; toast `清理完成`/`删除 {removed} 个文件`; error `清理失败`. Button text restored to `清理`. | `cleaner_preview()`, `cleaner_apply()` |
| `导出实例` | `export_modpack(CONFIG.default_instance or "default")` (task), toast `开始导出`/`实例 {name} → exports/` | `export_modpack(name)` |
| `全局 Mod` | opens `GlobalModsDialog(backend)` (not in this part) | — |
| `保存当前主题` | `InputDialog(保存主题包, 主题包名称, text=我的主题)` → `save_theme(name)`; toast `已保存`/`主题包「{name}」已保存`; error `保存失败` | `save_theme` |
| `加载主题` | `list_themes()`; empty → info `提示`/`没有已保存的主题包`; `ComboDialog(加载主题, 选择要加载的主题包, names)` → `load_theme(name)`; `refresh_from_config()`; toast `已加载`/`主题包「{name}」已应用`; `apply_theme()`; error `加载失败` | `list_themes`, `load_theme` |
| `删除主题` | same list/empty check; `ComboDialog(删除主题, 选择要删除的主题包)` → `delete_theme(name)`; toast `已删除`/`主题包「{name}」已删除`; error `删除失败` | `list_themes`, `delete_theme` |
| `检测并迁移` | Button `检测中…`; async probe: `detect_official_launcher()`; if true → `{"dir": official_launcher_dir(), "versions": scan_official_versions()}`. None → info `提示`/`未检测到官方启动器数据目录`. Else confirm `官方启动器迁移` / `发现官方启动器目录: {dir}\n\n发现 {n} 个版本\n\n要导入吗？` → `migrate_official_launcher()` → toast `迁移中`/`导入任务已启动: {task_id}`; error `迁移失败`; probe error `检测失败`. | `detect_official_launcher`, `official_launcher_dir`, `scan_official_versions`, `migrate_official_launcher()` |
| `查看推荐` | Button `检测中…`; `call_async(get_smart_recommendation)`; `MessageBox(智能推荐, "你的系统: {total_ram_gb} GB 内存 / {cpu_count} 核 CPU\n\n推荐内存: {memory_mb} MB\n\n可以到「性能」设置区调整。", yes 应用推荐, cancel 关闭)`; yes → memory spin = rec, toast `已应用`/`内存已设为 {mem} MB，保存设置后生效`; error `检测失败`. | `get_smart_recommendation()` |

`collect()` keys submitted on save: `share_libraries, share_assets, download_threads, download_source, community_source, use_system_proxy, default_memory_mb, default_resolution, ms_client_id, curseforge_api_key, ai_mode, ai_gateway_url, ai_base_url, ai_api_key, ai_model ("deepseek-v4-flash" if blank), feedback_url, feedback_heartbeat, feedback_consent, ui_fly_animation, ui_fly_duration_ms, ui_dark, theme_color, ui_background, default_isolation, default_jvm_args, update_url, launcher_visibility, gc_preset, download_limit_kbps, auto_check_update, ui_motion, homepage_mode, custom_homepage, window_mode, allow_multi_instance, language`.

### 6.4 `layout_settings.py` dialogs (write CONFIG directly, not via backend)

**SidebarEditorDialog** (`MessageBoxBase`, min width 460; yes `确定`, cancel `取消`)
- Title `自定义侧栏`; hint `调整顶部导航的顺序与显示项，以及侧栏宽度。`
- Rows for top-level keys in order (`_TOP_KEYS = ("launch","download","ai","more","tasks")`, titles `启动`,`下载`,`AI 助手`,`更多`,`下载任务`): up/down `ToolButton`s (disabled at ends) + `CheckBox` (visible = not in `ui_nav_hidden`). Initial order = `ui_nav_order` filtered to top keys, then missing appended.
- Section `固定到侧栏的子页` + hint `把分区横条里的子页拖到侧栏即可固定；此处可调整顺序或取消固定。`; rows for `ui_nav_pinned` keys: up/down, title via `sub_title(key)`, button `取消固定`; empty caption `暂无固定项`.
- `侧栏宽度` SpinBox 140–320 suffix ` px`, initial `ui_sidebar_width` or 188 (clamped).
- Button `恢复默认侧栏`: order = default, all visible, pinned = [], width 188.
- Accept: ensure ≥1 visible (re-checks first); merges new top order into the current mixed nav sequence keeping pinned sub keys' relative positions; writes `ui_nav_order` (list), `ui_nav_hidden` (sorted list), `ui_sidebar_width` (int), `ui_nav_pinned` (list or None); `CONFIG.save()`; `window._rebuild_sidebar()`.

**SectionEditorDialog** (min width 560)
- Title `自定义分区内容`; hint `在「下载」和「更多」之间移动子页，或调整分区内顺序；每栏至少保留一项。`
- Two sections `下载栏` / `更多栏` with rows: up/down, `sub_title(key)`, pin toggle button (`已固定到侧栏` / `固定到侧栏`), move button `移到「下载」`/`移到「更多」` (disabled when only 1 item left in the section).
- Defaults `_SUB_DEFAULT_MEMBERS`: download = `version, mod, modpack, datapack, resource, shader, world, java`; more = `instance, mods, account, multiplayer, servers, playtime, feedback, settings`. Sub titles: version `原版游戏`, mod `Mod`, modpack `整合包`, datapack `数据包`, resource `资源包`, shader `光影包`, world `世界`, java `Java`, instance `实例`, mods `模组`, account `账号`, multiplayer `联机`, servers `服务器`, playtime `时长`, feedback `反馈`, settings `设置`.
- Button `恢复默认分区`.
- Accept: members minus pinned; if any section empty → warning toast `分区不能为空`/`每栏至少保留一个子页` and stay open. Writes `ui_section_members = {"download": [...], "more": [...]}`, `ui_nav_pinned` (existing order preserved, new appended, or None); save; `window._rebuild_sections()`, `_rebuild_sidebar()`.

**Layout profiles (`layout_model.py`)** — config keys `ui_layout` (active doc or None=default), `ui_layouts` ({name: doc}), `ui_layout_profile` (active name, "" = default). Doc JSON: `{"version": 1, "grid": int(px, 0=free), "items": [{"id","type","x","y","w","h" (0..1 ratios, 5 dp),"z","hidden","settings":{}}]}`. Card types + min px sizes: banner (340,150), config (330,300), log (260,180), news (220,180), quick (220,150), notes (180,130), playtime (220,130), tasks (220,130). Default doc: banner (0,0,1,0.26), config (0,0.275,0.315,0.725), log (0.325,0.275,0.41,0.725), news (0.745,0.275,0.255,0.725), grid 8. Import drops unknown types and rejects files without `items` list.

### 6.5 `get_settings()` return shape (exact keys)
`share_libraries, share_assets, download_threads, default_memory_mb, default_resolution [w,h], ms_client_id, curseforge_api_key, ai_mode, ai_gateway_url, ai_base_url, ai_api_key, ai_model, ai_confirm_writes, ai_permission_mode, download_source, community_source, use_system_proxy, feedback_url, feedback_heartbeat, feedback_consent (bool; True only if config is True), ui_fly_animation, ui_motion, ui_fly_duration_ms, default_isolation, default_jvm_args, default_priority, update_url, theme_color, ui_dark, ui_background, global_mods_dir, launcher_visibility, gc_preset, download_limit_kbps, auto_check_update, custom_homepage, homepage_mode, window_mode, skip_assets, allow_multi_instance, first_run, show_hidden_versions, offline_skin, default_java, instances_dir (raw), game_dir (absolute), root (launcher ROOT)`.

`save_settings(data)`: partial-update semantics (missing keys keep CONFIG); special: `ms_client_id` empty keeps old; `ai_permission_mode` coerced to `standard|full`; `first_run` explicit only; after write: `invalidate_probe()`, `apply_proxy_policy()`, `warmup_async()`; emits `theme_changed` if any of `ui_dark`/`theme_color`/`ui_background` present. Also accepts `show_hidden_versions`, `instances_dir`, `feedback_url`, `feedback_heartbeat`, `feedback_consent`, `default_priority`, `global_mods_dir`, `skip_assets`, `offline_skin`, `default_java`.

Other shapes:
- `set_game_dir(path) -> str` (writes `instances_dir`, emits `ui_changed`).
- `test_ai_connection(settings) -> str` e.g. `公益接口正常，模型 deepseek-v4-flash`, `NewAPI 正常，可用模型 N 个，例如 …`, `已连通`; raises `AIClientError` (`请在设置里填写自定义 NewAPI 地址（到 /v1 为止）`, `请在设置里填写 NewAPI 令牌`, HTTP errors).
- `check_update() -> {"ok", "current", "latest", "has_update", "message", "notes", "url", "sha256"}`; message `已是最新版本` / `发现 {v}` / `检查更新失败: …` / `更新清单缺少有效 SHA-256，已拒绝自动更新`.
- `start_self_update() -> task_id` (title `更新启动器`; downloads to `cache/PyMCL-<ver>.bin`, writes `pymcl-apply-update.bat`, message = bat path or `当前不是打包版，请用新压缩包覆盖源码目录。`).
- `cleaner_preview() -> {"unused_libraries": [{"path","bytes"}], "parts": [...], "cache": [...], "bytes": int, "count": int}`; `cleaner_apply(kinds=None) -> {"removed": int, "bytes": int}`.
- `export_modpack(instance, dest="") -> task_id` (title `导出整合包 {instance}`, output `exports/<inst>.mrpack`).
- `list_themes() -> [{"name","file","theme_color","ui_dark"}]`; `save_theme(name) -> theme dict {name, theme_color, ui_dark, ui_background, window_mode, custom_homepage, homepage_mode}`; `load_theme(name) -> dict` (updates CONFIG those keys, emits `theme_changed`, `ui_changed`; raises `主题包不存在: {name}`); `delete_theme(name)`; `import_theme(path) -> name`; `export_theme(name, dest) -> path` (last two unused by UI).
- `detect_official_launcher() -> bool`; `official_launcher_dir() -> str`; `scan_official_versions() -> [str]`; `migrate_official_launcher(instance="default") -> task_id` (title `导入官方启动器`; returns `已导入 N 个版本` / `无版本可导入`).
- `get_smart_recommendation() -> {"memory_mb", "java_major", "window_width", "window_height", "gc_preset", "cpu_count", "total_ram_gb"}`.
- `get_language() -> str`; `available_languages() -> {"zh_CN": "简体中文", "en": "English"}`.

---

## 7. `app/pages/ai_page.py` — AiPage (`objectName="aiPage"`)

### 7.1 Layout
Horizontal: **left sidebar** (200 px, card bg, right border): primary button (ADD) `新对话` (32 px), `QListWidget` of chats (title text, `UserRole` = chat id), transparent button (DELETE) `删除对话`.
**Main**: header row: title `AI 助手` (16 pt demi-bold), status caption (`公益接口 · deepseek-v4-flash` or `自定义 · {ai_model}`), stretch, buttons `停止` (CLOSE, disabled idle) and transparent `重试` (SYNC, disabled unless idle and history non-empty).
Chips row (28 px buttons, send text on click): `下一款游戏 1.20.1 Fabric`, `装钠和光影`, `启动闪退了帮我看`.
Scroll area with vertical chat layout (bottom stretch). Input box card: `ChatInput` (PlainTextEdit, 48→140 px auto-grow, placeholder `问我要下什么、哪报错、模组怎么配…  Enter 发送，Shift+Enter 换行`), permission `ComboBox` (112 px, tooltip `AI 权限等级`; items `标准`, `完全访问`, `免确认`), gear `TransparentToolButton` (tooltip `点击管理 AI 权限`), primary `发送` (34 px).

Message widgets:
- `Bubble(role, text)`: header caption `我` (user) / `助手` / `出错`; non-user bubbles have transparent `复制` button (copies plain text; toast `已复制`, 1200). Body: user → plain text; assistant while streaming (`live=True`) → plain; final → rich HTML via `_md` (fenced ```` ``` ```` → `<pre>` monospace block, `` `code` `` → `<code>`, `**b**` → `<b>`, `\n` → `<br>`, all HTML-escaped; empty → `…`). Max width 640; user bubbles right-aligned, others left. Colours: user bg `#E8F6EF`/dark `#1E3A2E`; error bg `#FDECEC`/`#3A1E1E` border `#E07A7A`, header `#C23A3A`; assistant `Theme.card`.
- `ToolLine(text)`: small hover-bg card with green caption + hidden `ProgressBar` (0–100) shown when bound to a task id.
- `ConfirmCard(label, detail)`: yellow card; `需要你点一下确认：` + label + optional read-only detail box (≤160 px); buttons primary `确认执行`, `取消`. Disabled after click.
- `AskCard(questions, title)`: green card; optional title; one `_AskBlock` per question; buttons primary `确定`, `跳过`. Block: prompt (+ `（可多选）` when multi); options as `RadioButton`s (single) or `CheckBox`es (multi); hidden `LineEdit` (placeholder `选「其他」时在这里填`) shown when option id `other` is selected.

### 7.2 Controls

| Control | Does | Backend / store | Result |
|---|---|---|---|
| `新对话` | `_stop(wait=True)`; `chat_store.new_chat(store)`; load; refresh list | store file | — |
| `删除对话` | `_stop(wait=True)`; `chat_store.delete_chat(store, active_id)`; load; refresh | store | Deleting last chat creates a fresh blank one. |
| Chat list selection | Switch active chat | `chat_store.set_active` | Ignored while a worker is running. |
| Chips | `_send_text(chip)` | | |
| `发送` / Enter (Shift+Enter newline; IME preedit respected) | Send | see 7.3 | Empty → ignore. If a worker is busy → queue: clear input, echo user bubble, info toast `已排队`/`这条会在当前回复结束后发出` (1800); queued item sent (`echo=False`) 30 ms after current finishes. |
| `停止` / **Esc** shortcut | `worker.cancel()` (sets flag, aborts HTTP, answers pending confirm False and ask None) | | Results in `failed("已停止")`. |
| `重试` | Re-send last non-empty user message (`_send(last)`, echoes a new user bubble) | | Only when idle. |
| Permission combo | index 0 → `{"ai_confirm_writes": True, "ai_permission_mode": "standard"}`, 1 → `{True, "full"}`, 2 → `{"ai_confirm_writes": False}` | `save_settings(data)` | error toast `保存失败`; then refresh combo from settings. Level derivation: `!ai_confirm_writes` → `noconfirm`; `ai_permission_mode == "full"` → `full`; else `standard`. |
| Gear | `PermissionDialog` | | Title `权限管理`, caption `控制 AI 助手改东西前要不要先问你`; `SettingCard(INFO, 变更前确认, 改文件前先问我)` + Switch (`ai_confirm_writes`); `SettingCard(FINGERPRINT, 完全访问, 减少确认次数)` + Combo (`标准`, `完全访问`) (`ai_permission_mode`); tip `关掉「变更前确认」后写操作全部直接执行；「完全访问」仍会在删除实例、删除模组、改配置前询问。`; changes saved immediately via `save_settings`; single button `关闭`. |
| Bubble `复制` | clipboard | | |
| ConfirmCard `确认执行`/`取消` | `worker.answer_confirm(True/False)` | | |
| AskCard `确定` | validate each block (`collect()` None → warning toast `还没选` / prompt, 2200), then `submitted({"answers": {qid: {...}}})` → `worker.answer_ask(payload)`; notes `已选 A、B` appended | | |
| AskCard `跳过` | `worker.answer_ask(None)` | | |

### 7.3 Send flow & event protocol (Python UI: `AgentThread`)
`_send(text)`: echo user bubble; reset stream/notes/tool lines; add assistant bubble `正在想…`; `settings = backend.get_settings()`; `backend._ui_launch = _launch_prefs()`; `AgentThread(backend, settings, chat_store.api_messages(history[-24:]), text)`; busy state (send disabled, stop enabled).

`_launch_prefs()` (launch context read from LaunchPage widgets): `{"instance", "version", "account", "username" (default "Player"), "memory_mb", "width", "height", "java"}` — used by the `launch_game` tool when args omitted. Bridge equivalent: `ai_send(text, chat_id, launch={...})`.

`run_agent(backend, settings, history, user_text, on_delta, on_status, confirm_fn, ask_fn, cancelled, http_cancel)` callbacks → thread signals → UI:

| Callback / signal | Payload | UI handling |
|---|---|---|
| `on_delta(text)` → `delta(str)` | text chunk | Append to `_stream`; flush to assistant bubble (plain, live) at most every 33 ms; autoscroll (50 ms debounce). |
| `on_status("think", {"after_tools": bool})` | | If no stream text yet: bubble text `搜完了，正在整理…` (after_tools) or `正在想…`. |
| `on_status("tool", {"name","args","label"})` | tool about to run | If name == `ask_user`: bubble `请在下面选一下` (if no stream). Else create/update `ToolLine` keyed by tool name with text `准备：{label}`. |
| `on_status("tool_run", {"name","label"})` | | ToolLine `执行中：{label}` |
| `on_status("tool_done", {"name","label","result"[:400],"task_id"?})` | | ToolLine `完成：{label}`; extract `task_id` from payload or JSON `result` (`{"task_id": …, "queued": true}`) → `line.bind_task(tid)` (shows progress bar) and register in `_task_lines`; append label to `_notes`. |
| `on_status("tool_skip", {"name","label"})` | | ToolLine `已跳过：{label}` |
| `confirm_fn(name, args, label)` → `need_confirm(name, args, label)` (blocks worker until answered) | | `ConfirmCard(label, detail)`; detail = `args.content[:4000]` for `write_mod_config`, `删掉后文件找不回来。` for `delete_instance`, else "". |
| `ask_fn(questions, title)` → `need_ask(list, str)` (blocks) | `questions = [{"id","prompt","allow_multiple","options":[{"id","label"}]}]` (normalized: always has `other` option appended; `skip`/`先不选` inserted if <2 options) | `AskCard`; bubble `请在下面选一下`. Answer shape: `{"answers": {qid: {"ids": [...], "labels": [...], "other_text": str}}}` or `None` (skip → tool result `用户取消了选择`). |
| `done(text)` | final assistant text | `_finish(text or stream, ok=True)` |
| `failed(msg)` | error string (`已停止` when cancelled; `AIClientError` text otherwise) | Bubble text = msg (or `接口没返回具体原因`); if msg ∈ {`已停止`,`已取消`} → info toast `已停止`/`可以继续说下一句` (2200) and treated as ok=True (stored as assistant); else error toast `助手出错`/msg (12000), stored as role `error`. |

`_finish(text, ok)`: compose body = text + `\n\n（本轮：note1；note2…）` (max 8 notes) if not already present; set bubble (rich); append `{"role":"user"}` and `{"role": "assistant"|"error"}` to history; `chat_store.upsert_messages(store, active_id, history)` (also auto-titles chat from first user message[:24] and re-sorts by `updated`); refresh list; un-busy; focus input; pop queue.

Task progress inside chat: `backend.progress(task_id, cur, total, msg)` → matching ToolLine `set_progress` (bar %; label = msg before `"  |  "`). `backend.finished(task_id, ok, msg)` → ToolLine `完成：msg` / `失败：msg`, bar 100 on success.

Agent rules relevant to UI: write tools (`WRITE_TOOLS`) require confirm per policy (`ai_confirm_writes` false → never; `full` → only `DANGEROUS_TOOLS = {delete_instance, delete_mod, write_mod_config}`; standard → all). `LONG_TOOLS` (install_*, download_java) and `launch_game` return immediately with `{"task_id", "queued": true}` (not awaited). Search tools (`search_mods`, `search_modpacks`, `search_versions`) are deduped per turn (`tool_skip` label `拦截重复搜索`). Max 10 tool rounds, history trimmed to 24 messages. Tool names: `ask_user, get_launcher_state, list_instances, list_installed_versions, search_versions, search_mods, search_modpacks, list_mods, install_game, install_mod, install_modpack, install_shader, install_resourcepack, install_datapack, create_instance, delete_instance, delete_mod, disable_mod, enable_mod, get_java_list, download_java, launch_game, diagnose_launch, get_latest_log, get_crash_report, scan_mod_conflicts, inspect_mod, list_mod_configs, read_mod_config, write_mod_config`. Confirm labels (`confirm_label`): e.g. `安装游戏 {version} {loader} → {inst}`, `安装模组 {name} → {inst}`, `安装整合包 …`, `安装光影 …`, `安装资源包 …`, `安装数据包 …`, `下载 Java {major}`, `启动 {version|当前版本} @ {inst}`, `新建实例 {name}`, `删除实例 {name}（不可恢复）`, `删除模组 {filename} @ {inst}`, `禁用模组 …`, `启用模组 …`, `改配置 {path} @ {inst}`, default `执行 {name}`; `inst` defaults to `默认实例`.

**Bridge (JSON-RPC) equivalent protocol** (`bridge/api.py`): methods `ai_list_chats() -> store`, `ai_new_chat() -> store`, `ai_delete_chat(chat_id) -> store`, `ai_set_active(chat_id) -> store`, `ai_send(text, chat_id="", launch={}) -> {"ok","started"}` (or `{"ok": False, "message": "上一条还在处理"}`), `ai_stop() -> {"ok"}`, `ai_confirm(ok: bool)`, `ai_answer(result)`. Events: `ai.delta {"text"}` (coalesced ≤33 ms), `ai.status {"kind", ...payload}`, `ai.confirm {"name","args","label"}`, `ai.ask {"questions","title"}`, `ai.done {"text","store"}`, `ai.fail {"text","stopped": bool}`. Notes composition is done server-side in the bridge.

Chat store (`ai_chats.json`): `{"active_id": str, "chats": [{"id": 12-hex, "title": str≤40 (default 新对话), "updated": epoch, "messages": [{"role": "user"|"assistant"|"error", "content"}]}]}`; max 40 chats, 24 messages/chat; `api_messages()` maps `error` → `assistant`.

### 7.4 Welcome / status
Empty chat shows assistant bubble `_WELCOME` (`我是启动器助手。可以帮你下游戏、装模组和整合包、看启动报错、查模组冲突、改常用配置。\n直接说你想做什么就行。写操作我会先让你确认。`) or `_WELCOME_NOCONFIRM` (`…写操作会直接执行，不逐条询问。`) when `ai_confirm_writes` false. `reload()` (navigation) refreshes status caption and permission combo. `restyle()` re-themes all bubbles/cards.

### 7.5 Edge
- Esc stops. Chat switching blocked while running. New/Delete chat waits up to 2.5 s for worker stop.
- Only last 24 history messages sent to model; full history kept locally (but store also trims to 24).
- Settings keys used: `ai_mode, ai_model, ai_confirm_writes, ai_permission_mode` (+ all `ai_*` via `get_settings()` passed to agent).

---

## 8. `app/pages/tasks_page.py` — TasksPage (`objectName="tasksPage"`) & DownloadDock

### 8.1 TasksPage layout
Header: title `下载任务`, caption `下载板块内所有安装任务的实时进度；整合包安装会自动展开详细日志`; right button (BROOM) `清除已完成` (disabled until something finished). Scroll list of `TaskCard`s; `EmptyState(DOWNLOAD, "暂无任务 —— 去下载板块里的版本 / 整合包 / 模组 / 光影 / 资源包 / Java 发起")`.

**TaskCard(task_id, title)**: min height 96. Left `IconTile(letter, color, 46)` where letter = title with `安装`/`下载` stripped (or `T`), icon/colour by title prefix (`_TASK_ICONS`, compared via `tr(prefix)`): `安装游戏` GAME `#4C8BF5`; `安装整合包` FOLDER `#7C5CD6`; `安装模组` TAG `#2FA36B`; `安装光影` BRIGHTNESS `#E8862E`; `安装资源包` PHOTO `#2E9FB8`; `下载 Java` CODE `#D95568`; `启动游戏` PLAY `#D95568`; `微软登录` PEOPLE `#8A6FBD`; default DOWNLOAD `#4C8BF5`. Top row: bold title, toggle log `TransparentToolButton` (CARE_UP/DOWN, tooltip `收起日志`/`显示日志`), cancel `TransparentToolButton` (CLOSE, tooltip `取消任务`). `SmoothProgressBar` 0–100. Status row: status caption (initial `排队中…`) + right-aligned speed caption. Log `PlainTextEdit` (read-only, 240 px, max 2500 blocks, placeholder `安装过程的详细日志会显示在这里`), expanded by default only if `整合包` in title.

### 8.2 Controls

| Control | Does | Backend |
|---|---|---|
| Card toggle | show/hide log | — |
| Card cancel | `cancel_task(task_id)`; status `正在取消…`; button disabled | `cancel_task` |
| `清除已完成` | remove all finished cards; disable button; show empty state if none left | — |

No explicit "retry" exists on this page (retry of failed installs is done from the originating page); crash reports are shown by LaunchPage (see §9), not here.

### 8.3 Signals
- `task_added(task_id, title)`: only if `BackendAPI.is_download_title(title)` (i.e. title does NOT start with `启动游戏`, `微软登录`, `皮肤站登录`) → hide empty, add card.
- `progress(task_id, cur, total, msg)`: `set_progress`: bar = `cur*100/total` if total>0; split `msg` on `"  |  "` → status (or `处理中…`) and speed.
- `log(task_id, text)`: append.
- `finished(task_id, ok, msg)`: cancel disabled; ok → bar 100, status `✔ {msg}`; else `✘ {msg}`; speed cleared; msg appended to log; failed & collapsed → auto-expand log; enable `清除已完成`.
- Side badge: `task_count_changed(n)` (count of running download-title tasks) → badge `n` / `99+`, hidden when 0, pulses on change.

### 8.4 DownloadDock (floating card at bottom of content area, 560 px default; window resizes to `min(640, max(420, width-40))`)
Header row: bold `下载任务` (becomes `下载任务（{n}）`), status caption (initial `就绪`), speed caption, toggle button. `SmoothProgressBar`. Hidden log `PlainTextEdit` (220 px). Behaviour:
- `task_added` (download titles only): register; title count; status = title; bar 0; if first active → clear log; append `—— {title} ——`; auto-expand if `整合包` in title; ask window `_place_download_dock()` (slides in 280 ms from +28 px).
- `progress`: same split; status = status or title or `处理中…`.
- `log`: append if task active or current.
- `finished`: pop; append msg; if none left: title reset, status `✔ 全部完成` (success) or msg / `已结束`, bar 100 on success, dock hides (slide 200 ms). Else current = next active, status = its title.
- Window hides the dock on pages `settings`, `instance`, `tasks`, `feedback`.

### 8.5 Progress/speed formatting (backend side)
`BackendWorker._progress` throttles to ≥80 ms and ≥0.5 % change (unless done); values >2e9 rescaled to basis 10000. `_dm` logs a line whenever the status prefix (before `"  |  "`) changes. Finished message: task return string or `任务完成`; cancelled → `已取消`; exception → `str(exc)` (also logged `[错误] …`).
Main window toasts on `finished` (`_notify_task`): success `title`/msg (TOP_RIGHT 3000); failure (not `已取消`) error `title`/msg (5000); skipped for `启动游戏`/`微软登录` titles.

---

## 9. `app/pages/crash_dialog.py` — CrashDialog (+ `show_launcher_error`)

### 9.1 When shown
- LaunchPage on `backend.crash(task_id, report)` for its launch task → `CrashDialog(report, window, backend)`; if `want_relaunch` → select report `instance`/`version` in launch combos and relaunch.
- LaunchPage on launch task `finished(success=False)` with no crash shown and not `已取消` → `CrashDialog({"title": 启动失败, "headline": 启动中止, "detail": message, "help": 这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。, "instance", "version"})`.
- `show_launcher_error(parent, kind, text, log_file)` for uncaught launcher exceptions: title `启动器出现错误` (or `启动器后台线程出错` if kind == "thread"), headline `未捕获异常已写入日志`, detail = last 8000 chars, help `完整日志：{log_file}` or default footer, `direct_file`/`files`/`output_tail` set, no actions.

### 9.2 Layout (modal QDialog, min 560×420, default 640×520)
Title = `title` arg / `report.title` / `Minecraft 出现错误`. `SubtitleLabel` title; optional `headline` body label (if differs from title); read-only `PlainTextEdit` with `detail`; caption `report.help` or `HELP_FOOTER` (`如果要寻求帮助，请把错误报告文件发给对方，而不是发送这个窗口的照片或者截图。`); if `actions`: bold `建议操作` + one `PushButton(tr(action.label or id or "修复"))` per action. Bottom row (right-aligned): `重新启动`, `查看输出`, `导出错误报告`, `发送给开发者`, primary `确定`.
Visibility: `重新启动` only if report has `instance` and `version`; `查看输出` only if `direct_file` or `output_tail`; `导出错误报告` only if report non-empty; `发送给开发者` always.

### 9.3 Controls

| Button | Does | Backend |
|---|---|---|
| Action button | `apply_crash_action(action, report)`; button disabled during; result `{ok, message, task_id?}`: ok → success toast `已处理`/message (4000), for `disable_mods` button text → `已禁用`; not ok → re-enable + error toast `操作失败`/message (or `失败`); exception → `操作失败`/str. No backend → error `无法执行`/`没有连接到启动器后端`. | `apply_crash_action` |
| `重新启动` | set `want_relaunch = True`, accept | — |
| `查看输出` | if `direct_file` → `open_path`; else write `output_tail`/`detail` to `<ROOT>/游戏崩溃前的输出.txt` and open | — (module fn) |
| `导出错误报告` | `export_report(report)` → zip `<ROOT>/错误报告-YYYY-MM-DD_HH.MM.SS.zip` (contains `分析结论.txt`, `游戏崩溃前的输出.txt`, copied log files, secrets filtered) then open | — (module fn; backend equivalent `export_crash_report(task_id, dest)`) |
| `发送给开发者` | consent check (`prompt_feedback_consent`; refused → warning `未同意`/`不同意上传则不会发送`); button `发送中…`; `submit_crash_feedback(report)` async; ok → button `已发送`, toast `已发给开发者`/`反馈中心会实时显示这条崩溃和本机配置`; error → restore, toast `发送失败`. | `submit_crash_feedback(report, extra="")` |
| `确定` | accept | |

### 9.4 Data shapes
Crash report (`analyze_launch`): `is_crash, title ("Minecraft 出现错误"|"游戏已退出"), headline, summary, detail, help, reasons [{"code","title","extra": [..]}], exit_code, exit_hint, direct_file, files [str], instance, version, output_tail (≤8000), log_mc, log_crash, log_hs, has_latest, has_crash, has_hs_err, actions [..]`.
Actions (`build_actions`): `{"id","label","codes":[..], ...}` with ids/labels: `disable_mods` (`禁用嫌疑 Mod` / `禁用重复 Mod`, `mods: [filenames]`), `open_mods_folder` (`打开 Mods 文件夹排查` / `打开 Mods 文件夹`), `bump_memory` (`提高默认内存`, `memory_mb`), `need_java` (`下载 Java {major}`, `major`), `repair_version` (`修复该版本文件`, `version`, `instance`), `open_gpu_hint` (`查看显卡驱动提示`), `reset_jvm_args` (`清空自定义 JVM 参数`), `open_crash_file` (`打开崩溃报告` / `打开 hs_err 日志`, `path`).
`apply_crash_action(action, report) -> {"ok": bool, "message": str, "task_id"?: str}`: `disable_mods` → `已禁用 N 个 Mod`(+`；部分失败：…`) / `未能禁用：…`; `repair_version` → starts task `修复 {version}` (`已开始修复 {v}`) or `报告里没有版本号，无法修复`; `need_java` → `download_java(major)` (`已开始下载 Java {n}`); `bump_memory` → sets `memory_mb` (clamped 1024–32768) `默认内存已设为 {mb} MB`; `open_mods_folder` → `已打开 Mods 文件夹`; `open_crash_file` → `已打开崩溃报告` / `没有可打开的崩溃文件` / `文件不存在：…`; `open_gpu_hint` → tip text; `reset_jvm_args` → clears global + version jvm args `已清空自定义 JVM 参数`; unknown → `未知动作: …`.
Other backend crash helpers: `get_crash(task_id="") -> dict` (latest if empty), `export_crash_report(task_id="", dest="") -> path`, `open_crash_file(path="", task_id="") -> path`, `submit_crash_report(task_id="") -> message`.
`submit_crash_feedback(report, extra)` posts category `crash`, title = headline/title/summary/`游戏崩溃`, body = extra + summary + detail/output_tail[:8000], `crash: {headline, summary, title, help, direct_file}`, with sysinfo.

---

## 10. `app/pages/first_run.py` — FirstRunDialog

Shown at boot when `first_run` is true (`MainWindow._boot_extras`). `MessageBoxBase`, min width 480; yes `开始使用`, cancel `以后再说`.
Fields:
- Title `欢迎使用 PyMCL`; hint `先选好游戏目录和下载源。这些以后都能在设置里改。`
- `游戏 / 实例目录`: LineEdit (initial `settings.game_dir` or `CONFIG.instances_dir`) + `浏览` (`getExistingDirectory(选择游戏目录)`).
- `文件下载源`: Combo `自动（官方慢则 BMCLAPI）`=auto, `仅官方`=official, `仅 BMCLAPI`=bmclapi.
- `默认内存 (MB)`: SpinBox 512–32768, initial `CONFIG.memory_mb` or 4096.
- `新版本默认隔离`: Combo `关闭（共用实例目录）`=none, `隔离存档`=saves, `隔离 Mod 与配置`=mods, `隔离全部`=all.
Accept → `apply()`: `data = get_settings(); data.update({download_source, default_memory_mb, default_isolation, first_run: False}); save_settings(data)`; then `set_game_dir(path)` if non-empty (errors swallowed). Cancel → main window still saves `first_run = False`. After the dialog the consent prompt (§5.4) runs, then background `check_update` if `auto_check_update` (toast `发现更新`/message or `到设置里安装`, TOP_RIGHT 5000).

---

## 11. `app/motion.py`, `app/fly_anim.py`, `app/motion_prefs.py` — animations

`motion_prefs.ui_motion_ok()` → `CONFIG.get("ui_motion", True)` (read on every call → toggling applies live once saved).

Gated by `ui_motion` (`motion.py`):
- `fade(widget, start=0, end=1, ms=180)` opacity, OutCubic (skipped if widget hidden).
- `slide_in(widget, dy=-10, ms=200)` slide from above + fade (floating toolbars).
- `tween(setter, start, end, ms=240)` generic value tween (height expand, positions).
- `pop(widget, scale=1.35, ms=260)` scale pulse OutBack (badge count change); skipped if one already running.
- `SmoothProgressBar`: `setValue` animates drawn value over 240 ms OutCubic; if an animation is running, jumps to target immediately (dense updates). Used by TaskCard, DownloadDock.

`fly_anim.py` (gated by `ui_fly_animation` and duration `ui_fly_duration_ms`, both read in `MainWindow.fly_to_tasks(source, text, color)`):
- `fly_to(window, source, letter, color, target=..., duration=620)`: 48 px `FlyBall` (rounded square 44→14 px, letter drawn until t<0.45, fades out after t≥0.75) follows a quadratic Bézier from source centre to the sidebar `tasks` button centre (arc height `clamp(dist*0.35, 48, 150)`, clamped inside window), InOutCubic. At most 2 concurrent flights (older ones finished early). On landing: `Ripple` (ring 6→24 px radius, alpha .55→0, 420 ms OutCubic) and `pulse_widget(badge or target, 220 ms)` (geometry scale 1→1.12→1). Letter = first char of `text` upper-cased (or `↓`); colour = given or `pick_color(text)` from palette.
- Callers in this part: MultiplayerPage (`联` on prepare, `进` on enter-world). (Install pages use it for downloads.)
- Not gated by `ui_motion`: Ripple/pulse (only via fly), DownloadDock slide (`_anim_pos`, 280/200 ms OutCubic).

---

## 12. `mclauncher/i18n.py`

- `LANGUAGES = {"zh_CN": "简体中文", "en": "English"}`; locale files `mclauncher/locales/<code>.json` (present: `zh_CN.json`, `en.json`) — flat `{source_chinese_string: translation}`. `available_languages()` = LANGUAGES ∪ any extra locale file codes (display = code).
- Keys are the Chinese source text. `_(key, lang=None, default=None)`: lookup in `lang` table; for `zh_CN`/`en` no cross-fallback (missing → key itself); other languages fall back to `en` then key. `tr = _` (UI uses `tr`).
- `set_language(lang)`: normalises `-`→`_`, unknown → `zh_CN`; sets current; **writes `CONFIG["language"]` and saves**. `init_language()` loads from config at startup. `current_language()`.
- `add_translations(lang, mapping)`, `save_translations(lang)` (runtime extension).
- Backend: `get_language()`, `set_language(lang)` (+ `ui_changed`), `available_languages()`, `translate(key, lang="")`.
- Language switch: all UI strings are evaluated at widget construction, so a change only fully applies after restart; settings page offers immediate restart (§6.3). Task titles are also translated at creation (`tr("微软登录")` etc.), so title-prefix matching (`is_download_title`, `_TASK_ICONS`) is done via `tr()` at compare time.

---

## 13. Consolidated BackendAPI methods used (this part)

Task/infra: `call_async(fn, on_ok, on_err)`, `cancel_task(task_id)`, `task_title(task_id)`, signals `task_added, progress, log, finished, crash, login_code, login_status, ui_changed, theme_changed, task_count_changed, game_started, game_exited`; static `is_download_title(title)`.

Account: `authlib_presets()`, `get_account_rows()`, `remove_account(name)`, `set_active_account(name)`, `add_offline_account(name, skin)`, `start_microsoft_login()`, `start_authlib_login(api, username, password)`, `start_nide8_login(server_id, username, password)`.

Multiplayer: `lan_hint()`, `local_ips()` (available, unused by page), `terracotta_snapshot()`, `terracotta_prepare()`, `terracotta_host()`, `terracotta_join(room)`, `terracotta_idle()`, `terracotta_allow_firewall()`, `terracotta_open_firewall_settings()`, `terracotta_enter_world()`, `terracotta_direct_connect(address)`, `terracotta_shutdown()` (window close).

Servers: `get_instances()`, `list_servers(instance)`, `add_server(instance, name, ip, port)`, `update_server(instance, index, name=, ip=, port=)`, `delete_server(instance, index)`, `import_servers(instance, text)`, `export_servers(instance)`.

Playtime: `get_playtime(instance)`, `get_all_playtime()`, `format_playtime(seconds)`, `clear_playtime(instance)`.

Feedback: `collect_sysinfo(force=, scan_system_java=)`, `sysinfo_text(info)`, `submit_feedback(category=, title=, body=, contact=, include_sysinfo=)`, `feedback_history()`, `help_articles()`, `help_article(id)`, `submit_crash_feedback(report)`.

Settings: `get_settings()`, `get_setting(key)`, `save_settings(dict)`, `set_game_dir(path)`, `available_languages()`, `get_language()`, `test_ai_connection(settings)`, `check_update()`, `start_self_update()`, `cleaner_preview()`, `cleaner_apply()`, `export_modpack(instance)`, `list_themes()`, `save_theme(name)`, `load_theme(name)`, `delete_theme(name)`, `detect_official_launcher()`, `official_launcher_dir()`, `scan_official_versions()`, `migrate_official_launcher()`, `get_smart_recommendation()`.

AI: `get_settings()`, `save_settings({ai_confirm_writes, ai_permission_mode})`, attribute `_ui_launch` (launch context), plus agent-internal calls (`get_instances`, `get_java_list(False)`, `get_installed_versions`, `get_version_list`, `fetch_version_list`, `search_mods`, `search_modpacks`, `install_*`, `download_java`, `launch_game`, `wait_task`, `create/delete_instance`, `delete_mod`, `get_accounts`, `_instance`).

Crash: `apply_crash_action(action, report)`, `submit_crash_feedback(report)` (+ available `get_crash`, `export_crash_report`, `open_crash_file`, `submit_crash_report`).

First run: `get_settings()`, `save_settings(data)`, `set_game_dir(path)`.

**Bridge gaps observed** (`bridge/api.py` lacks vs Python UI): `set_game_dir`, `terracotta_enter_world`, `terracotta_direct_connect`, `local_ips`, `skin_urls`; `add_offline_account(username)` has no `skin` parameter; `test_ai_connection()` takes no settings argument (cannot test unsaved values). `layout_model`/`layout_settings` write CONFIG directly (`ui_layout*`, `ui_nav_*`, `ui_section_members`, `ui_sidebar_width`) — no backend method exists for them.

---

## 14. Config / settings keys touched by these pages (with `DEFAULT_CONFIG` defaults)

| CONFIG key | Default | Read/written by |
|---|---|---|
| `instances_dir` | `".minecraft"` | settings/first-run via `set_game_dir`; exposed as `game_dir` |
| `default_instance` | `"default"` | servers page (preferred instance), settings export, playtime default |
| `shared_libraries` / `shared_assets` | False / False | settings (`share_libraries`/`share_assets`) |
| `memory_mb` | 4096 | settings (`default_memory_mb`), first run, crash `bump_memory` |
| `download_threads` | 8 | settings |
| `width` / `height` | 854 / 480 | settings (`default_resolution`) |
| `microsoft_client_id` | `"00000000402b5328"` | settings (`ms_client_id`), MS login |
| `curseforge_api_key` | HMCL key | settings |
| `download_source` | `"auto"` | settings, first run |
| `community_source` | `"auto"` | settings |
| `use_system_proxy` | True | settings |
| `ai_mode` | `"public"` | settings, AI status |
| `ai_gateway_url` / `ai_base_url` / `ai_api_key` | "" | settings |
| `ai_model` | `"deepseek-v4-flash"` | settings, AI status |
| `ai_confirm_writes` | True | AI page combo/dialog, welcome text, agent policy |
| `ai_permission_mode` | `"standard"` | AI page combo/dialog |
| `terracotta_extra_nodes` | one glavo node | terracotta (not UI) |
| `feedback_url` | "" | settings |
| `feedback_heartbeat` | True | settings |
| `feedback_consent` | None | settings switch, consent prompt, feedback/crash send |
| `device_id` | "" | feedback module |
| `default_isolation` | `"none"` | settings, first run |
| `default_jvm_args` | "" | settings, crash `reset_jvm_args` |
| `default_priority` | `"normal"` | get_settings only |
| `update_url` | `"https://pymcl.dev/update.json"` | settings |
| `theme_color` | `"#2E9B6B"` | settings (live), themes |
| `ui_dark` | False | settings (live), themes |
| `ui_background` | "" | settings (live), themes |
| `ui_fly_animation` | True | settings; `fly_to_tasks` |
| `ui_fly_duration_ms` | 620 | settings; `fly_to_tasks` |
| `ui_motion` | True | settings; `motion_prefs` |
| `ui_layout` | None | layout profiles |
| `ui_layouts` | {} | layout profiles |
| `ui_layout_profile` | "" | layout profiles |
| `ui_nav_order` | [] | SidebarEditorDialog |
| `ui_nav_hidden` | [] | SidebarEditorDialog |
| `ui_nav_pinned` | [] | Sidebar/Section editors |
| `ui_section_members` | {} | SectionEditorDialog |
| `ui_sidebar_width` | 0 (UI default 188) | SidebarEditorDialog |
| `default_java` | "" | get_settings only |
| `global_mods_dir` | "" | get_settings only |
| `launcher_visibility` | `"keep"` | settings; main window |
| `gc_preset` | `"auto"` | settings |
| `download_limit_kbps` | 0 | settings |
| `auto_check_update` | True | settings; boot |
| `custom_homepage` | "" | settings, themes |
| `homepage_mode` | `"news"` | settings, themes |
| `window_mode` | `"window"` | settings, themes |
| `skip_assets` | False | get_settings only |
| `first_run` | True | first-run dialog / boot |
| `show_hidden_versions` | False | get_settings only |
| `catalog_favorites` | [] | (catalog, not this part) |
| `offline_skin` | `"default"` | offline account default skin |
| `allow_multi_instance` | False | settings; launch check |
| `language` | `"zh_CN"` | settings via `i18n.set_language` |

Non-config persisted files used here: `accounts.json` (accounts), `playtime.json`, `feedback_history.json`, `device_id`, `ai_chats.json`, `themes/*.json`, `terracotta/` (kernel + `allow-firewall.bat`), per-instance `servers.dat` + `servers.json`, `错误报告-*.zip`, `游戏崩溃前的输出.txt`.

I'm noting the bridge is missing several functions like set_game_dir, terracotta world entry/connect, local IPs, skin URLs, and AI connection testing with settings. Now I have enough to write the exhaustive markdown output, structuring it page by page: Account, Multiplayer, Servers, Playtime, Feedback, and more.

I still need to cover Settings (with its dialogs and layout model), AI page and protocol, Tasks/DownloadDock, Crash dialog, First run, Motion/fly animation preferences, i18n, a consolidated BackendAPI method list, config keys, and the bridge gaps note. I'm also double-checking edge cases like the account page's default skin display when no accounts exist, and walking through the full Microsoft login flow -- the device code dialog, task lifecycle, success/failure InfoBar messages, and the automatic browser opening behavior.

Comparing login flows: the skin-station login task doesn't count as a download title so it's hidden from the Tasks page, but the Nide8 login oddly does qualify as a download title, meaning it shows up in the Tasks page, dock, and badge count -- worth flagging as an inconsistency. I'm also mapping out which settings apply immediately versus which require hitting "Save," including dark mode toggling, theme color, background image, game directory, language (needs restart), motion preferences (read live from config), download thread count (applied at next task), proxy policy, and download source probing.

Continuing to trace live-vs-restart behavior across remaining settings: multi-instance allowance and launcher visibility are checked live at launch time, homepage mode reloads on the launch page, window mode is read at launch, update-checking waits for next startup, and feedback consent plus AI settings both apply immediately since they're read on each call. I'm also noting that save_settings has a quirk where an empty ms_client_id field won't clear the stored value, and that the settings collection sends a fixed set of 35 keys I want to enumerate. Now shifting to fully documenting the AI page's launch preference reader.

Ask answers include ids, labels, and other_text fields, or None to skip. I'm also noting markdown rendering rules (code fences, bold, escaping), the chat storage format with limits on chat/message counts and auto-titling, and the tasks page's icon mapping and download-title exclusions.

I'm figuring out the progress message format combining status and speed, with basis capping and throttling for updates. I'm also covering download dock visibility rules by page and sizing, crash dialog button logic and actions, and first-run setup behavior including settings persistence and memory config handling.

Now I'm mapping out motion settings and which UI effects they gate—fades, slides, tweens, pop animations, and progress bars, versus ripple/pulse effects that bypass the motion toggle. Then I'm working through the i18n system: supported languages, locale file structure, translation lookup and saving, and how language switching requires a restart since strings are evaluated at construction time.

The restart mechanism relaunches the Python process with the same executable and arguments, then exits the current one. Now I'm ready to write out the full detailed markdown response, being careful to get all these details right.