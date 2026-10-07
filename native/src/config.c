#include "pymcl.h"
#include <pthread.h>

static cJSON *g_cfg;

/* P1-6：g_cfg 是一棵被多线程共享的 cJSON 树——client 线程在 save_settings 里删/插键，
   任务线程在 config_set_str("default_instance") + config_save，layout 的 cfg_put 也在改。
   以前一把锁都没有：config_save 遍历整棵树时另一线程正在删节点就是 UAF，
   或者写出一份撕裂的 config.json（GOAL 2.2 要求两个桥轮流读写同一份数据不出错）。
   现在所有 config_* 入口都在同一把互斥量下（内部走 *_locked 变体，所以不需要递归锁）。
   保护范围：config_get / config_str / config_int / config_bool / config_set* /
   config_save / config_init。config_obj 返回内部指针，调用方要自己用
   config_lock() / config_unlock() 把「读-改-写」整段圈起来（backend.c 的 ui_* 透传、
   layout.c 的 cfg_put 已改）。
   残留风险：config_str() / config_get() 返回的是树内指针，锁释放后若别的线程删掉了那个
   键就悬空——现存调用点全部是「取值后立刻拷进栈缓冲 / 立刻读数值」，没有跨调用持有；
   要彻底消除得让访问器返回值拷贝，属于另一轮改动。 */
static pthread_mutex_t g_cfg_mu = PTHREAD_MUTEX_INITIALIZER;
static INIT_ONCE g_cfg_once = INIT_ONCE_STATIC_INIT;

/* 递归锁：layout 的处理器会 config_lock() 圈住整段「读-改-写」，中间又会调
   config_save()（内部再锁一次），非递归锁会自死锁。 */
static BOOL CALLBACK cfg_mu_init(PINIT_ONCE once, PVOID param, PVOID *ctx) {
    (void)once; (void)param; (void)ctx;
    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr);
    pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&g_cfg_mu, &attr);
    pthread_mutexattr_destroy(&attr);
    return TRUE;
}

void config_lock(void) {
    InitOnceExecuteOnce(&g_cfg_once, cfg_mu_init, NULL, NULL);
    pthread_mutex_lock(&g_cfg_mu);
}
void config_unlock(void) { pthread_mutex_unlock(&g_cfg_mu); }

/* 与 mclauncher/config.py 的 DEFAULT_CONFIG 逐键一致，顺序也一致：两个桥轮流落盘的
   config.json 读回来是同一份。改 Python 那边的出厂值时这里要跟着改（_c_py_parity.py 的
   get_settings 用例会抓到没跟上的键）。 */
static const char *k_default_config =
    "{"
    "\"instances_dir\":\".minecraft\","
    "\"default_instance\":\"\","
    "\"java_dir\":\"java\","
    "\"shared_libraries\":false,"
    "\"shared_assets\":false,"
    "\"memory_mb\":4096,"
    "\"download_threads\":8,"
    "\"width\":854,"
    "\"height\":480,"
    "\"microsoft_client_id\":\"" PYMCL_MS_CLIENT_DEFAULT "\","
    "\"curseforge_api_key\":\"$2a$10$o8pygPrhvKBHuuh5imL2W.LCNFhB15zBYAExXx/TqTx/Zp5px2lxu\","
    "\"github_proxy_prefixes\":[\"https://gitproxy.mrhjx.cn/\",\"https://ghproxy.vip/\","
    "\"https://gh-proxy.com/\",\"https://v6.gh-proxy.org/\",\"https://cdn.gh-proxy.com/\"],"
    "\"force_manifest_refresh\":false,"
    "\"download_source\":\"auto\","
    "\"community_source\":\"auto\","
    "\"use_system_proxy\":true,"
    "\"ai_mode\":\"public\","
    "\"ai_gateway_url\":\"\","      /* 空 = 用内置公益网关（settings.c 运行期解码兜底） */
    "\"ai_base_url\":\"\","
    "\"ai_api_key\":\"\","
    "\"ai_model\":\"deepseek-v4-flash\","
    "\"ai_confirm_writes\":true,"
    "\"ai_permission_mode\":\"default\","
    "\"ai_permission_rules\":[],"
    "\"ai_permission_dont_ask\":false,"
    "\"ai_context_window\":200000,"
    "\"ai_max_tokens\":8192,"
    "\"terracotta_extra_nodes\":[\"https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0\"],"
    "\"feedback_url\":\"\","
    "\"feedback_heartbeat\":true,"
    "\"feedback_consent\":null,"
    "\"device_id\":\"\","
    "\"default_isolation\":\"all\","
    "\"isolation_defaults\":\"\","
    "\"ai_gateway_defaults\":\"\","
    "\"default_jvm_args\":\"\","
    "\"default_priority\":\"normal\","
    "\"update_url\":\"https://pymcl.dev/update.json\","
    "\"theme_color\":\"#2E9B6B\","
    "\"ui_dark\":false,"
    "\"ui_background\":\"\","
    "\"ui_background_folder\":\"\","
    "\"ui_background_shuffle\":false,"
    "\"ui_background_interval\":10,"
    "\"ui_background_history\":[],"
    "\"ui_background_folder_history\":[],"
    "\"ui_sidebar_opacity\":85,"
    "\"ui_background_blur\":0,"
    "\"ui_background_dim\":25,"
    "\"ui_fly_animation\":true,"
    "\"ui_fly_duration_ms\":620,"
    "\"ui_motion\":true,"
    "\"ui_layout\":null,"
    "\"ui_layouts\":{},"
    "\"ui_layout_profile\":\"\","
    "\"ui_launch_dock_corner\":\"auto\","
    "\"ui_window_aspect\":\"4:3\","
    "\"ui_nav_order\":[],"
    "\"ui_nav_hidden\":[],"
    "\"ui_nav_pinned\":[],"
    "\"ui_nav_groups\":null,"
    "\"ui_nav_defaults\":\"\","
    "\"ui_nav_style\":\"grouped\","
    "\"ui_section_members\":{},"
    "\"ui_sidebar_width\":0,"
    "\"default_java\":\"\","
    "\"global_mods_dir\":\"\","
    "\"launcher_visibility\":\"keep\","
    "\"gc_preset\":\"auto\","
    "\"download_limit_kbps\":0,"
    "\"auto_check_update\":true,"
    "\"custom_homepage\":\"\","
    "\"homepage_mode\":\"news\","
    "\"window_mode\":\"window\","
    "\"skip_assets\":false,"
    "\"first_run\":true,"
    "\"show_hidden_versions\":false,"
    "\"catalog_favorites\":[],"
    "\"offline_skin\":\"default\","
    "\"allow_multi_instance\":false,"
    "\"export_dir\":\"\","
    "\"language\":\"zh_CN\""
    "}";

#define ISOLATION_DEFAULTS_VERSION "2026.09-isolate-all"
#define AI_GATEWAY_DEFAULTS_VERSION "2026.10-builtin-newapi"

static void set_item(cJSON *o, const char *key, cJSON *val) {
    if (cJSON_GetObjectItemCaseSensitive(o, key)) cJSON_ReplaceItemInObjectCaseSensitive(o, key, val);
    else cJSON_AddItemToObject(o, key, val);
}

/* 旧版默认 instances/ 迁到 .minecraft/。用户自己改过的路径不动。 */
static int migrate_legacy_instances_dir(cJSON *o) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(o, "instances_dir");
    if (!cJSON_IsString(v) || !v->valuestring) return 0;
    char cur[PYMCL_PATH];
    snprintf(cur, sizeof(cur), "%s", v->valuestring);
    char *s = cur, *e = cur + strlen(cur);
    while (*s == ' ' || *s == '\t') s++;
    while (e > s && (e[-1] == ' ' || e[-1] == '\t')) *--e = 0;
    if (strcmp(s, "instances") != 0) return 0;
    char oldp[PYMCL_PATH], newp[PYMCL_PATH];
    pymcl_path_join(oldp, sizeof(oldp), g_root, "instances");
    pymcl_path_join(newp, sizeof(newp), g_root, ".minecraft");
    if (pymcl_dir_exists(oldp) && !pymcl_dir_exists(newp) && !pymcl_file_exists(newp)) {
        wchar_t *wa = pymcl_u8_to_wide(oldp), *wb = pymcl_u8_to_wide(newp);
        MoveFileW(wa, wb);
        free(wa);
        free(wb);
    }
    set_item(o, "instances_dir", cJSON_CreateString(".minecraft"));
    return 1;
}

/* 新版本默认隔离档位换过出厂值：还停在旧出厂值 none 上的配置跟一次，只做一次。 */
static int migrate_default_isolation(cJSON *o) {
    const char *mark = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "isolation_defaults"));
    if (mark && strcmp(mark, ISOLATION_DEFAULTS_VERSION) == 0) return 0;
    const char *iso = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "default_isolation"));
    if (iso && strcmp(iso, "none") == 0) set_item(o, "default_isolation", cJSON_CreateString("all"));
    set_item(o, "isolation_defaults", cJSON_CreateString(ISOLATION_DEFAULTS_VERSION));
    return 1;
}

/* 内置网关从「自建 ai_gateway 的 /pymcl/chat」换成「标准 NewAPI 的 /v1」。
   只迁还停在旧出厂值 public、且三条地址都没自己填过的配置；挑过模式或填过地址的人不动。 */
static int migrate_ai_gateway_mode(cJSON *o) {
    const char *mark = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "ai_gateway_defaults"));
    if (mark && strcmp(mark, AI_GATEWAY_DEFAULTS_VERSION) == 0) return 0;
    const char *keys[] = {"ai_gateway_url", "ai_base_url", "ai_api_key"};
    int untouched = 1;
    for (int i = 0; i < 3; i++) {
        const char *v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, keys[i]));
        if (v && v[0]) { untouched = 0; break; }
    }
    const char *mode = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, "ai_mode"));
    if (untouched && mode && strcmp(mode, "public") == 0)
        set_item(o, "ai_mode", cJSON_CreateString("custom"));
    set_item(o, "ai_gateway_defaults", cJSON_CreateString(AI_GATEWAY_DEFAULTS_VERSION));
    return 1;
}

void config_init(void) {
    config_lock();
    char p[PYMCL_PATH];
    pymcl_path_join(p, sizeof(p), g_root, "config.json");
    cJSON *defaults = cJSON_Parse(k_default_config);
    cJSON *stored = pymcl_read_json(p);
    int save = 0;
    if (cJSON_IsObject(stored)) {
        /* 出厂键按出厂顺序在前，磁盘上多出来的键原样留在后面（布局模块等走 set 写进来的键） */
        g_cfg = cJSON_CreateObject();
        cJSON *d;
        cJSON_ArrayForEach(d, defaults) {
            cJSON *v = cJSON_GetObjectItemCaseSensitive(stored, d->string);
            if (v) cJSON_AddItemToObject(g_cfg, d->string, cJSON_Duplicate(v, 1));
            else {
                cJSON_AddItemToObject(g_cfg, d->string, cJSON_Duplicate(d, 1));
                save = 1;
            }
        }
        cJSON *s;
        cJSON_ArrayForEach(s, stored) {
            if (s->string && !cJSON_GetObjectItemCaseSensitive(defaults, s->string))
                cJSON_AddItemToObject(g_cfg, s->string, cJSON_Duplicate(s, 1));
        }
        cJSON_Delete(defaults);
    } else {
        g_cfg = defaults;
        save = 1;
    }
    cJSON_Delete(stored);
    if (migrate_legacy_instances_dir(g_cfg)) save = 1;
    if (migrate_default_isolation(g_cfg)) save = 1;
    if (migrate_ai_gateway_mode(g_cfg)) save = 1;
    if (save) config_save();
    config_unlock();
}

/* 返回内部指针。读改写的调用方必须自己用 config_lock()/config_unlock() 圈住整段
   （backend.c 的 ui_* 透传、layout.c 的 cfg_put 已经这么做）。 */
cJSON *config_obj(void) { return g_cfg; }

static cJSON *get_item_unlocked(const char *key) {
    return g_cfg ? cJSON_GetObjectItemCaseSensitive(g_cfg, key) : NULL;
}

cJSON *config_get(const char *key) {
    config_lock();
    cJSON *v = get_item_unlocked(key);
    config_unlock();
    return v;
}

/* 注意：返回的是树内字符串指针，出锁后别的线程删掉这个键就会悬空。现存调用点
   全部是「拿到就立刻拷进栈缓冲 / 立刻 strcmp」，没有跨调用持有；要彻底消除
   得把访问器改成返回值拷贝。 */
const char *config_str(const char *key, const char *def) {
    cJSON *v = config_get(key);
    return cJSON_IsString(v) ? v->valuestring : def;
}
int config_int(const char *key, int def) {
    /* 锁内读完整个字段：出锁后节点可能已被别的线程删掉 */
    config_lock();
    cJSON *v = get_item_unlocked(key);
    int out = def;
    if (cJSON_IsNumber(v)) out = (int)v->valuedouble;
    else if (cJSON_IsBool(v)) out = cJSON_IsTrue(v);
    else if (cJSON_IsString(v) && v->valuestring) {
        char *end = NULL;
        long x = strtol(v->valuestring, &end, 10);
        if (end && end != v->valuestring && !*end) out = (int)x;
    }
    config_unlock();
    return out;
}
int config_bool(const char *key, int def) {
    config_lock();
    cJSON *v = get_item_unlocked(key);
    int out = def;
    if (!v) out = def;
    else if (cJSON_IsBool(v)) out = cJSON_IsTrue(v);
    else if (cJSON_IsNumber(v)) out = v->valuedouble != 0;
    else if (cJSON_IsString(v)) out = v->valuestring && v->valuestring[0];
    else if (cJSON_IsNull(v)) out = 0;
    else if (cJSON_IsArray(v) || cJSON_IsObject(v)) out = v->child != NULL;
    config_unlock();
    return out;
}
void config_set(const char *key, cJSON *val) {
    config_lock();
    if (g_cfg && val) set_item(g_cfg, key, val);
    else if (val) cJSON_Delete(val);
    config_unlock();
}
void config_set_str(const char *key, const char *val) {
    config_set(key, cJSON_CreateString(val ? val : ""));
}
void config_set_int(const char *key, int val) {
    config_set(key, cJSON_CreateNumber(val));
}
void config_set_bool(const char *key, int v) {
    config_set(key, cJSON_CreateBool(v));
}
void config_save(void) {
    char p[PYMCL_PATH];
    pymcl_path_join(p, sizeof(p), g_root, "config.json");
    /* 序列化在锁内做：pymcl_write_json 会遍历整棵树，必须挡住并发的改树线程 */
    config_lock();
    pymcl_write_json(p, g_cfg);
    config_unlock();
}
void config_libraries_dir(const char *instance_path, char *out, size_t n) {
    if (config_bool("shared_libraries", 0))
        pymcl_path_join3(out, n, g_root, "shared", "libraries");
    else
        pymcl_path_join(out, n, instance_path, "libraries");
}
void config_assets_dir(const char *instance_path, char *out, size_t n) {
    if (config_bool("shared_assets", 0))
        pymcl_path_join3(out, n, g_root, "shared", "assets");
    else
        pymcl_path_join(out, n, instance_path, "assets");
}
