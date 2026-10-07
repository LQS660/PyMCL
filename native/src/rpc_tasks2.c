/* M3 后台任务B（docs/GOAL-c-bridge-no-python.md）：与 bridge/api.py 对齐。
 * export_launch_script / install_java / start_mod_updates / start_self_update /
 * migrate_official_launcher。尽量复用已原生的实现：
 * 启动命令 → backend_call("build_launch_command")；模组更新 → rpc_mod_update_call；
 * 更新检查 → backend_call("check_update")；Java → java_install_adoptium。 */
#include "pymcl.h"
#include <bcrypt.h>

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(o, k));
    return (v && v[0]) ? v : def;
}

/* tr(key) 双参数替换：{0}→a {1}→b（Python .format(a, b) 的两参形态） */
static void tr_fmt2(char *out, size_t n, const char *key, const char *a, const char *b) {
    char buf[1024];
    snprintf(buf, sizeof(buf), "%s", tr(key));
    char *p0 = strstr(buf, "{0}");
    if (p0) {
        char tmp[1024];
        snprintf(tmp, sizeof(tmp), "%.*s%s%s", (int)(p0 - buf), buf, a, p0 + 3);
        snprintf(buf, sizeof(buf), "%s", tmp);
    }
    char *p1 = strstr(buf, "{1}");
    if (p1) {
        char tmp[1024];
        snprintf(tmp, sizeof(tmp), "%.*s%s%s", (int)(p1 - buf), buf, b, p1 + 3);
        snprintf(buf, sizeof(buf), "%s", tmp);
    }
    snprintf(out, n, "%s", buf);
}

/* SHA-256（BCrypt）：updater 下载包完整性校验用 */
static int my_sha256_file(const char *path, char hex[65]) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    DWORD cbHash = 0, cbData = 0, done = 0;
    unsigned char sha[32] = {0};
    int rc = -1;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) != 0) goto out;
    if (BCryptGetProperty(alg, BCRYPT_HASH_LENGTH, (PUCHAR)&cbHash, sizeof(cbHash), &cbData, 0) != 0 || cbHash != 32) goto out;
    if (BCryptCreateHash(alg, &hash, NULL, 0, NULL, 0, 0) != 0) goto out;
    {
        static unsigned char buf[1 << 16];
        size_t r;
        while ((r = fread(buf, 1, sizeof(buf), f)) > 0)
            if (BCryptHashData(hash, buf, (ULONG)r, 0) != 0) goto out;
    }
    if (BCryptFinishHash(hash, sha, sizeof(sha), 0) != 0) goto out;
    static const char hexd[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) { hex[i * 2] = hexd[sha[i] >> 4]; hex[i * 2 + 1] = hexd[sha[i] & 0xf]; }
    hex[64] = '\0';
    (void)done;
    rc = 0;
out:
    if (hash) BCryptDestroyHash(hash);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    fclose(f);
    return rc;
}

static int valid_sha256(const char *s) {
    if (strlen(s) != 64) return 0;
    for (const char *p = s; *p; p++)
        if (!((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f'))) return 0;
    return 1;
}

/* ---------------- export_launch_script ---------------- */

/* version_ops.export_launch_bat 的引用规则：含空白/特殊字符才加引号，内部 " 转义为 \" */
static void bat_quote(const char *a, char *out, size_t n) {
    int need = strchr(a, ' ') || strchr(a, '\t') || strchr(a, '&') || strchr(a, '|')
            || strchr(a, '<') || strchr(a, '>') || strchr(a, '^') || strchr(a, '"');
    if (!need) { snprintf(out, n, "%s", a); return; }
    size_t w = 0;
    out[w++] = '"';
    for (const char *p = a; *p && w + 3 < n; p++) {
        if (*p == '"') { out[w++] = '\\'; out[w++] = '"'; }
        else out[w++] = *p;
    }
    out[w++] = '"';
    out[w] = '\0';
}

int task_export_launch_script_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    const char *ver = pstr(args, "version", "");
    const char *dest_in = pstr(args, "dest", "");
    if (!ver[0]) { pymcl_set_error("%s", tr("请先选择版本")); return -1; }
    /* 复用对前端暴露的 build_launch_command（账号解析/props/auth 注入全同一条路） */
    cJSON *lc = cJSON_CreateObject();
    cJSON_AddStringToObject(lc, "instance", inst);
    cJSON_AddStringToObject(lc, "version", ver);
    const char *acc = pstr(args, "account", "");
    const char *usr = pstr(args, "username", "");
    if (acc[0]) cJSON_AddStringToObject(lc, "account", acc);
    if (usr[0]) cJSON_AddStringToObject(lc, "username", usr);
    int handled = 0;
    cJSON *cmdarr = backend_call("build_launch_command", lc);
    (void)handled;
    cJSON_Delete(lc);
    if (!cJSON_IsArray(cmdarr)) { pymcl_set_error("%s", pymcl_error()); return -1; }

    char ip[PYMCL_PATH];
    if (instance_open(inst, ip, sizeof(ip)) != 0) { cJSON_Delete(cmdarr); pymcl_set_error("实例不存在: %s", inst); return -1; }
    /* 对齐 Python _export_bat_impl 的 prepare()：隔离档位定游戏目录 + 全局模组落位 */
    {
        char game[PYMCL_PATH];
        cJSON *st = version_settings_load(inst, ver);
        const char *iso = st ? cJSON_GetStringValue(cJSON_GetObjectItem(st, "isolation")) : NULL;
        if (ver[0] && iso && (!strcmp(iso, "all") || !strcmp(iso, "saves") || !strcmp(iso, "mods"))) {
            char vd[PYMCL_PATH];
            instance_versions_dir(inst, vd, sizeof(vd));
            pymcl_path_join(game, sizeof(game), vd, ver);
        } else snprintf(game, sizeof(game), "%s", ip);
        cJSON_Delete(st);
        char gm[PYMCL_PATH];
        pymcl_path_join(gm, sizeof(gm), game, "mods");
        global_mods_apply(gm);
    }
    char dest[PYMCL_PATH];
    if (!dest_in[0]) {
        char ex[PYMCL_PATH], rname[256], fn[256];
        pymcl_path_join(ex, sizeof(ex), g_root, "exports");
        pymcl_ensure_dir(ex);
        instance_resolved_name(inst, rname, sizeof(rname));
        snprintf(fn, sizeof(fn), "launch-%s-%s.bat", rname, ver);
        pymcl_path_join(dest, sizeof(dest), ex, fn);
    } else {
        snprintf(dest, sizeof(dest), "%s", dest_in);
        /* 对齐 Python export_launch_bat 的 ensure_dir(dest.parent) */
        char parent[PYMCL_PATH];
        snprintf(parent, sizeof(parent), "%s", dest);
        char *s1 = strrchr(parent, '/'), *s2 = strrchr(parent, '\\');
        char *cut = s1 > s2 ? s1 : s2;
        if (cut && cut != parent) { *cut = '\0'; pymcl_ensure_dir(parent); }
    }

    FILE *f = fopen(dest, "wb");
    if (!f) { cJSON_Delete(cmdarr); pymcl_set_error("无法写出: %s", dest); return -1; }
    fprintf(f, "@echo off\r\nchcp 65001 >nul\r\ncd /d \"%s\"\r\n", ip);
    cJSON *it; int first = 1;
    cJSON_ArrayForEach(it, cmdarr) {
        const char *a = cJSON_GetStringValue(it) ?: "";
        char q[PYMCL_PATH * 2];
        bat_quote(a, q, sizeof(q));
        fprintf(f, "%s%s", first ? "" : " ", q);
        first = 0;
    }
    fprintf(f, "\r\npause\r\n");
    fclose(f);
    cJSON_Delete(cmdarr);
    char lg[PYMCL_PATH + 32];
    snprintf(lg, sizeof(lg), "已写出 %s", dest);
    ctx->on_log(ctx->ud, lg);
    snprintf(msg, msgn, "%s", dest);
    return 0;
}

/* ---------------- install_java ---------------- */

int task_install_java_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    int maj = (int)cJSON_GetNumberValue(cJSON_GetObjectItem(args, "major")) ?: 17;
    if (maj <= 0) maj = 17;
    char vendor[64];
    {
        const char *v = pstr(args, "vendor", "adoptium");
        snprintf(vendor, sizeof(vendor), "%s", v);
        for (char *p = vendor; *p; p++) *p = (char)tolower((unsigned char)*p);
    }
    if (strcmp(vendor, "adoptium") != 0) {
        /* zulu / microsoft 下载源未原生：错误文案与 Python DownloadError 一致 */
        pymcl_set_error("未知的 Java 发行版: %s", vendor);
        return -1;
    }
    char *exe = java_install_adoptium(maj, NULL, ctx);
    if (!exe) return -1;
    char lg[512];
    snprintf(lg, sizeof(lg), "Java 已安装: %s", exe);
    ctx->on_log(ctx->ud, lg);
    char maj_s[16], vend_s[64];
    snprintf(maj_s, sizeof(maj_s), "%d", maj);
    snprintf(vend_s, sizeof(vend_s), "%s", vendor);
    tr_fmt2(msg, msgn, "Java {0} ({1}) 安装完成", maj_s, vend_s);
    free(exe);
    return 0;
}

/* ---------------- start_mod_updates ---------------- */

int task_start_mod_updates_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    cJSON p;
    cJSON *params = cJSON_CreateObject();
    cJSON_AddStringToObject(params, "instance", inst);
    int h = 0;
    cJSON *rows = rpc_mod_update_call("check_mod_updates", params, &h);
    if (!cJSON_IsArray(rows)) {
        cJSON_Delete(params);
        char inner[256]; snprintf(inner, sizeof(inner), "%s", pymcl_error());
        pymcl_set_error("%s", inner);
        return -1;
    }
    int n = cJSON_GetArraySize(rows);
    if (n == 0) {
        cJSON_Delete(rows); cJSON_Delete(params);
        snprintf(msg, msgn, "%s", tr("没有可更新的模组"));
        return 0;
    }
    int i = 0;
    cJSON *row;
    cJSON_ArrayForEach(row, rows) {
        if (ctx->cancel && ctx->cancel(ctx->ud)) {
            cJSON_Delete(rows); cJSON_Delete(params);
            pymcl_set_error("已取消");
            return -1;
        }
        cJSON *ap = cJSON_CreateObject();
        cJSON_AddStringToObject(ap, "instance", inst);
        cJSON_AddItemToObject(ap, "row", cJSON_Duplicate(row, 1));
        int h2 = 0;
        cJSON *name = rpc_mod_update_call("apply_mod_update", ap, &h2);
        cJSON_Delete(ap);
        if (!name) {
            cJSON_Delete(rows); cJSON_Delete(params);
            return -1;
        }
        cJSON_Delete(name);
        char nm[256];
        snprintf(nm, sizeof(nm), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(row, "name")) ?: "");
        if (!nm[0]) snprintf(nm, sizeof(nm), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(row, "filename")) ?: "");
        ctx->on_progress(ctx->ud, nm, ++i, n);
    }
    cJSON_Delete(rows);
    cJSON_Delete(params);
    char num[16]; snprintf(num, sizeof(num), "%d", n);
    tr_fmt0(msg, msgn, "已更新 {0} 个模组", num);
    return 0;
}

/* ---------------- start_self_update ---------------- */

int task_start_self_update_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    (void)args;
    int h = 0;
    cJSON *info = backend_call("check_update", cJSON_CreateObject());
    if (!cJSON_IsObject(info)) { pymcl_set_error("%s", pymcl_error()); return -1; }
    cJSON *hu = cJSON_GetObjectItem(info, "has_update");
    if (!cJSON_IsTrue(hu)) {
        const char *m = cJSON_GetStringValue(cJSON_GetObjectItem(info, "message"));
        snprintf(msg, msgn, "%s", m && m[0] ? m : tr("已是最新版本"));
        cJSON_Delete(info);
        return 0;
    }
    const char *latest = pstr(info, "latest", "");
    const char *sha = pstr(info, "sha256", "");
    const char *url = pstr(info, "url", "");
    if (!url[0] || !valid_sha256(sha)) {
        cJSON_Delete(info);
        pymcl_set_error("更新包缺少有效 SHA-256，已拒绝下载");
        return -1;
    }
    ctx->on_log(ctx->ud, cJSON_GetStringValue(cJSON_GetObjectItem(info, "message")) ?: tr("下载更新"));
    char cache[PYMCL_PATH], dest[PYMCL_PATH];
    pymcl_path_join(cache, sizeof(cache), g_root, "cache");
    pymcl_ensure_dir(cache);
    char fn[128];
    snprintf(fn, sizeof(fn), "PyMCL-%s.bin", latest[0] ? latest : "update");
    pymcl_path_join(dest, sizeof(dest), cache, fn);
    cJSON_Delete(info);

    /* 下载（无 sha1 语义，直接落盘后按清单 sha256 终检） */
    http_resp jr;
    if (http_get(url, &jr, NULL, 300) != 0 || !jr.body || jr.len == 0) {
        char inner[256]; snprintf(inner, sizeof(inner), "%s", pymcl_error());
        http_resp_free(&jr);
        pymcl_set_error("下载更新失败: %s", inner);
        return -1;
    }
    FILE *f = fopen(dest, "wb");
    if (f) { fwrite(jr.body, 1, jr.len, f); fclose(f); }
    http_resp_free(&jr);
    char got[65];
    if (my_sha256_file(dest, got) != 0 || strcmp(got, sha) != 0) {
        DeleteFileA(dest);
        pymcl_set_error("更新包 SHA-256 校验失败");
        return -1;
    }
    char lg[PYMCL_PATH + 40];
    snprintf(lg, sizeof(lg), "更新包已下载: %s", dest);
    ctx->on_log(ctx->ud, lg);
    if (ctx->on_event) {
        cJSON *ev = cJSON_CreateObject();
        cJSON_AddStringToObject(ev, "package", dest);
        cJSON_AddStringToObject(ev, "version", latest);
        ctx->on_event(ctx->event_ud, "update_staged", ev);
        cJSON_Delete(ev);
    }
    tr_fmt0(msg, msgn, "更新包已下载到 {0}，关闭启动器后运行它即可完成更新", dest);
    return 0;
}

/* ---------------- migrate_official_launcher ---------------- */

static int my_dir_exists(const char *p) { return pymcl_dir_exists(p); }

/* 官方 versions/<vid>/<vid>.json 的 inheritsFrom 链（含自身） */
static int inherit_chain(const char *src, const char *vid, char chain[][128], int cap) {
    int n = 0;
    char cur[128];
    snprintf(cur, sizeof(cur), "%s", vid);
    while (cur[0] && n < cap) {
        int dup = 0;
        for (int i = 0; i < n; i++) if (!strcmp(chain[i], cur)) { dup = 1; break; }
        if (dup) break;
        snprintf(chain[n++], 128, "%s", cur);
        char vp[PYMCL_PATH], jf[PYMCL_PATH];
        pymcl_path_join(vp, sizeof(vp), src, "versions");
        pymcl_path_join(vp, sizeof(vp), vp, cur);
        snprintf(jf, sizeof(jf), "%s.json", cur);
        char jp[PYMCL_PATH];
        pymcl_path_join(jp, sizeof(jp), vp, jf);
        cJSON *vjson = pymcl_read_json(jp);
        const char *inh = vjson ? cJSON_GetStringValue(cJSON_GetObjectItem(vjson, "inheritsFrom")) : NULL;
        snprintf(cur, sizeof(cur), "%s", inh ? inh : "");
        cJSON_Delete(vjson);
    }
    return n;
}

static int copy_file2(const char *srcf, const char *dstf) {
    FILE *a = fopen(srcf, "rb");
    if (!a) return -1;
    char parent[PYMCL_PATH];
    snprintf(parent, sizeof(parent), "%s", dstf);
    char *slash = strrchr(parent, '/');
    char *bs = strrchr(parent, '\\');
    char *sp = slash > bs ? slash : bs;
    if (sp) { *sp = '\0'; pymcl_ensure_dir(parent); *sp = (slash > bs) ? '/' : '\\'; }
    FILE *b = fopen(dstf, "wb");
    if (!b) { fclose(a); return -1; }
    char buf[1 << 16];
    size_t r;
    while ((r = fread(buf, 1, sizeof(buf), a)) > 0) fwrite(buf, 1, r, b);
    fclose(a); fclose(b);
    return 0;
}

/* 版本 json 的 libraries → Maven 相对路径（含 natives classifier），去重 */
static int library_relpaths(const char *src, const char *vid, char rels[][512], int cap) {
    int n = 0;
    char chain[8][128];
    int cn = inherit_chain(src, vid, chain, 8);
    for (int c = 0; c < cn; c++) {
        char vp[PYMCL_PATH], jf[PYMCL_PATH], jp[PYMCL_PATH];
        pymcl_path_join(vp, sizeof(vp), src, "versions");
        pymcl_path_join(vp, sizeof(vp), vp, chain[c]);
        snprintf(jf, sizeof(jf), "%s.json", chain[c]);
        pymcl_path_join(jp, sizeof(jp), vp, jf);
        cJSON *vjson = pymcl_read_json(jp);
        cJSON *libs = vjson ? cJSON_GetObjectItem(vjson, "libraries") : NULL;
        cJSON *lib;
        cJSON_ArrayForEach(lib, libs) {
            const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(lib, "name"));
            if (!name) continue;
            const char *paths[2] = { NULL, NULL };
            char nrel[512], arel[512];
            cJSON *dls = cJSON_GetObjectItem(lib, "downloads");
            const char *ap = cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(dls, "artifact"), "path"));
            snprintf(arel, sizeof(arel), "%s", ap ? ap : "");
            if (!arel[0]) pymcl_maven_path(name, "jar", arel, sizeof(arel));
            paths[0] = arel;
            char *nkey = select_native_classifier(lib);
            if (nkey) {
                const char *np = cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(cJSON_GetObjectItem(dls, "classifiers"), nkey), "path"));
                if (np && np[0]) snprintf(nrel, sizeof(nrel), "%s", np);
                else {
                    char spec[512];
                    snprintf(spec, sizeof(spec), "%s:%s", name, nkey);
                    pymcl_maven_path(spec, "jar", nrel, sizeof(nrel));
                }
                paths[1] = nrel;
                free(nkey);
            }
            for (int pi = 0; pi < 2; pi++) {
                if (!paths[pi] || !paths[pi][0]) continue;
                int dup = 0;
                for (int q = 0; q < n; q++) if (!strcmp(rels[q], paths[pi])) { dup = 1; break; }
                if (!dup && n < cap) snprintf(rels[n++], 512, "%s", paths[pi]);
            }
        }
        cJSON_Delete(vjson);
    }
    return n;
}

int task_migrate_official_run(pymcl_ctx *ctx, cJSON *args, char *msg, size_t msgn) {
    const char *inst = pstr(args, "instance", "default");
    char src[PYMCL_PATH];
    {
        const char *appdata = getenv("APPDATA");
        if (!appdata || !appdata[0]) { pymcl_set_error("%s", tr("未找到官方启动器目录")); return -1; }
        pymcl_path_join(src, sizeof(src), appdata, ".minecraft");
    }
    if (!my_dir_exists(src)) { pymcl_set_error("%s", tr("未找到官方启动器目录")); return -1; }
    char lg[PYMCL_PATH + 40];
    snprintf(lg, sizeof(lg), "正在从 %s 迁移…", src);
    ctx->on_log(ctx->ud, lg);
    ctx->on_progress(ctx->ud, tr("扫描版本"), 1, 3);

    /* scan versions */
    char vdir[PYMCL_PATH];
    pymcl_path_join(vdir, sizeof(vdir), src, "versions");
    char vids[256][128];
    int nv = 0;
    if (my_dir_exists(vdir)) {
        wchar_t *w = pymcl_u8_to_wide(vdir);
        wchar_t pat[PYMCL_PATH]; _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
        WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW(pat, &fd); free(w);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
                if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
                char *nm = pymcl_wide_to_u8(fd.cFileName);
                char jf[PYMCL_PATH], jp[PYMCL_PATH];
                pymcl_path_join(jf, sizeof(jf), vdir, nm);
                snprintf(jp, sizeof(jp), "%s.json", nm);
                char jfull[PYMCL_PATH];
                pymcl_path_join(jfull, sizeof(jfull), jf, jp);
                if (pymcl_file_size(jfull) >= 0 && nv < 256) snprintf(vids[nv++], 128, "%s", nm);
                free(nm);
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
    }
    if (nv == 0) {
        ctx->on_log(ctx->ud, tr("未发现版本"));
        snprintf(msg, msgn, "%s", tr("无版本可导入"));
        return 0;
    }
    {
        char lg2[80];
        snprintf(lg2, sizeof(lg2), "发现 %d 个版本", nv);
        ctx->on_log(ctx->ud, lg2);
    }
    char pmsg[160];
    snprintf(pmsg, sizeof(pmsg), "导入 %d 个版本（含依赖库）", nv);
    ctx->on_progress(ctx->ud, pmsg, 2, 3);

    char ip[PYMCL_PATH];
    if (instance_open(inst, ip, sizeof(ip)) != 0) { pymcl_set_error("实例不存在: %s", inst); return -1; }
    instance_ensure_dirs(inst);
    int imported = 0;
    for (int i = 0; i < nv; i++) {
        /* inherit chain 的版本 json/jar 复制 */
        char chain[8][128];
        int cn = inherit_chain(src, vids[i], chain, 8);
        for (int c = 0; c < cn; c++) {
            char vs[PYMCL_PATH], ds[PYMCL_PATH];
            pymcl_path_join(vs, sizeof(vs), src, "versions");
            pymcl_path_join(vs, sizeof(vs), vs, chain[c]);
            pymcl_path_join(ds, sizeof(ds), ip, "versions");
            pymcl_path_join(ds, sizeof(ds), ds, chain[c]);
            pymcl_ensure_dir(ds);
            for (int k = 0; k < 2; k++) {
                char name[300];
                snprintf(name, sizeof(name), "%s.%s", chain[c], k == 0 ? "json" : "jar");
                char s[PYMCL_PATH], d[PYMCL_PATH];
                pymcl_path_join(s, sizeof(s), vs, name);
                pymcl_path_join(d, sizeof(d), ds, name);
                if (pymcl_file_size(s) >= 0) copy_file2(s, d);
            }
        }
        /* libraries 按版本 json 清单复制 */
        char rels[512][512];
        int nr = library_relpaths(src, vids[i], rels, 512);
        char libsrc[PYMCL_PATH];
        pymcl_path_join(libsrc, sizeof(libsrc), src, "libraries");
        for (int r = 0; r < nr; r++) {
            char s[PYMCL_PATH], d[PYMCL_PATH];
            pymcl_path_join(s, sizeof(s), libsrc, rels[r]);
            if (pymcl_file_size(s) < 0) continue;
            pymcl_path_join(d, sizeof(d), ip, "libraries");
            pymcl_path_join(d, sizeof(d), d, rels[r]);
            if (pymcl_file_size(d) >= 0 && pymcl_file_size(d) == pymcl_file_size(s)) continue;
            copy_file2(s, d);
        }
        imported++;
    }
    /* assets 全量复制 */
    {
        char as[PYMCL_PATH], ad[PYMCL_PATH];
        pymcl_path_join(as, sizeof(as), src, "assets");
        pymcl_path_join(ad, sizeof(ad), ip, "assets");
        if (my_dir_exists(as)) {
            pymcl_file_list l = {0};
            pymcl_collect_file_tree(as, "", &l);
            for (int i = 0; i < l.n; i++) {
                char d[PYMCL_PATH];
                pymcl_path_join(d, sizeof(d), ad, l.v[i].rel);
                copy_file2(l.v[i].abs, d);
            }
            free(l.v);
        }
    }
    /* 官方账号导入 */
    char acc_names[16][64];
    int nacc = 0;
    {
        char af[PYMCL_PATH];
        pymcl_path_join(af, sizeof(af), src, "launcher_accounts.json");
        cJSON *data = pymcl_read_json(af);
        cJSON *accs = data ? cJSON_GetObjectItem(data, "accounts") : NULL;
        cJSON *it;
        cJSON_ArrayForEach(it, accs) {
            cJSON *profile = cJSON_GetObjectItem(it, "minecraftProfile");
            const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(profile, "name"));
            const char *uuid = cJSON_GetStringValue(cJSON_GetObjectItem(profile, "id"));
            const char *tok = cJSON_GetStringValue(cJSON_GetObjectItem(it, "accessToken"));
            if (!name || !name[0]) continue;
            cJSON *acc = cJSON_CreateObject();
            cJSON_AddStringToObject(acc, "type", "microsoft");
            cJSON_AddStringToObject(acc, "name", name);
            char dashed[64];
            if (uuid) {
                if (strlen(uuid) == 32)
                    snprintf(dashed, sizeof(dashed), "%.8s-%.4s-%.4s-%.4s-%.6s", uuid, uuid + 8, uuid + 12, uuid + 16, uuid + 20);
                else snprintf(dashed, sizeof(dashed), "%s", uuid);
            } else snprintf(dashed, sizeof(dashed), "");
            cJSON_AddStringToObject(acc, "uuid", dashed);
            cJSON_AddStringToObject(acc, "access_token", tok ? tok : "0");
            double now = (double)time(NULL);
            cJSON_AddNumberToObject(acc, "expires_at", 0); /* 解析不了官方过期时间：一律视为已过期 */
            cJSON_AddNumberToObject(acc, "updated_at", now);
            /* 写进 accounts.json（复用 auth 的落库语义） */
            cJSON *root = accounts_load();
            cJSON *arr = cJSON_GetObjectItem(root, "accounts");
            if (!cJSON_IsArray(arr)) { cJSON_AddArrayToObject(root, "accounts"); arr = cJSON_GetObjectItem(root, "accounts"); }
            cJSON_AddItemToArray(arr, acc);
            accounts_save(root);
            cJSON_Delete(root);
            if (nacc < 16) snprintf(acc_names[nacc++], 64, "%s", name);
        }
        cJSON_Delete(data);
    }
    if (imported > 0)
        instance_set_meta(inst, "mc_version", cJSON_CreateString(vids[nv - 1]));
    {
        char lg3[128];
        snprintf(lg3, sizeof(lg3), "已导入 %d 个版本（含各版本用到的 libraries）", imported);
        ctx->on_log(ctx->ud, lg3);
    }
    if (nacc > 0) {
        char joined[512] = "";
        size_t off = 0;
        for (int i = 0; i < nacc; i++) {
            if (i) off += (size_t)snprintf(joined + off, sizeof(joined) - off, "、");
            off += (size_t)snprintf(joined + off, sizeof(joined) - off, "%s", acc_names[i]);
        }
        char lg4[600];
        snprintf(lg4, sizeof(lg4), "已导入账号: %s", joined);
        ctx->on_log(ctx->ud, lg4);
        ctx->on_log(ctx->ud, "官方只存了访问令牌、没有刷新令牌，过期后需要重新登录");
    }
    char num[16]; snprintf(num, sizeof(num), "%d", imported);
    if (nacc > 0) {
        char an[16]; snprintf(an, sizeof(an), "%d", nacc);
        char base[128], tail[128];
        tr_fmt0(base, sizeof(base), "已导入 {0} 个版本", num);
        tr_fmt0(tail, sizeof(tail), "、{0} 个账号", an);
        snprintf(msg, msgn, "%s%s", base, tail);
    } else {
        tr_fmt0(msg, msgn, "已导入 {0} 个版本", num);
    }
    return 0;
}
