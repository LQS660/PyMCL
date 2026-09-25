#include "pymcl.h"

static cJSON *g_cfg;

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
    "\"ai_gateway_url\":\"\","
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

void config_init(void) {
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
    if (save) config_save();
}

cJSON *config_obj(void) { return g_cfg; }

cJSON *config_get(const char *key) {
    return g_cfg ? cJSON_GetObjectItemCaseSensitive(g_cfg, key) : NULL;
}

const char *config_str(const char *key, const char *def) {
    cJSON *v = config_get(key);
    return cJSON_IsString(v) ? v->valuestring : def;
}
int config_int(const char *key, int def) {
    cJSON *v = config_get(key);
    if (cJSON_IsNumber(v)) return (int)v->valuedouble;
    if (cJSON_IsBool(v)) return cJSON_IsTrue(v);
    if (cJSON_IsString(v) && v->valuestring) {
        char *end = NULL;
        long x = strtol(v->valuestring, &end, 10);
        if (end && end != v->valuestring && !*end) return (int)x;
    }
    return def;
}
int config_bool(const char *key, int def) {
    cJSON *v = config_get(key);
    if (!v) return def;
    if (cJSON_IsBool(v)) return cJSON_IsTrue(v);
    if (cJSON_IsNumber(v)) return v->valuedouble != 0;
    if (cJSON_IsString(v)) return v->valuestring && v->valuestring[0];
    if (cJSON_IsNull(v)) return 0;
    if (cJSON_IsArray(v) || cJSON_IsObject(v)) return v->child != NULL;
    return def;
}
void config_set(const char *key, cJSON *val) {
    if (!g_cfg || !val) return;
    set_item(g_cfg, key, val);
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
    pymcl_write_json(p, g_cfg);
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
