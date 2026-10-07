/* 目录项目文件列表（docs/GOAL-c-bridge-no-python.md M2）：与 mclauncher/catalog_files.py 对齐。
 * list_catalog_files(extra)：source 决定 Modrinth / CurseForge；
 * extra.slug|name、extra.id、extra.game_version、extra.loader 参与查询。 */
#include "pymcl.h"

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(o, k));
    return (v && v[0]) ? v : def;
}

static cJSON *mr_get_path(const char *path_query) {
    char url[1024];
    snprintf(url, sizeof(url), MODRINTH_API "%s", path_query);
    cJSON *j = http_get_json(url, 30);
    if (j) return j;
    snprintf(url, sizeof(url), MCIM_MIRROR "/modrinth/v2%s", path_query);
    return http_get_json(url, 30);
}

static int is_loader_token(const char *s) {
    static const char *L[] = { "forge", "fabric", "quilt", "neoforge", "rift", "liteloader", "cauldron", "nonspecific" };
    for (size_t i = 0; i < sizeof(L)/sizeof(L[0]); i++) if (strcmp(s, L[i]) == 0) return 1;
    return 0;
}

static int is_mc_ver_token(const char *s) {
    /* ^\d+\.\d+ */
    int dig1 = 0, dig2 = 0, i = 0;
    while (s[i] >= '0' && s[i] <= '9') { dig1++; i++; }
    if (!dig1 || s[i] != '.') return 0;
    i++;
    while (s[i] >= '0' && s[i] <= '9') { dig2++; i++; }
    return dig2 > 0;
}

static cJSON *row_new(void) {
    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "id", "");
    cJSON_AddStringToObject(row, "name", "");
    cJSON_AddStringToObject(row, "version_number", "");
    cJSON_AddStringToObject(row, "filename", "");
    cJSON_AddItemToObject(row, "game_versions", cJSON_CreateArray());
    cJSON_AddItemToObject(row, "loaders", cJSON_CreateArray());
    cJSON_AddStringToObject(row, "date", "");
    cJSON_AddNumberToObject(row, "downloads", 0);
    cJSON_AddNumberToObject(row, "size", 0);
    cJSON_AddStringToObject(row, "release_type", "release");
    cJSON_AddStringToObject(row, "source", "");
    cJSON_AddStringToObject(row, "changelog", "");
    return row;
}

static void set_str_trunc(cJSON *row, const char *key, const char *v, size_t max_chars) {
    if (!v) v = "";
    char *buf = malloc(strlen(v) + 1);
    size_t chars = 0, i = 0;
    while (v[i] && chars < max_chars) {
        unsigned char c = (unsigned char)v[i];
        i += (c < 0x80) ? 1 : (c < 0xE0) ? 2 : (c < 0xF0) ? 3 : 4;
        chars++;
    }
    size_t end = i;
    memcpy(buf, v, end); buf[end] = '\0';
    cJSON_ReplaceItemInObject(row, key, cJSON_CreateString(buf));
    free(buf);
}

static void set_date(cJSON *row, const char *text) {
    char d[11] = "";
    if (text) { size_t n = strlen(text); if (n > 10) n = 10; memcpy(d, text, n); d[n] = '\0'; }
    cJSON_ReplaceItemInObject(row, "date", cJSON_CreateString(d));
}

/* ---- Modrinth ---- */
static cJSON *mr_list_versions(const char *slug, const char *gv, const char *loader) {
    char q[256]; q[0] = '\0';
    if (gv[0] && loader[0])
        snprintf(q, sizeof(q), "?game_versions=[\"%s\"]&loaders=[\"%s\"]", gv, loader);
    else if (gv[0]) snprintf(q, sizeof(q), "?game_versions=[\"%s\"]", gv);
    else if (loader[0]) snprintf(q, sizeof(q), "?loaders=[\"%s\"]", loader);
    char pq[512];
    snprintf(pq, sizeof(pq), "/project/%s/version%s", slug, q);
    cJSON *vers = mr_get_path(pq);
    if ((!vers || cJSON_GetArraySize(vers) == 0) && q[0]) {
        cJSON_Delete(vers);
        snprintf(pq, sizeof(pq), "/project/%s/version", slug);
        vers = mr_get_path(pq);
    }
    return cJSON_IsArray(vers) ? vers : (cJSON_Delete(vers), (cJSON *)NULL);
}

static cJSON *rows_from_mr(const char *slug, const char *gv, const char *loader) {
    cJSON *out = cJSON_CreateArray();
    cJSON *vers = mr_list_versions(slug, gv, loader);
    if (!vers) return out;
    cJSON *v;
    cJSON_ArrayForEach(v, vers) {
        cJSON *row = row_new();
        const char *id = cJSON_GetStringValue(cJSON_GetObjectItem(v, "id"));
        cJSON_ReplaceItemInObject(row, "id", cJSON_CreateString(id ? id : ""));
        const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(v, "name"));
        const char *vn = cJSON_GetStringValue(cJSON_GetObjectItem(v, "version_number"));
        cJSON_ReplaceItemInObject(row, "name", cJSON_CreateString(name ? name : (vn ? vn : "")));
        cJSON_ReplaceItemInObject(row, "version_number", cJSON_CreateString(vn ? vn : ""));
        cJSON *files = cJSON_GetObjectItem(v, "files");
        cJSON *file = NULL, *f;
        cJSON_ArrayForEach(f, files) {
            if (cJSON_IsTrue(cJSON_GetObjectItem(f, "primary"))) { file = f; break; }
            if (!file) file = f;
        }
        const char *fn = file ? cJSON_GetStringValue(cJSON_GetObjectItem(file, "filename")) : NULL;
        cJSON_ReplaceItemInObject(row, "filename", cJSON_CreateString(fn ? fn : ""));
        cJSON *gv_arr = cJSON_GetObjectItem(row, "game_versions");
        cJSON *it;
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(v, "game_versions"))
            if (cJSON_IsString(it)) cJSON_AddItemToArray(gv_arr, cJSON_CreateString(it->valuestring));
        cJSON *ld_arr = cJSON_GetObjectItem(row, "loaders");
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(v, "loaders"))
            if (cJSON_IsString(it)) cJSON_AddItemToArray(ld_arr, cJSON_CreateString(it->valuestring));
        const char *dp = cJSON_GetStringValue(cJSON_GetObjectItem(v, "date_published"));
        if (!dp || !dp[0]) dp = cJSON_GetStringValue(cJSON_GetObjectItem(v, "date"));
        set_date(row, dp);
        cJSON_ReplaceItemInObject(row, "downloads", cJSON_CreateNumber(cJSON_GetNumberValue(cJSON_GetObjectItem(v, "downloads"))));
        cJSON_ReplaceItemInObject(row, "size", cJSON_CreateNumber(file ? cJSON_GetNumberValue(cJSON_GetObjectItem(file, "size")) : 0));
        const char *rt = cJSON_GetStringValue(cJSON_GetObjectItem(v, "version_type"));
        cJSON_ReplaceItemInObject(row, "release_type", cJSON_CreateString(rt ? rt : "release"));
        cJSON_ReplaceItemInObject(row, "source", cJSON_CreateString("modrinth"));
        set_str_trunc(row, "changelog", cJSON_GetStringValue(cJSON_GetObjectItem(v, "changelog")), 400);
        cJSON_AddItemToArray(out, row);
    }
    cJSON_Delete(vers);
    return out;
}

/* ---- CurseForge ---- */
static long long cf_class_of(const char *kind) {
    /* 与 Python KIND_CF 对齐；CF_CLASS_* 常量在 mods.c 用数字，这里直接内联数值 */
    if (strcmp(kind, "mod") == 0) return 6;
    if (strcmp(kind, "modpack") == 0) return 4471;
    if (strcmp(kind, "shader") == 0) return 6552;
    if (strcmp(kind, "resourcepack") == 0) return 12;
    if (strcmp(kind, "datapack") == 0) return 6945;
    if (strcmp(kind, "world") == 0) return 17;
    return 6;
}

static long long cf_by_slug(const char *slug, const char *kind) {
    char q[256];
    snprintf(q, sizeof(q), "slug=%s&classId=%lld", slug, cf_class_of(kind));
    cJSON *d = cf_get("/mods/search", q);
    cJSON *items = d ? cf_items_of(d) : NULL;
    long long id = 0;
    if (cJSON_IsArray(items) && cJSON_GetArraySize(items) > 0) {
        cJSON *hit = cJSON_GetArrayItem(items, 0);
        id = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(hit, "id"));
    }
    cJSON_Delete(d);
    return id;
}

static cJSON *rows_from_cf(long long addon_id, const char *gv, const char *loader) {
    cJSON *out = cJSON_CreateArray();
    char q[256];
    if (gv[0]) snprintf(q, sizeof(q), "pageSize=50&gameVersion=%s", gv);
    else snprintf(q, sizeof(q), "pageSize=50");
    char p[80]; snprintf(p, sizeof(p), "/mods/%lld/files", addon_id);
    cJSON *fl = cf_get(p, q);
    cJSON *files = fl ? cf_items_of(fl) : NULL;
    if (!files) { cJSON_Delete(fl); return out; }
    cJSON *f;
    cJSON_ArrayForEach(f, files) {
        /* gameVersions 拆成 版本 与 加载器；指定 loader 且文件带 loader 信息时过滤 */
        cJSON *gvs_in = cJSON_GetObjectItem(f, "gameVersions");
        cJSON *game = cJSON_CreateArray(), *lds = cJSON_CreateArray();
        cJSON *it;
        cJSON_ArrayForEach(it, gvs_in) {
            const char *s = NULL; char num[32];
            if (cJSON_IsString(it)) s = it->valuestring;
            else if (cJSON_IsNumber(it)) {
                snprintf(num, sizeof(num), "%lld", (long long)it->valuedouble); s = num;
            }
            if (!s || !s[0]) continue;
            char low[64]; size_t i = 0;
            for (; s[i] && i < sizeof(low)-1; i++) low[i] = (char)tolower((unsigned char)s[i]);
            low[i] = '\0';
            if (is_loader_token(low)) cJSON_AddItemToArray(lds, cJSON_CreateString(low));
            else if (is_mc_ver_token(s)) cJSON_AddItemToArray(game, cJSON_CreateString(s));
        }
        if (loader[0] && cJSON_GetArraySize(lds) > 0) {
            int hit = 0;
            cJSON_ArrayForEach(it, lds) if (strcmp(it->valuestring, loader) == 0) { hit = 1; break; }
            if (!hit) { cJSON_Delete(game); cJSON_Delete(lds); continue; }
        }
        cJSON *row = row_new();
        long long rid = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(f, "id"));
        char ids[32]; snprintf(ids, sizeof(ids), "%lld", rid);
        cJSON_ReplaceItemInObject(row, "id", cJSON_CreateString(ids));
        const char *dn = cJSON_GetStringValue(cJSON_GetObjectItem(f, "displayName"));
        const char *fn2 = cJSON_GetStringValue(cJSON_GetObjectItem(f, "fileName"));
        const char *nm = (dn && dn[0]) ? dn : (fn2 ? fn2 : ids);
        cJSON_ReplaceItemInObject(row, "name", cJSON_CreateString(nm));
        cJSON_ReplaceItemInObject(row, "version_number", cJSON_CreateString(nm));
        cJSON_ReplaceItemInObject(row, "filename", cJSON_CreateString(fn2 ? fn2 : ""));
        cJSON_ReplaceItemInObject(row, "game_versions", game);
        cJSON_ReplaceItemInObject(row, "loaders", lds);
        set_date(row, cJSON_GetStringValue(cJSON_GetObjectItem(f, "fileDate")));
        cJSON_ReplaceItemInObject(row, "downloads", cJSON_CreateNumber(cJSON_GetNumberValue(cJSON_GetObjectItem(f, "downloadCount"))));
        double sz = cJSON_GetNumberValue(cJSON_GetObjectItem(f, "fileLength"));
        if (sz == 0) sz = cJSON_GetNumberValue(cJSON_GetObjectItem(f, "fileSizeOnDisk"));
        cJSON_ReplaceItemInObject(row, "size", cJSON_CreateNumber(sz));
        cJSON *rt = cJSON_GetObjectItem(f, "releaseType");
        if (cJSON_IsNumber(rt)) {
            int rv = (int)rt->valuedouble;
            cJSON_ReplaceItemInObject(row, "release_type", cJSON_CreateString(rv == 1 ? "release" : rv == 2 ? "beta" : rv == 3 ? "alpha" : "release"));
        } else if (cJSON_IsString(rt) && rt->valuestring[0]) {
            cJSON_ReplaceItemInObject(row, "release_type", cJSON_CreateString(rt->valuestring));
        }
        cJSON_ReplaceItemInObject(row, "source", cJSON_CreateString("curseforge"));
        cJSON_AddItemToArray(out, row);
    }
    cJSON_Delete(fl);
    return out;
}

cJSON *rpc_catalog_call(const char *method, cJSON *params, int *handled) {
    if (strcmp(method, "list_catalog_files") != 0) return NULL;
    *handled = 1;
    cJSON *extra = cJSON_GetObjectItem(params, "extra");
    if (!cJSON_IsObject(extra)) extra = params;

    const char *src = pstr(extra, "source", "");
    const char *slug = pstr(extra, "slug", "");
    if (!slug[0]) slug = pstr(extra, "name", "");
    const char *id_s = pstr(extra, "id", "");
    const char *gv = pstr(extra, "game_version", "");
    if (!gv[0]) gv = pstr(extra, "mc_version", "");
    if (!gv[0]) gv = pstr(extra, "version", "");
    if (gv[0] && (pymcl_ieq(gv, "全部") || pymcl_ieq(gv, "all"))) gv = "";
    const char *loader = pstr(extra, "loader", "");
    if (!loader[0]) loader = pstr(extra, "loaders", "");
    if (loader[0] && (pymcl_ieq(loader, "全部") || pymcl_ieq(loader, "all") || pymcl_ieq(loader, "任意"))) loader = "";
    {
        char low[32]; size_t i = 0;
        for (; loader[i] && i < sizeof(low)-1; i++) low[i] = (char)tolower((unsigned char)loader[i]);
        low[i] = '\0';
        loader = low; /* 局部副本存活到函数尾，够用 */
        int is_cf = 0;
        if (pymcl_ieq(src, "curseforge") || strncmp(src, "curse", 5) == 0) is_cf = 1;
        else if (id_s[0] && !slug[0]) is_cf = 1;
        if (is_cf) {
            long long addon = 0;
            if (id_s[0]) addon = strtoll(id_s, NULL, 10);
            if (!addon && slug[0]) {
                const char *kind = pstr(extra, "kind", "");
                if (!kind[0]) kind = pstr(extra, "project_type", "mod");
                addon = cf_by_slug(slug, kind);
            }
            if (!addon) return cJSON_CreateArray();
            return rows_from_cf(addon, gv, loader);
        }
        if (!slug[0]) return cJSON_CreateArray();
        return rows_from_mr(slug, gv, loader);
    }
}
