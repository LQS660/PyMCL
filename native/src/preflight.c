/* 启动前预检：mclauncher/preflight.py 的逐条移植（对齐 PCL「先查再启」）。 */
#include "pymcl.h"
#include <ctype.h>
#include <math.h>
#include <stdarg.h>

#define PF_MAX_LIB_CHECK 400
#define PF_MAX_ASSET_SAMPLE 80
#define PF_MAX_MOD_JARS 120

static cJSON *pf_item(const char *level, const char *code, const char *title, const char *detail) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "level", level);
    cJSON_AddStringToObject(o, "code", code);
    cJSON_AddStringToObject(o, "title", title);
    cJSON_AddStringToObject(o, "detail", detail);
    return o;
}

static cJSON *pf_itemf(const char *level, const char *code, const char *title, const char *fmt, ...) {
    char detail[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(detail, sizeof(detail), fmt, ap);
    va_end(ap);
    return pf_item(level, code, title, detail);
}

static int pf_file_matches(const char *path, const char *sha1, double size) {
    if (!pymcl_file_exists(path)) return 0;
    if (size >= 0) {
        long long actual = pymcl_file_size(path);
        if (actual >= 0 && (double)actual != size) return 0;
    }
    if (sha1 && sha1[0]) {
        char hex[41];
        if (pymcl_sha1_file(path, hex) != 0) return 0;
        if (!pymcl_ieq(hex, sha1)) return 0;
    }
    return 1;
}

/* 与 Python sorted(dir.iterdir()) 一致：按名字节序排序 */
static int pf_cmp_str(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}
static char **pf_sorted_names(const char *dir, int *n) {
    cJSON *names = pymcl_list_dir(dir, 0, 0);
    if (!names || !cJSON_IsArray(names)) { cJSON_Delete(names); *n = 0; return NULL; }
    int cnt = cJSON_GetArraySize(names);
    char **arr = (char **)calloc((size_t)cnt + 1, sizeof(char *));
    int k = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, names) {
        const char *s = cJSON_GetStringValue(it);
        if (s) arr[k++] = pymcl_strdup(s);
    }
    cJSON_Delete(names);
    qsort(arr, (size_t)k, sizeof(char *), pf_cmp_str);
    *n = k;
    return arr;
}
static void pf_free_names(char **arr, int n) {
    for (int i = 0; i < n; i++) free(arr[i]);
    free(arr);
}
static int pf_is_dir(const char *p) { return pymcl_dir_exists(p); }
static int pf_is_file(const char *p) { return pymcl_file_exists(p) && !pymcl_dir_exists(p); }

/* ---------- ai/conflict.inspect_jar：jar 元数据 ---------- */

static void pf_dep_push(cJSON *arr, const char *id, const char *version) {
    if (!id || !id[0]) return;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "id", id);
    cJSON_AddStringToObject(o, "version", version && version[0] ? version : "*");
    cJSON_AddItemToArray(arr, o);
}

/* fabric _as_map：dict → [{id,version}]；list[dict] → id 取 id/mod，version 取 versions/version；
   list[str] → {id,version:"*"} */
static cJSON *pf_as_map(cJSON *val) {
    cJSON *out = cJSON_CreateArray();
    if (cJSON_IsObject(val)) {
        cJSON *it;
        cJSON_ArrayForEach(it, val) {
            char vs[128];
            if (cJSON_IsNumber(it)) snprintf(vs, sizeof(vs), "%g", it->valuedouble);
            else snprintf(vs, sizeof(vs), "%s", cJSON_GetStringValue(it) ?: "");
            pf_dep_push(out, it->string, vs);
        }
    } else if (cJSON_IsArray(val)) {
        cJSON *it;
        cJSON_ArrayForEach(it, val) {
            if (cJSON_IsObject(it)) {
                const char *id = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "";
                if (!id[0]) id = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "mod")) ?: "";
                const char *v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "versions")) ?: "";
                if (!v[0]) v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "version")) ?: "";
                pf_dep_push(out, id, v);
            } else if (!cJSON_IsNull(it)) {
                char ids[128];
                if (cJSON_IsString(it)) snprintf(ids, sizeof(ids), "%s", it->valuestring);
                else if (cJSON_IsNumber(it)) snprintf(ids, sizeof(ids), "%g", it->valuedouble);
                else snprintf(ids, sizeof(ids), "");
                if (ids[0]) pf_dep_push(out, ids, "*");
            }
        }
    }
    return out;
}

typedef struct {
    char modId[128];
    char displayName[256];
    char version[128];
    char owner[128];
    char dep_modId[128];
    char dep_type[32];
    int dep_mandatory;   /* -1 未写 */
} pf_forge_row;

/* 直接解析 mods.toml：主 mods 行 + dependencies 行，语义与 _from_forge_toml 一致 */
static void pf_forge_fill(const char *text, const char *flavor, cJSON *info) {
    char primary_modId[128] = "", primary_disp[256] = "", primary_ver[128] = "";
    char loader[64];
    snprintf(loader, sizeof(loader), "%s", flavor);
    char owner[128] = "";
    int have_dep = 0;
    char d_mid[128] = "", d_type[32] = "", d_vr[128] = "";
    int d_mand = -1;
    cJSON *depends = cJSON_CreateArray();
    cJSON *breaks = cJSON_CreateArray();

    const char *p = text;
    while (*p) {
        char line[1024];
        size_t li = 0;
        while (*p && *p != '\n' && li < sizeof(line) - 1) {
            if (*p != '\r') line[li++] = *p;
            p++;
        }
        if (*p == '\n') p++;
        line[li] = 0;
        char *s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (!*s || *s == '#') continue;
        if (*s == '[') {
            /* 先把攒着的 dep 落库 */
            if (have_dep && d_mid[0]) {
                char own[128];
                snprintf(own, sizeof(own), "%s", owner);
                if (primary_modId[0] && own[0] && strcmp(own, primary_modId) != 0) {
                    /* owner 不是主 mod：跳过（同 Python mid and owner not in (mid, "")） */
                } else {
                    int is_break = !_strnicmp(d_type, "incompatible", 12) || !_strnicmp(d_type, "broke", 5)
                                   || !_strnicmp(d_type, "break", 5) || !_strnicmp(d_type, "breaks", 6);
                    cJSON *rec = cJSON_CreateObject();
                    cJSON_AddStringToObject(rec, "id", d_mid);
                    cJSON_AddBoolToObject(rec, "mandatory", d_mand != 0);
                    cJSON_AddStringToObject(rec, "version", d_vr[0] ? d_vr : "*");
                    if (is_break || d_mand != 0)
                        cJSON_AddItemToArray(is_break ? breaks : depends, rec);
                        else cJSON_Delete(rec);
                }
            }
            have_dep = 0; d_mid[0] = 0; d_type[0] = 0; d_vr[0] = 0; d_mand = -1;
            char *e = s + 1;
            if (*e == '[') e++;
            char *end = strchr(e, ']');
            if (!end) continue;
            *end = 0;
            if (!strncmp(e, "dependencies", 12) && e[12] == '.') {
                snprintf(owner, sizeof(owner), "%s", e + 13);
                have_dep = 1;
            } else if (strncmp(e, "mods", 4) == 0 && strlen(e) == 4) {
                owner[0] = 0;   /* 新主行 */
            }
            continue;
        }
        char *eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        char *key = s;
        while (*key && (key[strlen(key) - 1] == ' ')) key[strlen(key) - 1] = 0;
        char *val = eq + 1;
        while (*val == ' ' || *val == '\t') val++;
        size_t L = strlen(val);
        if (L >= 2 && ((val[0] == '"' && val[L - 1] == '"') || (val[0] == '\'' && val[L - 1] == '\''))) {
            val[L - 1] = 0;
            memmove(val, val + 1, L - 1);
        }
        if (!strcmp(key, "modLoader")) snprintf(loader, sizeof(loader), "%s", val);
        else if (!strcmp(key, "modId")) {
            if (owner[0]) snprintf(d_mid, sizeof(d_mid), "%s", val);
            else snprintf(primary_modId, sizeof(primary_modId), "%s", val);
        } else if (!strcmp(key, "displayName") && !owner[0]) snprintf(primary_disp, sizeof(primary_disp), "%s", val);
        else if (!strcmp(key, "version")) {
            if (owner[0]) snprintf(d_vr, sizeof(d_vr), "%s", val);
            else snprintf(primary_ver, sizeof(primary_ver), "%s", val);
        } else if (!strcmp(key, "versionRange") && owner[0]) snprintf(d_vr, sizeof(d_vr), "%s", val);
        else if (!strcmp(key, "type") && owner[0]) snprintf(d_type, sizeof(d_type), "%s", val);
        else if (!strcmp(key, "mandatory") && owner[0]) d_mand = _strnicmp(val, "true", 4) == 0;
    }
    if (have_dep && d_mid[0]) {
        if (!primary_modId[0] || !owner[0] || strcmp(owner, primary_modId) == 0) {
            int is_break = !_strnicmp(d_type, "incompatible", 12) || !_strnicmp(d_type, "broke", 5)
                           || !_strnicmp(d_type, "break", 5) || !_strnicmp(d_type, "breaks", 6);
            cJSON *rec = cJSON_CreateObject();
            cJSON_AddStringToObject(rec, "id", d_mid);
            cJSON_AddBoolToObject(rec, "mandatory", d_mand != 0);
            cJSON_AddStringToObject(rec, "version", d_vr[0] ? d_vr : "*");
            if (is_break || d_mand != 0)
                cJSON_AddItemToArray(is_break ? breaks : depends, rec);
            else cJSON_Delete(rec);
        }
    }
    cJSON_ReplaceItemInObjectCaseSensitive(info, "id", cJSON_CreateString(primary_modId));
    cJSON_ReplaceItemInObjectCaseSensitive(info, "name",
                                           cJSON_CreateString(primary_disp[0] ? primary_disp : primary_modId));
    cJSON_ReplaceItemInObjectCaseSensitive(info, "version", cJSON_CreateString(primary_ver));
    cJSON_ReplaceItemInObjectCaseSensitive(info, "loader",
                                           cJSON_CreateString(strstr(loader, "neo") || strstr(loader, "Neo") ? "neoforge" : "forge"));
    cJSON_ReplaceItemInObjectCaseSensitive(info, "depends", depends);
    cJSON_ReplaceItemInObjectCaseSensitive(info, "breaks", breaks);
    cJSON_ReplaceItemInObjectCaseSensitive(info, "conflicts", cJSON_CreateArray());
}

/* 从 zip 里的元数据文件填 info；返回命中哪一种 */
static void pf_inspect_jar(const char *path, cJSON *info) {
    const char *base = pymcl_basename(path);
    char stem[512];
    snprintf(stem, sizeof(stem), "%s", base);
    char *dot = strrchr(stem, '.');
    if (dot) *dot = 0;   /* path.stem：只去最后一个后缀（x.jar.disabled → x.jar） */
    cJSON_AddStringToObject(info, "file", base);
    cJSON_AddStringToObject(info, "id", stem);
    cJSON_AddStringToObject(info, "name", stem);
    cJSON_AddStringToObject(info, "version", "");
    cJSON_AddStringToObject(info, "loader", "unknown");
    cJSON_AddItemToObject(info, "depends", cJSON_CreateArray());
    cJSON_AddItemToObject(info, "breaks", cJSON_CreateArray());
    cJSON_AddItemToObject(info, "conflicts", cJSON_CreateArray());
    cJSON_AddItemToObject(info, "provides", cJSON_CreateArray());
    cJSON_AddBoolToObject(info, "enabled", !pymcl_endswith(base, ".disabled"));

    struct { const char *inner; const char *kind; } table[] = {
        {"fabric.mod.json", "fabric"},
        {"quilt.mod.json", "quilt"},
        {"META-INF/neoforge.mods.toml", "neoforge"},
        {"META-INF/mods.toml", "forge"},
        {"mcmod.info", "mcmod"},
    };
    for (size_t i = 0; i < sizeof(table) / sizeof(table[0]); i++) {
        if (!pymcl_zip_has(path, table[i].inner)) continue;
        size_t len = 0;
        char *text = pymcl_zip_read(path, table[i].inner, &len);
        if (!text) return;
        /* 审计 05 P1-4 前置缺陷：原来传 len（**不含**结尾 0）+ require_null_terminated=1。
           cJSON 的该分支判据是 `buffer.offset >= buffer.length`（cJSON.c:1135-1140），
           解析到末尾时 offset == len == length → 直接判失败 → 这段元数据解析**从未成功过**，
           fabric / forge / quilt 的 id / name / version / depends 永远是默认值
           （id=文件名、loader=unknown）。带上结尾 0 的长度才符合参数语义。 */
        cJSON *data = cJSON_ParseWithLengthOpts(text, len + 1, NULL, 1);
        if (!data) { free(text); return; }
        if (!strcmp(table[i].kind, "fabric")) {
            cJSON_ReplaceItemInObjectCaseSensitive(info, "id", cJSON_CreateString(
                cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(data, "id")) ?: ""));
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(data, "name")) ?: "";
            if (!nm[0]) nm = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(data, "id")) ?: "";
            cJSON_ReplaceItemInObjectCaseSensitive(info, "name", cJSON_CreateString(nm));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "version", cJSON_CreateString(
                cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(data, "version")) ?: ""));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "loader", cJSON_CreateString("fabric"));
            cJSON *dv = cJSON_GetObjectItemCaseSensitive(data, "depends");
            cJSON *bv = cJSON_GetObjectItemCaseSensitive(data, "breaks");
            cJSON *cv = cJSON_GetObjectItemCaseSensitive(data, "conflicts");
            cJSON_ReplaceItemInObjectCaseSensitive(info, "depends", pf_as_map(dv));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "breaks", pf_as_map(bv));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "conflicts", pf_as_map(cv));
        } else if (!strcmp(table[i].kind, "quilt")) {
            cJSON *ql = cJSON_GetObjectItemCaseSensitive(data, "quilt_loader");
            if (!cJSON_IsObject(ql)) ql = data;
            const char *qid = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(ql, "id")) ?: "";
            const char *did = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(data, "id")) ?: "";
            cJSON_ReplaceItemInObjectCaseSensitive(info, "id", cJSON_CreateString(qid[0] ? qid : did));
            cJSON *md = cJSON_GetObjectItemCaseSensitive(ql, "metadata");
            const char *mdn = cJSON_IsObject(md)
                ? (cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(md, "name")) ?: "") : "";
            if (!mdn[0]) mdn = qid[0] ? qid : did;
            cJSON_ReplaceItemInObjectCaseSensitive(info, "name", cJSON_CreateString(mdn));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "version", cJSON_CreateString(
                cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(ql, "version")) ?: ""));
            cJSON_ReplaceItemInObjectCaseSensitive(info, "loader", cJSON_CreateString("quilt"));
            cJSON *nd = cJSON_CreateArray(), *nb = cJSON_CreateArray();
            cJSON *it;
            cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(ql, "depends"))
                if (cJSON_IsObject(it))
                    pf_dep_push(nd, cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "",
                                cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "versions")) ?: "*");
            cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(ql, "breaks"))
                if (cJSON_IsObject(it))
                    pf_dep_push(nb, cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "",
                                cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "versions")) ?: "*");
            cJSON_ReplaceItemInObjectCaseSensitive(info, "depends", nd);
            cJSON_ReplaceItemInObjectCaseSensitive(info, "breaks", nb);
        } else if (!strcmp(table[i].kind, "mcmod")) {
            cJSON *row = NULL;
            if (cJSON_IsArray(data) && cJSON_GetArraySize(data) > 0)
                row = cJSON_GetArrayItem(data, 0);
            else if (cJSON_IsObject(data)) row = data;
            if (row) {
                const char *modid = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(row, "modid")) ?: "";
                const char *nm = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(row, "name")) ?: "";
                cJSON_ReplaceItemInObjectCaseSensitive(info, "id", cJSON_CreateString(modid[0] ? modid : stem));
                cJSON_ReplaceItemInObjectCaseSensitive(info, "name", cJSON_CreateString(nm[0] ? nm : stem));
                cJSON_ReplaceItemInObjectCaseSensitive(info, "version", cJSON_CreateString(
                    cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(row, "version")) ?: ""));
                cJSON_ReplaceItemInObjectCaseSensitive(info, "loader", cJSON_CreateString("forge"));
                cJSON *nd = cJSON_CreateArray();
                cJSON *it;
                cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(row, "requiredMods"))
                    pf_dep_push(nd, cJSON_GetStringValue(it) ?: "", "*");
                cJSON_ReplaceItemInObjectCaseSensitive(info, "depends", nd);
            }
        } else {
            pf_forge_fill(text, table[i].kind, info);
        }
        free(text);
        cJSON_Delete(data);
        break;
    }
}

/* 全局 Mod 池里启用 jar 的模组 id 集合 */
static void pf_global_mod_ids(cJSON *ids) {
    char gdir[PYMCL_PATH];
    {
        char custom[PYMCL_PATH] = "";
        cJSON *v = config_get("global_mods_dir");
        if (py_truthy(v)) py_str(v, custom, sizeof(custom));
        char *s = custom;
        while (*s && isspace((unsigned char)*s)) s++;
        size_t len = strlen(s);
        while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
        if (s[0]) pymcl_py_path(s, gdir, sizeof(gdir));
        else pymcl_path_join3(gdir, sizeof(gdir), g_root, "shared", "mods");
    }
    if (!pf_is_dir(gdir)) return;
    int n = 0;
    char **names = pf_sorted_names(gdir, &n);
    int cnt = 0;
    for (int i = 0; i < n && cnt < PF_MAX_MOD_JARS; i++) {
        if (!pymcl_endswith(names[i], ".jar")) continue;
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), gdir, names[i]);
        if (!pf_is_file(p)) continue;
        cJSON *info = cJSON_CreateObject();
        pf_inspect_jar(p, info);
        const char *mid = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(info, "id")) ?: "";
        if (mid[0]) cJSON_AddTrueToObject(ids, mid);   /* 大小写在查重时归一 */
        cJSON_Delete(info);
        cnt++;
    }
    pf_free_names(names, n);
}

static int pf_ids_has(cJSON *ids, const char *mid) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(ids, mid);
    return v != NULL;
}

static void pf_check_mod_conflicts(const char *mods_path, cJSON *items) {
    int n = 0;
    char **names = pf_sorted_names(mods_path, &n);
    char **jars = (char **)calloc((size_t)n + 1, sizeof(char *));
    int nj = 0;
    for (int i = 0; i < n && nj < PF_MAX_MOD_JARS; i++) {
        const char *ln = names[i];
        size_t L = strlen(ln);
        char low[512];
        snprintf(low, sizeof(low), "%s", ln);
        for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
        if (L >= 4 && !strcmp(low + L - 4, ".jar")) jars[nj++] = pymcl_strdup(names[i]);
        else if (L >= 13 && !strcmp(low + L - 13, ".jar.disabled")) jars[nj++] = pymcl_strdup(names[i]);
    }
    pf_free_names(names, n);
    if (!nj) { free(jars); return; }

    cJSON *mods = cJSON_CreateArray();
    for (int i = 0; i < nj; i++) {
        if (pymcl_endswith(jars[i], ".disabled")) continue;
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), mods_path, jars[i]);
        if (!pf_is_file(p)) continue;
        cJSON *info = cJSON_CreateObject();
        pf_inspect_jar(p, info);
        cJSON_ReplaceItemInObjectCaseSensitive(info, "file", cJSON_CreateString(jars[i]));
        cJSON_AddItemToArray(mods, info);
    }

    /* 重复 id */
    cJSON *seen = cJSON_CreateObject();
    char dups[4096] = "";
    cJSON *it;
    cJSON_ArrayForEach(it, mods) {
        char mid[256];
        snprintf(mid, sizeof(mid), "%s", cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "");
        for (char *q = mid; *q; q++) *q = (char)tolower((unsigned char)*q);
        if (!mid[0]) continue;
        cJSON *slot = cJSON_GetObjectItemCaseSensitive(seen, mid);
        if (!slot) { cJSON_AddNumberToObject(seen, mid, 1); continue; }
        slot->valuedouble = slot->valuedouble + 1;
    }
    /* 行格式 "{mid} ×{n}（file1, file2, file3）"，按首现顺序重建（同 Python） */
    {
        cJSON *order = cJSON_CreateArray();
        cJSON_ArrayForEach(it, mods) {
            char mid[256];
            snprintf(mid, sizeof(mid), "%s", cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "");
            for (char *q = mid; *q; q++) *q = (char)tolower((unsigned char)*q);
            if (!mid[0]) continue;
            if (!cJSON_GetObjectItemCaseSensitive(seen, mid)) continue;
            int listed = 0;
            cJSON *o2;
            cJSON_ArrayForEach(o2, order) if (!strcmp(cJSON_GetStringValue(o2), mid)) listed = 1;
            if (!listed) cJSON_AddItemToArray(order, cJSON_CreateString(mid));
        }
        cJSON *o2;
        cJSON_ArrayForEach(o2, order) {
            const char *mid = cJSON_GetStringValue(o2);
            int cntn = 0;
            char files[3][512];
            int nf = 0;
            cJSON_ArrayForEach(it, mods) {
                char m2[256];
                snprintf(m2, sizeof(m2), "%s", cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "");
                for (char *q = m2; *q; q++) *q = (char)tolower((unsigned char)*q);
                if (strcmp(m2, mid)) continue;
                cntn++;
                if (nf < 3) snprintf(files[nf++], sizeof(files[0]), "%s",
                                    cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "file")) ?: "?");
            }
            if (cntn < 2) continue;
            char line2[1024];
            snprintf(line2, sizeof(line2), "%s ×%d（", mid, cntn);
            for (int f = 0; f < nf; f++) {
                if (f) strncat(line2, ", ", sizeof(line2) - strlen(line2) - 1);
                strncat(line2, files[f], sizeof(line2) - strlen(line2) - 1);
            }
            strncat(line2, "）", sizeof(line2) - strlen(line2) - 1);
            if (dups[0]) strncat(dups, "\n - ", sizeof(dups) - strlen(dups) - 1);
            strncat(dups, line2, sizeof(dups) - strlen(dups) - 1);
        }
        cJSON_Delete(order);
    }
    if (dups[0]) {
        char detail[4608];
        snprintf(detail, sizeof(detail), "同 id 装了多份会导致启动失败：\n - %s", dups);
        cJSON_AddItemToArray(items, pf_item("error", "mod_duplicate", "重复安装同一模组", detail));
    }

    cJSON *present = cJSON_CreateObject();
    cJSON_ArrayForEach(it, mods) {
        char mid[256];
        snprintf(mid, sizeof(mid), "%s", cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "");
        for (char *q = mid; *q; q++) *q = (char)tolower((unsigned char)*q);
        if (mid[0]) cJSON_AddTrueToObject(present, mid);
    }
    cJSON *gids = cJSON_CreateObject();
    pf_global_mod_ids(gids);
    int fabric_present = pf_ids_has(present, "fabric-api") || pf_ids_has(present, "fabricapi")
                         || pf_ids_has(gids, "fabric-api") || pf_ids_has(gids, "fabricapi");
    cJSON_Delete(gids);

    char breaks_txt[4096] = "", fab_dep[4096] = "", other_dep[4096] = "";
    cJSON_ArrayForEach(it, mods) {
        const char *mid = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "id")) ?: "";
        const char *fname = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "file")) ?: "";
        const char *mname = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "name")) ?: "";
        cJSON *rows;
        cJSON_ArrayForEach(rows, cJSON_GetObjectItemCaseSensitive(it, "breaks")) {
            char bid[256];
            snprintf(bid, sizeof(bid), "%s",
                     cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(rows, "id")) ?: "");
            for (char *q = bid; *q; q++) *q = (char)tolower((unsigned char)*q);
            if (bid[0] && pf_ids_has(present, bid)) {
                char line[600];
                snprintf(line, sizeof(line), "%s ↔ %s", mid, bid);
                if (breaks_txt[0]) strncat(breaks_txt, "\n - ", sizeof(breaks_txt) - strlen(breaks_txt) - 1);
                strncat(breaks_txt, line, sizeof(breaks_txt) - strlen(breaks_txt) - 1);
            }
        }
        cJSON_ArrayForEach(rows, cJSON_GetObjectItemCaseSensitive(it, "conflicts")) {
            char bid[256];
            snprintf(bid, sizeof(bid), "%s",
                     cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(rows, "id")) ?: "");
            for (char *q = bid; *q; q++) *q = (char)tolower((unsigned char)*q);
            if (bid[0] && pf_ids_has(present, bid)) {
                char line[600];
                snprintf(line, sizeof(line), "%s ↔ %s", mid, bid);
                if (breaks_txt[0]) strncat(breaks_txt, "\n - ", sizeof(breaks_txt) - strlen(breaks_txt) - 1);
                strncat(breaks_txt, line, sizeof(breaks_txt) - strlen(breaks_txt) - 1);
            }
        }
        cJSON_ArrayForEach(rows, cJSON_GetObjectItemCaseSensitive(it, "depends")) {
            char did[256];
            snprintf(did, sizeof(did), "%s",
                     cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(rows, "id")) ?: "");
            for (char *q = did; *q; q++) *q = (char)tolower((unsigned char)*q);
            if (!did[0]) continue;
            if (!strcmp(did, "minecraft") || !strcmp(did, "java") || !strcmp(did, "forge")
                || !strcmp(did, "neoforge") || !strcmp(did, "fabricloader") || !strcmp(did, "fabric-loader")
                || !strcmp(did, "quilt_loader") || !strcmp(did, "quilt-loader")) continue;
            char line[1024];
            if (!strcmp(did, "fabric-api") || !strcmp(did, "fabricapi") || !strcmp(did, "fabric")) {
                if (fabric_present) continue;
                snprintf(line, sizeof(line), "%s 需要 Fabric API", mname[0] ? mname : fname);
                if (fab_dep[0]) strncat(fab_dep, "\n - ", sizeof(fab_dep) - strlen(fab_dep) - 1);
                strncat(fab_dep, line, sizeof(fab_dep) - strlen(fab_dep) - 1);
                continue;
            }
            if (!pf_ids_has(present, did)) {
                snprintf(line, sizeof(line), "%s 缺少 %s", mname[0] ? mname : fname, did);
                if (other_dep[0]) strncat(other_dep, "\n - ", sizeof(other_dep) - strlen(other_dep) - 1);
                strncat(other_dep, line, sizeof(other_dep) - strlen(other_dep) - 1);
            }
        }
    }
    cJSON_Delete(present);
    if (breaks_txt[0]) {
        char detail[4608];
        snprintf(detail, sizeof(detail), "元数据声明不兼容：\n - %s", breaks_txt);
        cJSON_AddItemToArray(items, pf_item("error", "mod_breaks", "模组互相冲突", detail));
    }
    if (fab_dep[0]) cJSON_AddItemToArray(items, pf_item("error", "mod_missing_fabric_api", "缺少 Fabric API", fab_dep));
    if (other_dep[0]) {
        char detail[4608];
        snprintf(detail, sizeof(detail), "%s\n（若实际由其它 jar 提供可忽略）", other_dep);
        cJSON_AddItemToArray(items, pf_item("warn", "mod_missing_dep", "可能缺少模组依赖", detail));
    }
    free(jars);
}

static void pf_check_libraries(const char *inst, cJSON *resolved, cJSON *items) {
    char libs[PYMCL_PATH];
    instance_libraries_dir(inst, libs, sizeof(libs));
    char *missing[64];
    int nmissing = 0, nmissing_all = 0;
    char *bad_hash[64];
    int nbad = 0, nbad_all = 0;
    int checked = 0;
    cJSON *lib;
    cJSON_ArrayForEach(lib, cJSON_GetObjectItemCaseSensitive(resolved, "libraries")) {
        if (checked >= PF_MAX_LIB_CHECK) break;
        if (cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(lib, "clientreq"))) continue;
        if (!pymcl_check_rules(cJSON_GetObjectItemCaseSensitive(lib, "rules"), 0)) continue;
        const char *name = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(lib, "name"));
        if (!name) continue;
        cJSON *downloads = cJSON_GetObjectItemCaseSensitive(lib, "downloads");
        cJSON *artifact = cJSON_IsObject(downloads)
            ? cJSON_GetObjectItemCaseSensitive(downloads, "artifact") : NULL;
        /* Python 真值：{} 与缺失都算假 */
        if (py_truthy(artifact) || (!py_truthy(downloads) && !py_truthy(cJSON_GetObjectItemCaseSensitive(lib, "natives")))) {
            char rel[512], dest[PYMCL_PATH];
            const char *apath = cJSON_IsObject(artifact)
                ? cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(artifact, "path")) : NULL;
            if (apath && apath[0]) snprintf(rel, sizeof(rel), "%s", apath);
            else pymcl_maven_path(name, "jar", rel, sizeof(rel));
            pymcl_path_join(dest, sizeof(dest), libs, rel);
            const char *sha1 = cJSON_IsObject(artifact)
                ? cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(artifact, "sha1")) : NULL;
            cJSON *szv = cJSON_IsObject(artifact) ? cJSON_GetObjectItemCaseSensitive(artifact, "size") : NULL;
            double size = cJSON_IsNumber(szv) ? szv->valuedouble : -1;
            checked++;
            const char *bn = pymcl_basename(rel);
            if (!pf_is_file(dest)) {
                nmissing_all++;
                if (nmissing < 64) missing[nmissing++] = pymcl_strdup(bn);
            } else if ((sha1 && sha1[0]) || size >= 0) {
                if (!pf_file_matches(dest, sha1, size)) {
                    nbad_all++;
                    if (nbad < 64) bad_hash[nbad++] = pymcl_strdup(bn);
                }
            }
        }
        char *nkey = select_native_classifier(lib);
        if (nkey && checked < PF_MAX_LIB_CHECK) {
            cJSON *classifiers = cJSON_IsObject(downloads)
                ? cJSON_GetObjectItemCaseSensitive(downloads, "classifiers") : NULL;
            cJSON *entry = cJSON_IsObject(classifiers)
                ? cJSON_GetObjectItemCaseSensitive(classifiers, nkey) : NULL;
            if (!cJSON_IsObject(entry) && cJSON_IsObject(classifiers)) {
                cJSON *kv;
                cJSON_ArrayForEach(kv, classifiers) {
                    /* Python: subst_native_key(k) == nkey —— C 的 select_native_classifier
                       已经做过 ${arch} 归一，这里键比较即可 */
                    if (kv->string && !strcmp(kv->string, nkey)) { entry = kv; break; }
                }
            }
            char rel[512], dest[PYMCL_PATH];
            const char *epath = cJSON_IsObject(entry)
                ? cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "path")) : NULL;
            if (epath && epath[0]) snprintf(rel, sizeof(rel), "%s", epath);
            else {
                char withkey[600];
                snprintf(withkey, sizeof(withkey), "%s:%s", name, nkey);
                pymcl_maven_path(withkey, "jar", rel, sizeof(rel));
            }
            pymcl_path_join(dest, sizeof(dest), libs, rel);
            const char *sha1 = cJSON_IsObject(entry)
                ? cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "sha1")) : NULL;
            cJSON *szv = cJSON_IsObject(entry) ? cJSON_GetObjectItemCaseSensitive(entry, "size") : NULL;
            double size = cJSON_IsNumber(szv) ? szv->valuedouble : -1;
            checked++;
            const char *bn = pymcl_basename(rel);
            if (!pf_is_file(dest)) {
                nmissing_all++;
                if (nmissing < 64) missing[nmissing++] = pymcl_strdup(bn);
            } else if ((sha1 && sha1[0]) || size >= 0) {
                if (!pf_file_matches(dest, sha1, size)) {
                    nbad_all++;
                    if (nbad < 64) bad_hash[nbad++] = pymcl_strdup(bn);
                }
            }
        }
        free(nkey);
    }
    if (nmissing_all > 0) {
        char detail[4096];
        size_t off = (size_t)snprintf(detail, sizeof(detail), "缺少以下库文件，请到版本页点「修复」：");
        int show = nmissing < 10 ? nmissing : 10;
        for (int i = 0; i < show; i++)
            off += (size_t)snprintf(detail + off, sizeof(detail) - off, "\n - %s", missing[i]);
        if (nmissing_all > 10)
            snprintf(detail + off, sizeof(detail) - off, "\n…共缺 %d 个", nmissing_all);
        cJSON_AddItemToArray(items, pf_item(nmissing_all >= 3 ? "error" : "warn",
                                            "libs_missing", "依赖库缺失", detail));
    }
    if (nbad_all > 0) {
        char detail[4096];
        size_t off = (size_t)snprintf(detail, sizeof(detail), "以下库 sha1/大小与清单不符，可能损坏：");
        int show = nbad < 8 ? nbad : 8;
        for (int i = 0; i < show; i++)
            off += (size_t)snprintf(detail + off, sizeof(detail) - off, "\n - %s", bad_hash[i]);
        snprintf(detail + off, sizeof(detail) - off, "\n建议修复该版本。");
        cJSON_AddItemToArray(items, pf_item("warn", "libs_hash", "依赖库校验不一致", detail));
    }
    for (int i = 0; i < nmissing; i++) free(missing[i]);
    for (int i = 0; i < nbad; i++) free(bad_hash[i]);
}

static int pf_cmp_keys(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

static void pf_check_assets(const char *inst, cJSON *resolved, cJSON *items) {
    cJSON *idx = cJSON_GetObjectItemCaseSensitive(resolved, "assetIndex");
    if (!cJSON_IsObject(idx)) return;
    char assets[PYMCL_PATH];
    instance_assets_dir(inst, assets, sizeof(assets));
    const char *index_id = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(idx, "id")) ?: "";
    char fname[300];
    snprintf(fname, sizeof(fname), "%s.json", index_id);
    char ifpath[PYMCL_PATH];
    pymcl_path_join3(ifpath, sizeof(ifpath), assets, "indexes", fname);
    if (!pf_is_file(ifpath)) {
        char detail[1024];
        snprintf(detail, sizeof(detail), "找不到 assets/indexes/%s.json，请修复该版本。", index_id);
        cJSON_AddItemToArray(items, pf_item("error", "assets_index_missing", "资源索引缺失", detail));
        return;
    }
    const char *isha = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(idx, "sha1"));
    cJSON *iszv = cJSON_GetObjectItemCaseSensitive(idx, "size");
    if (isha && isha[0] && !pf_file_matches(ifpath, isha, cJSON_IsNumber(iszv) ? iszv->valuedouble : -1)) {
        char detail[1024];
        snprintf(detail, sizeof(detail), "%s.json 与清单不符，建议修复该版本。", index_id);
        cJSON_AddItemToArray(items, pf_item("warn", "assets_index_hash", "资源索引校验失败", detail));
    }
    cJSON *index = pymcl_read_json(ifpath);
    cJSON *objects = index ? cJSON_GetObjectItemCaseSensitive(index, "objects") : NULL;
    if (!cJSON_IsObject(objects) || cJSON_GetArraySize(objects) == 0) {
        char detail[1024];
        snprintf(detail, sizeof(detail), "%s.json 没有 objects，游戏可能缺材质/音效。", index_id);
        cJSON_AddItemToArray(items, pf_item("warn", "assets_index_empty", "资源索引为空", detail));
        cJSON_Delete(index);
        return;
    }
    int total = cJSON_GetArraySize(objects);
    char **keys = (char **)calloc((size_t)total, sizeof(char *));
    int nk = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, objects) if (it->string && nk < total) keys[nk++] = it->string;
    qsort(keys, (size_t)nk, sizeof(char *), pf_cmp_keys);
    int sample = nk < PF_MAX_ASSET_SAMPLE ? nk : PF_MAX_ASSET_SAMPLE;
    int miss = 0;
    for (int i = 0; i < sample; i++) {
        cJSON *obj = cJSON_GetObjectItemCaseSensitive(objects, keys[i]);
        const char *h = cJSON_IsObject(obj)
            ? (cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(obj, "hash")) ?: "") : "";
        if (strlen(h) < 2) continue;
        char hh[3] = {h[0], h[1], 0};
        char dest[PYMCL_PATH];
        pymcl_path_join3(dest, sizeof(dest), assets, "objects", hh);
        pymcl_path_join(dest, sizeof(dest), dest, h);
        if (!pf_is_file(dest)) miss++;
    }
    if (miss > 0) {
        double ratio = (double)miss / (double)(sample > 0 ? sample : 1);
        int est = (int)rint(ratio * (double)total);
        char detail[1024];
        if (ratio >= 0.25 || miss >= 8) {
            snprintf(detail, sizeof(detail),
                     "抽样 %d 个资源缺 %d 个（约估全量缺 %d/%d）。请修复该版本。", sample, miss, est, total);
            cJSON_AddItemToArray(items, pf_item("error", "assets_missing", "游戏资源大量缺失", detail));
        } else {
            snprintf(detail, sizeof(detail),
                     "抽样 %d 个资源缺 %d 个（约估全量缺 %d/%d）。可先启动，异常再修复。", sample, miss, est, total);
            cJSON_AddItemToArray(items, pf_item("warn", "assets_partial", "部分游戏资源缺失", detail));
        }
    }
    free(keys);
    cJSON_Delete(index);
}

static void pf_check_natives(const char *inst, const char *version, cJSON *resolved, cJSON *items) {
    int needs = 0;
    cJSON *lib;
    cJSON_ArrayForEach(lib, cJSON_GetObjectItemCaseSensitive(resolved, "libraries")) {
        if (!pymcl_check_rules(cJSON_GetObjectItemCaseSensitive(lib, "rules"), 0)) continue;
        char *nkey = select_native_classifier(lib);
        if (nkey) { free(nkey); needs = 1; break; }
    }
    if (!needs) return;
    char ndir[PYMCL_PATH], vd[PYMCL_PATH], ip[PYMCL_PATH];
    if (manifest_is_legacy(resolved)) {
        instance_path(inst, ip, sizeof(ip));
        pymcl_path_join3(ndir, sizeof(ndir), ip, "bin", "natives");
    } else {
        instance_versions_dir(inst, vd, sizeof(vd));
        char dn[600];
        snprintf(dn, sizeof(dn), "%s-natives", version);
        pymcl_path_join3(ndir, sizeof(ndir), vd, version, dn);
    }
    if (!natives_present(ndir)) {
        char detail[PYMCL_PATH + 160];
        snprintf(detail, sizeof(detail),
                 "%s 为空或不完整。启动时会尝试再解压；若仍黑屏请修复该版本。", ndir);
        cJSON_AddItemToArray(items, pf_item("warn", "natives_missing", "本地库（natives）可能未解压", detail));
    }
}

static cJSON *pf_load_parent(const char *pid, void *ud) {
    return instance_version_json((const char *)ud, pid);
}

cJSON *preflight_check_launch(const char *inst, const char *version_in, int memory_mb, const char *java_exe) {
    cJSON *items = cJSON_CreateArray();
    char root[PYMCL_PATH];
    instance_path(inst && inst[0] ? inst : "default", root, sizeof(root));
    char ver[256] = "";
    snprintf(ver, sizeof(ver), "%s", version_in ? version_in : "");
    char *v = ver;
    while (*v && isspace((unsigned char)*v)) v++;
    memmove(ver, v, strlen(v) + 1);

    if (!pf_is_dir(root)) {
        cJSON_AddItemToArray(items, pf_itemf("error", "no_instance", "实例目录不存在", "%s", root));
        cJSON *out = cJSON_CreateObject();
        cJSON_AddBoolToObject(out, "ok", 0);
        cJSON_AddItemToObject(out, "items", items);
        return out;
    }
    {
        char probe[PYMCL_PATH];
        pymcl_path_join(probe, sizeof(probe), root, ".pymcl_write_probe");
        if (pymcl_write_file(probe, "ok", 2) != 0) {
            char detail[600];
            snprintf(detail, sizeof(detail), "无法写入 %s", probe);
            cJSON_AddItemToArray(items, pf_item("error", "not_writable", "实例目录不可写", detail));
        } else {
            remove(probe);
        }
    }

    cJSON *vjson = NULL;
    cJSON *resolved = NULL;
    if (!ver[0]) {
        cJSON_AddItemToArray(items, pf_item("error", "no_version", "未选择版本",
                                            "请先到「下载 → 原版游戏」安装版本"));
    } else {
        vjson = instance_version_json(inst, ver);
        if (!vjson) {
            char detail[600];
            snprintf(detail, sizeof(detail), "找不到 %s 的版本 JSON", ver);
            cJSON_AddItemToArray(items, pf_item("error", "no_version_json", "版本未安装", detail));
        } else {
            char vd[PYMCL_PATH], jn[600], jar[PYMCL_PATH];
            instance_versions_dir(inst, vd, sizeof(vd));
            snprintf(jn, sizeof(jn), "%s.jar", ver);
            pymcl_path_join3(jar, sizeof(jar), vd, ver, jn);
            if (!pf_is_file(jar)) {
                char detail[PYMCL_PATH + 120];
                snprintf(detail, sizeof(detail), "%s（若为继承版本，启动时会解析父版本）", jar);
                cJSON_AddItemToArray(items, pf_item("warn", "no_client_jar", "客户端 jar 未直接找到", detail));
            }
            resolved = manifest_resolve_inherits(vjson, pf_load_parent, (void *)inst);
            if (!resolved) resolved = cJSON_Duplicate(vjson, 1);
        }
    }

    {
        wchar_t *w = pymcl_u8_to_wide(root);
        ULARGE_INTEGER free_total;
        if (w && GetDiskFreeSpaceExW(w, NULL, NULL, &free_total)) {
            long long free_mb = (long long)(free_total.QuadPart / (1024 * 1024));
            if (free_mb < 512) {
                char detail[300];
                snprintf(detail, sizeof(detail), "实例所在盘仅剩约 %lld MB，至少需要 512 MB", free_mb);
                cJSON_AddItemToArray(items, pf_item("error", "disk_low", "磁盘空间不足", detail));
            } else if (free_mb < 2048) {
                char detail[300];
                snprintf(detail, sizeof(detail), "实例所在盘剩余约 %lld MB，建议清理后再装大整合包", free_mb);
                cJSON_AddItemToArray(items, pf_item("warn", "disk_warn", "磁盘空间偏低", detail));
            }
        }
        free(w);
    }

    char mods_path[PYMCL_PATH];
    if (ver[0]) {
        cJSON *vs = version_settings_load(inst, ver);
        version_game_dir(inst, ver, vs, mods_path, sizeof(mods_path));
        cJSON_Delete(vs);
        char tail[16];
        snprintf(tail, sizeof(tail), "%s", "mods");
        pymcl_path_join(mods_path, sizeof(mods_path), mods_path, tail);
    } else {
        pymcl_path_join(mods_path, sizeof(mods_path), root, "mods");
    }
    if (pf_is_dir(mods_path)) {
        int n = 0;
        char **names = pf_sorted_names(mods_path, &n);
        char unzipped[12][512];
        int nun = 0;
        int jars = 0;
        for (int i = 0; i < n; i++) {
            char full[PYMCL_PATH];
            pymcl_path_join(full, sizeof(full), mods_path, names[i]);
            if (pf_is_dir(full) && names[i][0] != '.') {
                if (nun < 12) snprintf(unzipped[nun++], sizeof(unzipped[0]), "%s", names[i]);
                continue;
            }
            const char *bn = pymcl_basename(names[i]);
            if (pymcl_endswith(bn, ".jar")) jars++;
        }
        pf_free_names(names, n);
        if (nun > 0) {
            char detail[4096];
            size_t off = (size_t)snprintf(detail, sizeof(detail),
                                          "直接放整个 .jar/.zip 即可。请删掉这些文件夹：");
            for (int i = 0; i < nun; i++)
                off += (size_t)snprintf(detail + off, sizeof(detail) - off, "\n - %s", unzipped[i]);
            cJSON_AddItemToArray(items, pf_item("warn", "mod_unzipped", "Mods 被解压成了文件夹", detail));
        }
        if (jars > 0 && ver[0]) {
            char low[600];
            snprintf(low, sizeof(low), "%s", ver);
            for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
            int looks_loader = strstr(low, "forge") || strstr(low, "fabric") || strstr(low, "quilt")
                               || strstr(low, "neoforge") || strstr(low, "optifine") || strstr(low, "liteloader");
            if (!looks_loader) {
                char detail[300];
                snprintf(detail, sizeof(detail),
                         "mods 里有 %d 个 jar，但当前版本名像原版。请安装 Fabric/Forge 等加载器。", jars);
                cJSON_AddItemToArray(items, pf_item("warn", "vanilla_mods", "原版版本不会加载模组", detail));
            }
        }
    }

    if (resolved && ver[0]) {
        pf_check_libraries(inst, resolved, items);
        pf_check_assets(inst, resolved, items);
        pf_check_natives(inst, ver, resolved, items);
    }
    if (pf_is_dir(mods_path) && ver[0]) pf_check_mod_conflicts(mods_path, items);

    if (java_exe && java_exe[0] && strcmp(java_exe, "自动选择") && strcmp(java_exe, "auto")
        && strcmp(java_exe, "default")) {
        if (!pf_is_file(java_exe)) {
            cJSON_AddItemToArray(items, pf_item("error", "java_missing", "指定的 Java 不存在", java_exe));
        } else if (ver[0]) {
            cJSON *src = resolved ? resolved : vjson;
            int need = src ? java_required_major(src) : 0;
            int got = java_get_major(java_exe);
            if (need && got && got < need) {
                char title[64], detail[PYMCL_PATH + 120];
                snprintf(title, sizeof(title), "Java 版本过低（需要 %d+）", need);
                snprintf(detail, sizeof(detail), "当前是 Java %d：%s", got, java_exe);
                cJSON_AddItemToArray(items, pf_item("error", "java_too_old", title, detail));
            }
        }
    }

    if (memory_mb > 0) {
        MEMORYSTATUSEX st;
        memset(&st, 0, sizeof(st));
        st.dwLength = sizeof(st);
        if (GlobalMemoryStatusEx(&st)) {
            long long avail_mb = (long long)(st.ullAvailPhys / (1024 * 1024));
            if ((long long)memory_mb + 1024 > avail_mb) {
                char detail[300];
                snprintf(detail, sizeof(detail),
                         "游戏 %d MB，系统当前可用约 %lld MB，可能触发交换卡顿", memory_mb, avail_mb);
                cJSON_AddItemToArray(items, pf_item("warn", "memory_high", "分配内存接近可用物理内存", detail));
            }
        }
    }

    int ok = 1;
    cJSON *it;
    cJSON_ArrayForEach(it, items)
        if (!strcmp(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(it, "level")) ?: "", "error")) ok = 0;
    if (cJSON_GetArraySize(items) == 0)
        cJSON_AddItemToArray(items, pf_item("ok", "ready", "预检通过", "未发现阻塞问题"));
    cJSON_Delete(resolved);
    cJSON_Delete(vjson);
    cJSON *out = cJSON_CreateObject();
    cJSON_AddBoolToObject(out, "ok", ok);
    cJSON_AddItemToObject(out, "items", items);
    return out;
}

/* ---- 供 ai_agent.c（AI 工具执行）透出的内部助手 ---- */
int pf_sorted_names_public(const char *dir, char ***out) {
    int n = 0;
    *out = pf_sorted_names(dir, &n);
    return n;
}
void pf_free_names_public(char **arr, int n) { pf_free_names(arr, n); }
void pf_inspect_jar_public(const char *path, cJSON *info) { pf_inspect_jar(path, info); }
