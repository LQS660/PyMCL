#include "pymcl.h"
#include <ctype.h>
#include <pthread.h>

static cJSON *load_parent_ud(const char *pid, void *ud) {
    const char *inst = (const char *)ud;
    return instance_version_json(inst, pid);
}

/* ---------- python one-shot RPC (full parity with bridge.api) ---------- */

static int find_python(char *out, size_t n) {
    const char *env = getenv("PYMCL_PYTHON");
    if (env && env[0] && GetFileAttributesA(env) != INVALID_FILE_ATTRIBUTES) {
        snprintf(out, n, "%s", env);
        return 0;
    }
    {
        const char *known =
            "C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\envs\\pymcl5\\Scripts\\python.exe";
        if (GetFileAttributesA(known) != INVALID_FILE_ATTRIBUTES) {
            snprintf(out, n, "%s", known);
            return 0;
        }
    }
    snprintf(out, n, "python");
    return 0;
}

cJSON *py_rpc_call(const char *method, cJSON *params) {
    return py_rpc_call_ex(method, params, NULL);
}

cJSON *py_rpc_call_ex(const char *method, cJSON *params, int *handled) {
    if (handled) *handled = 0;
#ifdef PYMCL_NO_PY
    /* 去 Python 化验收用的构建：不许悄悄回落到 Python。_c_rpc_coverage.py 认 NOT_NATIVE 这个前缀。 */
    (void)params;
    pymcl_set_error("NOT_NATIVE: %s is not implemented in the C bridge", method);
    return NULL;
#else
    char py[PYMCL_PATH], script[PYMCL_PATH], pin[PYMCL_PATH], pout[PYMCL_PATH], tmpdir[PYMCL_PATH];
    find_python(py, sizeof(py));
    pymcl_path_join3(script, sizeof(script), g_root, "native\\tools", "py_rpc.py");
    if (!pymcl_file_exists(script)) {
        pymcl_path_join3(script, sizeof(script), g_root, "native/tools", "py_rpc.py");
    }
    if (!pymcl_file_exists(script)) {
        pymcl_set_error("py_rpc.py missing; method %s needs Python bridge", method);
        return NULL;
    }
    GetTempPathA(sizeof(tmpdir), tmpdir);
    /* 文件名必须一次调用一套。桥是多线程 HTTP 服务，只按进程 ID 取名的话，
       两个同时落到 Python 回落的请求会抢同一对 in/out 文件：后到的覆盖先到的
       入参，先返回的把对方的 out 文件删掉。表现出来就是随机的
       "unknown method"，以及某个方法拿回另一个方法的结果——实测 list_themes
       返回过陶瓦联机的快照。加线程 ID 和自增序号把它们隔开。 */
    {
        static volatile LONG seq = 0;
        LONG n = InterlockedIncrement(&seq);
        unsigned pid = (unsigned)GetCurrentProcessId();
        unsigned tid = (unsigned)GetCurrentThreadId();
        snprintf(pin, sizeof(pin), "%spymcl-rpc-%u-%u-%ld-in.json", tmpdir, pid, tid, (long)n);
        snprintf(pout, sizeof(pout), "%spymcl-rpc-%u-%u-%ld-out.json", tmpdir, pid, tid, (long)n);
    }

    cJSON *body = params ? cJSON_Duplicate(params, 1) : cJSON_CreateObject();
    if (!cJSON_IsObject(body)) {
        cJSON_Delete(body);
        body = cJSON_CreateObject();
    }
    {
        char *txt = cJSON_PrintUnformatted(body);
        cJSON_Delete(body);
        if (!txt) { pymcl_set_error("params serialize failed"); return NULL; }
        pymcl_write_file(pin, txt, strlen(txt));
        free(txt);
    }

    const char *argv[16];
    int argc = 0;
    argv[argc++] = py;
    argv[argc++] = "-u";
    argv[argc++] = script;
    argv[argc++] = "--root";
    argv[argc++] = g_root;
    argv[argc++] = "--method";
    argv[argc++] = method;
    argv[argc++] = "--params";
    argv[argc++] = pin;
    argv[argc++] = "--out";
    argv[argc++] = pout;
    int rc = pymcl_run_process(argv, argc, g_root, NULL, NULL, 120);
    DeleteFileA(pin);
    cJSON *wrap = pymcl_read_json(pout);
    DeleteFileA(pout);
    if (!wrap) {
        /* 连 out 文件都没有：Python 压根没跑起来（干净机器上没装）或者超时了。
           这跟「方法不存在」是两回事，说清楚，别让用户去查一个存在的方法名。 */
        pymcl_set_error("%s 需要 Python 支持，但这次没跑起来（找不到 python 或已超时，rc=%d）",
                        method, rc);
        return NULL;
    }
    if (!cJSON_IsTrue(cJSON_GetObjectItem(wrap, "ok"))) {
        const char *err = cJSON_GetStringValue(cJSON_GetObjectItem(wrap, "error"));
        /* Python 端跑到了、只是抛了错——这一位告诉调用方错误原因已经在这儿了，
           别再拿 "unknown method" 盖掉它。py_rpc.py 自己判定方法不存在时
           回的也是这条路，那一种才是真的没这个方法。 */
        if (handled && err && strncmp(err, "unknown method", 14) != 0) *handled = 1;
        pymcl_set_error("%s", err ? err : "py_rpc error");
        cJSON_Delete(wrap);
        return NULL;
    }
    cJSON *result = cJSON_DetachItemFromObject(wrap, "result");
    cJSON_Delete(wrap);
    if (!result) result = cJSON_CreateNull();
    if (handled) *handled = 1;
    return result;
#endif
}

/* ---------- helpers ---------- */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    cJSON *v = cJSON_GetObjectItem(o, k);
    const char *s = cJSON_GetStringValue(v);
    return s ? s : def;
}

static int pint(cJSON *o, const char *k, int def) {
    cJSON *v = o ? cJSON_GetObjectItemCaseSensitive(o, k) : NULL;
    return (v && cJSON_IsNumber(v)) ? (int)v->valuedouble : def;
}


static void playtime_path(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "playtime.json");
}

static void version_settings_path(const char *inst, const char *ver, char *out, size_t n) {
    char vd[PYMCL_PATH];
    instance_versions_dir(inst, vd, sizeof(vd));
    pymcl_path_join3(out, n, vd, ver, "pymcl.json");
}

static cJSON *vs_defaults(void) {
    return cJSON_Parse(
        "{\"isolation\":\"none\",\"memory_mb\":null,\"java\":\"自动选择\","
        "\"jvm_args\":\"\",\"game_args\":\"\",\"pre_launch\":\"\",\"post_launch\":\"\","
        "\"pre_launch_wait\":true,\"server\":\"\",\"port\":\"\",\"process_priority\":\"normal\","
        "\"icon\":\"\",\"hidden\":false,\"login_account\":\"\",\"auth_server\":\"\","
        "\"auth_server_name\":\"\",\"nide8_id\":\"\",\"gc\":\"\",\"window_title\":\"\","
        "\"window_mode\":\"window\",\"window_width\":null,\"window_height\":null,"
        "\"skip_assets\":false,\"offline_skin\":\"default\"}");
}

/* mclauncher/version_settings.load：出厂值 + pymcl.json，隔离档位认不出就回 none */
cJSON *version_settings_load(const char *inst, const char *ver) {
    cJSON *data = vs_defaults();
    char path[PYMCL_PATH];
    version_settings_path(inst, ver, path, sizeof(path));
    cJSON *stored = pymcl_read_json(path);
    if (cJSON_IsObject(stored)) {
        cJSON *it = stored->child;
        while (it) {
            cJSON *nx = it->next;
            if (it->string) {
                cJSON_DeleteItemFromObjectCaseSensitive(data, it->string);
                cJSON_AddItemToObject(data, it->string, cJSON_Duplicate(it, 1));
            }
            it = nx;
        }
    }
    cJSON_Delete(stored);
    cJSON *iso = cJSON_GetObjectItemCaseSensitive(data, "isolation");
    const char *s = NULL;
    if (py_truthy(iso)) s = cJSON_GetStringValue(iso);
    else if (py_truthy(config_get("default_isolation"))) s = cJSON_GetStringValue(config_get("default_isolation"));
    else s = "none";
    if (!s || (strcmp(s, "none") && strcmp(s, "saves") && strcmp(s, "mods") && strcmp(s, "all"))) s = "none";
    char keep[16];
    snprintf(keep, sizeof(keep), "%s", s);
    if (iso) cJSON_ReplaceItemInObjectCaseSensitive(data, "isolation", cJSON_CreateString(keep));
    else cJSON_AddStringToObject(data, "isolation", keep);
    return data;
}

static int set_mod_enabled(const char *instance, const char *filename, int enabled) {
    if (!filename || !filename[0]) { pymcl_set_error("缺少文件名"); return -1; }
    char dir[PYMCL_PATH], src[PYMCL_PATH], dst[PYMCL_PATH];
    char ip[PYMCL_PATH];
    instance_path(instance, ip, sizeof(ip));
    pymcl_path_join(dir, sizeof(dir), ip, "mods");
    pymcl_ensure_dir(dir);

    char name[512];
    snprintf(name, sizeof(name), "%s", filename);
    size_t len = strlen(name);
    int is_dis = (len > 9 && pymcl_endswith(name, ".disabled"));
    if (enabled) {
        if (!is_dis) return 0;
        name[len - 9] = 0;
        pymcl_path_join(src, sizeof(src), dir, filename);
        pymcl_path_join(dst, sizeof(dst), dir, name);
    } else {
        if (is_dis) return 0;
        pymcl_path_join(src, sizeof(src), dir, filename);
        snprintf(name, sizeof(name), "%s.disabled", filename);
        pymcl_path_join(dst, sizeof(dst), dir, name);
    }
    if (!pymcl_file_exists(src)) { pymcl_set_error("模组不存在: %s", filename); return -1; }
    if (MoveFileExA(src, dst, MOVEFILE_REPLACE_EXISTING) == 0) {
        pymcl_set_error("重命名失败");
        return -1;
    }
    return 0;
}

/* 同 Python 的 _is_offline_account：「离线模式」原文 / 译文 / 空串都算离线 */
static int is_offline_account_str(const char *a) {
    return !a || !a[0] || strcmp(a, "离线模式") == 0 || strcmp(a, tr("离线模式")) == 0;
}
/* 按名字找账号，找到返回拷贝 */
static cJSON *accounts_find_name(const char *name) {
    cJSON *root = accounts_load();
    cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItem(root, "accounts")) {
        const char *n = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
        if (n && strcmp(n, name) == 0) {
            cJSON *d = cJSON_Duplicate(it, 1);
            cJSON_Delete(root);
            return d;
        }
    }
    cJSON_Delete(root);
    return NULL;
}
/* 账号参数解析（build_launch_command 用）：离线或指定账号，账号不存在要报错 */
static cJSON *resolve_launch_account(const char *account, const char *user, const char *errkey) {
    if (is_offline_account_str(account)) return account_offline(user);
    cJSON *acc = accounts_find_name(account);
    if (!acc) {
        char msg[512];
        tr_fmt0(msg, sizeof(msg), errkey, account);
        pymcl_set_error("%s", msg);
        return NULL;
    }
    cJSON *v = account_ensure_valid(acc);
    cJSON_Delete(acc);
    return v;   /* 刷新失败时 v 为 NULL，错误信息已由 ensure_valid 设置 */
}
/* version_settings 的 auth_server 注入 launch_props（bridge/api.py build_launch_command） */
static void inject_auth_server(cJSON *props, const char *inst, const char *ver) {
    cJSON *vs = version_settings_load(inst, ver);
    char asrv[512];
    snprintf(asrv, sizeof(asrv), "%s",
             cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "auth_server")) ?: "");
    cJSON_Delete(vs);
    char *s = asrv;
    while (*s && isspace((unsigned char)*s)) s++;
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    if (!s[0]) return;
    const char *cur = cJSON_GetStringValue(cJSON_GetObjectItem(props, "authlib_api")) ?: "";
    if (!cur[0]) cJSON_AddStringToObject(props, "authlib_api", s);
}
/* launch_flow.prepare：隔离目录 + 全局模组 + 服务器 / 全屏参数 + GC 预设 */
static void launch_prepare(const char *inst, const char *ver, int mem_param,
                           char *gdir, size_t gn, int *mem_out,
                           char ***ega, int *n_ega, char ***ejv, int *n_ejv) {
    cJSON *vs = version_settings_load(inst, ver);
    version_apply_isolation(inst, ver, vs);
    version_game_dir(inst, ver, vs, gdir, gn);
    char mods[PYMCL_PATH];
    pymcl_path_join(mods, sizeof(mods), gdir, "mods");
    global_mods_apply(mods);
    int base = mem_param;
    if (!base) {
        cJSON *cm = config_get("memory_mb");
        base = cJSON_IsNumber(cm) ? (int)cm->valuedouble : 0;
        if (!base) base = 4096;
    }
    cJSON *sm = cJSON_GetObjectItemCaseSensitive(vs, "memory_mb");
    *mem_out = (sm && cJSON_IsNumber(sm) && sm->valuedouble != 0) ? (int)sm->valuedouble : base;
    /* 额外游戏参数：game_args 拆分 + 服务器直连 + 全屏 */
    char **ex = NULL;
    int nex = 0;
    {
        char **parts = NULL;
        int np = 0;
        pymcl_split_args(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "game_args")) ?: "", &parts, &np);
        for (int i = 0; i < np; i++) if (parts[i] && parts[i][0]) {
            ex = (char **)realloc(ex, sizeof(char *) * (size_t)(nex + 1));
            ex[nex++] = parts[i];
        } else free(parts[i]);
        free(parts);
    }
    const char *srv = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "server")) ?: "";
    if (srv[0]) {
        int has_server = 0;
        for (int i = 0; i < nex && !has_server; i++) has_server = strcmp(ex[i], "--server") == 0;
        if (!has_server) {
            char port[32];
            snprintf(port, sizeof(port), "%s",
                     cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "port")) ?: "");
            const char *pp = port[0] ? port : "25565";
            ex = (char **)realloc(ex, sizeof(char *) * (size_t)(nex + 4));
            ex[nex++] = pymcl_strdup("--server");
            ex[nex++] = pymcl_strdup(srv);
            ex[nex++] = pymcl_strdup("--port");
            ex[nex++] = pymcl_strdup(pp);
        }
    }
    char wm[32];
    snprintf(wm, sizeof(wm), "%s",
             cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "window_mode")) ?: "");
    if (!wm[0]) snprintf(wm, sizeof(wm), "%s", config_str("window_mode", "window"));
    if (!wm[0]) snprintf(wm, sizeof(wm), "window");
    if (!strcmp(wm, "maximize") || !strcmp(wm, "fullscreen")) {
        int has_fs = 0;
        for (int i = 0; i < nex && !has_fs; i++) has_fs = strcmp(ex[i], "--fullscreen") == 0;
        if (!has_fs) {
            ex = (char **)realloc(ex, sizeof(char *) * (size_t)(nex + 1));
            ex[nex++] = pymcl_strdup("--fullscreen");
        }
    }
    *ega = ex;
    *n_ega = nex;
    /* 额外 JVM 参数：GC 预设接到版本 jvm_args 前面（gc.apply） */
    char preset[32];
    snprintf(preset, sizeof(preset), "%s",
             cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "gc")) ?: "");
    if (!preset[0]) snprintf(preset, sizeof(preset), "%s", config_str("gc_preset", "auto"));
    if (!preset[0]) snprintf(preset, sizeof(preset), "auto");
    char existing[2048];
    snprintf(existing, sizeof(existing), "%s",
             cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(vs, "jvm_args")) ?: "");
    static const char *const GC_FLAGS[] = {
        "-XX:+UseG1GC", "-XX:+UseZGC", "-XX:+UseShenandoahGC",
        "-XX:+UseParallelGC", "-XX:+UseConcMarkSweepGC", "-XX:+UseSerialGC",
    };
    static const char *const GC_ARGS[] = {
        /* auto */ "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M",
        /* g1 */ "-XX:+UseG1GC",
        /* g1_tuned */ "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:+ParallelRefProcEnabled",
        /* zgc */ "-XX:+UseZGC -XX:+UnlockExperimentalVMOptions",
        /* none */ "",
    };
    char *pl = preset;
    while (*pl && isspace((unsigned char)*pl)) pl++;
    size_t plen = strlen(pl);
    while (plen && isspace((unsigned char)pl[plen - 1])) pl[--plen] = 0;
    for (char *q = pl; *q; q++) *q = (char)tolower((unsigned char)*q);
    const char *extra_gc = GC_ARGS[0];
    if (!strcmp(pl, "g1")) extra_gc = GC_ARGS[1];
    else if (!strcmp(pl, "g1_tuned")) extra_gc = GC_ARGS[2];
    else if (!strcmp(pl, "zgc")) extra_gc = GC_ARGS[3];
    else if (!strcmp(pl, "none")) extra_gc = GC_ARGS[4];
    int has_gc = 0;
    {
        char **bits = NULL;
        int nb = 0;
        pymcl_split_args(existing, &bits, &nb);
        for (int i = 0; i < nb && !has_gc; i++) {
            int in_flags = 0;
            for (size_t f = 0; f < sizeof(GC_FLAGS) / sizeof(GC_FLAGS[0]); f++)
                if (strcmp(bits[i], GC_FLAGS[f]) == 0) in_flags = 1;
            if (in_flags || (pymcl_startswith(bits[i], "-XX:+Use") && strstr(bits[i], "GC"))) has_gc = 1;
            free(bits[i]);
        }
        free(bits);
    }
    char combined[4096];
    if (has_gc) snprintf(combined, sizeof(combined), "%s", existing);
    else if (!extra_gc[0]) snprintf(combined, sizeof(combined), "%s", existing);
    else if (!existing[0]) snprintf(combined, sizeof(combined), "%s", extra_gc);
    else snprintf(combined, sizeof(combined), "%s %s", extra_gc, existing);
    char *tail = combined;
    while (*tail && isspace((unsigned char)*tail)) tail++;
    size_t clen = strlen(tail);
    while (clen && isspace((unsigned char)tail[clen - 1])) tail[--clen] = 0;
    *ejv = NULL;
    *n_ejv = 0;
    pymcl_split_args(tail, ejv, n_ejv);
    cJSON_Delete(vs);
}

/* Prefer native; on failure or complexity, Python.
   *handled 只在末尾「这里没有这个方法」时为 0：原生分支失败返回 NULL 也算处理过，
   不能再让 backend_call 往下落到 Python 回落，把真正的错误盖成 unknown method。 */
cJSON *rpc_align_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    int dummy;
    if (!handled) handled = &dummy;
    *handled = 1;
    if (!method) { *handled = 0; return NULL; }

    /* ---- accounts ---- */
    if (strcmp(method, "get_account_rows") == 0) {
        cJSON *root = accounts_load();
        cJSON *out = cJSON_CreateArray();
        const char *active = cJSON_GetStringValue(cJSON_GetObjectItem(root, "active"));
        cJSON *it;
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(root, "accounts")) {
            cJSON *row = cJSON_CreateObject();
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name")) ?: "";
            cJSON_AddStringToObject(row, "name", nm);
            cJSON_AddStringToObject(row, "type", cJSON_GetStringValue(cJSON_GetObjectItem(it, "type")) ?: "offline");
            cJSON_AddStringToObject(row, "uuid", cJSON_GetStringValue(cJSON_GetObjectItem(it, "uuid")) ?: "");
            cJSON_AddStringToObject(row, "api", cJSON_GetStringValue(cJSON_GetObjectItem(it, "api")) ?: "");
            cJSON_AddStringToObject(row, "avatar", "");
            cJSON_AddStringToObject(row, "body", "");
            cJSON_AddBoolToObject(row, "active", active && strcmp(active, nm) == 0);
            cJSON_AddItemToArray(out, row);
        }
        cJSON_Delete(root);
        return out;
    }
    if (strcmp(method, "add_offline_account") == 0) {
        const char *user = pstr(params, "username", pstr(params, "name", "Player"));
        const char *skin = pstr(params, "skin", "");
        cJSON *acc = account_offline_skin(user, skin);
        cJSON *root = accounts_load();
        cJSON *arr = cJSON_GetObjectItem(root, "accounts");
        if (!cJSON_IsArray(arr)) {
            arr = cJSON_CreateArray();
            cJSON_AddItemToObject(root, "accounts", arr);
        }
        cJSON_AddItemToArray(arr, cJSON_Duplicate(acc, 1));
        cJSON_ReplaceItemInObject(root, "active", cJSON_CreateString(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"))));
        accounts_save(root);
        cJSON_Delete(root);
        if (emit) emit("ui_changed", cJSON_CreateObject());
        cJSON *name = cJSON_CreateString(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")));
        cJSON_Delete(acc);
        return name;
    }
    if (strcmp(method, "remove_account") == 0) {
        const char *name = pstr(params, "name", "");
        cJSON *root = accounts_load();
        cJSON *arr = cJSON_GetObjectItem(root, "accounts");
        cJSON *next = cJSON_CreateArray();
        cJSON *it;
        cJSON_ArrayForEach(it, arr) {
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
            if (nm && strcmp(nm, name) == 0) continue;
            cJSON_AddItemToArray(next, cJSON_Duplicate(it, 1));
        }
        cJSON_ReplaceItemInObject(root, "accounts", next);
        const char *active = cJSON_GetStringValue(cJSON_GetObjectItem(root, "active"));
        if (active && strcmp(active, name) == 0)
            cJSON_ReplaceItemInObject(root, "active", cJSON_CreateNull());
        accounts_save(root);
        cJSON_Delete(root);
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "set_active_account") == 0) {
        const char *name = pstr(params, "name", "");
        cJSON *root = accounts_load();
        cJSON_ReplaceItemInObject(root, "active", cJSON_CreateString(name));
        accounts_save(root);
        cJSON_Delete(root);
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateString(name);
    }
    if (strcmp(method, "authlib_presets") == 0) {
        cJSON *out = cJSON_CreateArray();
        cJSON *a = cJSON_CreateObject();
        cJSON_AddStringToObject(a, "name", "Little Skin");
        cJSON_AddStringToObject(a, "api", "https://littleskin.cn/api/yggdrasil");
        cJSON_AddItemToArray(out, a);
        cJSON *b = cJSON_CreateObject();
        cJSON_AddStringToObject(b, "name", "Blessing Skin（自填）");
        cJSON_AddStringToObject(b, "api", "");
        cJSON_AddItemToArray(out, b);
        return out;
    }

    /* ---- mods ---- */
    if (strcmp(method, "enable_mod") == 0) {
        if (set_mod_enabled(pstr(params, "instance", "default"), pstr(params, "filename", ""), 1) != 0)
            return NULL;
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateString(pstr(params, "filename", ""));
    }
    if (strcmp(method, "disable_mod") == 0) {
        if (set_mod_enabled(pstr(params, "instance", "default"), pstr(params, "filename", ""), 0) != 0)
            return NULL;
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateString(pstr(params, "filename", ""));
    }
    if (strcmp(method, "open_global_mods") == 0) {
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), g_root, "global_mods");
        pymcl_ensure_dir(p);
        pymcl_open_folder(p);
        return cJSON_CreateTrue();
    }

    /* ---- playtime ---- */
    if (strcmp(method, "clear_playtime") == 0) {
        const char *inst = pstr(params, "instance", "");
        char path[PYMCL_PATH];
        playtime_path(path, sizeof(path));
        if (!inst[0]) {
            cJSON *empty = cJSON_Parse("{\"instances\":{}}");
            pymcl_write_json(path, empty);
            cJSON_Delete(empty);
        } else {
            cJSON *j = pymcl_read_json(path);
            if (!j) j = cJSON_Parse("{\"instances\":{}}");
            cJSON *insts = cJSON_GetObjectItem(j, "instances");
            if (cJSON_IsObject(insts)) cJSON_DeleteItemFromObject(insts, inst);
            pymcl_write_json(path, j);
            cJSON_Delete(j);
        }
        return cJSON_CreateTrue();
    }

    /* ---- version settings ---- */
    if (strcmp(method, "get_version_settings") == 0) {
        char ip[PYMCL_PATH];
        const char *inst = pstr(params, "instance", "");
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        return version_settings_load(inst, pstr(params, "version", ""));
    }
    if (strcmp(method, "save_version_settings") == 0) {
        const char *inst = pstr(params, "instance", "default");
        const char *ver = pstr(params, "version", "");
        cJSON *data = cJSON_GetObjectItem(params, "data");
        if (!cJSON_IsObject(data)) data = params;
        char path[PYMCL_PATH], parent[PYMCL_PATH];
        version_settings_path(inst, ver, path, sizeof(path));
        pymcl_parent(path, parent, sizeof(parent));
        pymcl_ensure_dir(parent);
        cJSON *cur = vs_defaults();
        cJSON *stored = pymcl_read_json(path);
        if (cJSON_IsObject(stored)) {
            cJSON *it = stored->child;
            while (it) {
                cJSON *n = it->next;
                cJSON_DeleteItemFromObject(cur, it->string);
                cJSON_AddItemToObject(cur, it->string, cJSON_Duplicate(it, 1));
                it = n;
            }
        }
        cJSON_Delete(stored);
        if (cJSON_IsObject(data)) {
            cJSON *it = data->child;
            while (it) {
                cJSON *n = it->next;
                if (it->string && strcmp(it->string, "instance") && strcmp(it->string, "version")
                    && strcmp(it->string, "data")) {
                    cJSON_DeleteItemFromObject(cur, it->string);
                    cJSON_AddItemToObject(cur, it->string, cJSON_Duplicate(it, 1));
                }
                it = n;
            }
        }
        pymcl_write_json(path, cur);
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return cur;
    }

    /* ---- 启动命令（docs/GOAL-c-bridge-no-python.md M1） ---- */
    if (strcmp(method, "build_launch_command") == 0) {
        const char *inst = pstr(params, "instance", "default");
        const char *ver = pstr(params, "version", "");
        const char *account = pstr(params, "account", "");
        const char *user = pstr(params, "username", "");
        int mem = pint(params, "memory_mb", 4096);
        int w = pint(params, "width", 0);
        int h = pint(params, "height", 0);
        const char *java = pstr(params, "java", PYMCL_JAVA_AUTO);
        if (!ver[0]) { pymcl_set_error("%s", tr("请先选择版本")); return NULL; }
        cJSON *acc = resolve_launch_account(account, user, "账号不存在: {0}");
        if (!acc) return NULL;
        cJSON *props = account_launch_props(acc);
        cJSON_Delete(acc);
        inject_auth_server(props, inst, ver);
        const char *jex = (!java[0] || strcmp(java, PYMCL_JAVA_AUTO) == 0) ? PYMCL_JAVA_AUTO : java;
        char **cmdv = NULL;
        int cmdc = 0;
        int rc = build_launch_command(inst, ver, props, jex, mem, w, h, &cmdv, &cmdc, NULL, 0);
        cJSON_Delete(props);
        if (rc != 0) return NULL;
        cJSON *arr = cJSON_CreateArray();
        for (int i = 0; i < cmdc; i++) cJSON_AddItemToArray(arr, cJSON_CreateString(cmdv[i]));
        for (int i = 0; i < cmdc; i++) free(cmdv[i]);
        free(cmdv);
        return arr;
    }

    if (strcmp(method, "get_launch_command") == 0) {
        const char *inst = pstr(params, "instance", "default");
        const char *ver = pstr(params, "version", "");
        const char *account = pstr(params, "account", "");
        const char *user = pstr(params, "username", "");
        int mem = pint(params, "memory_mb", 0);
        if (!ver[0]) { pymcl_set_error("%s", tr("请先选择版本")); return NULL; }
        cJSON *vjson = instance_version_json(inst, ver);
        if (!vjson) { pymcl_set_error("版本 %s 未安装，请先安装。", ver); return NULL; }
        cJSON *resolved = manifest_resolve_inherits(vjson, load_parent_ud, (void *)inst);
        cJSON *use = resolved ? resolved : vjson;
        char *jexe = java_resolve_launch(use, NULL, NULL);
        if (!jexe) {
            cJSON_Delete(resolved);
            cJSON_Delete(vjson);
            pymcl_set_error("%s", tr("无法确定 Java 路径"));
            return NULL;
        }
        /* 账号：空取活动账号，缺了就离线；指定但不存在也回退离线（同 bridge/api.py） */
        cJSON *acc = NULL;
        if (!account[0]) {
            cJSON *root = accounts_load();
            const char *act = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root, "active")) ?: "";
            if (act[0]) acc = accounts_find_name(act);
            cJSON_Delete(root);
            if (!acc) acc = account_offline(user);
        } else {
            acc = accounts_find_name(account);
            if (acc) {
                cJSON *v = account_ensure_valid(acc);
                cJSON_Delete(acc);
                acc = v;
            }
            if (!acc) acc = account_offline(user);
        }
        cJSON *props = account_launch_props(acc);
        cJSON_Delete(acc);
        char gdir[PYMCL_PATH];
        int prepmem = 0;
        char **ega = NULL, **ejv = NULL;
        int n_ega = 0, n_ejv = 0;
        launch_prepare(inst, ver, mem, gdir, sizeof(gdir), &prepmem, &ega, &n_ega, &ejv, &n_ejv);
        char **cmdv = NULL;
        int cmdc = 0;
        int rc = build_launch_command_ex(inst, ver, props, jexe, prepmem, 0, 0,
                                         gdir, ega, n_ega, ejv, n_ejv,
                                         &cmdv, &cmdc, NULL, 0);
        for (int i = 0; i < n_ega; i++) free(ega[i]);
        free(ega);
        for (int i = 0; i < n_ejv; i++) free(ejv[i]);
        free(ejv);
        cJSON_Delete(props);
        free(jexe);
        cJSON_Delete(resolved);
        if (vjson != use) cJSON_Delete(vjson);
        if (rc != 0) return NULL;
        /* Python 端 " ".join(cmd)：命令拼成一行文本返回 */
        size_t cap = 1;
        for (int i = 0; i < cmdc; i++) cap += strlen(cmdv[i]) + 1;
        char *joined = (char *)malloc(cap);
        joined[0] = 0;
        size_t off = 0;
        for (int i = 0; i < cmdc; i++) {
            if (i) joined[off++] = ' ';
            size_t L = strlen(cmdv[i]);
            memcpy(joined + off, cmdv[i], L);
            off += L;
        }
        joined[off] = 0;
        for (int i = 0; i < cmdc; i++) free(cmdv[i]);
        free(cmdv);
        cJSON *out = cJSON_CreateString(joined);
        free(joined);
        return out;
    }

    /* ---- preflight / crash (python preferred, safe stub fallback) ---- */
    if (strcmp(method, "preflight_launch") == 0) {
        cJSON *r = py_rpc_call(method, params);
        if (r) return r;
        /* C-only: basic existence check */
        const char *inst = pstr(params, "instance", "default");
        const char *ver = pstr(params, "version", "");
        cJSON *out = cJSON_CreateObject();
        cJSON *issues = cJSON_CreateArray();
        if (!ver[0]) {
            cJSON *iss = cJSON_CreateObject();
            cJSON_AddStringToObject(iss, "level", "error");
            cJSON_AddStringToObject(iss, "code", "no_version");
            cJSON_AddStringToObject(iss, "message", "请先选择版本");
            cJSON_AddItemToArray(issues, iss);
        } else if (!instance_has_version(inst, ver)) {
            cJSON *iss = cJSON_CreateObject();
            cJSON_AddStringToObject(iss, "level", "error");
            cJSON_AddStringToObject(iss, "code", "missing_version");
            cJSON_AddStringToObject(iss, "message", "版本未安装");
            cJSON_AddItemToArray(issues, iss);
        }
        cJSON_AddItemToObject(out, "issues", issues);
        cJSON_AddBoolToObject(out, "ok", cJSON_GetArraySize(issues) == 0);
        cJSON_AddBoolToObject(out, "can_launch", cJSON_GetArraySize(issues) == 0);
        return out;
    }
    if (strcmp(method, "apply_crash_action") == 0) {
        cJSON *r = py_rpc_call(method, params);
        if (r) return r;
        cJSON *action = cJSON_GetObjectItem(params, "action");
        const char *aid = pstr(action, "id", "");
        if (strcmp(aid, "open_mods_folder") == 0 || strcmp(aid, "open_crash_file") == 0) {
            const char *inst = pstr(action, "instance", "default");
            char ip[PYMCL_PATH], mods[PYMCL_PATH];
            instance_path(inst, ip, sizeof(ip));
            pymcl_path_join(mods, sizeof(mods), ip, "mods");
            pymcl_ensure_dir(mods);
            pymcl_open_folder(mods);
            cJSON *o = cJSON_CreateObject();
            cJSON_AddBoolToObject(o, "ok", 1);
            cJSON_AddStringToObject(o, "message", "已打开目录");
            return o;
        }
        cJSON *o = cJSON_CreateObject();
        cJSON_AddBoolToObject(o, "ok", 0);
        cJSON_AddStringToObject(o, "message", "需要 Python 桥完成此修复动作");
        return o;
    }

    /* ---- 尚未原生实现、仍转给 Python 的方法（去 Python 化进行中，见 docs/GOAL-c-bridge-no-python.md） ---- */
    if (strcmp(method, "submit_feedback") == 0
        || strcmp(method, "ai_send") == 0
        || strcmp(method, "ai_stop") == 0
        || strcmp(method, "ai_confirm") == 0
        || strcmp(method, "ai_answer") == 0
        || strcmp(method, "list_catalog_files") == 0
        || strcmp(method, "search_worlds") == 0
        || strcmp(method, "install_world") == 0
        || strcmp(method, "repair_version") == 0
        || strcmp(method, "export_modpack") == 0
        || strcmp(method, "start_authlib_login") == 0
        || strcmp(method, "start_nide8_login") == 0
        || strcmp(method, "start_self_update") == 0
        || strcmp(method, "start_mod_updates") == 0) {
        cJSON *r = py_rpc_call(method, params);
        if (r) return r;
        pymcl_set_error("方法 %s 需要 Python 桥（设置 PYMCL_PYTHON）", method);
        return NULL;
    }

    *handled = 0;
    return NULL; /* not handled here */
}
