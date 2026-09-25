#include "pymcl.h"
#include <ctype.h>

/* 存档 / 截图 / 全局模组 / 主题包 / 清理 / 皮肤：mclauncher 下 saves.py、global_mods.py、
   themes.py、cleaner.py、skin.py 的移植（GOAL 附录 A 的 M1）。 */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

static cJSON *param(cJSON *o, const char *k) { return cJSON_GetObjectItemCaseSensitive(o, k); }

static void emit_ui_changed(sse_emit_fn emit) {
    if (emit) emit("ui_changed", cJSON_CreateObject());
}

static int is_file(const char *p) { return pymcl_file_exists(p) && !pymcl_dir_exists(p); }

/* _safe_child：只允许 folder 的直接子项 */
static int safe_child(const char *folder, const char *name, const char *what, char *out, size_t n) {
    if (!name || !name[0] || strcmp(name, ".") == 0 || strcmp(name, "..") == 0 || strpbrk(name, "\\/") ||
        (isalpha((unsigned char)name[0]) && name[1] == ':')) {
        pymcl_set_error("非法%s名: %s", what, name ? name : "");
        return -1;
    }
    pymcl_path_join(out, n, folder, name);
    return 0;
}

/* saves._game_dir：给了版本就按它的隔离档位找游戏目录 */
static int game_dir(const char *inst, const char *version, char *out, size_t n) {
    char ip[PYMCL_PATH];
    if (instance_open(inst, ip, sizeof(ip)) != 0) return -1;
    if (version && version[0]) {
        cJSON *s = version_settings_load(inst, version);
        const char *iso = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(s, "isolation"));
        if (iso && (!strcmp(iso, "all") || !strcmp(iso, "saves") || !strcmp(iso, "mods"))) {
            char vd[PYMCL_PATH];
            instance_versions_dir(inst, vd, sizeof(vd));
            pymcl_path_join(out, n, vd, version);
        } else {
            snprintf(out, n, "%s", ip);
        }
        cJSON_Delete(s);
    } else {
        snprintf(out, n, "%s", ip);
    }
    return 0;
}

static long long dir_size(const char *dir, int limit) {
    cJSON *files = pymcl_walk_files(dir);
    long long total = 0;
    int n = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, files) {
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), dir, it->valuestring);
        total += pymcl_file_size(p);
        if (++n >= limit) break;
    }
    cJSON_Delete(files);
    return total;
}

/* Path.suffix：最后一段里最后一个点起（点在开头不算） */
static const char *path_suffix(const char *name) {
    const char *dot = strrchr(name, '.');
    if (!dot || dot == name) return "";
    return dot;
}

static void open_path(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    if (w) ShellExecuteW(NULL, L"open", w, NULL, NULL, SW_SHOWNORMAL);
    free(w);
}

/* 按 mtime 降序的稳定排序（Python sort 是稳定的，同 mtime 保持原顺序） */
typedef struct { cJSON *row; long long mtime; int idx; } mrow;
static int cmp_mrow(const void *a, const void *b) {
    const mrow *x = (const mrow *)a, *y = (const mrow *)b;
    if (x->mtime != y->mtime) return x->mtime < y->mtime ? 1 : -1;
    return x->idx - y->idx;
}
static cJSON *sort_by_mtime_desc(cJSON *rows) {
    int n = cJSON_GetArraySize(rows);
    mrow *m = (mrow *)calloc((size_t)(n ? n : 1), sizeof(mrow));
    cJSON *out = cJSON_CreateArray();
    if (!m) return rows;
    int i = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, rows) {
        m[i].row = it;
        m[i].mtime = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(it, "mtime"));
        m[i].idx = i;
        i++;
    }
    qsort(m, (size_t)n, sizeof(mrow), cmp_mrow);
    for (i = 0; i < n; i++) cJSON_AddItemToArray(out, cJSON_Duplicate(m[i].row, 1));
    free(m);
    cJSON_Delete(rows);
    return out;
}

static cJSON *file_row(const char *dir, const char *name) {
    char p[PYMCL_PATH];
    pymcl_path_join(p, sizeof(p), dir, name);
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "name", name);
    cJSON_AddStringToObject(r, "path", p);
    cJSON_AddNumberToObject(r, "bytes", (double)pymcl_file_size(p));
    cJSON_AddNumberToObject(r, "mtime", (double)pymcl_file_mtime(p));
    return r;
}

/* _STAMP_RE = -(\d{8}-\d{6})$，去掉备份文件名末尾的时间戳 */
static void strip_stamp(const char *stem, char *out, size_t n) {
    snprintf(out, n, "%s", stem);
    size_t len = strlen(out);
    if (len < 16) return;
    const char *t = out + len - 16;
    if (t[0] != '-' || t[9] != '-') return;
    for (int i = 1; i < 16; i++) if (i != 9 && !isdigit((unsigned char)t[i])) return;
    out[len - 16] = 0;
}

static int zip_dir(const char *src, const char *top, const char *out_path) {
    pymcl_zipw *z = pymcl_zipw_open(out_path);
    if (!z) return -1;
    cJSON *files = pymcl_walk_files(src);
    cJSON *it;
    cJSON_ArrayForEach(it, files) {
        char p[PYMCL_PATH], arc[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), src, it->valuestring);
        pymcl_path_join(arc, sizeof(arc), top, it->valuestring);
        if (pymcl_zipw_add_file(z, p, arc, 6) != 0) {
            cJSON_Delete(files);
            pymcl_zipw_abort(z);
            return -1;
        }
    }
    cJSON_Delete(files);
    return pymcl_zipw_close(z);
}

/* ---------- 全局模组 global_mods.py ---------- */

static void global_mods_root(char *out, size_t n) {
    char custom[PYMCL_PATH] = "";
    cJSON *v = config_get("global_mods_dir");
    if (py_truthy(v)) py_str(v, custom, sizeof(custom));
    char *s = custom;
    while (*s && isspace((unsigned char)*s)) s++;
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    if (s[0]) pymcl_py_path(s, out, n);
    else pymcl_path_join3(out, n, g_root, "shared", "mods");
}

/* global_mods._link_file：已存在就跳过；先试符号链接（管理员 / 开发模式可用），
   失败退回复制。放不进去只是没模组，不该连启动命令都失败 */
int global_mods_apply(const char *game_mods_dir) {
    char src[PYMCL_PATH];
    global_mods_root(src, sizeof(src));
    if (!pymcl_dir_exists(src)) return 0;
    pymcl_ensure_dir(game_mods_dir);
    int n = 0;
    cJSON *names = pymcl_list_dir(src, 0, 1);
    cJSON *it;
    cJSON_ArrayForEach(it, names) {
        const char *name = cJSON_GetStringValue(it);
        if (!name || !pymcl_endswith(name, ".jar")) continue;
        char dest[PYMCL_PATH], file[PYMCL_PATH];
        pymcl_path_join(dest, sizeof(dest), game_mods_dir, name);
        pymcl_path_join(file, sizeof(file), src, name);
        if (pymcl_path_exists(dest)) continue;   /* 已链接 / 游戏目录已有同名模组 */
        wchar_t *wd = pymcl_u8_to_wide(dest);
        wchar_t *ws = pymcl_u8_to_wide(file);
        int linked = 0;
        if (wd && ws) linked = CreateSymbolicLinkW(wd, ws, 0x2) != 0;  /* SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE */
        free(wd);
        free(ws);
        if (!linked) pymcl_copy_file(file, dest);
        n++;
    }
    cJSON_Delete(names);
    return n;
}

/* ---------- 主题包 themes.py ---------- */

static void themes_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "themes");
    pymcl_ensure_dir(out);
}

/* _sanitize：字母数字（含中文等）和 " _-" 原样，其余换成 _，再 strip */
static void theme_sanitize(const char *name, char *out, size_t n) {
    wchar_t *w = pymcl_u8_to_wide(name ? name : "");
    if (!w) { snprintf(out, n, "untitled"); return; }
    for (wchar_t *p = w; *p; p++) {
        if (!(IsCharAlphaNumericW(*p) || *p == L' ' || *p == L'_' || *p == L'-')) *p = L'_';
    }
    char *u = pymcl_wide_to_u8(w);
    free(w);
    char *s = u ? u : "";
    while (*s && isspace((unsigned char)*s)) s++;
    snprintf(out, n, "%s", s);
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
    free(u);
    if (!out[0]) snprintf(out, n, "untitled");
}

static void theme_path(const char *name, char *out, size_t n) {
    char d[PYMCL_PATH], safe[512], fn[600];
    themes_dir(d, sizeof(d));
    theme_sanitize(name, safe, sizeof(safe));
    snprintf(fn, sizeof(fn), "%s.json", safe);
    pymcl_path_join(out, n, d, fn);
}

/* CONFIG.get(key, default) 的原值 */
static cJSON *cfg_or_default(const char *key, cJSON *def) {
    cJSON *v = config_get(key);
    if (v) { cJSON_Delete(def); return cJSON_Duplicate(v, 1); }
    return def;
}

static cJSON *current_theme(void) {
    cJSON *t = cJSON_CreateObject();
    cJSON_AddStringToObject(t, "name", "当前主题");
    cJSON_AddItemToObject(t, "theme_color", cfg_or_default("theme_color", cJSON_CreateString("#2E9B6B")));
    cJSON_AddBoolToObject(t, "ui_dark", py_truthy(config_get("ui_dark")));
    cJSON_AddItemToObject(t, "ui_background", cfg_or_default("ui_background", cJSON_CreateString("")));
    cJSON_AddItemToObject(t, "ui_sidebar_opacity", cfg_or_default("ui_sidebar_opacity", cJSON_CreateNumber(100)));
    cJSON_AddItemToObject(t, "ui_background_blur", cfg_or_default("ui_background_blur", cJSON_CreateNumber(0)));
    cJSON_AddItemToObject(t, "ui_background_dim", cfg_or_default("ui_background_dim", cJSON_CreateNumber(0)));
    cJSON_AddItemToObject(t, "ui_background_folder", cfg_or_default("ui_background_folder", cJSON_CreateString("")));
    cJSON_AddItemToObject(t, "ui_background_shuffle", cfg_or_default("ui_background_shuffle", cJSON_CreateFalse()));
    cJSON_AddItemToObject(t, "ui_background_interval", cfg_or_default("ui_background_interval", cJSON_CreateNumber(10)));
    cJSON_AddItemToObject(t, "window_mode", cfg_or_default("window_mode", cJSON_CreateString("window")));
    cJSON_AddItemToObject(t, "custom_homepage", cfg_or_default("custom_homepage", cJSON_CreateString("")));
    cJSON_AddItemToObject(t, "homepage_mode", cfg_or_default("homepage_mode", cJSON_CreateString("news")));
    return t;
}

static void str_of(cJSON *v, char *out, size_t n) {
    out[0] = 0;
    if (py_truthy(v)) py_str(v, out, n);
}

/* config.push_background_history：返回新的两个栈（不落盘） */
static void push_bg_history(const char *old_image, const char *old_folder, cJSON **images, cJSON **folders) {
    *images = cJSON_CreateArray();
    *folders = cJSON_CreateArray();
    cJSON *it;
    cJSON *ri = config_get("ui_background_history"), *rf = config_get("ui_background_folder_history");
    if (cJSON_IsArray(ri)) cJSON_ArrayForEach(it, ri) if (cJSON_IsString(it)) cJSON_AddItemToArray(*images, cJSON_CreateString(it->valuestring));
    if (cJSON_IsArray(rf)) cJSON_ArrayForEach(it, rf) if (cJSON_IsString(it)) cJSON_AddItemToArray(*folders, cJSON_CreateString(it->valuestring));
    int ni = cJSON_GetArraySize(*images), nf = cJSON_GetArraySize(*folders);
    if (nf != ni) {
        cJSON *f = cJSON_CreateArray();
        for (int i = 0; i < ni; i++) {
            cJSON *s = i < nf ? cJSON_GetArrayItem(*folders, i) : NULL;
            cJSON_AddItemToArray(f, cJSON_CreateString(s ? s->valuestring : ""));
        }
        cJSON_Delete(*folders);
        *folders = f;
    }
    if (ni && !strcmp(cJSON_GetArrayItem(*images, ni - 1)->valuestring, old_image) &&
        !strcmp(cJSON_GetArrayItem(*folders, ni - 1)->valuestring, old_folder))
        return;
    cJSON_AddItemToArray(*images, cJSON_CreateString(old_image));
    cJSON_AddItemToArray(*folders, cJSON_CreateString(old_folder));
    while (cJSON_GetArraySize(*images) > 20) cJSON_DeleteItemFromArray(*images, 0);
    while (cJSON_GetArraySize(*folders) > 20) cJSON_DeleteItemFromArray(*folders, 0);
}

/* ---------- 清理 cleaner.py ---------- */

static cJSON *load_parent_version(const char *id, void *ud) {
    return instance_version_json((const char *)ud, id);
}

static void lower_path(char *s) {
    wchar_t *w = pymcl_u8_to_wide(s);
    if (!w) return;
    CharLowerW(w);
    char *u = pymcl_wide_to_u8(w);
    free(w);
    if (u) { strcpy(s, u); free(u); }
}

static void add_used(cJSON *used, const char *libs, const char *rel) {
    char p[PYMCL_PATH], full[PYMCL_PATH];
    pymcl_path_join(p, sizeof(p), libs, rel);
    pymcl_py_path(p, full, sizeof(full));
    lower_path(full);
    if (!cJSON_GetObjectItemCaseSensitive(used, full)) cJSON_AddTrueToObject(used, full);
}

static void lib_paths(const char *inst, cJSON *used) {
    char libs[PYMCL_PATH];
    instance_libraries_dir(inst, libs, sizeof(libs));
    cJSON *ids = NULL;
    instance_installed_ids(inst, &ids);
    cJSON *v;
    cJSON_ArrayForEach(v, ids) {
        cJSON *vj = instance_version_json(inst, v->valuestring);
        if (!vj) vj = cJSON_CreateObject();
        cJSON *resolved = manifest_resolve_inherits(vj, load_parent_version, (void *)inst);
        cJSON *src = resolved ? resolved : vj;
        cJSON *lib;
        cJSON_ArrayForEach(lib, cJSON_GetObjectItem(src, "libraries")) {
            cJSON *dl = cJSON_GetObjectItem(lib, "downloads");
            cJSON *art = cJSON_GetObjectItem(dl, "artifact");
            const char *path = cJSON_GetStringValue(cJSON_GetObjectItem(art, "path"));
            char mp[PYMCL_PATH];
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(lib, "name"));
            if ((!path || !path[0]) && nm && nm[0] && !py_truthy(cJSON_GetObjectItem(lib, "natives"))) {
                if (pymcl_maven_path(nm, "jar", mp, sizeof(mp)) == 0) path = mp;
            }
            if (path && path[0]) add_used(used, libs, path);
            cJSON *clf;
            cJSON_ArrayForEach(clf, cJSON_GetObjectItem(dl, "classifiers")) {
                const char *cp = cJSON_GetStringValue(cJSON_GetObjectItem(clf, "path"));
                if (cJSON_IsObject(clf) && cp && cp[0]) add_used(used, libs, cp);
            }
        }
        if (resolved && resolved != vj) cJSON_Delete(resolved);
        cJSON_Delete(vj);
    }
    cJSON_Delete(ids);
}

static void stat_rows(cJSON *paths, cJSON **rows, long long *total) {
    *rows = cJSON_CreateArray();
    *total = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, paths) {
        if (!pymcl_file_exists(it->valuestring)) continue;
        long long sz = pymcl_file_size(it->valuestring);
        *total += sz;
        cJSON *r = cJSON_CreateObject();
        cJSON_AddStringToObject(r, "path", it->valuestring);
        cJSON_AddNumberToObject(r, "bytes", (double)sz);
        cJSON_AddItemToArray(*rows, r);
    }
}

static cJSON *cleaner_preview(void) {
    cJSON *lib_files = cJSON_CreateArray(), *parts = cJSON_CreateArray(), *cache_files = cJSON_CreateArray();
    cJSON *used = cJSON_CreateObject(), *seen = cJSON_CreateObject();
    cJSON *names = NULL;
    instance_list(&names);
    cJSON *nm;
    cJSON_ArrayForEach(nm, names) lib_paths(nm->valuestring, used);
    cJSON_ArrayForEach(nm, names) {
        char libs[PYMCL_PATH];
        instance_libraries_dir(nm->valuestring, libs, sizeof(libs));
        if (cJSON_GetObjectItemCaseSensitive(seen, libs)) continue;
        cJSON_AddTrueToObject(seen, libs);
        cJSON *files = pymcl_walk_files(libs);
        cJSON *f;
        cJSON_ArrayForEach(f, files) {
            char p[PYMCL_PATH], low[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), libs, f->valuestring);
            if (!_stricmp(path_suffix(pymcl_basename(p)), ".part")) { cJSON_AddItemToArray(parts, cJSON_CreateString(p)); continue; }
            pymcl_py_path(p, low, sizeof(low));
            lower_path(low);
            if (!cJSON_GetObjectItemCaseSensitive(used, low)) cJSON_AddItemToArray(lib_files, cJSON_CreateString(p));
        }
        cJSON_Delete(files);
    }
    cJSON_Delete(names);
    char cache[PYMCL_PATH];
    pymcl_cache_dir(cache, sizeof(cache));
    if (pymcl_dir_exists(cache)) {
        cJSON *files = pymcl_walk_files(cache);
        cJSON *f;
        cJSON_ArrayForEach(f, files) {
            if (!pymcl_endswith(f->valuestring, ".part")) continue;
            char p[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), cache, f->valuestring);
            cJSON_AddItemToArray(parts, cJSON_CreateString(p));
        }
        cJSON_Delete(files);
        cJSON *top = pymcl_list_dir(cache, 0, 1);
        cJSON_ArrayForEach(f, top) {
            const char *s = f->valuestring;
            if (!_strnicmp(s, "PyMCL-", 6) && pymcl_endswith(s, ".bin")) {
                char p[PYMCL_PATH];
                pymcl_path_join(p, sizeof(p), cache, s);
                cJSON_AddItemToArray(cache_files, cJSON_CreateString(p));
            }
        }
        cJSON_Delete(top);
    }
    cJSON_Delete(used);
    cJSON_Delete(seen);
    cJSON *u, *pr, *cr;
    long long ub, pb, cb;
    stat_rows(lib_files, &u, &ub);
    stat_rows(parts, &pr, &pb);
    stat_rows(cache_files, &cr, &cb);
    cJSON_Delete(lib_files);
    cJSON_Delete(parts);
    cJSON_Delete(cache_files);
    cJSON *o = cJSON_CreateObject();
    int count = cJSON_GetArraySize(u) + cJSON_GetArraySize(pr) + cJSON_GetArraySize(cr);
    cJSON_AddItemToObject(o, "unused_libraries", u);
    cJSON_AddItemToObject(o, "parts", pr);
    cJSON_AddItemToObject(o, "cache", cr);
    cJSON_AddNumberToObject(o, "bytes", (double)(ub + pb + cb));
    cJSON_AddNumberToObject(o, "count", count);
    return o;
}

/* ---------- 皮肤 skin.py ---------- */

static void dashed_hex(const char *uuid, char *out, size_t n) {
    char raw[128], hex[64];
    const char *s = uuid ? uuid : "";
    while (*s && isspace((unsigned char)*s)) s++;
    snprintf(raw, sizeof(raw), "%s", s);
    size_t len = strlen(raw);
    while (len && isspace((unsigned char)raw[len - 1])) raw[--len] = 0;
    size_t h = 0;
    for (const char *p = raw; *p && h < sizeof(hex) - 1; p++) if (*p != '-') hex[h++] = *p;
    hex[h] = 0;
    int ok = h == 32;
    for (size_t i = 0; ok && i < h; i++) if (!isxdigit((unsigned char)hex[i])) ok = 0;
    if (!ok) {
        /* dashed_uuid 认不出就原样返回，外面再去掉连字符 */
        size_t o = 0;
        for (const char *p = raw; *p && o + 1 < n; p++) if (*p != '-') out[o++] = *p;
        out[o] = 0;
        return;
    }
    for (size_t i = 0; i < h; i++) hex[i] = (char)tolower((unsigned char)hex[i]);
    snprintf(out, n, "%s", hex);
}

static void site_origin(const char *api, char *out, size_t n) {
    char raw[1024];
    snprintf(raw, sizeof(raw), "%s", api ? api : "");
    size_t len = strlen(raw);
    while (len && raw[len - 1] == '/') raw[--len] = 0;
    const char *sufs[] = {"/api/yggdrasil", "/yggdrasil"};
    for (int i = 0; i < 2; i++) {
        size_t sl = strlen(sufs[i]);
        if (len >= sl && !strcmp(raw + len - sl, sufs[i])) { raw[len - sl] = 0; snprintf(out, n, "%s", raw); return; }
    }
    char full[1100];
    if (strstr(raw, "://")) snprintf(full, sizeof(full), "%s", raw);
    else snprintf(full, sizeof(full), "https://%s", raw);
    const char *sep = strstr(full, "://");
    const char *host = sep + 3;
    size_t hl = strcspn(host, "/?#");
    if (sep > full && hl > 0) {
        snprintf(out, n, "%.*s://%.*s", (int)(sep - full), full, (int)hl, host);
        return;
    }
    snprintf(out, n, "%s", raw);
}

static void avatar_url(cJSON *acc, char *out, size_t n) {
    char uuid[128], name[512], q[1600], origin[1024];
    dashed_hex(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")), uuid, sizeof(uuid));
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"));
    snprintf(name, sizeof(name), "%s", nm && nm[0] ? nm : "Steve");
    const char *kind = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "type"));
    if (!kind || !kind[0]) kind = "offline";
    const char *api = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "api"));
    if (!strcmp(kind, "authlib") && api && api[0]) {
        site_origin(api, origin, sizeof(origin));
        pymcl_url_quote(name, q, sizeof(q));
        snprintf(out, n, "%s/avatar/%s", origin, q);
        return;
    }
    if (uuid[0] && !strcmp(kind, "microsoft")) {
        snprintf(out, n, "https://crafatar.com/avatars/%s?overlay=true&size=128", uuid);
        return;
    }
    pymcl_url_quote(name, q, sizeof(q));
    snprintf(out, n, "https://mc-heads.net/avatar/%s/128", q);
}

static void body_url(cJSON *acc, char *out, size_t n) {
    char uuid[128], name[512], q[1600], origin[1024];
    dashed_hex(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")), uuid, sizeof(uuid));
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"));
    snprintf(name, sizeof(name), "%s", nm && nm[0] ? nm : "Steve");
    const char *kind = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "type"));
    const char *api = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "api"));
    pymcl_url_quote(name, q, sizeof(q));
    if (kind && !strcmp(kind, "authlib") && api && api[0]) {
        site_origin(api, origin, sizeof(origin));
        snprintf(out, n, "%s/preview/%s", origin, q);
        return;
    }
    if (kind && !strcmp(kind, "microsoft") && uuid[0]) {
        snprintf(out, n, "https://crafatar.com/renders/body/%s?overlay=true&scale=6", uuid);
        return;
    }
    snprintf(out, n, "https://mc-heads.net/body/%s/180", q);
}

static int is_offline_account(const char *s) {
    return !s || !s[0] || !strcmp(s, "离线模式") || !strcmp(s, tr("离线模式"));
}

static cJSON *find_account(cJSON *root, const char *name) {
    cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItem(root, "accounts")) {
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
        if (nm && name && !strcmp(nm, name)) return it;
    }
    return NULL;
}

static void skins_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "skins");
    pymcl_ensure_dir(out);
}

static int png_valid_skin(const unsigned char *d, size_t len, char *err, size_t en) {
    static const unsigned char sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    if (len < 24 || memcmp(d, sig, 8) != 0 || memcmp(d + 12, "IHDR", 4) != 0) {
        snprintf(err, en, "这不是一个有效的 PNG 文件");
        return 0;
    }
    uint32_t w = ((uint32_t)d[16] << 24) | ((uint32_t)d[17] << 16) | ((uint32_t)d[18] << 8) | d[19];
    uint32_t h = ((uint32_t)d[20] << 24) | ((uint32_t)d[21] << 16) | ((uint32_t)d[22] << 8) | d[23];
    if (!(w == 64 && (h == 64 || h == 32))) {
        snprintf(err, en, "皮肤尺寸必须是 64x64 或 64x32，这张是 %ux%u", w, h);
        return 0;
    }
    return 1;
}

static void skin_dest(const char *account_name, char *out, size_t n) {
    char d[PYMCL_PATH], safe[512];
    skins_dir(d, sizeof(d));
    wchar_t *w = pymcl_u8_to_wide(account_name && account_name[0] ? account_name : "player");
    if (w) {
        for (wchar_t *p = w; *p; p++) if (!(IsCharAlphaNumericW(*p) || *p == L'-' || *p == L'_')) *p = L'_';
        char *u = pymcl_wide_to_u8(w);
        snprintf(safe, sizeof(safe), "%s", u && u[0] ? u : "player");
        free(u);
        free(w);
    } else {
        snprintf(safe, sizeof(safe), "player");
    }
    char fn[600];
    snprintf(fn, sizeof(fn), "%s.png", safe);
    pymcl_path_join(out, n, d, fn);
}

/* skin.skin_file_for：只认 skins 目录下的文件名 */
static int skin_file_for(cJSON *acc, char *out, size_t n) {
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_file"));
    char s[512] = "";
    if (nm) {
        while (*nm && isspace((unsigned char)*nm)) nm++;
        snprintf(s, sizeof(s), "%s", nm);
        size_t len = strlen(s);
        while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    }
    if (!s[0]) return 0;
    char d[PYMCL_PATH];
    skins_dir(d, sizeof(d));
    pymcl_path_join(out, n, d, pymcl_basename(s));
    return is_file(out);
}

static const char *skin_model(cJSON *acc) {
    const char *m = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_model"));
    return (m && !_stricmp(m, "slim")) ? "slim" : "classic";
}

/* ---------- 主分发 ---------- */

cJSON *rpc_content_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    int dummy;
    if (!handled) handled = &dummy;
    *handled = 1;
    const char *inst = pstr(params, "instance", "");
    const char *ver = pstr(params, "version", "");

    /* saves.list_saves */
    if (strcmp(method, "list_saves") == 0) {
        char gd[PYMCL_PATH], folder[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(folder, sizeof(folder), gd, "saves");
        cJSON *rows = cJSON_CreateArray();
        if (!pymcl_dir_exists(folder)) return rows;
        cJSON *names = pymcl_list_dir(folder, 1, 1);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            if (it->valuestring[0] == '.') continue;
            char p[PYMCL_PATH], icon[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), folder, it->valuestring);
            pymcl_path_join(icon, sizeof(icon), p, "icon.png");
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "name", it->valuestring);
            cJSON_AddStringToObject(r, "path", p);
            cJSON_AddStringToObject(r, "icon", is_file(icon) ? icon : "");
            cJSON_AddNumberToObject(r, "bytes", (double)dir_size(p, 80));
            cJSON_AddNumberToObject(r, "mtime", (double)pymcl_file_mtime(p));
            cJSON_AddItemToArray(rows, r);
        }
        cJSON_Delete(names);
        return rows;
    }

    /* saves.list_media */
    if (strcmp(method, "list_media") == 0) {
        const char *kind = pstr(params, "kind", "");
        const char *sub = NULL, *exts[4] = {0};
        if (!strcmp(kind, "screenshots")) { sub = "screenshots"; exts[0] = ".png"; exts[1] = ".jpg"; exts[2] = ".jpeg"; }
        else if (!strcmp(kind, "crash-reports")) { sub = "crash-reports"; exts[0] = ".txt"; }
        else if (!strcmp(kind, "logs")) { sub = "logs"; exts[0] = ".log"; exts[1] = ".gz"; exts[2] = ".txt"; }
        char gd[PYMCL_PATH], folder[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        if (!sub) { pymcl_set_error("未知类型: %s", kind); return NULL; }
        pymcl_path_join(folder, sizeof(folder), gd, sub);
        cJSON *rows = cJSON_CreateArray();
        if (!pymcl_dir_exists(folder)) return rows;
        cJSON *names = pymcl_list_dir(folder, 0, 1);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            const char *suf = path_suffix(it->valuestring);
            int ok = 0;
            for (int i = 0; exts[i]; i++) if (!_stricmp(suf, exts[i])) ok = 1;
            if (ok) cJSON_AddItemToArray(rows, file_row(folder, it->valuestring));
        }
        cJSON_Delete(names);
        rows = sort_by_mtime_desc(rows);
        while (cJSON_GetArraySize(rows) > 200) cJSON_DeleteItemFromArray(rows, 200);
        return rows;
    }

    /* saves.list_backups */
    if (strcmp(method, "list_save_backups") == 0) {
        const char *save = pstr(params, "name", "");
        char gd[PYMCL_PATH], folder[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(folder, sizeof(folder), gd, "backups");
        cJSON *rows = cJSON_CreateArray();
        if (!pymcl_dir_exists(folder)) return rows;
        cJSON *names = pymcl_list_dir(folder, 0, 1);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            const char *fn = it->valuestring;
            if (!pymcl_endswith(fn, ".zip")) continue;
            char stem[512], origin[512];
            snprintf(stem, sizeof(stem), "%.*s", (int)(strlen(fn) - 4), fn);
            strip_stamp(stem, origin, sizeof(origin));
            if (save[0] && strcmp(origin, save) != 0) continue;
            char p[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), folder, fn);
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "name", fn);
            cJSON_AddStringToObject(r, "path", p);
            cJSON_AddStringToObject(r, "save", origin);
            cJSON_AddNumberToObject(r, "bytes", (double)pymcl_file_size(p));
            cJSON_AddNumberToObject(r, "mtime", (double)pymcl_file_mtime(p));
            cJSON_AddItemToArray(rows, r);
        }
        cJSON_Delete(names);
        return sort_by_mtime_desc(rows);
    }

    /* saves.delete_save */
    if (strcmp(method, "delete_save") == 0) {
        const char *name = pstr(params, "name", "");
        char gd[PYMCL_PATH], saves[PYMCL_PATH], target[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(saves, sizeof(saves), gd, "saves");
        if (safe_child(saves, name, "存档", target, sizeof(target)) != 0) return NULL;
        if (!pymcl_path_exists(target)) { pymcl_set_error("存档不存在: %s", name); return NULL; }
        pymcl_remove_tree(target);
        return cJSON_CreateNull();
    }

    /* saves.open_save */
    if (strcmp(method, "open_save") == 0) {
        const char *name = pstr(params, "name", "");
        char gd[PYMCL_PATH], folder[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join3(folder, sizeof(folder), gd, "saves", name);
        if (!pymcl_dir_exists(folder)) { pymcl_set_error("存档不存在: %s", name); return NULL; }
        open_path(folder);
        return cJSON_CreateString(folder);
    }

    /* saves.install_datapack_into_save */
    if (strcmp(method, "install_datapack_into_save") == 0) {
        const char *fn = pstr(params, "filename", "");
        const char *save = pstr(params, "save_name", "");
        char ip[PYMCL_PATH], root[PYMCL_PATH], src[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        pymcl_path_join(root, sizeof(root), ip, "datapacks");
        if (safe_child(root, fn, "", src, sizeof(src)) != 0 || !is_file(src)) {
            pymcl_set_error("数据包不存在: %s", fn);
            return NULL;
        }
        char gd[PYMCL_PATH], dest_dir[PYMCL_PATH], dest[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join3(dest_dir, sizeof(dest_dir), gd, "saves", save);
        pymcl_path_join(dest_dir, sizeof(dest_dir), dest_dir, "datapacks");
        pymcl_ensure_dir(dest_dir);
        pymcl_path_join(dest, sizeof(dest), dest_dir, pymcl_basename(src));
        if (pymcl_copy_file(src, dest) != 0) return NULL;
        return cJSON_CreateString(dest);
    }

    /* saves.delete_backup */
    if (strcmp(method, "delete_save_backup") == 0) {
        const char *bn = pstr(params, "backup_name", "");
        char gd[PYMCL_PATH], folder[PYMCL_PATH], archive[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(folder, sizeof(folder), gd, "backups");
        if (safe_child(folder, bn, "备份", archive, sizeof(archive)) != 0) return NULL;
        if (!is_file(archive)) { pymcl_set_error("备份不存在: %s", bn); return NULL; }
        wchar_t *w = pymcl_u8_to_wide(archive);
        DeleteFileW(w);
        free(w);
        emit_ui_changed(emit);
        return cJSON_CreateNull();
    }

    /* saves.restore_backup */
    if (strcmp(method, "restore_save_backup") == 0) {
        const char *bn = pstr(params, "backup_name", "");
        int overwrite = py_truthy(param(params, "overwrite"));
        char gd[PYMCL_PATH], folder[PYMCL_PATH], archive[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(folder, sizeof(folder), gd, "backups");
        if (safe_child(folder, bn, "备份", archive, sizeof(archive)) != 0) return NULL;
        if (!is_file(archive)) { pymcl_set_error("备份不存在: %s", bn); return NULL; }
        char saves_root[PYMCL_PATH];
        pymcl_path_join(saves_root, sizeof(saves_root), gd, "saves");
        pymcl_ensure_dir(saves_root);
        char stem[512], origin[512];
        const char *base = pymcl_basename(archive);
        const char *dot = strrchr(base, '.');
        snprintf(stem, sizeof(stem), "%.*s", dot && dot != base ? (int)(dot - base) : (int)strlen(base), base);
        strip_stamp(stem, origin, sizeof(origin));
        char dest[PYMCL_PATH];
        if (safe_child(saves_root, origin, "存档", dest, sizeof(dest)) != 0) return NULL;
        if (pymcl_path_exists(dest)) {
            if (!overwrite) {
                for (int n = 1; pymcl_path_exists(dest); n++) {
                    char nm[600];
                    if (n > 1) snprintf(nm, sizeof(nm), "%s-还原%d", origin, n);
                    else snprintf(nm, sizeof(nm), "%s-还原", origin);
                    if (safe_child(saves_root, nm, "存档", dest, sizeof(dest)) != 0) return NULL;
                }
            } else {
                pymcl_remove_tree(dest);
            }
        }
        char staging[PYMCL_PATH], sn[64];
        snprintf(sn, sizeof(sn), ".restore-%lld", (long long)time(NULL));
        pymcl_path_join(staging, sizeof(staging), saves_root, sn);
        pymcl_remove_tree(staging);
        pymcl_ensure_dir(staging);
        if (pymcl_extract_zip(archive, staging) != 0) {
            pymcl_remove_tree(staging);
            pymcl_set_error("备份文件损坏: %s", pymcl_error());
            return NULL;
        }
        cJSON *tops = pymcl_list_dir(staging, -1, 1);
        char inner[PYMCL_PATH];
        if (cJSON_GetArraySize(tops) == 0) {
            cJSON_Delete(tops);
            pymcl_remove_tree(staging);
            pymcl_set_error("备份是空的");
            return NULL;
        }
        if (cJSON_GetArraySize(tops) == 1 && pymcl_dir_exists(staging)) {
            pymcl_path_join(inner, sizeof(inner), staging, cJSON_GetArrayItem(tops, 0)->valuestring);
            if (!pymcl_dir_exists(inner)) snprintf(inner, sizeof(inner), "%s", staging);
        } else {
            snprintf(inner, sizeof(inner), "%s", staging);
        }
        cJSON_Delete(tops);
        wchar_t *wa = pymcl_u8_to_wide(inner), *wb = pymcl_u8_to_wide(dest);
        BOOL moved = MoveFileExW(wa, wb, MOVEFILE_COPY_ALLOWED);
        free(wa);
        free(wb);
        pymcl_remove_tree(staging);
        if (!moved) { pymcl_set_error("还原失败: %s", dest); return NULL; }
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "name", pymcl_basename(dest));
        cJSON_AddStringToObject(o, "path", dest);
        cJSON_AddStringToObject(o, "from", base);
        emit_ui_changed(emit);
        return o;
    }

    /* saves.export_save */
    if (strcmp(method, "export_save") == 0) {
        const char *name = pstr(params, "name", "");
        const char *destp = pstr(params, "dest", "");
        char gd[PYMCL_PATH], saves[PYMCL_PATH], src[PYMCL_PATH];
        if (game_dir(inst, ver, gd, sizeof(gd)) != 0) return NULL;
        pymcl_path_join(saves, sizeof(saves), gd, "saves");
        if (safe_child(saves, name, "存档", src, sizeof(src)) != 0) return NULL;
        if (!pymcl_dir_exists(src)) { pymcl_set_error("存档不存在: %s", name); return NULL; }
        char out[PYMCL_PATH];
        pymcl_py_path(destp, out, sizeof(out));
        if (pymcl_dir_exists(out)) {
            char fn[600];
            snprintf(fn, sizeof(fn), "%s.zip", pymcl_basename(src));
            pymcl_path_join(out, sizeof(out), out, fn);
        }
        if (_stricmp(path_suffix(pymcl_basename(out)), ".zip") != 0) {
            char *base = (char *)pymcl_basename(out);
            char *dot = strrchr(base, '.');
            if (dot && dot != base) *dot = 0;
            strncat(out, ".zip", sizeof(out) - strlen(out) - 1);
        }
        if (zip_dir(src, pymcl_basename(src), out) != 0) return NULL;
        return cJSON_CreateString(out);
    }

    /* BackendAPI.open_media：crash.open_path，存在才打开 */
    if (strcmp(method, "open_media") == 0) {
        const char *p = pstr(params, "path", "");
        if (p[0] && pymcl_path_exists(p)) { open_path(p); return cJSON_CreateTrue(); }
        return cJSON_CreateFalse();
    }

    /* BackendAPI.open_mods_folder */
    if (strcmp(method, "open_mods_folder") == 0) {
        char ip[PYMCL_PATH], folder[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        if (ver[0]) {
            char gd[PYMCL_PATH];
            game_dir(inst, ver, gd, sizeof(gd));
            pymcl_path_join(folder, sizeof(folder), gd, "mods");
        } else {
            pymcl_path_join(folder, sizeof(folder), ip, "mods");
        }
        pymcl_ensure_dir(folder);
        open_path(folder);
        return cJSON_CreateString(folder);
    }

    /* global_mods.list_entries / set_enabled */
    if (strcmp(method, "list_global_mods") == 0) {
        char d[PYMCL_PATH];
        global_mods_root(d, sizeof(d));
        cJSON *rows = cJSON_CreateArray();
        if (!pymcl_dir_exists(d)) return rows;
        cJSON *names = pymcl_list_dir(d, 0, 1);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            const char *fn = it->valuestring;
            int en;
            if (pymcl_endswith(fn, ".jar")) en = 1;
            else if (pymcl_endswith(fn, ".jar.disabled") || pymcl_endswith(fn, ".disabled")) en = 0;
            else continue;
            char p[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), d, fn);
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "filename", fn);
            cJSON_AddBoolToObject(r, "enabled", en);
            cJSON_AddNumberToObject(r, "bytes", (double)pymcl_file_size(p));
            cJSON_AddItemToArray(rows, r);
        }
        cJSON_Delete(names);
        return rows;
    }
    if (strcmp(method, "set_global_mod_enabled") == 0) {
        const char *fn = pstr(params, "filename", "");
        int enabled = py_truthy(param(params, "enabled"));
        char d[PYMCL_PATH], p[PYMCL_PATH];
        global_mods_root(d, sizeof(d));
        pymcl_path_join(p, sizeof(p), d, fn);
        if (!is_file(p)) { pymcl_set_error("%s", fn); return NULL; }
        char name[512], dest[PYMCL_PATH], dn[512];
        snprintf(name, sizeof(name), "%s", pymcl_basename(p));
        size_t len = strlen(name);
        if (enabled) {
            if (!pymcl_endswith(name, ".disabled")) return cJSON_CreateString(name);
            snprintf(dn, sizeof(dn), "%.*s", (int)(len - 9), name);
            pymcl_path_join(dest, sizeof(dest), d, dn);
            if (pymcl_path_exists(dest)) { pymcl_set_error("启用失败，已存在: %s", dn); return NULL; }
        } else {
            if (pymcl_endswith(name, ".disabled")) return cJSON_CreateString(name);
            snprintf(dn, sizeof(dn), "%s.disabled", name);
            pymcl_path_join(dest, sizeof(dest), d, dn);
            if (pymcl_path_exists(dest)) { pymcl_set_error("禁用失败，已存在: %s", dn); return NULL; }
        }
        wchar_t *wa = pymcl_u8_to_wide(p), *wb = pymcl_u8_to_wide(dest);
        BOOL ok = MoveFileW(wa, wb);
        free(wa);
        free(wb);
        if (!ok) { pymcl_set_error("重命名失败: %s", name); return NULL; }
        return cJSON_CreateString(dn);
    }

    /* themes.* */
    if (strcmp(method, "list_themes") == 0) {
        char d[PYMCL_PATH];
        themes_dir(d, sizeof(d));
        cJSON *out = cJSON_CreateArray();
        cJSON *names = pymcl_list_dir(d, -1, 1);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            const char *fn = it->valuestring;
            if (_stricmp(path_suffix(fn), ".json") != 0) continue;
            char p[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), d, fn);
            cJSON *data = pymcl_read_json(p);
            if (!cJSON_IsObject(data)) { cJSON_Delete(data); continue; }
            char stem[512];
            snprintf(stem, sizeof(stem), "%.*s", (int)(strlen(fn) - 5), fn);
            cJSON *r = cJSON_CreateObject();
            cJSON *nm = cJSON_GetObjectItemCaseSensitive(data, "name");
            cJSON_AddItemToObject(r, "name", nm ? cJSON_Duplicate(nm, 1) : cJSON_CreateString(stem));
            cJSON_AddStringToObject(r, "file", fn);
            cJSON *tc = cJSON_GetObjectItemCaseSensitive(data, "theme_color");
            cJSON_AddItemToObject(r, "theme_color", tc ? cJSON_Duplicate(tc, 1) : cJSON_CreateString("#2E9B6B"));
            cJSON_AddBoolToObject(r, "ui_dark", py_truthy(cJSON_GetObjectItemCaseSensitive(data, "ui_dark")));
            cJSON_AddItemToArray(out, r);
            cJSON_Delete(data);
        }
        cJSON_Delete(names);
        return out;
    }
    if (strcmp(method, "save_theme") == 0) {
        const char *name = pstr(params, "name", "");
        cJSON *t = current_theme();
        cJSON_ReplaceItemInObject(t, "name", cJSON_CreateString(name));
        char p[PYMCL_PATH];
        theme_path(name, p, sizeof(p));
        pymcl_write_json(p, t);
        return t;
    }
    if (strcmp(method, "load_theme") == 0) {
        const char *name = pstr(params, "name", "");
        char p[PYMCL_PATH];
        theme_path(name, p, sizeof(p));
        if (!is_file(p)) { pymcl_set_error("主题包不存在: %s", name); return NULL; }
        cJSON *t = pymcl_read_json(p);
        if (!t) t = cJSON_CreateObject();
        if (!cJSON_IsObject(t)) { cJSON_Delete(t); pymcl_set_error("主题包数据损坏: %s", name); return NULL; }
        static const char *keys[] = {"theme_color", "ui_dark", "ui_background", "ui_sidebar_opacity",
                                     "ui_background_blur", "ui_background_dim", "ui_background_folder",
                                     "ui_background_shuffle", "ui_background_interval",
                                     "window_mode", "custom_homepage", "homepage_mode", NULL};
        char old_i[PYMCL_PATH], old_f[PYMCL_PATH], new_i[PYMCL_PATH], new_f[PYMCL_PATH];
        str_of(config_get("ui_background"), old_i, sizeof(old_i));
        str_of(config_get("ui_background_folder"), old_f, sizeof(old_f));
        cJSON *bi = cJSON_GetObjectItemCaseSensitive(t, "ui_background");
        cJSON *bf = cJSON_GetObjectItemCaseSensitive(t, "ui_background_folder");
        if (bi) str_of(bi, new_i, sizeof(new_i)); else snprintf(new_i, sizeof(new_i), "%s", old_i);
        if (bf) str_of(bf, new_f, sizeof(new_f)); else snprintf(new_f, sizeof(new_f), "%s", old_f);
        int any = 0;
        for (int i = 0; keys[i]; i++) {
            cJSON *v = cJSON_GetObjectItemCaseSensitive(t, keys[i]);
            if (v) { config_set(keys[i], cJSON_Duplicate(v, 1)); any = 1; }
        }
        if (strcmp(new_i, old_i) || strcmp(new_f, old_f)) {
            cJSON *images, *folders;
            push_bg_history(old_i, old_f, &images, &folders);
            config_set("ui_background_history", images);
            config_set("ui_background_folder_history", folders);
            any = 1;
        }
        if (any) config_save();
        return t;
    }
    if (strcmp(method, "delete_theme") == 0) {
        char p[PYMCL_PATH];
        theme_path(pstr(params, "name", ""), p, sizeof(p));
        if (is_file(p)) {
            wchar_t *w = pymcl_u8_to_wide(p);
            DeleteFileW(w);
            free(w);
        }
        return cJSON_CreateNull();
    }
    if (strcmp(method, "export_theme") == 0) {
        const char *name = pstr(params, "name", "");
        char src[PYMCL_PATH], dst[PYMCL_PATH];
        theme_path(name, src, sizeof(src));
        if (!is_file(src)) { pymcl_set_error("主题包不存在: %s", name); return NULL; }
        pymcl_py_path(pstr(params, "dest", ""), dst, sizeof(dst));
        if (pymcl_dir_exists(dst)) pymcl_path_join(dst, sizeof(dst), dst, pymcl_basename(src));
        if (pymcl_copy_file(src, dst) != 0) return NULL;
        return cJSON_CreateString(dst);
    }
    if (strcmp(method, "import_theme") == 0) {
        const char *path = pstr(params, "path", "");
        char src[PYMCL_PATH];
        pymcl_py_path(path, src, sizeof(src));
        if (!is_file(src)) { pymcl_set_error("文件不存在: %s", path); return NULL; }
        cJSON *data = pymcl_read_json(src);
        if (!cJSON_IsObject(data)) { cJSON_Delete(data); pymcl_set_error("文件不是有效的主题包"); return NULL; }
        char name[512];
        cJSON *nm = cJSON_GetObjectItemCaseSensitive(data, "name");
        if (nm) py_str(nm, name, sizeof(name));
        else {
            const char *b = pymcl_basename(src), *dot = strrchr(b, '.');
            snprintf(name, sizeof(name), "%.*s", dot && dot != b ? (int)(dot - b) : (int)strlen(b), b);
        }
        cJSON_Delete(data);
        char dst[PYMCL_PATH];
        theme_path(name, dst, sizeof(dst));
        if (pymcl_copy_file(src, dst) != 0) return NULL;
        return cJSON_CreateString(name);
    }

    /* cleaner.preview / apply */
    if (strcmp(method, "cleaner_preview") == 0) return cleaner_preview();
    if (strcmp(method, "cleaner_apply") == 0) {
        cJSON *kinds = param(params, "kinds");
        const char *all[] = {"parts", "cache", "unused_libraries"};
        cJSON *want = cJSON_CreateArray();
        if (py_truthy(kinds) && cJSON_IsArray(kinds)) {
            cJSON *k;
            cJSON_ArrayForEach(k, kinds) if (cJSON_IsString(k)) cJSON_AddItemToArray(want, cJSON_CreateString(k->valuestring));
        } else {
            for (int i = 0; i < 3; i++) cJSON_AddItemToArray(want, cJSON_CreateString(all[i]));
        }
        cJSON *info = cleaner_preview();
        long long removed = 0, bytes = 0;
        cJSON *k;
        cJSON_ArrayForEach(k, want) {
            cJSON *row;
            cJSON_ArrayForEach(row, cJSON_GetObjectItem(info, k->valuestring)) {
                const char *p = cJSON_GetStringValue(cJSON_GetObjectItem(row, "path"));
                if (!p || !pymcl_file_exists(p)) continue;
                long long sz = pymcl_file_size(p);
                wchar_t *w = pymcl_u8_to_wide(p);
                if (w && DeleteFileW(w)) { removed++; bytes += sz; }
                free(w);
            }
        }
        cJSON_Delete(info);
        cJSON_Delete(want);
        cJSON *o = cJSON_CreateObject();
        cJSON_AddNumberToObject(o, "removed", (double)removed);
        cJSON_AddNumberToObject(o, "bytes", (double)bytes);
        return o;
    }

    /* BackendAPI.skin_urls */
    if (strcmp(method, "skin_urls") == 0) {
        const char *an = pstr(params, "account_name", "");
        cJSON *root = accounts_load();
        cJSON *acc = NULL;
        cJSON *tmp = cJSON_CreateObject();
        if (is_offline_account(an)) {
            cJSON_AddStringToObject(tmp, "type", "offline");
            cJSON_AddStringToObject(tmp, "name", "Steve");
            acc = tmp;
        } else {
            acc = find_account(root, an);
            if (!acc) {
                cJSON_AddStringToObject(tmp, "type", "offline");
                cJSON_AddStringToObject(tmp, "name", an);
                acc = tmp;
            }
        }
        char a[2048], b[2048];
        avatar_url(acc, a, sizeof(a));
        body_url(acc, b, sizeof(b));
        cJSON_Delete(tmp);
        cJSON_Delete(root);
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "avatar", a);
        cJSON_AddStringToObject(o, "body", b);
        return o;
    }

    /* BackendAPI.get_account_skin */
    if (strcmp(method, "get_account_skin") == 0) {
        const char *name = pstr(params, "name", "");
        cJSON *root = accounts_load();
        cJSON *acc = find_account(root, name);
        cJSON *empty = cJSON_CreateObject();
        if (!acc) acc = empty;
        char sp[PYMCL_PATH];
        char *data_url = NULL;
        if (skin_file_for(acc, sp, sizeof(sp))) {
            char *buf = NULL;
            size_t n = 0;
            char err[128];
            if (pymcl_read_file(sp, &buf, &n) == 0 && png_valid_skin((unsigned char *)buf, n, err, sizeof(err))) {
                char *b64 = pymcl_b64encode((unsigned char *)buf, n);
                if (b64) {
                    size_t l = strlen(b64) + 32;
                    data_url = (char *)malloc(l);
                    if (data_url) snprintf(data_url, l, "data:image/png;base64,%s", b64);
                    free(b64);
                }
            }
            free(buf);
        }
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "name", name);
        const char *sf = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_file"));
        cJSON_AddStringToObject(o, "skin_file", sf && sf[0] ? sf : "");
        cJSON_AddStringToObject(o, "skin_model", skin_model(acc));
        cJSON_AddStringToObject(o, "data_url", data_url ? data_url : "");
        free(data_url);
        cJSON_Delete(empty);
        cJSON_Delete(root);
        return o;
    }

    /* BackendAPI.stash_upload */
    if (strcmp(method, "stash_upload") == 0) {
        const char *name = pstr(params, "name", "");
        const char *data = pstr(params, "data", "");
        char blob[16];
        while (*data && isspace((unsigned char)*data)) data++;
        const char *raw = data;
        if (!strncmp(data, "data:", 5)) {
            const char *c = strchr(data, ',');
            raw = c ? c + 1 : data;
        }
        (void)blob;
        char *trimmed = pymcl_strdup(raw);
        size_t tl = strlen(trimmed);
        while (tl && isspace((unsigned char)trimmed[tl - 1])) trimmed[--tl] = 0;
        size_t plen = 0;
        unsigned char *payload = pymcl_b64decode(trimmed, &plen);
        free(trimmed);
        if (!payload) { pymcl_set_error("%s", tr("上传的数据不是有效的 base64")); return NULL; }
        if (!plen) { free(payload); pymcl_set_error("%s", tr("上传的文件是空的")); return NULL; }
        char safe[512];
        snprintf(safe, sizeof(safe), "%s", pymcl_basename(name));
        for (char *p = safe; *p; p++) {
            unsigned char c = (unsigned char)*p;
            if (c < 0x20 || strchr("<>:\"/\\|?*", c)) *p = '_';
        }
        char *s = safe;
        while (*s == ' ' || *s == '.') s++;
        size_t sl = strlen(s);
        while (sl && (s[sl - 1] == ' ' || s[sl - 1] == '.')) s[--sl] = 0;
        char folder[PYMCL_PATH], dest[PYMCL_PATH];
        pymcl_path_join(folder, sizeof(folder), g_root, "uploads");
        pymcl_ensure_dir(folder);
        pymcl_path_join(dest, sizeof(dest), folder, s[0] ? s : "upload.bin");
        if (pymcl_path_exists(dest)) {
            const char *b = pymcl_basename(dest), *dot = strrchr(b, '.');
            char nn[600];
            if (dot && dot != b) snprintf(nn, sizeof(nn), "%.*s-%lld%s", (int)(dot - b), b, (long long)time(NULL), dot);
            else snprintf(nn, sizeof(nn), "%s-%lld", b, (long long)time(NULL));
            pymcl_path_join(dest, sizeof(dest), folder, nn);
        }
        int r = pymcl_write_file(dest, payload, plen);
        free(payload);
        if (r != 0) return NULL;
        return cJSON_CreateString(dest);
    }

    /* BackendAPI.set_game_dir */
    if (strcmp(method, "set_game_dir") == 0) {
        const char *path = pstr(params, "path", "");
        int absolute = (isalpha((unsigned char)path[0]) && path[1] == ':') || (path[0] == '\\' && path[1] == '\\');
        char target[PYMCL_PATH];
        if (absolute) pymcl_py_path(path, target, sizeof(target));
        else pymcl_path_join(target, sizeof(target), g_root, path);
        pymcl_ensure_dir(target);
        char probe[PYMCL_PATH];
        pymcl_path_join(probe, sizeof(probe), target, ".pymcl-write-test");
        if (pymcl_write_file(probe, "ok", 2) != 0) {
            char msg[PYMCL_PATH];
            snprintf(msg, sizeof(msg), "%s", tr("游戏目录不可写: {0}"));
            char *ph = strstr(msg, "{0}");
            if (ph) {
                char tail[PYMCL_PATH];
                snprintf(tail, sizeof(tail), "%s", ph + 3);
                snprintf(ph, sizeof(msg) - (size_t)(ph - msg), "%s%s", target, tail);
            }
            pymcl_set_error("%s", msg);
            return NULL;
        }
        wchar_t *w = pymcl_u8_to_wide(probe);
        DeleteFileW(w);
        free(w);
        if (absolute) {
            char p[PYMCL_PATH];
            pymcl_py_path(path, p, sizeof(p));
            config_set_str("instances_dir", p);
        } else {
            config_set_str("instances_dir", path);
        }
        config_save();
        emit_ui_changed(emit);
        char d[PYMCL_PATH];
        pymcl_instances_dir(d, sizeof(d));
        return cJSON_CreateString(d);
    }

    return rpc_servers_call(method, params, emit, handled);
}
