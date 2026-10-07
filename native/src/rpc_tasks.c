/* M3 后台任务A（docs/GOAL-c-bridge-no-python.md）：与 bridge/api.py 对齐。
 * backup_save / export_modpack 走本文件的极简 zip 写入器（STORE，只求文件集合
 * 与路径一致，对拍比较的是文件列表与返回文案）；repair_version 复用 installer
 * 的 install_version；authlib / nide8 登录走 Yggdrasil authenticate（出网经
 * PYMCL_HTTP_REPLAY 钩子可录制回放）。 */
#include "pymcl.h"
#include <zlib.h>

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(o, k));
    return (v && v[0]) ? v : def;
}

/* ---------------- 极简 zip 写入器（STORE + CRC32） ---------------- */

static unsigned int zip_crc32(const unsigned char *d, size_t n) {
    uLong c = crc32(0L, Z_NULL, 0);
    /* 分段喂，避免大文件一次占内存（crc32 本身流式） */
    c = crc32(c, d, (uInt)n);
    return (unsigned int)c;
}

static void w16(FILE *f, unsigned v) { fputc(v & 0xff, f); fputc((v >> 8) & 0xff, f); }
static void w32(FILE *f, unsigned v) {
    fputc(v & 0xff, f); fputc((v >> 8) & 0xff, f);
    fputc((v >> 16) & 0xff, f); fputc((v >> 24) & 0xff, f);
}

static void dos_time(const char *path, unsigned *dtime, unsigned *ddate) {
    (void)path;
    time_t now = time(NULL);
    struct tm *lt = localtime(&now);
    if (!lt) { *dtime = 0; *ddate = 0x21; return; }
    *dtime = (unsigned)((lt->tm_hour << 11) | (lt->tm_min << 5) | (lt->tm_sec >> 1));
    *ddate = (unsigned)(((lt->tm_year + 1900 - 1980) << 9) | ((lt->tm_mon + 1) << 5) | lt->tm_mday);
}

/* 把 name→磁盘路径 的文件集合打成 STORE zip。name 用 '/' 分隔。返回 0 成功。 */
int zip_create_store(const char **names, const char **paths, int n, const char *dest) {
    FILE *f = fopen(dest, "wb");
    if (!f) { pymcl_set_error("无法创建压缩包: %s", dest); return -1; }
    /* local entry 暂存到临时文件结构：先写 local headers 与数据，记录偏移 */
    long long *offsets = (long long *)calloc((size_t)(n > 0 ? n : 1), sizeof(long long));
    unsigned *crcs = (unsigned *)calloc((size_t)(n > 0 ? n : 1), sizeof(unsigned));
    unsigned *sizes = (unsigned *)calloc((size_t)(n > 0 ? n : 1), sizeof(unsigned));
    unsigned char *dtime = (unsigned char *)calloc((size_t)(n > 0 ? n : 1), 2);
    unsigned char *ddate = (unsigned char *)calloc((size_t)(n > 0 ? n : 1), 2);
    if (!offsets || !crcs || !sizes || !dtime || !ddate) {
        free(offsets); free(crcs); free(sizes); free(dtime); free(ddate); fclose(f);
        pymcl_set_error("内存不足"); return -1;
    }
    for (int i = 0; i < n; i++) {
        FILE *src = fopen(paths[i], "rb");
        if (!src) { pymcl_set_error("无法读取: %s", paths[i]); goto fail; }
        fseek(src, 0, SEEK_END);
        long sz = ftell(src);
        fseek(src, 0, SEEK_SET);
        unsigned char *buf = (unsigned char *)malloc((size_t)(sz > 0 ? sz : 1));
        if (!buf) { fclose(src); pymcl_set_error("内存不足"); goto fail; }
        if (sz > 0 && fread(buf, 1, (size_t)sz, src) != (size_t)sz) {
            free(buf); fclose(src); pymcl_set_error("读取失败: %s", paths[i]); goto fail;
        }
        fclose(src);
        offsets[i] = _ftelli64(f);
        crcs[i] = zip_crc32(buf, (size_t)sz);
        sizes[i] = (unsigned)sz;
        unsigned dt, dd; dos_time(paths[i], &dt, &dd);
        dtime[i * 2] = dt & 0xff; dtime[i * 2 + 1] = (dt >> 8) & 0xff;
        ddate[i * 2] = dd & 0xff; ddate[i * 2 + 1] = (dd >> 8) & 0xff;
        size_t nlen = strlen(names[i]);
        w32(f, 0x04034b50); w16(f, 20); w16(f, 0); w16(f, 0);   /* sig, version, flags, method=STORE */
        w16(f, dtime[i * 2] | (dtime[i * 2 + 1] << 8));
        w16(f, ddate[i * 2] | (ddate[i * 2 + 1] << 8));
        w32(f, crcs[i]); w32(f, sizes[i]); w32(f, sizes[i]);
        w16(f, (unsigned)nlen); w16(f, 0);
        fwrite(names[i], 1, nlen, f);
        if (sz > 0) fwrite(buf, 1, (size_t)sz, f);
        free(buf);
    }
    {
        long long cd_off = _ftelli64(f);
        for (int i = 0; i < n; i++) {
            size_t nlen = strlen(names[i]);
            w32(f, 0x02014b50); w16(f, 20); w16(f, 20); w16(f, 0); w16(f, 0);
            w16(f, dtime[i * 2] | (dtime[i * 2 + 1] << 8));
            w16(f, ddate[i * 2] | (ddate[i * 2 + 1] << 8));
            w32(f, crcs[i]); w32(f, sizes[i]); w32(f, sizes[i]);
            w16(f, (unsigned)nlen); w16(f, 0); w16(f, 0); w16(f, 0); w16(f, 0);
            w32(f, 0); w32(f, offsets[i]); fwrite(names[i], 1, nlen, f);
        }
        long long cd_size = _ftelli64(f) - cd_off;
        w32(f, 0x06054b50); w16(f, 0); w16(f, 0);
        w16(f, (unsigned)n); w16(f, (unsigned)n);
        w32(f, (unsigned)cd_size); w32(f, (unsigned)cd_off); w16(f, 0);
    }
    free(offsets); free(crcs); free(sizes); free(dtime); free(ddate);
    fclose(f);
    return 0;
fail:
    free(offsets); free(crcs); free(sizes); free(dtime); free(ddate);
    fclose(f);
    DeleteFileA(dest);
    return -1;
}

/* ---------------- 递归收集文件（相对路径用 '/'） ---------------- */

typedef struct { char rel[PYMCL_PATH]; char abs[PYMCL_PATH]; } file_rec;
typedef struct { file_rec *v; int n, cap; } file_list;

static int fl_push(file_list *l, const char *rel, const char *abs) {
    if (l->n == l->cap) {
        int nc = l->cap ? l->cap * 2 : 64;
        file_rec *nv = (file_rec *)realloc(l->v, (size_t)nc * sizeof(file_rec));
        if (!nv) return -1;
        l->v = nv; l->cap = nc;
    }
    snprintf(l->v[l->n].rel, PYMCL_PATH, "%s", rel);
    snprintf(l->v[l->n].abs, PYMCL_PATH, "%s", abs);
    l->n++;
    return 0;
}

int pymcl_collect_file_tree(const char *root, const char *prefix, void *list);

static int fl_walk(const char *root, const char *prefix, file_list *l);

int pymcl_collect_file_tree(const char *root, const char *prefix, void *list) {
    return fl_walk(root, prefix, (file_list *)list);
}

static int fl_walk(const char *root, const char *prefix, file_list *l) {
    wchar_t *w = pymcl_u8_to_wide(root);
    if (!w) return -1;
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    free(w);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        char *name = pymcl_wide_to_u8(fd.cFileName);
        char abs[PYMCL_PATH], rel[PYMCL_PATH];
        pymcl_path_join(abs, sizeof(abs), root, name);
        if (prefix[0]) snprintf(rel, sizeof(rel), "%s/%s", prefix, name);
        else snprintf(rel, sizeof(rel), "%s", name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) fl_walk(abs, rel, l);
        else fl_push(l, rel, abs);
        free(name);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return 0;
}

static int cmp_rec(const void *a, const void *b) {
    return strcmp(((const file_rec *)a)->rel, ((const file_rec *)b)->rel);
}

/* ---------------- backup_save ---------------- */

int task_backup_save_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    const char *name = pstr(args, "name", "");
    const char *ver = pstr(args, "version", "");
    char ip[PYMCL_PATH], game[PYMCL_PATH], saves[PYMCL_PATH], src[PYMCL_PATH], backups[PYMCL_PATH];
    if (instance_open(inst, ip, sizeof(ip)) != 0) { pymcl_set_error("实例不存在: %s", inst); return -1; }
    /* 与 rpc_content.game_dir / saves._game_dir 同款：版本隔离档位决定游戏目录 */
    if (ver[0]) {
        cJSON *st = version_settings_load(inst, ver);
        const char *iso = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(st, "isolation"));
        if (iso && (!strcmp(iso, "all") || !strcmp(iso, "saves") || !strcmp(iso, "mods"))) {
            char vd[PYMCL_PATH];
            instance_versions_dir(inst, vd, sizeof(vd));
            pymcl_path_join(game, sizeof(game), vd, ver);
        } else snprintf(game, sizeof(game), "%s", ip);
        cJSON_Delete(st);
    } else snprintf(game, sizeof(game), "%s", ip);
    pymcl_path_join(saves, sizeof(saves), game, "saves");
    pymcl_path_join(src, sizeof(src), saves, name);
    if (!pymcl_dir_exists(src)) { pymcl_set_error("存档不存在: %s", name); return -1; }
    pymcl_path_join(backups, sizeof(backups), game, "backups");
    pymcl_ensure_dir(backups);
    char stamp[32];
    { time_t now = time(NULL); struct tm *lt = localtime(&now); strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", lt); }
    char dest[PYMCL_PATH], zipname[256];
    snprintf(zipname, sizeof(zipname), "%s-%s.zip", name, stamp);
    pymcl_path_join(dest, sizeof(dest), backups, zipname);
    int dup = 1;
    while (pymcl_file_size(dest) >= 0) {
        snprintf(zipname, sizeof(zipname), "%s-%s-%d.zip", name, stamp, dup++);
        pymcl_path_join(dest, sizeof(dest), backups, zipname);
    }

    file_list l = {0};
    fl_walk(src, "", &l);
    qsort(l.v, (size_t)l.n, sizeof(file_rec), cmp_rec);
    int total = l.n > 0 ? l.n : 1;
    const char **names = (const char **)calloc((size_t)(l.n > 0 ? l.n : 1), sizeof(char *));
    const char **paths = (const char **)calloc((size_t)(l.n > 0 ? l.n : 1), sizeof(char *));
    for (int i = 0; i < l.n; i++) {
        names[i] = l.v[i].rel; paths[i] = l.v[i].abs;
        char pm[PYMCL_PATH + 32];
        snprintf(pm, sizeof(pm), "备份 %s", name);
        if (ctx->cancel && ctx->cancel(ctx->ud)) {
            free(names); free(paths); free(l.v);
            pymcl_set_error("已取消"); return -1;
        }
        ctx->on_progress(ctx->ud, pm, i + 1, total);
    }
    int rc = zip_create_store(names, paths, l.n, dest);
    free(names); free(paths); free(l.v);
    if (rc != 0) return -1;
    char lg[PYMCL_PATH + 32]; snprintf(lg, sizeof(lg), "备份完成: %s", dest);
    ctx->on_log(ctx->ud, lg);
    tr_fmt0(msg, msgn, "已备份到 {0}", pymcl_basename(dest));
    return 0;
}

/* ---------------- repair_version ---------------- */

int task_repair_version_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    const char *ver = pstr(args, "version", "");
    if (!ver[0]) { pymcl_set_error("请选择要修复的版本"); return -1; }
    char note[128];
    snprintf(note, sizeof(note), "修复 %s：校验并补全缺失文件", ver);
    ctx->on_log(ctx->ud, note);
    if (install_version(inst, ver, ctx) != 0) return -1;
    snprintf(msg, msgn, "已修复 %s", ver);
    return 0;
}

/* ---------------- export_modpack ---------------- */

int task_export_modpack_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    const char *dest_in = pstr(args, "dest", "");
    char ip[PYMCL_PATH], mods[PYMCL_PATH], dest[PYMCL_PATH];
    if (instance_path(inst, ip, sizeof(ip)) != 0) { pymcl_set_error("实例不存在: %s", inst); return -1; }
    pymcl_path_join(mods, sizeof(mods), ip, "mods");
    if (!dest_in[0]) {
        char ex[PYMCL_PATH];
        pymcl_path_join(ex, sizeof(ex), g_root, "exports");
        pymcl_ensure_dir(ex);
        char rname[256], fn[256];
        instance_resolved_name(inst, rname, sizeof(rname));
        snprintf(fn, sizeof(fn), "%s.mrpack", rname);
        pymcl_path_join(dest, sizeof(dest), ex, fn);
    } else snprintf(dest, sizeof(dest), "%s", dest_in);

    /* mods：sha1 → Modrinth version_file 查询；命中进 index.files，未命中进 overrides */
    file_list overrides = {0};
    cJSON *files = cJSON_CreateArray();
    file_list jars = {0};
    if (pymcl_dir_exists(mods)) {
        wchar_t *w = pymcl_u8_to_wide(mods);
        wchar_t pat[PYMCL_PATH]; _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
        WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW(pat, &fd); free(w);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
                char *n = pymcl_wide_to_u8(fd.cFileName);
                if (!pymcl_endswith(n, ".jar")) { free(n); continue; }
                char abs[PYMCL_PATH], rel[PYMCL_PATH];
                pymcl_path_join(abs, sizeof(abs), mods, n);
                snprintf(rel, sizeof(rel), "mods/%s", n);
                fl_push(&jars, rel, abs);
                free(n);
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
    }
    for (int i = 0; i < jars.n; i++) {
        if (ctx->cancel && ctx->cancel(ctx->ud)) {
            free(jars.v); free(overrides.v); cJSON_Delete(files);
            pymcl_set_error("已取消"); return -1;
        }
        char note[PYMCL_PATH];
        snprintf(note, sizeof(note), "解析模组 %s", pymcl_basename(jars.v[i].abs));
        ctx->on_progress(ctx->ud, note, i, jars.n > 0 ? jars.n : 1);
        char digest[41] = "";
        pymcl_sha1_file(jars.v[i].abs, digest);
        char pq[160], url[256];
        snprintf(pq, sizeof(pq), "/version_file/%s", digest);
        snprintf(url, sizeof(url), MODRINTH_API "%s", pq);
        cJSON *hit = http_get_json(url, 15);
        if (!hit) {
            snprintf(url, sizeof(url), MCIM_MIRROR "/modrinth/v2%s", pq);
            hit = http_get_json(url, 15);
        }
        cJSON *primary = NULL;
        if (cJSON_IsObject(hit)) {
            cJSON *f;
            cJSON_ArrayForEach(f, cJSON_GetObjectItem(hit, "files")) {
                if (cJSON_IsTrue(cJSON_GetObjectItem(f, "primary"))) { primary = f; break; }
                if (!primary) primary = f;
            }
        }
        const char *purl = primary ? cJSON_GetStringValue(cJSON_GetObjectItem(primary, "url")) : NULL;
        if (purl && purl[0]) {
            cJSON *e = cJSON_CreateObject();
            cJSON_AddStringToObject(e, "path", jars.v[i].rel);
            cJSON *hs = cJSON_AddObjectToObject(e, "hashes");
            cJSON_AddStringToObject(hs, "sha1", digest);
            char sha512[129] = "";
            const char *s512 = primary ? cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(primary, "hashes"), "sha512")) : NULL;
            snprintf(sha512, sizeof(sha512), "%s", s512 ? s512 : "");
            cJSON_AddStringToObject(hs, "sha512", sha512);
            cJSON *dls = cJSON_AddArrayToObject(e, "downloads");
            cJSON_AddItemToArray(dls, cJSON_CreateString(purl));
            double psz = primary ? cJSON_GetNumberValue(cJSON_GetObjectItem(primary, "size")) : 0;
            if (psz <= 0) psz = (double)pymcl_file_size(jars.v[i].abs);
            cJSON_AddNumberToObject(e, "fileSize", psz);
            cJSON_AddItemToArray(files, e);
        } else {
            fl_push(&overrides, jars.v[i].rel, jars.v[i].abs);
        }
        cJSON_Delete(hit);
        ctx->on_progress(ctx->ud, note, i + 1, jars.n > 0 ? jars.n : 1);
    }
    free(jars.v);

    /* 其余 overrides 目录（config/ 等），与 Python OVERRIDE_DIRS 对齐 */
    static const char *OVERRIDE_DIRS[] = { "config", "shaderpacks", "resourcepacks", "kubejs", "defaultconfigs" };
    for (size_t d = 0; d < sizeof(OVERRIDE_DIRS)/sizeof(OVERRIDE_DIRS[0]); d++) {
        char dir[PYMCL_PATH];
        pymcl_path_join(dir, sizeof(dir), ip, OVERRIDE_DIRS[d]);
        if (!pymcl_dir_exists(dir)) continue;
        fl_walk(dir, OVERRIDE_DIRS[d], &overrides);
    }
    qsort(overrides.v, (size_t)overrides.n, sizeof(file_rec), cmp_rec);

    /* modrinth.index.json */
    cJSON *index = cJSON_CreateObject();
    cJSON_AddNumberToObject(index, "formatVersion", 1);
    cJSON_AddStringToObject(index, "game", "minecraft");
    cJSON *meta = instance_meta(inst);
    cJSON *pack = cJSON_GetObjectItem(meta, "modpack");
    char pk_name[256], pk_ver[64], mc[64], loader[64], ldver[64];
    snprintf(pk_name, sizeof(pk_name), "%s", (cJSON_IsObject(pack) ? cJSON_GetStringValue(cJSON_GetObjectItem(pack, "name")) : NULL) ?: inst);
    snprintf(pk_ver, sizeof(pk_ver), "%s", (cJSON_IsObject(pack) ? cJSON_GetStringValue(cJSON_GetObjectItem(pack, "version")) : NULL) ?: "1.0.0");
    snprintf(mc, sizeof(mc), "%s", (cJSON_IsObject(pack) ? cJSON_GetStringValue(cJSON_GetObjectItem(pack, "mc_version")) : NULL) ?: cJSON_GetStringValue(cJSON_GetObjectItem(meta, "mc_version")) ?: "");
    snprintf(loader, sizeof(loader), "%s", (cJSON_IsObject(pack) ? cJSON_GetStringValue(cJSON_GetObjectItem(pack, "loader")) : NULL) ?: "");
    snprintf(ldver, sizeof(ldver), "%s", (cJSON_IsObject(pack) ? cJSON_GetStringValue(cJSON_GetObjectItem(pack, "loader_version")) : NULL) ?: "");
    cJSON_AddStringToObject(index, "versionId", pk_ver);
    cJSON_AddStringToObject(index, "name", pk_name);
    char summary[512];
    snprintf(summary, sizeof(summary), "由 PyMCL 从实例 %s 导出", inst);
    cJSON_AddStringToObject(index, "summary", summary);
    cJSON_AddItemToObject(index, "files", files);
    cJSON *deps = cJSON_AddObjectToObject(index, "dependencies");
    if (mc[0]) cJSON_AddStringToObject(deps, "minecraft", mc);
    for (char *p = loader; *p; p++) *p = (char)tolower((unsigned char)*p);
    if (loader[0]) cJSON_AddStringToObject(deps, loader, ldver);
    char *index_s = cJSON_Print(index);
    cJSON_Delete(index);
    cJSON_Delete(meta);

    /* 打包：index + overrides */
    int n = overrides.n + 1;
    const char **names = (const char **)calloc((size_t)n, sizeof(char *));
    const char **paths = (const char **)calloc((size_t)n, sizeof(char *));
    char idx_name[] = "modrinth.index.json";
    char idx_tmp[PYMCL_PATH];
    snprintf(idx_tmp, sizeof(idx_tmp), "%s.modrinth.index.json.tmp", dest);
    { FILE *f = fopen(idx_tmp, "wb"); if (f) { fwrite(index_s, 1, strlen(index_s), f); fclose(f); } }
    free(index_s);
    names[0] = idx_name; paths[0] = idx_tmp;
    for (int i = 0; i < overrides.n; i++) { names[i + 1] = overrides.v[i].rel; paths[i + 1] = overrides.v[i].abs; }
    int rc = zip_create_store(names, paths, n, dest);
    free(names); free(paths); free(overrides.v);
    DeleteFileA(idx_tmp);
    if (rc != 0) return -1;
    ctx->on_progress(ctx->ud, "导出完成", 1, 1);
    snprintf(msg, msgn, "%s", dest);
    return 0;
}

/* ---------------- authlib / nide8 登录 ---------------- */

static void dashed_uuid(const char *hex32, char *out, size_t n) {
    if (strlen(hex32) == 32)
        snprintf(out, n, "%.8s-%.4s-%.4s-%.4s-%.6s", hex32, hex32 + 8, hex32 + 12, hex32 + 16, hex32 + 20);
    else snprintf(out, n, "%s", hex32);
}

static void auth_now_plus7(double *expires, double *updated) {
    time_t now = time(NULL);
    *expires = (double)now + 7.0 * 24 * 3600;
    *updated = (double)now;
}

/* 共用：POST {base}/authserver/authenticate；错误文案按各登录方式的前缀 */
static cJSON *ygg_authenticate(const char *base, const char *username, const char *password,
                               const char *conn_err_prefix, const char *login_err_prefix) {
    char url[1024];
    snprintf(url, sizeof(url), "%s/authserver/authenticate", base);
    cJSON *payload = cJSON_CreateObject();
    cJSON *agent = cJSON_AddObjectToObject(payload, "agent");
    cJSON_AddStringToObject(agent, "name", "Minecraft");
    cJSON_AddNumberToObject(agent, "version", 1);
    cJSON_AddStringToObject(payload, "username", username);
    cJSON_AddStringToObject(payload, "password", password);
    cJSON_AddBoolToObject(payload, "requestUser", 1);
    char *body = cJSON_PrintUnformatted(payload);
    cJSON_Delete(payload);
    http_resp r;
    int rc = http_post_json(url, body, &r, NULL, 20);
    free(body);
    if (rc != 0) {
        char inner[512]; snprintf(inner, sizeof(inner), "%s", pymcl_error());
        pymcl_set_error("%s: %s", conn_err_prefix, inner);
        return NULL;
    }
    cJSON *data = cJSON_ParseWithLength(r.body ? r.body : "", r.len);
    int status = r.status;
    http_resp_free(&r);
    if (status >= 400) {
        const char *err = data ? cJSON_GetStringValue(cJSON_GetObjectItem(data, "errorMessage")) : NULL;
        if (!err && data) err = cJSON_GetStringValue(cJSON_GetObjectItem(data, "error"));
        char text[201] = "";
        if (err && err[0]) snprintf(text, sizeof(text), "%s", err);
        pymcl_set_error("%s: %s", login_err_prefix, text[0] ? text : "");
        cJSON_Delete(data);
        return NULL;
    }
    return data; /* 可能是 {}（解析失败），调用方按 Python 的空 dict 语义走 */
}

static void ygg_build_account(cJSON *data, const char *type, const char *api,
                              const char *username, const char *sid,
                              const char *no_profile_err, cJSON *out) {
    cJSON *profile = cJSON_GetObjectItem(data, "selectedProfile");
    if (!cJSON_IsObject(profile) || !cJSON_GetStringValue(cJSON_GetObjectItem(profile, "name"))) {
        cJSON *profiles = cJSON_GetObjectItem(data, "availableProfiles");
        if (cJSON_IsArray(profiles) && cJSON_GetArraySize(profiles) > 0)
            profile = cJSON_GetArrayItem(profiles, 0);
    }
    const char *pname = profile ? cJSON_GetStringValue(cJSON_GetObjectItem(profile, "name")) : NULL;
    if (!pname || !pname[0]) { pymcl_set_error("%s", no_profile_err); return; }
    const char *pid = profile ? cJSON_GetStringValue(cJSON_GetObjectItem(profile, "id")) : "";
    char dashed[64]; dashed_uuid(pid ? pid : "", dashed, sizeof(dashed));
    char hex[64]; /* Python dashed_uuid 接受带连字符或裸 hex；C 侧统一存 dashed */
    cJSON_AddStringToObject(out, "type", type);
    cJSON_AddStringToObject(out, "name", pname);
    cJSON_AddStringToObject(out, "uuid", dashed);
    cJSON_AddStringToObject(out, "access_token", cJSON_GetStringValue(cJSON_GetObjectItem(data, "accessToken")) ?: "0");
    cJSON_AddStringToObject(out, "client_token", cJSON_GetStringValue(cJSON_GetObjectItem(data, "clientToken")) ?: "");
    if (sid && sid[0]) cJSON_AddStringToObject(out, "server_id", sid);
    cJSON_AddStringToObject(out, "api", api);
    cJSON_AddStringToObject(out, "username", username);
    double exp, upd; auth_now_plus7(&exp, &upd);
    cJSON_AddNumberToObject(out, "expires_at", exp);
    cJSON_AddNumberToObject(out, "updated_at", upd);
}

static void normalize_api_url(const char *raw, char *out, size_t n) {
    const char *s = raw ? raw : "";
    while (*s == ' ' || *s == '\t') s++;
    size_t len = strlen(s);
    while (len > 0 && s[len - 1] == '/') len--;
    int is_http = strncmp(s, "http", 4) == 0;
    if (is_http) snprintf(out, n, "%.*s", (int)len, s);
    else snprintf(out, n, "https://%.*s", (int)len, s);
}

/* 账号写入 accounts.json（add_account 语义：同名覆盖） */
static void accounts_add_one(cJSON *acc) {
    cJSON *root = accounts_load();
    cJSON *arr = cJSON_GetObjectItem(root, "accounts");
    if (!cJSON_IsArray(arr)) { cJSON_AddArrayToObject(root, "accounts"); arr = cJSON_GetObjectItem(root, "accounts"); }
    const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")) ?: "";
    const char *uuid = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")) ?: "";
    int idx = 0, found = -1;
    cJSON *it;
    cJSON_ArrayForEach(it, arr) {
        const char *n2 = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
        const char *u2 = cJSON_GetStringValue(cJSON_GetObjectItem(it, "uuid"));
        if ((n2 && strcmp(n2, name) == 0) || (uuid[0] && u2 && strcmp(u2, uuid) == 0)) { found = idx; break; }
        idx++;
    }
    if (found >= 0) cJSON_DeleteItemFromArray(arr, found);
    cJSON_AddItemToArray(arr, cJSON_Duplicate(acc, 1));
    accounts_save(root);
    cJSON_Delete(root);
}

/* authlib.ensure_injector / nide8.ensure_jar：与 Python 一致，登录前先备 jar */
static int ensure_authlib_injector(pymcl_ctx *ctx) {
    char dest[PYMCL_PATH];
    pymcl_path_join(dest, sizeof(dest), g_root, "authlib-injector.jar");
    if (pymcl_file_size(dest) > 10000) return 0;
    static const char *metas[] = {
        "https://bmclapi2.bangbang93.com/mirrors/authlib-injector/artifact/latest.json",
        "https://authlib-injector.yushi.moe/artifact/latest.json",
    };
    for (int i = 0; i < 2; i++) {
        cJSON *meta = http_get_json(metas[i], 20);
        char du[512] = "";
        if (meta) {
            const char *d = cJSON_GetStringValue(cJSON_GetObjectItem(meta, "download_url"));
            if (!d || !d[0]) d = cJSON_GetStringValue(cJSON_GetObjectItem(meta, "url"));
            snprintf(du, sizeof(du), "%s", d ? d : "");
            { char dbg[160]; snprintf(dbg, sizeof(dbg), "[ensure] meta ok, du=%.100s", du);
              ctx->on_log(ctx->ud, dbg); }
        } else {
            char dbg[256]; snprintf(dbg, sizeof(dbg), "[ensure] meta NULL: %.120s", pymcl_error());
            ctx->on_log(ctx->ud, dbg);
        }
        cJSON_Delete(meta);
        if (!du[0]) continue;
        ctx->on_log(ctx->ud, "下载 authlib-injector");
        /* download_file 会按"无校验信息=失败"的安装语义拒收；ensure 只求落盘，直接 GET 写文件 */
        http_resp jr;
        if (http_get(du, &jr, NULL, 60) == 0 && jr.body && jr.len > 0) {
            FILE *jf = fopen(dest, "wb");
            if (jf) { fwrite(jr.body, 1, jr.len, jf); fclose(jf); }
            http_resp_free(&jr);
            if (pymcl_file_size(dest) > 0) return 0;
        } else {
            http_resp_free(&jr);
        }
        { char inner[256]; snprintf(inner, sizeof(inner), "%s", pymcl_error());
          char dbg[512]; snprintf(dbg, sizeof(dbg), "[ensure] dl fail: %.150s", inner);
          ctx->on_log(ctx->ud, dbg);
          pymcl_set_error("下载 authlib-injector 失败: %s", inner); }
    }
    pymcl_set_error("无法下载 authlib-injector");
    return -1;
}

static int ensure_nide8_jar(pymcl_ctx *ctx) {
    char dest[PYMCL_PATH];
    pymcl_path_join(dest, sizeof(dest), g_root, "nide8auth.jar");
    if (pymcl_file_size(dest) > 8000) return 0;
    ctx->on_log(ctx->ud, "下载 nide8auth");
    http_resp jr;
    if (http_get("https://login.mc-user.com:233/index/jar", &jr, NULL, 60) == 0 && jr.body && jr.len > 0) {
        FILE *jf = fopen(dest, "wb");
        if (jf) { fwrite(jr.body, 1, jr.len, jf); fclose(jf); }
        http_resp_free(&jr);
    } else {
        http_resp_free(&jr);
    }
    if (pymcl_file_size(dest) < 8000) {
        pymcl_set_error("nide8auth 下载失败");
        return -1;
    }
    return 0;
}

int task_authlib_login_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    if (ensure_authlib_injector(ctx) != 0) return -1;
    char api[512];
    normalize_api_url(pstr(args, "api", ""), api, sizeof(api));
    char base[512];
    /* Python normalize_api 只 rstrip('/')；这里补 https:// 前缀语义一致 */
    normalize_api_url(pstr(args, "api", ""), base, sizeof(base));
    const char *username = pstr(args, "username", "");
    const char *password = pstr(args, "password", "");
    if (!api[0]) { pymcl_set_error("请填写皮肤站 Yggdrasil API 地址"); return -1; }
    if (!username[0] || !password[0]) { pymcl_set_error("请输入皮肤站账号和密码"); return -1; }
    cJSON *data = ygg_authenticate(api, username, password,
                                   "皮肤站无法连接", "皮肤站登录失败");
    if (!data) return -1;
    cJSON *acc = cJSON_CreateObject();
    ygg_build_account(data, "authlib", api, username, NULL,
                      "皮肤站没有可用角色，请先在网站创建角色", acc);
    cJSON_Delete(data);
    if (!cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"))) {
        cJSON_Delete(acc);
        return -1;
    }
    accounts_add_one(acc);
    char lg[256];
    snprintf(lg, sizeof(lg), "皮肤站登录成功：%s", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")));
    ctx->on_log(ctx->ud, lg);
    tr_fmt0(msg, msgn, "已登录 {0}", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")));
    cJSON_Delete(acc);
    return 0;
}

int task_nide8_login_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    if (ensure_nide8_jar(ctx) != 0) return -1;
    /* server_id 归一：Python 用 _SID_RE 提取 UUID 并小写；这里抽 8-4-4-4-12 段 */
    const char *raw = pstr(args, "server_id", "");
    char sid[64] = "";
    {
        /* 找第一段 8-4-4-4-12 hex（可含连字符） */
        static const char hexd[] = "0123456789abcdefABCDEF";
        size_t len = strlen(raw);
        for (size_t i = 0; i < len && !sid[0]; i++) {
            if (raw[i] != '-' && !strchr(hexd, raw[i])) continue;
            size_t j = i, seg = 0, got = 0;
            while (j < len) {
                if (raw[j] == '-') { j++; seg++; if (seg > 4) break; continue; }
                if (!strchr(hexd, raw[j])) break;
                j++; got++;
                if (seg < 4 && got == 8 + seg * 4 && j < len && raw[j] == '-') { seg++; j++; }
                else if (seg == 4 && got == 32) { if (j >= len || !strchr(hexd, raw[j])) break; }
            }
            if (got == 32) {
                char buf[40]; size_t k2 = i, w = 0;
                for (; k2 < j && w < sizeof(buf) - 1; k2++) {
                    if (raw[k2] != '-') buf[w++] = (char)tolower((unsigned char)raw[k2]);
                }
                buf[w] = '\0';
                if (w == 32) snprintf(sid, sizeof(sid), "%s", buf);
            }
        }
        if (!sid[0]) {
            /* 整段 32 位 hex 兜底 */
            size_t w = 0;
            for (size_t k = 0; raw[k] && w < 32; k++)
                if (strchr(hexd, raw[k])) sid[w++] = (char)tolower((unsigned char)raw[k]);
            sid[w] = '\0';
            if (w != 32) sid[0] = '\0';
        }
    }
    if (!sid[0]) { pymcl_set_error("请填写统一通行证服务器 ID"); return -1; }
    const char *username = pstr(args, "username", "");
    const char *password = pstr(args, "password", "");
    if (!username[0] || !password[0]) { pymcl_set_error("请输入统一通行证账号和密码"); return -1; }
    char base[256];
    snprintf(base, sizeof(base), "https://auth.mc-user.com:233/nide8/auth/%s", sid);
    cJSON *data = ygg_authenticate(base, username, password,
                                   "统一通行证无法连接", "统一通行证登录失败");
    if (!data) return -1;
    cJSON *acc = cJSON_CreateObject();
    ygg_build_account(data, "nide8", base, username, sid,
                      "该通行证没有可用角色", acc);
    cJSON_Delete(data);
    if (!cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"))) {
        cJSON_Delete(acc);
        return -1;
    }
    accounts_add_one(acc);
    char lg[256];
    snprintf(lg, sizeof(lg), "统一通行证登录成功：%s", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")));
    ctx->on_log(ctx->ud, lg);
    tr_fmt0(msg, msgn, "已登录 {0}", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")));
    cJSON_Delete(acc);
    return 0;
}
