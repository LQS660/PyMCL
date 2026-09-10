# PyMCL Python UI — Feature Inventory, Part 1

Source of truth: `C:\Users\Administrator\Downloads\Compressed\PyMCL-main\wt-opus45\app\…` (read-only; no files modified).

---

## 0. Shared infrastructure every frontend must replicate

### 0.1 `BackendAPI` signals (Qt) → must map to JSON-RPC events/polling

| Signal | Payload | Emitted when |
|---|---|---|
| `task_added(task_id: str, title: str)` | | `start_task()` creates a worker |
| `progress(task_id, current: int, total: int, message: str)` | throttled 80 ms / 0.5 %; huge totals rescaled to `/10000`; `message` may be `"status  |  speed"` (split on `"  |  "`) | any task |
| `log(task_id, text)` | | any task line |
| `finished(task_id, success: bool, message: str)` | `message` = task return string or `"任务完成"`; `"已取消"` on cancel | task end. On success also triggers `ui_changed` |
| `crash(task_id, report: dict)` | report keys used by UI: `instance, version, title, headline, detail, help, summary, is_crash, direct_file, actions…` | launch task raised `GameCrashError` |
| `login_code(code, uri)` / `login_status(text)` | | Microsoft device-code login |
| `ui_changed()` | | any data mutation (`_emit_ui_changed`) and every successful task |
| `theme_changed()` | | `save_settings` with `ui_dark`/`theme_color`/`ui_background`, or `load_theme` |
| `task_count_changed(n: int)` | count of running tasks whose title does **not** start with `启动游戏` / `微软登录` / `皮肤站登录` | task start/finish |
| `game_started()` / `game_exited(code)` | | game process spawned / exited |

### 0.2 Task model
- `start_task(title, fn, …) -> task_id` (format `task-N`). All `install_*`, `download_java`, `repair_version`, `launch_game`, `start_microsoft_login`, `start_mod_updates`, `export_modpack`, `export_launch_script`, `backup_save` return a `task_id` **immediately**; results arrive via signals.
- `cancel_task(task_id)`: sets worker cancel flag; if it's the launch task also kills the game process.
- `task_title(task_id) -> str`.
- `call_async(fn, on_ok, on_err)`: fire-and-forget background call for synchronous methods (search, list_*, fetch_*). Frontends should call the sync RPC asynchronously.
- `_download_task_count()` (private but used by UI for badge init).

### 0.3 Settings access
- `get_setting(key, default)` reads from `get_settings()` (cached on `CONFIG.revision`). Full key list is in §16.
- `get_settings() -> dict`, `save_settings(data)` / `update_settings(data)` — partial-update semantics (missing keys keep current values).
- Several pages **bypass** the backend and read/write `CONFIG` directly (memory/resolution/layout/nav customization/favorites) — listed per page and in §17.

---

## 1. `app/main_window.py` — `MainWindow`

### 1.1 Purpose / layout
Frameless Fluent window, title `"{APP_DISPLAY_NAME} v{APP_VERSION}"`, default size 1180×760, Mica off, background `#FFFFFF` (light) / `#1B1B1B` (dark), accent `#2E9B6B`.
- **Top bar** (`PclTitleBar`, 40 px): brand label "PyMCL" + minimize + close (maximize hidden).
- **Left sidebar** (`PclSideBar`, default 188 px, resizable 140–320): top-level nav items + pinned sub-pages + stretch + divider + "下载任务" + bottom button "编辑布局".
- **Content stack**: `launch`, `download` (section shell), `ai`, `more` (section shell), `tasks`.
- **Floating download dock** (`DownloadDock`) over content bottom-center.
- **Task badge** (red pill) overlaid on the "下载任务" sidebar button.

### 1.2 Navigation structure (static metadata)

Top-level keys `_TOP_KEYS = ("launch","download","ai","more","tasks")`:

| key | icon | title |
|---|---|---|
| launch | PLAY | 启动 |
| download | DOWNLOAD | 下载 |
| ai | CHAT/HELP | AI 助手 |
| more | MORE/MENU | 更多 |
| tasks | CLOUD_DOWNLOAD | 下载任务 |

Sub-pages (default section membership, `_SUB_DEFAULT_MEMBERS`):

| section | key | title | page class |
|---|---|---|---|
| download | version | 原版游戏 | `VersionPage` |
| download | mod | Mod | `ModPage` |
| download | modpack | 整合包 | `ModpackPage` |
| download | datapack | 数据包 | `DatapackPage` |
| download | resource | 资源包 | `ResourcePackPage` |
| download | shader | 光影包 | `ShaderPage` |
| download | world | 世界 | `WorldPage` |
| download | java | Java | `JavaPage` |
| more | instance | 实例 | `InstancePage` |
| more | mods | 模组 | `ModManagerPage` |
| more | account | 账号 | `AccountPage` |
| more | multiplayer | 联机 | `MultiplayerPage` |
| more | servers | 服务器 | `ServerPage` |
| more | playtime | 时长 | `PlaytimePage` |
| more | feedback | 反馈 | `FeedbackPage` |
| more | settings | 设置 | `SettingsPage` |

All sub-pages and the AI page are **lazy-constructed** on first navigation.

### 1.3 Sidebar customization (persisted in CONFIG, not via backend)

| Config key | Meaning | Rules |
|---|---|---|
| `ui_section_members` | `{download: [keys…], more: [keys…]}` | invalid keys dropped, duplicates removed, missing keys appended per default section, pinned keys excluded |
| `ui_nav_pinned` | list of sub-page keys promoted to top-level sidebar items (or `None`) | invalid keys filtered |
| `ui_nav_order` | full mixed sequence of top keys + pinned sub keys | missing top keys appended at end; unlisted pinned keys inserted before `more` (else before `tasks`, else at end) |
| `ui_nav_hidden` | list of top keys to hide | only top keys are hideable |
| `ui_sidebar_width` | int px | accepted only if 140 ≤ w ≤ 320, else 188 |

User actions:

| Action | Trigger | Effect |
|---|---|---|
| Reorder sidebar item | Drag a sidebar button (mime `application/x-pymcl-nav`, drag threshold 8 px) and drop on another button (upper half = before, lower half = after; green 2 px drop line indicator) | `_write_sidebar_sequence` → `ui_nav_order`, `ui_nav_pinned`; sidebar rebuilt, selection preserved |
| Pin a sub-page to sidebar | Drag a category-bar button (from Download/More section) onto the sidebar | Removes key from its section (`ui_section_members`), adds to `ui_nav_pinned`, inserts at drop position in `ui_nav_order` (or before `more`). **Refused** with `InfoBar.warning("无法移出", "该分区只剩这一个子页，移走会变空栏；先在「自定义分区」里补充其它子页")` if the section would become empty. Rebuilds sections + sidebar |
| Unpin (drop on section) | Drag a pinned sidebar item onto the "下载"/"更多" sidebar button | `_unpin_nav(key, section)` → removed from `ui_nav_pinned`, appended to that section's members |
| Unpin (drop on category bar) | Drag pinned item onto the section's category bar (`DownloadCatBar.unpinRequested`) | same as above with that section |
| Resize sidebar | Drag 5 px right-edge handle | live width; on release `ui_sidebar_width` saved, badge repositioned |
| "编辑布局" (bottom button, tooltip "自由调整启动页布局：拖动、缩放、增删卡片") | click | `launch_page.canvas.set_edit_mode(True)` (does not navigate) |
| Click nav item | | `_on_nav(key)`: pinned sub key → `switchTo(key)` (shows in its default section shell, selection stays on the pinned button); top key → `ensure_first()` on sections, switch stack, `_reload_page` |

### 1.4 Task badge
- Attached to the "下载任务" button; text = count or `"99+"`; hidden when 0; "pop" animation when count increases; repositioned on resize/rebuild.
- Source: `backend.task_count_changed` and `backend._download_task_count()` after sidebar rebuild.

### 1.5 Download dock placement
- `_place_download_dock()` on every stack change and resize: visible iff `dock._active` (running tasks) non-empty **and** visible page key ∉ `{settings, instance, tasks, feedback}` (drills into section's current sub-page).
- Width `min(640, max(420, contentWidth-40))`, bottom-center with 18 px margin, slide-in 280 ms / slide-out 200 ms.

### 1.6 Notifications (`_notify_task` on `backend.finished`)
1. If task_id was queued via `queue_launch_after(task_id, instance, version, loader)` and succeeded → `InfoBar.success("安装完成", "正在启动游戏…")` TOP_RIGHT 2500 ms; after 380 ms `_launch_installed()`:
   - uses `backend._last_installed` (`{instance, version, loader}`) to pick the real installed version id;
   - `switchTo(launch_page)`, `launch_page.reload()`, set `instance_box`, reload, choose version in `version_box` (exact → contains vid → contains version+loader → first), then `launch_page._on_launch()`.
2. Skip toasts for titles starting with `启动游戏` or `微软登录`.
3. Otherwise `InfoBar.success(title, message)` 3000 ms, or `InfoBar.error(title, message)` 5000 ms unless `message == "已取消"`.

### 1.7 Boot behaviours (`_boot_extras`, 400 ms after construction)
1. If `get_setting("first_run", True)`: show `FirstRunDialog` (game dir + download source + memory + default isolation). Accept → `dlg.apply()` (calls `get_settings()`, updates `download_source`, `default_memory_mb`, `default_isolation`, `first_run=False`, `save_settings(data)`, then `set_game_dir(path)`). Reject → `save_settings({...first_run: False})`.
2. Feedback consent: if `feedback.consent_asked()` is False → `prompt_feedback_consent` MessageBox("是否上传诊断数据", …, yes="同意", cancel="暂不同意") → `fb.set_consent(ok)`; start/stop heartbeat. Else if consent → `fb.start_heartbeat()`.
3. If `get_setting("auto_check_update", True)`: `call_async(check_update)` → if `info["has_update"]` → `InfoBar.info("发现更新", info["message"] or "到设置里安装")` TOP_RIGHT 5000 ms.

### 1.8 Game lifecycle
- `game_started` → `launcher_visibility` (`get_setting`, default `"keep"`): `close` → set quit-on-exit and hide; `hide`/`hide_reopen` → hide; `minimize` → minimize; `keep` → nothing.
- `game_exited(code)` → if quit-on-exit → `QApplication.quit()`; if `hide_reopen` → show + raise + activate.

### 1.9 Theme
- `apply_theme()` reads `theme_color` (default `#2E9B6B`), `ui_dark`, `ui_background`; short-circuits if unchanged. Background image applied only if file exists; page surfaces become transparent when active.
- Subscribed to `backend.theme_changed`.

### 1.10 Refresh policy
- `backend.ui_changed` → sets `_data_dirty`, 280 ms single-shot → `_refresh_pages(force=True)` on visible page only: `launch` → `reload()`; `mods` → `reload_list()`; `version` → `reload_installed_only()`; `java` → `reload(scan_system=False)`; pages with `reload_installed()` → that; else `reload()`.
- `_reload_page(page)` on navigation: same dispatch, throttled to once per 1.2 s per page unless forced/dirty.

### 1.11 Close
`closeEvent`: `backend.terracotta_shutdown()`, `feedback.stop_heartbeat(send_offline=True)`, `backend.shutdown()` (800 ms budget; launch task not cancelled).

### 1.12 Fly animation helper
`fly_to_tasks(source_widget, text, color)`: if `ui_fly_animation` (default True) → animate first letter of `text` from source to the "下载任务" button for `ui_fly_duration_ms` (default 620).

### 1.13 Backend methods used
`get_setting`, `get_settings`, `save_settings`, `check_update` (async), `task_title`, `terracotta_shutdown`, `shutdown`, `_download_task_count`, `_last_installed` (attr). Signals: `finished`, `theme_changed`, `ui_changed`, `task_count_changed`, `game_started`, `game_exited`.

---

## 2. `app/pcl_chrome.py`, `app/widgets.py` — user-visible behaviour

### 2.1 `PclTitleBar`
Brand "PyMCL", min & close buttons only (close hover red `#E81123`). Window drag via title bar.

### 2.2 `PclSideBar`
Already covered in §1.3. Additional: supports `group` items with chevron expand/collapse (not used by current config), `header` labels, `stretch` + divider before "下载任务".

### 2.3 `widgets.py` dialogs (reused across pages)

| Class | UI | Buttons |
|---|---|---|
| `InputDialog(title, label, text, placeholder)` | subtitle + optional label + single `LineEdit`; `value()` = stripped text; min width 380 | 确定 / 取消 |
| `ComboDialog(title, label, items, current)` | subtitle + wrapped hint + ComboBox; `value()` = current text; min width 420 | 确定 / 取消 |
| `DeviceCodeDialog` | "微软账号登录"; hint "正在获取登录代码…"; code label `------`; uri label. `show_code(code, uri)` sets hint "请在浏览器打开下面的地址并输入代码："; `show_status(text)` | 打开浏览器 (opens `uri` in browser, does not close) / 关闭 |
| `prompt_feedback_consent(parent)` | MessageBox "是否上传诊断数据" with multi-line explanation | 同意 / 暂不同意 |
| `EmptyState(icon, text)` | centered gray icon 48 px + caption | — |
| `IconTile(text, color, size)` | rounded square with first letter; color from `pick_color(name)` (8-color palette by hash) | — |
| `ThumbnailTile(text, url, size)` | rounded thumbnail loaded from URL via `mclauncher.thumbnails.ensure_thumb` in a thread pool (4 threads), memory cache 240 entries; falls back to `IconTile` look | — |
| `Pill(text, color, solid)` | capsule badge | — |
| `BannerWidget` | gradient hero banner (`#123B2A → #3E7C4F → #7BB661`), kicker "MINECRAFT", title (default "准备启程"), subtitle, right-side vertical layout for buttons; drifting glow animation only if `ui_motion` allows | — |

`grid_columns(scroll, page, card_w, spacing=12, gutter=8)` — responsive column count from viewport width.

---

## 3. `app/dashboard.py`, `app/layout_model.py` — Launch page free-layout canvas

### 3.1 Data model (`layout_model.py`)
- Coordinates are canvas fractions 0..1 (`x, y, w, h`), `z` order, `hidden`, `settings: dict`, `id`, `type`.
- `LayoutDoc {version: 1, grid: int, items: [LayoutItem.to_dict()]}`.
- Card min sizes (px): banner 340×150, config 330×300, log 260×180, news 220×180, quick 220×150, notes 180×130, playtime 220×130, tasks 220×130; fallback 200×120. Card widget adds 40 px for header.
- Default layout (`default_doc()`, grid 8): banner (0,0,1,0.26) z0; config (0,0.275,0.315,0.725) z1; log (0.325,0.275,0.41,0.725) z2; news (0.745,0.275,0.255,0.725) z3.
- Persistence (direct `CONFIG`): `ui_layout` (active doc or None), `ui_layouts` ({name: doc}), `ui_layout_profile` (active name, "" = unnamed).
- Functions: `load_active_doc`, `save_active_doc(doc, profile=None)`, `active_profile`, `list_profiles`, `save_profile(name, doc)` (also sets active), `activate_profile(name)` ("" → default; unknown → default & reset), `delete_profile(name)` (resets active if it was active), `reset_to_default`, `export_doc(doc, path)` JSON, `import_doc(path)` (drops unknown card types; None if invalid/empty).

### 3.2 Canvas user actions (`DashboardCanvas`)

| Control / gesture | Label | Effect |
|---|---|---|
| Enter edit mode | sidebar "编辑布局" | toolbar slides in top-right; cards get dashed green border, transparent "shield" (blocks content interaction), 8 resize grips, header always shown, remove/settings buttons visible; grid dots fade in |
| Toolbar "添加卡片" | `_CardPalette` dialog "添加卡片" / "点击要添加到布局的卡片：" — one row per registered type (desc text + icon), singles already present are omitted; click adds & closes; cancel "关闭" | `add_card(type)` at first free spot (24 px scan step) using `_ADD_DEFAULT` size; fade-in |
| Toolbar "吸附" combo | items: 自由(0), 4px, 8px, 16px, 24px | sets `doc.grid`, emits `layout_changed` |
| Toolbar "适应窗口" | | scales union bounding box of visible cards to fill canvas with 12 px margin, respecting min sizes |
| Toolbar "重置布局" | | `build_from_doc(default_doc())` |
| Toolbar "完成" (primary) | | exit edit mode |
| Drag card body (edit mode) | | move with grid snap, clamped to canvas, raise to top (new z) |
| Drag grip n/s/e/w/ne/nw/se/sw | | resize with snap, min size, canvas clamp; **linked resize**: neighbours touching the dragged edge (gap −8..28 px) shrink/grow keeping gap; blocked by non-following cards |
| Card header "移除此卡片" (DELETE icon) | edit mode only | `remove_card` (fade out); `on_removed` hook (`_keep` for singles = body cached, `_drop` for multi = destroyed) |
| Card header "卡片设置" (SETTING icon) | edit mode, only for types with `on_settings` (quick) | opens `QuickSettingsDialog` |
| Window resize | | cards re-laid proportionally |

Persistence: `layout_changed` emitted immediately for structural changes and debounced 300 ms for geometry; `LaunchPage` debounces another 400 ms then `save_active_doc(doc)` and, if a named profile is active, `save_profile(name, doc)`.

---

## 4. `app/pages/launch_page.py` + `app/pages/home_cards.py` — Launch page

### 4.1 Purpose / layout
Free-layout canvas of cards. Four **singleton** cards (banner, config, log, news) whose bodies are created once and cached even when removed; four **multi-instance** cards (quick, notes, playtime, tasks) storing data in `item.settings`.

Card registry (`build_registry`):

| type | title | icon | palette description | single | chrome (header always) |
|---|---|---|---|---|---|
| banner | 启动横幅 | HOME | 启动横幅 — 大标题与启动/停止按钮、进度条 | yes | no |
| config | 启动配置 | SETTING | 启动配置 — 实例/版本/账号/内存等表单 | yes | no |
| log | 实时日志 | DOCUMENT | 实时日志 — 游戏输出与启动命令 | yes | yes |
| news | 主页 | SYNC | 主页 — Minecraft 新闻 / 自定义主页 | yes | yes |
| quick | 快捷入口 | TILES | 快捷入口 — 一键跳转到常用页面，可配置显示哪些 | no | yes (has settings) |
| notes | 便签 | EDIT | 便签 — 自动保存的随手记 | no | yes |
| playtime | 游戏时长 | HISTORY | 游戏时长 — 总量与各实例排行 | no | yes |
| tasks | 任务摘要 | CLOUD_DOWNLOAD | 任务摘要 — 下载任务数量与最近结果 | no | yes |

### 4.2 Banner card (`BannerBody`)
- `BannerWidget` title/subtitle (see `_sync_banner`), right side: **"启动游戏"** (primary, 170×46, PLAY icon), **"停止"** (170×30, CLOSE icon, disabled until launching).
- Below: `SmoothProgressBar` 0–100, status `CaptionLabel` "就绪".
- `_sync_banner()`: if current instance has `pack` → title = pack name, subtitle = `"{pack_version} · Minecraft {mc_version} · 实例 {instance}"` (non-empty parts) else version; else title = version or "—", subtitle `"实例 {instance} · 点击「启动游戏」进入世界"`.

### 4.3 Config card (`ConfigBody`) — form "启动配置"

| Row label | Control | Behaviour |
|---|---|---|
| 实例 | ComboBox `instance_box` | items from `get_instances()` names; selection preserved else `CONFIG.default_instance`; change → reload versions + Java box |
| 版本 | ComboBox `version_box` | `get_installed_versions(instance)` (hidden versions excluded unless `show_hidden_versions`); change → `_sync_banner` |
| 账号 | ComboBox `account_box` | `get_accounts()` (`"离线模式"` first); default = active account from `get_account_rows()` |
| 用户名 | LineEdit `username_edit` placeholder "离线用户名", default "Player" | |
| Java（本实例） | ComboBox `java_box` | `java_combo_options(instance, scan_system=False)` sync, then async `java_combo_options(instance, True)`; current = `java_combo_label_for(instance, opts)`; user change → `set_instance_java(instance, value)` |
| 内存 | Slider 512–32768 step 256 + label "{n} MB" | initial `CONFIG.memory_mb` (4096); change → debounce 400 ms → `CONFIG.set("memory_mb")` |
| 分辨率 | SpinBox width 320–7680 × SpinBox height 240–4320 | initial `CONFIG.width`(854)/`height`(480); change → debounced `CONFIG.set("width"/"height")` |
| 服务器 | LineEdit `server_edit` placeholder "直连服务器 host 或 host:port" | passed as `--server host --port port` (default port 25565) |
| (blank) | TransparentPushButton "此版本设置…" | opens `VersionSetupDialog(backend, instance or "default", version)`; if no version → `InfoBar.info("未选择版本","请先安装并选择一个版本")`; on accept `dlg.save()` → `InfoBar.success("已保存","版本设置已写入")` |
| (blank) | "刷新新闻" | `_load_news()` |
| (blank) | "使用微软账户登录…" | `_login()` (see below) |

`_sync_from_config()` on every `reload()`: if a control still equals the last CONFIG snapshot, it's updated to the new CONFIG value (settings page changes propagate; user's local edits are kept).

### 4.4 Log card (`LogBody`)
Read-only `PlainTextEdit` (max 5000 blocks, placeholder "启动日志将输出到这里…") + button **"复制启动命令"** → `build_launch_command(instance, version, account, username, memory_mb, width, height, java)` → clipboard → `InfoBar.success("已复制","启动命令已复制到剪贴板")` or `InfoBar.error("复制失败", str(e))`.

### 4.5 News / homepage card (`NewsBody`)
`_load_news()` by `CONFIG.homepage_mode` (`news` default):
- `blank`: card title "主页", caption "主页已设为空白".
- `custom`: title "自定义主页"; `CONFIG.custom_homepage` path → `.html/.htm` rendered in QTextBrowser (external links open), other files as plain text; missing → "未设置自定义主页。到设置 → 启动页主页 填写本地 HTML 路径。"; read errors shown inline.
- `news`: title "Minecraft 新闻"; first `cached_news()` then async `fetch_news()`; show up to 6 rows: bold `title` + caption `(body or version)[:80]`; empty → "暂无新闻"; fetch error → `InfoBar.warning("新闻刷新失败", str(exc) or "将继续显示缓存")`.

### 4.6 Quick card (`QuickBody`)
Grid of `PushButton(icon, label)` (4 cols if >6 targets else 3); click → `window.switchTo(key)`. Default targets: `version, mod, modpack, mods, instance, account, settings, tasks`. Settings dialog `QuickSettingsDialog` "选择快捷入口" / "勾选要显示在卡片上的入口：" with a checkbox per `QUICK_TARGETS` key (launch, version, mod, modpack, datapack, resource, shader, world, java, instance, mods, account, multiplayer, servers, playtime, feedback, settings, tasks; labels = `_QUICK_LABELS`); 确定 writes `item.settings["targets"]` (ignored if none checked) and persists layout.

### 4.7 Notes card (`NotesBody`)
`PlainTextEdit` placeholder "写点什么，自动保存"; 600 ms debounce → `item.settings["text"]` → persist layout.

### 4.8 Playtime card (`PlaytimeBody`)
`refresh()` (called on every `LaunchPage.reload()` via `canvas.refresh_cards()`): "总时长：{format_playtime(get_total_playtime())}" + top-5 instances by `total` from `get_all_playtime()` as lines `"{name}  {format_playtime(sec)}"` (only sec>0).

### 4.9 Tasks card (`TasksBody`)
"下载任务：{n}" from `task_count_changed` (init via `_download_task_count()`); "暂无任务" when 0; on `finished` → `"✓ "/"✗ " + message[:120]`.

### 4.10 Launch flow (`_on_launch`)
1. Flush pending memory/resolution to CONFIG.
2. `preflight_launch(instance=, version=, memory_mb=, java=)` → exception → `MessageBox("启动预检失败", str)`. Items with `level=="error"` → `MessageBox("启动预检未通过", "· title\ndetail" joined)` and abort. Items `level=="warn"` → `MessageBox("启动预检有警告", body + "\n\n是否仍要继续启动？", yes="继续启动", cancel="取消")`; abort on cancel.
3. Clear log, append `"[预检:warn] {title}: {detail}"` per warning, progress 0, status "准备启动…", disable 启动游戏, enable 停止.
4. `task_id = launch_game(instance, version, account, username, memory_mb, width, height, java, extra_game_args)`.
5. `progress` for this task → bar = current*100/total; status = message part before `"  |  "` + speed.
6. `log` → append.
7. `crash(task_id, report)` → `CrashDialog(report)`; if `want_relaunch` → set instance/version from report and relaunch.
8. `finished`: re-enable 启动游戏, disable 停止, status = message. Success → progress 100, `InfoBar.success("游戏已结束", message or "已正常退出")`. Failure: if crash already shown → nothing; if `message == "已取消"` → `InfoBar.info("已停止", message)`; else `CrashDialog({"title":"启动失败","headline":"启动中止","detail":message,"help":"这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。","instance","version"})`, relaunch if requested.
- **"停止"** → `cancel_task(task_id)`.

### 4.11 Microsoft login (`_login`)
Open `DeviceCodeDialog`, `task_id = start_microsoft_login()`; `login_code` → `show_code`, `login_status` → `show_status`; `finished(task_id)`: success → dialog accept + `reload()`; failure → `show_status(message)`. If the user closes the dialog before completion → `cancel_task(login_task_id)`. Then `reload()`.

### 4.12 Signals / timers / config
- Subscribes: `backend.progress`, `log`, `finished`, `crash`, `login_code`, `login_status`.
- Timers: layout persist 400 ms; launch defaults persist 400 ms; boot load `singleShot(0)`.
- CONFIG read: `memory_mb`, `width`, `height`, `default_instance`, `homepage_mode`, `custom_homepage`, `ui_layout`, `ui_layouts`, `ui_layout_profile`. CONFIG written: `memory_mb`, `width`, `height`, `ui_layout`, `ui_layouts`, `ui_layout_profile`.

### 4.13 Backend data shapes used here
- `get_instances() -> [{name, versions:int, mc:str, pack:str, pack_version:str, mc_version:str, java:str, java_label:str}]` (2.5 s TTL cache).
- `get_accounts() -> ["离线模式", …names]`.
- `get_account_rows() -> [{name, type, uuid, api, avatar, body, active:bool}]`.
- `get_installed_versions(instance, include_hidden=False) -> [version_id…]`; with `instance=""` → `["inst / vid", …]` across all instances.
- `java_combo_options(instance, scan_system) -> [{label, value}]`, first `{label:"自动选择", value:"自动选择"}`, plus `"已保存 (path)"` entry if stored pref not found.
- `java_combo_label_for(instance, options) -> label` (falls back "自动选择").
- `set_instance_java(name, java)` (normalizes; no event).
- `preflight_launch(...) -> {ok: bool, items: [{level: "error"|"warn"|"ok"|"info", code, title, detail}]}`.
- `launch_game(...) -> task_id`; side effects: `CONFIG.default_instance = instance`, `game_started`/`game_exited`, playtime tracking, crash analysis.
- `build_launch_command(...) -> str` (may raise `LaunchError`).
- `start_microsoft_login() -> task_id` (title "微软登录").
- `cancel_task(task_id)`.
- `cached_news()/fetch_news() -> [{title, body, version, image, date}]`.
- `get_total_playtime() -> int`, `get_all_playtime() -> {instance: {total, versions:{vid: sec}, sessions:[…]}}`, `format_playtime(sec) -> "X 小时 Y 分钟" | "Y 分钟 Z 秒" | "Z 秒"`.

---

## 5. `app/pages/version_page.py` — `VersionPage` ("原版游戏")

### 5.1 Layout
Title "版本". Toolbar: `SearchLineEdit` "搜索版本号…" (260 px); `Pivot` tabs 全部/正式版/快照/远古 (keys `all/release/snapshot/old_alpha`; 远古 matches `old_alpha` **and** `old_beta`); label "实例" + `ComboBox`; CheckBox "显示隐藏"; CheckBox "完成后启动" (default checked). Scroll grid of `VersionCard`s (216×132; 240 px column basis): version id, type Pill (正式版 `#2FA36B` / 快照 `#E8862E` / 远古 `#7C5CD6`), "发布于 {date}", button "安装". Shows first 24, then "加载更多（还有 N）" (+80 each). Empty → `EmptyState("没有匹配的版本")`.
Bottom card "已安装版本": header buttons repair (SYNC, tooltip "修复选中版本（补全缺失文件）") and uninstall (DELETE, "卸载选中版本"); rows: CheckBox(version id) + loader Pill + "版本设置" (SETTING) + "更多" (MORE) menu button.

Loader Pill rules on the lowercase id: contains `fabric` → "Fabric" `#7C5CD6`; `forge` w/o `neo` → "Forge" `#E8862E`; `quilt` → "Quilt"; `neoforge`/`neo` → "NeoForge"; `optifine` → "OptiFine" `#2E9B6B`; `liteloader` → "LiteLoader"; else "原版" `#4C8BF5` (non-listed colors default `#4C8BF5`).

### 5.2 Actions

| Control | Backend call | Result handling |
|---|---|---|
| Page load / `reload()` | `get_instances()`; `get_version_list()` (cached manifest); once: async `fetch_version_list()` | fill instance box (default = `CONFIG.default_instance`), grid, installed list. Fetch error → `InfoBar.error("版本列表加载失败", msg)` 4000 ms + `EmptyState("版本列表加载失败")` if nothing cached; `_fetched` reset so next reload retries |
| Search text / pivot | — | 150 ms debounce refill |
| 实例 combo change | `get_installed_versions(instance, include_hidden=show_hidden)` | rebuild installed rows |
| 显示隐藏 toggle | `CONFIG.set("show_hidden_versions", on)` + save | reload installed |
| Card "安装" | opens `InstallWizardDialog(backend, version, instance)`; on accept: `fly_to_tasks(card, version, "#2FA36B")`; `install_game(version, loader, loader_version, instance=instance, extra=payload.extra)` → task_id; if 完成后启动 → `window.queue_launch_after(tid, instance, version, loader)` | |
| Row "版本设置" | `VersionSetupDialog(backend, instance, version)`; accept → `dlg.save()` | |
| Row "更多" menu | items: 打开游戏文件夹 (`open_version_folder(inst, ver, "game")`), 打开 mods (`…"mods"`), 打开 saves (`…"saves"`), 打开截图 (`…"screenshots"`), 存档管理… (`SavesDialog(backend, inst, ver)`), 重命名 (`InputDialog("重命名版本","新版本 ID", text=ver)` → `rename_version(inst, ver, new)`), 复制 (`InputDialog("复制版本","新版本 ID", text=ver+"-copy")` → `copy_version(inst, ver, new)`), 隐藏 / 取消隐藏 (`get_version_settings` → `hide_version(inst, ver, not hidden)`), 创建桌面快捷方式 (`create_desktop_shortcut(inst, ver)` → `MessageBox("已创建", "桌面快捷方式：\n{path}\n\n双击即可直接启动该版本。")` / `MessageBox("创建失败", e)`), 导出启动脚本 (`export_launch_script(inst, ver)` → task) | errors → `MessageBox("无法打开"/"重命名失败"/"复制失败"/"操作失败", str(e))`; list reloaded after rename/copy/hide |
| Header uninstall | selected = checked rows as `"{instance} / {vid}"`; none → `MessageBox("未选择","请先勾选要卸载的版本")`; confirm `MessageBox("确认卸载", "将卸载 N 个版本：\n…")`; each → `uninstall_version(spec)`; error `MessageBox("卸载失败", e)` | reload installed |
| Header repair | none → `MessageBox("未选择","请先勾选要修复的版本")`; each → `repair_version(inst, vid)` → task; `InfoBar.success("已开始修复", "N 个版本")` | |
| Resize | 120 ms debounce refill if column count changes | |

### 5.3 Data shapes
- `get_version_list()/fetch_version_list() -> [{version, type: "release"|"snapshot"|"old_alpha"|"old_beta", date: "YYYY-MM-DD"}]` sorted date desc.
- `install_game(version, loader="无", loader_version="", instance="", extra={}) -> task_id`; title `"安装游戏 {version} + {loader} + OptiFine + LiteLoader"`; extra keys: `optifine, liteloader, skip_assets, loader_version, optifine_version`; on success sets `backend._last_installed={instance, version, loader}` and applies `default_isolation` to version settings.
- `get_version_settings(inst, ver) -> dict` (see §7.3). `hide_version -> dict`. `rename_version/copy_version -> new_id`. `open_version_folder -> path` (`which` ∈ root/game/mods/saves/screenshots/resourcepacks/shaderpacks/datapacks/logs/crash-reports/version). `create_desktop_shortcut(inst, ver, username="", account="", name="") -> path`. `export_launch_script(inst, ver, dest="") -> task_id` (writes `exports/launch-{inst}-{ver}.bat`). `uninstall_version("inst / vid")`. `repair_version(inst, ver) -> task_id` (title `"修复 {ver}"`). All mutators emit `ui_changed`.

### 5.4 Config
Read: `show_hidden_versions`, `default_instance`. Written: `show_hidden_versions`.

---

## 6. `app/pages/install_wizard.py` — `InstallWizardDialog`

Title `"安装 {mc_version}"`; hint "主加载器只能选一个。Forge 可同时勾选 OptiFine（放入 mods）。"

| Control | Items / default | Behaviour |
|---|---|---|
| 主加载器 ComboBox | 无（原版）, Fabric, Forge, Quilt, NeoForge | change → reload loader versions |
| 加载器版本 ComboBox | "最新" + async `list_loader_versions(mc, loader)` rows (`label` or `id`); previous selection kept | only when loader ≠ 无 |
| CheckBox "同时安装 OptiFine（Forge / 原版）" | enabled only if primary is 无 or Forge (else unchecked+disabled) | |
| OptiFine ComboBox | "最新" + async `list_loader_versions(mc, "OptiFine")` | reset to "最新" when not allowed |
| CheckBox "同时安装 LiteLoader（1.7–1.12）" | | |
| CheckBox "跳过资源文件校验（加快重装）" | default `CONFIG.skip_assets` | |
| 开始安装 / 取消 | | `payload() = {loader: "无"|name, loader_version: str, extra: {optifine, liteloader, skip_assets, [loader_version], [optifine_version]}}` |

Data: `list_loader_versions(mc_version, loader) -> [{id, label, stable, (type, patch for OptiFine)}]`; empty for 无.

---

## 7. `app/pages/version_setup.py` — `VersionSetupDialog`

Title `"版本设置 · {version}"`, hint "这些选项只作用于当前版本，对齐 PCL 的「版本设置」。" Loads `get_version_settings(instance, version)`.

### 7.1 Form rows

| Label | Control | Load | Save key |
|---|---|---|---|
| 隔离 | Combo of `ISOLATION_LABELS` values: 关闭（共用实例目录）/隔离存档/隔离 Mod 与配置/隔离全部 | `isolation` (none/saves/mods/all) | `isolation` |
| 内存 MB | LineEdit placeholder "留空则用启动页滑条" | `memory_mb` | int or None |
| Java | Combo `java_combo_options(instance, False)` labels, then async `java_combo_options(instance, True)`; unknown stored value appended | `java` | value of chosen option (or text) |
| GC | Combo "跟随全局" + `GC_LABELS` values (G1（推荐）, G1, 调优 G1, ZGC, 不指定) | `gc` key | `gc` key or "" |
| JVM 参数 | TextEdit placeholder "-XX:+UseG1GC 等，一行或空格分隔" | `jvm_args` | |
| 游戏参数 | LineEdit "附加游戏参数" | `game_args` | |
| 绑定账号 | Combo "跟随启动页" + `get_accounts()` | `login_account` | "" if 跟随启动页 |
| 统一通行证 | LineEdit "32 位服务器 ID 或通行证链接" | `nide8_id` | |
| 认证服 | LineEdit "自定义认证服 API（可选）" | `auth_server` | |
| 服务器 | LineEdit "启动后直连，例如 play.example.com" | `server` | |
| 端口 | LineEdit "25565" | `port` | string |
| 窗口标题 | LineEdit "自定义窗口标题" | `window_title` | |
| 窗口模式 | Combo 窗口/全屏 | `window_mode` in `("maximize","fullscreen")` → 全屏 | `"maximize"` or `"window"` |
| 窗口宽度 / 窗口高度 | LineEdit "留空则用设置页的全局分辨率" | `window_width/height` | positive int or None |
| 离线皮肤 | Combo 默认/Steve/Alex | `offline_skin` default/steve/alex | |
| 启动前 | LineEdit "启动前命令（cmd / 脚本）" | `pre_launch` | |
| (blank) | CheckBox "等待启动前命令结束" | `pre_launch_wait` (default True) | |
| 退出后 | LineEdit "退出后命令" | `post_launch` | |
| 优先级 | Combo low/normal/high | `process_priority` | |

Buttons 保存 / 取消. `save()` → `save_version_settings(instance, version, payload) -> merged dict`; emits `ui_changed`.

### 7.2 Data shape `get_version_settings` (DEFAULTS merged with stored)
`{isolation, memory_mb, java, jvm_args, game_args, pre_launch, post_launch, pre_launch_wait, server, port, process_priority, icon, hidden, login_account, auth_server, auth_server_name, nide8_id, gc, window_title, window_mode, window_width, window_height, skip_assets, offline_skin}`.

---

## 8. `app/pages/download_hub.py` — `DownloadSection` / `MoreSection`

### 8.1 Layout
Section shell = horizontal **category bar** (48 px, horizontally scrollable, animated green underline indicator) + `SlideHStack` (left/right slide animation 260 ms; skipped if `ui_motion` off or rapid clicks).

### 8.2 Behaviour
- `bind([(title, getter, key)…])` creates lazy buttons immediately; page constructed on first click / first entry (`ensure_first()` builds first member).
- Click button → `show_page(page)` → slide + select + `window._reload_page(page)`.
- Category buttons are **drag sources** (`_DragButton`, mime `application/x-pymcl-nav` with key) → drop on sidebar pins the page.
- Category bar is a **drop target**: dropping a nav key → `unpinRequested(key)` → MainWindow moves it back into this section.
- Pinned sub-pages are added to the stack **without** a bar button (title "").
- `MoreSection` is identical (subclass).

No backend calls.

---

## 9. `app/pages/catalog_page.py` — `PclCatalogPage` (Mod / 整合包 / 资源包 / 光影包 / 数据包 / 世界)

### 9.1 Per-kind spec

| Kind | class | search title | types (type_box) | search → install → list_installed → delete | local import label / filter / dialog | link title / hint / placeholder | task prefix | empty search / installed |
|---|---|---|---|---|---|---|---|---|
| mod | `ModPage` | 搜索 Mod | 全部, 优化, 科技, 魔法, 冒险 | `search_mods` → `install_mod` → `get_installed_mods` → `delete_mod` | 导入 jar / 模组 (*.jar) / 选择模组 | 从链接安装模组 / 模组下载链接 (URL) / `https://…/mod.jar` | 安装模组 | 没有找到相关模组 / 还没有安装模组 |
| modpack | `ModpackPage` | 搜索整合包 | 全部, 生存, 空岛, 科技, 魔法 | `search_modpacks` → `install_modpack` → `get_installed_modpacks` → `delete_modpack` | 导入文件 / 整合包 (*.mrpack *.zip) / 选择整合包 | 从链接安装整合包 / 整合包链接或文件 / `https://…/pack.mrpack` | 安装整合包 | 没有找到相关整合包 / 还没有安装整合包 |
| resourcepack | `ResourcePackPage` | 搜索资源包 | 全部, 16x, 32x, 64x, 写实, 现代风, 动态效果 | `search_resourcepacks` → `install_resourcepack` → `get_installed_resourcepacks` → `delete_resourcepack` | 导入 zip / 资源包 (*.zip) / 选择资源包 | 从链接安装资源包 / 资源包下载链接 (URL) / `https://…/pack.zip` | 安装资源包 | 没有找到相关资源包 / 还没有安装资源包 |
| shader | `ShaderPage` | 搜索光影包 | 全部, 写实, 卡通, 高性能, 光追 | `search_shaders` → `install_shader` → `get_installed_shaders` → `delete_shader` | 导入 zip / 光影包 (*.zip) / 选择光影包 | 从链接安装光影 / 光影包下载链接 (URL) / `https://…/shader.zip` | 安装光影 | 没有找到相关光影 / 还没有安装光影 |
| datapack | `DatapackPage` | 搜索数据包 | 全部, 生存, 冒险, 装饰 | `search_datapacks` → `install_datapack` → `get_installed_datapacks` → `delete_datapack` | 导入 zip / 数据包 (*.zip) / 选择数据包 | 从链接安装数据包 / 数据包下载链接 (URL) / `https://…/datapack.zip` | 安装数据包 | 没有找到相关数据包 / 还没有安装数据包 |
| world | `WorldPage` | 搜索世界 | 全部, 生存, 冒险, 创造 | `search_worlds` → `install_world` → `list_saves` → `delete_save` | 导入 zip / 世界 (*.zip) / 选择世界 | 从链接安装世界 / 世界下载链接 (URL) / `https://…/world.zip` | 安装世界 | 没有找到相关世界 / 还没有安装世界 |

Every "全部" link label is "从链接安装". `WorldPage` replaces the source combo items with only `["CurseForge"]`.

### 9.2 Layout
**Search card**: title; right side: instance ComboBox (120 px), "从链接安装" (LINK), local import (FOLDER). Grid: 名称 `LineEdit` (placeholder "名称", Enter = search); 来源 ComboBox [全部, Modrinth, CurseForge]; 版本 `EditableComboBox` ["全部 (也可自行输入)", 1.21.1, 1.20.1, 1.19.2, 1.18.2, 1.16.5, 1.12.2] (free text allowed); 类型 ComboBox (spec types). Buttons centered: "搜索" (ghost style), "重置条件".
**Result card**: mode toggles "浏览" / "已安装" (checkable), `installed_ver_box` (160 px, "实例目录" + installed version ids; **visible only for mod kind in 已安装 mode**), stretch, "收藏" (HEART), "检查更新" (SYNC; **visible only for mod kind**). Scrollable list.

Result row (`PclResultRow`, 88 px): thumbnail (`icon_url|thumb|icon|image`) or letter tile; name (title color); up to 4 tag chips; description[:90]; meta chips: game version (`game_version|version|"—"`), downloads formatted (`≥1e8 → "x.x亿"`, `≥1e4 → "N万"`, else raw, 0 → "—"), updated (`updated|date|"—"`), source label (CurseForge / Modrinth / "—"). Buttons: "选择版本" (88×30 ghost) and heart "收藏".

Installed row (52 px): filename/name; `SwitchButton` if row has `enabled`; DELETE button.

### 9.3 Actions

| Action | Call | Result |
|---|---|---|
| Initial state | `_show_idle()` → `EmptyState("输入名称后点击搜索")`; `_reload_instances()` via `get_instances()` | |
| First `reload_installed()` while in 浏览 mode (i.e. first time page is shown) | auto `_search()` with empty query → popular list | |
| 搜索 / Enter / 重置条件 | async `fn(query, source, extra)` where `source ∈ {"全部","Modrinth","CurseForge"}`, `extra={game_version: "" if starts with "全部" else text, category: type label}`; fallback `fn(query, source)` on TypeError. While running → `EmptyState("正在搜索…")`. Token guard discards stale results | empty query → header "热门推荐" then rows; no rows → `EmptyState(spec.empty_search)`; error → `EmptyState("搜索失败: {err}")` |
| 重置条件 | clears name, source idx 0, version idx 0, type idx 0, then search | |
| 浏览 / 已安装 toggle | `_set_mode`; 已安装 → `reload_installed()`; 浏览 → `_search()` | |
| Instance combo / installed_ver_box change | `reload_installed()` | |
| 已安装 list (mod kind) | `get_installed_mod_entries(inst, version)` (version = "" for "实例目录") | rows `{filename, enabled, bytes, path}` |
| 已安装 list (other kinds) | `getattr(backend, spec.list_installed)(inst)`; list of str → `{filename}`; list of dict (world: `list_saves`) used directly (uses `name`) | empty → `EmptyState(spec.empty_installed)` |
| Installed switch (mod only) | `enable_mod(inst, filename, ver)` / `disable_mod(inst, filename, ver)` | error → `InfoBar.error("切换失败", e)` + reload |
| Installed DELETE | Confirm: modpack → `MessageBox("删除整合包实例", "将删除整个实例「{inst}」及其文件，不可恢复。", yes="删除实例")`; world → `MessageBox("删除世界存档", "将永久删除世界「{name}」，其中的建筑与游戏进度都无法恢复。\n建议先在「存档管理」里备份。", yes="永久删除")`; else `MessageBox("删除确认", "将删除「{name}」。", yes="删除")`; cancel "取消". Then `delete_mod(inst, filename, ver)` or `delete_shader/delete_resourcepack/delete_datapack/delete_modpack/delete_save(inst, filename)` | error → `InfoBar.error("删除失败", e)`; reload |
| "检查更新" (mod) | `start_mod_updates(inst)` → task | |
| "收藏" toolbar | `catalog_favorites()` → rows rendered as result rows; empty → `EmptyState(HEART, "还没有收藏")` | |
| Row heart | `toggle_favorite(item)` → `InfoBar.success("已更新收藏", name)` / `InfoBar.error("收藏失败", e)` | |
| Row "选择版本" (`_install(item, tile)`) | If item has `path`/`url` or lacks `slug`/`id` → direct `_do_install`. Else `FilePickDialog(backend, item+{instance}, kind, version_box.text)`; on accept `extra = dlg.selected_extra()`; datapack → `_maybe_datapack_save(extra)`: `list_saves(inst)` names → `ComboDialog("装进存档", "可选：把数据包装进某个存档，或只放到 datapacks 文件夹。", ["不装进存档"]+names)` → sets `extra["save"]`; then `_do_install(extra, tile)` | |
| `_do_install(item, tile)` | `fly_to_tasks(tile, name)`; `extra = dict(item)`; `extra.setdefault("instance", current)`; `extra["source"] = item.source or source combo`; `extra.setdefault("game_version", filter)`. modpack: `install_modpack(name, extra.source or "Modrinth", extra=extra)`; others: `install_xxx(name, extra.instance, extra=extra)`; fallbacks `(name, instance)` / `(name)` | task_id (ignored); toast via MainWindow |
| "从链接安装" | `InputDialog(link_title, link_hint, placeholder)` → `_install({"name": url, "url": url}, link_btn)` | |
| Local import | `QFileDialog.getOpenFileNames(local_dialog, filter)` → each `_install({"name": p, "path": p}, local_btn)` | |
| Drag & drop files onto page | each local file → `_do_install({"name": path, "path": path}, local_btn)` | |
| `showEvent` clipboard detection | if clipboard text contains `modrinth.com` or `curseforge.com` and differs from `window._clip_seen` → store it, put into 名称 if empty, `InfoBar.info("识别到剪贴板链接", clip[:96])` 3500 ms | |

### 9.4 Data shapes
- `search_mods(query, source, extra) -> [{name, author, downloads, id, slug, source: "modrinth"|"curseforge", description, tags, updated, icon_url}]`; empty query returns `POPULAR_MODS` with `tags:["热门"]`, `description:"热门推荐"`.
- `search_modpacks(query, source, extra) -> [{name, author, downloads, id, slug, source, description, (tags)}]`; empty query → `POPULAR_MODPACKS` (CBC pinned first).
- `search_shaders/search_resourcepacks/search_datapacks(query, source, extra) -> [{name, author, downloads, id, slug, source, description, tags, updated, icon_url}]` (both sources merged when 全部).
- `search_worlds(query, source="CurseForge", extra) -> [{name, author, downloads, id, slug, source, description, tags, updated}]`.
- `extra.category` accepts the Chinese type label (backend maps via `_TYPE_ALIASES`: 优化→optimization, 科技→technology, 魔法→magic, 冒险→adventure, 生存→survival, 装饰→decoration, 写实→realistic, 卡通→cartoon, 高性能→performance, 光追→path-tracing, 现代风→modern, 动态效果→animated, 空岛→skyblock, 创造→creation; 16x/32x/64x literal).
- `install_mod(name, instance, extra) -> task_id` (title `"安装模组 {basename}"`); extra keys honored: `path|url`, `source`, `id`, `slug`, `version_id`, `file_id`, `game_version|mc_version`, `version` (target version dir when isolated), `instance`.
- `install_modpack(name, source, extra) -> task_id` (title `"安装整合包 {basename}"`); extra: `path`, `instance`, `id`, `slug`, `file_id|version_id`; on success sets `CONFIG.default_instance` to the installed instance.
- `install_shader/resourcepack/datapack(name, instance, extra) -> task_id`; datapack extra `save`/`world` → also copies into that save.
- `install_world(name, instance, extra) -> task_id`; extra `path|url|id(+file_id|version_id)`.
- `get_installed_mods(inst, ver) -> [filename…]` (enabled only); `get_installed_mod_entries(inst, ver) -> [{filename, enabled, bytes, path}]`.
- `get_installed_shaders/resourcepacks/datapacks(inst) -> [filename…]` (`.zip`/`.jar` in subdir). `get_installed_modpacks(inst) -> ["Name version"]` or `[]`.
- `list_saves(inst, ver="") -> [{name, path, icon, bytes, mtime}]`.
- `delete_mod(inst, filename, ver)`, `delete_shader/resourcepack/datapack(inst, filename)`, `delete_modpack(inst, filename)` (**deletes whole instance**; raises if no modpack meta), `delete_save(inst, name, ver="")`. All emit `ui_changed`.
- `enable_mod/disable_mod(inst, filename, ver) -> new filename`.
- `start_mod_updates(inst) -> task_id` (title `"检查模组更新 {inst}"`; applies all updates).
- `catalog_favorites() -> [{name, source, slug, id}]`; `toggle_favorite(item) -> list` (keyed by `(source, slug|id|name)`; stored in `CONFIG.catalog_favorites`).
- `get_installed_versions(inst) -> [vid…]` (for installed_ver_box).

### 9.5 Config
Read: `default_instance`. Written (via backend): `catalog_favorites`.

---

## 10. `app/pages/file_pick.py` — `FilePickDialog`

Title = item name (or "选择版本"); hint "选择要安装的构建。可按游戏版本和加载器筛选。"

| Control | Behaviour |
|---|---|
| MC ComboBox `gv` (160 px) | "全部" + unique `game_versions` across rows (order of appearance); preselect `item.game_version` if present |
| 加载器 ComboBox (120 px) | 全部, Fabric, Forge, Quilt, NeoForge; match case-insensitive against row `loaders`; rows with empty `loaders`/`game_versions` always pass |
| (mod kind only) "安装到" instance ComboBox (`get_instances()` names, preselect `item.instance`) + target ComboBox (`get_mods_targets(inst)` labels) + tip "开启版本隔离的版本会出现在这里" | instance change → reload targets; fallback `[{"label":"实例共享 mods 目录","value":""}]` |
| List (320 px tall) | rows: title `version_number|name|filename`; meta `"{game_versions[:4]} · {loaders or '任意'} · {date} · {downloads} · {release_type}"`; filename line; button "安装" (64×28) → choose row & accept. Page size 80 + "加载更多（还有 N）". Empty → "没有匹配的文件，试试放宽筛选。" |
| Status label | "正在加载版本列表…" → "{n} 个文件" → "{matched} 个匹配 / 共 {n} 个文件"; error "加载失败: {err}" |
| Buttons | "安装最新" (left, transparent) → `chosen={"latest": True}` & accept; "安装所选" (yes button, accepts with current `chosen` — may be None → treated as latest); "取消" |

Load: async `list_catalog_files({kind, source, slug, id, name, game_version})`.

`selected_extra()` → copy of item + (mod) `instance`, `version` (target vid or "") + if a concrete row chosen: `source`, `version_id = row.id`, additionally `file_id = row.id` when source is curseforge, `filename`.

Data: `list_catalog_files(extra) -> [{id, name, version_number, filename, game_versions:[…], loaders:[…], date, downloads, size, release_type, source, changelog}]`. `get_mods_targets(inst) -> [{label, value}]` (`""` = shared; isolated versions as `"{vid} · 独立 mods"`).

---

## 11. `app/pages/mod_page.py` — `ModManagerPage` ("模组")

### 11.1 Layout
Header card: title "模组管理", subtitle (dynamic: `"启用 {on} · 禁用 {off} · {size} · {instance}[ / {version}]"`, initial "查看与管理已安装的模组"), Pill `"{on}/{total}"` (initial "0 个"). Toolbar: instance ComboBox (130), target ComboBox (190, from `get_mods_targets`), LineEdit "按文件名筛选…" (200), stretch, "打开 mods 文件夹" (FOLDER), "导入 jar" (ADD), "检查更新" (SYNC). Tip: "提示：在版本设置里开启「隔离 Mod」后，各版本会拥有独立 mods 目录，可在此切换查看。"
List card: rows (`_ModRow`, 60 px): letter tile 40, filename, meta `"{size}[ · 已禁用]"`, `SwitchButton` (on text "启用", off "禁用"), DELETE (tooltip "删除").
Empty: filtered-out → `EmptyState(SEARCH, "没有匹配的模组")`; none installed → `EmptyState(TAG, "还没有安装模组，可点右上角「导入 jar」或到「下载」页安装")`.

### 11.2 Actions

| Action | Call | Result |
|---|---|---|
| load / `reload()` | `get_instances()`, `get_mods_targets(inst)`, `get_installed_mod_entries(inst, ver)` | error → `InfoBar.error("读取模组失败", e)` |
| filter text | client-side substring on filename | |
| switch | `enable_mod/disable_mod(inst, filename, ver)` | error `InfoBar.error("切换失败", e)`; always `reload_list()` |
| DELETE | `MessageBox("删除确认", "将删除模组文件「{filename}」，不可恢复。", yes="删除", cancel="取消")` → `delete_mod(inst, filename, ver)` | error `InfoBar.error("删除失败", e)` |
| 打开 mods 文件夹 | `open_mods_folder(inst, ver) -> path` | error `InfoBar.error("打开失败", e)` |
| 导入 jar | `QFileDialog.getOpenFileNames("选择模组 jar", "模组 (*.jar)")` → for each: `fly_to_tasks(import_btn, basename)`; `install_mod(path, inst, extra={"path": p, "instance": inst, "version": ver, "source": "本地"})` | error `InfoBar.error("导入失败", e)` |
| Drag & drop `.jar` files | same as import | |
| 检查更新 | `start_mod_updates(inst)` | error `InfoBar.error("检查更新失败", e)` |
| `showEvent` | if clipboard has modrinth/curseforge URL → `InfoBar.info("识别到剪贴板链接", "到「下载」页搜索框粘贴即可安装")` 3000 ms | |

Size format: ≥1 GB "x.x GB", ≥1 MB "x.x MB", ≥1 KB "N KB", else "N B".

Config read: `default_instance`.

---

## 12. `app/pages/global_mods_dialog.py` — `GlobalModsDialog`
(Not opened from any Part-1 page; likely from Settings.)

Title "全局 Mod"; hint "启用的 jar 会在每次启动前链到当前版本的 mods。"; one row per `list_global_mods()` entry: filename + `SwitchButton(enabled)` → `set_global_mod_enabled(filename, on)`; on error switch is reverted and `InfoBar.error("切换失败", e)`. Empty: "还没有全局模组，点「打开文件夹」放入 jar。" Button "打开文件夹" → `open_global_mods()`. Close button "关闭" (cancel hidden). Min width 480.

Data: `list_global_mods() -> [{filename, enabled, bytes}]`; `set_global_mod_enabled -> new filename`; dir = `CONFIG.global_mods_dir` or `ROOT/shared/mods`.

---

## 13. `app/pages/instance_page.py` — `InstancePage` ("实例")

### 13.1 Layout
Title "实例", caption "每个实例相互隔离，放心折腾". Responsive grid (240 px) of `InstanceCard` (240×138) + trailing `NewInstanceCard`.
Card: letter tile 40, name, `"{versions} 个版本"`, Pill "默认" (`name == CONFIG.default_instance`) else "实例" (`#4C8BF5`), caption `mc`, caption `"Java · {java_label or '自动选择'}"`. Icon buttons (right-aligned, in order): 打开实例文件夹 (FOLDER), 存档 / 截图 (PHOTO), 选择此实例使用的 Java (CODE), 重命名 (EDIT), 导出为 .mrpack (SHARE), 删除实例 (DELETE).
`NewInstanceCard`: "＋ 新建实例" / "隔离的版本、模组与存档"; **left-click only** → create.

### 13.2 Actions

| Action | Call | Result |
|---|---|---|
| reload | `get_instances()` | rebuild grid; re-entrancy guarded |
| 新建实例 | `InputDialog("新建实例","实例名称", placeholder="例如：模组生存")` → `create_instance(name)` | error `MessageBox("创建失败", e)`; reload |
| 删除实例 | `MessageBox("删除实例", "确定删除实例「{name}」？其中的存档与配置将一并移除。")` → `delete_instance(name)` | error `MessageBox("删除失败", e)`; reload |
| 重命名 | `InputDialog("重命名实例","新名称", text=name)` → `rename_instance(name, new)` | error `MessageBox("重命名失败", e)`; reload |
| 导出为 .mrpack | `export_modpack(name)` → task (dest `exports/{name}.mrpack`) | |
| 选择 Java | async `java_combo_options(name, True)`; then `ComboDialog("选择 Java", "实例「{name}」启动时使用的 Java。自动选择会按游戏版本匹配（1.19+ 用 17，远古版用 8）。", labels, java_combo_label_for(name, opts))` → `set_instance_java(name, value)`; reload; refresh launch page Java box | scan error `MessageBox("扫描 Java 失败", msg)`; save error `MessageBox("保存失败", e)`; re-entrancy guard |
| 打开实例文件夹 | `open_instance_folder(name)` | error `MessageBox("无法打开", e)` |
| 存档 / 截图 | `SavesDialog(backend, name, "")` | |
| resize | 120 ms debounce reload when column count changes | |

Data: `create_instance/delete_instance/rename_instance` emit `ui_changed`. `export_modpack(instance, dest="") -> task_id` (title `"导出整合包 {inst}"`). Config read: `default_instance`.

---

## 14. `app/pages/saves_dialog.py` — `SavesDialog(backend, instance, version="")`

Title `"存档 · {instance}"`. Kind ComboBox: 存档 / 备份 / 截图 / 崩溃报告 / 日志. `ListWidget` (icon 48 px). Button rows: [打开] [删除存档|删除备份] [把数据包装进所选存档] / [备份存档] [还原备份] [导出为 zip]. Close = "关闭" (cancel hidden). Min width 640.

Enabled state by kind: 删除 → 存档 or 备份 (text "删除备份" for 备份); 把数据包装进所选存档 / 备份存档 / 导出为 zip → 存档 only; 还原备份 → 备份 only; 打开 → always.

| Kind | List source | Row text |
|---|---|---|
| 存档 | `list_saves(inst, ver)` | `"{name}  ({format_size(bytes)})"` with `icon.png` thumbnail |
| 备份 | `list_save_backups(inst, "", ver)` | `"{name}  ({size})"` |
| 截图 | `list_media(inst, "screenshots", ver)` | name, 48 px thumbnail of the image |
| 崩溃报告 | `list_media(inst, "crash-reports", ver)` | name |
| 日志 | `list_media(inst, "logs", ver)` | name |

Selected name = text before `"  ("`.

| Action | Call | Result |
|---|---|---|
| 打开 | 存档 → `open_save(inst, name, ver)`; 备份 → find row → `open_media(path)` (error `MessageBox("打开失败", e)`); media → `open_media(path)` | |
| 删除存档 | `MessageBox("删除存档", "确定删除「{name}」？")` → `delete_save(inst, name, ver)`; reload | |
| 删除备份 | `MessageBox("删除备份", "确定删除备份「{name}」？")` → `delete_save_backup(inst, name, ver)`; reload | |
| 备份存档 | none selected → `MessageBox("未选择","请先在列表里选一个存档。")`; `backup_save(inst, name, ver)` → task; `MessageBox("已开始备份", "「{name}」正在打包，可到下载任务页看进度。")`; error `MessageBox("备份失败", e)` | |
| 还原备份 | `MessageBox("还原备份", "从「{name}」还原存档？\n若同名存档已存在，会另存为「原名-还原」，不会覆盖。")` → `restore_save_backup(inst, name, ver)` → `MessageBox("还原完成", "已还原为存档「{out.name}」。")`; switch kind to 存档; error `MessageBox("还原失败", e)` | |
| 导出为 zip | `QFileDialog.getSaveFileName("导出存档", "{name}.zip", "压缩包 (*.zip)")` → `export_save(inst, name, path, ver)` → `MessageBox("导出完成", "已导出到：\n{out}")`; error `MessageBox("导出失败", e)` | |
| 把数据包装进所选存档 | `get_installed_datapacks(inst)`; none → `MessageBox("没有数据包","先到下载页安装数据包。")`; else inline dialog "选择数据包" with ComboBox, yes "安装" → `install_datapack_into_save(inst, filename, save, ver)` | |

Data: `list_save_backups -> [{name, path, save, bytes, mtime}]` (mtime desc); `list_media -> [{name, path, bytes, mtime}]` (max 200, mtime desc); `restore_save_backup -> {name, path, from}`; `export_save -> path str`; `backup_save -> task_id` (title `"备份存档 {name}"`, result `"已备份到 {zipname}"`); `open_save -> path`; `open_media(path) -> bool`; `install_datapack_into_save -> dest path`.

---

## 15. `app/pages/java_page.py` — `JavaPage` ("Java")

Layout: title "Java", caption "Minecraft 所需 Java 会在启动时自动匹配下载；也可在实例页为每个实例单独指定", button "重新检测" (SYNC). Section "本机环境": `JavaCard` rows (76 px): orange "J" tile, `"Java {major}"`, Pill "可用" `#2FA36B`, caption path. Empty → `EmptyState(CODE, "未检测到 Java，请从下方下载")`. Section "下载新运行时": label "发行版" + vendor ComboBox (`java_vendor_list()` → labels via `java_vendor_label`; default `adoptium`) and 4 tiles (150×128) "Java 8/11/17/21" with notes: 8 "1.16 及以下旧版本", 11 "部分旧模组环境", 17 "1.18 – 1.20.4 推荐", 21 "1.20.5+ 新版本"; each with "下载" button.

| Action | Call | Result |
|---|---|---|
| load / nav reload | `get_java_list(scan_system=False)` (launcher-managed runtimes only) | fill |
| 重新检测 | `get_java_list(False)` then async `get_java_list(True)` (system scan) | error `InfoBar.error("扫描 Java 失败", err)` |
| 下载 | `fly_to_tasks(tile, "J", "#E8862E")`; `download_java(major, vendor=vendor)` → task | |

Data: `get_java_list(scan_system) -> [{name, major: str, path}]`; `java_vendor_list() -> ["adoptium","zulu","microsoft"]`; `java_vendor_label(v)` → "Adoptium Temurin" / "Azul Zulu" / "Microsoft OpenJDK"; `download_java(major, vendor) -> task_id` (title `"下载 Java {major}"` for adoptium, else `"下载 {vendor} Java {major}"`).

---

## 16. Consolidated `BackendAPI` methods used (Part 1), with signatures as called and return shapes

| Method (as called) | Returns / side effects |
|---|---|
| `get_setting(key, default)` | value from `get_settings()` |
| `get_settings()` | dict with keys: `share_libraries, share_assets, download_threads, default_memory_mb, default_resolution[w,h], ms_client_id, curseforge_api_key, ai_mode, ai_gateway_url, ai_base_url, ai_api_key, ai_model, ai_confirm_writes, ai_permission_mode, download_source, community_source, use_system_proxy, feedback_url, feedback_heartbeat, feedback_consent, ui_fly_animation, ui_motion, ui_fly_duration_ms, default_isolation, default_jvm_args, default_priority, update_url, theme_color, ui_dark, ui_background, global_mods_dir, launcher_visibility, gc_preset, download_limit_kbps, auto_check_update, custom_homepage, homepage_mode, window_mode, skip_assets, allow_multi_instance, first_run, show_hidden_versions, offline_skin, default_java, instances_dir, game_dir, root` |
| `save_settings(data)` / `update_settings(data)` | partial update; emits `theme_changed` if theme keys present |
| `set_game_dir(path)` | sets `instances_dir`; `ui_changed`; returns dir |
| `check_update()` | `{ok, current, latest, has_update, message, notes, url, sha256}` |
| `task_title(task_id)` | str |
| `cancel_task(task_id)` | — |
| `call_async(fn, on_ok, on_err)` | background helper |
| `shutdown()`, `terracotta_shutdown()` | — |
| `_download_task_count()` | int |
| `get_instances()` | `[{name, versions, mc, pack, pack_version, mc_version, java, java_label}]` |
| `create_instance(name)`, `delete_instance(name)`, `rename_instance(name, new_name)` | `ui_changed` |
| `open_instance_folder(name)` | — |
| `export_modpack(name)` | task_id |
| `get_accounts()` | `["离线模式", …]` |
| `get_account_rows()` | `[{name, type, uuid, api, avatar, body, active}]` |
| `start_microsoft_login()` | task_id; emits `login_code(code, uri)`, `login_status(text)` |
| `get_installed_versions(instance)` / `(instance, include_hidden=bool)` | `[vid…]` |
| `get_version_list()` / `fetch_version_list()` | `[{version, type, date}]` |
| `install_game(version, loader, loader_version, instance=, extra=)` | task_id; sets `_last_installed` |
| `list_loader_versions(mc_version, loader)` | `[{id, label, stable, …}]` |
| `uninstall_version("inst / vid")` | `ui_changed` |
| `repair_version(instance, version)` | task_id |
| `get_version_settings(instance, version)` | dict (§7.2) |
| `save_version_settings(instance, version, payload)` | merged dict; `ui_changed` |
| `hide_version(instance, version, hidden)` | dict; `ui_changed` |
| `rename_version(instance, version, new_id)` / `copy_version(...)` | new_id; `ui_changed` |
| `open_version_folder(instance, version, which)` | path |
| `create_desktop_shortcut(instance, version)` | path |
| `export_launch_script(instance, version)` | task_id |
| `preflight_launch(instance=, version=, memory_mb=, java=)` | `{ok, items:[{level, code, title, detail}]}` |
| `launch_game(instance=, version=, account=, username=, memory_mb=, width=, height=, java=, extra_game_args=)` | task_id; `game_started/game_exited`, `crash` |
| `build_launch_command(instance=, version=, account=, username=, memory_mb=, width=, height=, java=)` | str |
| `java_combo_options(instance, scan_system)` | `[{label, value}]` |
| `java_combo_label_for(instance, opts)` | label |
| `set_instance_java(instance, value)` | — |
| `get_java_list(scan_system=bool)` | `[{name, major, path}]` |
| `java_vendor_list()` / `java_vendor_label(vendor)` | list / str |
| `download_java(major, vendor=)` | task_id |
| `cached_news()` / `fetch_news()` | `[{title, body, version, image, date}]` |
| `get_total_playtime()` / `get_all_playtime()` / `format_playtime(sec)` | int / `{inst: {total, versions, sessions}}` / str |
| `search_mods(query, source, extra)`, `search_modpacks(...)`, `search_shaders(...)`, `search_resourcepacks(...)`, `search_datapacks(...)`, `search_worlds(...)` | list of result rows (§9.4) |
| `list_catalog_files(extra)` | `[{id, name, version_number, filename, game_versions, loaders, date, downloads, size, release_type, source, changelog}]` |
| `get_mods_targets(instance)` | `[{label, value}]` |
| `install_mod(name, instance, extra=)`, `install_modpack(name, source, extra=)`, `install_shader/install_resourcepack/install_datapack/install_world(name, instance, extra=)` | task_id |
| `get_installed_mods(inst, ver)` / `get_installed_mod_entries(inst, ver)` | `[str]` / `[{filename, enabled, bytes, path}]` |
| `get_installed_shaders/resourcepacks/datapacks(inst)` | `[str]` |
| `get_installed_modpacks(inst)` | `[str]` (0 or 1) |
| `enable_mod/disable_mod(inst, filename, ver)` | new filename; `ui_changed` |
| `delete_mod(inst, filename, ver)`, `delete_shader/resourcepack/datapack(inst, filename)`, `delete_modpack(inst, filename)` | `ui_changed` |
| `open_mods_folder(inst, ver)` | path |
| `start_mod_updates(inst)` | task_id |
| `catalog_favorites()` / `toggle_favorite(item)` | `[{name, source, slug, id}]` |
| `list_saves(inst, ver="")` | `[{name, path, icon, bytes, mtime}]` |
| `delete_save(inst, name, ver)` | `ui_changed` |
| `open_save(inst, name, ver)` | path |
| `backup_save(inst, name, ver)` | task_id |
| `list_save_backups(inst, "", ver)` | `[{name, path, save, bytes, mtime}]` |
| `restore_save_backup(inst, backup_name, ver)` | `{name, path, from}`; `ui_changed` |
| `delete_save_backup(inst, backup_name, ver)` | `ui_changed` |
| `export_save(inst, name, dest, ver)` | path |
| `list_media(inst, kind, ver)` (`screenshots|crash-reports|logs`) | `[{name, path, bytes, mtime}]` |
| `open_media(path)` | bool |
| `get_installed_datapacks(inst)` + `install_datapack_into_save(inst, filename, save, ver)` | list / dest path |
| `list_global_mods()` / `set_global_mod_enabled(filename, on)` / `open_global_mods()` | `[{filename, enabled, bytes}]` / new name / — |

---

## 17. Config / settings keys touched by Part-1 pages

**Via `backend.get_setting` / `get_settings` / `save_settings`:**
`first_run`, `auto_check_update`, `launcher_visibility`, `theme_color`, `ui_dark`, `ui_background`, `ui_fly_animation`, `ui_fly_duration_ms`, `game_dir` (FirstRun), `download_source`, `default_memory_mb`, `default_isolation` (FirstRun apply).

**Direct `CONFIG.get` reads:**
`ui_section_members`, `ui_nav_pinned`, `ui_nav_order`, `ui_nav_hidden`, `ui_sidebar_width`, `memory_mb`, `width`, `height`, `default_instance`, `homepage_mode`, `custom_homepage`, `ui_layout`, `ui_layouts`, `ui_layout_profile`, `show_hidden_versions`, `skip_assets`, `ui_motion` (via `motion_prefs`).

**Direct `CONFIG.set` + `save` writes:**
`ui_section_members`, `ui_nav_pinned`, `ui_nav_order`, `ui_sidebar_width`, `memory_mb`, `width`, `height`, `ui_layout`, `ui_layouts`, `ui_layout_profile`, `show_hidden_versions`.

**Written by backend on behalf of these pages:**
`catalog_favorites` (toggle_favorite), `instances_dir` (set_game_dir), `default_instance` (launch_game, install_modpack), `first_run` (save_settings).

I'm double-checking the crash report keys needed (instance, version, title, headline, detail, help) and confirming other utility functions like shortcut creation and motion preference checks are in scope and behaving as expected.

I think I've gathered enough context on the backend now, including instance install tracking, dialog guards, and version fetching. Now I'm planning the structure for the markdown documentation, starting with global architecture notes on BackendAPI signals and the task model, then working through MainWindow, chrome/widgets, the launch page, and version handling.

For MainWindow specifically, I'm noting the window title format and dimensions, the top-level navigation keys (launch, download, ai, more, tasks) with their sub-sections like download types and the "more" menu items, plus the relevant config keys for section membership and pinned navigation items.

I still need to cover the sidebar's drag-and-drop reordering and pinning behavior, its resize handle with the width persisted to config, the "编辑布局" button that toggles edit mode on the launch canvas, and the download task count badge shown on the sidebar button.

Now I'm working out the download dock's placement and sizing logic, floating at the bottom center of the content area only when active tasks exist and the visible page isn't settings/instance/tasks/feedback, with width constrained between 420 and 640px. I'm also wiring up the finish signal to show success/error notifications while filtering out noise from login and launch-related titles, and chaining a delayed "installation complete, launching game" message after install tasks succeed.

Then I'm mapping out the rest of the app's reactive behavior: theme changes trigger palette and background updates (checking the background file exists first), UI setting changes debounce into a forced page refresh, task counts drive the badge, and game start/exit events control window visibility (keep, close, hide, hide-and-reopen, or minimize) along with quit-on-exit logic. Finally there's the boot sequence—after a short delay, showing the first-run dialog if needed, applying or rejecting its settings, then prompting for feedback consent.

I'm now tracking the update-check flow (async check on boot showing an info bar if a new version exists), cleanup on window close (shutting down the terracotta service, feedback heartbeat, and backend), throttled per-page reload logic keyed by what changed (version, java, or specific pages), and how navigation clicks route to the right page or pinned sub-item.

I'm also noting how clipboard detection is wired into the catalog and mod pages via their showEvent handlers, the shape of the update-check response object, and which settings keys (like launcher_visibility, theme_color, ui_fly_animation) get read through get_setting. Now I'm moving into the LaunchPage controls and its data.

I'm mapping out the data flows for LaunchPage: instance/account/version listings, Java combo options, the preflight and launch task pipeline (preflight_launch, launch_game, cancel_task, build_launch_command), Microsoft login flow signals (code, URI, status), progress/log/finished/crash task events with their message formats, and the news feed shape from fetch_news/cached_news.

I'm also cataloging playtime tracking (per-instance and aggregate stats plus a formatter), the config keys stored for memory/window/instance/homepage/layout settings, and the version management API surface -- fetching and filtering version lists by type and date, installing/uninstalling/repairing versions per instance, and version visibility settings.

I'm mapping out the remaining feature areas: version-related actions like renaming, copying, opening folders, and exporting launch scripts, along with the loader install wizard's version listing and payload structure, the version setup screen's defaults and account/isolation options, the catalog page as a whole, and the file-picker's targets and instance listing.

Now moving into mod management: fetching installed mod entries with their enabled state and paths, toggling and deleting mods, installing from local files, and triggering mod update tasks, plus the global mods dialog for enabling/disabling mods across instances.

For instances, I'm covering creation, deletion, renaming, modpack export, async Java version selection, and folder access, then turning to the saves dialog which lists save files and their backups with metadata like size and modification time.

I'm outlining the media listing (capped at 200 items, sorted by recency), save/media opening, backup and restore flows with a "backup started" notification, save export, and datapack installation into saves. Then covering the Java page's system scan, vendor list (Adoptium, Zulu, Microsoft), and download task with a vendor-aware title.

Since this is a read-only response, I'll present it directly as markdown text in my reply rather than writing to a file, matching the user's instruction to output markdown only.