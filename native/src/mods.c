#include "pymcl.h"

/* 任务日志出口，与 modpack.c 的 emit 同构：进度回调 + SSE log + 全局日志三处一起写。
   mods.c 的安装任务此前一条 log 都不发，任务框必然空白（审查代理定位的必现问题）。 */
static void emit(pymcl_ctx *ctx, const char *msg) {
    if (ctx && ctx->on_progress) ctx->on_progress(ctx->ud, msg, 0, 1);
    if (ctx && ctx->on_log) ctx->on_log(ctx->ud, msg);
    pymcl_log("%s", msg);
}

static const char *cf_bases[] = {
    CF_OFFICIAL,
    "https://mod.mcimirror.top/curseforge/v1",
    BMCLAPI "/curseforge/v1",
};

/* content 别名表通用查询，定义在文件末尾（自持 catalog.json 懒加载副本，
   避免改 catalog.c / pymcl.h 的并发区）。 */
int catalog_lookup_named(const char *table, const char *q, char *slug, size_t ns,
                         long long *cf, char *title, size_t nt);

static void cf_hdr(char *out, size_t n) {
    const char *key = config_str("curseforge_api_key", "");
    if (key && key[0]) snprintf(out, n, "Accept: application/json\nx-api-key: %s", key);
    else snprintf(out, n, "Accept: application/json");
}

/* mod_update / catalog 共用的 CF GET（带 key 与镜像回落） */
cJSON *cf_get(const char *path, const char *query) {
    char hdr[512]; cf_hdr(hdr, sizeof(hdr));
    for (int i = 0; i < 3; i++) {
        char url[1024];
        if (query && query[0])
            snprintf(url, sizeof(url), "%s%s?%s", cf_bases[i], path, query);
        else
            snprintf(url, sizeof(url), "%s%s", cf_bases[i], path);
        cJSON *j = http_get_json_hdr(url, hdr, 45);
        if (j) return j;
    }
    return NULL;
}

/* CF POST JSON（fingerprints 等），镜像回落同 cf_get */
cJSON *cf_post_json(const char *path, const char *json_body) {
    char hdr[512]; cf_hdr(hdr, sizeof(hdr));
    for (int i = 0; i < 3; i++) {
        char url[1024];
        snprintf(url, sizeof(url), "%s%s", cf_bases[i], path);
        http_resp r;
        if (http_post_json(url, json_body, &r, hdr, 45) != 0) continue;
        cJSON *j = cJSON_ParseWithLength(r.body ? r.body : "", r.len);
        http_resp_free(&r);
        if (j) return j;
    }
    return NULL;
}

static cJSON *cf_items(cJSON *data) {
    if (cJSON_IsArray(data)) return data;
    cJSON *d = cJSON_GetObjectItem(data, "data");
    return cJSON_IsArray(d) ? d : NULL;
}

cJSON *cf_items_of(cJSON *data) { return cf_items(data); }

static void mirror_mr(const char *url, char *out, size_t n) {
    if (strstr(url, "api.modrinth.com")) {
        snprintf(out, n, "%s", url);
        char *p = strstr(out, "https://api.modrinth.com");
        if (p) {
            char tmp[1024];
            snprintf(tmp, sizeof(tmp), "%s/modrinth%s", MCIM_MIRROR, p + strlen("https://api.modrinth.com"));
            snprintf(out, n, "%s", tmp);
        }
        return;
    }
    if (strstr(url, MODRINTH_CDN)) {
        snprintf(out, n, "%s", url);
        char *p = strstr(out, MODRINTH_CDN);
        if (p) {
            char tmp[1024];
            snprintf(tmp, sizeof(tmp), "%s%s", MCIM_MIRROR, p + strlen(MODRINTH_CDN));
            snprintf(out, n, "%s", tmp);
        }
        return;
    }
    snprintf(out, n, "%s", url);
}

/* URL query 百分号编码（RFC3986 unreserved 之外全部 %XX，空格编成 %20）。
   与 mr_search 里的 enc 循环同口径，但抽成函数给 CF 搜索的 searchFilter 复用：
   以前 search_mods / search_modpacks / search_content 把 query 原样拼进 URL，
   中文会被 curl 当非法字节、`&` 直接截断参数、`+` 被服务端当空格、`#` 会把后段
   切成 fragment。逐字节编码，永不越界：目标缓冲不足时截断（宁可少一个字符也
   不溢出），并保证 NUL 结尾。 */
static void url_encode(const char *s, char *out, size_t n) {
    if (!out || n == 0) return;
    size_t o = 0;
    if (!s) { out[0] = 0; return; }
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
            || c == '-' || c == '_' || c == '.' || c == '~') {
            if (o + 1 >= n) break;
            out[o++] = (char)c;
        } else {
            if (o + 3 >= n) break; /* 放不下 "%XX" + NUL 就停 */
            out[o++] = '%';
            out[o++] = "0123456789ABCDEF"[c >> 4];
            out[o++] = "0123456789ABCDEF"[c & 0xF];
        }
    }
    out[o] = 0;
}

static cJSON *mr_search(const char *query, const char *ptype, int limit) {
    char q[1024];
    char facets[128];
    snprintf(facets, sizeof(facets), "[[\"project_type:%s\"]]", ptype);
    /* curl-escape roughly */
    char enc[512] = {0};
    const char *s = query ? query : "";
    size_t o = 0;
    for (; *s && o + 4 < sizeof(enc); s++) {
        unsigned char c = (unsigned char)*s;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_')
            enc[o++] = (char)c;
        else { snprintf(enc + o, sizeof(enc) - o, "%%%02X", c); o = strlen(enc); }
    }
    snprintf(q, sizeof(q), "query=%s&facets=%s&limit=%d&index=relevance", enc[0] ? enc : "%20", facets, limit);
    /* encode facets brackets */
    char url1[1024], url2[1024];
    snprintf(url1, sizeof(url1), MODRINTH_API "/search?query=%s&limit=%d&index=relevance&facets=%%5B%%5B%%22project_type%%3A%s%%22%%5D%%5D",
             enc[0] ? enc : "%20", limit, ptype);
    snprintf(url2, sizeof(url2), MCIM_MIRROR "/modrinth/v2/search?query=%s&limit=%d&index=relevance&facets=%%5B%%5B%%22project_type%%3A%s%%22%%5D%%5D",
             enc[0] ? enc : "%20", limit, ptype);
    cJSON *j = http_get_json(url1, 45);
    if (!j) j = http_get_json(url2, 45);
    return j;
}

/* CF 封面：官方字段是 logo.thumbnailUrl，个别响应给 logoUrl。取不到给空串。 */
static const char *cf_logo_url(cJSON *m) {
    cJSON *logo = cJSON_GetObjectItem(m, "logo");
    if (cJSON_IsObject(logo)) {
        const char *t = cJSON_GetStringValue(cJSON_GetObjectItem(logo, "thumbnailUrl"));
        if (t) return t;
        const char *u = cJSON_GetStringValue(cJSON_GetObjectItem(logo, "url"));
        if (u) return u;
    }
    return cJSON_GetStringValue(cJSON_GetObjectItem(m, "logoUrl"));
}

static cJSON *row_from_mr_hit(cJSON *h) {
    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(h, "title")) ?: "?");
    cJSON_AddStringToObject(row, "author", cJSON_GetStringValue(cJSON_GetObjectItem(h, "author")) ?: "?");
    cJSON_AddNumberToObject(row, "downloads", cJSON_GetNumberValue(cJSON_GetObjectItem(h, "downloads")));
    const char *slug = cJSON_GetStringValue(cJSON_GetObjectItem(h, "slug"));
    if (slug) cJSON_AddStringToObject(row, "slug", slug);
    cJSON_AddStringToObject(row, "source", "modrinth");
    const char *desc = cJSON_GetStringValue(cJSON_GetObjectItem(h, "description"));
    if (desc) {
        char d[161]; snprintf(d, sizeof(d), "%s", desc);
        cJSON_AddStringToObject(row, "description", d);
    }
    const char *icon = cJSON_GetStringValue(cJSON_GetObjectItem(h, "icon_url"));
    cJSON_AddStringToObject(row, "icon_url", icon ? icon : "");
    /* project_url：Modrinth 拿 slug 拼主页（前端点卡片打开介绍页用） */
    char purl[256] = {0};
    if (slug) snprintf(purl, sizeof(purl), "https://modrinth.com/mod/%s", slug);
    cJSON_AddStringToObject(row, "project_url", purl);
    return row;
}

/* CF 的 authors 拼成 "a, b"（Python _cf_norm 的 ", ".join(a.get("name", "") for a in ...)） */
static void cf_authors_join(cJSON *m, char *out, size_t n) {
    out[0] = 0;
    cJSON *a; int first = 1;
    cJSON_ArrayForEach(a, cJSON_GetObjectItem(m, "authors")) {
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(a, "name"));
        if (!nm) continue;
        if (!first) strncat(out, ", ", n - strlen(out) - 1);
        strncat(out, nm, n - strlen(out) - 1);
        first = 0;
    }
}

static cJSON *row_from_cf(cJSON *m) {
    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(m, "name")) ?: "?");
    char author[256] = {0};
    cf_authors_join(m, author, sizeof(author));
    cJSON_AddStringToObject(row, "author", author[0] ? author : "?");
    cJSON_AddNumberToObject(row, "downloads", cJSON_GetNumberValue(cJSON_GetObjectItem(m, "downloadCount")));
    cJSON *cid = cJSON_GetObjectItem(m, "id");
    if (cJSON_IsNumber(cid))
        cJSON_AddNumberToObject(row, "id", cid->valuedouble);
    else if (cJSON_IsString(cid) && cid->valuestring && cid->valuestring[0])
        cJSON_AddNumberToObject(row, "id", (double)atoll(cid->valuestring));
    const char *slug = cJSON_GetStringValue(cJSON_GetObjectItem(m, "slug"));
    if (slug) cJSON_AddStringToObject(row, "slug", slug);
    cJSON_AddStringToObject(row, "source", "curseforge");
    const char *sum = cJSON_GetStringValue(cJSON_GetObjectItem(m, "summary"));
    if (sum) {
        char d[161]; snprintf(d, sizeof(d), "%s", sum);
        cJSON_AddStringToObject(row, "description", d);
    }
    const char *icon = cf_logo_url(m);
    cJSON_AddStringToObject(row, "icon_url", icon ? icon : "");
    /* project_url：优先 links.websiteUrl（详情接口才有），否则按 slug 拼。
       CF /mods/search 的响应不带 links，搜索结果只能拼、可能不准。 */
    const char *web = NULL;
    cJSON *links = cJSON_GetObjectItem(m, "links");
    if (cJSON_IsObject(links)) web = cJSON_GetStringValue(cJSON_GetObjectItem(links, "websiteUrl"));
    if (web && web[0]) {
        cJSON_AddStringToObject(row, "project_url", web);
    } else if (slug && slug[0]) {
        char purl[256];
        snprintf(purl, sizeof(purl), "https://www.curseforge.com/minecraft/mc-mods/%s", slug);
        cJSON_AddStringToObject(row, "project_url", purl);
    } else {
        cJSON_AddStringToObject(row, "project_url", "");
    }
    return row;
}

cJSON *search_mods(const char *query, const char *source) {
    const char *q = query ? query : "";
    int want_cf = 0, want_mr = 1;
    if (source && (pymcl_ieq(source, "全部") || pymcl_ieq(source, "all") || !source[0])) { want_cf = 1; want_mr = 1; }
    else if (source && pymcl_startswith(source, "curse")) { want_cf = 1; want_mr = 0; }
    else { want_mr = 1; want_cf = 0; }
    if (!q[0]) return catalog_popular_mods(source);
    cJSON *out = cJSON_CreateArray();
    char slug[128] = {0}; long long cf = 0; char title[128] = {0};
    catalog_lookup_mod(q, slug, sizeof(slug), &cf, title, sizeof(title));
    if (slug[0] && want_mr) {
        char url[256]; snprintf(url, sizeof(url), MODRINTH_API "/project/%s", slug);
        cJSON *p = http_get_json(url, 30);
        if (p) {
            cJSON *row = cJSON_CreateObject();
            const char *rslug = cJSON_GetStringValue(cJSON_GetObjectItem(p, "slug"));
            cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(p, "title")) ?: title);
            cJSON_AddStringToObject(row, "author", "?");
            cJSON_AddNumberToObject(row, "downloads", cJSON_GetNumberValue(cJSON_GetObjectItem(p, "downloads")));
            cJSON_AddStringToObject(row, "slug", rslug ? rslug : slug);
            cJSON_AddStringToObject(row, "source", "modrinth");
            const char *icon = cJSON_GetStringValue(cJSON_GetObjectItem(p, "icon_url"));
            cJSON_AddStringToObject(row, "icon_url", icon ? icon : "");
            char purl[256];
            snprintf(purl, sizeof(purl), "https://modrinth.com/mod/%s", rslug ? rslug : slug);
            cJSON_AddStringToObject(row, "project_url", purl);
            cJSON_AddItemToArray(out, row);
            cJSON_Delete(p);
        }
    }
    if (cf && want_cf) {
        char path[64]; snprintf(path, sizeof(path), "/mods/%lld", cf);
        cJSON *d = cf_get(path, NULL);
        cJSON *m = d ? cJSON_GetObjectItem(d, "data") : NULL;
        if (cJSON_IsObject(m)) cJSON_AddItemToArray(out, row_from_cf(m));
        cJSON_Delete(d);
    }
    if (cJSON_GetArraySize(out) > 0) return out;
    if (want_mr) {
        cJSON *j = mr_search(q, "mod", 30);
        cJSON *hits = j ? cJSON_GetObjectItem(j, "hits") : NULL;
        cJSON *h;
        cJSON_ArrayForEach(h, hits) cJSON_AddItemToArray(out, row_from_mr_hit(h));
        cJSON_Delete(j);
    }
    if (want_cf) {
        char qenc[1024], queryp[1280];
        url_encode(q, qenc, sizeof(qenc));
        snprintf(queryp, sizeof(queryp), "gameId=432&classId=%d&sortField=2&pageSize=30&index=0&searchFilter=%s",
                 CF_CLASS_MOD, qenc);
        cJSON *d = cf_get("/mods/search", queryp);
        cJSON *items = cf_items(d);
        cJSON *m;
        cJSON_ArrayForEach(m, items) cJSON_AddItemToArray(out, row_from_cf(m));
        cJSON_Delete(d);
    }
    return out;
}

cJSON *search_modpacks(const char *query, const char *source) {
    const char *q = query ? query : "";
    if (!q[0]) return catalog_popular_packs(source);
    int want_cf = 1, want_mr = 1;
    if (source && pymcl_startswith(source, "curse")) want_mr = 0;
    if (source && pymcl_ieq(source, "modrinth")) want_cf = 0;
    cJSON *out = cJSON_CreateArray();
    char slug[128] = {0}; long long cf = 0; char title[128] = {0};
    catalog_lookup_pack(q, slug, sizeof(slug), &cf, title, sizeof(title));
    if (cf && want_cf) {
        char path[64]; snprintf(path, sizeof(path), "/mods/%lld", cf);
        cJSON *d = cf_get(path, NULL);
        cJSON *m = d ? cJSON_GetObjectItem(d, "data") : NULL;
        if (cJSON_IsObject(m)) cJSON_AddItemToArray(out, row_from_cf(m));
        cJSON_Delete(d);
    }
    if (slug[0] && want_mr) {
        char url[256]; snprintf(url, sizeof(url), MODRINTH_API "/project/%s", slug);
        cJSON *p = http_get_json(url, 30);
        if (p) {
            cJSON *row = cJSON_CreateObject();
            cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(p, "title")) ?: title);
            cJSON_AddStringToObject(row, "slug", slug);
            cJSON_AddStringToObject(row, "source", "modrinth");
            cJSON_AddNumberToObject(row, "downloads", cJSON_GetNumberValue(cJSON_GetObjectItem(p, "downloads")));
            const char *icon = cJSON_GetStringValue(cJSON_GetObjectItem(p, "icon_url"));
            cJSON_AddStringToObject(row, "icon_url", icon ? icon : "");
            char purl[256];
            snprintf(purl, sizeof(purl), "https://modrinth.com/modpack/%s", slug);
            cJSON_AddStringToObject(row, "project_url", purl);
            cJSON_AddItemToArray(out, row);
            cJSON_Delete(p);
        }
    }
    if (cJSON_GetArraySize(out) > 0) return out;
    if (want_mr) {
        cJSON *j = mr_search(q, "modpack", 25);
        cJSON *hits = j ? cJSON_GetObjectItem(j, "hits") : NULL;
        cJSON *h;
        cJSON_ArrayForEach(h, hits) cJSON_AddItemToArray(out, row_from_mr_hit(h));
        cJSON_Delete(j);
    }
    if (want_cf) {
        char qenc[1024], queryp[1280];
        url_encode(q, qenc, sizeof(qenc));
        snprintf(queryp, sizeof(queryp), "gameId=432&classId=%d&sortField=2&pageSize=25&index=0&searchFilter=%s",
                 CF_CLASS_MODPACK, qenc);
        cJSON *d = cf_get("/mods/search", queryp);
        cJSON *items = cf_items(d);
        cJSON *m;
        cJSON_ArrayForEach(m, items) cJSON_AddItemToArray(out, row_from_cf(m));
        cJSON_Delete(d);
    }
    return out;
}

/* content 类型 -> catalog.json 里的别名表名。catalog_lookup_mod 只认 mod_aliases，
   光影/资源包/数据包是另外三张表（见 catalog_lookup_named 注释）。 */
static const char *content_alias_table(const char *kind) {
    if (strcmp(kind, "shader") == 0) return "shader_aliases";
    if (strcmp(kind, "resourcepack") == 0) return "resourcepack_aliases";
    if (strcmp(kind, "datapack") == 0) return "datapack_aliases";
    return "mod_aliases";
}

/* search_content：shader / resourcepack / datapack 三类的多源搜索。
   别名表按 kind 选（content_alias_table），命中即返回。 */
cJSON *search_content(const char *kind, const char *query, const char *source) {
    const char *mr = "mod";
    int cf = CF_CLASS_MOD;
    if (strcmp(kind, "shader") == 0) { mr = "shader"; cf = CF_CLASS_SHADER; }
    else if (strcmp(kind, "resourcepack") == 0) { mr = "resourcepack"; cf = CF_CLASS_RESOURCEPACK; }
    else if (strcmp(kind, "datapack") == 0) { mr = "datapack"; cf = CF_CLASS_DATAPACK; }
    int want_mr = 1, want_cf = 1;
    if (source && pymcl_startswith(source, "curse")) want_mr = 0;
    if (source && pymcl_ieq(source, "modrinth")) want_cf = 0;
    const char *q = query ? query : "";
    cJSON *out = cJSON_CreateArray();
    /* 中文别名：与 search_mods(:197) / search_modpacks(:254) 同一套逻辑。此前
       search_content 根本没调 catalog_lookup_*，中文搜光影/资源包/数据包不命中别名表。
       与 Python 桥 search_content 的语义对齐（bridge/api.py:1686+ 的 search_mods_chinese
       分支）：别名解析是**跨源**的，命中即返回，不被 source 筛选（curseforge-only /
       modrinth-only）挡掉；否则用户选「CurseForge」时中文别名永远搜不到。
       表项只带 slug 就查 Modrinth，只带 cf 就查 CF，两者都有就都试。 */
    if (q[0]) {
        char aslug[128] = {0}, atitle[128] = {0}; long long acf = 0;
        if (catalog_lookup_named(content_alias_table(kind), q, aslug, sizeof(aslug), &acf, atitle, sizeof(atitle))) {
            if (acf) {
                char path[64]; snprintf(path, sizeof(path), "/mods/%lld", acf);
                cJSON *d = cf_get(path, NULL);
                cJSON *m = d ? cJSON_GetObjectItem(d, "data") : NULL;
                if (cJSON_IsObject(m)) cJSON_AddItemToArray(out, row_from_cf(m));
                cJSON_Delete(d);
            }
            if (aslug[0]) {
                char url[256]; snprintf(url, sizeof(url), MODRINTH_API "/project/%s", aslug);
                cJSON *p = http_get_json(url, 30);
                if (p) {
                    cJSON *row = cJSON_CreateObject();
                    const char *rslug = cJSON_GetStringValue(cJSON_GetObjectItem(p, "slug"));
                    cJSON_AddStringToObject(row, "name", cJSON_GetStringValue(cJSON_GetObjectItem(p, "title")) ?: atitle);
                    cJSON_AddStringToObject(row, "author", "?");
                    cJSON_AddNumberToObject(row, "downloads", cJSON_GetNumberValue(cJSON_GetObjectItem(p, "downloads")));
                    cJSON_AddStringToObject(row, "slug", rslug ? rslug : aslug);
                    cJSON_AddStringToObject(row, "source", "modrinth");
                    const char *icon = cJSON_GetStringValue(cJSON_GetObjectItem(p, "icon_url"));
                    cJSON_AddStringToObject(row, "icon_url", icon ? icon : "");
                    char purl[256];
                    snprintf(purl, sizeof(purl), "https://modrinth.com/%s/%s", mr, rslug ? rslug : aslug);
                    cJSON_AddStringToObject(row, "project_url", purl);
                    cJSON_AddItemToArray(out, row);
                    cJSON_Delete(p);
                }
            }
            if (cJSON_GetArraySize(out) > 0) return out;
        }
    }
    if (want_mr) {
        cJSON *j = mr_search(q, mr, 30);
        cJSON *hits = j ? cJSON_GetObjectItem(j, "hits") : NULL;
        cJSON *h;
        cJSON_ArrayForEach(h, hits) cJSON_AddItemToArray(out, row_from_mr_hit(h));
        cJSON_Delete(j);
    }
    if (want_cf) {
        char qenc[1024], queryp[1280];
        url_encode(q, qenc, sizeof(qenc));
        snprintf(queryp, sizeof(queryp), "gameId=432&classId=%d&sortField=2&pageSize=30&index=0%s%s",
                 cf, qenc[0] ? "&searchFilter=" : "", qenc);
        cJSON *d = cf_get("/mods/search", queryp);
        cJSON *items = cf_items(d);
        cJSON *m;
        cJSON_ArrayForEach(m, items) cJSON_AddItemToArray(out, row_from_cf(m));
        cJSON_Delete(d);
    }
    return out;
}

/* ---------- 世界（地图存档） ---------- */

/* CF 分类名列表 -> 小写名字数组（Python _cf_norm 的 cf_categories）。 */
static cJSON *cf_category_names(cJSON *m) {
    cJSON *out = cJSON_CreateArray();
    cJSON *c;
    cJSON_ArrayForEach(c, cJSON_GetObjectItem(m, "categories")) {
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(c, "name"));
        if (!nm || !nm[0]) continue;
        char low[128]; size_t i = 0;
        for (; nm[i] && i < sizeof(low) - 1; i++) low[i] = (char)tolower((unsigned char)nm[i]);
        low[i] = '\0';
        cJSON_AddItemToArray(out, cJSON_CreateString(low));
    }
    return out;
}

/* 世界的 CurseForge 网页路径是 /minecraft/worlds/<slug>（不是 mc-mods）。
   links.websiteUrl 只有详情接口才有，搜索结果按 slug 拼是尽力而为的兜底。 */
static void cf_world_url(cJSON *m, const char *slug, char *out, size_t n) {
    out[0] = 0;
    cJSON *links = cJSON_GetObjectItem(m, "links");
    if (cJSON_IsObject(links)) {
        const char *web = cJSON_GetStringValue(cJSON_GetObjectItem(links, "websiteUrl"));
        if (web && web[0]) { snprintf(out, n, "%s", web); return; }
    }
    if (slug && slug[0]) snprintf(out, n, "https://www.curseforge.com/minecraft/worlds/%s", slug);
}

/* row_from_cf 的搜索结果版：/mods/search 的响应不带 links，主页只能按 slug 拼；
   updated / tags 也从这一层带出来（前端 CatalogItem 要 updated / tags）。
   与 Python search_projects -> _hit_row 的字段集对齐。 */
static cJSON *row_from_cf_world(cJSON *m) {
    cJSON *row = row_from_cf(m);
    const char *slug = cJSON_GetStringValue(cJSON_GetObjectItem(m, "slug"));
    char purl[512];
    cf_world_url(m, slug, purl, sizeof(purl));
    cJSON_ReplaceItemInObject(row, "project_url", cJSON_CreateString(purl));
    /* updated：dateModified 取前 10 位（Python _date / _hit_row 的 [:10]） */
    const char *dm = cJSON_GetStringValue(cJSON_GetObjectItem(m, "dateModified"));
    if (!dm) dm = cJSON_GetStringValue(cJSON_GetObjectItem(m, "dateCreated"));
    char d[11] = "";
    if (dm) { size_t l = strlen(dm); if (l > 10) l = 10; memcpy(d, dm, l); d[l] = 0; }
    cJSON_AddStringToObject(row, "updated", d);
    cJSON_AddItemToObject(row, "tags", cf_category_names(m));
    return row;
}

/* 世界的分类筛选：CF 的 categoryFilter 对 slug 不稳定，Python 侧拉回结果后按
   分类名做客户端过滤（catalog_files.search_projects -> cf_category_tokens 生成
   canonical key 的展示名碎片，再 any(tok in c for c in cf_categories)）。
   这里照搬同一套：中文/译文标签先归一成 canonical key，再取碎片做子串匹配。
   表与 mclauncher/catalog_files.py 的 TYPE_ALIASES / CF_TYPE_TOKENS 逐条对齐。 */
static const struct { const char *label, *key; } k_world_type_alias[] = {
    {"优化", "optimization"}, {"科技", "technology"}, {"魔法", "magic"},
    {"冒险", "adventure"}, {"生存", "survival"}, {"装饰", "decoration"},
    {"写实", "realistic"}, {"卡通", "cartoon"}, {"高性能", "performance"},
    {"光追", "path-tracing"}, {"现代风", "modern"}, {"动态效果", "animated"},
    {"空岛", "skyblock"}, {"创造", "creation"},
    /* 译文入口（英文界面下前端发的是 tr() 之后的文案） */
    {"optimization", "optimization"}, {"tech", "technology"}, {"magic", "magic"},
    {"adventure", "adventure"}, {"survival", "survival"}, {"decor", "decoration"},
    {"realistic", "realistic"}, {"cartoon", "cartoon"},
    {"high performance", "performance"}, {"ray tracing", "path-tracing"},
    {"modern", "modern"}, {"motion effects", "animated"}, {"skyblock", "skyblock"},
    {"creative", "creation"},
    {NULL, NULL}
};
static const struct { const char *key, *tok; } k_world_cf_tokens[] = {
    {"optimization", "performance"}, {"optimization", "optimization"},
    {"technology", "technology"}, {"technology", "tech"},
    {"magic", "magic"},
    {"adventure", "adventure"},
    {"survival", "survival"}, {"survival", "util"}, {"survival", "food"},
    {"decoration", "decor"},
    {"realistic", "realistic"},
    {"cartoon", "cartoon"}, {"cartoon", "animated"},
    {"performance", "performance"},
    {"path-tracing", "path tracing"}, {"path-tracing", "shader"},
    {"16x", "16x"}, {"32x", "32x"}, {"64x", "64x"},
    {"modern", "modern"}, {"animated", "animated"},
    {"skyblock", "skyblock"}, {"creation", "creation"},
    {NULL, NULL}
};

/* type_key：标签归一成 canonical key；「不限」/认不出都返回空串（= 不过滤）。 */
static const char *world_type_key(const char *label) {
    if (!label || !label[0]) return "";
    if (pymcl_ieq(label, "全部") || pymcl_ieq(label, "all") || pymcl_ieq(label, "any")) return "";
    const char *tl = tr("全部");
    if (tl && tl[0] && pymcl_ieq(label, tl)) return "";
    for (int i = 0; k_world_type_alias[i].label; i++)
        if (pymcl_ieq(k_world_type_alias[i].label, label)) return k_world_type_alias[i].key;
    /* 认不出的原样返回（Python type_key 的 .get(s, s)），没有碎片就等于不过滤 */
    return label;
}

static int world_cat_hit(cJSON *m, const char *cat) {
    const char *key = world_type_key(cat);
    if (!key[0]) return 1;
    int any_tok = 0;
    for (int i = 0; k_world_cf_tokens[i].key; i++) {
        if (strcmp(k_world_cf_tokens[i].key, key) != 0) continue;
        any_tok = 1;
        const char *tok = k_world_cf_tokens[i].tok;
        cJSON *names = cf_category_names(m);
        cJSON *it;
        int hit = 0;
        cJSON_ArrayForEach(it, names)
            if (pymcl_icontains(it->valuestring, tok)) { hit = 1; break; }
        cJSON_Delete(names);
        if (hit) return 1;
    }
    /* 表里没有这个 key（Python 的 跑酷 之类）：碎片为空 → 不过滤，全部放行 */
    return any_tok ? 0 : 1;
}

/* search_worlds：世界只有 CurseForge 一个源（mclauncher/catalog_files.py:340-342
   的 kind == "world" 分支强制 want_mr = False / want_cf = True），classId=17。
   query 为空时按人气列出（CF sortField=2 = 下载量）。
   extra 认 game_version / version（MC 版本）与 category / type（分类标签）。
   返回结构与 search_content / search_mods 一致：前端 CatalogItem 直接反序列化。 */
cJSON *search_worlds(const char *query, const char *source, cJSON *extra) {
    const char *q = query ? query : "";
    const char *cat = "";
    const char *gv = "";
    if (cJSON_IsObject(extra)) {
        const char *c = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "category"));
        if (!c || !c[0]) c = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "type"));
        if (c) cat = c;
        const char *g = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "game_version"));
        if (!g || !g[0]) g = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "mc_version"));
        if (!g || !g[0]) g = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "version"));
        if (g) gv = g;
    }
    if (pymcl_ieq(gv, "全部") || pymcl_ieq(gv, "all")) gv = "";
    /* 世界没有 Modrinth 源，而且 source 不参与筛选：Python 的 search_projects 在
       kind == "world" 时无条件 want_cf = True / want_mr = False
       （mclauncher/catalog_files.py:340-342），连选 Modrinth 也只查 CurseForge。
       这里保持一致，source 只作占位（前端默认发 CurseForge）。 */
    (void)source;
    cJSON *out = cJSON_CreateArray();
    char qenc[1024], queryp[1408];
    url_encode(q, qenc, sizeof(qenc));
    /* 带分类时要客户端过滤，多取一些；CF 的 pageSize 硬上限 50 */
    int page = (cat && cat[0]) ? 50 : 30;
    char gvpart[128] = "";
    if (gv[0]) {
        char gvenc[128];
        url_encode(gv, gvenc, sizeof(gvenc));
        snprintf(gvpart, sizeof(gvpart), "&gameVersion=%s", gvenc);
    }
    snprintf(queryp, sizeof(queryp),
             "gameId=432&classId=%d&sortField=2&sortOrder=desc&pageSize=%d&index=0%s%s%s",
             CF_CLASS_WORLD, page, gvpart, qenc[0] ? "&searchFilter=" : "", qenc);
    cJSON *d = cf_get("/mods/search", queryp);
    cJSON *items = cf_items(d);
    cJSON *m;
    cJSON_ArrayForEach(m, items) {
        if (!world_cat_hit(m, cat)) continue;
        cJSON_AddItemToArray(out, row_from_cf_world(m));
        if (cJSON_GetArraySize(out) >= 30) break;
    }
    cJSON_Delete(d);
    return out;
}

static const char *detect_loader(const char *inst) {
    cJSON *ids = NULL;
    instance_installed_ids(inst, &ids);
    const char *r = NULL;
    cJSON *it;
    cJSON_ArrayForEach(it, ids) {
        const char *v = it->valuestring;
        if (pymcl_icontains(v, "fabric")) r = "fabric";
        else if (pymcl_icontains(v, "quilt")) r = "quilt";
        else if (pymcl_icontains(v, "neoforge")) r = "neoforge";
        else if (pymcl_icontains(v, "forge")) r = "forge";
    }
    cJSON_Delete(ids);
    return r;
}

static char *detect_mc(const char *inst) {
    cJSON *m = instance_meta(inst);
    const char *mc = cJSON_GetStringValue(cJSON_GetObjectItem(m, "mc_version"));
    char *r = NULL;
    if (mc && mc[0]) {
        /* strip loader suffix */
        char buf[64]; snprintf(buf, sizeof(buf), "%s", mc);
        char *d = strchr(buf, '-'); if (d) *d = 0;
        r = pymcl_strdup(buf);
    }
    cJSON_Delete(m);
    if (r) return r;
    cJSON *ids = NULL;
    instance_installed_ids(inst, &ids);
    if (cJSON_GetArraySize(ids) > 0) {
        const char *v = cJSON_GetArrayItem(ids, 0)->valuestring;
        char buf[64]; snprintf(buf, sizeof(buf), "%s", v);
        char *d = strchr(buf, '-'); if (d) *d = 0;
        r = pymcl_strdup(buf);
    }
    cJSON_Delete(ids);
    return r;
}

static int install_modrinth_mod(const char *inst, const char *slug, pymcl_ctx *ctx) {
    char url[256];
    char lmsg[256];
    snprintf(lmsg, sizeof(lmsg), "从 Modrinth 下载模组 %s", slug ? slug : "");
    emit(ctx, lmsg);
    snprintf(url, sizeof(url), MODRINTH_API "/project/%s/version", slug);
    cJSON *vers = http_get_json(url, 45);
    if (!cJSON_IsArray(vers) || cJSON_GetArraySize(vers) == 0) {
        cJSON_Delete(vers);
        pymcl_set_error("模组 %s 没有可下载版本", slug);
        emit(ctx, pymcl_error());
        return -1;
    }
    char *mc = detect_mc(inst);
    const char *loader = detect_loader(inst);
    cJSON *chosen = cJSON_GetArrayItem(vers, 0);
    cJSON *v;
    cJSON_ArrayForEach(v, vers) {
        int ok_mc = !mc, ok_ld = !loader;
        cJSON *gv, *ld;
        cJSON_ArrayForEach(gv, cJSON_GetObjectItem(v, "game_versions"))
            if (mc && cJSON_IsString(gv) && strcmp(gv->valuestring, mc) == 0) ok_mc = 1;
        cJSON_ArrayForEach(ld, cJSON_GetObjectItem(v, "loaders"))
            if (loader && cJSON_IsString(ld) && pymcl_ieq(ld->valuestring, loader)) ok_ld = 1;
        if (ok_mc && ok_ld) { chosen = v; break; }
    }
    free(mc);
    cJSON *files = cJSON_GetObjectItem(chosen, "files");
    cJSON *file = NULL, *f;
    cJSON_ArrayForEach(f, files) if (cJSON_IsTrue(cJSON_GetObjectItem(f, "primary"))) file = f;
    if (!file && cJSON_GetArraySize(files) > 0) file = cJSON_GetArrayItem(files, 0);
    if (!file) { cJSON_Delete(vers); pymcl_set_error("没有可下载文件"); emit(ctx, pymcl_error()); return -1; }
    const char *fn = cJSON_GetStringValue(cJSON_GetObjectItem(file, "filename"));
    const char *u = cJSON_GetStringValue(cJSON_GetObjectItem(file, "url"));
    char dest[PYMCL_PATH], ip[PYMCL_PATH];
    instance_path(inst, ip, sizeof(ip));
    instance_ensure_dirs(inst);
    pymcl_path_join3(dest, sizeof(dest), ip, "mods", fn ? fn : "mod.jar");
    snprintf(lmsg, sizeof(lmsg), "下载 %s", fn ? fn : "mod.jar");
    emit(ctx, lmsg);
    char mir[1024];
    mirror_mr(u, mir, sizeof(mir));
    const char *ex[] = { u };
    int r = download_file(mir, ex, 1, dest, ctx,
                          cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(file, "hashes"), "sha1")),
                          -1,
                          cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(file, "hashes"), "sha512")));
    cJSON_Delete(vers);
    if (r != 0) { emit(ctx, pymcl_error()); return -1; }
    snprintf(lmsg, sizeof(lmsg), "安装完成: %s", fn ? fn : "mod.jar");
    emit(ctx, lmsg);
    return 0;
}

static void cf_cdn(long long fid, const char *fn, const char *host, char *out, size_t n) {
    snprintf(out, n, "https://%s/files/%lld/%lld/%s", host, fid / 1000, fid % 1000, fn ? fn : "file.jar");
}

/* extra.id 可能是数字（Python 桥 JSON 里是 int）也可能是字符串（UI 传值不稳），
   宽松取数：两种都认，避免掉到 Modrinth 分支拿 CF slug 去查 Modrinth。 */
static int extra_id(cJSON *extra, long long *out) {
    cJSON *id = extra ? cJSON_GetObjectItem(extra, "id") : NULL;
    if (cJSON_IsNumber(id)) { if (out) *out = (long long)id->valuedouble; return 1; }
    if (cJSON_IsString(id) && id->valuestring && id->valuestring[0]) {
        if (out) *out = atoll(id->valuestring);
        return 1;
    }
    return 0;
}

static int install_cf_mod(const char *inst, long long addon, pymcl_ctx *ctx) {
    char lmsg[256];
    snprintf(lmsg, sizeof(lmsg), "从 CurseForge 下载模组 id=%lld", addon);
    emit(ctx, lmsg);
    char path[64]; snprintf(path, sizeof(path), "/mods/%lld", addon);
    cJSON *d = cf_get(path, NULL);
    cJSON *mod = d ? cJSON_GetObjectItem(d, "data") : NULL;
    if (!cJSON_IsObject(mod)) {
        cJSON_Delete(d);
        pymcl_set_error("获取 CurseForge 详情失败（id=%lld）", addon);
        emit(ctx, pymcl_error());
        return -1;
    }
    cJSON *files = cJSON_GetObjectItem(mod, "latestFiles");
    if (!cJSON_IsArray(files) || cJSON_GetArraySize(files) == 0) {
        char p2[80]; snprintf(p2, sizeof(p2), "/mods/%lld/files", addon);
        cJSON *fl = cf_get(p2, "pageSize=50");
        files = cf_items(fl);
        /* leak fl with d - keep both */
        if (!files) { cJSON_Delete(d); cJSON_Delete(fl); pymcl_set_error("没有可下载文件"); emit(ctx, pymcl_error()); return -1; }
        /* use fl as owner via attaching */
        cJSON_AddItemToObject(d, "_files", fl);
        files = cf_items(fl);
    }
    cJSON *f = cJSON_GetArrayItem(files, 0);
    long long fid = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(f, "id"));
    const char *fn = cJSON_GetStringValue(cJSON_GetObjectItem(f, "fileName")) ?: "mod.jar";
    const char *du = cJSON_GetStringValue(cJSON_GetObjectItem(f, "downloadUrl"));
    char dest[PYMCL_PATH], ip[PYMCL_PATH];
    instance_path(inst, ip, sizeof(ip));
    instance_ensure_dirs(inst);
    pymcl_path_join3(dest, sizeof(dest), ip, "mods", fn);
    snprintf(lmsg, sizeof(lmsg), "下载 %s", fn);
    emit(ctx, lmsg);
    char u1[512], u2[512], u3[512];
    cf_cdn(fid, fn, "mediafilez.forgecdn.net", u1, sizeof(u1));
    cf_cdn(fid, fn, "edge.forgecdn.net", u2, sizeof(u2));
    snprintf(u3, sizeof(u3), CF_OFFICIAL "/mods/%lld/files/%lld/download", addon, fid);
    const char *first = du && du[0] ? du : u1;
    const char *ex[4]; int ne = 0;
    if (first != u1) ex[ne++] = u1;
    ex[ne++] = u2; ex[ne++] = u3;
    int r = download_file(first, ex, ne, dest, ctx, NULL, -1, NULL);
    cJSON_Delete(d);
    if (r != 0) { emit(ctx, pymcl_error()); return -1; }
    snprintf(lmsg, sizeof(lmsg), "安装完成: %s", fn);
    emit(ctx, lmsg);
    return 0;
}

int install_mod(const char *instance, const char *name, cJSON *extra, pymcl_ctx *ctx) {
    instance_ensure_dirs(instance);
    const char *path = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "path")) : NULL;
    const char *url = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "url")) : NULL;
    const char *src = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "source")) : NULL;
    emit(ctx, "安装模组到实例 mods 目录");
    if (path && pymcl_file_exists(path)) {
        char dest[PYMCL_PATH], ip[PYMCL_PATH];
        instance_path(instance, ip, sizeof(ip));
        pymcl_path_join3(dest, sizeof(dest), ip, "mods", pymcl_basename(path));
        char cpmsg[PYMCL_PATH * 2 + 96];
        snprintf(cpmsg, sizeof(cpmsg), "复制本地模组文件: %s", pymcl_basename(path));
        emit(ctx, cpmsg);
        if (pymcl_copy_file(path, dest) != 0) {
            /* pymcl_copy_file 失败时不写 g_err，直接用 pymcl_error() 会打印上一条残留
               错误（或空串）——这里显式给出来源/目标与 GetLastError。 */
            DWORD e = GetLastError();
            snprintf(cpmsg, sizeof(cpmsg), "复制失败: %s -> %s (Win32 %lu)", path, dest, (unsigned long)e);
            pymcl_set_error("%s", cpmsg);
            emit(ctx, cpmsg);
            return -1;
        }
        emit(ctx, "模组安装完成");
        return 0;
    }
    if (url && pymcl_startswith(url, "http")) {
        if (strstr(url, "modrinth.com/mod")) {
            const char *p = strstr(url, "/mod/");
            char slug[128] = {0};
            if (p) {
                p += 5; int i = 0;
                while (*p && *p != '/' && *p != '?' && i < 127) slug[i++] = *p++;
            }
            int r = install_modrinth_mod(instance, slug, ctx);
            if (r == 0) emit(ctx, "模组安装完成");
            return r;
        }
        if (strstr(url, "curseforge.com")) {
            /* treat as direct if .jar */
        }
        if (pymcl_endswith(url, ".jar")) {
            char dest[PYMCL_PATH], ip[PYMCL_PATH];
            instance_path(instance, ip, sizeof(ip));
            const char *bn = pymcl_basename(url);
            if (!bn || !bn[0]) {
                char umsg[PYMCL_PATH + 64];
                snprintf(umsg, sizeof(umsg), "无法从 URL 解析文件名: %s", url);
                pymcl_set_error("%s", umsg);
                emit(ctx, umsg);
                return -1;
            }
            pymcl_path_join3(dest, sizeof(dest), ip, "mods", bn);
            emit(ctx, "下载模组文件");
            if (download_file(url, NULL, 0, dest, ctx, NULL, -1, NULL) != 0) { emit(ctx, pymcl_error()); return -1; }
            emit(ctx, "模组安装完成");
            return 0;
        }
        /* 是 http(s) 但不是 modrinth 主页、也不以 .jar 结尾（如 CF 项目页）：
           以前这里静默落到下面的 slug 分支，最终报「无法解析模组」。给出具体原因。 */
        {
            char umsg[PYMCL_PATH + 64];
            snprintf(umsg, sizeof(umsg), "不支持的模组 URL（非 .jar 直链）: %s", url);
            pymcl_set_error("%s", umsg);
            emit(ctx, umsg);
            return -1;
        }
    }
    long long cfid = 0;
    if (src && pymcl_startswith(src, "curse") && extra && extra_id(extra, &cfid)) {
        int r = install_cf_mod(instance, cfid, ctx);
        if (r == 0) emit(ctx, "模组安装完成");
        return r;
    }
    const char *slug = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "slug")) : NULL;
    if (!slug) slug = name;
    if (slug && slug[0]) {
        int r = install_modrinth_mod(instance, slug, ctx);
        if (r == 0) emit(ctx, "模组安装完成");
        return r;
    }
    {
        char umsg[512];
        snprintf(umsg, sizeof(umsg),
                 "无法解析模组（name=\"%s\" path=%s url=%s source=%s slug=%s）",
                 name ? name : "", path ? path : "-", url ? url : "-",
                 src ? src : "-", (slug && slug[0]) ? slug : "-");
        pymcl_set_error("%s", umsg);
        emit(ctx, umsg);
    }
    return -1;
}

static const char *kind_subdir(const char *kind) {
    if (strcmp(kind, "shader") == 0) return "shaderpacks";
    if (strcmp(kind, "resourcepack") == 0) return "resourcepacks";
    if (strcmp(kind, "datapack") == 0) return "datapacks";
    return "mods";
}

int install_content(const char *kind, const char *instance, const char *name, cJSON *extra, pymcl_ctx *ctx) {
    const char *subdir = kind_subdir(kind);
    instance_ensure_dirs(instance);
    const char *path = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "path")) : NULL;
    const char *url = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "url")) : NULL;
    char ip[PYMCL_PATH], dest[PYMCL_PATH];
    instance_path(instance, ip, sizeof(ip));
    {
        char msg[PYMCL_PATH + 64];
        snprintf(msg, sizeof(msg), "安装到 %s/%s", instance, subdir);
        emit(ctx, msg);
    }
    if (path && pymcl_file_exists(path)) {
        pymcl_path_join3(dest, sizeof(dest), ip, subdir, pymcl_basename(path));
        char msg[PYMCL_PATH * 2 + 96];
        snprintf(msg, sizeof(msg), "复制本地文件 %s", pymcl_basename(path));
        emit(ctx, msg);
        if (pymcl_copy_file(path, dest) != 0) {
            /* pymcl_copy_file 失败不写 g_err；显式带出来源/目标/Win32 码，避免 pymcl_error()
               打出上一条残留错误或空串（任务日志看起来「什么都没说」）。 */
            DWORD e = GetLastError();
            snprintf(msg, sizeof(msg), "复制失败: %s -> %s (Win32 %lu)", path, dest, (unsigned long)e);
            pymcl_set_error("%s", msg);
            emit(ctx, msg);
            return -1;
        }
        snprintf(msg, sizeof(msg), "安装完成: %s", pymcl_basename(path));
        emit(ctx, msg);
        return 0;
    }
    if (url && pymcl_startswith(url, "http")) {
        const char *bn = pymcl_basename(url);
        if (!bn || !bn[0]) {
            char msg[PYMCL_PATH + 64];
            snprintf(msg, sizeof(msg), "无法从 URL 解析文件名: %s", url);
            pymcl_set_error("%s", msg);
            emit(ctx, msg);
            return -1;
        }
        pymcl_path_join3(dest, sizeof(dest), ip, subdir, bn);
        char msg[PYMCL_PATH + 64];
        snprintf(msg, sizeof(msg), "下载 %s", bn);
        emit(ctx, msg);
        if (download_file(url, NULL, 0, dest, ctx, NULL, -1, NULL) != 0) {
            emit(ctx, pymcl_error());
            return -1;
        }
        snprintf(msg, sizeof(msg), "安装完成: %s", pymcl_basename(url));
        emit(ctx, msg);
        return 0;
    }
    const char *src = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "source")) : NULL;
    long long cfid = 0;
    if (src && pymcl_startswith(src, "curse") && extra && extra_id(extra, &cfid)) {
        char msg[PYMCL_PATH + 64];
        snprintf(msg, sizeof(msg), "从 CurseForge 下载资源 id=%lld", cfid);
        emit(ctx, msg);
        char pth[64]; snprintf(pth, sizeof(pth), "/mods/%lld", cfid);
        cJSON *d = cf_get(pth, NULL);
        cJSON *mod = d ? cJSON_GetObjectItem(d, "data") : NULL;
        cJSON *files = mod ? cJSON_GetObjectItem(mod, "latestFiles") : NULL;
        cJSON *f = files && cJSON_GetArraySize(files) ? cJSON_GetArrayItem(files, 0) : NULL;
        if (!f) {
            cJSON_Delete(d);
            pymcl_set_error("CurseForge 没有可下载文件（id=%lld）", cfid);
            emit(ctx, pymcl_error());
            return -1;
        }
        const char *fn = cJSON_GetStringValue(cJSON_GetObjectItem(f, "fileName")) ?: "pack.zip";
        const char *du = cJSON_GetStringValue(cJSON_GetObjectItem(f, "downloadUrl"));
        pymcl_path_join3(dest, sizeof(dest), ip, subdir, fn);
        snprintf(msg, sizeof(msg), "下载 %s", fn);
        emit(ctx, msg);
        long long fid = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(f, "id"));
        char u1[512], u2[512];
        cf_cdn(fid, fn, "mediafilez.forgecdn.net", u1, sizeof(u1));
        cf_cdn(fid, fn, "edge.forgecdn.net", u2, sizeof(u2));
        const char *first = du && du[0] ? du : u1;
        const char *ex[3]; int ne = 0;
        if (du && du[0]) { ex[ne++] = u1; ex[ne++] = u2; }
        else { ex[ne++] = u2; }
        int r = download_file(first, ex, ne, dest, ctx, NULL, -1, NULL);
        cJSON_Delete(d);
        if (r != 0) { emit(ctx, pymcl_error()); return -1; }
        snprintf(msg, sizeof(msg), "安装完成: %s", fn);
        emit(ctx, msg);
        return 0;
    }
    const char *slug = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "slug")) : NULL;
    if (!slug) slug = name;
    char u[256];
    char want_vid[128] = {0};
    if (extra) {
        const char *vid = cJSON_GetStringValue(cJSON_GetObjectItem(extra, "version_id"));
        if (vid && vid[0]) snprintf(want_vid, sizeof(want_vid), "%s", vid);
    }
    /* 四条来源都没命中（本地 path 不存在、非 http url、非 CF id、slug 也空）：
       以前会带着空 slug 去请求 /project//version，最终报「没有可下载版本」，
       完全看不出是「根本没给可安装的东西」。这里直接说清收到的是什么。 */
    if ((!slug || !slug[0]) && !want_vid[0]) {
        char msg[512];
        snprintf(msg, sizeof(msg),
                 "无法解析安装来源（kind=%s instance=%s name=\"%s\" path=%s url=%s）",
                 kind ? kind : "", instance ? instance : "", name ? name : "",
                 path ? path : "-", url ? url : "-");
        pymcl_set_error("%s", msg);
        emit(ctx, msg);
        return -1;
    }
    {
        char msg[256];
        snprintf(msg, sizeof(msg), "从 Modrinth 下载 %s", (slug && slug[0]) ? slug : want_vid);
        emit(ctx, msg);
    }
    cJSON *vers = NULL;
    if (want_vid[0]) {
        /* 前端选了具体文件：先按版本 id 精确取，取不到再退回最新版 */
        snprintf(u, sizeof(u), MODRINTH_API "/version/%s", want_vid);
        cJSON *one = http_get_json(u, 45);
        if (cJSON_IsObject(one)) { vers = cJSON_CreateArray(); cJSON_AddItemToArray(vers, one); }
        else cJSON_Delete(one);
    }
    if (!vers) {
        snprintf(u, sizeof(u), MODRINTH_API "/project/%s/version", slug);
        vers = http_get_json(u, 45);
    }
    if (!cJSON_IsArray(vers) || cJSON_GetArraySize(vers) == 0) {
        cJSON_Delete(vers);
        pymcl_set_error("%s 没有可下载版本", slug ? slug : "");
        emit(ctx, pymcl_error());
        return -1;
    }
    cJSON *files = cJSON_GetObjectItem(cJSON_GetArrayItem(vers, 0), "files");
    cJSON *file = cJSON_GetArraySize(files) ? cJSON_GetArrayItem(files, 0) : NULL;
    const char *fn = file ? cJSON_GetStringValue(cJSON_GetObjectItem(file, "filename")) : "pack.zip";
    const char *du = file ? cJSON_GetStringValue(cJSON_GetObjectItem(file, "url")) : NULL;
    if (!du) {
        cJSON_Delete(vers);
        pymcl_set_error("%s 的文件没有下载地址", slug ? slug : "");
        emit(ctx, pymcl_error());
        return -1;
    }
    pymcl_path_join3(dest, sizeof(dest), ip, subdir, fn);
    {
        char msg[256];
        snprintf(msg, sizeof(msg), "下载 %s", fn);
        emit(ctx, msg);
    }
    char mir[1024];
    mirror_mr(du, mir, sizeof(mir));
    const char *ex[] = { du };
    int r = download_file(mir, ex, 1, dest, ctx, NULL, -1, NULL);
    cJSON_Delete(vers);
    if (r != 0) { emit(ctx, pymcl_error()); return -1; }
    {
        char msg[256];
        snprintf(msg, sizeof(msg), "安装完成: %s", fn);
        emit(ctx, msg);
    }
    return 0;
}

/* ---------- 世界安装（mclauncher/worlds.py 的移植） ---------- */

/* saves_root：开了存档隔离的版本落到 versions/<id>/saves，否则是实例的 saves。
   version_id 从 extra.version 取（前端 CatalogPage 的世界页在装之前会弹
   「装进哪里」，把选中的版本写进 extra["version"]；FileDrop 也带 version）。 */
static void world_saves_root(const char *inst, const char *version, char *out, size_t n) {
    char base[PYMCL_PATH];
    if (version && version[0]) {
        cJSON *s = version_settings_load(inst, version);
        version_game_dir(inst, version, s, base, sizeof(base));
        cJSON_Delete(s);
    } else {
        instance_path(inst, base, sizeof(base));
    }
    pymcl_path_join(out, n, base, "saves");
}

/* _extract_world：zip 解到 dest_root；根目录直接有 level.dat 时套一层存档名
   （Minecraft 只认 saves/<world>/level.dat，不认 saves/level.dat）。
   非 zip 按单文件存档处理：建 <stem>/ 放原文件。返回顶层名数组（调用方 delete）。 */
static cJSON *world_extract(const char *archive, const char *dest_root, int *rc) {
    *rc = 0;
    const char *base = pymcl_basename(archive);
    char stem[512];
    snprintf(stem, sizeof(stem), "%s", base);
    char *dot = strrchr(stem, '.');
    if (dot && dot != stem) *dot = 0;
    if (!pymcl_endswith(base, ".zip")) {
        char dest[PYMCL_PATH], file[PYMCL_PATH];
        pymcl_path_join(dest, sizeof(dest), dest_root, stem);
        pymcl_ensure_dir(dest);
        pymcl_path_join(file, sizeof(file), dest, base);
        if (pymcl_copy_file(archive, file) != 0) {
            pymcl_set_error("复制世界文件失败: %s", base);
            *rc = -1;
            return NULL;
        }
        cJSON *files = cJSON_CreateArray();
        cJSON_AddItemToArray(files, cJSON_CreateString(stem));
        return files;
    }
    cJSON *names = pymcl_zip_entries(archive);
    if (!names) {
        pymcl_set_error("世界压缩包损坏: %s", base);
        *rc = -1;
        return NULL;
    }
    if (cJSON_GetArraySize(names) == 0) {
        cJSON_Delete(names);
        pymcl_set_error("空的世界压缩包");
        *rc = -1;
        return NULL;
    }
    /* 根有 level.dat（Python worlds.py:101 的 any(parts == ["level.dat"])，
       parts 是去掉空段与 "." 之后的路径段）→ 整个包就是一个世界，套一层 stem 目录 */
    int root_level = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, names) {
        const char *nm = it->valuestring;
        while (*nm == '/') nm++;
        while (nm[0] == '.' && nm[1] == '/') nm += 2;
        if (pymcl_ieq(nm, "level.dat")) { root_level = 1; break; }
    }
    /* 暂存目录名带进程内自增序号：同一个存档连装两次（或两个世界任务并发）
       落在同一秒时，光用 time() 会撞名，后一个的 remove_tree 会把前一个正在
       解压的目录删掉。 */
    static volatile long g_world_tmp_n = 0;
    char staging[PYMCL_PATH];
    snprintf(staging, sizeof(staging), "%s\\.world-tmp-%lld-%ld", dest_root,
             (long long)time(NULL), (long)InterlockedIncrement(&g_world_tmp_n));
    pymcl_remove_tree(staging);
    pymcl_ensure_dir(staging);
    if (pymcl_extract_zip(archive, staging) != 0) {
        pymcl_remove_tree(staging);
        cJSON_Delete(names);
        *rc = -1;
        return NULL;
    }
    /* 顶层目录名（Python 的 top = {parts[0]}，用来当安装结果里的 files） */
    cJSON *top = cJSON_CreateArray();
    cJSON *tops = pymcl_list_dir(staging, -1, 1);
    if (root_level) {
        cJSON_AddItemToArray(top, cJSON_CreateString(stem));
    } else {
        cJSON_ArrayForEach(it, tops) {
            int seen = 0;
            cJSON *e;
            cJSON_ArrayForEach(e, top)
                if (strcmp(e->valuestring, it->valuestring) == 0) { seen = 1; break; }
            if (!seen) cJSON_AddItemToArray(top, cJSON_CreateString(it->valuestring));
        }
    }
    char final_root[PYMCL_PATH];
    if (root_level) {
        pymcl_path_join(final_root, sizeof(final_root), dest_root, stem);
    } else {
        snprintf(final_root, sizeof(final_root), "%s", dest_root);
    }
    pymcl_ensure_dir(final_root);
    /* 逐个顶层项搬进目标（同名先删，保持与 Python 一致的覆盖语义） */
    int nmoved = 0;
    cJSON_ArrayForEach(it, tops) {
        char src[PYMCL_PATH], dst[PYMCL_PATH];
        pymcl_path_join(src, sizeof(src), staging, it->valuestring);
        pymcl_path_join(dst, sizeof(dst), final_root, it->valuestring);
        if (pymcl_path_exists(dst)) pymcl_remove_tree(dst);
        wchar_t *ws = pymcl_u8_to_wide(src), *wd = pymcl_u8_to_wide(dst);
        BOOL ok = (ws && wd) ? MoveFileExW(ws, wd, MOVEFILE_COPY_ALLOWED) : FALSE;
        free(ws); free(wd);
        if (!ok) {
            /* 跨盘/占用时退回递归复制 */
            if (pymcl_dir_exists(src)) pymcl_copy_tree(src, dst);
            else pymcl_copy_file(src, dst);
        }
        nmoved++;
    }
    cJSON_Delete(tops);
    cJSON_Delete(names);
    pymcl_remove_tree(staging);
    if (nmoved == 0) {
        cJSON_Delete(top);
        pymcl_set_error("世界压缩包里没有可安装的文件");
        *rc = -1;
        return NULL;
    }
    /* 返回的是存档目录名集合（Python 的 top）：根有 level.dat 时是套出来的
       <stem>，否则是包里的顶层目录名。任务文案「已安装世界 X」用的就是这个。 */
    return top;
}

/* install_world：本地 path / 直链 url / CurseForge id 三种来源，装进 saves。
   与 mclauncher/worlds.py 的 install_world 同序：path → url → id(+file_id)。
   世界是 CurseForge 独占，没有 Modrinth 分支（Python 侧也不查 MR）。 */
int install_world(const char *instance, const char *name, cJSON *extra, pymcl_ctx *ctx,
                  char *msg, size_t msgn) {
    instance_ensure_dirs(instance);
    const char *path = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "path")) : NULL;
    const char *url = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "url")) : NULL;
    const char *ver = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "version")) : NULL;
    char dest_root[PYMCL_PATH];
    world_saves_root(instance, ver ? ver : "", dest_root, sizeof(dest_root));
    pymcl_ensure_dir(dest_root);
    {
        char m[PYMCL_PATH + 64];
        snprintf(m, sizeof(m), "安装世界到 %s", dest_root);
        emit(ctx, m);
    }

    /* 1) 本地文件 */
    if (path && pymcl_file_exists(path)) {
        char m[PYMCL_PATH * 2 + 96];
        snprintf(m, sizeof(m), "解压本地世界 %s", pymcl_basename(path));
        emit(ctx, m);
        int rc = 0;
        cJSON *files = world_extract(path, dest_root, &rc);
        if (rc != 0) { emit(ctx, pymcl_error()); return -1; }
        char joined[2048] = "";
        cJSON *it;
        cJSON_ArrayForEach(it, files) {
            if (joined[0]) strncat(joined, ", ", sizeof(joined) - strlen(joined) - 1);
            strncat(joined, it->valuestring, sizeof(joined) - strlen(joined) - 1);
        }
        cJSON_Delete(files);
        if (msg && msgn) {
            if (joined[0]) tr_fmt0(msg, msgn, "已安装世界 {0}", joined);
            else snprintf(msg, msgn, "%s", name ? name : "");
        }
        char m2[2048];
        snprintf(m2, sizeof(m2), "安装完成: %s", joined[0] ? joined : (name ? name : ""));
        emit(ctx, m2);
        return 0;
    }

    /* 2) 直链（Python：str(url).startswith("http")，落到 cache/ 再解压） */
    if (url && pymcl_startswith(url, "http")) {
        char cache[PYMCL_PATH], tmp[PYMCL_PATH];
        pymcl_cache_dir(cache, sizeof(cache));
        pymcl_ensure_dir(cache);
        const char *bn = pymcl_basename(url);
        char fn[512];
        snprintf(fn, sizeof(fn), "%s", (bn && bn[0]) ? bn : "world.zip");
        char *q = strchr(fn, '?');
        if (q) *q = 0;
        if (!fn[0]) snprintf(fn, sizeof(fn), "world.zip");
        pymcl_path_join(tmp, sizeof(tmp), cache, fn);
        {
            char m[PYMCL_PATH + 64];
            snprintf(m, sizeof(m), "下载世界 %s", fn);
            emit(ctx, m);
        }
        if (download_file(url, NULL, 0, tmp, ctx, NULL, -1, NULL) != 0) {
            emit(ctx, pymcl_error());
            return -1;
        }
        int rc = 0;
        cJSON *files = world_extract(tmp, dest_root, &rc);
        if (rc != 0) { emit(ctx, pymcl_error()); return -1; }
        char joined[2048] = "";
        cJSON *it;
        cJSON_ArrayForEach(it, files) {
            if (joined[0]) strncat(joined, ", ", sizeof(joined) - strlen(joined) - 1);
            strncat(joined, it->valuestring, sizeof(joined) - strlen(joined) - 1);
        }
        cJSON_Delete(files);
        if (msg && msgn) {
            if (joined[0]) tr_fmt0(msg, msgn, "已安装世界 {0}", joined);
            else snprintf(msg, msgn, "%s", name ? name : "");
        }
        {
            char m2[2048];
            snprintf(m2, sizeof(m2), "安装完成: %s", joined[0] ? joined : (name ? name : ""));
            emit(ctx, m2);
        }
        return 0;
    }

    /* 3) CurseForge 项目 id（世界没有 Modrinth 源） */
    long long addon = 0;
    if (!extra_id(extra, &addon)) {
        pymcl_set_error("缺少 CurseForge 世界项目 id");
        emit(ctx, pymcl_error());
        return -1;
    }
    long long want_file = 0;
    {
        cJSON *fid = extra ? cJSON_GetObjectItem(extra, "file_id") : NULL;
        if (!fid) fid = extra ? cJSON_GetObjectItem(extra, "version_id") : NULL;
        if (cJSON_IsNumber(fid)) want_file = (long long)fid->valuedouble;
        else if (cJSON_IsString(fid) && fid->valuestring && fid->valuestring[0])
            want_file = atoll(fid->valuestring);
    }
    char pth[80];
    snprintf(pth, sizeof(pth), "/mods/%lld/files", addon);
    char fq[256];
    /* 选了具体文件就拉全一点再按 id 挑；没选就按 game_version 过滤取最新 */
    const char *gv = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "game_version")) : NULL;
    if (!gv || !gv[0]) gv = extra ? cJSON_GetStringValue(cJSON_GetObjectItem(extra, "mc_version")) : NULL;
    if (gv && (pymcl_ieq(gv, "全部") || pymcl_ieq(gv, "all"))) gv = "";
    if (want_file) snprintf(fq, sizeof(fq), "pageSize=50&index=0");
    else if (gv && gv[0]) {
        char gvenc[128];
        url_encode(gv, gvenc, sizeof(gvenc));
        snprintf(fq, sizeof(fq), "pageSize=50&index=0&gameVersion=%s", gvenc);
    } else snprintf(fq, sizeof(fq), "pageSize=50&index=0");
    {
        char m[128];
        snprintf(m, sizeof(m), "从 CurseForge 获取世界文件 id=%lld", addon);
        emit(ctx, m);
    }
    cJSON *fl = cf_get(pth, fq);
    cJSON *files = cf_items(fl);
    if (!files || cJSON_GetArraySize(files) == 0) {
        cJSON_Delete(fl);
        pymcl_set_error("该世界没有可下载文件");
        emit(ctx, pymcl_error());
        return -1;
    }
    cJSON *chosen = NULL, *f;
    if (want_file) {
        cJSON_ArrayForEach(f, files)
            if ((long long)cJSON_GetNumberValue(cJSON_GetObjectItem(f, "id")) == want_file) { chosen = f; break; }
        if (!chosen) {
            cJSON_Delete(fl);
            pymcl_set_error("找不到指定世界文件");
            emit(ctx, pymcl_error());
            return -1;
        }
    } else {
        chosen = cJSON_GetArrayItem(files, 0);
    }
    long long fid = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(chosen, "id"));
    const char *fn = cJSON_GetStringValue(cJSON_GetObjectItem(chosen, "fileName"));
    if (!fn || !fn[0]) {
        static _Thread_local char fnbuf[128];
        snprintf(fnbuf, sizeof(fnbuf), "world-%lld.zip", addon);
        fn = fnbuf;
    }
    const char *du = cJSON_GetStringValue(cJSON_GetObjectItem(chosen, "downloadUrl"));
    char cache[PYMCL_PATH], tmp[PYMCL_PATH];
    pymcl_cache_dir(cache, sizeof(cache));
    pymcl_ensure_dir(cache);
    pymcl_path_join(tmp, sizeof(tmp), cache, fn);
    /* 候选顺序照 cf_mod_download_urls：downloadUrl → 两个 CDN → 官方 download */
    char u1[512], u2[512], u3[512];
    cf_cdn(fid, fn, "mediafilez.forgecdn.net", u1, sizeof(u1));
    cf_cdn(fid, fn, "edge.forgecdn.net", u2, sizeof(u2));
    snprintf(u3, sizeof(u3), CF_OFFICIAL "/mods/%lld/files/%lld/download", addon, fid);
    const char *first = (du && du[0]) ? du : u1;
    const char *ex[4]; int ne = 0;
    if (first != u1) ex[ne++] = u1;
    ex[ne++] = u2; ex[ne++] = u3;
    {
        char m[PYMCL_PATH + 64];
        snprintf(m, sizeof(m), "下载世界 %s", fn);
        emit(ctx, m);
    }
    int r = download_file(first, ex, ne, tmp, ctx, NULL, -1, NULL);
    cJSON_Delete(fl);
    if (r != 0) { emit(ctx, pymcl_error()); return -1; }
    int rc = 0;
    cJSON *out_files = world_extract(tmp, dest_root, &rc);
    if (rc != 0) { emit(ctx, pymcl_error()); return -1; }
    char joined[2048] = "";
    cJSON *it;
    cJSON_ArrayForEach(it, out_files) {
        if (joined[0]) strncat(joined, ", ", sizeof(joined) - strlen(joined) - 1);
        strncat(joined, it->valuestring, sizeof(joined) - strlen(joined) - 1);
    }
    cJSON_Delete(out_files);
    if (msg && msgn) {
        if (joined[0]) tr_fmt0(msg, msgn, "已安装世界 {0}", joined);
        else snprintf(msg, msgn, "%s", name ? name : "");
    }
    {
        char m2[2048];
        snprintf(m2, sizeof(m2), "安装完成: %s", joined[0] ? joined : (name ? name : ""));
        emit(ctx, m2);
    }
    return 0;
}

cJSON *list_instance_files(const char *instance, const char *subdir) {
    cJSON *out = cJSON_CreateArray();
    char ip[PYMCL_PATH], dir[PYMCL_PATH];
    instance_path(instance, ip, sizeof(ip));
    pymcl_path_join(dir, sizeof(dir), ip, subdir);
    if (!pymcl_dir_exists(dir)) return out;
    wchar_t *w = pymcl_u8_to_wide(dir);
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    free(w);
    if (h == INVALID_HANDLE_VALUE) return out;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char *n = pymcl_wide_to_u8(fd.cFileName);
        if (pymcl_endswith(n, ".jar") || pymcl_endswith(n, ".zip")
            || pymcl_endswith(n, ".jar.disabled") || pymcl_endswith(n, ".zip.disabled"))
            cJSON_AddItemToArray(out, cJSON_CreateString(n));
        free(n);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return out;
}

/* 删除类方法的落点校验，口径与 mclauncher/mods.py 的 _mod_file_at /
   delete_content_file 对齐（Python 判据是 `(folder / filename).resolve().parent
   != folder` 就报「非法路径」）。两层：
     1. 文件名本身不许带分隔符 / 盘符 / `..` —— 正常资源包名不可能含这些，
        含了就是越界或 NTFS 数据流（`a.jar:evil`）写法；
     2. 规范化后必须正好落在 dir 的直接子项上 —— 纵深防御，dir 自身含 `..`
        或 8.3 短名时第 1 层挡不住。
   返回 0 时 out 里是拼好的待删路径。
   非 static（`mods_safe_child_path` 是给 ai_agent.c 的 read_artifact 复用的入口，
   审计 05 P1-5）。 */
static int safe_child_path(const char *dir, const char *filename, char *out, size_t n) {
    if (!filename || !filename[0]) { pymcl_set_error("非法路径: %s", filename ? filename : ""); return -1; }
    if (strstr(filename, "..") || strchr(filename, '/') || strchr(filename, '\\')
        || strchr(filename, ':')) {
        pymcl_set_error("非法路径: %s", filename);
        return -1;
    }
    char p[PYMCL_PATH];
    pymcl_path_join(p, sizeof(p), dir, filename);
    wchar_t *wd = pymcl_u8_to_wide(dir), *wc = pymcl_u8_to_wide(p);
    if (!wd || !wc) { free(wd); free(wc); pymcl_set_error("非法路径: %s", filename); return -1; }
    wchar_t fd[PYMCL_PATH], fc[PYMCL_PATH];
    DWORD nd = GetFullPathNameW(wd, PYMCL_PATH, fd, NULL);
    DWORD nc = GetFullPathNameW(wc, PYMCL_PATH, fc, NULL);
    free(wd); free(wc);
    if (!nd || nd >= PYMCL_PATH || !nc || nc >= PYMCL_PATH) {
        pymcl_set_error("非法路径: %s", filename);
        return -1;
    }
    size_t ld = wcslen(fd);
    while (ld > 0 && (fd[ld - 1] == L'\\' || fd[ld - 1] == L'/')) fd[--ld] = 0;
    if (ld == 0 || _wcsnicmp(fc, fd, ld) != 0 || (fc[ld] != L'\\' && fc[ld] != L'/')
        || wcschr(fc + ld + 1, L'\\') || wcschr(fc + ld + 1, L'/')) {
        pymcl_set_error("非法路径: %s", filename);
        return -1;
    }
    snprintf(out, n, "%s", p);
    return 0;
}

/* mods.py:1079 delete_content_file：`if p.is_file(): p.unlink()` —— 只处理普通文件，
   目录或已不存在的名字一律静默跳过（返回 None，不报错）。
   旧版这里无条件 pymcl_remove_tree(p)，同名目录会被**整棵递归删掉**，
   与 Python 语义不符，也超出了「删一个资源包」的授权范围。 */
int delete_instance_file(const char *instance, const char *subdir, const char *filename) {
    char ip[PYMCL_PATH], dir[PYMCL_PATH], p[PYMCL_PATH];
    if (instance_path(instance, ip, sizeof(ip)) != 0) return -1;
    pymcl_path_join(dir, sizeof(dir), ip, subdir);
    if (safe_child_path(dir, filename, p, sizeof(p)) != 0) return -1;
    if (pymcl_file_exists(p)) pymcl_remove_tree(p);
    return 0;
}

/* ---- 导出给 mod_update / catalog 模块复用 ---- */
void mods_mirror_mr(const char *url, char *out, size_t n) { mirror_mr(url, out, n); }
const char *mods_detect_loader(const char *inst) { return detect_loader(inst); }
char *mods_detect_mc(const char *inst) { return detect_mc(inst); }
/* safe_child_path 的公开入口：ai_agent.c 的 read_artifact 需要同一套落点校验
   （审计 05 P1-5）。语义与 static 版完全一致。 */
int mods_safe_child_path(const char *dir, const char *filename, char *out, size_t n) {
    return safe_child_path(dir, filename, out, n);
}

/* ---- content 中文别名查询（缺陷A）----
   catalog.c 里 catalog_lookup_mod/_pack 各写死一张表，没有通用入口；catalog.c
   属他人并发区，不改它。这里自持一份 catalog.json 的懒加载副本，按表名查
   shader_aliases / resourcepack_aliases / datapack_aliases。查找口径与
   catalog.c:lookup_map 完全一致：先 pymcl_ieq 精确，再 pymcl_icontains 双向包含。
   表项形状有 {slug,title} / {cf,title} / {cf,slug,title}，与 mod_aliases 同构。
   文件候选路径顺序与 catalog_init 相同，保证与 C 桥取到的是同一份。 */
static cJSON *g_content_cat;
static int g_content_cat_tried;

static void content_cat_load(void) {
    if (g_content_cat_tried) return;
    g_content_cat_tried = 1;
    const char *cands[4] = {NULL, NULL, NULL, NULL};
    char p1[PYMCL_PATH], p2[PYMCL_PATH], p3[PYMCL_PATH], p4[PYMCL_PATH];
    pymcl_path_join3(p1, sizeof(p1), g_root, "native", "data");
    pymcl_path_join(p1, sizeof(p1), p1, "catalog.json");
    pymcl_path_join3(p2, sizeof(p2), g_root, "data", "catalog.json");
    cands[0] = p1; cands[1] = p2;
    wchar_t wexe[PYMCL_PATH];
    if (GetModuleFileNameW(NULL, wexe, PYMCL_PATH)) {
        char *exe = pymcl_wide_to_u8(wexe);
        if (exe) {
            char dir[PYMCL_PATH];
            pymcl_parent(exe, dir, sizeof(dir));
            free(exe);
            pymcl_path_join(p3, sizeof(p3), dir, "catalog.json");
            pymcl_path_join3(p4, sizeof(p4), dir, "data", "catalog.json");
            cands[2] = p3; cands[3] = p4;
        }
    }
    for (int i = 0; i < 4; i++) {
        if (!cands[i] || !pymcl_file_exists(cands[i])) continue;
        g_content_cat = pymcl_read_json(cands[i]);
        if (g_content_cat) return;
    }
}

int catalog_lookup_named(const char *table, const char *q, char *slug, size_t ns,
                         long long *cf, char *title, size_t nt) {
    if (slug) slug[0] = 0;
    if (cf) *cf = 0;
    if (title) title[0] = 0;
    if (!table || !q || !q[0]) return 0;
    content_cat_load();
    cJSON *map = g_content_cat ? cJSON_GetObjectItem(g_content_cat, table) : NULL;
    if (!cJSON_IsObject(map)) return 0;
    cJSON *it = NULL;
    cJSON_ArrayForEach(it, map) {
        if (!it->string) continue;
        int exact = pymcl_ieq(it->string, q);
        int fuzzy = !exact && (pymcl_icontains(it->string, q) || pymcl_icontains(q, it->string));
        if (!exact && !fuzzy) continue;
        cJSON *s = cJSON_GetObjectItem(it, "slug");
        cJSON *c = cJSON_GetObjectItem(it, "cf");
        cJSON *t = cJSON_GetObjectItem(it, "title");
        if (slug && cJSON_IsString(s)) snprintf(slug, ns, "%s", s->valuestring);
        if (cf && cJSON_IsNumber(c)) *cf = (long long)c->valuedouble;
        if (title && cJSON_IsString(t)) snprintf(title, nt, "%s", t->valuestring);
        return 1;
    }
    return 0;
}
