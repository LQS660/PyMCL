/* 模组更新（docs/GOAL-c-bridge-no-python.md M2）：与 mclauncher/mod_update.py 对齐。
 * check_mod_updates：sha1 查 Modrinth version_file → project 版本列表（带 game_versions/loaders
 * 过滤）→ 比版本；Modrinth 查不到再走 CurseForge fingerprints（murmur2）。
 * apply_mod_update：下载新 jar（sha1/size 校验、落地检查）成功后才删旧文件。 */
#include "pymcl.h"

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(o, k));
    return (v && v[0]) ? v : def;
}

/* Modrinth GET：官方 → MCIM 镜像 */
static cJSON *mr_get(const char *path_query) {
    char url[1024];
    snprintf(url, sizeof(url), MODRINTH_API "%s", path_query);
    cJSON *j = http_get_json(url, 20);
    if (j) return j;
    snprintf(url, sizeof(url), MCIM_MIRROR "/modrinth/v2%s", path_query);
    return http_get_json(url, 20);
}

/* CurseForge murmur2 指纹（与 mclauncher/mod_update.py._murmur2 一致） */
static unsigned int murmur2(const unsigned char *data, size_t length) {
    const unsigned int m = 0x5bd1e995u;
    const int r = 24;
    unsigned int h = (1u ^ (unsigned int)length);
    size_t n = length / 4;
    for (size_t i = 0; i < n; i++) {
        unsigned int k;
        memcpy(&k, data + i * 4, 4);
        k *= m; k ^= k >> r; k *= m;
        h *= m; h ^= k;
    }
    const unsigned char *rest = data + n * 4;
    size_t rl = length - n * 4;
    if (rl >= 3) h ^= (unsigned int)rest[2] << 16;
    if (rl >= 2) h ^= (unsigned int)rest[1] << 8;
    if (rl >= 1) { h ^= rest[0]; h *= m; }
    h ^= h >> 13; h *= m; h ^= h >> 15;
    return h;
}

static int cf_fingerprint(const char *path, unsigned int *out) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    /* 去 9/10/13/32 后哈希；先流式过滤避免整包进内存 */
    unsigned char *buf = malloc(1 << 20);
    unsigned char *clean = malloc(1 << 20);
    if (!buf || !clean) { free(buf); free(clean); fclose(f); return -1; }
    size_t cl = 0;
    size_t r;
    while ((r = fread(buf, 1, 1 << 20, f)) > 0) {
        if (cl + r > (1u << 20) * 4) { /* 超大 jar：扩一次 */
            unsigned char *nc = realloc(clean, cl + r);
            if (!nc) { free(buf); free(clean); fclose(f); return -1; }
            clean = nc;
        }
        for (size_t i = 0; i < r; i++) {
            unsigned char b = buf[i];
            if (b == 9 || b == 10 || b == 13 || b == 32) continue;
            clean[cl++] = b;
        }
    }
    fclose(f);
    free(buf);
    *out = murmur2(clean, cl);
    free(clean);
    return 0;
}

/* row_from_mr 的字段拼装（与 Python _modrinth_update 返回一致） */
static cJSON *mr_update_row(const char *filename, const char *digest,
                            const char *mc_version, const char *loader) {
    char pq[256];
    snprintf(pq, sizeof(pq), "/version_file/%s", digest);
    cJSON *cur = mr_get(pq);
    if (!cJSON_IsObject(cur)) { cJSON_Delete(cur); return NULL; }
    const char *project = cJSON_GetStringValue(cJSON_GetObjectItem(cur, "project_id"));
    const char *cur_id = cJSON_GetStringValue(cJSON_GetObjectItem(cur, "id"));
    const char *cur_ver = cJSON_GetStringValue(cJSON_GetObjectItem(cur, "version_number"));
    if (!cur_ver || !cur_ver[0]) cur_ver = cJSON_GetStringValue(cJSON_GetObjectItem(cur, "name"));
    if (!project || !project[0]) { cJSON_Delete(cur); return NULL; }

    char q[256]; q[0] = '\0';
    if (mc_version[0] && loader[0])
        snprintf(q, sizeof(q), "?game_versions=[\"%s\"]&loaders=[\"%s\"]", mc_version, loader);
    else if (mc_version[0])
        snprintf(q, sizeof(q), "?game_versions=[\"%s\"]", mc_version);
    else if (loader[0])
        snprintf(q, sizeof(q), "?loaders=[\"%s\"]", loader);
    char vq[256];
    snprintf(vq, sizeof(vq), "/project/%s/version%s", project, q);
    cJSON *versions = mr_get(vq);
    if (!cJSON_IsArray(versions) || cJSON_GetArraySize(versions) == 0) {
        cJSON_Delete(cur); cJSON_Delete(versions); return NULL;
    }
    cJSON *latest = cJSON_GetArrayItem(versions, 0);
    const char *lat_id = cJSON_GetStringValue(cJSON_GetObjectItem(latest, "id"));
    if (cur_id && lat_id && strcmp(cur_id, lat_id) == 0) {
        cJSON_Delete(cur); cJSON_Delete(versions); return NULL; /* 已是最新 */
    }
    const char *lat_ver = cJSON_GetStringValue(cJSON_GetObjectItem(latest, "version_number"));
    if (!lat_ver || !lat_ver[0]) lat_ver = cJSON_GetStringValue(cJSON_GetObjectItem(latest, "name"));
    cJSON *file = NULL, *f;
    cJSON_ArrayForEach(f, cJSON_GetObjectItem(latest, "files")) {
        if (cJSON_IsTrue(cJSON_GetObjectItem(f, "primary"))) { file = f; break; }
        if (!file) file = f;
    }

    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "filename", filename);
    cJSON_AddStringToObject(row, "name", ""); /* C 侧不解析 jar 内 mod 名，与 stem 对齐由前端处理 */
    cJSON_AddStringToObject(row, "current", cur_ver ? cur_ver : "");
    cJSON_AddStringToObject(row, "latest", lat_ver ? lat_ver : "");
    cJSON_AddStringToObject(row, "project", project);
    cJSON_AddStringToObject(row, "url", file ? (cJSON_GetStringValue(cJSON_GetObjectItem(file, "url")) ? : "") : "");
    cJSON_AddStringToObject(row, "sha1", file ? (cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(file, "hashes"), "sha1")) ? : "") : "");
    cJSON_AddNumberToObject(row, "size", file ? cJSON_GetNumberValue(cJSON_GetObjectItem(file, "size")) : 0);
    cJSON_AddStringToObject(row, "filename_new", file ? (cJSON_GetStringValue(cJSON_GetObjectItem(file, "filename")) ? : "") : "");
    cJSON_AddStringToObject(row, "source", "modrinth");
    cJSON_AddStringToObject(row, "mc_version", mc_version);
    cJSON *gvs = cJSON_AddArrayToObject(row, "game_versions");
    cJSON *gv;
    cJSON_ArrayForEach(gv, cJSON_GetObjectItem(latest, "game_versions"))
        if (cJSON_IsString(gv)) cJSON_AddItemToArray(gvs, cJSON_CreateString(gv->valuestring));
    cJSON_Delete(cur);
    /* versions 数组挂进 row 临时持有再松手 */
    cJSON_Delete(versions);
    return row;
}

static cJSON *cf_update_row(const char *filename, const char *path,
                            const char *mc_version, const char *loader) {
    unsigned int fp;
    if (cf_fingerprint(path, &fp) != 0) return NULL;
    char body[80];
    snprintf(body, sizeof(body), "{\"fingerprints\":[%u]}", fp);
    cJSON *data = cf_post_json("/fingerprints", body);
    cJSON *matches = data ? cJSON_GetObjectItem(cJSON_GetObjectItem(data, "data"), "exactMatches") : NULL;
    if (!cJSON_IsArray(matches) || cJSON_GetArraySize(matches) == 0) { cJSON_Delete(data); return NULL; }
    cJSON *hit = cJSON_GetArrayItem(matches, 0);
    cJSON *file_obj = cJSON_GetObjectItem(hit, "file");
    long long addon_id = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(hit, "id"));
    if (!addon_id) addon_id = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(file_obj, "modId"));
    if (!addon_id) { cJSON_Delete(data); return NULL; }

    char q[128];
    if (mc_version[0]) snprintf(q, sizeof(q), "pageSize=20&gameVersion=%s", mc_version);
    else snprintf(q, sizeof(q), "pageSize=20");
    char p[80]; snprintf(p, sizeof(p), "/mods/%lld/files", addon_id);
    cJSON *fl = cf_get(p, q);
    cJSON *files = fl ? cf_items_of(fl) : NULL;
    if (!files || cJSON_GetArraySize(files) == 0) {
        cJSON_Delete(data); cJSON_Delete(fl); return NULL;
    }
    cJSON *latest = cJSON_GetArrayItem(files, 0);
    long long lat_id = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(latest, "id"));
    long long file_id = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(file_obj, "id"));
    if (lat_id && file_id && lat_id == file_id) {
        cJSON_Delete(data); cJSON_Delete(fl); return NULL; /* 已是最新 */
    }
    const char *lfn = cJSON_GetStringValue(cJSON_GetObjectItem(latest, "fileName"));
    const char *du = cJSON_GetStringValue(cJSON_GetObjectItem(latest, "downloadUrl"));

    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "filename", filename);
    cJSON_AddStringToObject(row, "name", "");
    cJSON_AddStringToObject(row, "current", cJSON_GetStringValue(cJSON_GetObjectItem(file_obj, "displayName")) ? : cJSON_GetStringValue(cJSON_GetObjectItem(file_obj, "fileName")) ? : "");
    cJSON_AddStringToObject(row, "latest", cJSON_GetStringValue(cJSON_GetObjectItem(latest, "displayName")) ? : (lfn ? lfn : ""));
    char proj[32]; snprintf(proj, sizeof(proj), "%lld", addon_id);
    cJSON_AddStringToObject(row, "project", proj);
    cJSON_AddStringToObject(row, "url", (du && du[0]) ? du : "");
    cJSON_AddStringToObject(row, "sha1", "");
    cJSON_AddNumberToObject(row, "size", cJSON_GetNumberValue(cJSON_GetObjectItem(latest, "fileLength")));
    cJSON_AddStringToObject(row, "filename_new", lfn ? lfn : filename);
    cJSON_AddStringToObject(row, "source", "curseforge");
    cJSON_AddNumberToObject(row, "file_id", (double)lat_id);
    cJSON_AddStringToObject(row, "mc_version", mc_version);
    cJSON *gvs = cJSON_AddArrayToObject(row, "game_versions");
    cJSON *gv;
    cJSON_ArrayForEach(gv, cJSON_GetObjectItem(latest, "gameVersions"))
        if (cJSON_IsNumber(gv)) {
            char buf[32]; snprintf(buf, sizeof(buf), "%lld", (long long)gv->valuedouble);
            cJSON_AddItemToArray(gvs, cJSON_CreateString(buf));
        } else if (cJSON_IsString(gv)) cJSON_AddItemToArray(gvs, cJSON_CreateString(gv->valuestring));
    (void)loader;
    cJSON_Delete(data);
    cJSON_Delete(fl);
    return row;
}

cJSON *rpc_mod_update_call(const char *method, cJSON *params, int *handled) {
    if (strcmp(method, "check_mod_updates") == 0) {
        *handled = 1;
        const char *inst = pstr(params, "instance", "default");
        char ip[PYMCL_PATH], dir[PYMCL_PATH];
        if (instance_path(inst, ip, sizeof(ip)) != 0) {
            pymcl_set_error("实例不存在: %s", inst);
            return NULL;
        }
        pymcl_path_join(dir, sizeof(dir), ip, "mods");
        char *mc = mods_detect_mc(inst);
        const char *loader = mods_detect_loader(inst);
        cJSON *out = cJSON_CreateArray();
        if (!pymcl_dir_exists(dir)) { free(mc); return out; }
        wchar_t *w = pymcl_u8_to_wide(dir);
        wchar_t pat[PYMCL_PATH];
        _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
        WIN32_FIND_DATAW fd;
        HANDLE h = FindFirstFileW(pat, &fd);
        free(w);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
                char *n = pymcl_wide_to_u8(fd.cFileName);
                if (!pymcl_endswith(n, ".jar")) { free(n); continue; }
                char path[PYMCL_PATH];
                pymcl_path_join(path, sizeof(path), dir, n);
                char digest[41];
                if (pymcl_sha1_file(path, digest) == 0) {
                    cJSON *row = mr_update_row(n, digest, mc ? mc : "", loader ? loader : "");
                    if (!row) row = cf_update_row(n, path, mc ? mc : "", loader ? loader : "");
                    if (row) cJSON_AddItemToArray(out, row);
                }
                free(n);
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
        free(mc);
        return out;
    }
    if (strcmp(method, "apply_mod_update") == 0) {
        *handled = 1;
        const char *inst = pstr(params, "instance", "default");
        cJSON *row = cJSON_GetObjectItem(params, "row");
        if (!cJSON_IsObject(row)) { pymcl_set_error("缺少更新行"); return NULL; }
        const char *url = pstr(row, "url", "");
        if (!url[0]) { pymcl_set_error("没有可下载的更新地址"); return NULL; }
        const char *old_name = pstr(row, "filename", "");
        const char *new_name = pstr(row, "filename_new", "");
        if (!new_name[0]) new_name = old_name;
        char ip[PYMCL_PATH], dir[PYMCL_PATH], dest[PYMCL_PATH];
        if (instance_path(inst, ip, sizeof(ip)) != 0) { pymcl_set_error("实例不存在: %s", inst); return NULL; }
        pymcl_path_join(dir, sizeof(dir), ip, "mods");
        pymcl_ensure_dir(dir);
        pymcl_path_join(dest, sizeof(dest), dir, new_name);

        const char *sha1 = pstr(row, "sha1", "");
        long long size = (long long)cJSON_GetNumberValue(cJSON_GetObjectItem(row, "size"));
        char mir[2048];
        mods_mirror_mr(url, mir, sizeof(mir));
        const char *ex[] = { url };
        if (strcmp(mir, url) == 0) {
            if (download_file(url, NULL, 0, dest, NULL, sha1[0] ? sha1 : NULL, size > 0 ? size : -1, NULL) != 0)
                return NULL;
        } else {
            if (download_file(mir, ex, 1, dest, NULL, sha1[0] ? sha1 : NULL, size > 0 ? size : -1, NULL) != 0)
                return NULL;
        }
        /* 只有确认新文件真的落地了才删旧的（与 Python 注释同一条规矩） */
        long long got = pymcl_file_size(dest);
        if (got <= 0) {
            DeleteFileA(dest);
            pymcl_set_error("更新包没有正确落地，已保留原文件: %s", new_name);
            return NULL;
        }
        if (size > 0 && got != size) {
            DeleteFileA(dest);
            pymcl_set_error("更新包大小与清单不符（%lld != %lld），已保留原文件", got, size);
            return NULL;
        }
        if (old_name[0] && strcmp(old_name, new_name) != 0) {
            char oldp[PYMCL_PATH];
            pymcl_path_join(oldp, sizeof(oldp), dir, old_name);
            DeleteFileA(oldp);
        }
        return cJSON_CreateString(new_name);
    }
    return NULL;
}
