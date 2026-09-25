#include "pymcl.h"
#include <ctype.h>

/* 版本目录操作与隔离、内容导出：mclauncher/version_ops.py、version_settings.set_isolation、
   content_export.py 的移植。 */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

static void open_path(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    if (w) ShellExecuteW(NULL, L"open", w, NULL, NULL, SW_SHOWNORMAL);
    free(w);
}

static int is_link(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    DWORD a = w ? GetFileAttributesW(w) : INVALID_FILE_ATTRIBUTES;
    free(w);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_REPARSE_POINT);
}

/* single_root.drop_link：只摘链接本身 */
static void drop_link(const char *p) {
    if (!is_link(p)) return;
    wchar_t *w = pymcl_u8_to_wide(p);
    if (w && !RemoveDirectoryW(w)) DeleteFileW(w);
    free(w);
}

static int dir_nonempty(const char *p) {
    cJSON *l = pymcl_list_dir(p, -1, 0);
    int n = cJSON_GetArraySize(l);
    cJSON_Delete(l);
    return n > 0;
}

/* version_settings._junction：cmd /c mklink /J，与 Python 一样 */
static void junction(const char *link, const char *target) {
    if (pymcl_path_exists(link) || is_link(link)) {
        if (pymcl_dir_exists(link) && !is_link(link) && dir_nonempty(link)) return;
        wchar_t *w = pymcl_u8_to_wide(link);
        BOOL ok = TRUE;
        if (is_link(link) || pymcl_file_exists(link)) ok = RemoveDirectoryW(w) || DeleteFileW(w);
        else if (pymcl_dir_exists(link) && !dir_nonempty(link)) ok = RemoveDirectoryW(w);
        free(w);
        if (!ok) return;
    }
    pymcl_ensure_dir(target);
    char parent[PYMCL_PATH];
    pymcl_parent(link, parent, sizeof(parent));
    pymcl_ensure_dir(parent);
    const char *argv[] = {"cmd", "/c", "mklink", "/J", link, target};
    pymcl_run_process(argv, 6, NULL, NULL, NULL, 30);
}

static const char *iso_of(cJSON *s) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(s, "isolation"));
    return v && v[0] ? v : "none";
}
static int valid_iso(const char *m) {
    return m && (!strcmp(m, "none") || !strcmp(m, "saves") || !strcmp(m, "mods") || !strcmp(m, "all"));
}
static int isolated(cJSON *s) { const char *i = iso_of(s); return !strcmp(i, "mods") || !strcmp(i, "all"); }

void version_game_dir(const char *inst, const char *vid, cJSON *s, char *out, size_t n) {
    const char *i = iso_of(s);
    if (!strcmp(i, "all") || !strcmp(i, "saves") || !strcmp(i, "mods")) {
        char vd[PYMCL_PATH];
        instance_versions_dir(inst, vd, sizeof(vd));
        pymcl_path_join(out, n, vd, vid);
    } else {
        instance_path(inst, out, n);
    }
}

static void vs_file(const char *inst, const char *vid, char *out, size_t n) {
    char vd[PYMCL_PATH];
    instance_versions_dir(inst, vd, sizeof(vd));
    pymcl_path_join3(out, n, vd, vid, "pymcl.json");
}

/* version_settings.save：load() 结果合并 data 后整份写回 */
static cJSON *vs_save(const char *inst, const char *vid, cJSON *data) {
    cJSON *cur = version_settings_load(inst, vid);
    cJSON *it;
    cJSON_ArrayForEach(it, data) {
        if (!it->string) continue;
        cJSON_DeleteItemFromObjectCaseSensitive(cur, it->string);
        cJSON_AddItemToObject(cur, it->string, cJSON_Duplicate(it, 1));
    }
    if (!valid_iso(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(cur, "isolation")))) {
        cJSON_DeleteItemFromObjectCaseSensitive(cur, "isolation");
        cJSON_AddStringToObject(cur, "isolation", "none");
    }
    char f[PYMCL_PATH];
    vs_file(inst, vid, f, sizeof(f));
    pymcl_write_json(f, cur);
    return cur;
}

void version_apply_isolation(const char *inst, const char *vid, cJSON *s) {
    char gd[PYMCL_PATH], ip[PYMCL_PATH];
    version_game_dir(inst, vid, s, gd, sizeof(gd));
    instance_path(inst, ip, sizeof(ip));
    pymcl_ensure_dir(gd);
    const char *iso = iso_of(s);
    char a[PYMCL_PATH], b[PYMCL_PATH];
    if (!strcmp(iso, "saves")) {
        const char *shared[] = {"mods", "config", "resourcepacks", "shaderpacks", "downloads"};
        for (int i = 0; i < 5; i++) {
            pymcl_path_join(a, sizeof(a), gd, shared[i]);
            pymcl_path_join(b, sizeof(b), ip, shared[i]);
            junction(a, b);
        }
        pymcl_path_join(a, sizeof(a), gd, "saves");
        pymcl_ensure_dir(a);
    } else if (!strcmp(iso, "mods")) {
        const char *links[] = {"saves", "resourcepacks", "shaderpacks", "screenshots"};
        for (int i = 0; i < 4; i++) {
            pymcl_path_join(a, sizeof(a), gd, links[i]);
            pymcl_path_join(b, sizeof(b), ip, links[i]);
            junction(a, b);
        }
        const char *own[] = {"mods", "config"};
        for (int i = 0; i < 2; i++) { pymcl_path_join(a, sizeof(a), gd, own[i]); pymcl_ensure_dir(a); }
    } else if (!strcmp(iso, "all")) {
        const char *drops[] = {"mods", "config", "resourcepacks", "shaderpacks", "downloads", "saves", "screenshots"};
        for (int i = 0; i < 7; i++) { pymcl_path_join(a, sizeof(a), gd, drops[i]); drop_link(a); }
        const char *own[] = {"mods", "config", "saves", "resourcepacks", "shaderpacks"};
        for (int i = 0; i < 5; i++) { pymcl_path_join(a, sizeof(a), gd, own[i]); pymcl_ensure_dir(a); }
    }
}

static void copy_tree_into(const char *src, const char *dst);

static void seed_from_shared(const char *inst, const char *vid) {
    char ip[PYMCL_PATH], vd[PYMCL_PATH];
    instance_path(inst, ip, sizeof(ip));
    instance_versions_dir(inst, vd, sizeof(vd));
    const char *seed[] = {"mods", "config", "resourcepacks", "shaderpacks"};
    for (int i = 0; i < 4; i++) {
        char src[PYMCL_PATH], dest[PYMCL_PATH];
        pymcl_path_join(src, sizeof(src), ip, seed[i]);
        if (!pymcl_dir_exists(src)) continue;
        pymcl_path_join3(dest, sizeof(dest), vd, vid, seed[i]);
        pymcl_ensure_dir(dest);
        cJSON *kids = pymcl_list_dir(src, -1, 0);
        cJSON *k;
        cJSON_ArrayForEach(k, kids) {
            char c[PYMCL_PATH], t[PYMCL_PATH];
            pymcl_path_join(c, sizeof(c), src, k->valuestring);
            pymcl_path_join(t, sizeof(t), dest, k->valuestring);
            if (pymcl_path_exists(t) || is_link(c)) continue;
            if (pymcl_dir_exists(c)) copy_tree_into(c, t);
            else pymcl_copy_file(c, t);
        }
        cJSON_Delete(kids);
    }
}

static void copy_tree_into(const char *src, const char *dst) {
    pymcl_ensure_dir(dst);
    cJSON *files = pymcl_walk_files(src);
    cJSON *f;
    cJSON_ArrayForEach(f, files) {
        char a[PYMCL_PATH], b[PYMCL_PATH];
        pymcl_path_join(a, sizeof(a), src, f->valuestring);
        pymcl_path_join(b, sizeof(b), dst, f->valuestring);
        pymcl_copy_file(a, b);
    }
    cJSON_Delete(files);
}

/* version_ops.sanitize_id */
static int sanitize_id(const char *raw, char *out, size_t n) {
    char t[512], u[512];
    const char *s = raw ? raw : "";
    while (*s && isspace((unsigned char)*s)) s++;
    snprintf(t, sizeof(t), "%s", s);
    size_t len = strlen(t);
    while (len && isspace((unsigned char)t[len - 1])) t[--len] = 0;
    size_t o = 0;
    for (const char *p = t; *p; p++) {
        unsigned char c = (unsigned char)*p;
        u[o++] = (c < 32 || strchr("\\/:*?\"<>|", c)) ? '-' : (char)c;
    }
    u[o] = 0;
    o = 0;
    for (const char *p = u; *p; p++) {
        if (isspace((unsigned char)*p)) { if (o == 0 || t[o - 1] != ' ') t[o++] = ' '; }
        else t[o++] = *p;
    }
    t[o] = 0;
    char *b = t;
    while (*b == ' ' || *b == '.') b++;
    len = strlen(b);
    while (len && (b[len - 1] == ' ' || b[len - 1] == '.')) b[--len] = 0;
    if (!b[0]) { pymcl_set_error("版本名不能为空"); return -1; }
    /* 截到 64 个字符（码点） */
    size_t chars = 0, i = 0;
    for (; b[i]; i++) {
        if (((unsigned char)b[i] & 0xC0) != 0x80) {
            if (chars == 64) { b[i] = 0; len = strlen(b); while (len && (b[len - 1] == ' ' || b[len - 1] == '.')) b[--len] = 0; break; }
            chars++;
        }
    }
    snprintf(out, n, "%s", b);
    return 0;
}

static int vdir_of(const char *inst, const char *vid, char *out, size_t n) {
    char vd[PYMCL_PATH];
    instance_versions_dir(inst, vd, sizeof(vd));
    pymcl_path_join(out, n, vd, vid);
    if (!pymcl_dir_exists(out)) { pymcl_set_error("版本不存在: %s", vid); return -1; }
    return 0;
}

static void rewrite_ids(const char *dest, const char *old_id, const char *new_id) {
    cJSON *files = pymcl_list_dir(dest, 0, 0);
    cJSON *f;
    size_t ol = strlen(old_id);
    cJSON_ArrayForEach(f, files) {
        const char *fn = f->valuestring;
        const char *dot = strrchr(fn, '.');
        size_t stem_len = (dot && dot != fn) ? (size_t)(dot - fn) : strlen(fn);
        if (stem_len != ol || strncmp(fn, old_id, ol) != 0) continue;
        char a[PYMCL_PATH], b[PYMCL_PATH], nn[600];
        snprintf(nn, sizeof(nn), "%s%s", new_id, (dot && dot != fn) ? dot : "");
        pymcl_path_join(a, sizeof(a), dest, fn);
        pymcl_path_join(b, sizeof(b), dest, nn);
        wchar_t *wa = pymcl_u8_to_wide(a), *wb = pymcl_u8_to_wide(b);
        MoveFileW(wa, wb);
        free(wa);
        free(wb);
    }
    cJSON_Delete(files);
    char jf[PYMCL_PATH], jn[600];
    snprintf(jn, sizeof(jn), "%s.json", new_id);
    pymcl_path_join(jf, sizeof(jf), dest, jn);
    if (!pymcl_file_exists(jf)) {
        char oj[PYMCL_PATH], on[600];
        snprintf(on, sizeof(on), "%s.json", old_id);
        pymcl_path_join(oj, sizeof(oj), dest, on);
        if (pymcl_file_exists(oj)) {
            wchar_t *wa = pymcl_u8_to_wide(oj), *wb = pymcl_u8_to_wide(jf);
            MoveFileW(wa, wb);
            free(wa);
            free(wb);
        }
    }
    cJSON *data = pymcl_read_json(jf);
    if (cJSON_IsObject(data)) {
        if (cJSON_GetObjectItemCaseSensitive(data, "id")) cJSON_ReplaceItemInObjectCaseSensitive(data, "id", cJSON_CreateString(new_id));
        else cJSON_AddStringToObject(data, "id", new_id);
        pymcl_write_json(jf, data);
    }
    cJSON_Delete(data);
    char sf[PYMCL_PATH];
    pymcl_path_join(sf, sizeof(sf), dest, "pymcl.json");
    if (pymcl_file_exists(sf)) {
        cJSON *st = pymcl_read_json(sf);
        if (!py_truthy(st)) { cJSON_Delete(st); st = cJSON_CreateObject(); }
        cJSON_DeleteItemFromObjectCaseSensitive(st, "hidden");
        pymcl_write_json(sf, st);
        cJSON_Delete(st);
    }
}

/* content_export ---------------------------------------------------------- */

static const char *content_sub(const char *kind) {
    if (!strcmp(kind, "mod")) return "mods";
    if (!strcmp(kind, "shader")) return "shaderpacks";
    if (!strcmp(kind, "resourcepack")) return "resourcepacks";
    if (!strcmp(kind, "datapack")) return "datapacks";
    if (!strcmp(kind, "world")) return "saves";
    return NULL;
}

static void default_export_dir(char *out, size_t n) {
    char saved[PYMCL_PATH] = "";
    cJSON *v = config_get("export_dir");
    if (py_truthy(v)) py_str(v, saved, sizeof(saved));
    char *s = saved;
    while (*s && isspace((unsigned char)*s)) s++;
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    if (s[0]) {
        char p[PYMCL_PATH];
        pymcl_py_path(s, p, sizeof(p));
        if (pymcl_dir_exists(p)) { snprintf(out, n, "%s", p); return; }
    }
    pymcl_path_join(out, n, g_root, "exports");
    pymcl_ensure_dir(out);
}

static void split_name(const char *fn, char *stem, size_t sn, char *suffix, size_t xn) {
    const char *dbl[] = {".jar.disabled", ".zip.disabled", ".tar.gz"};
    size_t len = strlen(fn);
    for (int i = 0; i < 3; i++) {
        size_t l = strlen(dbl[i]);
        if (len >= l && !_stricmp(fn + len - l, dbl[i])) {
            snprintf(stem, sn, "%.*s", (int)(len - l), fn);
            snprintf(suffix, xn, "%s", fn + len - l);
            return;
        }
    }
    const char *dot = strrchr(fn, '.');
    if (dot && dot != fn) {
        snprintf(stem, sn, "%.*s", (int)(dot - fn), fn);
        snprintf(suffix, xn, "%s", dot);
    } else {
        snprintf(stem, sn, "%s", fn);
        suffix[0] = 0;
    }
}

static void free_path(const char *folder, const char *fn, char *out, size_t n) {
    pymcl_path_join(out, n, folder, fn);
    if (!pymcl_path_exists(out)) return;
    char stem[512], suf[64], nn[700];
    split_name(fn, stem, sizeof(stem), suf, sizeof(suf));
    for (int i = 2;; i++) {
        snprintf(nn, sizeof(nn), "%s (%d)%s", stem, i, suf);
        pymcl_path_join(out, n, folder, nn);
        if (!pymcl_path_exists(out)) return;
    }
}

/* shutil.make_archive(base, "zip", root_dir=src)：目录也各占一条（结尾 /），路径相对 src */
static int make_archive(const char *src, const char *out_zip) {
    pymcl_zipw *z = pymcl_zipw_open(out_zip);
    if (!z) return -1;
    cJSON *files = pymcl_walk_files(src);
    cJSON *dirs = cJSON_CreateObject();
    cJSON *f;
    cJSON_ArrayForEach(f, files) {
        char rel[PYMCL_PATH];
        snprintf(rel, sizeof(rel), "%s", f->valuestring);
        for (char *p = rel; *p; p++) {
            if (*p == '\\') {
                *p = 0;
                char d[PYMCL_PATH];
                snprintf(d, sizeof(d), "%s/", rel);
                for (char *q = d; *q; q++) if (*q == '\\') *q = '/';
                if (!cJSON_GetObjectItemCaseSensitive(dirs, d)) {
                    cJSON_AddTrueToObject(dirs, d);
                    pymcl_zipw_add_bytes(z, d, "", 0, 0);
                }
                *p = '\\';
            }
        }
        char a[PYMCL_PATH];
        pymcl_path_join(a, sizeof(a), src, f->valuestring);
        if (pymcl_zipw_add_file(z, a, f->valuestring, 6) != 0) {
            cJSON_Delete(files);
            cJSON_Delete(dirs);
            pymcl_zipw_abort(z);
            return -1;
        }
    }
    cJSON_Delete(files);
    cJSON_Delete(dirs);
    return pymcl_zipw_close(z);
}

static cJSON *export_one(const char *inst, const char *kind, const char *name, const char *dest_dir, const char *ver) {
    const char *sub = content_sub(kind);
    if (!sub) { pymcl_set_error("不支持导出的类型: '%s'", kind); return NULL; }
    char base[PYMCL_PATH], folder[PYMCL_PATH];
    if (ver[0]) {
        cJSON *s = version_settings_load(inst, ver);
        version_game_dir(inst, ver, s, base, sizeof(base));
        cJSON_Delete(s);
    } else {
        instance_path(inst, base, sizeof(base));
    }
    pymcl_path_join(folder, sizeof(folder), base, sub);
    if (!name[0] || !strcmp(name, ".") || !strcmp(name, "..") || strpbrk(name, "\\/")) {
        pymcl_set_error("非法的文件名: '%s'", name);
        return NULL;
    }
    char src[PYMCL_PATH];
    pymcl_path_join(src, sizeof(src), folder, name);
    if (!pymcl_path_exists(src)) { pymcl_set_error("文件不存在: %s", name); return NULL; }
    char out_dir[PYMCL_PATH];
    if (dest_dir[0]) pymcl_py_path(dest_dir, out_dir, sizeof(out_dir));
    else default_export_dir(out_dir, sizeof(out_dir));
    pymcl_ensure_dir(out_dir);
    if (!strcmp(kind, "world")) {
        cJSON *p = cJSON_CreateObject();
        cJSON_AddStringToObject(p, "instance", inst);
        cJSON_AddStringToObject(p, "name", name);
        cJSON_AddStringToObject(p, "dest", out_dir);
        cJSON_AddStringToObject(p, "version", ver);
        int h = 0;
        cJSON *r = rpc_content_call("export_save", p, NULL, &h);
        cJSON_Delete(p);
        return r;
    }
    char dest[PYMCL_PATH];
    if (pymcl_dir_exists(src)) {
        char fn[600];
        snprintf(fn, sizeof(fn), "%s.zip", pymcl_basename(src));
        free_path(out_dir, fn, dest, sizeof(dest));
        if (make_archive(src, dest) != 0) return NULL;
        return cJSON_CreateString(dest);
    }
    free_path(out_dir, pymcl_basename(src), dest, sizeof(dest));
    if (pymcl_copy_file(src, dest) != 0) return NULL;
    return cJSON_CreateString(dest);
}

/* official_migrate.official_dir：没找到时 Python 返回 Path("")，str 之后是 "."（按当前目录解释） */
static void official_dir(char *out, size_t n) {
    wchar_t buf[PYMCL_PATH];
    DWORD len = GetEnvironmentVariableW(L"APPDATA", buf, PYMCL_PATH);
    if (len && len < PYMCL_PATH) {
        char *u = pymcl_wide_to_u8(buf);
        if (u) {
            char c[PYMCL_PATH];
            pymcl_path_join(c, sizeof(c), u, ".minecraft");
            free(u);
            if (pymcl_dir_exists(c)) { snprintf(out, n, "%s", c); return; }
        }
    }
    snprintf(out, n, ".");
}

static void thumb_dir(char *out, size_t n) {
    char cache[PYMCL_PATH];
    pymcl_cache_dir(cache, sizeof(cache));
    pymcl_path_join(out, n, cache, "thumbs");
    pymcl_ensure_dir(out);
}

/* thumbnails.thumb_path：sha1(url)[:24] + 路径里认得的图片后缀（默认 .png） */
static void thumb_path(const char *url, char *out, size_t n) {
    if (!url || !url[0]) { out[0] = 0; return; }
    char hex[41];
    pymcl_sha1_bytes(url, strlen(url), hex);
    hex[24] = 0;
    const char *p = strstr(url, "://");
    p = p ? strchr(p + 3, '/') : url;
    char path[2048] = "";
    if (p) snprintf(path, sizeof(path), "%.*s", (int)strcspn(p, "?#"), p);
    const char *last = strrchr(path, '/');
    last = last ? last + 1 : path;
    const char *dot = strrchr(last, '.');
    char ext[16] = ".png";
    if (dot && dot != last) {
        char low[16];
        snprintf(low, sizeof(low), "%s", dot);
        for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
        const char *ok[] = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico"};
        for (int i = 0; i < 6; i++) if (!strcmp(low, ok[i])) snprintf(ext, sizeof(ext), "%s", low);
    }
    char dir[PYMCL_PATH], fn[64];
    thumb_dir(dir, sizeof(dir));
    snprintf(fn, sizeof(fn), "%s%s", hex, ext);
    pymcl_path_join(out, n, dir, fn);
}

/* 下载失败的 url 冷却 10 分钟（与 Python 一样只在进程内记） */
static cJSON *g_thumb_fail;
static CRITICAL_SECTION g_thumb_cs;
static volatile LONG g_thumb_cs_init;

static void thumb_lock(void) {
    if (InterlockedCompareExchange(&g_thumb_cs_init, 1, 0) == 0) InitializeCriticalSection(&g_thumb_cs);
    else while (g_thumb_cs_init != 1) Sleep(0);
    EnterCriticalSection(&g_thumb_cs);
}

static cJSON *ensure_thumb(const char *url) {
    if (!url || !url[0]) return cJSON_CreateString("");
    char local[PYMCL_PATH];
    thumb_path(url, local, sizeof(local));
    if (pymcl_file_exists(local) && (long long)time(NULL) - pymcl_file_mtime(local) < 7LL * 24 * 3600)
        return cJSON_CreateString(local);
    thumb_lock();
    if (!g_thumb_fail) g_thumb_fail = cJSON_CreateObject();
    cJSON *stamp = cJSON_GetObjectItemCaseSensitive(g_thumb_fail, url);
    int cooling = stamp && (double)time(NULL) - stamp->valuedouble < 600;
    if (stamp && !cooling) cJSON_DeleteItemFromObjectCaseSensitive(g_thumb_fail, url);
    LeaveCriticalSection(&g_thumb_cs);
    if (cooling) return cJSON_CreateString("");
    http_resp r;
    memset(&r, 0, sizeof(r));
    int ok = http_get(url, &r, NULL, 20) == 0 && r.status >= 200 && r.status < 300 && r.len > 0 &&
             pymcl_write_file(local, r.body, r.len) == 0;
    http_resp_free(&r);
    thumb_lock();
    if (ok) cJSON_DeleteItemFromObjectCaseSensitive(g_thumb_fail, url);
    else {
        if (cJSON_GetArraySize(g_thumb_fail) >= 512) {
            while (cJSON_GetArraySize(g_thumb_fail) > 256) cJSON_DeleteItemFromArray(g_thumb_fail, 0);
        }
        cJSON_AddNumberToObject(g_thumb_fail, url, (double)time(NULL));
    }
    LeaveCriticalSection(&g_thumb_cs);
    return cJSON_CreateString(ok ? local : "");
}

cJSON *rpc_versions_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    *handled = 1;
    const char *inst = pstr(params, "instance", "");
    const char *ver = pstr(params, "version", "");

    /* official_migrate.detect_official / official_dir / scan_versions */
    if (!strcmp(method, "official_launcher_dir")) {
        char d[PYMCL_PATH];
        official_dir(d, sizeof(d));
        return cJSON_CreateString(d);
    }
    if (!strcmp(method, "detect_official_launcher") || !strcmp(method, "scan_official_versions")) {
        char d[PYMCL_PATH], vd[PYMCL_PATH];
        official_dir(d, sizeof(d));
        pymcl_path_join(vd, sizeof(vd), d, "versions");
        if (!strcmp(method, "detect_official_launcher"))
            return cJSON_CreateBool(pymcl_dir_exists(d) && pymcl_dir_exists(vd));
        cJSON *out = cJSON_CreateArray();
        if (!pymcl_dir_exists(vd)) return out;
        cJSON *kids = pymcl_list_dir(vd, 1, 1);
        cJSON *k;
        cJSON_ArrayForEach(k, kids) {
            char jf[PYMCL_PATH], jn[600];
            snprintf(jn, sizeof(jn), "%s.json", k->valuestring);
            pymcl_path_join3(jf, sizeof(jf), vd, k->valuestring, jn);
            if (pymcl_file_exists(jf)) cJSON_AddItemToArray(out, cJSON_CreateString(k->valuestring));
        }
        cJSON_Delete(kids);
        return out;
    }

    /* thumbnails.thumb_path / ensure_thumb */
    if (!strcmp(method, "thumb_path")) {
        char p[PYMCL_PATH];
        thumb_path(pstr(params, "url", ""), p, sizeof(p));
        return cJSON_CreateString(p);
    }
    if (!strcmp(method, "ensure_thumb")) return ensure_thumb(pstr(params, "url", ""));

    /* BackendAPI.rename_version / copy_version */
    if (!strcmp(method, "rename_version") || !strcmp(method, "copy_version")) {
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        char new_id[512];
        if (sanitize_id(pstr(params, "new_id", ""), new_id, sizeof(new_id)) != 0) return NULL;
        int rename = !strcmp(method, "rename_version");
        if (rename && !strcmp(new_id, ver)) return cJSON_CreateString(ver);
        char src[PYMCL_PATH], dest[PYMCL_PATH], vd[PYMCL_PATH];
        if (vdir_of(inst, ver, src, sizeof(src)) != 0) return NULL;
        instance_versions_dir(inst, vd, sizeof(vd));
        pymcl_path_join(dest, sizeof(dest), vd, new_id);
        if (pymcl_path_exists(dest)) { pymcl_set_error("已存在版本 %s", new_id); return NULL; }
        copy_tree_into(src, dest);
        rewrite_ids(dest, ver, new_id);
        if (rename) pymcl_remove_tree(src);
        return cJSON_CreateString(new_id);
    }

    /* BackendAPI.hide_version → version_ops.set_hidden */
    if (!strcmp(method, "hide_version")) {
        char ip[PYMCL_PATH], vdir[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        if (vdir_of(inst, ver, vdir, sizeof(vdir)) != 0) return NULL;
        cJSON *hv = cJSON_GetObjectItemCaseSensitive(params, "hidden");
        cJSON *data = cJSON_CreateObject();
        cJSON_AddBoolToObject(data, "hidden", hv ? py_truthy(hv) : 1);
        cJSON *r = vs_save(inst, ver, data);
        cJSON_Delete(data);
        return r;
    }

    /* BackendAPI.open_version_folder → version_ops.open_folder */
    if (!strcmp(method, "open_version_folder")) {
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        const char *which = pstr(params, "which", "root");
        char gd[PYMCL_PATH], path[PYMCL_PATH], vd[PYMCL_PATH];
        cJSON *s = ver[0] ? version_settings_load(inst, ver) : NULL;
        if (ver[0]) version_game_dir(inst, ver, s, gd, sizeof(gd));
        else snprintf(gd, sizeof(gd), "%s", ip);
        instance_versions_dir(inst, vd, sizeof(vd));
        if (!strcmp(which, "game")) snprintf(path, sizeof(path), "%s", gd);
        else if (!strcmp(which, "mods")) pymcl_path_join(path, sizeof(path), ver[0] ? gd : ip, "mods");
        else if (!strcmp(which, "version")) { if (ver[0]) pymcl_path_join(path, sizeof(path), vd, ver); else snprintf(path, sizeof(path), "%s", vd); }
        else if (!strcmp(which, "saves") || !strcmp(which, "screenshots") || !strcmp(which, "resourcepacks") ||
                 !strcmp(which, "shaderpacks") || !strcmp(which, "datapacks") || !strcmp(which, "logs") ||
                 !strcmp(which, "crash-reports")) pymcl_path_join(path, sizeof(path), gd, which);
        else snprintf(path, sizeof(path), "%s", ip);
        cJSON_Delete(s);
        pymcl_ensure_dir(path);
        open_path(path);
        return cJSON_CreateString(path);
    }

    /* BackendAPI.set_version_isolation / toggle_version_isolation → version_settings.set_isolation */
    if (!strcmp(method, "set_version_isolation") || !strcmp(method, "toggle_version_isolation")) {
        char ip[PYMCL_PATH];
        if (instance_open(NULL, ip, sizeof(ip)) != 0) return NULL;
        const char *mode;
        char mbuf[64];
        if (!strcmp(method, "toggle_version_isolation")) mode = py_truthy(cJSON_GetObjectItem(params, "isolated")) ? "all" : "none";
        else { snprintf(mbuf, sizeof(mbuf), "%s", pstr(params, "mode", "")); mode = mbuf; }
        if (!valid_iso(mode)) { pymcl_set_error("未知的隔离模式: '%s'", mode); return NULL; }
        cJSON *before = version_settings_load("", ver);
        cJSON *data = cJSON_CreateObject();
        cJSON_AddStringToObject(data, "isolation", mode);
        cJSON *saved = vs_save("", ver, data);
        cJSON_Delete(data);
        if (py_truthy(cJSON_GetObjectItem(params, "seed")) && isolated(saved) && !isolated(before))
            seed_from_shared("", ver);
        cJSON_Delete(before);
        version_apply_isolation("", ver, saved);
        if (emit) emit("ui_changed", cJSON_CreateObject());
        return saved;
    }

    /* BackendAPI.export_content / export_contents */
    if (!strcmp(method, "export_content")) {
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        return export_one(inst, pstr(params, "kind", ""), pstr(params, "name", ""), pstr(params, "dest_dir", ""), ver);
    }
    if (!strcmp(method, "export_contents")) {
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        const char *dd = pstr(params, "dest_dir", "");
        char folder[PYMCL_PATH];
        if (dd[0]) pymcl_py_path(dd, folder, sizeof(folder));
        else default_export_dir(folder, sizeof(folder));
        pymcl_ensure_dir(folder);
        cJSON *done = cJSON_CreateArray(), *failed = cJSON_CreateArray();
        cJSON *n;
        cJSON_ArrayForEach(n, cJSON_GetObjectItem(params, "names")) {
            char name[1024];
            py_str(n, name, sizeof(name));
            cJSON *r = export_one(inst, pstr(params, "kind", ""), name, folder, ver);
            if (r) cJSON_AddItemToArray(done, r);
            else {
                cJSON *e = cJSON_CreateObject();
                cJSON_AddStringToObject(e, "name", name);
                cJSON_AddStringToObject(e, "error", pymcl_error());
                cJSON_AddItemToArray(failed, e);
            }
        }
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "dir", folder);
        cJSON_AddItemToObject(o, "exported", done);
        cJSON_AddItemToObject(o, "failed", failed);
        return o;
    }

    return rpc_net_call(method, params, emit, handled);
}
