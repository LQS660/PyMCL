#include "pymcl.h"

/* 启动页布局的 RPC（get_layout / save_layout / *_layout_profile / import_layout /
 * reset_layout），逐条对齐 mclauncher/ui_layout.py 与 bridge/api.py 里的同名方法。
 *
 * 之前这几个方法在 C 桥里全走 Python 一次性回落：画布每拖一下就起一个 python
 * 进程写一次 config.json，慢，而且没装 Python 的机器上布局根本存不下来。
 * 数据形状与 Python 侧完全一致（同一份 config.json 的 ui_layout / ui_layouts /
 * ui_layout_profile），三端在哪边拖好另一边打开就是同一个。 */

#define LAYOUT_VERSION 1

static const struct { const char *type; int w, h; } k_min_size[] = {
    {"banner", 340, 125}, {"config", 330, 300}, {"log", 260, 180}, {"news", 220, 180},
    {"quick", 220, 150}, {"notes", 180, 130}, {"playtime", 220, 130}, {"tasks", 220, 130},
    {"skin", 160, 200},
};

static int known_type(const char *t) {
    if (!t) return 0;
    for (size_t i = 0; i < sizeof(k_min_size) / sizeof(k_min_size[0]); i++)
        if (strcmp(k_min_size[i].type, t) == 0) return 1;
    return 0;
}

static double clamp01(double v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

static double jnum(cJSON *o, const char *k, double def) {
    cJSON *v = o ? cJSON_GetObjectItem(o, k) : NULL;
    if (cJSON_IsNumber(v)) return v->valuedouble;
    if (cJSON_IsString(v) && v->valuestring && v->valuestring[0]) return atof(v->valuestring);
    return def;
}

static const char *jstr(cJSON *o, const char *k, const char *def) {
    const char *s = o ? cJSON_GetStringValue(cJSON_GetObjectItem(o, k)) : NULL;
    return s ? s : def;
}

static cJSON *item_new(const char *id, const char *type, double x, double y, double w, double h,
                       int z, int hidden, cJSON *settings) {
    cJSON *it = cJSON_CreateObject();
    cJSON_AddStringToObject(it, "id", id ? id : "");
    cJSON_AddStringToObject(it, "type", type ? type : "notes");
    cJSON_AddNumberToObject(it, "x", clamp01(x));
    cJSON_AddNumberToObject(it, "y", clamp01(y));
    cJSON_AddNumberToObject(it, "w", w < 0.04 ? 0.04 : (w > 1 ? 1 : w));
    cJSON_AddNumberToObject(it, "h", h < 0.04 ? 0.04 : (h > 1 ? 1 : h));
    cJSON_AddNumberToObject(it, "z", z);
    cJSON_AddBoolToObject(it, "hidden", hidden);
    cJSON_AddItemToObject(it, "settings", cJSON_IsObject(settings) ? cJSON_Duplicate(settings, 1) : cJSON_CreateObject());
    return it;
}

/* LayoutItem.from_dict：`or` 语义——0 / 空 / 缺省都回默认值 */
static cJSON *item_from_dict(cJSON *row) {
    const char *type = jstr(row, "type", "");
    double w = jnum(row, "w", 0), h = jnum(row, "h", 0);
    return item_new(jstr(row, "id", ""), type[0] ? type : "notes",
                    jnum(row, "x", 0), jnum(row, "y", 0),
                    w == 0 ? 0.3 : w, h == 0 ? 0.3 : h,
                    (int)jnum(row, "z", 0),
                    cJSON_IsTrue(cJSON_GetObjectItem(row, "hidden")),
                    cJSON_GetObjectItem(row, "settings"));
}

static int cmp_z(const void *a, const void *b) {
    cJSON *ia = *(cJSON *const *)a, *ib = *(cJSON *const *)b;
    double za = jnum(ia, "z", 0), zb = jnum(ib, "z", 0);
    return za < zb ? -1 : (za > zb ? 1 : 0);
}

/* LayoutDoc.normalize：修 id 重复 / z 序空洞 */
static void doc_normalize(cJSON *doc) {
    cJSON *items = cJSON_GetObjectItem(doc, "items");
    if (!cJSON_IsArray(items)) return;
    int n = cJSON_GetArraySize(items);
    if (n <= 0) return;
    cJSON **arr = (cJSON **)calloc((size_t)n, sizeof(cJSON *));
    int i = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, items) {
        char base[128], nid[160];
        const char *id = jstr(it, "id", "");
        if (id[0]) snprintf(base, sizeof(base), "%s", id);
        else snprintf(base, sizeof(base), "%s-%d", jstr(it, "type", "notes"), i);
        snprintf(nid, sizeof(nid), "%s", base);
        for (int k = 2;; k++) {
            int dup = 0;
            for (int j = 0; j < i; j++)
                if (strcmp(jstr(arr[j], "id", ""), nid) == 0) { dup = 1; break; }
            if (!dup) break;
            snprintf(nid, sizeof(nid), "%s-%d", base, k);
        }
        cJSON_DeleteItemFromObject(it, "id");
        cJSON_AddStringToObject(it, "id", nid);
        arr[i++] = it;
    }
    /* 稳定排序：先按原序编号，z 相同时保持原来的相对位置 */
    for (int a = 1; a < n; a++) {
        cJSON *cur = arr[a];
        int b = a - 1;
        while (b >= 0 && cmp_z(&arr[b], &cur) > 0) { arr[b + 1] = arr[b]; b--; }
        arr[b + 1] = cur;
    }
    for (int z = 0; z < n; z++) {
        cJSON_DeleteItemFromObject(arr[z], "z");
        cJSON_AddNumberToObject(arr[z], "z", z);
    }
    free(arr);
}

static cJSON *doc_new(int grid) {
    cJSON *doc = cJSON_CreateObject();
    cJSON_AddNumberToObject(doc, "version", LAYOUT_VERSION);
    cJSON_AddNumberToObject(doc, "grid", grid < 0 ? 0 : grid);
    cJSON_AddItemToObject(doc, "items", cJSON_CreateArray());
    return doc;
}

/* ui_layout.default_doc：横幅通栏 + 左侧启动配置 */
static cJSON *default_doc(void) {
    cJSON *doc = doc_new(8);
    cJSON *items = cJSON_GetObjectItem(doc, "items");
    cJSON_AddItemToArray(items, item_new("banner-main", "banner", 0.0, 0.0, 1.0, 0.30, 0, 0, NULL));
    cJSON_AddItemToArray(items, item_new("config-main", "config", 0.0, 0.315, 0.315, 0.685, 1, 0, NULL));
    return doc;
}

/* LayoutDoc.from_dict：宽松——不是文档就回默认；显式空列表照留 */
static cJSON *doc_from_dict(cJSON *data) {
    if (!cJSON_IsObject(data)) return default_doc();
    cJSON *g = cJSON_GetObjectItem(data, "grid");
    int grid = 8;
    if (cJSON_IsNumber(g)) grid = (int)g->valuedouble;
    else if (cJSON_IsString(g) && g->valuestring && g->valuestring[0]) grid = atoi(g->valuestring);
    cJSON *doc = doc_new(grid);
    cJSON *items = cJSON_GetObjectItem(doc, "items");
    cJSON *raw = cJSON_GetObjectItem(data, "items");
    if (cJSON_IsArray(raw)) {
        cJSON *row;
        cJSON_ArrayForEach(row, raw) {
            if (cJSON_IsObject(row)) cJSON_AddItemToArray(items, item_from_dict(row));
        }
    }
    if (cJSON_GetArraySize(items) == 0 && !cJSON_IsArray(raw)) {
        cJSON_Delete(doc);
        return default_doc();
    }
    doc_normalize(doc);
    return doc;
}

/* ui_layout.parse_doc：严格——结构不对返回 NULL，未知卡片类型丢弃 */
static cJSON *parse_doc(cJSON *data) {
    if (!cJSON_IsObject(data)) return NULL;
    cJSON *raw = cJSON_GetObjectItem(data, "items");
    if (!cJSON_IsArray(raw) || cJSON_GetArraySize(raw) == 0) return NULL;
    cJSON *doc = doc_from_dict(data);
    cJSON *items = cJSON_GetObjectItem(doc, "items");
    for (int i = cJSON_GetArraySize(items) - 1; i >= 0; i--) {
        cJSON *it = cJSON_GetArrayItem(items, i);
        if (!known_type(jstr(it, "type", ""))) cJSON_DeleteItemFromArray(items, i);
    }
    if (cJSON_GetArraySize(items) == 0) {
        cJSON_Delete(doc);
        return NULL;
    }
    return doc;
}

static cJSON *min_sizes(void) {
    cJSON *o = cJSON_CreateObject();
    for (size_t i = 0; i < sizeof(k_min_size) / sizeof(k_min_size[0]); i++) {
        cJSON *pair = cJSON_CreateArray();
        cJSON_AddItemToArray(pair, cJSON_CreateNumber(k_min_size[i].w));
        cJSON_AddItemToArray(pair, cJSON_CreateNumber(k_min_size[i].h));
        cJSON_AddItemToObject(o, k_min_size[i].type, pair);
    }
    return o;
}

/* ---- 持久化：直接读写 config.json 的三个键，与 Python 侧同一份 ---- */

static void cfg_put(const char *key, cJSON *value_owned_or_null) {
    cJSON *cfg = config_obj();
    if (!cfg) { if (value_owned_or_null) cJSON_Delete(value_owned_or_null); return; }
    cJSON_DeleteItemFromObject(cfg, key);
    cJSON_AddItemToObject(cfg, key, value_owned_or_null ? value_owned_or_null : cJSON_CreateNull());
}

static const char *active_profile(void) { return config_str("ui_layout_profile", ""); }

static cJSON *profiles_obj(void) {
    cJSON *cfg = config_obj();
    cJSON *p = cfg ? cJSON_GetObjectItem(cfg, "ui_layouts") : NULL;
    return cJSON_IsObject(p) ? p : NULL;
}

static cJSON *ensure_profiles_obj(void) {
    cJSON *p = profiles_obj();
    if (p) return p;
    cfg_put("ui_layouts", cJSON_CreateObject());
    return profiles_obj();
}

static cJSON *load_active_doc(void) {
    cJSON *cfg = config_obj();
    cJSON *raw = cfg ? cJSON_GetObjectItem(cfg, "ui_layout") : NULL;
    if (!cJSON_IsObject(raw)) return default_doc();
    return doc_from_dict(raw);
}

static int cmp_str(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

static cJSON *layout_state(void) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddItemToObject(o, "doc", load_active_doc());
    cJSON_AddStringToObject(o, "profile", active_profile());
    cJSON *names = cJSON_CreateArray();
    cJSON *profiles = profiles_obj();
    if (profiles) {
        int n = 0;
        cJSON *it;
        cJSON_ArrayForEach(it, profiles) n++;
        if (n > 0) {
            const char **keys = (const char **)calloc((size_t)n, sizeof(char *));
            int i = 0;
            cJSON_ArrayForEach(it, profiles) keys[i++] = it->string ? it->string : "";
            qsort(keys, (size_t)n, sizeof(char *), cmp_str);
            for (i = 0; i < n; i++) cJSON_AddItemToArray(names, cJSON_CreateString(keys[i]));
            free(keys);
        }
    }
    cJSON_AddItemToObject(o, "profiles", names);
    cJSON_AddItemToObject(o, "default", default_doc());
    cJSON_AddItemToObject(o, "min_sizes", min_sizes());
    return o;
}

static void reset_active(void) {
    cfg_put("ui_layout", NULL);
    cfg_put("ui_layout_profile", cJSON_CreateString(""));
}

static void trim_copy(char *out, size_t n, const char *s) {
    if (!s) { out[0] = 0; return; }
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
    snprintf(out, n, "%s", s);
    size_t len = strlen(out);
    while (len > 0 && (out[len - 1] == ' ' || out[len - 1] == '\t' || out[len - 1] == '\r' || out[len - 1] == '\n'))
        out[--len] = 0;
}

cJSON *rpc_layout_call(const char *method, cJSON *params, int *handled) {
    if (handled) *handled = 0;
    if (!method || !strstr(method, "layout")) return NULL;

    if (strcmp(method, "get_layout") == 0) {
        if (handled) *handled = 1;
        return layout_state();
    }
    if (strcmp(method, "save_layout") == 0) {
        if (handled) *handled = 1;
        cJSON *parsed = parse_doc(cJSON_GetObjectItem(params, "doc"));
        if (!parsed) { pymcl_set_error("不是有效的布局文档"); return NULL; }
        const char *name = active_profile();
        if (name && name[0]) {
            cJSON *profiles = ensure_profiles_obj();
            if (profiles) {
                cJSON_DeleteItemFromObject(profiles, name);
                cJSON_AddItemToObject(profiles, name, cJSON_Duplicate(parsed, 1));
            }
        }
        cfg_put("ui_layout", parsed);
        config_save();
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "profile", name ? name : "");
        return o;
    }
    if (strcmp(method, "save_layout_profile") == 0) {
        if (handled) *handled = 1;
        char name[256];
        trim_copy(name, sizeof(name), jstr(params, "name", ""));
        if (!name[0]) { pymcl_set_error("方案名称不能为空"); return NULL; }
        cJSON *raw = cJSON_GetObjectItem(params, "doc");
        cJSON *doc;
        if (!raw || cJSON_IsNull(raw)) doc = load_active_doc();
        else {
            doc = parse_doc(raw);
            if (!doc) { pymcl_set_error("不是有效的布局文档"); return NULL; }
        }
        cJSON *profiles = ensure_profiles_obj();
        if (profiles) {
            cJSON_DeleteItemFromObject(profiles, name);
            cJSON_AddItemToObject(profiles, name, cJSON_Duplicate(doc, 1));
        }
        cfg_put("ui_layout_profile", cJSON_CreateString(name));
        cfg_put("ui_layout", doc);
        config_save();
        return layout_state();
    }
    if (strcmp(method, "activate_layout_profile") == 0) {
        if (handled) *handled = 1;
        char name[256];
        trim_copy(name, sizeof(name), jstr(params, "name", ""));
        cJSON *profiles = profiles_obj();
        cJSON *doc = (name[0] && profiles) ? cJSON_GetObjectItem(profiles, name) : NULL;
        if (!name[0] || !cJSON_IsObject(doc)) {
            /* 空名 = 回内置默认；指名的方案不存在也回默认并修正记录，避免死键 */
            reset_active();
        } else {
            cfg_put("ui_layout", cJSON_Duplicate(doc, 1));
            cfg_put("ui_layout_profile", cJSON_CreateString(name));
        }
        config_save();
        return layout_state();
    }
    if (strcmp(method, "delete_layout_profile") == 0) {
        if (handled) *handled = 1;
        char name[256];
        trim_copy(name, sizeof(name), jstr(params, "name", ""));
        cJSON *profiles = profiles_obj();
        if (!profiles || !cJSON_GetObjectItem(profiles, name)) {
            pymcl_set_error("布局方案「%s」不存在", name);
            return NULL;
        }
        cJSON_DeleteItemFromObject(profiles, name);
        if (strcmp(active_profile(), name) == 0) reset_active();
        config_save();
        return layout_state();
    }
    if (strcmp(method, "reset_layout") == 0) {
        if (handled) *handled = 1;
        reset_active();
        config_save();
        return layout_state();
    }
    if (strcmp(method, "import_layout") == 0) {
        if (handled) *handled = 1;
        cJSON *parsed = parse_doc(cJSON_GetObjectItem(params, "doc"));
        if (!parsed) { pymcl_set_error("不是有效的布局文件"); return NULL; }
        cfg_put("ui_layout", parsed);
        config_save();
        return layout_state();
    }
    return NULL;
}
