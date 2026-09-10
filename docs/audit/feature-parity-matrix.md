I have completed the read-only survey. No repository files were modified (one temp file I created during analysis was removed immediately).

---

# PyMCL — FEATURE PARITY MATRIX

**Repo root audited:** `C:\Users\Administrator\Downloads\Compressed\PyMCL-main\wt-sonnet45`
**Snapshot caveat:** the tree was being edited by another process *during* this audit. `app/**`, `bridge/**`, `wpf/**` and `eziapp/src/pages/**` are all stamped `2026-09-07 22:21:09`, but `eziapp/src/dom.ts`, `fmt.ts`, `store.ts`, `ui.ts`, `styles/main.css` were rewritten at `22:24–22:29`. Section B therefore describes a tree that is **mid-refactor**, and I call that out explicitly because it is the single largest correctness problem in eziapp right now.

---

# A. Python reference — page-by-page feature inventory

## A.0 Application shell — `app/main_window.py` + `app/pcl_chrome.py`

### A.0.1 Navigation model (module-level data in `main_window.py`)

```python
_TOP_KEYS = ("launch", "download", "ai", "more", "tasks")

_NAV_SPECS = {
  "launch":   (FIF.PLAY,           "启动"),
  "download": (FIF.DOWNLOAD,       "下载"),
  "ai":       (FIF.CHAT|FIF.HELP,  "AI 助手"),
  "more":     (FIF.MORE|FIF.MENU,  "更多"),
  "tasks":    (FIF.CLOUD_DOWNLOAD, "下载任务"),
}

_SUB_DEFAULT_MEMBERS = {
  "download": ["version","mod","modpack","datapack","resource","shader","world","java"],
  "more":     ["instance","mods","account","multiplayer","servers","playtime","feedback","settings"],
}

_SUB_TITLES = {
  "version":"原版游戏", "mod":"Mod", "modpack":"整合包", "datapack":"数据包",
  "resource":"资源包", "shader":"光影包", "world":"世界", "java":"Java",
  "instance":"实例", "mods":"模组", "account":"账号", "multiplayer":"联机",
  "servers":"服务器", "playtime":"时长", "feedback":"反馈", "settings":"设置",
}

_SUB_FACTORIES = { <key> -> "_make_<key>_page" }   # 16 lazy factories
```

Helpers: `section_members_from_config()`, `pinned_from_config()`, `nav_items_from_config()`, `sidebar_width_from_config()` (clamped 140–320, default `SIDE_W = 188`), `sub_title(key)`.

### A.0.2 Sidebar customisation behaviour (the exact contract to re-implement)

Persisted config keys (all in `config.json`):

| Key | Meaning |
|---|---|
| `ui_nav_order` | ordered list of top-level sidebar entries (mix of `_TOP_KEYS` and pinned sub-keys) |
| `ui_nav_pinned` | sub-page keys promoted out of their group into the sidebar root |
| `ui_nav_hidden` | hidden top-level entries |
| `ui_sidebar_width` | integer px, clamped 140–320 |
| `ui_section_members` | `{"download":[...], "more":[...]}` — which sub-pages live in which group |

Behaviour:

* **Reordering** — drag a nav button onto another; `PclSideBar` shows a 2 px drop-line indicator above/below the hover target and emits `reorderRequested(key, target, before)`. `MainWindow._on_sidebar_reorder` rewrites `ui_nav_order` via `_sidebar_sequence()` / `_write_sidebar_sequence()`.
* **Pinning / unpinning** — drag uses MIME type `application/x-pymcl-nav`. Dropping a *sub-page* button (from `DownloadCatBar` in `download_hub.py`) onto the sidebar fires `pinRequested` / `pinAtRequested(key, target, before)` → `_pin_nav` / `_pin_nav_at`, which calls `_take_from_section(key)` to remove it from `ui_section_members` and appends to `ui_nav_pinned`. Dragging a pinned item back onto the category bar unpins it (`DownloadCatBar` drop handler → `_unpin_nav`).
* **Hide / show** — `SidebarEditorDialog` (see A.3.7) toggles `ui_nav_hidden`; `_rebuild_sidebar()` re-creates buttons.
* **Groups** — `download` and `more` render as expandable groups with an animated chevron; expand/collapse is a height animation in `PclSideBar`. Group membership is editable via `SectionEditorDialog` (minimum 1 member per section enforced).
* **Width** — `_SideResizer` (5 px grip on the right edge, `MIN_W = 140`, `MAX_W = 320`) drags live; on release `widthCommitted` → `_on_side_width` → `save_settings({"ui_sidebar_width": w})`.
* **"编辑布局" button** at the sidebar bottom emits `editLayoutRequested`.

### A.0.3 `pcl_chrome.py` resources (names to reuse)

* `Theme` — dark/light palettes with fields `bg, card, line, text, muted, title, hover, chip, btn_bg, row_hover, row_line`, plus fixed accents `green = #2E9B6B`, `green_deep = #1E7A52`; `_version` counter and `background_active` flag.
* Constants `TITLE_H = 40`, `SIDE_W = 188`.
* Functions `ensure_theme_surfaces()`, `paint_theme_surfaces()`, `form_label()`, `ghost_btn_qss()`, `row_qss()`, `chip_qss()`, `fade_stack_to()`.
* Widgets `PclTitleBar` (brand "PyMCL", minimise + close only — no maximise), `PclNavButton`, `_SideResizer`, `PclSideBar`.
* QSS strategy: **ID-selector-only** stylesheets so nothing cascades into child widgets; theme reapplication short-circuits on the tuple `(dark, color, image)`.

### A.0.4 `MainWindow` behaviours

* Lazy page construction: `_ensure_top(key)` / `_ensure_sub(key)` + 17 `_make_*_page()` factories + `@property` accessors; reverse map `_by_obj` keyed by `id(page)`.
* `apply_theme()` / `_apply_theme_impl()` / `_paint_page_surfaces()` / `_apply_background()`.
* `_boot_reload()`, `_refresh_if_stale()`, `_reload_page()` (1.2 s dedupe), `_refresh_pages()`.
* `_boot_extras()` — first-run dialog, feedback consent prompt, auto update check.
* Game lifecycle: `_on_game_started` / `_on_game_exited` honour setting `launcher_visibility` ∈ `{keep, minimize, hide, hide_reopen, close}`.
* Task badge: `_create_task_badge`, `_update_task_badge`, `_place_task_badge`.
* Floating download dock: `_place_download_dock()` — hidden on pages `{settings, instance, tasks, feedback}`.
* Fly animation entry point `fly_to_tasks()`; deferred launch `queue_launch_after()` / `_launch_installed()`.
* `closeEvent` → `backend.terracotta_shutdown()`, stop heartbeat, `backend.shutdown()`.
* **backend calls:** `get_setting`, `get_settings`, `save_settings`, `check_update`, `call_async`, `task_title`, `terracotta_shutdown`, `shutdown`, `_download_task_count`.

---

## A.1 The dashboard / layout system

### A.1.1 `app/layout_model.py`

* `LAYOUT_VERSION = 1`
* `CARD_MIN_SIZE` (px) — `banner (340,150)`, `config (330,300)`, `log (260,180)`, `news (220,180)`, `quick (220,150)`, `notes (180,130)`, `playtime (220,130)`, `tasks (220,130)`; `FALLBACK_MIN = (200,120)`.
* `LayoutItem(type, x, y, w, h, item_id, z, hidden, settings)` — geometry is **proportional 0..1**; converters `geometry_px(host_size)` / `set_geometry_px(rect, host_size)`.
* `LayoutDoc(items, grid)` with `normalize()`, `clone()`, `next_z()`, `visible_items()`.
* `default_doc()`:

```python
LayoutDoc([
  LayoutItem("banner", 0.0,   0.0,   1.0,   0.26,  item_id="banner-main", z=0),
  LayoutItem("config", 0.0,   0.275, 0.315, 0.725, item_id="config-main", z=1),
  LayoutItem("log",    0.325, 0.275, 0.41,  0.725, item_id="log-main",    z=2),
  LayoutItem("news",   0.745, 0.275, 0.255, 0.725, item_id="news-main",   z=3),
], grid=8)
```

* Persistence API: `load_active_doc()`, `save_active_doc(doc)`, `active_profile()`, `list_profiles()`, `save_profile(name)`, `activate_profile(name)`, `delete_profile(name)`, `reset_to_default()`, `export_doc(doc, path)`, `import_doc(path)` (silently drops unknown card types). Config keys: `ui_layout`, `ui_layouts`, `ui_layout_profile`.

### A.1.2 `app/dashboard.py`

* `GRID_CHOICES = [0, 4, 8, 16, 24]`; `_ADD_DEFAULT` gives each card type its spawn geometry.
* `CardSpec(key, title, icon, desc, make_body, single, chrome, on_settings, on_removed)`.
* `DashboardCard` — header (icon + title + optional ⚙ settings button + ✕ remove button), body inside a `QScrollArea`, `_Shield` overlay to swallow child interaction during drag/resize, 8 `_Grip` handles (`n, s, e, w, ne, nw, se, sw`).
  * Drag: `_drag_begin` / `_drag_move` / `_drag_end`; resize: `_resize_by`; snapping: `_snap()` to the active grid; `_take_top()` raises z; `_commit_geometry()` writes proportional geometry back to the `LayoutItem`.
* `_CardPalette` — a `MessageBoxBase` "添加卡片" picker listing every registered `CardSpec` (with icon + description; `single=True` specs are disabled once placed).
* `DashboardCanvas` — signal `layout_changed`, persisted with a **300 ms debounce**.
  * Toolbar: **添加卡片** / **吸附** combo (`自由, 4px, 8px, 16px, 24px`) / **适应窗口** / **重置布局** / **完成**.
  * Linked resize: `_link_followers()` + `_resize_linked()` make neighbouring cards follow an edge drag, with blocker rules `_LINK_GAP_MAX = 28`, `_LINK_OVERLAP_MAX = 8`.
  * `add_card`, `remove_card`, `_find_free_spot`, `fit_to_window`, `reset_layout`, `current_doc`, `refresh_cards`; grid is painted from a cached `QPixmap` in `paintEvent`.

### A.1.3 Card registry — `app/pages/home_cards.py`

`build_registry(page)` returns 8 `CardSpec`s:

| key | body class | controls |
|---|---|---|
| `banner` | `BannerBody` | creates `page.banner`, launch button (170×46), stop button, `SmoothProgressBar`, status label |
| `config` | `ConfigBody` | `instance_box`, `version_box`, `account_box`, `java_box`, `username_edit`, `memory_slider` (512–32768) + `memory_label`, `width_spin` (320–7680), `height_spin` (240–4320), `server_edit`, buttons **此版本设置…**, **刷新新闻**, **使用微软账户登录…** |
| `log` | `LogBody` | `log_edit` (`maxBlockCount = 5000`), **复制启动命令** |
| `news` | `NewsBody` | cached/fetched Minecraft news list |
| `quick` | `QuickBody` + `QuickSettingsDialog` | 18 `QUICK_TARGETS` nav shortcuts with icons; per-card configurable via the settings ⚙ |
| `notes` | `NotesBody` | free-text scratchpad, 600 ms autosave |
| `playtime` | `PlaytimeBody` | `get_total_playtime`, `get_all_playtime`, `format_playtime` |
| `tasks` | `TasksBody` | live task mini-list |

Helpers: `QUICK_TARGETS`, `_QUICK_LABELS`, `quick_label(key)`, `quick_icon(key)`.

---

## A.2 Pages

### A.2.1 LaunchPage — `app/pages/launch_page.py` (nav key `launch`, title 启动)

The launch page **is** the dashboard canvas: it hosts `DashboardCanvas` with `build_registry(self)`.

* Controls: everything in A.1.3 plus the canvas toolbar.
* Server direct-connect: text typed into `server_edit` is parsed into `--server` / `--port` game args.
* Dialogs opened: `VersionSetupDialog`, `DeviceCodeDialog`, `CrashDialog`.
* **backend:** `get_instances`, `get_accounts`, `get_account_rows`, `get_installed_versions`, `java_combo_options(instance, scan_system)`, `java_combo_label_for`, `set_instance_java`, `preflight_launch(instance, version, memory_mb, java)`, `launch_game(instance, version, account, username, memory_mb, width, height, java, extra_game_args)`, `cancel_task`, `build_launch_command(...)`, `start_microsoft_login`, `cached_news`, `fetch_news`, `call_async`.

### A.2.2 VersionPage — `app/pages/version_page.py` (`version`, 原版游戏)

* Card grid of downloadable versions (`VersionCard`, 216×132), search box, `Pivot` tabs `all / release / snapshot / old_alpha`, instance combo, checkboxes **显示隐藏** and **完成后启动**.
* Paging: `_limit = 24`, "+80" on demand.
* Installed list with per-row **设置** button and **更多** `RoundMenu`: 打开游戏文件夹 / 打开 mods / 打开 saves / 打开截图 / 存档管理… / 重命名 / 复制 / 隐藏 / 创建桌面快捷方式 / 导出启动脚本. Selected-row actions: **卸载**, **修复**.
* Dialogs: `InstallWizard`, `VersionSetupDialog`, `SavesDialog`, `InputDialog`.
* **backend:** `get_instances`, `get_version_list`, `fetch_version_list`, `get_installed_versions(instance, include_hidden)`, `install_game(version, loader, loader_version, instance, extra)`, `create_desktop_shortcut`, `export_launch_script`, `open_version_folder`, `rename_version`, `copy_version`, `get_version_settings`, `hide_version`, `uninstall_version`, `repair_version`.

### A.2.3 Catalog pages — `app/pages/catalog_page.py` (one class, six pages)

`PclCatalogPage` is parameterised by a SPEC dict and reused as **ModPage / ModpackPage / DatapackPage / ResourcePackPage / ShaderPage / WorldPage** (`MOD_SPEC`, `MODPACK_SPEC`, `RESOURCE_SPEC`, `SHADER_SPEC`, `DATAPACK_SPEC`, `WORLD_SPEC`). Each SPEC carries `object_name` and the *names* of the search / install / list-installed / delete backend methods plus a type-filter list.

Controls: name filter, 来源 combo (`全部 / Modrinth / CurseForge`), 版本 `EditableComboBox`, 类型 combo, **搜索**, **重置条件**, mode toggle **浏览 / 已安装**, installed-version combo (mods only), per-row **收藏** toggle, **检查更新** (mods only), enable/disable switch on installed mods, delete.
Extras: **drag-and-drop** file install onto the page; clipboard link auto-detection in `showEvent`; `FilePickDialog` for build selection; datapack installs prompt for a target save via `ComboDialog`.

**backend:** `search_*`, `install_*`, `get_installed_*`, `delete_*`, `get_installed_mod_entries`, `enable_mod`, `disable_mod`, `start_mod_updates`, `toggle_favorite`, `catalog_favorites`, `list_saves`, `get_installed_versions`, `get_instances`, `call_async`, `start_task`.

### A.2.4 ModManagerPage — `app/pages/mod_page.py` (`mods`, 模组)

Instance combo, target-directory combo (`get_mods_targets`), filename filter, buttons **打开 mods 文件夹** / **导入 jar** / **检查更新**, per-row `SwitchButton` + delete, drag-and-drop `.jar` install.
**backend:** `get_instances`, `get_mods_targets`, `get_installed_mod_entries`, `enable_mod`, `disable_mod`, `delete_mod`, `open_mods_folder`, `install_mod`, `start_mod_updates`.

### A.2.5 InstancePage — `app/pages/instance_page.py` (`instance`, 实例)

`InstanceCard` grid (240×138) with six action buttons: open folder, saves, java, rename, export, delete; plus a `NewInstanceCard` tile.
**backend:** `get_instances`, `create_instance`, `delete_instance`, `rename_instance`, `export_modpack`, `java_combo_options`, `java_combo_label_for`, `set_instance_java`, `open_instance_folder`.

### A.2.6 JavaPage — `app/pages/java_page.py` (`java`, Java)

`JavaCard` list, vendor `ComboBox` fed by `java_vendor_list()` / `java_vendor_label()`, download tiles for majors **8 / 11 / 17 / 21** each with an explanatory NOTE, and **重新检测**.
**backend:** `get_java_list(scan_system)`, `download_java(major, vendor)`.

### A.2.7 AccountPage — `app/pages/account_page.py` (`account`, 账号)

Skin body preview (140×260); saved-account list with **使用** / **删除** and a type pill (`microsoft / authlib / nide8 / offline`); four login flows:
1. Microsoft device-code (`DeviceCodeDialog`),
2. authlib-injector (preset combo + API + user + password),
3. Nide8 统一通行证 (server id + user + password),
4. offline (name + skin combo).

**backend:** `authlib_presets`, `get_account_rows`, `remove_account`, `set_active_account`, `add_offline_account`, `start_microsoft_login`, `start_authlib_login(api, user, pw)`, `start_nide8_login(sid, user, pw)`, `call_async`.

### A.2.8 MultiplayerPage — `app/pages/multiplayer_page.py` (`multiplayer`, 联机)

Terracotta P2P. State pill, LAN hint text, firewall card (**允许访问** / **打开设置**), room card (click to copy the invite code), player list, and a **dynamic action card per state**: `unsupported, missing, idle, launching, waiting, host-scanning, host-starting, host-ok, guest-connecting, guest-starting, guest-ok, exception, fatal`. Polls every **1200 ms**.
**backend:** `terracotta_snapshot`, `terracotta_prepare`, `terracotta_host`, `terracotta_join`, `terracotta_idle`, `terracotta_enter_world`, `terracotta_direct_connect`, `terracotta_allow_firewall`, `terracotta_open_firewall_settings`, `lan_hint`, `task_title`.

### A.2.9 ServersPage — `app/pages/servers_page.py` (`servers`, 服务器)

`QTableWidget` with columns 名称 / 地址 / 端口 / 描述 / 操作; instance combo; **添加服务器** / **导入** / **导出**; per-row **编辑** / **删除**; `EmptyState` swapped in via a `QStackedWidget`.
**backend:** `get_instances`, `list_servers`, `add_server`, `update_server`, `delete_server`, `import_servers`, `export_servers`.

### A.2.10 PlaytimePage — `app/pages/playtime_page.py` (`playtime`, 时长)

Total card + per-version cards, **清除记录**.
**backend:** `get_playtime`, `get_all_playtime`, `format_playtime`, `clear_playtime`.

### A.2.11 FeedbackPage — `app/pages/feedback_page.py` (`feedback`, 反馈)

Category combo (from `mclauncher.feedback_defaults.CATEGORIES`), 联系方式, 标题, 正文, **附带本机配置** checkbox, **发送反馈**; FAQ list; sysinfo preview with **重新采集**; recent submission history.
**backend:** `help_articles`, `help_article`, `collect_sysinfo(force, scan_system_java)`, `sysinfo_text`, `feedback_history`, `submit_feedback(category, title, body, contact, include_sysinfo)`.

### A.2.12 SettingsPage — `app/pages/settings_page.py` (`settings`, 设置) — 48 KB

`SettingCardGroup`s: **版本隔离与存储 / 界面 / 个性化布局 / 下载与性能 / 账号与下载源 / 维护 / AI 助手 / 反馈与诊断**. `collect()` returns ~38 keys.
Notable: the **个性化布局** group is the entry point to `SidebarEditorDialog`, `SectionEditorDialog`, layout-profile switch / save-as / delete / export / import.
**backend:** `get_settings`, `save_settings`, `get_setting`, `set_game_dir`, `available_languages`, `get_language`, `save_theme`, `list_themes`, `load_theme`, `delete_theme`, `check_update`, `start_self_update`, `cleaner_preview`, `cleaner_apply`, `export_modpack`, `test_ai_connection`, `detect_official_launcher`, `official_launcher_dir`, `scan_official_versions`, `migrate_official_launcher`, `get_smart_recommendation`, `call_async`.

### A.2.13 TasksPage + DownloadDock — `app/pages/tasks_page.py` (`tasks`, 下载任务)

`_TASK_ICONS` prefix table maps a task title prefix to an icon; `split_progress_message()` splits `"状态  |  速度"`. `TaskCard`: progress bar, status line, speed, expandable log, cancel. `DownloadDock`: floating bottom bar with a log toggle. `TasksPage`: **清除已完成**.
**backend:** `cancel_task`; signals `task_added`, `progress`, `log`, `finished`.

### A.2.14 AIPage — `app/pages/ai_page.py` (`ai`, AI 助手) — 40 KB

Multi-chat sidebar (**新对话** / **删除对话**), streaming bubbles with markdown rendering (`_md`), `ToolLine` progress rows, `ConfirmCard`, `AskCard` (radio / checkbox / "其他" free text), `PermissionDialog` (switch `ai_confirm_writes` + combo `ai_permission_mode`), `perm_combo` (`标准 / 完全访问 / 免确认`), quick-prompt chips, **停止** / **重试**, `Esc` shortcut, `Enter` = send / `Shift+Enter` = newline, message queueing while busy. Uses `mclauncher.ai.agent.run_agent` and `mclauncher.ai.store`.
**backend:** `get_settings`, `save_settings`, `progress` / `finished` signals, `_ui_launch` injection.

### A.2.15 Download hub / "更多" hub — `app/pages/download_hub.py`

`SlideHStack` (260 ms slide), `NAV_MIME = "application/x-pymcl-nav"`, `_DragButton`, `DownloadCatBar` (lazily built buttons, animated selection indicator, accepts drops to *unpin*), `DownloadSection` / `MoreSection` with `bind / add_page / ensure_first / show_page / has_page / current_page`.

---

## A.3 Dialogs

### A.3.1 `crash_dialog.py`
`CrashDialog`: title/headline, scrollable detail text, help footer, suggested-action buttons driven by `backend.apply_crash_action(action, report)`, plus **重新启动** / **查看输出** / **导出错误报告** / **发送给开发者** / **确定**. Also exports `show_launcher_error(...)`.
**backend:** `apply_crash_action`, `export_crash_report`, `open_crash_file`, `submit_crash_report`.

### A.3.2 `saves_dialog.py`
`SavesDialog`: kind combo **存档 / 备份 / 截图 / 崩溃报告 / 日志**, thumbnail tiles, actions **打开** / **删除** / **把数据包装进所选存档** / **备份存档** / **还原备份** / **导出为 zip**.
**backend:** `list_saves`, `list_save_backups`, `list_media`, `open_save`, `open_media`, `delete_save`, `delete_save_backup`, `backup_save`, `restore_save_backup`, `export_save`, `get_installed_datapacks`, `install_datapack_into_save`.

### A.3.3 `install_wizard.py`
Primary loader combo **无 / Fabric / Forge / Quilt / NeoForge**, loader-version combo, OptiFine checkbox + version combo, LiteLoader checkbox, `skip_assets` checkbox. `payload()` produces the `extra` dict for `install_game`.
**backend:** `list_loader_versions(mc_version, loader)`.

### A.3.4 `version_setup.py`
`VersionSetupDialog` — 20 form rows: 隔离 / 内存 / Java / GC / JVM 参数 / 游戏参数 / 绑定账号 / 统一通行证 / 认证服 / 服务器 / 端口 / 窗口标题 / 窗口模式 / 窗口宽度 / 窗口高度 / 离线皮肤 / 启动前 / 等待 / 退出后 / 优先级.
**backend:** `get_version_settings`, `save_version_settings`, `java_combo_options`, `get_accounts`.

### A.3.5 `global_mods_dialog.py`
Per-file enable switch + **打开文件夹**.
**backend:** `list_global_mods`, `set_global_mod_enabled`, `open_global_mods`.

### A.3.6 `first_run.py`
Game directory picker, download source, memory, default isolation.
**backend:** `set_game_dir`, `get_settings`, `save_settings`.

### A.3.7 `layout_settings.py`
* `SidebarEditorDialog` — order up/down, per-entry visibility checkbox, pinned sub-page list with **取消固定**, width `SpinBox` 140–320, **恢复默认侧栏**.
* `SectionEditorDialog` — move a sub-page between **下载栏** and **更多栏**, reorder, **固定到侧栏** toggle, **恢复默认分区**; enforces ≥ 1 member per section.
* Module helpers: `default_profile_label`, `profile_labels`, `switch_profile`, `save_current_as_profile`, `delete_profile`, `export_current_layout`, `import_layout_file`.

### A.3.8 `file_pick.py`
`FilePickDialog` — MC-version filter, loader filter, install-target combos (instance + version, for mods), paginated file rows (`PAGE = 80`), **安装最新** shortcut.
**backend:** `list_catalog_files`, `get_mods_targets`, `get_instances`.

---

## A.4 Shared UI helpers (names to port)

* `app/widgets.py` — `InputDialog`, `ComboDialog`, `DeviceCodeDialog`, `prompt_feedback_consent(parent)`, `PALETTE` (8 colours) + `pick_color(name)`, `grid_columns(scroll, page, card_w, spacing=12, gutter=8)`, `IconTile`, `Pill` (`set_color`, dynamic property `pymclKeepBg`), `ThumbnailTile` (`_ThumbHub` / `_ThumbJob`, `_THUMB_PIXCACHE` capped at 240, max 4 threads), `BannerWidget` (animated glow, 90 ms tick, `set_info(title, subtitle)`), `EmptyState`.
* `app/motion.py` — `fade(widget, start, end, ms, on_done)`, `slide_in(widget, dy, ms)`, `tween(setter, start, end, ms, on_done)`, `pop(widget, scale=1.35, ms=260)`, `SmoothProgressBar` (240 ms OutCubic).
* `app/fly_anim.py` — `FlyBall` (`CANVAS=48`, `START_SIZE=44`, `END_SIZE=14`), `Ripple` (`MAX_R=24`, `DURATION=420`), `pulse_widget(widget, duration=220)`, `fly_to(window, source, letter, color, target_key="tasksPage", on_landed, duration=620, target=None)` with quadratic Bézier `_bezier` and `_clamp_control` (arc clamped 48–150 px).
* `app/motion_prefs.py` — `ui_motion_ok()` reads `CONFIG["ui_motion"]` (default `True`); deliberately **not** tied to the Windows animation flag.
* `app/ui_alive.py` — `widget_alive(widget)` (shiboken `isValid` + `_dismissed` flag) and `guard(widget, fn)` used to drop `call_async` callbacks after teardown.

---

# B. eziapp coverage — `eziapp/src/`

## B.0 CRITICAL: the shared layer was replaced and no page was migrated

`dom.ts`, `fmt.ts`, `store.ts` and `ui.ts` are a **new** API. `main.ts` and all 15 files under `pages/` still call the **old** API. This is a hard TypeScript build failure, not a style nit:

| Old API used by `main.ts` / `pages/*.ts` | Current `store.ts` / `ui.ts` |
|---|---|
| `store.setInstances / setVersionList / setJavaList / setAccounts / setAIChats` | only `setSettings`, `patchSettings` |
| `store.versionList / javaList / aiChats / aiActiveId / activeAccount` | `versions`, `javas`, (no AI state at all) |
| `store.currentInstance / currentVersion / currentAccount / currentUsername / currentMemory / currentWidth / currentHeight / currentJava` | single `store.pick { instance, version, account, username, java, memory, width, height }` + getters `instance`, `account` |
| `store.subscribe(fn)` / `store.notify()` | topic-based `store.on(topic, fn)` / `store.emit(...topics)` |
| `store.updateTask(id, patch)`, `TaskInfo.taskId`, `TaskInfo.finishedMessage` | `store.patchTask(id, patch)`, `TaskInfo.id`, `TaskInfo.done` |
| `store.bridgeConnected` (set in `ui.ts` itself), `store.bridgeUrl` (set in `bridge.ts`, read in `feedback.ts`) | `store.bridgeState: 'connecting' \| 'online' \| 'offline'` — neither property exists |
| `type AIChat` exported from `store` | not exported |
| `toast(msg, 'success')` | `toast(title, body, kind, ms)` → the kind string lands in the *body* slot |
| `confirmDialog`, `formDialog`, `inputDialog` | `confirm`, `form`, `prompt` |
| `registerPageCleanup`, `clearPageCleanups` | `onLeave`, `runCleanups` |
| `showLoading`, `showEmpty`, `showError` | `spinner`, `empty`, `skeleton` (no retry-button variant) |
| `preflightDialog`, `crashDialog` | **deleted** — no replacement |
| `initBridgeLifecycle(onReady)` | **deleted** |
| `applyTheme(dark)`, `applyAppearance(settings)` | `applyAppearance()` (no args, reads `store.settings`) |
| `escapeHtml`/`formatBytes`/`errorMessage` from `pages/common.ts` | duplicated in `fmt.ts` as `bytes`, `errMsg`, … ; `common.ts` still exists |
| `flyToTasks` target `.nav-item[data-page="tasks"]` (main.ts markup) | new `ui.ts` queries `.nav-item[data-id="tasks"]` |

Also: `ui.ts` `applyAppearance` now reads `--sidebar-w` / clamp 150–340 / `ui_scale_percent`, while `main.ts` writes `--sidebar-width` and clamps 140–320.

Everything below describes the pages **as written** (i.e. against the pre-refactor shared layer).

## B.1 `main.ts` — shell

* Static sidebar: `launch`, group `downloads` with 8 children (`vanilla, mods-catalog, modpacks, datapacks, resourcepacks, shaders, worlds, java`), `ai`, group `more` with 9 children (`instances, mods, accounts, multiplayer, servers, playtime, feedback, settings, tools`), `tasks` with a badge; a bridge-status footer and a sidebar resizer (140–320 px, persisted via `save_settings({ui_sidebar_width})`).
* `TITLES` map, `page-enter` CSS transition, code-split page imports.
* `loadInitialData()` → `get_settings`, `get_instances`, `get_version_list`, `get_java_list`, `get_account_rows`.
* SSE subscriptions: `task_added`, `progress`, `log`, `finished`, `task_count_changed`, `game_started`, `game_exited`, `ui_changed` (280 ms debounced reload).
* `maybeClipboardHint()` — a one-shot toast if the clipboard holds a modrinth/curseforge URL.

**Missing vs A.0:** no nav reordering, no hide/show, no pinning/unpinning, no group editing, no `ui_nav_order` / `ui_nav_pinned` / `ui_nav_hidden` / `ui_section_members` support, no lazy-page cache/reload-if-stale, no `launcher_visibility` handling, no floating download dock, no window chrome, no i18n (`tr()`), no first-run wizard, no feedback-consent prompt, no auto update check on boot.

## B.2 `bridge.ts`
`BridgeClient` with `setConnection / clearConnection / isConfigured / call<T> / connectEvents / subscribe / close / isConnected`; token in `X-PyMCL-Bridge-Token`, SSE token via `?token=`; config from URL fragment `#pymcl_bridge=<base64>` (then scrubbed from history) or `/bridge-config.json`; 3 s reconnect. Explicitly listens for: `hello, task_added, progress, log, finished, task_count_changed, ui_changed, login_code, login_status, crash, game_started, game_exited, ai.delta, ai.status, ai.confirm, ai.ask, ai.done, ai.fail` — i.e. the full SSE surface of section D.

## B.3 `router.ts`
22 `PageKey`s, `navigate`, `back`, `subscribe`. No URL/hash routing, no per-page scroll restore.

## B.4 `dom.ts` / `fmt.ts` (new, unused by pages)
`dom.ts`: `h(spec, props, ...kids)` with `div.card#id` spec parsing, `div/span/p/text/frag/fill/add/on/qs/qsa/debounce/raf`.
`fmt.ts`: `downloads`, `bytes`, `duration`, `pct`, `splitMsg` (mirrors `split_progress_message`), `relTime`, `errMsg`, `initial`.

## B.5 `ui.ts` (new)
`applyAppearance`, `toast/ok/warn/fail`, `dialog`, `btn`, `busy`, `confirm`, `alert`, `input`, `setOptions`, `toggle`, `form`, `prompt`, `choose`, `menu`, `ctxMenu`, `empty`, `skeleton`, `spinner`, `progress`, `flyToTasks`, `onLeave`, `runCleanups`.
**Missing vs A.4:** no `preflightDialog`, no `crashDialog`, no device-code dialog, no thumbnail cache, no banner glow, no `ComboDialog` equivalent beyond `choose`, no `SmoothProgressBar`-style tween on the log/progress pair.

## B.6 `pages/launch.ts`
A **fixed 7-card CSS grid**: hero (instance/version/account + 启动/停止/版本设置/桌面快捷方式/导出启动脚本 + progress), 启动配置 (username / java / memory / width / height), 快捷入口 (13 hard-coded targets), 新闻 (honours `homepage_mode` = news/custom/blank), 便签 (`localStorage['pymcl.notes']`), 时长与任务, 实时日志.
**backend:** `get_installed_versions`, `cached_news`, `get_total_playtime`, `create_desktop_shortcut`, `export_launch_script`, `preflight_launch`, `launch_game`, `cancel_task`.
**Missing vs A.1/A.2.1:** the entire dashboard system — no add/remove card, no drag, no resize, no grip handles, no grid snapping (`GRID_CHOICES`), no linked/neighbour resize, no z-order, no 适应窗口 / 重置布局 / 完成, no layout profiles, no `ui_layout*` persistence, no import/export. Also no `java_combo_options` (raw `get_java_list` paths instead), no per-instance java persistence, no server direct-connect field, no 复制启动命令 (`build_launch_command`), no memory slider, no `BannerWidget`, no notes autosave to backend, no `quick` card settings dialog.

## B.7 `pages/downloads.ts`
One page for all 7 categories with a tab strip.
* **vanilla:** search, type filter (all/release/snapshot/old), instance, loader (无/Fabric/Forge/NeoForge/Quilt), loader-version (`list_loader_versions`), OptiFine + LiteLoader checkboxes, 刷新清单 (`fetch_version_list`), 24-at-a-time paging.
* **catalog:** name / 来源 / 版本 / 类型 / 安装到 filters, 搜索, mode tabs **浏览 / 已安装 / 收藏**, **从链接安装**, **导入本地**, per-row 收藏 + 选择版本 (→ `pickCatalogFile`).
**backend:** `get_instances`, `get_version_list`, `fetch_version_list`, `install_game`, `list_loader_versions`, `search_*`, `install_*`, `get_installed_*`/`list_saves`, `delete_*`, `get_installed_mod_entries`, `catalog_favorites`, `toggle_favorite`.
**Missing vs A.2.2/A.2.3:** no version card grid or `Pivot`, no 显示隐藏 / 完成后启动, no installed-version list with the 11-item **更多** menu (rename/copy/hide/shortcut/export-script/open-folders/saves), no `uninstall_version`, no `repair_version`, no install wizard (no OptiFine *version*, no LiteLoader version, no `skip_assets`), no drag-and-drop, no per-page clipboard detection, no favourite state indication, no 检查更新, no enable/disable in the installed list, no `重置条件`, no native file picker (**导入本地 asks you to type an absolute path**), no datapack→save target prompt.

## B.8 `pages/mods.ts`
Instance combo, target-directory combo (`get_mods_targets`), filename filter, 打开目录 / 导入 jar / 检查更新, per-row toggle + delete, enabled-count pill.
**backend:** `get_instances`, `get_mods_targets`, `get_installed_mod_entries`, `enable_mod`, `disable_mod`, `delete_mod`, `open_mods_folder`, `install_mod`, `start_mod_updates`.
**Missing:** drag-and-drop `.jar`, native file dialog, per-mod metadata (name/version, only filename+bytes).

## B.9 `pages/instances.ts`
Grid of instances; per-card **启动 / 重命名 / 目录 / 存档 / Java / 导出 / 版本 / 删除**; **新建实例**; a version modal with per-version **设置** / **卸载** and **安装版本**.
**backend:** `get_instances`, `create_instance`, `rename_instance`, `open_instance_folder`, `java_combo_options`, `set_instance_java`, `export_modpack`, `get_installed_versions`, `uninstall_version`, `delete_instance`.
**Missing:** `java_combo_label_for` (Java pick is a *text prompt* where you must retype the label), no card visuals/`NewInstanceCard`, no modpack metadata display.

## B.10 `pages/java.ts`
**扫描系统 Java**, vendor select (hard-coded `adoptium / zulu / graal / oracle`), download buttons for 8/11/17/21 with `flyToTasks`, per-row **设为默认** (writes only `default_java`).
**backend:** `get_java_list(scan_system)`, `get_settings`, `save_settings`, `download_java(major, vendor)`.
**Missing:** `java_vendor_list` / `java_vendor_label` (vendors hard-coded), per-major NOTES text, `set_instance_java` from this page.

## B.11 `pages/accounts.ts`
Login-status card (device code + **打开微软验证页** + **取消**), **＋ 离线账号**, **微软账号**, authlib block (preset select from `authlib_presets` + api + user + pw), Nide8 block, saved-account grid with avatar / type label / **设为当前** / **删除**. Subscribes to `login_code`, `login_status`, `finished`, `ui_changed`.
**backend:** `get_account_rows`, `add_offline_account`, `start_microsoft_login`, `authlib_presets`, `start_nide8_login`, `start_authlib_login`, `set_active_account`, `remove_account`, `cancel_task`.
**Missing:** skin body preview, offline-skin combo (`add_offline_account(username, skin)` — the bridge overload doesn't accept `skin` anyway, see D), `nide8` type label (only microsoft/offline/authlib mapped), `skin_urls`.

## B.12 `pages/servers.ts`
Instance select, **添加服务器 / 导入 / 导出 / 刷新**, HTML table (名称/地址/端口/描述/操作), per-row 编辑 / 删除.
**backend:** `list_servers`, `add_server`, `update_server`, `delete_server`, `import_servers`, `export_servers`.
**Missing:** description is displayed but never editable; add/edit are three sequential `inputDialog` prompts instead of one form; **导出** copies to the clipboard rather than writing a file.

## B.13 `pages/playtime.ts`
Total card + per-instance cards + per-version rows + last-5 session rows, **刷新**, **清除全部**.
**backend:** `get_all_playtime`, `get_total_playtime`, `format_playtime`, `clear_playtime`.
**Missing:** per-instance/per-version clear (`bindClear` always passes `instance: ''`); calls `format_playtime` once **per row** (N+1 RPC round-trips); no `get_playtime`.

## B.14 `pages/multiplayer.ts`
State pill with `STATE_COLORS`, LAN hint, firewall card, room card (click to copy), per-state action cards for `unsupported / missing / idle / waiting / host-scanning / host-starting / host-ok / guest-connecting / guest-starting / guest-ok / exception / fatal`, player list, auto-copy of the invite code on entering `host-ok`, auto-prepare when installed-but-not-running, **1200 ms** polling.
**backend:** `lan_hint`, `terracotta_snapshot`, `terracotta_prepare`, `terracotta_host`, `terracotta_join`, `terracotta_idle`, `terracotta_allow_firewall`, `terracotta_open_firewall_settings`.
**Missing:** `terracotta_enter_world`, `terracotta_direct_connect` (both exist in `app/backend.py` but **not** in `bridge/api.py` — see D), the `launching` state, `terracotta_player`.

## B.15 `pages/tasks.ts`
Flat list of all tasks with progress bar, message, %, finished message, inline log, **取消** for running tasks.
**backend:** `cancel_task`.
**Missing:** speed column (`splitMsg` exists in `fmt.ts` but is unused here), task-type icons, collapsible log, **清除已完成**, the floating `DownloadDock`, sort/newest-first.

## B.16 `pages/settings.ts`
Eight cards: 版本隔离与存储 / 界面 / 下载与性能 / 账号与下载源 / 维护 / AI 助手 / 反馈与诊断 + a save row. Live-applies `ui_dark`, `theme_color`, `ui_background`. Buttons: 保存当前主题 / 加载主题 / 删除主题 / 官方启动器迁移 / 智能推荐 / 全局 Mod / 维护工具 / 测试 AI 连接 / 保存设置.
**backend:** `get_settings`, `save_settings`, `save_theme`, `list_themes`, `load_theme`, `delete_theme`, `migrate_official_launcher`, `get_smart_recommendation`, `ai_list_chats` (used **as a stand-in for `test_ai_connection`**).
**Missing vs A.2.12:** the whole **个性化布局** group (layout profiles, sidebar editor, section editor, import/export), language selector (`available_languages` / `get_language` / `set_language`), `set_game_dir` (writes the raw `game_dir` key instead), the cleaner (delegated to `tools.ts`), `check_update` / `start_self_update` (also in `tools.ts`), `detect_official_launcher` / `official_launcher_dir` / `scan_official_versions`, `import_theme` / `export_theme`, `test_ai_connection`, `ai_confirm_writes` / `ai_permission_mode`, `ui_scale_percent`, `export_modpack`, feedback-consent flow. Theme load/delete pick a name by **typing it** instead of a list.

## B.17 `pages/tools.ts` (no Python counterpart page — folds parts of Settings/维护 here)
清理缓存 (kind checkboxes `parts` / `cache` / `unused_libraries`, **清理所选内容**, **重新扫描**), 启动器更新 (**检查更新** → conditional **下载并更新**), 环境诊断 (**查看系统信息**, **查看推荐配置**), 全局模组 (**打开目录**), Minecraft 新闻 (**更新新闻**).
**backend:** `cleaner_preview`, `cleaner_apply`, `check_update`, `start_self_update`, `collect_sysinfo`, `get_smart_recommendation`, `cached_news`, `fetch_news`.
Note: it reads `cleaner.parts / cache / unused_libraries / count / bytes`, whereas `bridge/api.py` `cleaner_preview` returns the shape modelled in WPF's `CleanerPreview` (`total`, `total_text`, `kinds[]`) — **shape mismatch to verify**.

## B.18 `pages/feedback.ts`
类型 / 标题 / 详细说明 / 联系方式 / 附带系统信息 / **发送反馈** / **查看系统信息**, FAQ `<details>` list, recent-submission table, help card.
**backend:** `feedback_history`, `help_articles`, `submit_feedback`, `collect_sysinfo`.
**Missing:** `help_article` (bodies come from the list payload), `sysinfo_text` (raw JSON dump instead of the formatted text), **重新采集**, the hard-coded category list diverges from `mclauncher.feedback_defaults.CATEGORIES`, `submit_crash_feedback`.

## B.19 `pages/ai.ts`
Chat sidebar (**＋ 新对话**, per-chat select/delete), message list, streaming bubble, status line, textarea (`Enter` send / `Shift+Enter` newline / IME-safe), **发送** / **停止**; `ai.confirm` → generic confirm dialog; `ai.ask` → multi-question radio/checkbox dialog with an "其他" free-text field.
**backend:** `ai_list_chats`, `ai_new_chat`, `ai_set_active`, `ai_delete_chat`, `ai_send(text, chat_id, launch)`, `ai_stop`, `ai_confirm`, `ai_answer`.
**Missing vs A.2.14:** no markdown rendering (plain `escapeHtml`), no `ToolLine` tool-progress rows, no inline `ConfirmCard`, no `PermissionDialog` / permission-mode combo, no quick chips, no 重试, no `Esc` shortcut, no message queueing.

## B.20 `pages/dialogs.ts`
* `showVersionSetup(instance, version)` — 20 rows, matching A.3.4 field-for-field.
* `showSavesDialog(instance, version)` — kind tabs 存档/备份/截图/崩溃报告/日志, radio list, 打开 / 删除 / 备份 / 还原 / 导出 zip / 装数据包.
* `showGlobalMods()` — per-file switch + 打开文件夹.
* `pickCatalogFile(item, kind, gameVersion)` — first **80** files, radio list, 安装.
**Missing vs A.3:** no install wizard, no first-run wizard, no layout-settings dialogs, no crash dialog here (it lived in the deleted `ui.ts` helpers), no file-pick MC-version/loader filters or install-target combos or **安装最新**, no save thumbnails, no `restore_save_backup(overwrite=True)` conflict flow, no `open_media` (uses `open_crash_file` for every non-save kind), export/backup destinations are typed by hand.

## B.21 Summary of Python pages with **no eziapp counterpart at all**
* Dashboard/layout system (`dashboard.py`, `layout_model.py`, `home_cards.py` card registry)
* Version management page (`version_page.py`) — only install exists
* Sidebar/section editors (`layout_settings.py`)
* Install wizard (`install_wizard.py`)
* First-run wizard (`first_run.py`)
* Crash dialog + `show_launcher_error` (deleted with the old `ui.ts`)
* i18n (`mclauncher.i18n.tr`) — eziapp is hard-coded zh-CN
* Download dock / task badge fly-in parity is partial (`flyToTasks` exists, dock does not)

---

# C. WPF coverage — `wpf/PyMCL.Wpf/`

**Status: a design-system skeleton bolted onto an older 5-page prototype. It does not currently compile or run.**

## C.1 Files that exist

```
PyMCL.Wpf.sln
PyMCL.Wpf/
  App.xaml, App.xaml.cs, AssemblyInfo.cs, app.manifest, PyMCL.Wpf.csproj
  MainWindow.xaml, MainWindow.xaml.cs
  Pages/  LaunchPage, InstancePage, DownloadPage, SettingsPage, TasksPage   (5 pages)
  Services/  BridgeClient.cs, BridgeHost.cs, Models.cs, Motion.cs, Ui.cs
  Themes/  Controls.xaml (901 lines), Palette.Light.xaml, Palette.Dark.xaml
```

`csproj`: `net8.0-windows`, `UseWPF`, `SelfContained=false`, `DebugType=none`, no NuGet packages, version `3.2.0`.

## C.2 Pages (all five)

| Page | Nav key / title | Controls | Bridge calls |
|---|---|---|---|
| `LaunchPage` | `launch` / 启动 | gradient hero + **启动游戏**; 启动配置 card: `InstanceBox`, `VersionBox`, `AccountBox`, `UserNameBox`, `MemoryBox`, **启动游戏**, **刷新列表**; a static 提示 card | `get_instances`, `get_accounts`, `get_installed_versions`, `launch_game` (hard-codes `width=854, height=480, java="自动选择"`) |
| `InstancePage` | `instance` / 实例 | `ListBox` of instance names, **刷新** | `get_instances` |
| `DownloadPage` | `download` / 下载 | `InstanceBox`, version-ID `TextBox` (default `1.20.4`), loader combo (`vanilla/fabric/forge/quilt/neoforge`), **开始下载** | **`download_version`** ← *does not exist in `bridge/api.py`* |
| `SettingsPage` | `settings` / 设置 | read-only runtime info (`host.Root`, `host.Port`) | none |
| `TasksPage` | `tasks` / 下载任务 | `ListBox` of `id status title`, **刷新** | **`list_tasks`** ← *does not exist in `bridge/api.py`* |

`MainWindow.xaml`: custom chrome (`WindowChrome CaptionHeight=48`, `ResizeBorderThickness=6`), 200 px fixed sidebar (no resizer, no reorder, no groups, no pinning), status bar with `StatusText` + `TaskProgress`, bridge-status footer. `MainWindow.xaml.cs` caches pages in a `Dictionary<string, UserControl>` and handles SSE `progress` / `finished` / `task_count_changed`.

## C.3 Infrastructure available **by name**

### `Services/Ui.cs`

* `enum BtnKind { Primary, Soft, Normal, Ghost, Danger, Chip, Icon }`
* **`static class Ico`** — 68 Segoe MDL2 glyph constants: `Play, Stop, Rocket, Home, Box, Download, Cloud, Gear, Coffee, User, Robot, Wifi, Server, Clock, Chat, Folder, Trash, Refresh, Search, Add, Check, Close, Chevron, ChevronRight, ChevronLeft, Star, StarFill, List, Palette, Moon, Sun, Pin, Link, Copy, Edit, Save, Warning, Info, Error, Success, Grid, Package, Shader, World, Data, Image, Puzzle, Bug, Send, More, Open, Sort, Filter, Shield, Broom, Import, Export, Play2, Lightning, Heart, Book, Camera, Repair, Windowed, Minimize, Maximize, Restore, CloseWin`
* **`sealed class SPanel : Panel`** — `Orientation`, `Spacing` (StackPanel + gap).
* **`sealed class SmoothScroll : ScrollViewer`** — `OffsetProperty`, 230 ms CubicEase inertial wheel scrolling, disabled when `Motion.Enabled == false`.
* **`static class Fmt`** — `Downloads(long)` (万/亿), `Size(long)`, `Duration(long)`, `SplitMsg(msg, out status, out speed)` (splits on `"  |  "`).
* **`static class Ui`** — `S(key)`, `Res(key)`, `Txt`, `H1`, `H2`, `H3`, `Muted`, `Small`, `Mono`, `Glyph`, `V(spacing,…)`, `H(spacing,…)`, `Grid(rows, cols)` (string spec `"Auto,*,32"`), `Card`, `Pane`, `Scroll`, `Sep`, `Spring`, `Btn`, `IconBtn`, `Input`, `Multi`, `LogBox`, `Pw`, `Combo`, `Check`, `Switch`, `Sld`, `Prog`, `Tag`, `Badge`, `Field(label, control, hint, labelWidth=170)`, `Section(title, sub, right)`, `Empty(glyph, title, hint)`, `Skeleton(height, width)` (with sweep animation), `RowCard(content, click, padding)`, `OpenUrl`.
* **`static class UiExt`** (fluent extensions) — `Dyn(p, key)`, `M(l,t,r,b)`, `M(all)`, `W`, `MinW`, `Hh`, `At(row, col, rowSpan, colSpan)`, `Add(this Grid,…)`, `Left`, `Right`, `Center`, `Stretch`, `VCenter`, `VTop`, `Wrap`, `Trim`, `Tip`, `Tag2`, `Hide`, `Show`, `Shown`, `Str(this ComboBox)`, `Fill(this ComboBox, items, keep)`.

### `Services/Motion.cs`
`static class Motion` — properties `Enabled`, `Scale`; methods `FadeIn(el, ms=220, fromY=10, delayMs=0)`, `FadeOut`, `Stagger(panel, step=26, ms=210, fromY=12)`, `StaggerItems`, `HoverLift(el, scale=1.012, lift=2, blur=22)`, `Shadow<T>(el, blur=18, opacity=.08, depth=2)`, `Pulse(el, peak=1.06)`, `Shake(el)`, `Shine(layer, tx, width=1200)`, `Progress(bar, value)`, `CountUp(tb, from, to, fmt, ms=620)`, `AnimateWidth`, `AnimateHeight`, `Fade`, `PopIn(el, ms=200)`, `PopOut`, `SlideIn(el, fromX=40, ms=240)`, `SlideOut`, `PageSwap(host, next, forward=true)`. Stated budget: ≤14 px displacement, 130–260 ms, `CubicEase.Out`, transform/opacity only.
**Note:** there is **no `flyToTasks` equivalent** (`app/fly_anim.py` has no WPF counterpart).

### `Themes/Controls.xaml` — reusable keys
Tokens: `F.Ui`, `F.Mono`, `R.Card`, `CR.Card`, `CR.Ctl`, `CR.Pill`, `D.Fast`, `D.Med`, `E.Out`, `E.InOut`.
Text: `T.H1`, `T.H2`, `T.H3`, `T.Muted`, `T.Small`, `T.Mono`.
Surfaces: `Card`, `CardFlat`, `ScrollThumb`.
Buttons: `BtnTpl` (`ControlTemplate`), `Btn.Base`, `Btn.Primary`, `Btn.Soft`, `Btn.Normal`, `Btn.Ghost`, `Btn.Danger`, `Btn.Icon`, `Btn.Chip`, `Btn.Caption`, `Btn.CaptionClose`.
Navigation: `NavItem`, `TabItemBtn`.
Inputs: `Input`, `Input.Multi`, `Input.Log`, `Pw`, `ComboItem`, `Combo`, `Chk`, `Switch`, `Radio`, `Sld`, `Prog`, `ListItemRow`, `PlainList`.

### `Themes/Palette.Light.xaml` / `Palette.Dark.xaml` — brush keys
Colors: `C.Accent`, `C.AccentDeep`, `C.AccentLite`, `C.Canvas`, `C.Paper`, `C.Shadow`.
Brushes: `B.Accent`, `B.AccentDeep`, `B.AccentLite`, `B.AccentSoft`, `B.AccentSoft2`, `B.OnAccent`, `B.Canvas`, `B.Paper`, `B.Paper2`, `B.Side`, `B.Chrome`, `B.Line`, `B.LineSoft`, `B.Hover`, `B.Pressed`, `B.Ink`, `B.InkSoft`, `B.InkMuted`, `B.InkFaint`, `B.Danger`, `B.DangerSoft`, `B.Warn`, `B.WarnSoft`, `B.Info`, `B.InfoSoft`, `B.Ok`, `B.Scroll`, `B.ScrollHover`, `B.Mask`, `B.Glass`, `B.BannerFill`, `B.PageWash`.
`App.ApplyTheme(bool dark)` hot-swaps `MergedDictionaries[0]` between the two palettes; `App.IsDark`.

### `Services/BridgeClient.cs`
`BridgeEvent` (union DTO: `Event, TaskId, Title, Message, Text, Current, Total, Count, Success, Stopped, Code, Uri, Kind, Label, Name, Payload, Crash`).
`BridgeClient` — `TokenHeader`, `JsonOpt` (`SnakeCaseLower`), `BaseUri`, events `EventReceived`, `StreamStateChanged`, property `StreamConnected`; methods `ConnectEvents`, `IsHealthyAsync`, `CallAsync(method, args)`, `CallAsync<T>`, `TryCallAsync<T>(…, fallback)`, `StartTaskAsync`, `Dispose`. Loopback-only + ≥32-char token enforced in the ctor. SSE reconnect with exponential backoff capped at 15 s. `BridgeCallException(Method, Message)`.

### `Services/BridgeHost.cs`
`BridgeHost` — `Client`, `Port`, `Root`, `Backend`; `StartAsync(ct)` (prefers `pymcl-bridge.exe`, falls back to `python -u bridge/server.py --root <root>`, token via `PYMCL_BRIDGE_TOKEN`, parses `port=(\d+)` from the `PYMCL_BRIDGE` banner, then polls `/health` 60×100 ms), `FindRoot`, `FindPython`, `FindNativeBridge`, `Dispose`.
`static class AppServices` — `Client`, `Host`, `Window`, `Ready`, `Toast(title, body, kind)`.

### `Services/Models.cs` — DTOs already defined
`InstanceInfo, VersionRow, CatalogItem, JavaInfo, JavaOption, VersionSettingsDto, NewsRow, AuthlibPreset, AccountRow, TerracottaSnap, ModEntry, GlobalModRow, SaveRow, BackupRow, AiStoreDto, AiChatDto, AiMsgDto, CrashReport, CrashAction, PreflightResult, PreflightItem, OpResult, CatalogFile, LoaderVer, HelpArticle, ServerRow, ThemeRow, UpdateInfo, CleanerPreview, CleanerKind, FeedbackRow`
plus **`CatalogKind`** with the six ready-made presets `Mod, Modpack, Datapack, ResourcePack, Shader, World` and `CatalogKind.All` — each carrying `SearchMethod / InstallMethod / InstalledMethod / DeleteMethod / Types / FileKind / DefaultSource / LocalFilter / LinkHint / Empty / Icon`. This mirrors the Python `*_SPEC` dicts and is the intended basis for a single generic catalog page.

## C.4 Blocking defects found (all read-only observations)

1. **Legacy resource keys**: `MainWindow.xaml` and all 5 page XAMLs reference `Brush.Canvas`, `Brush.Paper`, `Brush.Line`, `Brush.Side`, `Brush.Accent`, `Brush.AccentSoft`, `Brush.AccentDeep`, `Brush.InkMuted`, `GhostButton`, `CloseButton`, `PclNavButton`, `PclPrimaryButton`, `PclSecondaryButton`, `FieldLabel`. **Zero** of these exist in `Palette.*.xaml` or `Controls.xaml` (which use `B.*` / `Btn.*` / `T.*` / `NavItem`). Only `Card` resolves.
2. **`ToastKind` and `MainWindow.Toast(...)` are undefined** — referenced from `App.xaml.cs` and `AppServices.Toast`.
3. **BridgeClient member names don't match usage** — `MainWindow.xaml.cs` uses `EventStreamStateChanged` / `EventStreamConnected`; the class exposes `StreamStateChanged` / `StreamConnected`.
4. **The bridge is never started** — `App.OnStartup` only does `new MainWindow().Show()`; nothing calls `BridgeHost.StartAsync` or assigns `AppServices.Client` / `Host` / `Window`, so every page's `AppServices.Client.CallAsync` would NRE.
5. **Two RPC methods called that do not exist**: `download_version` (DownloadPage) and `list_tasks` (TasksPage). Correct calls are `install_game(...)` and the SSE task stream (there is no task-list RPC — see D).
6. `Ui.cs` / `Motion.cs` / `Models.cs` / `Controls.xaml` are effectively **dead code**: no page imports `Ui`, `Ico`, `SPanel`, `SmoothScroll`, `Fmt`, `Motion`, or any `Models` DTO.

---

# D. Bridge RPC surface — `bridge/api.py`

Transport: `bridge/server.py` — loopback-only `ThreadingHTTPServer` bound to `127.0.0.1`, JSON-RPC 2.0 at `POST /rpc`, SSE at `GET /events`, health at `GET /health` and `/`. Auth header `X-PyMCL-Bridge-Token` (≥32 chars; SSE may pass `?token=`). Any method name starting with `_` is rejected as `hidden method`; unknown names return `-32601`. `params` may be an **array** (positional) or **object** (keyword, filtered by `inspect.signature` in `_call_kwargs`, `**kwargs` absorbs the rest). Max body 4 MiB. CLI: `--root` (required), `--host` (must be `127.0.0.1`), `--port` (0 = auto), `--token`, `--allowed-origin` (repeatable), `--ready-file`. Banner on stdout: `PYMCL_BRIDGE port=<n> host=<h> root=<r> auth=token`.

**All 165 public methods of `bridge.api.BackendAPI`, grouped by domain, with parameter names.**

## D.1 Tasks & crash reporting
```
start_task(title, fn, *args, **kwargs) -> str          # not usefully callable over RPC (fn is a callable)
cancel_task(task_id)
task_title(task_id) -> str
wait_task(task_id, timeout=1800, cancelled=None) -> dict
get_crash(task_id="") -> dict
export_crash_report(task_id="", dest="") -> str
open_crash_file(path="", task_id="") -> str
submit_crash_report(task_id="") -> str
apply_crash_action(action=None, report=None) -> dict
submit_crash_feedback(report, extra="") -> dict
```

## D.2 Launch
```
launch_game(instance, version, account, username, memory_mb, width, height,
            java="自动选择", extra_game_args=None) -> str
build_launch_command(instance, version, account, username, memory_mb, width, height,
                     java="自动选择") -> str
get_launch_command(instance, version, account="", username="", memory_mb=0) -> str
preflight_launch(instance="", version="", memory_mb=0, java="") -> dict
is_game_running() -> bool
allow_multi_instance() -> bool
set_multi_instance(allow)
```

## D.3 Instances
```
get_instances() -> list[dict]
create_instance(name)
delete_instance(name)
rename_instance(name, new_name)
open_instance_folder(name)
export_modpack(instance, dest="") -> str
get_instance_java(name) -> str
set_instance_java(name, java)
instance_java_label(name) -> str
```

## D.4 Versions (install / manage)
```
install_game(version, loader="无", loader_version="", instance="", extra=None) -> str
list_loader_versions(mc_version, loader) -> list[dict]
get_version_list() -> list[dict]
fetch_version_list() -> list[dict]
get_installed_versions(instance, include_hidden=False) -> list[str]
uninstall_version(spec)                      # spec = "<instance> / <version>" or "<version>"
repair_version(instance, version) -> str
rename_version(instance, version, new_id) -> str
copy_version(instance, version, new_id) -> str
hide_version(instance, version, hidden=True) -> dict
open_version_folder(instance, version="", which="root")
export_launch_script(instance, version, dest="") -> str
create_desktop_shortcut(instance, version, username="", account="", name="") -> str
get_version_settings(instance, version) -> dict
save_version_settings(instance, version, data) -> dict
```

## D.5 Catalog / search
```
search_modpacks(query, source) -> list[dict]
search_mods(query, source, extra=None) -> list[dict]
search_shaders(query, source, extra=None) -> list[dict]
search_resourcepacks(query, source, extra=None) -> list[dict]
search_datapacks(query, source, extra=None) -> list[dict]
search_worlds(query, source="CurseForge", extra=None) -> list[dict]
list_catalog_files(extra=None) -> list[dict]
catalog_favorites() -> list
toggle_favorite(item) -> list
thumb_path(url) -> str
ensure_thumb(url) -> str
```

## D.6 Content install / installed lists / delete
```
install_modpack(name, source="Modrinth", extra=None) -> str
install_mod(name, instance="default", extra=None) -> str
install_shader(name, instance="default", extra=None) -> str
install_resourcepack(name, instance="default", extra=None) -> str
install_datapack(name, instance="default", extra=None) -> str
install_world(name, instance="default", extra=None) -> str
get_installed_mods(instance) -> list[str]
get_installed_mod_entries(instance, version="") -> list
get_installed_shaders(instance) -> list[str]
get_installed_resourcepacks(instance) -> list[str]
get_installed_datapacks(instance) -> list[str]
get_installed_modpacks(instance) -> list[str]
delete_mod(instance, filename, version="")
delete_shader(instance, filename)
delete_resourcepack(instance, filename)
delete_datapack(instance, filename)
delete_modpack(instance, filename="")
```

## D.7 Mods management
```
enable_mod(instance, filename, version="") -> str
disable_mod(instance, filename, version="") -> str
get_mods_targets(instance) -> list[dict]
open_mods_folder(instance, version="") -> str
start_mod_updates(instance) -> str
list_global_mods() -> list[dict]
set_global_mod_enabled(filename, enabled) -> str
open_global_mods()
```

## D.8 Java
```
get_java_list(scan_system=False) -> list[dict]
normalize_java_pref(java) -> str
java_combo_options(instance, scan_system=False) -> list[dict]
java_combo_label_for(instance, options=None) -> str
java_vendor_list() -> list[str]
java_vendor_label(vendor) -> str
download_java(major, vendor="adoptium") -> str
install_java(major, vendor="adoptium") -> str
```

## D.9 Accounts
```
get_accounts() -> list[str]
get_account_rows() -> list[dict]
add_offline_account(username)
remove_account(name)
set_active_account(name)
start_microsoft_login() -> str
start_authlib_login(api, username, password) -> str
start_nide8_login(server_id, username, password) -> str
authlib_presets() -> list
```

## D.10 Settings / i18n
```
get_settings() -> dict
save_settings(data)
update_settings(settings)
get_setting(key, default=None)
get_language() -> str
set_language(lang)
available_languages() -> dict[str,str]
translate(key, lang="") -> str
```

## D.11 Servers
```
list_servers(instance="") -> list[dict]
add_server(instance, name, ip, port=25565, description="") -> dict
update_server(instance, index, **kwargs) -> dict
delete_server(instance, index)
import_servers(instance, text) -> int
export_servers(instance) -> str
```

## D.12 Playtime
```
get_playtime(instance="") -> dict
get_all_playtime() -> dict
get_total_playtime() -> int
format_playtime(seconds) -> str
clear_playtime(instance="", version="")
```

## D.13 Multiplayer / Terracotta
```
terracotta_player() -> str
terracotta_snapshot() -> dict
terracotta_prepare() -> str
terracotta_host()
terracotta_join(room)
terracotta_idle()
terracotta_allow_firewall() -> str
terracotta_open_firewall_settings()
terracotta_shutdown()
lan_hint(port=25565) -> str
```

## D.14 AI
```
test_ai_connection() -> str
ai_list_chats() -> dict
ai_new_chat() -> dict
ai_delete_chat(chat_id) -> dict
ai_set_active(chat_id) -> dict
ai_send(text, chat_id="", launch=None) -> dict
ai_stop() -> dict
ai_confirm(ok=False) -> dict
ai_answer(result=None) -> dict
```

## D.15 Feedback / help / diagnostics
```
submit_feedback(category, title, body, contact="", include_sysinfo=True) -> dict
feedback_history() -> list
help_articles(query="") -> list
help_article(article_id) -> dict
collect_sysinfo(force=False, scan_system_java=False) -> dict
sysinfo_text(info=None) -> str
get_smart_recommendation() -> dict
```

## D.16 Themes
```
list_themes() -> list[dict]
save_theme(name) -> dict
load_theme(name) -> dict
delete_theme(name)
import_theme(path) -> str
export_theme(name, dest) -> str
```

## D.17 Saves / worlds / media
```
list_saves(instance, version="") -> list[dict]
open_save(instance, name, version="") -> str
delete_save(instance, name, version="")
export_save(instance, name, dest, version="") -> str
backup_save(instance, name, version="") -> str
list_save_backups(instance, name="", version="") -> list[dict]
restore_save_backup(instance, backup_name, version="", overwrite=False) -> dict
delete_save_backup(instance, backup_name, version="")
install_datapack_into_save(instance, filename, save_name, version="") -> str
list_media(instance, kind, version="") -> list[dict]
```

## D.18 Tools / cleaner / update / migration
```
cleaner_preview() -> dict
cleaner_apply(kinds=None) -> dict
check_update() -> dict
start_self_update() -> str
detect_official_launcher() -> bool
official_launcher_dir() -> str
scan_official_versions() -> list[str]
migrate_official_launcher(instance="default") -> str
```

## D.19 Misc
```
fetch_news() -> list
cached_news() -> list
```

## D.20 SSE event names emitted

From `BackendWorker` (`self._emit(...)`) and `BackendAPI._emit` / `self._bus.emit(...)`:

| Event | Payload |
|---|---|
| `hello` | `{"ok": true}` — synthesised by `bridge/server.py::_sse` on connect |
| `progress` | `{task_id, current, total, message}` |
| `log` | `{task_id, text}` |
| `finished` | `{task_id, success, message}`; on a game crash also `crash: true` |
| `crash` | the `GameCrashError.report` dict + `task_id` (also cached in `_crashes`, capped at 40) |
| `login_code` | `{code, uri}` |
| `login_status` | `{text}` |
| `task_added` | `{task_id, title}` |
| `task_count_changed` | `{count}` — emitted on `start_task` and after every `finished` |
| `ui_changed` | `{}` — emitted after every successful task, and by `create/delete/rename_instance`, `uninstall_version`, `save_version_settings`, `delete/enable/disable_mod`, `delete_shader/resourcepack/datapack`, `remove_account`, `set_active_account`, `add_offline_account`, `restore_save_backup`, `delete_save_backup`, `_backup_save_impl`, and two branches of `apply_crash_action` |
| `game_started` | `{}` |
| `game_exited` | `{code}` |
| `ai.delta` | `{text}` |
| `ai.status` | `{kind, **payload}` |
| `ai.confirm` | `{name, args, label}` |
| `ai.ask` | `{questions, title}` |
| `ai.done` | `{text, store}` |
| `ai.fail` | `{text, stopped}` |

Note the special-casing in `_emit`: `crash` is cached and forwarded verbatim; `finished` additionally records `_task_results` (capped 80), pops the worker, and emits `task_count_changed` (+ `ui_changed` on success).

`app/backend.py` exposes the same stream as Qt signals: `task_added(str,str)`, `progress(str,int,int,str)`, `log(str,str)`, `finished(str,bool,str)`, `crash(str,object)`, `login_code(str,str)`, `login_status(str)`, `ui_changed()`, **`theme_changed()`**, `task_count_changed(int)`, `game_started()`, `game_exited(object)`.
→ **`theme_changed` has no SSE counterpart.** Both non-Python UIs must re-derive theme changes from `get_settings` after a `save_settings`/`load_theme` round-trip.

## D.21 Methods in `bridge/api.py` with **no** equivalent in `app/backend.py`

All 8 are AI-session-state RPCs. The Qt UI does not need them because `app/pages/ai_page.py` drives `mclauncher.ai.agent.run_agent` and `mclauncher.ai.store` in-process:

```
ai_list_chats(), ai_new_chat(), ai_delete_chat(chat_id), ai_set_active(chat_id),
ai_stop(), ai_confirm(ok=False), ai_answer(result=None), ai_send(text, chat_id="", launch=None)
```

## D.22 Methods in `app/backend.py` with **no** equivalent in `bridge/api.py`

These 12 are reachable from the Qt UI but **not** over the bridge — so eziapp and WPF cannot implement the corresponding features at all:

| Missing RPC | Used by (Python page) | Consequence for eziapp / WPF |
|---|---|---|
| `set_game_dir(path)` | `settings_page.py`, `first_run.py` | can only write the raw `game_dir` setting; no migration/validation side-effects |
| `open_media(path)` | `saves_dialog.py` | screenshots / logs / crash reports cannot be opened (eziapp abuses `open_crash_file`) |
| `terracotta_enter_world()` | `multiplayer_page.py` | "进入世界" action unavailable |
| `terracotta_direct_connect(address)` | `multiplayer_page.py` | direct-connect action unavailable |
| `check_mod_updates(instance)` | `mod_page.py`, `catalog_page.py` | can only fire-and-forget `start_mod_updates`; no update *preview* list |
| `apply_mod_update(instance, row)` | `mod_page.py` | cannot apply a single selected update |
| `skin_urls(account_name="")` | `account_page.py` | no skin/body preview (only the `avatar`/`body` fields already inside `get_account_rows`) |
| `local_ips()` | `multiplayer_page.py` | LAN address list unavailable (only the pre-formatted `lan_hint`) |
| `invalidate_instances()` | internal cache reset | n/a for RPC clients |
| `call_async(fn, on_ok, on_err)` | Qt threading helper | n/a — bridge clients use HTTP async |
| `shutdown(timeout_ms=800)` | `main_window.closeEvent` | clients cannot ask the backend to drain tasks before exit |
| `is_download_title(title)` (static) | `tasks_page.py` icon/dock logic | clients must re-implement the title-prefix heuristic locally |

## D.23 Signature divergences on otherwise-shared methods

| Method | `bridge/api.py` | `app/backend.py` |
|---|---|---|
| `add_offline_account` | `(username)` | `(username, skin="")` — **the bridge cannot set an offline skin** |
| `get_installed_mods` | `(instance)` | `(instance, version="")` — bridge cannot scope to an isolated version dir |
| `search_modpacks` | `(query, source)` | `(query, source, extra=None)` — **no version/category filter over the bridge** |
| `test_ai_connection` | `()` (uses `self.get_settings()`) | `(settings=None)` — cannot test *unsaved* settings over the bridge |
| `apply_crash_action` | `(action=None, report=None)` | `(action, report=None)` |
| `install_game` | `loader="无"` (literal) | `loader=tr("无")` (localised) |

---

# E. Gap list — prioritised

## E.1 eziapp

### P0 — the tree does not build
1. Finish the shared-layer migration. Either (a) port `main.ts` + all 15 `pages/*.ts` to the new `store.ts` / `ui.ts` / `dom.ts` / `fmt.ts` APIs (per the mapping table in B.0), or (b) restore the removed exports as thin adapters: `setInstances/setVersionList/setJavaList/setAccounts/setAIChats/subscribe/notify/current*/bridgeConnected/bridgeUrl/versionList/javaList/aiChats/aiActiveId/updateTask`, `toast(msg,type,ms)`, `confirmDialog/formDialog/inputDialog`, `registerPageCleanup/clearPageCleanups`, `showLoading/showEmpty/showError`, `initBridgeLifecycle`, `applyTheme`, `applyAppearance(settings)`, `preflightDialog`, `crashDialog`, `type AIChat`.
2. Re-add `preflightDialog` and `crashDialog` (deleted) — `launch.ts` imports both and they are the only crash-recovery UI.
3. Align the fly-in target selector: `ui.ts` queries `[data-id="tasks"]`, `main.ts` renders `[data-page="tasks"]`.
4. Align the sidebar CSS variable and clamp: `--sidebar-w` / 150–340 (ui.ts) vs `--sidebar-width` / 140–320 (main.ts, and the Python clamp).
5. Delete or fully adopt `pages/common.ts` — it duplicates `fmt.ts`.

### P1 — features the Python UI has and users will immediately miss
6. **Version management page** — installed-version list with the 11-item context menu (`open_version_folder(which=root|mods|saves|screenshots)`, `rename_version`, `copy_version`, `hide_version`, `create_desktop_shortcut`, `export_launch_script`, saves manager), plus `uninstall_version` and `repair_version` (both currently unused).
7. **Install wizard** — OptiFine *version* pick, LiteLoader, `skip_assets`, and pass them in `install_game(extra=…)`.
8. **File-pick parity** — MC-version + loader filters, install-target instance/version combos, paging beyond 80, **安装最新**.
9. **Native file/folder dialogs.** Today "导入本地", "导出存档", "导入模组", "导出 zip" and the theme/global-mod flows all require the user to type an absolute path into `inputDialog`. Add drag-and-drop install on the catalog and mods pages as the minimum viable substitute.
10. **Tasks page parity** — speed column (use the already-present `fmt.splitMsg`), task-type icons, collapsible logs, **清除已完成**, newest-first sort, and the floating download dock.
11. **Settings parity** — language selector (`available_languages/get_language/set_language`), real `test_ai_connection` (stop using `ai_list_chats` as a probe), `import_theme`/`export_theme`, theme *list* pickers instead of typing names, `detect_official_launcher`/`official_launcher_dir`/`scan_official_versions` before migrating, `ai_confirm_writes`/`ai_permission_mode`, `ui_scale_percent`, `set_game_dir` (needs D.22 first).
12. **First-run wizard** (`first_run.py`) and the **feedback-consent prompt** — currently there is no onboarding at all.
13. **Java page** — use `java_vendor_list`/`java_vendor_label` instead of a hard-coded vendor list; add the per-major NOTES; allow setting a per-instance Java.
14. **Instances page** — replace the "retype the Java label" prompt with a real select built from `java_combo_options` + `java_combo_label_for`.
15. **Playtime** — batch formatting client-side (`fmt.duration`) instead of one `format_playtime` RPC per row; wire per-instance/per-version clear.
16. **Accounts** — skin/body preview, offline-skin selection, a `nide8` type label.
17. **Feedback** — source the category list from the backend, use `sysinfo_text` for the preview, add **重新采集**, wire `help_article`.
18. **AI page** — markdown rendering, tool-progress rows, inline confirm cards, permission-mode UI, quick chips, retry, `Esc`.
19. **Verify the `cleaner_preview` shape** consumed by `tools.ts` (`parts/cache/unused_libraries/count/bytes`) against what `bridge/api.py` actually returns (`total/total_text/kinds[]` per the WPF DTO).

### P2 — the differentiating features
20. **The dashboard/layout system.** This is the single biggest gap: `layout_model.py` + `dashboard.py` + `home_cards.py` (8 card types, proportional geometry, `GRID_CHOICES`, 8-direction grips, linked resize with `_LINK_GAP_MAX`/`_LINK_OVERLAP_MAX`, z-order, add-card palette, 适应窗口 / 重置布局, profiles, `export_doc`/`import_doc`, `ui_layout`/`ui_layouts`/`ui_layout_profile`).
21. **Sidebar customisation.** Reorder (drag with drop-line), hide/show, pin/unpin via the `application/x-pymcl-nav` MIME contract, group membership editing, all persisted to `ui_nav_order` / `ui_nav_pinned` / `ui_nav_hidden` / `ui_section_members`.
22. **i18n.** Route every string through the bridge's `translate(key, lang)` / `available_languages()`.
23. `launcher_visibility` handling on `game_started` / `game_exited`, and a lazy page cache with a stale-reload rule equivalent to `_reload_page`'s 1.2 s dedupe.

## E.2 WPF

### P0 — make it compile and run (nothing works today)
1. **Rewrite `MainWindow.xaml` + the 5 page XAMLs against the shipped design system.** Replace `Brush.*` → `B.*`, `GhostButton`/`CloseButton` → `Btn.Caption`/`Btn.CaptionClose`, `PclNavButton` → `NavItem`, `PclPrimaryButton` → `Btn.Primary`, `PclSecondaryButton` → `Btn.Normal`, `FieldLabel` → `T.Small` (or use `Ui.Field(...)`).
2. **Add `enum ToastKind` and `MainWindow.Toast(title, body, kind)`** (build it with `Ui.Card` + `Motion.SlideIn` / `Motion.SlideOut`) so `AppServices.Toast` and `App.OnUnhandled` resolve.
3. **Fix the `BridgeClient` member names** used by `MainWindow.xaml.cs` (`StreamStateChanged` / `StreamConnected`).
4. **Actually start the bridge.** In `App.OnStartup`: `await BridgeHost.StartAsync()`, then set `AppServices.Host`, `AppServices.Client`, `AppServices.Window`, and show a connect/retry surface on failure. Every page currently dereferences `AppServices.Client` unguarded.
5. **Fix the two invented RPCs**: `download_version` → `install_game(version, loader, loader_version, instance, extra)`; `list_tasks` → maintain a client-side task store fed by the `task_added` / `progress` / `log` / `finished` / `task_count_changed` SSE events (there is **no** task-list RPC).
6. **Wire theming**: `App.ApplyTheme(dark)` exists but is never called; drive it from `get_settings()["ui_dark"]` and set `Motion.Enabled` from `ui_motion`, `Motion.Scale` from a UI-speed preference.

### P1 — reach the current eziapp level
7. Build a generic catalog page on the already-written `Models.CatalogKind.All` (6 presets) — search / source / version / type filters, browse ⇄ installed ⇄ favourites, `list_catalog_files` picker, `toggle_favorite`.
8. Real launch page: `java_combo_options`, width/height, `preflight_launch` → a preflight dialog, `crash` event → a crash dialog driven by `CrashReport`/`CrashAction` + `apply_crash_action`, `build_launch_command`, `cancel_task`.
9. Missing pages entirely: **Mods, Accounts, Java, Servers, Playtime, Multiplayer, Feedback, AI, Tools** (9 of the Python UI's 16 sub-pages).
10. Real Tasks page: per-task card with `Ui.Prog` + `Motion.Progress` + `Fmt.SplitMsg` speed, expandable log, cancel, clear-completed.
11. Real Settings page: the eight `SettingCardGroup`s, using `Ui.Field` / `Ui.Section` / `Ui.Switch` / `Ui.Combo`.
12. Dialogs: version setup (20 rows → `VersionSettingsDto`), saves manager (`SaveRow`/`BackupRow`), global mods (`GlobalModRow`), install wizard, first run.

### P2 — full parity
13. Sidebar customisation (reorder / hide / pin / groups / resizable width) — the sidebar is a fixed 200 px `StackPanel` with 5 hard-coded buttons today.
14. The dashboard/layout canvas — needs a `Canvas`-based port of `DashboardCard` + `_Grip` + `DashboardCanvas`, reusing `Motion.HoverLift` / `Motion.Shadow`.
15. A `fly_to_tasks` equivalent (quadratic Bézier ball + ripple + badge pulse) — `Motion.cs` has no counterpart to `app/fly_anim.py`.
16. i18n via `translate` / `available_languages`; `launcher_visibility` window handling; graceful shutdown (needs `shutdown` exposed, see below).

## E.3 Bridge-side work that unblocks both UIs

Add these to `bridge/api.py` (they already exist in `app/backend.py`):

```
set_game_dir(path)
open_media(path)
terracotta_enter_world()
terracotta_direct_connect(address)
check_mod_updates(instance)
apply_mod_update(instance, row)
skin_urls(account_name="")
local_ips()
shutdown(timeout_ms=800)
```

And widen four signatures so the bridge is not strictly weaker than the Qt adapter:

```
add_offline_account(username, skin="")
get_installed_mods(instance, version="")
search_modpacks(query, source, extra=None)
test_ai_connection(settings=None)
```

Finally, emit a **`theme_changed`** SSE event (the Qt adapter has the signal; the bridge does not), so both clients can repaint without polling `get_settings`.

I've confirmed there are no matches for the legacy keys across the 901-line file, including the tail section with ScrollBar templates. Now I'm ready to write the report.