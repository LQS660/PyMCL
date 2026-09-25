#include "pymcl.h"
#include <ctype.h>

/* 联网只读类 RPC（GOAL 附录 A 的 M2）：news.py、updater.check、loader_meta.py。 */

#define APP_VERSION "1.0.1"
#define FABRIC_META "https://meta.fabricmc.net/v2"
#define QUILT_META "https://meta.quiltmc.org/v3"
#define FORGE_MAVEN "https://maven.minecraftforge.net/net/minecraftforge/forge"
#define NEOFORGE_MAVEN "https://maven.neoforged.net/releases/net/neoforged/neoforge"
#define BMCLAPI "https://bmclapi2.bangbang93.com"

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

/* DownloadManager.fetch_json(url, expand=...)：按下载源展开镜像，逐个试 */
static cJSON *fetch_json(const char *url, int timeout, int expand) {
    if (!expand) {
        cJSON *j = http_get_json(url, timeout);
        return j;
    }
    char **urls = NULL;
    int n = 0;
    if (expand_urls(url, &urls, &n) != 0 || n == 0) return http_get_json(url, timeout);
    cJSON *j = fetch_json_mirrors((const char **)urls, n, timeout);
    free_urls(urls, n);
    return j;
}

static char *fetch_text(const char *url, int timeout, int expand) {
    if (!expand) {
        const char *one[1] = {url};
        return fetch_text_mirrors(one, 1, timeout);
    }
    char **urls = NULL;
    int n = 0;
    if (expand_urls(url, &urls, &n) != 0 || n == 0) {
        const char *one[1] = {url};
        return fetch_text_mirrors(one, 1, timeout);
    }
    char *t = fetch_text_mirrors((const char **)urls, n, timeout);
    free_urls(urls, n);
    return t;
}

/* 取前 n 个字符（码点） */
static void u8_head(const char *s, size_t max, char *out, size_t on, int *cut) {
    size_t chars = 0, i = 0;
    *cut = 0;
    for (; s[i]; i++) {
        if (((unsigned char)s[i] & 0xC0) != 0x80) {
            if (chars == max) { *cut = 1; break; }
            chars++;
        }
    }
    snprintf(out, on, "%.*s", (int)i, s);
}

static void strip_inplace(char *s) {
    char *a = s;
    while (*a && isspace((unsigned char)*a)) a++;
    if (a != s) memmove(s, a, strlen(a) + 1);
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
}

static cJSON *first_truthy(cJSON *o, const char *a, const char *b, const char *c) {
    cJSON *v = cJSON_GetObjectItem(o, a);
    if (py_truthy(v)) return v;
    v = cJSON_GetObjectItem(o, b);
    if (py_truthy(v)) return v;
    if (c) { v = cJSON_GetObjectItem(o, c); if (py_truthy(v)) return v; }
    return NULL;
}

/* news._rows_from */
static cJSON *news_rows(cJSON *payload) {
    cJSON *entries = NULL;
    if (cJSON_IsObject(payload)) {
        entries = cJSON_GetObjectItem(payload, "entries");
        if (!py_truthy(entries)) entries = cJSON_GetObjectItem(payload, "patchNotes");
    } else if (cJSON_IsArray(payload)) {
        entries = payload;
    }
    cJSON *rows = cJSON_CreateArray();
    int i = 0;
    cJSON *item;
    cJSON_ArrayForEach(item, entries) {
        if (i++ >= 12) break;
        if (!cJSON_IsObject(item)) continue;
        char title[1024] = "", body[4096] = "", version[256] = "", image[2048] = "", date[64] = "";
        cJSON *t = first_truthy(item, "title", "version", "id");
        if (t) py_str(t, title, sizeof(title));
        cJSON *b = first_truthy(item, "shortText", "body", "subtitle");
        if (b) {
            char raw[4096];
            py_str(b, raw, sizeof(raw));
            if (cJSON_IsString(b)) {
                int cut = 0;
                u8_head(raw, 160, body, sizeof(body) - 4, &cut);
                if (cut) strncat(body, "…", sizeof(body) - strlen(body) - 1);
            } else {
                snprintf(body, sizeof(body), "%s", raw);
            }
        }
        strip_inplace(body);
        cJSON *v = first_truthy(item, "version", "id", NULL);
        if (v) py_str(v, version, sizeof(version));
        cJSON *img = first_truthy(item, "image", "cardBackground", NULL);
        if (cJSON_IsObject(img)) {
            cJSON *u = cJSON_GetObjectItem(img, "url");
            if (py_truthy(u)) py_str(u, image, sizeof(image));
        } else if (cJSON_IsString(img)) {
            snprintf(image, sizeof(image), "%s", img->valuestring);
        }
        cJSON *d = first_truthy(item, "date", "updated_at", NULL);
        if (d) {
            char raw[256];
            int cut;
            py_str(d, raw, sizeof(raw));
            u8_head(raw, 10, date, sizeof(date), &cut);
        }
        cJSON *r = cJSON_CreateObject();
        cJSON_AddStringToObject(r, "title", title);
        cJSON_AddStringToObject(r, "body", body);
        cJSON_AddStringToObject(r, "version", version);
        cJSON_AddStringToObject(r, "image", image);
        cJSON_AddStringToObject(r, "date", date);
        cJSON_AddItemToArray(rows, r);
    }
    return rows;
}

static void news_cache_path(char *out, size_t n) { pymcl_path_join3(out, n, g_root, "cache", "news.json"); }

static cJSON *news_load_cached(void) {
    char p[PYMCL_PATH];
    news_cache_path(p, sizeof(p));
    cJSON *d = pymcl_read_json(p);
    if (cJSON_IsArray(d)) return d;
    if (cJSON_IsObject(d)) { cJSON *r = news_rows(d); cJSON_Delete(d); return r; }
    cJSON_Delete(d);
    return cJSON_CreateArray();
}

/* updater._parse / newer */
static void parse_ver(const char *v, long long out[4], int *n) {
    char buf[256];
    snprintf(buf, sizeof(buf), "%s", v && v[0] ? v : "0");
    for (char *p = buf; *p; p++) if (*p == '-') *p = '.';
    *n = 0;
    char *save = NULL;
    for (char *part = strtok_s(buf, ".", &save); ; part = strtok_s(NULL, ".", &save)) {
        if (!part) break;
        char num[64];
        size_t o = 0;
        for (char *q = part; *q && o + 1 < sizeof(num); q++) if (isdigit((unsigned char)*q)) num[o++] = *q;
        num[o] = 0;
        if (*n < 4) out[(*n)++] = o ? atoll(num) : 0;
        else (*n)++;
    }
    /* "".split(".") 至少有一段 */
    if (*n == 0) out[(*n)++] = 0;
    if (*n > 4) *n = 4;
    while (*n < 3) out[(*n)++] = 0;
}

static int version_newer(const char *remote, const char *local) {
    long long a[4] = {0}, b[4] = {0};
    int na, nb;
    parse_ver(remote, a, &na);
    parse_ver(local, b, &nb);
    int m = na < nb ? na : nb;
    for (int i = 0; i < m; i++) if (a[i] != b[i]) return a[i] > b[i];
    return na > nb;
}

static int valid_sha256(const char *s) {
    char t[128];
    snprintf(t, sizeof(t), "%s", s ? s : "");
    strip_inplace(t);
    if (strlen(t) != 64) return 0;
    for (int i = 0; i < 64; i++) if (!isxdigit((unsigned char)t[i])) return 0;
    return 1;
}

static cJSON *check_update(void) {
    char url[2048];
    cJSON *cfg = config_get("update_url");
    if (py_truthy(cfg)) py_str(cfg, url, sizeof(url));
    else snprintf(url, sizeof(url), "https://pymcl.dev/update.json");
    strip_inplace(url);
    cJSON *data = fetch_json(url, 12, 1);
    cJSON *o = cJSON_CreateObject();
    if (!data) {
        char msg[1024];
        snprintf(msg, sizeof(msg), "检查更新失败: %s", pymcl_error());
        cJSON_AddFalseToObject(o, "ok");
        cJSON_AddStringToObject(o, "current", APP_VERSION);
        cJSON_AddStringToObject(o, "latest", APP_VERSION);
        cJSON_AddFalseToObject(o, "has_update");
        cJSON_AddStringToObject(o, "message", msg);
        cJSON_AddStringToObject(o, "notes", "");
        cJSON_AddStringToObject(o, "url", "");
        return o;
    }
    char latest[256] = "", sha[256] = "", notes[8192] = "", dl[2048] = "";
    cJSON *v = first_truthy(data, "version", "latest", NULL);
    if (v) py_str(v, latest, sizeof(latest));
    int has = latest[0] && version_newer(latest, APP_VERSION);
    cJSON *s = cJSON_GetObjectItem(data, "sha256");
    if (py_truthy(s)) py_str(s, sha, sizeof(sha));
    strip_inplace(sha);
    for (char *p = sha; *p; p++) *p = (char)tolower((unsigned char)*p);
    int signed_update = has && valid_sha256(sha);
    int integrity_error = has && !signed_update;
    char msg[512];
    if (integrity_error) snprintf(msg, sizeof(msg), "更新清单缺少有效 SHA-256，已拒绝自动更新");
    else if (has) snprintf(msg, sizeof(msg), "发现 %s", latest);
    else snprintf(msg, sizeof(msg), "已是最新版本");
    cJSON *nt = first_truthy(data, "notes", "changelog", NULL);
    if (nt) py_str(nt, notes, sizeof(notes));
    cJSON *u = first_truthy(data, "url", "download", NULL);
    if (u) py_str(u, dl, sizeof(dl));
    cJSON_AddBoolToObject(o, "ok", !integrity_error);
    cJSON_AddStringToObject(o, "current", APP_VERSION);
    cJSON_AddStringToObject(o, "latest", latest[0] ? latest : APP_VERSION);
    cJSON_AddBoolToObject(o, "has_update", signed_update);
    cJSON_AddStringToObject(o, "message", msg);
    cJSON_AddStringToObject(o, "notes", notes);
    cJSON_AddStringToObject(o, "url", dl);
    cJSON_AddStringToObject(o, "sha256", sha);
    cJSON_Delete(data);
    return o;
}

/* ---------- loader_meta.list_loader_versions ---------- */

static cJSON *row3(const char *id, const char *label, int stable) {
    cJSON *r = cJSON_CreateObject();
    cJSON_AddStringToObject(r, "id", id);
    cJSON_AddStringToObject(r, "label", label);
    cJSON_AddBoolToObject(r, "stable", stable);
    return r;
}

/* installer.parse_maven_versions：取所有 <version> 文本 */
static cJSON *parse_maven_versions(const char *xml) {
    cJSON *out = cJSON_CreateArray();
    if (!xml) return out;
    const char *p = xml;
    while ((p = strstr(p, "<version>")) != NULL) {
        p += 9;
        const char *e = strstr(p, "</version>");
        if (!e) break;
        char v[256];
        snprintf(v, sizeof(v), "%.*s", (int)(e - p), p);
        strip_inplace(v);
        if (v[0]) cJSON_AddItemToArray(out, cJSON_CreateString(v));
        p = e;
    }
    return out;
}

/* installer.split_forge_artifact 里的 ver/branch */
static void split_forge(const char *full_in, const char *mc_in, char *ver, size_t vn, int *has_branch) {
    char full[256], mc[64];
    snprintf(full, sizeof(full), "%s", full_in);
    strip_inplace(full);
    snprintf(mc, sizeof(mc), "%s", mc_in ? mc_in : "");
    strip_inplace(mc);
    const char *rest = full;
    size_t ml = strlen(mc);
    if (ml && !strncmp(full, mc, ml) && full[ml] == '-') rest = full + ml + 1;
    else {
        const char *dash = strchr(full, '-');
        if (dash && isdigit((unsigned char)full[0])) {
            const char *q = full;
            while (isdigit((unsigned char)*q)) q++;
            if (*q == '.' && isdigit((unsigned char)q[1])) {
                snprintf(mc, sizeof(mc), "%.*s", (int)(dash - full), full);
                ml = strlen(mc);
                rest = dash + 1;
            }
        }
    }
    *has_branch = 0;
    size_t rl = strlen(rest);
    snprintf(ver, vn, "%s", rest);
    if (ml && rl > ml + 1 && rest[rl - ml - 1] == '-' && !strcmp(rest + rl - ml, mc)) {
        snprintf(ver, vn, "%.*s", (int)(rl - ml - 1), rest);
        *has_branch = 1;
    }
}

typedef struct { char id[256]; long long nums[16]; int nn; int branch; size_t len; } fkey;

static void forge_key(const char *full, const char *mc, fkey *k) {
    snprintf(k->id, sizeof(k->id), "%s", full);
    char ver[256];
    split_forge(full, mc, ver, sizeof(ver), &k->branch);
    k->nn = 0;
    for (const char *p = ver; *p;) {
        if (isdigit((unsigned char)*p)) {
            long long v = 0;
            while (isdigit((unsigned char)*p)) v = v * 10 + (*p++ - '0');
            if (k->nn < 16) k->nums[k->nn++] = v;
        } else p++;
    }
    k->len = strlen(full);
}

static int cmp_fkey_desc(const void *a, const void *b) {
    const fkey *x = (const fkey *)a, *y = (const fkey *)b;
    int m = x->nn < y->nn ? x->nn : y->nn;
    for (int i = 0; i < m; i++) if (x->nums[i] != y->nums[i]) return x->nums[i] < y->nums[i] ? 1 : -1;
    if (x->nn != y->nn) return x->nn < y->nn ? 1 : -1;
    if (x->branch != y->branch) return x->branch < y->branch ? 1 : -1;
    if (x->len != y->len) return x->len < y->len ? 1 : -1;
    return 0;
}

static int list_has(cJSON *a, const char *s) {
    cJSON *it;
    cJSON_ArrayForEach(it, a) if (!strcmp(it->valuestring, s)) return 1;
    return 0;
}

static cJSON *forge_versions(const char *mc) {
    char url[512];
    snprintf(url, sizeof(url), "%s/forge/minecraft/%s", BMCLAPI, mc);
    cJSON *found = cJSON_CreateArray();
    cJSON *data = fetch_json(url, 30, 1);
    cJSON *item;
    if (cJSON_IsArray(data)) {
        cJSON_ArrayForEach(item, data) {
            if (!cJSON_IsObject(item)) continue;
            char ver[128] = "", imc[64] = "", branch[64] = "", art[320];
            cJSON *v = cJSON_GetObjectItem(item, "version"), *m = cJSON_GetObjectItem(item, "mcversion"), *b = cJSON_GetObjectItem(item, "branch");
            if (py_truthy(v)) py_str(v, ver, sizeof(ver));
            if (py_truthy(m)) py_str(m, imc, sizeof(imc)); else snprintf(imc, sizeof(imc), "%s", mc);
            if (py_truthy(b)) py_str(b, branch, sizeof(branch));
            strip_inplace(ver); strip_inplace(imc); strip_inplace(branch);
            if (!ver[0]) continue;
            size_t il = strlen(imc);
            if (il && (!strcmp(ver, imc) || (!strncmp(ver, imc, il) && ver[il] == '-'))) snprintf(art, sizeof(art), "%s", ver);
            else if (branch[0]) snprintf(art, sizeof(art), "%s-%s-%s", imc, ver, branch);
            else snprintf(art, sizeof(art), "%s-%s", imc, ver);
            if (!list_has(found, art)) cJSON_AddItemToArray(found, cJSON_CreateString(art));
        }
    }
    cJSON_Delete(data);
    if (cJSON_GetArraySize(found) == 0) {
        struct { const char *u; int expand; } srcs[2] = {
            {BMCLAPI "/maven/net/minecraftforge/forge/maven-metadata.xml", 1},
            {FORGE_MAVEN "/maven-metadata.xml", 0},
        };
        for (int i = 0; i < 2 && cJSON_GetArraySize(found) == 0; i++) {
            char *xml = fetch_text(srcs[i].u, 40, srcs[i].expand);
            if (!xml) continue;
            cJSON *vers = parse_maven_versions(xml);
            free(xml);
            size_t ml = strlen(mc);
            cJSON *v;
            cJSON_ArrayForEach(v, vers) {
                const char *s = v->valuestring;
                if (!strcmp(s, mc) || (!strncmp(s, mc, ml) && s[ml] == '-')) cJSON_AddItemToArray(found, cJSON_CreateString(s));
            }
            cJSON_Delete(vers);
        }
    }
    int n = cJSON_GetArraySize(found);
    fkey *keys = (fkey *)calloc((size_t)(n ? n : 1), sizeof(fkey));
    int i = 0;
    cJSON_ArrayForEach(item, found) forge_key(item->valuestring, mc, &keys[i++]);
    /* Python 的 sort 是稳定的；等键时保持原顺序：给 qsort 加稳定性要靠原下标，这里键里带了全长，基本不会等 */
    qsort(keys, (size_t)n, sizeof(fkey), cmp_fkey_desc);
    cJSON *rows = cJSON_CreateArray();
    for (i = 0; i < n; i++) {
        char low[256];
        snprintf(low, sizeof(low), "%s", keys[i].id);
        for (char *p = low; *p; p++) *p = (char)tolower((unsigned char)*p);
        cJSON_AddItemToArray(rows, row3(keys[i].id, keys[i].id, strstr(low, "-pre") == NULL));
    }
    free(keys);
    cJSON_Delete(found);
    return rows;
}

static int mc_tuple_ge_1202(const char *mc) {
    int a = 0, b = 0, c = 0;
    if (mc_version_tuple(mc, &a, &b, &c) != 0) return 0;
    if (a != 1) return a > 1;
    if (b != 20) return b > 20;
    return c >= 2;
}

static cJSON *neoforge_versions(const char *mc) {
    static const char *map[][2] = {
        {"1.20.1", "47.1"}, {"1.20.2", "20.2"}, {"1.20.3", "20.3"}, {"1.20.4", "20.4"},
        {"1.20.5", "20.5"}, {"1.20.6", "20.6"}, {"1.21", "21.0"}, {"1.21.1", "21.1"},
    };
    char *xml = fetch_text(NEOFORGE_MAVEN "/maven-metadata.xml", 30, 0);
    cJSON *vers = parse_maven_versions(xml);
    free(xml);
    char prefix[64] = "";
    for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); i++) if (!strcmp(map[i][0], mc)) snprintf(prefix, sizeof(prefix), "%s", map[i][1]);
    if (!prefix[0] && mc_tuple_ge_1202(mc)) {
        const char *dot = strchr(mc, '.');
        if (dot) snprintf(prefix, sizeof(prefix), "%s", dot + 1);
    }
    cJSON *picked = cJSON_CreateArray();
    cJSON *v;
    size_t pl = strlen(prefix);
    if (pl) cJSON_ArrayForEach(v, vers) if (!strncmp(v->valuestring, prefix, pl) && v->valuestring[pl] == '.') cJSON_AddItemToArray(picked, cJSON_CreateString(v->valuestring));
    if (cJSON_GetArraySize(picked) == 0) {
        size_t ml = strlen(mc);
        cJSON_ArrayForEach(v, vers) if (!strncmp(v->valuestring, mc, ml) && v->valuestring[ml] == '-') cJSON_AddItemToArray(picked, cJSON_CreateString(v->valuestring));
    }
    cJSON_Delete(vers);
    int n = cJSON_GetArraySize(picked);
    int start = n > 80 ? n - 80 : 0;
    cJSON *rows = cJSON_CreateArray();
    for (int i = n - 1; i >= start; i--) {
        const char *s = cJSON_GetArrayItem(picked, i)->valuestring;
        char low[256];
        snprintf(low, sizeof(low), "%s", s);
        for (char *p = low; *p; p++) *p = (char)tolower((unsigned char)*p);
        cJSON_AddItemToArray(rows, row3(s, s, strstr(low, "beta") == NULL));
    }
    cJSON_Delete(picked);
    return rows;
}

static cJSON *list_loader_versions(const char *mc_in, const char *loader_in) {
    char mc[64], kind[64];
    snprintf(mc, sizeof(mc), "%s", mc_in);
    strip_inplace(mc);
    snprintf(kind, sizeof(kind), "%s", loader_in);
    strip_inplace(kind);
    for (char *p = kind; *p; p++) *p = (char)tolower((unsigned char)*p);
    if (!mc[0] || !kind[0] || !strcmp(kind, "无") || !strcmp(kind, "none")) return cJSON_CreateArray();
    char url[512];
    if (!strcmp(kind, "fabric") || !strcmp(kind, "quilt")) {
        int fabric = !strcmp(kind, "fabric");
        snprintf(url, sizeof(url), "%s/versions/loader/%s", fabric ? FABRIC_META : QUILT_META, mc);
        cJSON *data = fetch_json(url, 30, 1);
        if (!data) return NULL;
        cJSON *rows = cJSON_CreateArray();
        cJSON *d;
        cJSON_ArrayForEach(d, data) {
            cJSON *lo = cJSON_GetObjectItem(d, "loader");
            const char *ver = cJSON_GetStringValue(cJSON_GetObjectItem(lo, "version"));
            if (!ver || !ver[0]) continue;
            cJSON_AddItemToArray(rows, row3(ver, ver, fabric ? py_truthy(cJSON_GetObjectItem(lo, "stable")) : 1));
        }
        cJSON_Delete(data);
        return rows;
    }
    if (!strcmp(kind, "forge")) return forge_versions(mc);
    if (!strcmp(kind, "neoforge")) return neoforge_versions(mc);
    if (!strcmp(kind, "optifine")) {
        snprintf(url, sizeof(url), "%s/optifine/%s", BMCLAPI, mc);
        cJSON *data = fetch_json(url, 30, 1);
        if (!data) {
            pymcl_set_error("无法获取 OptiFine 列表 (%s): %s", mc, pymcl_error());
            return NULL;
        }
        cJSON *rows = cJSON_CreateArray();
        cJSON *r;
        cJSON_ArrayForEach(r, data) {
            if (!cJSON_IsObject(r)) continue;
            char typ[64] = "HD_U", patch[64] = "", id[160], label[160];
            cJSON *t = cJSON_GetObjectItem(r, "type"), *p = cJSON_GetObjectItem(r, "patch");
            if (py_truthy(t)) py_str(t, typ, sizeof(typ));
            if (py_truthy(p)) py_str(p, patch, sizeof(patch));
            snprintf(id, sizeof(id), "%s_%s", typ, patch);
            size_t il = strlen(id);
            while (il && id[il - 1] == '_') id[--il] = 0;
            snprintf(label, sizeof(label), "%s %s", typ, patch);
            strip_inplace(label);
            cJSON *row = cJSON_CreateObject();
            cJSON_AddStringToObject(row, "id", id);
            cJSON_AddStringToObject(row, "label", label);
            cJSON_AddStringToObject(row, "type", typ);
            cJSON_AddStringToObject(row, "patch", patch);
            cJSON_AddTrueToObject(row, "stable");
            cJSON_AddItemToArray(rows, row);
        }
        cJSON_Delete(data);
        return rows;
    }
    if (!strcmp(kind, "liteloader")) {
        cJSON *data = fetch_json(BMCLAPI "/liteloader/list", 20, 1);
        cJSON *vers = NULL;
        if (cJSON_IsObject(data)) {
            cJSON *v = cJSON_GetObjectItem(data, "versions");
            vers = py_truthy(v) ? v : data;
        }
        cJSON *official = NULL;
        if (!vers) {
            official = fetch_json("https://dl.liteloader.com/versions/versions.json", 20, 1);
            vers = cJSON_GetObjectItem(official, "versions");
        }
        cJSON *rows = cJSON_CreateArray();
        if (cJSON_IsObject(vers) && cJSON_GetObjectItemCaseSensitive(vers, mc)) cJSON_AddItemToArray(rows, row3(mc, mc, 1));
        cJSON_Delete(data);
        cJSON_Delete(official);
        return rows;
    }
    return cJSON_CreateArray();
}

cJSON *rpc_net_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    (void)emit;
    *handled = 1;
    if (!strcmp(method, "cached_news")) return news_load_cached();
    if (!strcmp(method, "fetch_news")) {
        const char *urls[] = {"https://launchercontent.mojang.com/v2/javaPatchNotes.json",
                              "https://launchercontent.mojang.com/javaPatchNotes.json"};
        char last[1024] = "";
        for (int i = 0; i < 2; i++) {
            cJSON *payload = fetch_json(urls[i], 15, 1);
            if (!payload) { snprintf(last, sizeof(last), "%s", pymcl_error()); continue; }
            cJSON *rows = news_rows(payload);
            cJSON_Delete(payload);
            if (cJSON_GetArraySize(rows) > 0) {
                char p[PYMCL_PATH];
                news_cache_path(p, sizeof(p));
                pymcl_write_json(p, rows);
                return rows;
            }
            cJSON_Delete(rows);
        }
        cJSON *cached = news_load_cached();
        if (cJSON_GetArraySize(cached) > 0) return cached;
        cJSON_Delete(cached);
        if (last[0]) { pymcl_set_error("%s", last); return NULL; }
        return cJSON_CreateArray();
    }
    if (!strcmp(method, "check_update")) return check_update();
    if (!strcmp(method, "list_loader_versions"))
        return list_loader_versions(pstr(params, "mc_version", ""), pstr(params, "loader", ""));
    return rpc_ai_store_call(method, params, emit, handled);
}
