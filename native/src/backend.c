#include "pymcl.h"
#include <pthread.h>
#include <string.h>
#include <time.h>

/* terracotta.c（M4 陶瓦联机） */
cJSON *rpc_terracotta_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled);
int terracotta_prepare_run(pymcl_ctx *ctx, char *msg, size_t n);

static sse_emit_fn g_emit;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_task_n;
static HANDLE g_game;
static char g_launch_id[32];

typedef struct {
    char id[32];
    char title[256];
    int cancelled;
    pthread_t th;
    char method[64];
    cJSON *args;
} task_t;

static task_t *g_tasks[32];
static int g_ntasks;
static cJSON *g_last_crash;
/* 与 bridge/api.py 的 _titles / _task_results 对应：标题一直留着，结果超过 80 条裁到最近 40 条 */
static cJSON *g_titles;
static cJSON *g_results;

#define CRASH_TAIL 200

/* P2-6：g_last_crash 的写入口（定义在 analyze_game_crash 之后，这里先声明）。 */
static void crash_store(cJSON *rep);

/* 开发后端的 Python 回落（GOAL 明确它仍是参考实现）。nopy 构建把整段编掉：
   find_python 与下面两处调用点都在 #ifndef PYMCL_NO_PY 里，产物中没有对应符号。 */
#ifndef PYMCL_NO_PY
static int find_python(char *out, size_t n) {
    const char *env = getenv("PYMCL_PYTHON");
    if (env && env[0] && GetFileAttributesA(env) != INVALID_FILE_ATTRIBUTES) {
        snprintf(out, n, "%s", env);
        return 0;
    }
    {
        const char *known = "C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\envs\\pymcl5\\Scripts\\python.exe";
        if (GetFileAttributesA(known) != INVALID_FILE_ATTRIBUTES) {
            snprintf(out, n, "%s", known);
            return 0;
        }
    }
    snprintf(out, n, "python");
    return 0;
}
#endif

static cJSON *analyze_game_crash(const char *inst, const char *ver, long code,
                                 char **tail, int tn, int ts, double started) {
#ifdef PYMCL_NO_PY
    (void)inst; (void)ver; (void)code; (void)tail; (void)tn; (void)ts; (void)started;
    return NULL;
#else
    char py[PYMCL_PATH], outf[PYMCL_PATH], jsonf[PYMCL_PATH], codebuf[32], startbuf[32];
    find_python(py, sizeof(py));
    snprintf(outf, sizeof(outf), "%s\\game-output-tail.txt", g_root);
    snprintf(jsonf, sizeof(jsonf), "%s\\last-crash.json", g_root);
    FILE *f = fopen(outf, "wb");
    if (f) {
        int start = (tn == CRASH_TAIL) ? ts : 0;
        for (int i = 0; i < tn; i++) {
            const char *s = tail[(start + i) % CRASH_TAIL];
            if (s) { fputs(s, f); fputc('\n', f); }
        }
        fclose(f);
    }
    snprintf(codebuf, sizeof(codebuf), "%ld", code);
    snprintf(startbuf, sizeof(startbuf), "%.0f", started);
    const char *argv[20];
    int argc = 0;
    argv[argc++] = py;
    argv[argc++] = "-u";
    argv[argc++] = "-m";
    argv[argc++] = "mclauncher.crash";
    argv[argc++] = "--instance";
    argv[argc++] = inst;
    argv[argc++] = "--version";
    argv[argc++] = ver ? ver : "";
    argv[argc++] = "--exit-code";
    argv[argc++] = codebuf;
    argv[argc++] = "--output";
    argv[argc++] = outf;
    argv[argc++] = "--json-out";
    argv[argc++] = jsonf;
    argv[argc++] = "--started-at";
    argv[argc++] = startbuf;
    pymcl_run_process(argv, argc, g_root, NULL, NULL, 45);
    cJSON *rep = pymcl_read_json(jsonf);
    if (rep) crash_store(rep);
    return rep;
#endif
}

/* P2-6：g_last_crash 的写入点。旧版这里是裸的两行（task 线程）：
       if (g_last_crash) cJSON_Delete(g_last_crash);
       g_last_crash = cJSON_Duplicate(rep, 1);
   而 client 线程会在 get_crash / backend_last_crash / open_crash_file 里读同一个
   指针 → 删除与复制之间被读 = use-after-free。现在写读都在 g_mu 下。
   抽成独立函数是为了让 tests/crash_race_harness.c 能直接并发压它。 */
static void crash_store(cJSON *rep) {
    cJSON *dup = rep ? cJSON_Duplicate(rep, 1) : NULL;
    pthread_mutex_lock(&g_mu);
    if (g_last_crash) cJSON_Delete(g_last_crash);
    g_last_crash = dup;
    pthread_mutex_unlock(&g_mu);
}

static void emit(const char *ev, cJSON *data) {
    if (g_emit) g_emit(ev, data);
}

/* AI 回合线程等后台使用者：事件与任务进度走同一条 SSE 通道。 */
void backend_emit(const char *ev, cJSON *data) { emit(ev, data); }

static void emit_kv(const char *ev, const char *fmt, ...) {
    /* unused helper kept for future */
    (void)ev; (void)fmt;
}

static int task_count(void) {
    pthread_mutex_lock(&g_mu);
    int n = g_ntasks;
    pthread_mutex_unlock(&g_mu);
    return n;
}

static void emit_count(void) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "count", task_count());
    emit("task_count_changed", o);
    cJSON_Delete(o);
}

static void ctx_progress(void *ud, const char *msg, long long done, long long total) {
    task_t *t = (task_t *)ud;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "task_id", t->id);
    cJSON_AddNumberToObject(o, "current", (double)done);
    cJSON_AddNumberToObject(o, "total", (double)total);
    cJSON_AddStringToObject(o, "message", msg ? msg : "");
    emit("progress", o);
    cJSON_Delete(o);
}
static void ctx_log(void *ud, const char *text) {
    task_t *t = (task_t *)ud;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "task_id", t->id);
    cJSON_AddStringToObject(o, "text", text ? text : "");
    emit("log", o);
    cJSON_Delete(o);
}
static int ctx_cancel(void *ud) {
    task_t *t = (task_t *)ud;
    return t->cancelled;
}

static void finish_task(task_t *t, int ok, const char *msg) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "task_id", t->id);
    cJSON_AddBoolToObject(o, "success", ok);
    cJSON_AddStringToObject(o, "message", msg ? msg : (ok ? "任务完成" : pymcl_error()));
    emit("finished", o);
    pthread_mutex_lock(&g_mu);
    if (!g_results) g_results = cJSON_CreateArray();
    {
        cJSON *r = cJSON_CreateObject();
        cJSON_AddStringToObject(r, "task_id", t->id);
        cJSON_AddBoolToObject(r, "success", ok);
        cJSON_AddStringToObject(r, "message", cJSON_GetStringValue(cJSON_GetObjectItem(o, "message")));
        cJSON_AddItemToArray(g_results, r);
        if (cJSON_GetArraySize(g_results) > 80)
            while (cJSON_GetArraySize(g_results) > 40) cJSON_DeleteItemFromArray(g_results, 0);
    }
    pthread_mutex_unlock(&g_mu);
    cJSON_Delete(o);
    if (ok) emit("ui_changed", cJSON_CreateObject());
    pthread_mutex_lock(&g_mu);
    for (int i = 0; i < g_ntasks; i++) {
        if (g_tasks[i] == t) {
            g_tasks[i] = g_tasks[g_ntasks - 1];
            g_tasks[g_ntasks - 1] = NULL;
            g_ntasks--;
            break;
        }
    }
    pthread_mutex_unlock(&g_mu);
    emit_count();
    cJSON_Delete(t->args);
    t->args = NULL;
    free(t);
}

static const char *pstr(cJSON *a, const char *k, const char *def) {
    const char *s = a ? cJSON_GetStringValue(cJSON_GetObjectItem(a, k)) : NULL;
    return s ? s : def;
}
static int pint(cJSON *a, const char *k, int def) {
    cJSON *v = a ? cJSON_GetObjectItem(a, k) : NULL;
    if (cJSON_IsNumber(v)) return (int)v->valuedouble;
    if (cJSON_IsString(v) && v->valuestring) return atoi(v->valuestring);
    return def;
}
/* save_settings 用：Python 的 (value or "").strip()，NULL 与空串都返回 "" */
static const char *trim_str_or(const char *s, const char *def) {
    static _Thread_local char buf[512];
    if (!s) return def;
    snprintf(buf, sizeof(buf), "%s", s);
    char *p = buf;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    size_t n = strlen(p);
    while (n && (p[n - 1] == ' ' || p[n - 1] == '\t' || p[n - 1] == '\r' || p[n - 1] == '\n')) p[--n] = 0;
    if (!p[0]) return def;
    return p;
}

static void on_login_code(void *ud, const char *code, const char *uri) {
    (void)ud;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "code", code ? code : "");
    cJSON_AddStringToObject(o, "uri", uri ? uri : "");
    emit("login_code", o);
    cJSON_Delete(o);
    cJSON *st = cJSON_CreateObject();
    cJSON_AddStringToObject(st, "text", "请在浏览器完成授权");
    emit("login_status", st);
    cJSON_Delete(st);
}

static void ctx_event(void *ud, const char *ev, cJSON *data) {
    (void)ud;
    emit(ev, data);
}

static void *task_run(void *p) {
    task_t *t = (task_t *)p;
    pymcl_ctx ctx = { ctx_progress, ctx_log, ctx_cancel, t, config_int("download_threads", 8), ctx_event, NULL };
    int ok = 0;
    char msg[256] = {0};
    if (strcmp(t->method, "install_game") == 0) {
        const char *ver = pstr(t->args, "version", "");
        const char *loader = pstr(t->args, "loader", "无");
        const char *lv = pstr(t->args, "loader_version", "");
        const char *inst = pstr(t->args, "instance", config_str("default_instance", "default"));
        ctx_log(t, "安装到实例");
        if (loader && loader[0] && strcmp(loader, "无") != 0) {
            char vid[256];
            ok = install_loader(inst, loader, lv[0] ? lv : NULL, ver, &ctx, vid, sizeof(vid)) == 0;
            if (ok) snprintf(msg, sizeof(msg), "加载器安装完成: %s", vid);
        } else {
            ok = install_version(inst, ver, &ctx) == 0;
            if (ok) snprintf(msg, sizeof(msg), "版本 %s 安装完成", ver);
        }
    } else if (strcmp(t->method, "download_java") == 0) {
        int maj = pint(t->args, "major", 17);
        char *exe = java_install_adoptium(maj, NULL, &ctx);
        ok = exe != NULL;
        if (ok) snprintf(msg, sizeof(msg), "Java %d 就绪: %s", maj, exe);
        free(exe);
    } else if (strcmp(t->method, "install_mod") == 0) {
        const char *name = pstr(t->args, "name", "");
        const char *inst = pstr(t->args, "instance", "default");
        cJSON *extra = cJSON_GetObjectItem(t->args, "extra");
        ok = install_mod(inst, name, extra, &ctx) == 0;
        if (ok) snprintf(msg, sizeof(msg), "模组安装完成");
    } else if (strcmp(t->method, "install_modpack") == 0) {
        ok = install_modpack(pstr(t->args, "name", ""), pstr(t->args, "source", "Modrinth"),
                             cJSON_GetObjectItem(t->args, "extra"), &ctx) == 0;
        if (ok) snprintf(msg, sizeof(msg), "整合包安装完成");
    } else if (strcmp(t->method, "install_shader") == 0 ||
               strcmp(t->method, "install_resourcepack") == 0 ||
               strcmp(t->method, "install_datapack") == 0) {
        const char *kind = strstr(t->method, "shader") ? "shader" :
            strstr(t->method, "resource") ? "resourcepack" : "datapack";
        ok = install_content(kind, pstr(t->args, "instance", "default"),
                             pstr(t->args, "name", ""), cJSON_GetObjectItem(t->args, "extra"), &ctx) == 0;
        if (ok) snprintf(msg, sizeof(msg), "完成");
    } else if (strcmp(t->method, "install_world") == 0) {
        /* 世界装进 saves（开了存档隔离的版本进 versions/<id>/saves）。
           完成文案由 install_world 回填，对齐 Python 的「已安装世界 {0}」。 */
        ok = install_world(pstr(t->args, "instance", "default"),
                           pstr(t->args, "name", ""), cJSON_GetObjectItem(t->args, "extra"),
                           &ctx, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "launch_game") == 0) {
        const char *inst = pstr(t->args, "instance", "default");
        const char *ver = pstr(t->args, "version", "");
        const char *account = pstr(t->args, "account", "离线模式");
        const char *user = pstr(t->args, "username", "Player");
        int mem = pint(t->args, "memory_mb", 4096);
        int w = pint(t->args, "width", 854);
        int h = pint(t->args, "height", 480);
        const char *java = pstr(t->args, "java", PYMCL_JAVA_AUTO);
        if (!ver[0]) { pymcl_set_error("请先选择版本"); }
        else {
            config_set_str("default_instance", inst);
            config_save();
            cJSON *acc = NULL;
            if (!account[0] || strcmp(account, "离线模式") == 0)
                acc = account_offline(user);
            else {
                cJSON *root = accounts_load();
                cJSON *it;
                cJSON_ArrayForEach(it, cJSON_GetObjectItem(root, "accounts")) {
                    if (strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(it, "name")) ?: "", account) == 0)
                        acc = cJSON_Duplicate(it, 1);
                }
                cJSON_Delete(root);
                if (acc) {
                    cJSON *v = account_ensure_valid(acc);
                    cJSON_Delete(acc);
                    acc = v;
                }
            }
            if (!acc && account[0] && strcmp(account, "离线模式") != 0)
                pymcl_set_error("账号不存在: %s", account);
            else {
                if (!acc) acc = account_offline(user);
                cJSON *props = account_launch_props(acc);
                cJSON *vj = instance_resolved_version(inst, ver);
                if (!vj) vj = instance_version_json(inst, ver);
                char jpbuf[PYMCL_PATH];
                const char *prefer;
                if (!java || pymcl_ieq(java, PYMCL_JAVA_AUTO)) {
                    instance_java_pref(inst, jpbuf, sizeof(jpbuf));
                    prefer = jpbuf;
                } else prefer = java;
                cJSON *jprobe = vj ? vj : cJSON_Parse("{}");
                char *jexe = java_resolve_launch(jprobe, prefer, &ctx);
                if (jprobe != vj) cJSON_Delete(jprobe);
                if (vj) cJSON_Delete(vj);
                char **argv = NULL; int argc = 0; char natives[PYMCL_PATH];
                char ip[PYMCL_PATH];
                instance_path(inst, ip, sizeof(ip));
                if (jexe && build_launch_command(inst, ver, props, jexe, mem, w, h, &argv, &argc, natives, sizeof(natives)) == 0) {
                    ctx_log(t, "正在启动游戏进程…");
                    HANDLE rd = NULL;
                    HANDLE proc = game_spawn((const char **)argv, argc, ip, &rd);
                    pthread_mutex_lock(&g_mu);
                    g_game = proc;
                    snprintf(g_launch_id, sizeof(g_launch_id), "%s", t->id);
                    pthread_mutex_unlock(&g_mu);
                    if (proc) {
                        /* bridge/api.py:2113 / :2136 —— game_started 无 payload（Python 发 {}），
                           game_exited 带 {"code": code}。WPF 启动页靠这两个事件更新状态行，
                           WinUI3 的 launcher_visibility（启动游戏时最小化/隐藏启动器）也订阅它们。
                           此前 C 桥一个都不发，默认后端下这两个功能全部失效。
                           发出时机与 Python 对齐：进程起来（拿到 handle）就 started，
                           等待结束、清掉 g_game 之后才 exited。 */
                        {
                            cJSON *gs = cJSON_CreateObject();
                            emit("game_started", gs);
                            cJSON_Delete(gs);
                        }
                        char buf[4096]; DWORD got;
                        char *tail[CRASH_TAIL];
                        int tn = 0, ts = 0;
                        memset(tail, 0, sizeof(tail));
                        double started = (double)time(NULL);
                        while (ReadFile(rd, buf, sizeof(buf) - 1, &got, NULL) && got) {
                            buf[got] = 0;
                            char *line = buf;
                            while (line && *line) {
                                char *nl = strchr(line, '\n');
                                if (nl) *nl = 0;
                                if (line[0] && line[0] != '\r') {
                                    ctx_log(t, line);
                                    if (tn < CRASH_TAIL) tail[tn++] = _strdup(line);
                                    else {
                                        free(tail[ts]);
                                        tail[ts] = _strdup(line);
                                        ts = (ts + 1) % CRASH_TAIL;
                                    }
                                }
                                line = nl ? nl + 1 : NULL;
                            }
                            if (t->cancelled) { game_kill(proc); break; }
                        }
                        WaitForSingleObject(proc, INFINITE);
                        DWORD code = 0;
                        GetExitCodeProcess(proc, &code);
                        /* P2-6（同族）：先把 g_game 摘掉再关句柄。旧顺序是
                           CloseHandle 在前、清 g_game 在后，中间 is_game_running
                           可能对一个已关闭的句柄做 WaitForSingleObject。 */
                        pthread_mutex_lock(&g_mu);
                        if (g_game == proc) g_game = NULL;
                        pthread_mutex_unlock(&g_mu);
                        CloseHandle(rd); CloseHandle(proc);
                        /* bridge/api.py:2136 的 `self._emit("game_exited", {"code": code})`。
                           Python 那边 code 是 subprocess 的退出码（Windows 上可能是
                           3221225477 这种大数），这里原样发 DWORD 转 double，不再做
                           scode 的符号还原——前端只按数字显示（WPF 取 GetInt32）。 */
                        {
                            cJSON *ge = cJSON_CreateObject();
                            cJSON_AddNumberToObject(ge, "code", (double)code);
                            emit("game_exited", ge);
                            cJSON_Delete(ge);
                        }
                        if (t->cancelled) { ok = 1; snprintf(msg, sizeof(msg), "已停止游戏"); }
                        else {
                            long scode = (long)code;
                            if (code > 0x7FFFFFFFu) scode = (long)(code - 0x100000000ull);
                            cJSON *rep = analyze_game_crash(inst, ver, scode, tail, tn, ts, started);
                            int crashed = 0;
                            const char *summary = NULL;
                            if (rep) {
                                cJSON *ic = cJSON_GetObjectItem(rep, "is_crash");
                                crashed = cJSON_IsTrue(ic);
                                summary = cJSON_GetStringValue(cJSON_GetObjectItem(rep, "summary"));
                                if (crashed) {
                                    cJSON_AddStringToObject(rep, "task_id", t->id);
                                    emit("crash", rep);
                                }
                                cJSON_Delete(rep);
                            }
                            if (crashed) {
                                ok = 0;
                                snprintf(msg, sizeof(msg), "%s", summary && summary[0] ? summary : "游戏崩溃");
                                pymcl_set_error("%s", msg);
                            } else if (code == 0) {
                                ok = 1;
                                snprintf(msg, sizeof(msg), "游戏已退出");
                            } else {
                                pymcl_set_error("游戏退出码 %lu", (unsigned long)code);
                                ok = 0;
                            }
                        }
                        for (int i = 0; i < tn; i++) free(tail[i]);
                    } else pymcl_set_error("无法启动游戏进程");
                    for (int i = 0; i < argc; i++) free(argv[i]);
                    free(argv);
                }
                free(jexe);
                cJSON_Delete(props);
                cJSON_Delete(acc);
            }
        }
    } else if (strcmp(t->method, "start_microsoft_login") == 0) {
        cJSON *acc = NULL;
        ok = ms_login(&ctx, on_login_code, t, &acc) == 0;
        if (ok && acc) {
            snprintf(msg, sizeof(msg), "已登录 %s", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")) ?: "");
            cJSON_Delete(acc);
        }
    } else if (strcmp(t->method, "terracotta_prepare") == 0) {
        ok = terracotta_prepare_run(&ctx, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "backup_save") == 0) {
        ok = task_backup_save_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "repair_version") == 0) {
        ok = task_repair_version_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "export_modpack") == 0) {
        ok = task_export_modpack_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "start_authlib_login") == 0) {
        ok = task_authlib_login_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "start_nide8_login") == 0) {
        ok = task_nide8_login_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "export_launch_script") == 0) {
        ok = task_export_launch_script_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "install_java") == 0) {
        ok = task_install_java_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "start_mod_updates") == 0) {
        ok = task_start_mod_updates_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "start_self_update") == 0) {
        ok = task_start_self_update_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    } else if (strcmp(t->method, "migrate_official_launcher") == 0) {
        ok = task_migrate_official_run(&ctx, t->args, msg, sizeof(msg)) == 0;
    }
    if (!msg[0]) snprintf(msg, sizeof(msg), "%s", ok ? "任务完成" : (t->cancelled ? "已取消" : pymcl_error()));
    finish_task(t, ok && !t->cancelled, t->cancelled ? "已取消" : msg);
    return NULL;
}

static cJSON *start_task(const char *title, const char *method, cJSON *args) {
    pthread_mutex_lock(&g_mu);
    if (g_ntasks >= 32) { pthread_mutex_unlock(&g_mu); pymcl_set_error("任务过多"); return NULL; }
    task_t *t = (task_t *)calloc(1, sizeof(*t));
    if (!t) { pthread_mutex_unlock(&g_mu); pymcl_set_error("内存不足"); return NULL; }
    snprintf(t->id, sizeof(t->id), "task-%d", ++g_task_n);
    snprintf(t->title, sizeof(t->title), "%s", title);
    snprintf(t->method, sizeof(t->method), "%s", method);
    if (!g_titles) g_titles = cJSON_CreateObject();
    cJSON_AddStringToObject(g_titles, t->id, t->title);
    t->args = args ? cJSON_Duplicate(args, 1) : cJSON_CreateObject();
    g_tasks[g_ntasks++] = t;
    pthread_mutex_unlock(&g_mu);
    cJSON *ad = cJSON_CreateObject();
    cJSON_AddStringToObject(ad, "task_id", t->id);
    cJSON_AddStringToObject(ad, "title", title);
    emit("task_added", ad);
    cJSON_Delete(ad);
    emit_count();
    pthread_create(&t->th, NULL, task_run, t);
    pthread_detach(t->th);
    return cJSON_CreateString(t->id);
}

static const char *ensure_inst(const char *name) {
    if (name && name[0]) return name;
    return config_str("default_instance", "default");
}

/* bridge/api.py instance_java_label：自动 → 「自动选择」；认得的 Java → 「Java 17」；否则文件名 */
static cJSON *rpc_instance_java_label(const char *name) {
    char ip[PYMCL_PATH], jp[PYMCL_PATH];
    if (instance_open(name, ip, sizeof(ip)) != 0) return NULL;
    instance_java_pref(name, jp, sizeof(jp));
    if (strcmp(jp, PYMCL_JAVA_AUTO) == 0) return cJSON_CreateString(PYMCL_JAVA_AUTO);
    cJSON *all = java_all();
    cJSON *j;
    cJSON_ArrayForEach(j, all) {
        const char *exe = cJSON_GetStringValue(cJSON_GetObjectItem(j, "exe"));
        if (exe && strcmp(exe, jp) == 0) {
            cJSON *maj = cJSON_GetObjectItem(j, "major");
            char label[64], ms[32] = "?";
            if (py_truthy(maj)) py_str(maj, ms, sizeof(ms));
            snprintf(label, sizeof(label), "Java %s", ms);
            cJSON_Delete(all);
            return cJSON_CreateString(label);
        }
    }
    cJSON_Delete(all);
    return cJSON_CreateString(pymcl_basename(jp));
}

static cJSON *rpc_get_instances(void) {
    cJSON *names = NULL;
    instance_list(&names);
    if (cJSON_GetArraySize(names) == 0) {
        const char *def = config_str("default_instance", "default");
        instance_create(def[0] ? def : "default", NULL);
        cJSON_Delete(names);
        instance_list(&names);
    }
    cJSON *out = cJSON_CreateArray();
    cJSON *it;
    cJSON_ArrayForEach(it, names) {
        const char *nm = it->valuestring;
        cJSON *ids = NULL;
        instance_installed_ids(nm, &ids);
        cJSON *meta = instance_meta(nm);
        cJSON *packv = cJSON_GetObjectItem(meta, "modpack");
        cJSON *pack = cJSON_IsObject(packv) ? packv : NULL;
        cJSON *pack_name = pack ? cJSON_GetObjectItem(pack, "name") : NULL;
        cJSON *mcver = cJSON_GetObjectItem(meta, "mc_version");
        char mc[512];
        if (py_truthy(pack_name)) py_str(pack_name, mc, sizeof(mc));
        else if (py_truthy(mcver)) py_str(mcver, mc, sizeof(mc));
        else if (cJSON_GetArraySize(ids) > 0) snprintf(mc, sizeof(mc), "%s", cJSON_GetArrayItem(ids, 0)->valuestring);
        else snprintf(mc, sizeof(mc), "%s", "未安装版本");
        char jp[PYMCL_PATH];
        instance_java_pref(nm, jp, sizeof(jp));
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "name", nm);
        cJSON_AddNumberToObject(row, "versions", cJSON_GetArraySize(ids));
        cJSON_AddStringToObject(row, "mc", mc);
        cJSON_AddItemToObject(row, "pack", py_truthy(pack_name) ? cJSON_Duplicate(pack_name, 1) : cJSON_CreateString(""));
        cJSON *pv = pack ? cJSON_GetObjectItem(pack, "version") : NULL;
        cJSON_AddItemToObject(row, "pack_version", py_truthy(pv) ? cJSON_Duplicate(pv, 1) : cJSON_CreateString(""));
        cJSON *pmc = pack ? cJSON_GetObjectItem(pack, "mc_version") : NULL;
        cJSON_AddItemToObject(row, "mc_version", py_truthy(pmc) ? cJSON_Duplicate(pmc, 1)
                              : py_truthy(mcver) ? cJSON_Duplicate(mcver, 1) : cJSON_CreateString(""));
        cJSON_AddStringToObject(row, "java", jp);
        cJSON *label = rpc_instance_java_label(nm);
        cJSON_AddItemToObject(row, "java_label", label ? label : cJSON_CreateString(pymcl_basename(jp)));
        cJSON_AddItemToArray(out, row);
        cJSON_Delete(ids);
        cJSON_Delete(meta);
    }
    cJSON_Delete(names);
    return out;
}

static cJSON *version_rows(cJSON *map) {
    cJSON *out = cJSON_CreateArray();
    cJSON *it;
    cJSON_ArrayForEach(it, map) {
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "version", it->string);
        const char *ty = cJSON_GetStringValue(cJSON_GetObjectItem(it, "type"));
        if (ty && strcmp(ty, "release") == 0) cJSON_AddStringToObject(row, "type", "release");
        else if (ty && (strcmp(ty, "old_alpha") == 0 || strcmp(ty, "old_beta") == 0))
            cJSON_AddStringToObject(row, "type", ty);
        else cJSON_AddStringToObject(row, "type", "snapshot");
        const char *dt = cJSON_GetStringValue(cJSON_GetObjectItem(it, "releaseTime"));
        if (!dt) dt = cJSON_GetStringValue(cJSON_GetObjectItem(it, "time"));
        char d[16] = {0};
        if (dt) { memcpy(d, dt, 10); d[10] = 0; }
        cJSON_AddStringToObject(row, "date", d);
        cJSON_AddItemToArray(out, row);
    }
    return out;
}

static cJSON *rpc_java_list(int scan) {
    cJSON *src = scan ? java_all() : java_list_installed();
    cJSON *out = cJSON_CreateArray();
    cJSON *j;
    cJSON_ArrayForEach(j, src) {
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(j, "name")) ?: "Java");
        cJSON *maj = cJSON_GetObjectItem(j, "major");
        char ms[16];
        if (cJSON_IsNumber(maj)) snprintf(ms, sizeof(ms), "%d", (int)maj->valuedouble);
        else snprintf(ms, sizeof(ms), "%s", cJSON_GetStringValue(maj) ?: "?");
        cJSON_AddStringToObject(row, "major", ms);
        cJSON_AddStringToObject(row, "path", cJSON_GetStringValue(cJSON_GetObjectItem(j, "exe")) ?: "");
        cJSON_AddItemToArray(out, row);
    }
    cJSON_Delete(src);
    return out;
}

void backend_init(sse_emit_fn emit_fn) {
    g_emit = emit_fn;
    catalog_init();
    cJSON *n = NULL;
    instance_list(&n);
    if (cJSON_GetArraySize(n) == 0)
        instance_create(config_str("default_instance", "default"), NULL);
    cJSON_Delete(n);
}

void backend_shutdown(void) {
    /* P2-6（同族）：与 task 线程的 g_game 写点共用 g_mu。game_kill 只是
       TerminateProcess，不会回调回来取锁，不构成重入。 */
    pthread_mutex_lock(&g_mu);
    HANDLE g = g_game;
    g_game = NULL;
    pthread_mutex_unlock(&g_mu);
    if (g) game_kill(g);
}

cJSON *backend_last_crash(void) {
    /* P2-6：读侧同样持锁 —— 复制完再解锁，否则 task 线程的 crash_store
       可能在这中间 delete 掉旧对象。 */
    pthread_mutex_lock(&g_mu);
    cJSON *dup = g_last_crash ? cJSON_Duplicate(g_last_crash, 1) : NULL;
    pthread_mutex_unlock(&g_mu);
    return dup ? dup : cJSON_CreateObject();
}

cJSON *backend_call(const char *method, cJSON *params) {
    if (!method) return NULL;
    if (strcmp(method, "get_settings") == 0) return rpc_get_settings();
    if (strcmp(method, "get_setting") == 0) {
        cJSON *s = rpc_get_settings();
        cJSON *v = cJSON_GetObjectItemCaseSensitive(s, pstr(params, "key", ""));
        cJSON *def = cJSON_GetObjectItemCaseSensitive(params, "default");
        cJSON *out = v ? cJSON_Duplicate(v, 1) : def ? cJSON_Duplicate(def, 1) : cJSON_CreateNull();
        cJSON_Delete(s);
        return out;
    }
    if (strcmp(method, "instance_java_label") == 0) return rpc_instance_java_label(pstr(params, "name", ""));

    /* BackendAPI.task_title / list_tasks / wait_task / is_game_running */
    if (strcmp(method, "task_title") == 0) {
        const char *id = pstr(params, "task_id", "");
        pthread_mutex_lock(&g_mu);
        const char *t = g_titles ? cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(g_titles, id)) : NULL;
        cJSON *r = cJSON_CreateString(t ? t : id);
        pthread_mutex_unlock(&g_mu);
        return r;
    }
    if (strcmp(method, "list_tasks") == 0) {
        cJSON *o = cJSON_CreateObject(), *running = cJSON_CreateArray();
        pthread_mutex_lock(&g_mu);
        for (int i = 0; i < g_ntasks; i++) {
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "task_id", g_tasks[i]->id);
            cJSON_AddStringToObject(r, "title", g_tasks[i]->title);
            cJSON_AddItemToArray(running, r);
        }
        cJSON *finished = g_results ? cJSON_Duplicate(g_results, 1) : cJSON_CreateArray();
        pthread_mutex_unlock(&g_mu);
        cJSON_AddItemToObject(o, "running", running);
        cJSON_AddItemToObject(o, "finished", finished);
        return o;
    }
    if (strcmp(method, "wait_task") == 0) {
        const char *id = pstr(params, "task_id", "");
        cJSON *tv = cJSON_GetObjectItem(params, "timeout");
        double timeout = cJSON_IsNumber(tv) ? tv->valuedouble : 1800;
        ULONGLONG start = GetTickCount64();
        for (;;) {
            cJSON *hit = NULL;
            pthread_mutex_lock(&g_mu);
            cJSON *r;
            cJSON_ArrayForEach(r, g_results) {
                const char *rid = cJSON_GetStringValue(cJSON_GetObjectItem(r, "task_id"));
                if (rid && strcmp(rid, id) == 0) hit = r;
            }
            cJSON *out = NULL;
            if (hit) {
                out = cJSON_CreateObject();
                cJSON_AddBoolToObject(out, "ok", cJSON_IsTrue(cJSON_GetObjectItem(hit, "success")));
                cJSON_AddStringToObject(out, "message", cJSON_GetStringValue(cJSON_GetObjectItem(hit, "message")));
                cJSON_AddStringToObject(out, "task_id", id);
            }
            pthread_mutex_unlock(&g_mu);
            if (out) return out;
            if ((double)(GetTickCount64() - start) / 1000.0 > timeout) {
                out = cJSON_CreateObject();
                cJSON_AddFalseToObject(out, "ok");
                cJSON_AddStringToObject(out, "message", tr("等待任务超时"));
                cJSON_AddStringToObject(out, "task_id", id);
                cJSON_AddTrueToObject(out, "timeout");
                return out;
            }
            Sleep(300);
        }
    }
    if (strcmp(method, "is_game_running") == 0) {
        /* P2-6（同族）：旧版裸读 g_game。WaitForSingleObject 用 0 超时（立即返回），
           放锁内不会阻塞他人；这样也不会对已被 CloseHandle 的句柄取值。 */
        pthread_mutex_lock(&g_mu);
        int running = g_game && WaitForSingleObject(g_game, 0) == WAIT_TIMEOUT;
        pthread_mutex_unlock(&g_mu);
        return cJSON_CreateBool(running);
    }
    if (strcmp(method, "save_settings") == 0 || strcmp(method, "update_settings") == 0) {
        cJSON *d = params;
        cJSON *inner = cJSON_GetObjectItem(d, "data");
        if (!cJSON_IsObject(inner)) inner = cJSON_GetObjectItem(d, "settings");
        if (cJSON_IsObject(inner)) d = inner;
        /* 局部更新：只写提交里真带来的键。侧栏拖一下只发 ui_nav_*，不能顺手把
           共享库 / 共享资源两个开关刷成 false。
           键名与落盘字段名逐条对照 bridge/api.py:956-1122 的 save_settings 白名单
           （Python 是权威）：有键名映射的按映射写（default_memory_mb→memory_mb、
           share_libraries→shared_libraries、game_dir→instances_dir）。
           以前这里只有 8 个键 + ui_* 透传，WinUI3 设置页提交的 23 个键里有 14 个被
           静默丢掉却仍返回 true（前端弹「已保存」）。 */
        cJSON *v;
        v = cJSON_GetObjectItem(d, "share_libraries");
        if (cJSON_IsBool(v)) config_set_bool("shared_libraries", cJSON_IsTrue(v));
        v = cJSON_GetObjectItem(d, "share_assets");
        if (cJSON_IsBool(v)) config_set_bool("shared_assets", cJSON_IsTrue(v));
        v = cJSON_GetObjectItem(d, "download_threads");
        if (cJSON_IsNumber(v)) config_set_int("download_threads", (int)v->valuedouble);
        v = cJSON_GetObjectItem(d, "default_memory_mb");
        if (cJSON_IsNumber(v)) config_set_int("memory_mb", (int)v->valuedouble);
        cJSON *res = cJSON_GetObjectItem(d, "default_resolution");
        if (cJSON_IsArray(res) && cJSON_GetArraySize(res) >= 2) {
            config_set_int("width", (int)cJSON_GetArrayItem(res, 0)->valuedouble);
            config_set_int("height", (int)cJSON_GetArrayItem(res, 1)->valuedouble);
        }
        v = cJSON_GetObjectItem(d, "ms_client_id");
        if (cJSON_IsString(v)) {
            /* Python：((value or "").strip() or CONFIG.get("microsoft_client_id")) —— 空串回退旧值 */
            char t[512];
            snprintf(t, sizeof(t), "%s", v->valuestring ? v->valuestring : "");
            char *s = t;
            while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
            size_t tl = strlen(s);
            while (tl && (s[tl - 1] == ' ' || s[tl - 1] == '\t' || s[tl - 1] == '\r' || s[tl - 1] == '\n')) s[--tl] = 0;
            if (s[0]) config_set_str("microsoft_client_id", s);
            else {
                const char *old = config_str("microsoft_client_id", PYMCL_MS_CLIENT_DEFAULT);
                if (old && old[0]) config_set_str("microsoft_client_id", old);
            }
        }
        v = cJSON_GetObjectItem(d, "curseforge_api_key");
        if (cJSON_IsString(v)) {
            char t[512];
            snprintf(t, sizeof(t), "%s", v->valuestring ? v->valuestring : "");
            char *s = t;
            while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
            size_t tl = strlen(s);
            while (tl && (s[tl - 1] == ' ' || s[tl - 1] == '\t' || s[tl - 1] == '\r' || s[tl - 1] == '\n')) s[--tl] = 0;
            config_set_str("curseforge_api_key", s);
        }
        {
            const char *inst = cJSON_GetStringValue(cJSON_GetObjectItem(d, "default_instance"));
            if (inst && inst[0]) config_set_str("default_instance", inst);
        }
        /* ---- AI 五键（WinUI3 的「测试 AI 连接」先 save_settings 再 test，缺这几个键
           测的永远是旧配置）。地址类键各自独立判定，不能挂在 ai_mode 下：Python 的
           注释专门写了这一点（api.py:986-996）。 ---- */
        v = cJSON_GetObjectItem(d, "ai_mode");
        if (v) {
            const char *s = cJSON_GetStringValue(v);
            config_set_str("ai_mode", (s && s[0]) ? s : "public");     /* value or "public" */
        }
        v = cJSON_GetObjectItem(d, "ai_gateway_url");
        if (v) config_set_str("ai_gateway_url", trim_str_or(cJSON_GetStringValue(v), ""));
        v = cJSON_GetObjectItem(d, "ai_base_url");
        if (v) config_set_str("ai_base_url", trim_str_or(cJSON_GetStringValue(v), ""));
        v = cJSON_GetObjectItem(d, "ai_api_key");
        if (v) {
            const char *s = cJSON_GetStringValue(v);                   /* value or ""（不 strip） */
            config_set_str("ai_api_key", s ? s : "");
        }
        v = cJSON_GetObjectItem(d, "ai_model");
        if (v) {
            /* value or CONFIG.get("ai_model") or "deepseek-v4-flash"（不 strip） */
            const char *s = cJSON_GetStringValue(v);
            if (!s || !s[0]) s = config_str("ai_model", "deepseek-v4-flash");
            config_set_str("ai_model", (s && s[0]) ? s : "deepseek-v4-flash");
        }
        /* ---- 其余 WinUI3 提交的键（api.py:1020-1122 的对应分支） ---- */
        /* 这四个 Python 走 `patch[key] = data.get(key)` 原样落盘（不补默认值、不 strip） */
        static const char *k_raw_keys[] = {"launcher_visibility", "gc_preset", "custom_homepage",
                                           "homepage_mode", NULL};
        for (int i = 0; k_raw_keys[i]; i++) {
            v = cJSON_GetObjectItem(d, k_raw_keys[i]);
            if (v) config_set(k_raw_keys[i], cJSON_Duplicate(v, 1));
        }
        v = cJSON_GetObjectItem(d, "download_source");
        if (v) {
            const char *s = cJSON_GetStringValue(v);
            config_set_str("download_source", (s && s[0]) ? s : "auto");   /* value or "auto" */
        }
        v = cJSON_GetObjectItem(d, "download_limit_kbps");
        if (v) {
            long long x = 0;
            if (!py_int(v, &x)) x = 0;                                    /* int(value or 0) */
            if (x < 0) x = 0;
            config_set_int("download_limit_kbps", (int)x);
        }
        v = cJSON_GetObjectItem(d, "auto_check_update");
        if (v) config_set_bool("auto_check_update", py_truthy(v));         /* bool(value) */
        v = cJSON_GetObjectItem(d, "default_isolation");
        if (v) {
            const char *s = cJSON_GetStringValue(v);
            config_set_str("default_isolation", (s && s[0]) ? s : "none"); /* value or "none" */
        }
        v = cJSON_GetObjectItem(d, "default_jvm_args");
        if (v) {
            const char *s = cJSON_GetStringValue(v);                       /* value or "" */
            config_set_str("default_jvm_args", s ? s : "");
        }
        /* ui_* 整键原样落盘：前端提交什么就存什么，读回去时各端自己做合法性过滤
           （Qt nav_items_from_config / WPF NavModel / 网页版 nav_model.ts 都会滤）。
           null 表示清掉（恢复默认侧栏就是把 ui_nav_groups / ui_section_members 置 null）。 */
        {
            config_lock();
            cJSON *cfg = config_obj();
            cJSON *it;
            cJSON_ArrayForEach(it, d) {
                if (!it->string || strncmp(it->string, "ui_", 3) != 0 || !cfg) continue;
                cJSON_DeleteItemFromObject(cfg, it->string);
                cJSON_AddItemToObject(cfg, it->string, cJSON_Duplicate(it, 1));
            }
            config_unlock();
        }
        config_save();
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "shutdown") == 0) {
        /* 关窗前收拢后台任务（对齐 bridge/api.py shutdown）：取消下载类任务、等一小会，
           启动游戏那个不动——「关掉启动器但游戏继续跑」是既定行为。 */
        int budget = pint(params, "timeout_ms", 800);
        pthread_mutex_lock(&g_mu);
        for (int i = 0; i < g_ntasks; i++)
            if (g_tasks[i] && strcmp(g_tasks[i]->id, g_launch_id) != 0) g_tasks[i]->cancelled = 1;
        pthread_mutex_unlock(&g_mu);
        for (int waited = 0; waited < budget; waited += 20) {
            int busy = 0;
            pthread_mutex_lock(&g_mu);
            for (int i = 0; i < g_ntasks; i++)
                if (g_tasks[i] && strcmp(g_tasks[i]->id, g_launch_id) != 0) busy++;
            pthread_mutex_unlock(&g_mu);
            if (!busy) break;
            Sleep(20);
        }
        cJSON *o = cJSON_CreateObject();
        cJSON *pending = cJSON_CreateArray();
        pthread_mutex_lock(&g_mu);
        for (int i = 0; i < g_ntasks; i++)
            if (g_tasks[i] && strcmp(g_tasks[i]->id, g_launch_id) != 0)
                cJSON_AddItemToArray(pending, cJSON_CreateString(g_tasks[i]->id));
        pthread_mutex_unlock(&g_mu);
        cJSON_AddItemToObject(o, "pending", pending);
        return o;
    }
    if (strcmp(method, "get_instances") == 0) return rpc_get_instances();
    if (strcmp(method, "create_instance") == 0) {
        if (instance_create(pstr(params, "name", ""), NULL) != 0) return NULL;
        emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateNull();
    }
    if (strcmp(method, "delete_instance") == 0) {
        if (instance_delete(pstr(params, "name", "")) != 0) return NULL;
        emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateNull();
    }
    if (strcmp(method, "rename_instance") == 0) {
        if (instance_rename(pstr(params, "name", ""), pstr(params, "new_name", "")) != 0) return NULL;
        emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateNull();
    }
    if (strcmp(method, "open_instance_folder") == 0) {
        char ip[PYMCL_PATH];
        instance_path(pstr(params, "name", ""), ip, sizeof(ip));
        pymcl_open_folder(ip);
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "get_version_list") == 0) {
        char mf[PYMCL_PATH];
        pymcl_path_join3(mf, sizeof(mf), g_root, "cache", "version_manifest.json");
        cJSON *cached = pymcl_read_json(mf);
        cJSON *map = cJSON_CreateObject();
        cJSON *v;
        cJSON_ArrayForEach(v, cJSON_GetObjectItem(cached, "versions")) {
            const char *id = cJSON_GetStringValue(cJSON_GetObjectItem(v, "id"));
            if (id) cJSON_AddItemToObject(map, id, cJSON_Duplicate(v, 1));
        }
        cJSON_Delete(cached);
        cJSON *rows = version_rows(map);
        cJSON_Delete(map);
        return rows;
    }
    if (strcmp(method, "fetch_version_list") == 0) {
        cJSON *map = manifest_list_remote(1);
        cJSON *rows = version_rows(map);
        cJSON_Delete(map);
        return rows;
    }
    if (strcmp(method, "get_installed_versions") == 0) {
        const char *inst = pstr(params, "instance", "");
        if (inst[0]) {
            char ip[PYMCL_PATH];
            if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
            cJSON *ids = NULL;
            instance_installed_ids(inst, &ids);
            if (py_truthy(cJSON_GetObjectItem(params, "include_hidden")) || config_bool("show_hidden_versions", 0))
                return ids;
            cJSON *shown = cJSON_CreateArray();
            cJSON *v;
            cJSON_ArrayForEach(v, ids) {
                cJSON *vs = version_settings_load(inst, v->valuestring);
                if (!py_truthy(cJSON_GetObjectItem(vs, "hidden")))
                    cJSON_AddItemToArray(shown, cJSON_CreateString(v->valuestring));
                cJSON_Delete(vs);
            }
            cJSON_Delete(ids);
            return shown;
        }
        cJSON *names = NULL, *out = cJSON_CreateArray();
        instance_list(&names);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            cJSON *ids = NULL;
            instance_installed_ids(it->valuestring, &ids);
            cJSON *v;
            cJSON_ArrayForEach(v, ids) {
                char s[256];
                snprintf(s, sizeof(s), "%s / %s", it->valuestring, v->valuestring);
                cJSON_AddItemToArray(out, cJSON_CreateString(s));
            }
            cJSON_Delete(ids);
        }
        cJSON_Delete(names);
        return out;
    }
    if (strcmp(method, "uninstall_version") == 0) {
        const char *spec = pstr(params, "spec", "");
        char inst[128], vid[128];
        const char *sep = strstr(spec, " / ");
        if (sep) {
            snprintf(inst, sizeof(inst), "%.*s", (int)(sep - spec), spec);
            snprintf(vid, sizeof(vid), "%s", sep + 3);
        } else {
            snprintf(inst, sizeof(inst), "%s", config_str("default_instance", "default"));
            snprintf(vid, sizeof(vid), "%s", spec);
        }
        if (uninstall_version(inst, vid) != 0) return NULL;
        emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "get_java_list") == 0)
        return rpc_java_list(cJSON_IsTrue(cJSON_GetObjectItem(params, "scan_system")));
    if (strcmp(method, "java_combo_options") == 0) {
        const char *inst = pstr(params, "instance", "default");
        int scan = cJSON_IsTrue(cJSON_GetObjectItem(params, "scan_system"));
        cJSON *opts = cJSON_CreateArray();
        cJSON *a = cJSON_CreateObject();
        cJSON_AddStringToObject(a, "label", PYMCL_JAVA_AUTO);
        cJSON_AddStringToObject(a, "value", PYMCL_JAVA_AUTO);
        cJSON_AddItemToArray(opts, a);
        cJSON *list = rpc_java_list(scan);
        cJSON *j;
        cJSON_ArrayForEach(j, list) {
            const char *p = cJSON_GetStringValue(cJSON_GetObjectItem(j, "path"));
            if (!p || !p[0]) continue;
            cJSON *o = cJSON_CreateObject();
            cJSON_AddStringToObject(o, "label", cJSON_GetStringValue(cJSON_GetObjectItem(j, "name")) ?: p);
            cJSON_AddStringToObject(o, "value", p);
            cJSON_AddItemToArray(opts, o);
        }
        cJSON_Delete(list);
        char stored[PYMCL_PATH];
        instance_java_pref(inst, stored, sizeof(stored));
        return opts;
    }
    if (strcmp(method, "java_combo_label_for") == 0) {
        const char *inst = pstr(params, "instance", "default");
        char stored[PYMCL_PATH];
        instance_java_pref(inst, stored, sizeof(stored));
        cJSON *opts = cJSON_GetObjectItem(params, "options");
        cJSON *o;
        cJSON_ArrayForEach(o, opts) {
            if (strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(o, "value")) ?: "", stored) == 0)
                return cJSON_CreateString(cJSON_GetStringValue(cJSON_GetObjectItem(o, "label")) ?: PYMCL_JAVA_AUTO);
        }
        return cJSON_CreateString(PYMCL_JAVA_AUTO);
    }
    if (strcmp(method, "set_instance_java") == 0) {
        instance_set_java_pref(pstr(params, "name", ""), pstr(params, "java", PYMCL_JAVA_AUTO));
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "get_instance_java") == 0) {
        char ip[PYMCL_PATH], jp[PYMCL_PATH];
        if (instance_open(pstr(params, "name", ""), ip, sizeof(ip)) != 0) return NULL;
        instance_java_pref(pstr(params, "name", ""), jp, sizeof(jp));
        return cJSON_CreateString(jp);
    }
    if (strcmp(method, "get_accounts") == 0) {
        cJSON *out = cJSON_CreateArray();
        cJSON_AddItemToArray(out, cJSON_CreateString("离线模式"));
        cJSON *root = accounts_load();
        cJSON *it;
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(root, "accounts")) {
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
            if (nm && nm[0]) cJSON_AddItemToArray(out, cJSON_CreateString(nm));
        }
        cJSON_Delete(root);
        return out;
    }
    if (strcmp(method, "search_mods") == 0)
        return search_mods(pstr(params, "query", ""), pstr(params, "source", ""));
    if (strcmp(method, "search_modpacks") == 0)
        return search_modpacks(pstr(params, "query", ""), pstr(params, "source", ""));
    if (strcmp(method, "search_shaders") == 0)
        return search_content("shader", pstr(params, "query", ""), pstr(params, "source", ""));
    if (strcmp(method, "search_resourcepacks") == 0)
        return search_content("resourcepack", pstr(params, "query", ""), pstr(params, "source", ""));
    if (strcmp(method, "search_datapacks") == 0)
        return search_content("datapack", pstr(params, "query", ""), pstr(params, "source", ""));
    /* 世界页直接调 search_worlds（CatalogKind.World 的 SearchMethod）。此前这一支
       落在 rpc_extra.c 的「转给 Python」列表里，打包版没有 Python 就必现
       「方法 search_worlds 需要 Python 桥」——docs/GOAL-c-bridge-no-python.md:31
       假设「前端不直接调用」是错的。这里原生实现，参数与 Python 版同构：
       query / source / extra{game_version, category}。 */
    if (strcmp(method, "search_worlds") == 0)
        return search_worlds(pstr(params, "query", ""), pstr(params, "source", ""),
                             cJSON_GetObjectItem(params, "extra"));
    if (strcmp(method, "get_installed_mods") == 0)
        return list_instance_files(pstr(params, "instance", "default"), "mods");
    if (strcmp(method, "get_installed_shaders") == 0)
        return list_instance_files(pstr(params, "instance", "default"), "shaderpacks");
    if (strcmp(method, "get_installed_resourcepacks") == 0)
        return list_instance_files(pstr(params, "instance", "default"), "resourcepacks");
    if (strcmp(method, "get_installed_datapacks") == 0)
        return list_instance_files(pstr(params, "instance", "default"), "datapacks");
    /* bridge/api.py:1458 get_installed_modpacks：读实例 .instance.json 里的 modpack 记录，
       有 name 就拼成 "名字 版本"（version 为空则只留名字），否则空列表。 */
    if (strcmp(method, "get_installed_modpacks") == 0) {
        const char *inst = pstr(params, "instance", "default");
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        cJSON *meta = instance_meta(inst);
        cJSON *pack = cJSON_GetObjectItemCaseSensitive(meta, "modpack");
        cJSON *out = cJSON_CreateArray();
        cJSON *name = cJSON_IsObject(pack) ? cJSON_GetObjectItemCaseSensitive(pack, "name") : NULL;
        if (py_truthy(name)) {
            char nm[512], ver[512];
            py_str(name, nm, sizeof(nm));
            cJSON *v = cJSON_GetObjectItemCaseSensitive(pack, "version");
            if (py_truthy(v)) {
                py_str(v, ver, sizeof(ver));
                char label[1100];
                snprintf(label, sizeof(label), "%s %s", nm, ver);
                cJSON_AddItemToArray(out, cJSON_CreateString(label));
            } else {
                cJSON_AddItemToArray(out, cJSON_CreateString(nm));
            }
        }
        cJSON_Delete(meta);
        return out;
    }
    if (strcmp(method, "delete_mod") == 0) {
        /* 原先无条件返回 true：路径校验失败（返回 -1）时前端照样弹「已删除」。
           改成跟 Python 一致——校验不过就报错（api.py:793 → mods.py:504 的
           delete_mod 会抛 ModError）。
           这一处不补 emit ui_changed：现有前端删完都自己 LoadInstalledAsync()，
           保持原样以免多一次无谓整页重载。 */
        if (delete_instance_file(pstr(params, "instance", "default"), "mods", pstr(params, "filename", "")) != 0)
            return NULL;
        return cJSON_CreateTrue();
    }
    /* bridge/api.py:830/834/838：三个 delete_<kind> 只差 subdir，Python 侧都是
       mods_mod.delete_content_file(inst, "<subdir>", filename) + emit ui_changed，
       返回 None。这里同样回 null（同 delete_modpack/delete_instance 的写法），
       前端只判 error 字段，不看 result。
       路径校验在 delete_instance_file 内（同 delete_mod）：文件名带分隔符 / `..`
       / 盘符一律报错，不落盘也不删。 */
    if (strcmp(method, "delete_shader") == 0 || strcmp(method, "delete_resourcepack") == 0
        || strcmp(method, "delete_datapack") == 0) {
        const char *subdir = strcmp(method, "delete_shader") == 0 ? "shaderpacks"
            : strcmp(method, "delete_resourcepack") == 0 ? "resourcepacks" : "datapacks";
        if (delete_instance_file(pstr(params, "instance", "default"), subdir, pstr(params, "filename", "")) != 0)
            return NULL;
        emit("ui_changed", cJSON_CreateObject());
        return cJSON_CreateNull();
    }
    if (strcmp(method, "get_crash") == 0) {
        /* P2-6：与 crash_store 同一把锁（旧版裸读 → 与写方的 delete 竞态） */
        pthread_mutex_lock(&g_mu);
        cJSON *c = g_last_crash ? cJSON_Duplicate(g_last_crash, 1) : NULL;
        pthread_mutex_unlock(&g_mu);
        return c ? c : cJSON_CreateObject();
    }
    if (strcmp(method, "export_crash_report") == 0) {
#ifdef PYMCL_NO_PY
        pymcl_set_error("NOT_NATIVE: export_crash_report still runs python -m mclauncher.crash");
        return NULL;
#else
        char py[PYMCL_PATH], jsonf[PYMCL_PATH], destf[PYMCL_PATH];
        const char *dest = pstr(params, "dest", "");
        find_python(py, sizeof(py));
        snprintf(jsonf, sizeof(jsonf), "%s\\last-crash.json", g_root);
        if (dest[0]) snprintf(destf, sizeof(destf), "%s", dest);
        else snprintf(destf, sizeof(destf), "%s\\crash-report.zip", g_root);
        const char *argv[10];
        int argc = 0;
        argv[argc++] = py;
        argv[argc++] = "-u";
        argv[argc++] = "-m";
        argv[argc++] = "mclauncher.crash";
        argv[argc++] = "--from-json";
        argv[argc++] = jsonf;
        argv[argc++] = "--export";
        argv[argc++] = destf;
        /* P2-1：退出码必须看——旧版无条件返回 destf，python 没跑起来时也报成功，
           前端拿到一个并不存在的 zip 路径。 */
        if (pymcl_run_process(argv, argc, g_root, NULL, NULL, 30) != 0 || !pymcl_file_exists(destf)) {
            if (!pymcl_error()[0]) pymcl_set_error("导出崩溃报告失败");
            return NULL;
        }
        return cJSON_CreateString(destf);
#endif
    }
    if (strcmp(method, "open_crash_file") == 0) {
        const char *path = pstr(params, "path", "");
        char from_crash[PYMCL_PATH];
        from_crash[0] = 0;
        if (!path[0]) {
            /* P2-6：在锁内把 direct_file 抄出来再用（旧版直接引用 g_last_crash 里的
               字符串，写方 delete 后就是悬垂指针）。 */
            pthread_mutex_lock(&g_mu);
            if (g_last_crash) {
                const char *df = cJSON_GetStringValue(cJSON_GetObjectItem(g_last_crash, "direct_file"));
                if (df) snprintf(from_crash, sizeof(from_crash), "%s", df);
            }
            pthread_mutex_unlock(&g_mu);
            path = from_crash;
        }
        if (!path[0]) { pymcl_set_error("没有可打开的日志文件"); return NULL; }
        pymcl_open_folder(path);
        return cJSON_CreateString(path);
    }
    if (strcmp(method, "cancel_task") == 0) {
        const char *tid = pstr(params, "task_id", "");
        pthread_mutex_lock(&g_mu);
        for (int i = 0; i < g_ntasks; i++)
            if (g_tasks[i] && strcmp(g_tasks[i]->id, tid) == 0) g_tasks[i]->cancelled = 1;
        if (strcmp(g_launch_id, tid) == 0 && g_game) game_kill(g_game);
        pthread_mutex_unlock(&g_mu);
        return cJSON_CreateTrue();
    }
    if (strcmp(method, "install_game") == 0)
        return start_task("安装游戏", method, params);
    if (strcmp(method, "download_java") == 0)
        return start_task("下载 Java", method, params);
    if (strcmp(method, "install_mod") == 0)
        return start_task("安装模组", method, params);
    if (strcmp(method, "install_modpack") == 0)
        return start_task("安装整合包", method, params);
    if (strcmp(method, "install_shader") == 0)
        return start_task("安装光影", method, params);
    if (strcmp(method, "install_resourcepack") == 0)
        return start_task("安装资源包", method, params);
    if (strcmp(method, "install_datapack") == 0)
        return start_task("安装数据包", method, params);
    if (strcmp(method, "install_world") == 0)
        return start_task("安装世界", method, params);
    if (strcmp(method, "launch_game") == 0)
        return start_task("启动游戏", method, params);
    if (strcmp(method, "start_microsoft_login") == 0)
        return start_task("微软登录", method, params);
    if (strcmp(method, "terracotta_prepare") == 0)
        return start_task("准备陶瓦联机", method, params);
    if (strcmp(method, "backup_save") == 0)
        return start_task("备份存档", method, params);
    if (strcmp(method, "repair_version") == 0)
        return start_task("修复", method, params);
    if (strcmp(method, "export_modpack") == 0)
        return start_task("导出整合包", method, params);
    if (strcmp(method, "start_authlib_login") == 0)
        return start_task("皮肤站登录", method, params);
    if (strcmp(method, "start_nide8_login") == 0)
        return start_task("统一通行证登录", method, params);
    if (strcmp(method, "export_launch_script") == 0)
        return start_task("导出启动脚本", method, params);
    if (strcmp(method, "install_java") == 0)
        return start_task("安装 Java", method, params);
    if (strcmp(method, "start_mod_updates") == 0)
        return start_task("检查模组更新", method, params);
    if (strcmp(method, "start_self_update") == 0)
        return start_task("更新启动器", method, params);
    if (strcmp(method, "migrate_official_launcher") == 0)
        return start_task("迁移官方启动器", method, params);

    /* 启动页布局：原生实现，别为每一次拖拽起一个 python 进程 */
    {
        int handled = 0;
        cJSON *lay = rpc_layout_call(method, params, &handled);
        if (handled) return lay;
    }

    /* 去 Python 化新移植的本地功能（docs/GOAL-c-bridge-no-python.md M1） */
    {
        int handled = 0;
        cJSON *local = rpc_local_call(method, params, emit, &handled);
        if (handled) return local;
    }

    /* M2 联网：反馈 / 模组更新 / 目录文件列表（docs/GOAL-c-bridge-no-python.md M2） */
    {
        int handled = 0;
        cJSON *m2 = rpc_feedback_call(method, params, &handled);
        if (handled) return m2;
        m2 = rpc_mod_update_call(method, params, &handled);
        if (handled) return m2;
        m2 = rpc_catalog_call(method, params, &handled);
        if (handled) return m2;
    }

    /* 陶瓦联机（docs/GOAL-c-bridge-no-python.md M4） */
    {
        int handled = 0;
        cJSON *tc = rpc_terracotta_call(method, params, emit, &handled);
        if (handled) return tc;
    }

    /* Align remaining RPC with Python bridge/api.py (native first, then py_rpc). */
    {
        int handled = 0;
        cJSON *aligned = rpc_align_call(method, params, emit, &handled);
        if (handled) return aligned;
    }
    {
        /* nopy 构建里这一支只剩 NOT_NATIVE（rpc_fallback_call 内部 #ifdef 掉真回落）。 */
        int handled = 0;
        cJSON *via_py = rpc_fallback_call(method, params, &handled);
        if (via_py) return via_py;
        /* Python 端跑到了、只是抛了错：pymcl_set_error 里已经是真正的原因。
           再写一句 "unknown method" 就把它盖掉了——界面上那一片
           "unknown method: XXX" 里，有很大一部分其实是这么来的。 */
        if (handled) return NULL;
    }
    pymcl_set_error("unknown method: %s", method);
    return NULL;
}
