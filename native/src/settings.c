#include "pymcl.h"

/* bridge/api.py BackendAPI.get_settings 的逐键移植（键的顺序、默认值、归一化都照抄）。 */

/* 内置公益网关（开箱即用）。这是一个标准 NewAPI 服务，所以默认接入方式是把
   ai_gateway_url 预填成 base（到 /v1 为止）、ai_api_key 预填成内置令牌。
   地址与令牌做「中度」混淆：逐字节 XOR 掩码，运行时解码。这**不是**安全边界，
   只为挡住 strings 顺手抄的小白；真正想白嫖的人反汇编照样能还原。 */
#define BUILTIN_GW_MASK 0x5A
static const unsigned char BUILTIN_GW_BYTES[] = {
    50, 46, 46, 42, 41, 96, 117, 117, 52, 63, 45, 116,
    105, 43, 116, 50, 59, 51, 40
};  /* 解码后是内置网关根地址（勿把明文写回这里，混淆就白做了） */

#define BUILTIN_KEY_MASK 0x37
static const unsigned char BUILTIN_KEY_BYTES[] = {
    68, 92, 26, 64, 116, 0, 7, 110, 86, 3, 125, 98, 98, 94, 100, 93, 71, 97, 123, 92,
    121, 113, 113, 83, 120, 6, 97, 85, 99, 65, 91, 89, 123, 124, 85, 6, 88, 96, 94,
    127, 125, 112, 69, 97, 96, 6, 0, 2, 127, 85, 66
};  /* 解码后是内置令牌 */

static void builtin_unmask(const unsigned char *data, size_t n, unsigned char mask,
                           char *out, size_t cap) {
    size_t i = 0;
    for (; i < n && i + 1 < cap; i++) out[i] = (char)(data[i] ^ mask);
    out[i] = 0;
}

/* 内置公益网关 base（带 /v1） */
void builtin_gateway_base(char *out, size_t cap) {
    char raw[128];
    builtin_unmask(BUILTIN_GW_BYTES, sizeof(BUILTIN_GW_BYTES), BUILTIN_GW_MASK, raw, sizeof(raw));
    snprintf(out, cap, "%s/v1", raw);
}

/* 内置公益网关令牌 */
void builtin_gateway_key(char *out, size_t cap) {
    builtin_unmask(BUILTIN_KEY_BYTES, sizeof(BUILTIN_KEY_BYTES), BUILTIN_KEY_MASK, out, cap);
}

static const char *builtin_gateway_base_default(void) {
    static char cached[160];
    if (!cached[0]) builtin_gateway_base(cached, sizeof(cached));
    return cached;
}

static const char *builtin_gateway_key_default(void) {
    static char cached[256];
    if (!cached[0]) builtin_gateway_key(cached, sizeof(cached));
    return cached;
}

#define DEFAULT_GATEWAY_URL builtin_gateway_base_default()
#define DEFAULT_GATEWAY_KEY builtin_gateway_key_default()
#define DEFAULT_MODEL "deepseek-v4-flash"
#define DEFAULT_FEEDBACK_URL "http://114.66.28.184:53611"

static int cfg_bool(const char *key, int def) {
    cJSON *v = config_get(key);
    return v ? py_truthy(v) : def;
}

static long long cfg_int(const char *key, long long def) {
    cJSON *v = config_get(key);
    return v ? py_int_or(v, def) : def;
}

/* CONFIG.get(key) or default（值原样带出，不强转成字符串） */
static cJSON *cfg_or(const char *key, const char *def) {
    return py_or(config_get(key), cJSON_CreateString(def));
}

static void add(cJSON *o, const char *key, cJSON *v) { cJSON_AddItemToObject(o, key, v); }

static int is_permission_mode(const char *m) {
    static const char *modes[] = {"default", "plan", "edit", "acceptEdits", "auto", "dontAsk",
                                  "autoEdit", "yolo", "bypassPermissions", NULL};
    for (int i = 0; modes[i]; i++) if (strcmp(m, modes[i]) == 0) return 1;
    return 0;
}

/* mclauncher/ai/permission.py normalize_permission_mode */
static const char *normalize_permission_mode(const cJSON *raw, int confirm_writes) {
    char mode[128] = "";
    if (py_truthy(raw)) py_str(raw, mode, sizeof(mode));
    char *s = mode;
    while (*s == ' ' || *s == '\t') s++;
    size_t len = strlen(s);
    while (len && (s[len - 1] == ' ' || s[len - 1] == '\t')) s[--len] = 0;
    static char keep[128];
    if (!s[0] || strcmp(s, "standard") == 0) return confirm_writes ? "default" : "yolo";
    if (strcmp(s, "full") == 0) return confirm_writes ? "acceptEdits" : "yolo";
    if (strcmp(s, "custom") == 0) return "custom";
    if (is_permission_mode(s)) {
        snprintf(keep, sizeof(keep), "%s", s);
        return keep;
    }
    return confirm_writes ? "default" : "yolo";
}

static cJSON *nav_keys(const cJSON *raw) {
    cJSON *out = cJSON_CreateArray();
    if (!cJSON_IsArray(raw)) return out;
    const cJSON *it;
    cJSON_ArrayForEach(it, raw) {
        char key[256];
        py_str(it, key, sizeof(key));
        char *s = key;
        while (*s && (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r')) s++;
        size_t len = strlen(s);
        while (len && (s[len - 1] == ' ' || s[len - 1] == '\t' || s[len - 1] == '\n' || s[len - 1] == '\r')) s[--len] = 0;
        if (!s[0]) continue;
        int seen = 0;
        const cJSON *e;
        cJSON_ArrayForEach(e, out) if (strcmp(e->valuestring, s) == 0) { seen = 1; break; }
        if (!seen) cJSON_AddItemToArray(out, cJSON_CreateString(s));
    }
    return out;
}

static cJSON *nav_groups(const cJSON *raw) {
    cJSON *out = cJSON_CreateArray();
    if (!cJSON_IsArray(raw)) return out;
    const cJSON *g;
    cJSON_ArrayForEach(g, raw) {
        if (!cJSON_IsObject(g)) continue;
        char title[512] = "";
        const cJSON *t = cJSON_GetObjectItemCaseSensitive(g, "title");
        if (py_truthy(t)) py_str(t, title, sizeof(title));
        char *s = title;
        while (*s == ' ' || *s == '\t') s++;
        size_t len = strlen(s);
        while (len && (s[len - 1] == ' ' || s[len - 1] == '\t')) s[--len] = 0;
        if (!s[0]) continue;
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "title", s);
        cJSON_AddItemToObject(row, "keys", nav_keys(cJSON_GetObjectItemCaseSensitive(g, "keys")));
        cJSON_AddItemToArray(out, row);
    }
    return out;
}

static cJSON *nav_members(const cJSON *raw) {
    static const char *sections[] = {"download", "more", NULL};
    cJSON *out = cJSON_CreateObject();
    if (!cJSON_IsObject(raw)) return out;
    int any = 0;
    for (int i = 0; sections[i]; i++) {
        cJSON *keys = nav_keys(cJSON_GetObjectItemCaseSensitive(raw, sections[i]));
        if (cJSON_GetArraySize(keys) > 0) any = 1;
        cJSON_AddItemToObject(out, sections[i], keys);
    }
    if (!any) {
        cJSON_Delete(out);
        return cJSON_CreateObject();
    }
    return out;
}

static const char *window_aspect(const cJSON *v) {
    char key[64] = "";
    if (py_truthy(v)) py_str(v, key, sizeof(key));
    char *s = key;
    while (*s == ' ' || *s == '\t') s++;
    size_t len = strlen(s);
    while (len && (s[len - 1] == ' ' || s[len - 1] == '\t')) s[--len] = 0;
    if (strcmp(s, "4:3") == 0) return "4:3";
    if (strcmp(s, "16:9") == 0) return "16:9";
    if (strcmp(s, "free") == 0) return "free";
    return "4:3";
}

/* CONFIG.get(key, default) 取值：键不存在才用 default */
static const cJSON *cfg_get_or(const char *key, cJSON *tmp_default) {
    cJSON *v = config_get(key);
    return v ? v : tmp_default;
}

cJSON *rpc_get_settings(void) {
    cJSON *o = cJSON_CreateObject();
    char buf[PYMCL_PATH];
    add(o, "share_libraries", cJSON_CreateBool(cfg_bool("shared_libraries", 0)));
    add(o, "share_assets", cJSON_CreateBool(cfg_bool("shared_assets", 0)));
    add(o, "download_threads", cJSON_CreateNumber((double)cfg_int("download_threads", 8)));
    add(o, "default_memory_mb", cJSON_CreateNumber((double)cfg_int("memory_mb", 4096)));
    cJSON *res = cJSON_CreateArray();
    cJSON_AddItemToArray(res, cJSON_CreateNumber((double)cfg_int("width", 854)));
    cJSON_AddItemToArray(res, cJSON_CreateNumber((double)cfg_int("height", 480)));
    add(o, "default_resolution", res);
    add(o, "ms_client_id", cfg_or("microsoft_client_id", ""));
    add(o, "curseforge_api_key", cfg_or("curseforge_api_key", ""));
    /* 内置网关是标准 NewAPI（仅 /v1/* 为真实接口），默认走 custom；public 留给自建 ai_gateway。 */
    add(o, "ai_mode", cfg_or("ai_mode", "custom"));
    /* 内置公益网关开箱即用：用户没填地址/令牌时回内置值（运行期解码），前端据此预填。 */
    add(o, "ai_gateway_url", py_or(config_get("ai_gateway_url"), cJSON_CreateString(DEFAULT_GATEWAY_URL)));
    add(o, "ai_base_url", py_or(config_get("ai_base_url"), cJSON_CreateString(DEFAULT_GATEWAY_URL)));
    add(o, "ai_api_key", py_or(config_get("ai_api_key"), cJSON_CreateString(DEFAULT_GATEWAY_KEY)));
    add(o, "ai_model", cfg_or("ai_model", DEFAULT_MODEL));
    int confirm = cfg_bool("ai_confirm_writes", 1);
    add(o, "ai_confirm_writes", cJSON_CreateBool(confirm));
    add(o, "ai_permission_mode", cJSON_CreateString(normalize_permission_mode(config_get("ai_permission_mode"), confirm)));
    add(o, "ai_permission_rules", py_list(config_get("ai_permission_rules")));
    add(o, "ai_permission_dont_ask", cJSON_CreateBool(cfg_bool("ai_permission_dont_ask", 0)));
    {
        cJSON *v = config_get("ai_context_window");
        long long w = py_truthy(v) ? py_int_or(v, 131072) : 131072;
        add(o, "ai_context_window", cJSON_CreateNumber((double)(w < 8192 ? 8192 : w)));
    }
    {
        cJSON *v = config_get("ai_max_tokens");
        add(o, "ai_max_tokens", cJSON_CreateNumber((double)(py_truthy(v) ? py_int_or(v, 8192) : 8192)));
    }
    {
        cJSON *v = config_get("ai_fallback_model");
        char s[512] = "";
        if (py_truthy(v)) py_str(v, s, sizeof(s));
        add(o, "ai_fallback_model", cJSON_CreateString(s));
    }
    add(o, "root", cJSON_CreateString(g_root));
    add(o, "feedback_url", py_or(config_get("feedback_url"), cJSON_CreateString(DEFAULT_FEEDBACK_URL)));
    add(o, "feedback_heartbeat", cJSON_CreateBool(cfg_bool("feedback_heartbeat", 1)));
    add(o, "feedback_consent", cJSON_CreateBool(cJSON_IsTrue(config_get("feedback_consent"))));
    add(o, "default_isolation", cfg_or("default_isolation", "none"));
    add(o, "default_jvm_args", cfg_or("default_jvm_args", ""));
    add(o, "update_url", cfg_or("update_url", ""));
    add(o, "download_source", cfg_or("download_source", "auto"));
    add(o, "community_source", cfg_or("community_source", "auto"));
    add(o, "use_system_proxy", cJSON_CreateBool(cfg_bool("use_system_proxy", 1)));
    add(o, "launcher_visibility", cfg_or("launcher_visibility", "keep"));
    add(o, "gc_preset", cfg_or("gc_preset", "auto"));
    {
        cJSON *v = config_get("download_limit_kbps");
        add(o, "download_limit_kbps", cJSON_CreateNumber((double)(py_truthy(v) ? py_int_or(v, 0) : 0)));
    }
    add(o, "auto_check_update", cJSON_CreateBool(cfg_bool("auto_check_update", 1)));
    add(o, "custom_homepage", cfg_or("custom_homepage", ""));
    add(o, "homepage_mode", cfg_or("homepage_mode", "news"));
    add(o, "window_mode", cfg_or("window_mode", "window"));
    pymcl_instances_dir(buf, sizeof(buf));
    add(o, "game_dir", cJSON_CreateString(buf));
    add(o, "offline_skin", cfg_or("offline_skin", "default"));
    add(o, "default_java", cfg_or("default_java", ""));
    add(o, "default_instance", cfg_or("default_instance", "default"));
    add(o, "ui_dark", cJSON_CreateBool(cfg_bool("ui_dark", 0)));
    add(o, "theme_color", cfg_or("theme_color", "#2E9B6B"));
    add(o, "ui_background", cfg_or("ui_background", ""));
    add(o, "ui_background_folder", cfg_or("ui_background_folder", ""));
    add(o, "ui_background_shuffle", cJSON_CreateBool(cfg_bool("ui_background_shuffle", 0)));
    {
        cJSON *d = cJSON_CreateNumber(10);
        add(o, "ui_background_interval", cJSON_CreateNumber((double)py_clamp_int(cfg_get_or("ui_background_interval", d), 1, 1440, 10)));
        cJSON_Delete(d);
    }
    add(o, "ui_background_history", py_list(config_get("ui_background_history")));
    {
        cJSON *d = cJSON_CreateNumber(0);
        add(o, "ui_background_blur", cJSON_CreateNumber((double)py_clamp_int(cfg_get_or("ui_background_blur", d), 0, 40, 0)));
        add(o, "ui_background_dim", cJSON_CreateNumber((double)py_clamp_int(cfg_get_or("ui_background_dim", d), 0, 80, 0)));
        cJSON_Delete(d);
    }
    {
        cJSON *d = cJSON_CreateNumber(100);
        add(o, "ui_sidebar_opacity", cJSON_CreateNumber((double)py_clamp_int(cfg_get_or("ui_sidebar_opacity", d), 30, 100, 100)));
        cJSON_Delete(d);
    }
    add(o, "ui_window_aspect", cJSON_CreateString(window_aspect(config_get("ui_window_aspect"))));
    add(o, "ui_motion", cJSON_CreateBool(cfg_bool("ui_motion", 1)));
    add(o, "ui_fly_animation", cJSON_CreateBool(cfg_bool("ui_fly_animation", 1)));
    {
        cJSON *v = config_get("ui_fly_duration_ms");
        long long ms = v ? py_int_or(v, 620) : 620;
        add(o, "ui_fly_duration_ms", cJSON_CreateNumber((double)(ms ? ms : 620)));
    }
    add(o, "first_run", cJSON_CreateBool(cfg_bool("first_run", 1)));
    add(o, "skip_assets", cJSON_CreateBool(cfg_bool("skip_assets", 0)));
    add(o, "allow_multi_instance", cJSON_CreateBool(cfg_bool("allow_multi_instance", 0)));
    add(o, "show_hidden_versions", cJSON_CreateBool(cfg_bool("show_hidden_versions", 0)));
    add(o, "export_dir", cfg_or("export_dir", ""));
    add(o, "default_priority", cfg_or("default_priority", "normal"));
    add(o, "global_mods_dir", cfg_or("global_mods_dir", ""));
    {
        cJSON *v = config_get("instances_dir");
        char s[PYMCL_PATH] = ".minecraft";
        if (py_truthy(v)) py_str(v, s, sizeof(s));
        add(o, "instances_dir", cJSON_CreateString(s));
    }
    add(o, "ui_nav_order", py_list(config_get("ui_nav_order")));
    add(o, "ui_nav_pinned", py_list(config_get("ui_nav_pinned")));
    add(o, "ui_nav_hidden", py_list(config_get("ui_nav_hidden")));
    add(o, "ui_nav_style", cfg_or("ui_nav_style", ""));
    add(o, "ui_nav_defaults", cfg_or("ui_nav_defaults", ""));
    add(o, "ui_nav_groups", nav_groups(config_get("ui_nav_groups")));
    add(o, "ui_section_members", nav_members(config_get("ui_section_members")));
    {
        cJSON *v = config_get("ui_sidebar_width");
        add(o, "ui_sidebar_width", cJSON_CreateNumber((double)(py_truthy(v) ? py_int_or(v, 0) : 0)));
    }
    return o;
}
