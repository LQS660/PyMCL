#include "pymcl.h"
#include <ctype.h>

static const char *k_dirs[] = {
    "mods", "config", "saves", "resourcepacks", "shaderpacks", "datapacks",
    "screenshots", "crash-reports", "logs", "options", "servers",
    "texturepacks", "versions", "libraries", NULL
};

static int reserved_name(const char *s) {
    static const char *r[] = {
        "CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
        "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9", NULL
    };
    for (int i = 0; r[i]; i++) if (pymcl_ieq(s, r[i])) return 1;
    return 0;
}

/* 下面这组函数逐条对齐 mclauncher/instances.py：只有一个游戏目录（.minecraft），
   它本身带 .instance.json 时是单目录模式，旧结构 .minecraft/<实例名>/ 只留读取能力。 */

#define MAX_INSTANCE_NAME 48

static void trim_copy(const char *s, char *out, size_t n) {
    const char *a = s ? s : "";
    while (*a && isspace((unsigned char)*a)) a++;
    snprintf(out, n, "%s", a);
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
}

static size_t u8_len(const char *s) {
    size_t n = 0;
    for (; *s; s++) if (((unsigned char)*s & 0xC0) != 0x80) n++;
    return n;
}

/* 截到前 max 个字符（按码点，不按字节） */
static void u8_truncate(char *s, size_t max) {
    size_t n = 0;
    for (char *p = s; *p; p++) {
        if (((unsigned char)*p & 0xC0) != 0x80) {
            if (n == max) { *p = 0; return; }
            n++;
        }
    }
}

static void rstrip_space_dot(char *s) {
    size_t len = strlen(s);
    while (len && (s[len - 1] == ' ' || s[len - 1] == '.')) s[--len] = 0;
}

void sanitize_instance_name(const char *raw, char *out, size_t n) {
    char t[512], u[512];
    trim_copy(raw, t, sizeof(t));
    size_t o = 0;
    for (const char *s = t; *s && o + 1 < sizeof(u); s++) {
        unsigned char c = (unsigned char)*s;
        u[o++] = (c < 32 || strchr("\\/:*?\"<>|", c)) ? '-' : (char)c;
    }
    u[o] = 0;
    /* re.sub(r"\s+", " ") 再 strip(" .") */
    o = 0;
    for (const char *s = u; *s; s++) {
        if (isspace((unsigned char)*s)) {
            if (o == 0 || t[o - 1] != ' ') t[o++] = ' ';
        } else t[o++] = *s;
    }
    t[o] = 0;
    char *b = t;
    while (*b == ' ' || *b == '.') b++;
    rstrip_space_dot(b);
    if (!*b) b = "游戏";
    snprintf(out, n, "%s", b);
    if (reserved_name(out)) {
        char tmp[128];
        snprintf(tmp, sizeof(tmp), "%s-游戏", out);
        snprintf(out, n, "%s", tmp);
    }
    if (u8_len(out) > MAX_INSTANCE_NAME) {
        u8_truncate(out, MAX_INSTANCE_NAME);
        rstrip_space_dot(out);
    }
    if (!out[0]) snprintf(out, n, "游戏");
}

void instance_root_name(char *out, size_t n) {
    char root[PYMCL_PATH];
    pymcl_instances_dir(root, sizeof(root));
    size_t len = strlen(root);
    while (len && (root[len - 1] == '\\' || root[len - 1] == '/')) root[--len] = 0;
    const char *b = pymcl_basename(root);
    snprintf(out, n, "%s", b[0] ? b : ".minecraft");
}

int instance_single_root_mode(void) {
    char root[PYMCL_PATH], meta[PYMCL_PATH];
    pymcl_instances_dir(root, sizeof(root));
    pymcl_path_join(meta, sizeof(meta), root, ".instance.json");
    return pymcl_file_exists(meta);
}

/* resolve_name(name) or root_name()：外部随手传的 "default" 在单目录模式下落到游戏目录本身 */
void instance_resolved_name(const char *name, char *out, size_t n) {
    char s[512], rn[256];
    trim_copy(name, s, sizeof(s));
    instance_root_name(rn, sizeof(rn));
    if (!s[0] || strcmp(s, rn) == 0) { snprintf(out, n, "%s", rn); return; }
    if (instance_single_root_mode()) {
        char root[PYMCL_PATH], meta[PYMCL_PATH];
        pymcl_instances_dir(root, sizeof(root));
        pymcl_path_join3(meta, sizeof(meta), root, s, ".instance.json");
        if (strpbrk(s, "\\/:*?\"<>|") || !pymcl_file_exists(meta)) { snprintf(out, n, "%s", rn); return; }
    }
    snprintf(out, n, "%s", s);
}

int instance_path(const char *name, char *out, size_t n) {
    char root[PYMCL_PATH], rn[256], s[512];
    pymcl_instances_dir(root, sizeof(root));
    instance_root_name(rn, sizeof(rn));
    instance_resolved_name(name, s, sizeof(s));
    if (strcmp(s, rn) == 0) {
        snprintf(out, n, "%s", root);
        return 0;
    }
    if (strcmp(s, ".") == 0 || strcmp(s, "..") == 0 || strpbrk(s, "\\/:*?\"<>|")) {
        pymcl_set_error("非法实例名: '%s'", s);
        return -1;
    }
    pymcl_path_join(out, n, root, s);
    return 0;
}

int instance_is_root(const char *name) {
    char rn[256], s[512];
    instance_root_name(rn, sizeof(rn));
    instance_resolved_name(name, s, sizeof(s));
    return strcmp(s, rn) == 0;
}

static int list_contains(cJSON *arr, const char *s) {
    cJSON *it;
    cJSON_ArrayForEach(it, arr) if (cJSON_IsString(it) && strcmp(it->valuestring, s) == 0) return 1;
    return 0;
}

void unique_instance_name(const char *raw, char *out, size_t n) {
    char base[256];
    sanitize_instance_name(raw, base, sizeof(base));
    cJSON *existing = NULL;
    instance_list(&existing);
    char root[PYMCL_PATH];
    pymcl_instances_dir(root, sizeof(root));
    snprintf(out, n, "%s", base);
    for (int i = 2;; i++) {
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), root, out);
        if (!list_contains(existing, out) && !pymcl_dir_exists(p) && !pymcl_file_exists(p)) break;
        char suffix[16], trimmed[256];
        snprintf(suffix, sizeof(suffix), "-%d", i);
        snprintf(trimmed, sizeof(trimmed), "%s", base);
        size_t limit = MAX_INSTANCE_NAME - strlen(suffix);
        if (u8_len(trimmed) > limit) {
            u8_truncate(trimmed, limit);
            rstrip_space_dot(trimmed);
            if (!trimmed[0]) snprintf(trimmed, sizeof(trimmed), "游戏");
        }
        snprintf(out, n, "%s%s", trimmed, suffix);
    }
    cJSON_Delete(existing);
}

static int cmp_u8(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* WindowsPath 排序不分大小写（比的是 lower() 之后的串） */
static int cmp_u8_nocase(const void *a, const void *b) {
    wchar_t *wa = pymcl_u8_to_wide(*(const char *const *)a), *wb = pymcl_u8_to_wide(*(const char *const *)b);
    int r = 0;
    if (wa && wb) {
        CharLowerW(wa);
        CharLowerW(wb);
        r = wcscmp(wa, wb);
    }
    free(wa);
    free(wb);
    return r;
}

/* 目录下的子目录名（可选：必须含某个文件），按 Python 的 sorted() 口径排好 */
static cJSON *list_subdirs(const char *dir, const char *must_have_fmt, int nocase) {
    cJSON *out = cJSON_CreateArray();
    if (!pymcl_dir_exists(dir)) return out;
    wchar_t *w = pymcl_u8_to_wide(dir);
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
    free(w);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return out;
    char **names = NULL;
    size_t cnt = 0, cap = 0;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        char *name = pymcl_wide_to_u8(fd.cFileName);
        if (!name) continue;
        if (must_have_fmt) {
            char inner[512], f[PYMCL_PATH];
            snprintf(inner, sizeof(inner), must_have_fmt, name);
            pymcl_path_join3(f, sizeof(f), dir, name, inner);
            if (!pymcl_file_exists(f)) { free(name); continue; }
        }
        if (cnt == cap) {
            cap = cap ? cap * 2 : 16;
            char **nn = (char **)realloc(names, cap * sizeof(char *));
            if (!nn) { free(name); break; }
            names = nn;
        }
        names[cnt++] = name;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    if (cnt) qsort(names, cnt, sizeof(char *), nocase ? cmp_u8_nocase : cmp_u8);
    for (size_t i = 0; i < cnt; i++) {
        cJSON_AddItemToArray(out, cJSON_CreateString(names[i]));
        free(names[i]);
    }
    free(names);
    return out;
}

/* list_instances()：单目录模式（或没有旧子实例）时是 [游戏目录名] + 旧子实例 */
int instance_list(cJSON **out) {
    char root[PYMCL_PATH], rn[256];
    pymcl_instances_dir(root, sizeof(root));
    instance_root_name(rn, sizeof(rn));
    cJSON *legacy = list_subdirs(root, ".instance.json", 0);
    if (instance_single_root_mode() || cJSON_GetArraySize(legacy) == 0) {
        cJSON *arr = cJSON_CreateArray();
        cJSON_AddItemToArray(arr, cJSON_CreateString(rn));
        cJSON *it;
        cJSON_ArrayForEach(it, legacy) cJSON_AddItemToArray(arr, cJSON_CreateString(it->valuestring));
        cJSON_Delete(legacy);
        *out = arr;
    } else {
        *out = legacy;
    }
    return 0;
}

void instance_ensure_dirs(const char *name) {
    char ip[PYMCL_PATH];
    if (instance_path(name, ip, sizeof(ip)) != 0) return;
    pymcl_ensure_dir(ip);
    for (int i = 0; k_dirs[i]; i++) {
        char d[PYMCL_PATH];
        pymcl_path_join(d, sizeof(d), ip, k_dirs[i]);
        pymcl_ensure_dir(d);
    }
}

static cJSON *default_meta(const char *name, cJSON *meta) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "name", name);
    cJSON_AddNullToObject(o, "mc_version");
    cJSON_AddNullToObject(o, "modpack");
    cJSON_AddStringToObject(o, "java", PYMCL_JAVA_AUTO);
    if (cJSON_IsObject(meta)) {
        cJSON *c = NULL;
        cJSON_ArrayForEach(c, meta) {
            cJSON_DeleteItemFromObject(o, c->string);
            cJSON_AddItemToObject(o, c->string, cJSON_Duplicate(c, 1));
        }
    }
    return o;
}

int instance_create(const char *name, cJSON *meta) {
    char ip[PYMCL_PATH], rname[512], mf[PYMCL_PATH];
    if (instance_path(name, ip, sizeof(ip)) != 0) return -1;
    instance_resolved_name(name, rname, sizeof(rname));
    pymcl_path_join(mf, sizeof(mf), ip, ".instance.json");
    if (instance_is_root(name)) {
        /* 游戏目录本身不存在「已存在」这回事，补齐结构即可 */
        instance_ensure_dirs(name);
        if (pymcl_file_exists(mf)) return 0;
    } else {
        if (pymcl_dir_exists(ip)) {
            pymcl_set_error("实例 %s 已存在。", rname);
            return -1;
        }
        instance_ensure_dirs(name);
    }
    cJSON *o = default_meta(rname, meta);
    int r = pymcl_write_json(mf, o);
    cJSON_Delete(o);
    return r;
}

/* bridge/api.py 的 _instance()：不存在就建，存在就补齐标准子目录 */
int instance_open(const char *name, char *path, size_t n) {
    const char *nm = (name && name[0]) ? name : config_str("default_instance", "default");
    if (instance_path(nm, path, n) != 0) return -1;
    if (!pymcl_dir_exists(path)) return instance_create(nm, NULL);
    instance_ensure_dirs(nm);
    return 0;
}

int instance_delete(const char *name) {
    char ip[PYMCL_PATH], rname[512];
    if (instance_path(name, ip, sizeof(ip)) != 0) return -1;
    instance_resolved_name(name, rname, sizeof(rname));
    if (instance_is_root(name)) {
        pymcl_set_error("游戏目录不能删除，请到「版本管理」里逐个卸载版本。");
        return -1;
    }
    if (!pymcl_dir_exists(ip)) { pymcl_set_error("实例 %s 不存在。", rname); return -1; }
    pymcl_remove_tree(ip);
    if (strcmp(config_str("default_instance", ""), rname) == 0) {
        config_set_str("default_instance", "");
        config_save();
    }
    return 0;
}

int instance_rename(const char *name, const char *new_name) {
    char a[PYMCL_PATH], b[PYMCL_PATH], rname[512], root[PYMCL_PATH];
    if (instance_path(name, a, sizeof(a)) != 0) return -1;
    instance_resolved_name(name, rname, sizeof(rname));
    if (instance_is_root(name)) {
        pymcl_set_error("游戏目录不能重命名，请到设置里改「游戏目录」。");
        return -1;
    }
    /* get_instance_path(new_name)：不走 resolve_name，名字原样校验 */
    const char *nn = new_name ? new_name : "";
    pymcl_instances_dir(root, sizeof(root));
    char rn[256];
    instance_root_name(rn, sizeof(rn));
    if (!nn[0] || strcmp(nn, rn) == 0) {
        snprintf(b, sizeof(b), "%s", root);
    } else {
        if (strcmp(nn, ".") == 0 || strcmp(nn, "..") == 0 || strpbrk(nn, "\\/:*?\"<>|")) {
            pymcl_set_error("非法实例名: '%s'", nn);
            return -1;
        }
        pymcl_path_join(b, sizeof(b), root, nn);
    }
    if (pymcl_dir_exists(b) || pymcl_file_exists(b)) { pymcl_set_error("实例 %s 已存在。", nn); return -1; }
    wchar_t *wa = pymcl_u8_to_wide(a), *wb = pymcl_u8_to_wide(b);
    BOOL ok = MoveFileW(wa, wb);
    free(wa); free(wb);
    if (!ok) { pymcl_set_error("重命名失败"); return -1; }
    if (strcmp(config_str("default_instance", ""), rname) == 0) {
        config_set_str("default_instance", nn);
        config_save();
    }
    char mf[PYMCL_PATH];
    pymcl_path_join(mf, sizeof(mf), b, ".instance.json");
    cJSON *o = pymcl_read_json(mf);
    if (!cJSON_IsObject(o)) { cJSON_Delete(o); o = cJSON_CreateObject(); }
    cJSON_DeleteItemFromObject(o, "name");
    cJSON_AddStringToObject(o, "name", nn);
    pymcl_write_json(mf, o);
    cJSON_Delete(o);
    return 0;
}

cJSON *instance_meta(const char *name) {
    char ip[PYMCL_PATH], mf[PYMCL_PATH];
    if (instance_path(name, ip, sizeof(ip)) != 0) return cJSON_CreateObject();
    pymcl_path_join(mf, sizeof(mf), ip, ".instance.json");
    cJSON *j = pymcl_read_json(mf);
    return j ? j : cJSON_CreateObject();
}

int instance_set_meta(const char *name, const char *key, cJSON *val) {
    char ip[PYMCL_PATH], mf[PYMCL_PATH];
    if (instance_path(name, ip, sizeof(ip)) != 0) return -1;
    pymcl_path_join(mf, sizeof(mf), ip, ".instance.json");
    cJSON *o = pymcl_read_json(mf);
    if (!o) o = cJSON_CreateObject();
    cJSON_DeleteItemFromObject(o, key);
    cJSON_AddItemToObject(o, key, cJSON_Duplicate(val, 1));
    int r = pymcl_write_json(mf, o);
    cJSON_Delete(o);
    return r;
}

void instance_java_pref(const char *name, char *out, size_t n) {
    cJSON *m = instance_meta(name);
    cJSON *j = cJSON_GetObjectItem(m, "java");
    const char *v = cJSON_IsString(j) ? j->valuestring : PYMCL_JAVA_AUTO;
    if (!v[0] || pymcl_ieq(v, "auto") || pymcl_ieq(v, "default") || pymcl_ieq(v, PYMCL_JAVA_AUTO))
        snprintf(out, n, "%s", PYMCL_JAVA_AUTO);
    else
        snprintf(out, n, "%s", v);
    cJSON_Delete(m);
}
void instance_set_java_pref(const char *name, const char *java) {
    const char *v = (!java || !java[0] || pymcl_ieq(java, "auto") || pymcl_ieq(java, "default"))
        ? PYMCL_JAVA_AUTO : java;
    cJSON *s = cJSON_CreateString(v);
    instance_set_meta(name, "java", s);
    cJSON_Delete(s);
}

void instance_versions_dir(const char *name, char *out, size_t n) {
    char ip[PYMCL_PATH];
    instance_path(name, ip, sizeof(ip));
    pymcl_path_join(out, n, ip, "versions");
}
void instance_libraries_dir(const char *name, char *out, size_t n) {
    char ip[PYMCL_PATH];
    instance_path(name, ip, sizeof(ip));
    config_libraries_dir(ip, out, n);
}
void instance_assets_dir(const char *name, char *out, size_t n) {
    char ip[PYMCL_PATH];
    instance_path(name, ip, sizeof(ip));
    config_assets_dir(ip, out, n);
}
void instance_natives_dir(const char *name, const char *vid, cJSON *vjson, char *out, size_t n) {
    if (vjson && manifest_is_legacy(vjson)) {
        char ip[PYMCL_PATH];
        instance_path(name, ip, sizeof(ip));
        pymcl_path_join3(out, n, ip, "bin", "natives");
        return;
    }
    char vd[PYMCL_PATH], nn[256];
    instance_versions_dir(name, vd, sizeof(vd));
    snprintf(nn, sizeof(nn), "%s-natives", vid);
    pymcl_path_join3(out, n, vd, vid, nn);
}

/* Instance.installed_ids()：versions/<id>/<id>.json 存在的才算，按 sorted(iterdir()) 排 */
int instance_installed_ids(const char *name, cJSON **out) {
    char vd[PYMCL_PATH];
    instance_versions_dir(name, vd, sizeof(vd));
    *out = list_subdirs(vd, "%s.json", 1);
    return 0;
}

cJSON *instance_version_json(const char *name, const char *vid) {
    char vd[PYMCL_PATH], jf[PYMCL_PATH], jn[256];
    instance_versions_dir(name, vd, sizeof(vd));
    snprintf(jn, sizeof(jn), "%s.json", vid);
    pymcl_path_join3(jf, sizeof(jf), vd, vid, jn);
    return pymcl_read_json(jf);
}

int instance_has_version(const char *name, const char *vid) {
    char vd[PYMCL_PATH], jf[PYMCL_PATH], jn[256];
    instance_versions_dir(name, vd, sizeof(vd));
    snprintf(jn, sizeof(jn), "%s.json", vid);
    pymcl_path_join3(jf, sizeof(jf), vd, vid, jn);
    return pymcl_file_exists(jf);
}
