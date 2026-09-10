I now have everything needed. Here is the full analysis.

---

# PyMCL Bridge ↔ `app/backend.py` Gap Analysis & Protocol Reference

Scope: `wt-opus45` worktree only. Files read: `bridge/server.py`, `bridge/api.py`, `bridge/selftest.py`, `app/backend.py` (all 2434 lines), `app/pages/ai_page.py`, `mclauncher/ai/{agent,tools,client,store,defaults}.py`, `mclauncher/config.py`, `mclauncher/launch_flow.py`, `eziapp/src/bridge.ts`, `eziapp/src/pages/ai.ts`, `eziapp_launcher.py`, `wpf/PyMCL.Wpf/Services/{BridgeHost,BridgeClient}.cs`, `native/src/server.c` (skimmed). Method lists were produced by AST-parsing both classes; every `mclauncher.*` symbol referenced by `bridge/api.py` was verified to exist (all 48 modules / ~200 symbols resolved).

---

## 1. Protocol reference (`bridge/server.py`)

### 1.1 Process start-up & discovery

| Item | Behaviour |
|---|---|
| Entry point | `python -u bridge/server.py --root <launcher_root> [--host 127.0.0.1] [--port 0] [--token T] [--allowed-origin http://127.0.0.1:PORT]... [--ready-file path]` |
| `--root` (required) | `_prepare_root()`: sets `os.environ["PYMCL_HOME"]`, `os.chdir(root)`, prepends root to `sys.path`. Then `mclauncher.guard.install(root/"pymcl-error.log")`, then imports `bridge.api`. |
| `--host` | Only the literal `127.0.0.1` is accepted (`_validate_bind_host`). `localhost` is rejected. |
| `--port` | `0` (default) = OS-assigned ephemeral port. |
| Token | Precedence: `--token` > env `PYMCL_BRIDGE_TOKEN` > `secrets.token_urlsafe(32)`. Must be ≥ 32 chars (`BridgeState` raises otherwise → `parser.error`). WPF host passes a 64-hex-char token via env. |
| `--allowed-origin` | Repeatable. Normalised by `_normalize_origin`: must be `http://127.0.0.1[:port]`, no path/query/userinfo. Stored as `frozenset`. Empty by default (native clients that send no `Origin` are still allowed). |
| `--ready-file` | Atomic write (`mkstemp` + `os.replace`, mode 0600 on POSIX) of `{"rpc_url": "http://127.0.0.1:<port>", "token": "<token>"}`. Deleted on exit. |
| Banner | Written to **both** stdout and stderr, flushed: `PYMCL_BRIDGE port=<n> host=127.0.0.1 root=<root> auth=token\n`. WPF `BridgeHost` reads stdout lines up to 30 s until it sees `PYMCL_BRIDGE`, parses `port=(\d+)`, then polls `GET /health` up to 60×100 ms. **The token is never printed**; a parent must supply it via `--token`/env or read the ready-file. |
| Serve loop | `httpd.serve_forever(poll_interval=0.3)`; `KeyboardInterrupt` → clean shutdown. |
| In-process embedding | `eziapp_launcher.py` does not spawn a subprocess: it calls `create_http_server(LOOPBACK_HOST, 0, BridgeState(api, bus, token=..., allowed_origins=[ui_origin]))` on a daemon thread, and hands the config to the browser either via URL fragment `#pymcl_bridge=<urlsafe-b64 JSON {rpc_url,token}>` (dev server / `--ui-url`) or by serving `/bridge-config.json` from its own static server (dist mode). `eziapp/src/bridge.ts` tries the fragment first (and scrubs it from history), then `GET /bridge-config.json`. |
| Logging | `log_message` prints only `[bridge] <METHOD> <path>` (query string with token stripped). |

### 1.2 Endpoints

| Method + path | Auth | Purpose / response |
|---|---|---|
| `GET /health`, `GET /` | token required | `200 {"ok": true, "name": "pymcl-bridge"}` |
| `POST /rpc`, `POST /` | token required | JSON-RPC 2.0 (see 1.4) |
| `GET /events` | token via header **or** `?token=` query (exactly one value) | SSE stream (see 1.5) |
| `OPTIONS /rpc|/events|/health|/` | none, but **requires `Origin` in allow-list** | `204` with `Access-Control-Allow-Methods: GET, POST, OPTIONS`, `Access-Control-Allow-Headers: Content-Type, X-PyMCL-Bridge-Token`, `Access-Control-Max-Age: 600`. Without `Origin` → `403 {"error":"origin required"}`. Other paths → 404. |
| anything else | loopback check only | `404 {"error":"not found"}` |

Every response has `Cache-Control: no-store`; `Content-Type: application/json; charset=utf-8`. CORS headers (`Access-Control-Allow-Origin: <origin>`, `Vary: Origin`) are added only when the request carried an allowed `Origin`.

### 1.3 Authentication / access control (evaluated in this order)

1. **Socket level**: `LoopbackThreadingHTTPServer.verify_request` silently drops non-loopback peers.
2. **`_request_origin`**: non-loopback client address → `403 {"error":"loopback clients only"}`. If an `Origin` header is present and not in `allowed_origins` → `403 {"error":"origin not allowed"}`. No `Origin` header ⇒ permitted (native clients).
3. **`_authorize`**: header `X-PyMCL-Bridge-Token` compared with `hmac.compare_digest`; for `/events` only, fallback to `?token=`. Failure → `401 {"error":"authentication required"}`.

Note the 401/403/404/413/400-content-length bodies are **plain `{"error": "<str>"}`**, not JSON-RPC envelopes.

### 1.4 JSON-RPC over `POST /rpc`

Request: body ≤ `MAX_REQUEST_BYTES` = 4 MiB (else `413`), UTF-8 JSON object. Missing/zero `Content-Length` is treated as `{}`.

```json
{"jsonrpc":"2.0","id":<any>,"method":"<public method name>","params":{...} | [...]}
```

| Condition | HTTP | Body |
|---|---|---|
| body not valid UTF-8 / JSON | 400 | `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"<exc>"}}` |
| body not an object | 400 | `error.code -32600 "request must be an object"` |
| `method` missing / not str | 400 | `error.code -32600 "method required"` (id echoed) |
| method starts with `_` | **200** | `error.code -32601 "hidden method"` |
| `getattr(api, method)` not callable | **200** | `error.code -32601 "unknown method: <m>"` |
| method raised any `Exception` | **200** | `error.code -32000 "message": str(exc)` (no `data`, no exception type) |
| `params` neither list nor dict | 200 | `-32000 "params must be object or array"` |
| success | 200 | `{"jsonrpc":"2.0","id":<echo>,"result":<value>}` |

**Params handling** (`_call_kwargs`, `server.py:281`):
- `params` **array** → `fn(*params)` positional.
- `params` **object** → only keys matching the method's declared parameter names are forwarded; **unknown keys are silently dropped** unless the method has `**kwargs` (only `update_server(instance, index, **kwargs)`), in which case all remaining keys are passed through. Missing required parameters surface as a Python `TypeError` string in a `-32000` error.
- `params` absent/null → `{}`.
- `id` is echoed as-is (may be `null`); there is no notification mode—every request gets a response.

**Result serialisation**: `json.dumps(..., ensure_ascii=False, default=_json_default)`; `pathlib.Path` → `str`. Any other non-JSON type raises `TypeError` **outside** the try/except → no JSON-RPC response is sent, the handler thread prints a traceback and the connection is closed (client sees an empty/aborted response). Return values are otherwise unbounded in size.

### 1.5 SSE `GET /events`

Headers: `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache, no-store`, `Connection: keep-alive`, `X-Accel-Buffering: no`.

Frame format (`server.py:271`): `event: <name>\ndata: <compact JSON object>\n\n`. There are **no `id:` lines, no `retry:` field, no multi-line `data:`**.

- First frame: `event: hello\ndata: {"ok": true}\n\n`.
- Idle for 15 s → comment frame `: keepalive\n\n`.
- The event name comes from `payload["event"]` (defaults to `"message"`); `data` from `payload["data"]` (defaults to `{}`).
- Subscription = one `queue.Queue(maxsize=800)` created at connection time (`EventBus.subscribe`). Events emitted before connection or during a reconnect gap are **lost** — there is no replay/`Last-Event-ID` support. On queue overflow `put_nowait` raises and the event is **silently dropped for that subscriber** (`EventBus.emit`, `api.py:46-49`).
- Reconnection is purely client-side: `bridge.ts` reopens after 3 s on `onerror`; WPF uses exponential backoff 1→15 s. After reconnect a client must re-poll state (`get_instances`, `get_settings`, `get_account_rows`, …) — and there is **no RPC to enumerate running tasks** (see §2a `list_tasks`).

### 1.6 Threading model

- `ThreadingHTTPServer` with `daemon_threads=True`, `protocol_version=HTTP/1.1` (keep-alive). One thread per TCP connection; requests on the same connection are serialised, different connections run concurrently. There is **no global lock** around `BackendAPI` calls → concurrent RPCs run truly in parallel against a not-fully-thread-safe object (e.g. `_pack_cache`, `CONFIG.set/save`, `accounts`).
- Each SSE client permanently occupies one handler thread.
- Long-running work: `start_task(title, fn, *args)` creates `BackendWorker(threading.Thread, daemon=True)`, `task_id = f"task-{n}"` (monotonic counter from 1). The RPC returns the id immediately. Worker calls `fn(progress, log, *args, **kwargs)`; `progress(current,total,message)` raises `TaskCancelled` if `cancel()` was called; `_dm()` also wires `DownloadManager(cancel=...)`. Return value `str` → `finished.message`, otherwise `"任务完成"`.
- `cancel_task(task_id)`: sets worker flag; if it is the launch task, also `proc.kill()` on the game process.
- `wait_task(task_id, timeout=1800)` is public and callable via RPC — it **blocks the connection thread** polling every 0.3 s.
- Synchronous heavy RPCs (`fetch_version_list`, `search_*`, `get_launch_command` (may download Java), `cleaner_apply`, `submit_feedback`, `test_ai_connection`, `collect_sysinfo(force=True)`, `list_catalog_files`, `check_update`, `get_java_list(scan_system=True)`, `get_instances` when Java scan cache is cold) block only their own connection.
- Server has no socket/read timeout: a client that sends `Content-Length` but not the body pins a thread forever. Client timeouts: WPF `HttpClient` 20 min; TS `fetch` none; `selftest.py` 120 s.

### 1.7 Every event emitted by `bridge/api.py` (+ `hello` from server)

| Event | Emitted from | `data` keys |
|---|---|---|
| `hello` | `server._sse` | `ok: true` |
| `task_added` | `start_task` (after `worker.start()`, so a very fast task's `progress`/`finished` can precede it) | `task_id: str`, `title: str` |
| `task_count_changed` | `start_task`, `_emit("finished")` | `count: int` — number of **all** live workers (Qt counts only "download" tasks) |
| `progress` | `BackendWorker._progress` | `task_id`, `current: int`, `total: int`, `message: str` — **unthrottled**, raw byte counts (may exceed int32; WPF `TryGetInt32` yields 0) |
| `log` | `BackendWorker._log` (incl. `[错误] …` on failure) | `task_id`, `text` |
| `finished` | `BackendWorker.run` → `_emit` | `task_id`, `success: bool`, `message: str`, optional `crash: true`. Followed immediately by `task_count_changed`, and by `ui_changed {}` if `success` |
| `crash` | `BackendWorker.run` on `GameCrashError` (before `finished`) | full crash report dict from `mclauncher.crash.analyze_launch` (`is_crash,title,headline,summary,detail,help,reasons,exit_code,exit_hint,direct_file,files,instance,version,output_tail,log_mc,log_crash,log_hs,has_latest,has_crash,has_hs_err,actions[]`) **plus** `task_id`. Cached for `get_crash()` (last 40). |
| `login_code` | `_microsoft_login_impl` via `worker.login_code` | `code: str`, `uri: str` |
| `login_status` | `_microsoft_login_impl` | `text: str` |
| `ui_changed` | many sync mutators + successful task finish | `{}` |
| `game_started` | `_launch_game_impl` | `{}` |
| `game_exited` | `_launch_game_impl` (finally) | `code: int \| null` |
| `ai.delta` | `_ai_run.flush_delta` (coalesced ≥33 ms) | `text: str` |
| `ai.status` | `_ai_run.on_status` | `kind` + payload keys (see §4) |
| `ai.confirm` | `_ai_run.confirm_fn` | `name`, `args: dict`, `label` |
| `ai.ask` | `_ai_run.ask_fn` | `questions: list`, `title: str` |
| `ai.done` | `_ai_run` | `text: str`, `store: dict` (whole chat store) |
| `ai.fail` | `_ai_run` | `text: str`, `stopped: bool` |

`eziapp/src/bridge.ts` registers listeners for exactly these 18 names (`hello` included) — any new event name added later must be added there too because `EventSource` needs an explicit `addEventListener` per named event.

### 1.8 Differences vs the C bridge (`native/src/server.c`) that a frontend may hit

- C: `/health` is **public** (no token) and returns extra `port`; `GET /bridge-config.json` is public and **returns the token**; serves static UI from `www/`; `OPTIONS` → 405; only checks that `Origin` is loopback (no allow-list); `Sleep(15000)` keepalive; 4 MiB body cap identical; same error codes; positional params unsupported semantics differ per method. Python bridge has none of the public endpoints.
- WPF `BridgeHost` prefers the C bridge (`pymcl-bridge.exe`) unless `PYMCL_BRIDGE=python`.

---

## 2. Method-by-method comparison

Counts: `app/backend.py` **169** public methods, `bridge/api.py` **165**.

### 2a. Present in `app/backend.py`, **missing** in `bridge/api.py`

| Method (app signature) | What it does / returns | Needed over RPC? |
|---|---|---|
| `check_mod_updates(instance) -> list` | `mod_update.check_updates(inst)` – returns rows `{name,current,latest,...}` without applying | Yes (mods page "check only") |
| `apply_mod_update(instance, row: dict) -> str` | applies one update row, emits `ui_changed`; returns new filename | Yes |
| `open_media(path) -> bool` | `open_path(path)` for screenshots/logs | Yes (eziapp `dialogs.ts` currently misuses `open_crash_file` for this) |
| `set_game_dir(path) -> str` | sets `instances_dir` (abs or relative), saves, `ui_changed`; returns resolved `CONFIG.instances_dir` | Yes |
| `skin_urls(account_name="") -> dict` | `{avatar, body}` URLs; `"离线模式"`/empty → Steve | Yes |
| `local_ips() -> list` | `lan.local_ips()` | Yes |
| `terracotta_enter_world()` | if snapshot `state=="guest-ok"` launches latest version with `--server host --port`; raises `TerracottaError` otherwise; returns task_id or the "already running" message | Yes |
| `terracotta_direct_connect(address)` | validates non-loopback host, same launch path | Yes |
| `shutdown(timeout_ms=800)` | cancels non-launch workers, waits | Optional (graceful exit RPC) |
| `invalidate_instances()` | clears 2.5 s instance cache | N/A (bridge has no cache) |
| `is_download_title(title)` (staticmethod) | title-based classification used for the download badge count | Should be replicated inside `task_count_changed` semantics |
| `call_async(fn, on_ok, on_err)` | Qt `SilentWorker` helper | N/A (not RPC-able) |

Also **referenced by frontends but present in neither backend**:
- `list_tasks` (WPF `TasksPage.xaml.cs:22`) — a snapshot `[{task_id,title,current,total,message}]` is required for SSE late-joiners/reconnects; bridge has `_workers`/`_titles` but no getter.
- `download_version` (WPF `DownloadPage.xaml.cs:41`) — does not exist anywhere (should map to `install_game`).

### 2b. Present in both, but different signature / return / behaviour

| Method | app/backend.py | bridge/api.py | Impact |
|---|---|---|---|
| `add_offline_account` | `(username, skin="")`, default skin = `CONFIG.offline_skin` | `(username)`; `offline_account(username)` → skin `"default"`, ignores configured skin | Skin setting ignored |
| `apply_crash_action` | `(action, report=None)`; `open_crash_file` distinguishes "文件不存在" | `(action=None, report=None)` | Cosmetic |
| `build_launch_command` | reads version-settings `auth_server`, injects `props["authlib_api"]`, passes `authlib_api=` | no `auth_server` handling, no `authlib_api=` kwarg | Wrong command for custom-Yggdrasil versions |
| `get_installed_mods` | `(instance, version="")` → enabled files in `_mods_folder(inst, version)` | `(instance)` → `list_instance_mods` (shared dir only) | Cannot list version-isolated mods |
| `preflight_launch` | `(instance, version, memory_mb=0, java="")`; resolves `java` through `normalize_java_pref` | `(instance="", version="", …)`; passes raw string as `java_exe` | Java *names* (from `get_java_list`) not resolved → false preflight errors |
| `search_modpacks` | `(query, source, extra=None)`; `_catalog_source` supports `""/"全部"/"all"`; passes `game_version`/`categories`; popular rows carry `description="热门推荐"`, `tags=["热门"]` | `(query, source)`; `""`/`"全部"` ⇒ Modrinth; no filters; no `tags` | eziapp filter panel ignored; no "all" |
| `search_mods` | supports `"all"` source; result rows include `icon_url`; popular rows include `description`, `tags`, `icon_url` | no `"all"`; no `icon_url`; popular rows lack `description`/`tags` | UI shows no icons |
| `search_shaders/resourcepacks/datapacks` (`_content_row`) | includes `icon_url` | no `icon_url` | same |
| `test_ai_connection` | `(settings=None)` – lets settings page test unsaved values | `()` | Cannot test before saving |
| `install_game` / `launch_game` / `build_launch_command` defaults | `tr("无")`, `tr("自动选择")`, `tr("离线模式")` (locale-dependent sentinels) | hard-coded Chinese | If Qt runs in `en`, stored/UI sentinels differ; bridge only understands the Chinese sentinel `"离线模式"` for offline |
| `rename_version`, `copy_version`, `hide_version` | emit `ui_changed` | no `ui_changed` | Stale UI |
| `delete_save`, `delete_modpack`, `set_global_mod_enabled`, `set_language`, `load_theme` | emit `ui_changed` (`load_theme` also `theme_changed`) | no event | Stale UI |
| `save_settings` | see §3; also calls `source.invalidate_probe()`, `net.apply_proxy_policy()`, `source.warmup_async()`, emits `theme_changed` when `ui_dark/theme_color/ui_background` in data; validates `ai_permission_mode ∈ {standard, full}` | only `CONFIG.update(patch); CONFIG.save()`. **Does not accept `ai_confirm_writes` / `ai_permission_mode`** | Proxy/source changes don't take effect until restart; AI permission cannot be changed from eziapp |
| `get_settings` | 47 keys | 35 keys (see §3) | |
| `get_setting` | cached by `CONFIG.revision` | rebuilds dict each call | Perf only |
| `get_instances` | 2.5 s TTL cache; `instance_java_label` uses `cached_all_javas()` (never scans) | no cache; `instance_java_label`/`normalize_java_pref` call `java_mod.all_javas()` → can trigger a **synchronous system-wide Java scan** (Program Files glob + `java -version` per JRE) inside an RPC; `__init__` also skips `warm_system_javas_async()` and `source.warmup_async()` | First `get_instances` may take seconds |
| `download_java` | non-adoptium → `install_java(int(major), vendor)` | wraps in `try/except: pass` then falls back to Adoptium (dead code path; `install_java` never raises) | Cosmetic |
| `open_mods_folder` | `open_path()`; raises `LaunchError("无法打开…")` on failure | `os.startfile`/`open`/`xdg-open` fire-and-forget | Cosmetic |
| `open_global_mods` | same | same (both use `xdg-open` on macOS – minor bug in both) | |
| `import_servers(instance, text)` | accepts JSON array (`import_servers_json`) or line text | text only | JSON import fails |
| `get_launch_command` | no `account` ⇒ **offline** account with `username` | no `account` ⇒ **active** account (`ensure_valid`, may do network refresh) else offline | Different output; bridge may block on token refresh |
| `start_task`/`task_count_changed` | `_download_task_count()` excludes titles starting with 启动游戏/微软登录/皮肤站登录 | counts every worker | Badge count differs |
| `finished` for crash | `(task_id, False, str(exc))` | adds `"crash": true` | Superset, fine |
| `progress` | throttled (≥80 ms or ≥0.5 % change), values >2e9 rescaled to ‰ (0..10000) | every downloader callback, raw ints | Event flood (800-slot queue overflow → silent drops), int32 overflow in WPF |
| `_install_mod_impl` (behind `install_mod`) | honours `extra["version"]` → installs into `versions/<id>/mods` (`mods_dir=`) and logs target | **ignores `extra["version"]`**, always shared `mods/` | eziapp `mods.ts:85` passes `version: tgtSel.value` → silently installs to wrong folder |
| `_install_content_impl` (datapack) | `extra["save"]`/`extra["world"]` → `install_datapack_into_save` | not supported | |
| `_launch_game_impl` | handles version-settings `auth_server` (authlib inject), logs isolation/global-mod count/vanilla-with-jars warning, return `"已正常退出"` | no `auth_server`, returns `"游戏已退出"` | Custom auth server ignored at launch |
| `_export_bat_impl` | `auth_server`, ensures authlib injector / nide8 jar before building | none of that | Exported script may miss `-javaagent` |
| `_self_update_impl` | passes `self._dm(...)` to `updater.check/download` (progress), returns `apply_exe()` message | no dm (no progress), fixed message | |
| `_microsoft_login_impl` | returns `None` → finished message `"任务完成"` | returns `"已登录 X"` | Cosmetic |
| `_authlib_login_impl`, `_nide8_login_impl` | emit `progress(0,0,…)`/`(1,2,…)` steps | no progress | Cosmetic |
| `_mod_update_impl` | logs per-mod "更新 A cur → latest" | minimal logging | Cosmetic |
| `_install_game_impl` | stores `self._last_installed = {instance, version, loader}` (main_window uses it for "install then launch") | not stored | Frontend cannot learn the real installed version id (e.g. `1.20.1-fabric-…`) except via `finished.message` `"已安装 <vid>"` |
| `ai_*` | **do not exist** in `app/backend.py` — the Qt AI logic lives in `app/pages/ai_page.py::AgentThread` | 8 methods | see §4 |

### 2c. Bridge methods that look **broken**

| # | Where | Problem |
|---|---|---|
| 1 | `mclauncher/ai/tools.py:494,504,508` (`create_instance`, `disable_mod`, `enable_mod` AI tools) call `backend.ui_changed.emit()` | Bridge `BackendAPI` has **no `ui_changed` attribute** → `AttributeError` → `run_tool` returns `"工具失败: 'BackendAPI' object has no attribute 'ui_changed'"` to the model **after the side-effect already happened**. The model then believes the action failed. (Bridge needs a `ui_changed` shim object with `.emit()` or tools.py must be fixed.) |
| 2 | `save_settings` loop `for key in (… "instances_dir", …): patch[key] = data.get(key)` (`api.py:748-751`) | Writes the raw value with **no validation**: `{"instances_dir": ""}` or `null` is persisted → `CONFIG.instances_dir` becomes `ROOT/""` = the launcher root itself. The app version only accepts a non-empty stripped string. Same loop stores `None` for `launcher_visibility`/`gc_preset`/… if the client sends `null`. |
| 3 | `save_settings` silently drops `ai_confirm_writes`, `ai_permission_mode`, `allow_multi_instance`, `show_hidden_versions`, `theme_color`, `ui_background`, `global_mods_dir`, `default_priority`, `ui_fly_*`, `ui_motion`, `first_run` | `get_settings` exposes `ai_confirm_writes`/`ai_permission_mode` but they can't be written → eziapp settings page round-trip loses them. |
| 4 | `_install_mod_impl` ignores `extra["version"]` | eziapp `mods.ts:85` passes it → mod lands in shared `mods/` while the UI shows the isolated target. |
| 5 | `preflight_launch` passes `java` verbatim as `java_exe` | Frontends pass the value from `java_combo_options` (an exe path) or `get_java_list().name` — names produce spurious "Java not found" preflight errors (app resolves with `normalize_java_pref`). |
| 6 | `EventBus.emit` + unthrottled `progress` | `queue.Full` swallowed → whole events (including `finished`!) can be dropped for a slow SSE consumer during a large download. |
| 7 | `_send_json` `TypeError` for non-serialisable results happens outside the `try` | Connection is torn down with no JSON-RPC error. (No current method is known to return such a type, but e.g. a future `set`/`bytes`/`datetime` would.) |
| 8 | `export_launch_script` returns a task id but eziapp `launch.ts:169` treats the result as the file path | Frontend bug rooted in the async design; a sync variant or `finished.message` usage is needed. |
| 9 | `get_installed_modpacks` — fine; `delete_modpack(instance, filename="")` deletes the **whole instance** (identical in app) | Not broken, but surprising for frontend implementers. |
| 10 | `wait_task` exposed publicly | RPC callers can block a connection thread for up to 1800 s; harmless but should be hidden or bounded. |
| 11 | `_call_kwargs` drops unknown kwargs silently | Typos in frontend param names (e.g. `taskId` vs `task_id`) fail as `TypeError: missing argument` or, for optional params, silently use defaults. Consider returning `-32602`. |

Nothing in `bridge/api.py` references a non-existent `mclauncher` function; all argument orders match the callee signatures checked (`search_curseforge`, `install_curseforge_mod(..., file_id=, mods_dir=)`, `install_mod_from_source(..., version_id=, mods_dir=)`, `search_modpacks_chinese(dm,q,limit,api_key,game_version,categories)`, `updater.check(dm=None)`, `updater.download(info, dm=None)`, `launch_flow.prepare(inst, vid, extra_game_args, memory_mb)`, `servers.update_server(inst, index, **kw)`).

### 2d. Qt `Signal`s in `app/backend.py` vs bridge events

| Qt signal (`BackendAPI`) | Bridge event | Notes |
|---|---|---|
| `task_added(str,str)` | `task_added {task_id,title}` | ✓ |
| `progress(str,int,int,str)` | `progress` | ✓ (no throttle / no int32 clamp) |
| `log(str,str)` | `log {task_id,text}` | ✓ |
| `finished(str,bool,str)` | `finished` | ✓ |
| `crash(str,object)` | `crash` (report ∪ `task_id`) | ✓ |
| `login_code(str,str)` | `login_code {code,uri}` | ✓ |
| `login_status(str)` | `login_status {text}` | ✓ |
| `ui_changed()` | `ui_changed {}` | ✓ but emitted from fewer places (see 2b) |
| **`theme_changed()`** | **none** | ✗ — emitted by app on `save_settings` (theme keys) and `load_theme`; needed so a frontend can re-apply theme when another client/AI changes it |
| `task_count_changed(int)` | `task_count_changed {count}` | ✓ different counting rule |
| `game_started()` | `game_started {}` | ✓ |
| `game_exited(object)` | `game_exited {code}` | ✓ |
| `BackendWorker.*` (progress/log/task_finished/crash/login_code/login_status) | same as above | ✓ |
| `AgentThread.delta/status/need_confirm/need_ask/done/failed` (`ai_page.py`) | `ai.delta/ai.status/ai.confirm/ai.ask/ai.done/ai.fail` | ✓ see §4 |

---

## 3. Settings

### 3.1 `DEFAULT_CONFIG` keys (`mclauncher/config.py`, 62 keys)

`instances_dir, default_instance, java_dir, shared_libraries, shared_assets, memory_mb, download_threads, width, height, microsoft_client_id, curseforge_api_key, github_proxy_prefixes, force_manifest_refresh, download_source, community_source, use_system_proxy, ai_mode, ai_gateway_url, ai_base_url, ai_api_key, ai_model, ai_confirm_writes, ai_permission_mode, terracotta_extra_nodes, feedback_url, feedback_heartbeat, feedback_consent(None), device_id, default_isolation, default_jvm_args, default_priority, update_url, theme_color, ui_dark, ui_background, ui_fly_animation, ui_fly_duration_ms, ui_motion, ui_layout, ui_layouts, ui_layout_profile, ui_nav_order, ui_nav_hidden, ui_nav_pinned, ui_section_members, ui_sidebar_width, default_java, global_mods_dir, launcher_visibility, gc_preset, download_limit_kbps, auto_check_update, custom_homepage, homepage_mode, window_mode, skip_assets, first_run, show_hidden_versions, catalog_favorites, offline_skin, allow_multi_instance, language`

`Config.load()` keeps unknown keys from disk too; `revision` increments on every `set/update/load`.

### 3.2 `get_settings()` — settings-key → CONFIG-key mapping

Shared by both (35): `share_libraries→shared_libraries`, `share_assets→shared_assets`, `download_threads`, `default_memory_mb→memory_mb`, `default_resolution→[width,height]`, `ms_client_id→microsoft_client_id`, `curseforge_api_key`, `ai_mode`, `ai_gateway_url` (falls back to `DEFAULT_GATEWAY_URL`), `ai_base_url`, `ai_api_key`, `ai_model` (fallback `DEFAULT_MODEL`), `ai_confirm_writes`, `ai_permission_mode`, `download_source`, `community_source`, `use_system_proxy`, `feedback_url` (fallback `DEFAULT_FEEDBACK_URL`), `feedback_heartbeat`, `feedback_consent` (`is True`), `default_isolation`, `default_jvm_args`, `update_url`, `ui_dark`, `launcher_visibility`, `gc_preset`, `download_limit_kbps`, `auto_check_update`, `custom_homepage`, `homepage_mode`, `window_mode`, `offline_skin`, `default_java`, `game_dir` (= `str(CONFIG.instances_dir)` absolute), `root` (= `str(utils.ROOT)`).

**App only (12), missing from bridge `get_settings`:** `ui_fly_animation`, `ui_motion`, `ui_fly_duration_ms`, `default_priority`, `theme_color`, `ui_background`, `global_mods_dir`, `skip_assets`, `allow_multi_instance`, `first_run`, `show_hidden_versions`, `instances_dir` (raw relative value; bridge only gives absolute `game_dir`).

Bridge-only keys: none.

Not exposed by either (frontend must use dedicated RPCs or is simply blocked): `default_instance`, `java_dir`, `github_proxy_prefixes`, `force_manifest_refresh`, `terracotta_extra_nodes`, `device_id`, `ui_layout*`, `ui_nav_*`, `ui_section_members`, `ui_sidebar_width` (eziapp `main.ts:80` sends it via `save_settings` → **silently discarded by both**), `catalog_favorites` (→ `catalog_favorites()`/`toggle_favorite`), `language` (→ `get_language`/`set_language`), `allow_multi_instance` (bridge → `allow_multi_instance()`/`set_multi_instance()`).

### 3.3 `save_settings(data)` accepted keys

| Key | App | Bridge |
|---|---|---|
| `share_libraries, share_assets, download_threads, default_memory_mb, default_resolution, ms_client_id, curseforge_api_key, ai_mode, ai_gateway_url, ai_base_url, ai_api_key, ai_model, download_source, community_source, use_system_proxy, default_isolation, default_jvm_args, update_url, ui_dark, launcher_visibility, gc_preset, download_limit_kbps, auto_check_update, custom_homepage, homepage_mode, window_mode, skip_assets, offline_skin, default_java, instances_dir, feedback_url, feedback_heartbeat, feedback_consent` | ✓ | ✓ |
| `ai_confirm_writes`, `ai_permission_mode` (validated to `standard\|full`) | ✓ | **✗** |
| `ui_fly_animation`, `ui_motion`, `ui_fly_duration_ms`, `default_priority`, `theme_color`, `ui_background`, `global_mods_dir`, `allow_multi_instance`, `first_run`, `show_hidden_versions` | ✓ | **✗** |
| Post-save side effects | `invalidate_probe()`, `apply_proxy_policy()`, `warmup_async()`, `theme_changed` signal, settings cache reset | none |
| Partial-update semantics | "keep CONFIG value if key absent" (with a few `or`-fallbacks: e.g. `download_threads`, `ai_model` treat falsy as absent) | strict `if key in data` patch; `ai_model` falsy → keeps CONFIG or `"deepseek-v4-flash"` |
| `instances_dir` | only if non-empty after strip | raw value, no validation (broken #2) |

`update_settings(settings)` is an alias of `save_settings` in both.

---

## 4. AI protocol

### 4.1 Where the logic lives

- **Qt**: `app/pages/ai_page.py::AgentThread` (QThread) calls `mclauncher.ai.agent.run_agent(backend, settings, history, text, on_delta, on_status, confirm_fn, ask_fn, cancelled, http_cancel)`; UI answers via `AgentThread.answer_confirm(bool)` / `answer_ask(result)` / `cancel()`. Chat persistence via `mclauncher.ai.store` directly in the page. `backend._ui_launch` is set from the launch page widgets before each send.
- **Bridge**: same `run_agent` inside `BackendAPI._ai_run` (plain `threading.Thread "ai-send"`), exposed through 8 RPCs and 6 SSE events. Only one agent run at a time (`_ai_busy`).

### 4.2 RPC methods (bridge)

| RPC | Params | Returns | Behaviour |
|---|---|---|---|
| `ai_list_chats` | – | store dict `{active_id: str, chats: [{id, title, updated:int, messages:[{role: user\|assistant\|error, content}]}]}` | `store.load()` (creates file `ROOT/ai_chats.json` if missing; ≤40 chats, ≤24 msgs/chat) |
| `ai_new_chat` | – | store dict | prepends blank chat `"新对话"`, makes it active, saves |
| `ai_delete_chat` | `chat_id` | store dict | removes; if list empties creates a blank chat; re-points `active_id` |
| `ai_set_active` | `chat_id` | store dict | unknown id ⇒ no-op (still returns store) |
| `ai_send` | `text: str`, `chat_id: str = ""`, `launch: dict \| null` | `{"ok": true, "started": true}` or `{"ok": false, "message": "上一条还在处理"}` | If busy → rejected (Qt queues instead). Sets `_ui_launch = launch` (keys used by the `launch_game` tool: `instance, version, account, username, memory_mb, width, height, java`). Starts thread; **returns immediately** — all output arrives via SSE. |
| `ai_stop` | – | `{"ok": true}` | sets `_ai_cancel`, `HttpCancel.abort()` (closes session/response), then `ai_confirm(False)` and `ai_answer(None)` to unblock any pending prompt |
| `ai_confirm` | `ok: bool = False` | `{"ok": true}` | sets `_ai_confirm_ok`, fires `_ai_confirm_ev` |
| `ai_answer` | `result: dict \| null` | `{"ok": true}` | sets `_ai_ask_result`, fires `_ai_ask_ev` |
| `test_ai_connection` | – | `str` | `client.test_connection(get_settings())` – GET `models_url`, 15 s timeout |

### 4.3 Event flow for one `ai_send`

1. `_ai_run` loads store; if `chat_id` given → `set_active`; builds `history = api_messages(chat.messages)` (`error`→`assistant`, other roles dropped).
2. `run_agent` loop (≤ `MAX_TOOL_ROUNDS`=10):
   - `ai.status {kind:"think", after_tools: bool}` at each round start.
   - Streaming text → `ai.delta {text}` (buffered, flushed at most every 33 ms; forced flush at end).
   - For each tool call: `ai.status {kind:"tool", name, args, label}` then one of:
     - **ask_user**: `ai.ask {questions:[{id, prompt, allow_multiple, options:[{id,label}]}], title}` (normalised by `normalize_ask_args`: always appends `{id:"other", label:"其他"}`; `<2` options ⇒ prepends `{id:"skip",label:"先不选"}`). Blocks until `ai_answer`. Expected `result` shape (what both UIs send): `{"answers": {"<qid>": {"ids": [...], "labels": [...], "other_text": ""}}}`; `null`/falsy ⇒ tool result `"用户取消了选择"` + `ai.status {kind:"tool_skip", name, label}`; otherwise `ai.status {kind:"tool_done", name, label:"已选择", result}`.
     - **search_mods / search_modpacks / search_versions**: `tool_run` → `tool_done {name,label,result≤400}`; repeated identical query in same turn ⇒ `tool_skip {label:"拦截重复搜索"}`.
     - **write tool** (`WRITE_TOOLS`): if `_confirm_policy(settings, name)` is true (i.e. `ai_confirm_writes` and either mode `standard` or tool ∈ `DANGEROUS_TOOLS={delete_instance, delete_mod, write_mod_config}` when mode `full`) → `ai.confirm {name, args, label}` and block until `ai_confirm`. `false` ⇒ `tool_skip`; `true` ⇒ `tool_run` → `run_tool(wait = name ∉ LONG_TOOLS and name != "launch_game")` → `tool_done {name, label, result≤400, task_id?}` (`task_id` extracted when tool returned `{"task_id":..., "queued": true}` — i.e. for `install_*`/`download_java` the UI should bind this `task_id` to subsequent `progress`/`finished` events, as the Qt `ToolLine.bind_task` does).
     - other read tools: `tool_run` → `tool_done`.
3. End: `ai.done {text, store}` — `text` = reply + `"（本轮：<tool labels>）"` suffix if any tools ran; store already has `user`+`assistant` appended (`upsert_messages(history[-24:])`, auto-title from first user message).
4. Errors: `ai.fail {text:"已停止", stopped:true}` on `AgentCancelled`/cancel; `ai.fail {text:str(exc), stopped:false}` on `AIClientError`/any exception. **Nothing is persisted on failure** (Qt persists `{"role":"error", ...}` and the user message).

### 4.4 Gaps vs the Qt AI page

| Area | Qt (`ai_page.py`) | Bridge |
|---|---|---|
| Busy handling | queues messages, sends next after finish | rejects with `ok:false` |
| Failure persistence | writes user + `error` message to store | not persisted; `ai.fail` only |
| Correlation of confirm/ask | per-`AgentThread` events; only one live | single shared `Event`; no request id in `ai.confirm`/`ai.ask`, so a late answer to a previous prompt is applied to the next one |
| Permission UI | `save_settings({ai_confirm_writes, ai_permission_mode})` | **bridge `save_settings` drops both keys** → permission level cannot be changed from non-Qt frontends |
| `test_ai_connection(settings)` | tests unsaved values | saved values only |
| Retry | `_retry()` re-sends last user message | frontend must implement (`ai_send` again) |
| Tool → task progress | `tool_done.task_id` bound to `progress`/`finished` | same data available; frontend must correlate |
| AI tools `create_instance`/`enable_mod`/`disable_mod` | `backend.ui_changed.emit()` works | **AttributeError** (broken #1) |
| Welcome text depends on `ai_confirm_writes` | UI-side | frontend must read `get_settings().ai_confirm_writes` |
| Status label (`ai_mode`/`ai_model`) | from `get_settings` | same |

Timeouts inherited from `mclauncher/ai/defaults.py`: stream connect 15 s / read 90 s, non-stream 90 s, `max_tokens` 2048, `MAX_TOOL_RESULT` 8000 chars, `MAX_HISTORY` 24. Proxies are forced off for AI calls (`proxies={"http": None, "https": None}`).

---

## 5. Other things a frontend implementer must know

- **`_emit` thread-safety**: `EventBus.emit` snapshots subscribers under a lock and uses `Queue.put_nowait` (thread-safe); `BackendAPI._emit` mutates `_crashes`/`_task_results`/`_workers` (the latter under `_lock`) and is called from worker threads, RPC threads and the AI thread. Safe to call from anywhere; ordering across threads is not guaranteed.
- **RPC does not block while tasks run**; tasks live in daemon threads. But `wait_task`, `fetch_version_list`, `search_*`, `get_launch_command`, `test_ai_connection`, `check_update`, `cleaner_apply`, `submit_feedback`, `collect_sysinfo(force)` and cold `get_instances`/`java_combo_options(scan_system=True)` are synchronous and can take seconds–minutes. Browsers cap 6 connections per origin and SSE holds one — do not fire many slow RPCs concurrently.
- **Ordering caveats**: `task_added` may arrive *after* the first `progress`/`log` of that task; `finished` is always followed by `task_count_changed`, then `ui_changed` on success; `crash` precedes its `finished` (`crash:true`).
- **Event loss**: per-subscriber queue of 800; no replay. After (re)connecting, re-fetch state; running tasks cannot currently be recovered (no `list_tasks`). Keep the SSE consumer fast (progress can arrive hundreds of times per second during downloads).
- **Sizes**: request body ≤ 4 MiB (`413`); responses and SSE frames are unbounded (crash reports carry up to ~8 KB `output_tail` + ~10 KB logs; `ai.done.store` carries the whole chat store, ≤40×24 messages).
- **Encoding**: UTF-8 everywhere, `ensure_ascii=False`; Chinese sentinel strings are part of the protocol: `"离线模式"` (offline account for `launch_game`/`build_launch_command`), `"自动选择"` (`JAVA_AUTO`), `"无"` (no loader), `"本地"`-prefixed `source` for local modpack/mod files, `"全部"` for all sources in `_search_content`. `game_exited.code` may be `null`. `progress.current/total` are unbounded Python ints.
- **Timeouts**: server none (SSE idle keepalive 15 s); pick client timeouts per call (≥120 s for search/fetch, effectively unbounded for `wait_task`). `HttpClient`/`fetch` keep-alive reuse means sequential calls on one connection are serialised by the server.
- **Error text** is Python `str(exc)` (mostly Chinese, from `LaunchError`, `InstanceError`, `InstallError`, `RuntimeError`, `TerracottaError`, `FileNotFoundError`, …) with no machine-readable code; `-32000` for all application errors.
- **Instance auto-creation**: `_instance(name)` creates a missing instance directory as a side effect of almost every read (`list_saves`, `get_version_settings`, `get_installed_mods`, …). `get_instances` also calls `_ensure_default_instance()`.
- **Config writes** happen from many methods (`toggle_favorite`, `set_multi_instance`, `apply_crash_action`, `_launch_game_impl` sets `default_instance`, `_install_modpack_impl` sets `default_instance`) — there is no `settings_changed` event; poll `get_settings` after such calls if the UI mirrors them.
- **Security posture differences**: Python bridge requires the token even for `/health`; the C bridge does not and additionally exposes the token on `GET /bridge-config.json`. A frontend targeting both must not rely on the public endpoints.

I'm checking that i18n's available_languages returns a dict correctly, and confirming get_installed_versions behaves consistently between the bridge and app. I'm also verifying the snapshot function's unlocked access matches the app's pattern, and noting that RPC-thread callers like list_catalog_files don't rely on the thread-local worker reference.

Now I'm tracing AI tool execution: tools run in a separate thread and call backend methods like install_game and wait_task, which poll task results fine. But I've confirmed a real bug — create_instance, disable_mod, and enable_mod call backend.ui_changed.emit(), which doesn't exist on the bridge's BackendAPI, causing an AttributeError even though the underlying action already succeeded.

I'm also checking that the offline-mode sentinel string is consistent between launch_game and get_accounts, and that the system message builder's calls to get_instances and get_java_list work fine on the bridge. Testing the AI connection test method looks fine too.

I've spotted a discrepancy in busy-state handling: when ai_send is called while already busy, the bridge immediately returns a rejection message instead of queuing like the Qt version does — a real behavioral gap. Now I'm looking at what fields are included in the ai.done payload.

I've found another persistence gap: on the failure path, the bridge doesn't save either the user message or the error into the chat store, unlike Qt which persists the "error" role message — so failed exchanges vanish from history on the bridge. I'm also noting that switching chats via a chat_id parameter triggers a save, and that the ai_run flow is missing a title parameter that Qt includes.

I'm also checking timing — both bridge and Qt page batch AI response deltas at the same 33ms interval, so that's consistent. Now I'm going through the exact payload shapes for each ai.status kind (think, tool, tool_run, tool_done, tool_skip) as well as ai.confirm, ai.ask, ai.done, and ai.fail, making sure none of their fields collide with the wrapping "kind" key.

For ai_answer, I'm checking that passing null is treated by the agent as the user canceling their selection, while a real answer needs to map question ids to selected option ids, labels, and free text. I'm also tracing a race condition around ai_confirm: the confirm_fn clears its event before waiting, so a stale confirm call is harmless, but there's no request/correlation id on ai.confirm or ai.ask, so if the frontend answers a stale confirm after a new one was already emitted, it could get misapplied to the wrong prompt. I'm also confirming that ai_stop properly resolves any pending confirm or ask calls (with False/None) and cancels the HTTP call, and that its cancel flag lingering afterward is harmless since it gets reset on the next ai_send. Then I move to checking that ai_send's launch parameter correctly populates the internal launch state used by the game-launching tool, and I start comparing get_settings between the app and bridge, noting the app exposes extra keys like ui_fly that the bridge doesn't.

So confirming the app has 47 settings keys versus bridge's 35, leaving exactly those 12 missing keys I identified. Now I need to check whether save_settings on the app side handles the same set of keys or differs further.

I'm finding critical gaps: bridge save is missing ai_permission_mode entirely, meaning eziapp can't change AI permission settings, plus it skips theme_changed callbacks and validation calls like invalidate_probe or warmup_async. There's also a real bug — the bridge writes instances_dir raw, so passing an empty string could corrupt the config by making ROOT itself the instances directory instead of guarding against empty values like the app does elsewhere.

I count 62 total keys, and cross-referencing shows several DEFAULT_CONFIG entries like default_instance, java_dir, github_proxy_prefixes, device_id, and the ui_layout/nav variants aren't exposed by either get_settings implementation — also noting eziapp's main.ts saves ui_sidebar_width which neither backend picks up.

Now I'm checking a few more potentially broken spots: download_java's int(major) conversion falls back silently, open_global_mods uses xdg-open on macOS matching the app's behavior, and I'm starting to look at get_launch_command's account handling.

I continue tracing through each bridge method — accounts.get_account, wait_task, terracotta_snapshot, crash emission, hide_version — checking each looks fine, then note that preflight_launch with an empty instance string correctly falls back to default, and install_java/update_server handle their RPC params correctly. I flag a real issue though: _call_kwargs silently drops unknown kwargs when there's no **kwargs catch-all, meaning frontends sending mistyped parameter names get no error feedback, while missing required positional args instead raise a TypeError surfaced as a -32000 RPC error. I verify translate() correctly calls into i18n's underscore function, and list_catalog_files looks fine, then move on to check apply_cr...

I check that open_mods_folder correctly retrieves the mods folder attribute, and that _install_modpack_impl finishes with the same "任务完成" completion message the app uses. I verify GameCrashError handling emits crash then finished events properly, and confirm _emit's dict mutations are safe enough under the GIL despite lacking explicit locks unlike EventBus.emit's locked subscriber copy. I flag that BackendAPI.__init__ skips the async java warmup calls that the app performs, meaning the first all_javas() call via get_instances could block synchronously — and I make a note to quickly check the root-level _check_rpc.py/_cmp_rpc.py files afterward to avoid missing anything from earlier gap analyses.

Then I decide those root scripts are just dev tooling and not worth digging into. I move on to note the hidden-method rule blocking underscore-prefixed methods, and that non-callable attributes return "unknown method" while blocked methods still return HTTP 200. I flag that wait_task is RPC-callable and can block up to 1800 seconds, risking client timeouts, and highlight key differences in the C bridge: no Origin allowlist beyond loopback checking, OPTIONS returning 405, and both /health and /bridge-config.json being publicly accessible without a token — unlike this bridge where even /health requires authentication.

Now I'm digging into the SSE protocol details: events formatted as name/data pairs, periodic keepalive comments every 15 seconds, an initial hello event, and no id or retry lines. I note the per-subscriber queue caps at 800 with silent overflow drops, then move to CORS behavior — origin echoing only for allowlisted origins, token passed via header for RPC or query param for SSE, and native clients without an Origin header being allowed by default while non-loopback clients get silently rejected. Finally I look at the error object shape, matching JSON-RPC error codes to HTTP status codes: 400 for parse/invalid-request errors, 200 for method-not-found or application errors.

Now I'm cataloging non-JSON-RPC errors (401/403/404/413 with a simple error string) and confirming that request ids get echoed back exactly, including null, and that notifications still receive responses. I note a subtlety where progress values for current/total can overflow 32-bit integers since the bridge sends raw ints but the WPF side silently defaults to zero on overflow.

I'm now compiling the full list of events emitted by the bridge — task_added, task_count_changed, progress, log, finished, crash, login_code, login_status, ui_changed, game_started, game_exited, and the various ai.* events — plus the server-level hello, totaling 17 named events. I'm cross-checking these against the Qt signals to see which have matching bridge equivalents, and noticing theme_changed doesn't have one.

I continue mapping remaining signals: task_count_changed has different semantics between the two, and both game_started/game_exited align, with AgentThread and BackendWorker signals corresponding to the ai.* event family. I verify that get_installed_mods and list_instance_mods both filter to enabled-only entries, and that get_instances follows the same default-instance-then-rows pattern in both app and bridge, just without caching.

I also trace through search_modpacks logic, confirming that an empty or "全部" source defaults to modrinth, and that the popular list filtering only shows modrinth plus CBC packs when source is modrinth, with no true "search all" option. Finally, I flag a possible mismatch: the Qt app's install_game uses a translated sentinel string ("无") that changes under different locales, while the bridge hardcodes the Chinese string, which could cause a mismatch if translations shift other strings like "离线模式" as well.

I check that JAVA_AUTO's value ("自动选择") matches what the bridge passes as its default java argument, so that comparison holds fine. Skipping over _cmp_rpc.py, I note unused imports in bridge/api.py but nothing breaking, and confirm BackendWorker.run properly resets thread-local state in its finally block.

I find a potential dead code path in bridge.download_java's adoptium fallback, since install_java rarely raises. I also catch a real frontend bug: export_launch_script returns a task id rather than a file path, but the launch script frontend code treats it as a destination path string—though this bug exists identically in the original app too, so I note it as a shared caveat rather than a regression. I confirm create_desktop_shortcut is synchronous and fine, then start considering whether RPC calls block while tasks run, concluding they don't since tasks execute in daemon threads and RPC returns immediately with a task id, though GIL contention remains a consideration.

Now I'm examining timeout behavior across the stack: the server has no read timeout, meaning a client sending Content-Length without a body could hang a connection thread indefinitely; the SSE loop polls with a 15-second timeout; and client-side timeouts vary (WPF's HttpClient at 20 minutes, no timeout on the TS fetch, and 120 seconds for selftest). I also look at request/response size limits—4 MiB caps incoming requests but responses and event data are unbounded, with crash reports potentially carrying large tails and logs.

On encoding, I verify UTF-8 and non-ASCII JSON output work consistently, and that Path objects serialize to strings, but flag that other non-serializable types (sets, bytes, datetimes) would raise an unhandled TypeError and drop the connection without a proper JSON-RPC error response—a robustness gap worth noting, particularly for methods like collect_sysinfo or get_version_settings. I also note that game_exited's code field can be None, serializing to JSON null, and I'm tracing the event ordering sequence where finished fires before task_count_changed and conditionally before ui_changed on success.

I'm also spotting a potential race: task_added is emitted after worker.start(), so a fast task could theoretically send progress or finished events before task_added appears on the stream, and the app has this same ordering issue since it starts the worker before emitting.

I note that cancel_task for a launch task terminates the game process consistently across both bridge and app. I'm now ready to begin structuring the actual report, planning to include gaps like list_tasks being missing despite being needed by WPF for reconnect, and download_version being called but not implemented anywhere. I also want to note that get_setting and task_title behave identically between implementations, and that AI history trimming to 24 messages works the same way in both the Qt page and the persisted store despite slightly different access patterns. Another small equivalence I want to mention: Qt sets backend._ui_launch from the launch page while the bridge takes a launch parameter directly, but they function the same, and both append the "（本轮：...）" notes to assistant text after completion, with Qt persisting an error-role message on failure.

I'm now noting that on failure, the bridge doesn't persist anything to history, so the user's message gets lost, whereas Qt does persist an error entry. I also want to flag that Qt queues messages while busy but the bridge just rejects with ok:false instead of queuing. There's also the tool progress binding pattern in Qt's AI page that ties task_id from tool_done events to progress/finished task events, which frontends consuming the bridge could replicate the same way, plus the "think" payload's after_tools field in ai.status worth mentioning.

I'm ready to write the full answer now, planning to use tables and cite specific line numbers where I can, while being careful about their accuracy.