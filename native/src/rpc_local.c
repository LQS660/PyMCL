#include "pymcl.h"
#include <ctype.h>
#include <winsock2.h>
#include <ws2tcpip.h>

/* 本地功能类 RPC（GOAL 附录 A 的 M1）：逐个照 bridge/api.py 与它调用的 mclauncher 模块移植。
   每个分支上方注明 Python 出处，改 Python 时顺着找得到。 */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

static cJSON *param(cJSON *o, const char *k) { return cJSON_GetObjectItemCaseSensitive(o, k); }

static void emit_ui_changed(sse_emit_fn emit) {
    if (emit) emit("ui_changed", cJSON_CreateObject());
}

/* ---------- version_settings 的几个小函数 ---------- */

static const char *vs_iso(cJSON *settings) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(settings, "isolation"));
    return (s && s[0]) ? s : "none";
}

static int vs_is_isolated(cJSON *settings) {
    const char *iso = vs_iso(settings);
    return strcmp(iso, "mods") == 0 || strcmp(iso, "all") == 0;
}

/* game_dir：隔离档（all / saves / mods）用 versions/<id>，否则就是游戏目录本身 */
static void vs_game_dir(const char *inst, const char *vid, cJSON *settings, char *out, size_t n) {
    const char *iso = vs_iso(settings);
    if (strcmp(iso, "all") == 0 || strcmp(iso, "saves") == 0 || strcmp(iso, "mods") == 0) {
        char vd[PYMCL_PATH];
        instance_versions_dir(inst, vd, sizeof(vd));
        pymcl_path_join(out, n, vd, vid);
    } else {
        instance_path(inst, out, n);
    }
}

static const char *isolation_label(const char *iso) {
    if (strcmp(iso, "none") == 0) return "大锅饭（与其他版本共用）";
    if (strcmp(iso, "saves") == 0) return "隔离存档";
    if (strcmp(iso, "mods") == 0) return "隔离 Mod 与配置";
    if (strcmp(iso, "all") == 0) return "完全独立";
    return "";
}

/* ---------- 模组列表 mods.list_mod_entries_at ---------- */

static cJSON *mod_entries_at(const char *dir) {
    cJSON *rows = cJSON_CreateArray();
    if (!pymcl_dir_exists(dir)) return rows;
    cJSON *names = pymcl_list_dir(dir, 0, 1);
    cJSON *it;
    cJSON_ArrayForEach(it, names) {
        const char *fn = it->valuestring;
        int enabled;
        if (pymcl_endswith(fn, ".jar")) enabled = 1;
        else if (pymcl_endswith(fn, ".jar.disabled") || pymcl_endswith(fn, ".disabled")) enabled = 0;
        else continue;
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), dir, fn);
        cJSON *row = cJSON_CreateObject();
        cJSON_AddStringToObject(row, "filename", fn);
        cJSON_AddBoolToObject(row, "enabled", enabled);
        cJSON_AddNumberToObject(row, "bytes", (double)pymcl_file_size(p));
        cJSON_AddStringToObject(row, "path", p);
        cJSON_AddItemToArray(rows, row);
    }
    cJSON_Delete(names);
    return rows;
}

static int count_jars(const char *dir) {
    if (!pymcl_dir_exists(dir)) return 0;
    cJSON *names = pymcl_list_dir(dir, 0, 0);
    int n = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, names) if (pymcl_endswith(it->valuestring, ".jar")) n++;
    cJSON_Delete(names);
    return n;
}

/* ---------- 加载器标签 BackendAPI.loader_of ---------- */

static cJSON *loader_of(const char *vid) {
    static const char *tags[][3] = {
        {"neoforge", "NeoForge", "#D84B28"}, {"fabric", "Fabric", "#7C5CD6"},
        {"quilt", "Quilt", "#C25BD6"}, {"forge", "Forge", "#E8862E"},
        {"optifine", "OptiFine", "#2E9B6B"}, {"liteloader", "LiteLoader", "#4C8BF5"},
    };
    char low[512];
    snprintf(low, sizeof(low), "%s", vid ? vid : "");
    for (char *p = low; *p; p++) *p = (char)tolower((unsigned char)*p);
    cJSON *out = cJSON_CreateArray();
    for (size_t i = 0; i < sizeof(tags) / sizeof(tags[0]); i++) {
        if (strstr(low, tags[i][0])) {
            cJSON_AddItemToArray(out, cJSON_CreateString(tags[i][1]));
            cJSON_AddItemToArray(out, cJSON_CreateString(tags[i][2]));
            return out;
        }
    }
    cJSON_AddItemToArray(out, cJSON_CreateString(tr("原版")));
    cJSON_AddItemToArray(out, cJSON_CreateString("#8A9099"));
    return out;
}

/* ---------- 游戏时长 mclauncher/playtime.py ---------- */

static void playtime_path(char *out, size_t n) { pymcl_path_join(out, n, g_root, "playtime.json"); }

static cJSON *playtime_load(void) {
    char p[PYMCL_PATH];
    playtime_path(p, sizeof(p));
    cJSON *d = pymcl_read_json(p);
    if (!py_truthy(d)) {
        cJSON_Delete(d);
        d = cJSON_Parse("{\"instances\":{}}");
    }
    return d;
}

static void format_duration(long long seconds, char *out, size_t n) {
    if (seconds < 0) seconds = 0;
    long long h = seconds / 3600, m = (seconds % 3600) / 60, s = seconds % 60;
    if (h > 0) snprintf(out, n, "%lld 小时 %lld 分钟", h, m);
    else if (m > 0) snprintf(out, n, "%lld 分钟 %lld 秒", m, s);
    else snprintf(out, n, "%lld 秒", s);
}

/* ---------- 局域网 mclauncher/lan.py ---------- */

static int in_list(cJSON *arr, const char *s) {
    cJSON *it;
    cJSON_ArrayForEach(it, arr) if (strcmp(it->valuestring, s) == 0) return 1;
    return 0;
}

static cJSON *local_ips(void) {
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    cJSON *found = cJSON_CreateArray();
    char host[256];
    if (gethostname(host, sizeof(host)) == 0) {
        struct addrinfo hints, *res = NULL;
        memset(&hints, 0, sizeof(hints));
        hints.ai_family = AF_INET;
        if (getaddrinfo(host, NULL, &hints, &res) == 0) {
            for (struct addrinfo *a = res; a; a = a->ai_next) {
                char ip[64];
                struct sockaddr_in *sin = (struct sockaddr_in *)a->ai_addr;
                if (!inet_ntop(AF_INET, &sin->sin_addr, ip, sizeof(ip))) continue;
                if (ip[0] && strncmp(ip, "127.", 4) != 0 && !in_list(found, ip))
                    cJSON_AddItemToArray(found, cJSON_CreateString(ip));
            }
            freeaddrinfo(res);
        }
    }
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s != INVALID_SOCKET) {
        struct sockaddr_in to;
        memset(&to, 0, sizeof(to));
        to.sin_family = AF_INET;
        to.sin_port = htons(80);
        inet_pton(AF_INET, "223.5.5.5", &to.sin_addr);
        if (connect(s, (struct sockaddr *)&to, sizeof(to)) == 0) {
            struct sockaddr_in me;
            int len = sizeof(me);
            char ip[64];
            if (getsockname(s, (struct sockaddr *)&me, &len) == 0 &&
                inet_ntop(AF_INET, &me.sin_addr, ip, sizeof(ip)) &&
                ip[0] && !in_list(found, ip) && strncmp(ip, "127.", 4) != 0)
                cJSON_InsertItemInArray(found, 0, cJSON_CreateString(ip));
        }
        closesocket(s);
    }
    if (cJSON_GetArraySize(found) == 0) cJSON_AddItemToArray(found, cJSON_CreateString("127.0.0.1"));
    return found;
}

/* ---------- 帮助 mclauncher/help_content.py ---------- */

static const char *k_articles[][3] = {
    {"launch-fail", "启动失败 / 闪退怎么办",
     "1. 看崩溃弹窗里的「建议操作」，能禁用嫌疑 Mod、提高内存、下载合适 Java、修复版本文件。\n"
     "2. 启动页点启动前会做预检：磁盘不足、Mods 被解压成文件夹、Java 过旧会直接拦住。\n"
     "3. 仍不行：到「反馈」页把错误报告发给开发者（同意上传后才会发送）。"},
    {"java", "Java 怎么选",
     "启动时默认自动匹配。也可在「下载 → Java」按版本下载：\n"
     "· Java 8：1.16 及更早\n"
     "· Java 17：1.18 – 1.20.4\n"
     "· Java 21：1.20.5+\n"
     "发行版推荐 Adoptium；也可用 Zulu / Microsoft。"},
    {"mods", "模组 / 整合包安装",
     "到「下载」页搜索 Modrinth / CurseForge（国内走镜像）。\n"
     "原版版本不会加载 mods 文件夹里的 jar，需要先装 Fabric / Forge / Quilt / NeoForge。\n"
     "不要把 .jar 解压成文件夹，否则会预检失败。"},
    {"account", "账号与正版登录",
     "支持离线、微软设备码、皮肤站（Yggdrasil）、统一通行证（Nide8）。\n"
     "微软登录请按弹窗打开链接并输入代码；关掉窗口会取消后台轮询。"},
    {"multiplayer", "陶瓦联机",
     "「联机」页可开房 / 加入。房间号形如 U/XXXX-XXXX-XXXX-XXXX。\n"
     "双方都要用兼容的陶瓦内核；防火墙提示按页面指引放行。"},
    {"isolation", "版本隔离与存档",
     "每个实例是独立的 .minecraft。版本设置里可选隔离档位。\n"
     "存档可在版本相关对话框里备份 / 还原；删世界前建议先备份。"},
};

static cJSON *article_json(size_t i) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "id", k_articles[i][0]);
    cJSON_AddStringToObject(o, "title", tr(k_articles[i][1]));
    cJSON_AddStringToObject(o, "body", k_articles[i][2]);
    return o;
}

static void ascii_lower(char *s) {
    for (; *s; s++) *s = (char)tolower((unsigned char)*s);
}

static void strip_copy(const char *s, char *out, size_t n) {
    while (s && *s && isspace((unsigned char)*s)) s++;
    snprintf(out, n, "%s", s ? s : "");
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
}

/* ---------- 壁纸历史 config.background_history ---------- */

static cJSON *history_paths(cJSON *raw) {
    cJSON *out = cJSON_CreateArray();
    cJSON *it;
    if (cJSON_IsArray(raw))
        cJSON_ArrayForEach(it, raw) if (cJSON_IsString(it)) cJSON_AddItemToArray(out, cJSON_CreateString(it->valuestring));
    return out;
}

static void bg_history(cJSON **images, cJSON **folders) {
    *images = history_paths(config_get("ui_background_history"));
    *folders = history_paths(config_get("ui_background_folder_history"));
    int ni = cJSON_GetArraySize(*images), nf = cJSON_GetArraySize(*folders);
    if (nf != ni) {
        cJSON *f = cJSON_CreateArray();
        for (int i = 0; i < ni; i++) {
            cJSON *src = i < nf ? cJSON_GetArrayItem(*folders, i) : NULL;
            cJSON_AddItemToArray(f, cJSON_CreateString(src ? src->valuestring : ""));
        }
        cJSON_Delete(*folders);
        *folders = f;
    }
}

static void keep_last(cJSON *arr, int max) {
    while (cJSON_GetArraySize(arr) > max) cJSON_DeleteItemFromArray(arr, 0);
}

static cJSON *current_background(void) {
    char img[PYMCL_PATH] = "", fold[PYMCL_PATH] = "";
    cJSON *a = config_get("ui_background"), *b = config_get("ui_background_folder");
    if (py_truthy(a)) py_str(a, img, sizeof(img));
    if (py_truthy(b)) py_str(b, fold, sizeof(fold));
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "image", img);
    cJSON_AddStringToObject(o, "folder", fold);
    return o;
}

/* ---------- 导出目录 content_export.default_export_dir ---------- */

static void default_export_dir(char *out, size_t n) {
    char saved[PYMCL_PATH] = "";
    cJSON *v = config_get("export_dir");
    if (py_truthy(v)) py_str(v, saved, sizeof(saved));
    char s[PYMCL_PATH];
    strip_copy(saved, s, sizeof(s));
    if (s[0]) {
        char p[PYMCL_PATH];
        pymcl_py_path(s, p, sizeof(p));
        if (pymcl_dir_exists(p)) { snprintf(out, n, "%s", p); return; }
    }
    pymcl_path_join(out, n, g_root, "exports");
    pymcl_ensure_dir(out);
}

/* ---------- 主分发 ---------- */

cJSON *rpc_local_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    int dummy;
    if (!handled) handled = &dummy;
    *handled = 1;

    /* i18n.* */
    if (strcmp(method, "get_language") == 0) return cJSON_CreateString(i18n_current());
    if (strcmp(method, "set_language") == 0) {
        i18n_set_language(pstr(params, "lang", ""));
        return cJSON_CreateNull();
    }
    if (strcmp(method, "available_languages") == 0) return i18n_available_languages();
    if (strcmp(method, "translate") == 0) {
        const char *key = pstr(params, "key", "");
        const char *lang = pstr(params, "lang", "");
        return cJSON_CreateString(tr_lang(key, lang[0] ? lang : NULL));
    }

    /* BackendAPI.catalog_favorites / toggle_favorite */
    if (strcmp(method, "catalog_favorites") == 0) return py_list(config_get("catalog_favorites"));
    if (strcmp(method, "toggle_favorite") == 0) {
        cJSON *item = param(params, "item");
        if (!cJSON_IsObject(item)) { pymcl_set_error("'NoneType' object has no attribute 'get'"); return NULL; }
        char ks[512] = "", kid[512] = "";
        cJSON *src = cJSON_GetObjectItemCaseSensitive(item, "source");
        if (py_truthy(src)) py_str(src, ks, sizeof(ks));
        cJSON *slug = cJSON_GetObjectItemCaseSensitive(item, "slug");
        if (!py_truthy(slug)) slug = cJSON_GetObjectItemCaseSensitive(item, "id");
        if (!py_truthy(slug)) slug = cJSON_GetObjectItemCaseSensitive(item, "name");
        if (py_truthy(slug)) py_str(slug, kid, sizeof(kid));
        cJSON *rows = py_list(config_get("catalog_favorites"));
        cJSON *kept = cJSON_CreateArray();
        int found = 0;
        cJSON *r;
        cJSON_ArrayForEach(r, rows) {
            char rs[512] = "", rid[512] = "";
            cJSON *a = cJSON_GetObjectItemCaseSensitive(r, "source");
            if (py_truthy(a)) py_str(a, rs, sizeof(rs));
            cJSON *b = cJSON_GetObjectItemCaseSensitive(r, "slug");
            if (!py_truthy(b)) b = cJSON_GetObjectItemCaseSensitive(r, "id");
            if (!py_truthy(b)) b = cJSON_GetObjectItemCaseSensitive(r, "name");
            if (py_truthy(b)) py_str(b, rid, sizeof(rid));
            if (strcmp(rs, ks) == 0 && strcmp(rid, kid) == 0) { found = 1; continue; }
            cJSON_AddItemToArray(kept, cJSON_Duplicate(r, 1));
        }
        cJSON_Delete(rows);
        if (!found) {
            cJSON *e = cJSON_CreateObject();
            const char *keys[] = {"name", "source", "slug", "id"};
            for (int i = 0; i < 4; i++) {
                cJSON *v = cJSON_GetObjectItemCaseSensitive(item, keys[i]);
                cJSON_AddItemToObject(e, keys[i], v ? cJSON_Duplicate(v, 1) : cJSON_CreateNull());
            }
            cJSON_AddItemToArray(kept, e);
        }
        config_set("catalog_favorites", cJSON_Duplicate(kept, 1));
        config_save();
        return kept;
    }

    /* BackendAPI.get_mods_targets / get_saves_targets */
    if (strcmp(method, "get_mods_targets") == 0 || strcmp(method, "get_saves_targets") == 0) {
        int mods = strcmp(method, "get_mods_targets") == 0;
        const char *inst = pstr(params, "instance", "");
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        cJSON *rows = cJSON_CreateArray();
        cJSON *first = cJSON_CreateObject();
        cJSON_AddStringToObject(first, "label", tr(mods ? "实例共享 mods 目录" : "大锅饭（所有版本共用）"));
        cJSON_AddStringToObject(first, "value", "");
        cJSON_AddItemToArray(rows, first);
        cJSON *ids = NULL;
        instance_installed_ids(inst, &ids);
        cJSON *v;
        cJSON_ArrayForEach(v, ids) {
            cJSON *vs = version_settings_load(inst, v->valuestring);
            const char *iso = vs_iso(vs);
            int hit = mods ? (strcmp(iso, "mods") == 0 || strcmp(iso, "all") == 0)
                           : (strcmp(iso, "saves") == 0 || strcmp(iso, "all") == 0);
            if (hit) {
                char label[512];
                snprintf(label, sizeof(label), "%s · %s", v->valuestring, tr(mods ? "独立 mods" : "独立存档"));
                cJSON *row = cJSON_CreateObject();
                cJSON_AddStringToObject(row, "label", label);
                cJSON_AddStringToObject(row, "value", v->valuestring);
                cJSON_AddItemToArray(rows, row);
            }
            cJSON_Delete(vs);
        }
        cJSON_Delete(ids);
        return rows;
    }

    /* BackendAPI.normalize_java_pref */
    if (strcmp(method, "normalize_java_pref") == 0) {
        const char *java = pstr(params, "java", "");
        if (!java[0] || strcmp(java, PYMCL_JAVA_AUTO) == 0 || strcmp(java, "auto") == 0 || strcmp(java, "default") == 0)
            return cJSON_CreateString(PYMCL_JAVA_AUTO);
        cJSON *all = java_all();
        cJSON *j;
        cJSON_ArrayForEach(j, all) {
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(j, "name"));
            const char *exe = cJSON_GetStringValue(cJSON_GetObjectItem(j, "exe"));
            if ((nm && strcmp(nm, java) == 0) || (exe && strcmp(exe, java) == 0)) {
                cJSON *r = cJSON_CreateString(exe && exe[0] ? exe : java);
                cJSON_Delete(all);
                return r;
            }
        }
        cJSON_Delete(all);
        char p[PYMCL_PATH];
        pymcl_py_path(java, p, sizeof(p));
        if (pymcl_file_exists(p) && !pymcl_dir_exists(p)) return cJSON_CreateString(p);
        return cJSON_CreateString(java);
    }

    /* playtime.get_playtime / get_all_playtime / get_total_playtime / format_duration */
    if (strcmp(method, "get_playtime") == 0) {
        const char *inst = pstr(params, "instance", "");
        if (!inst[0]) inst = config_str("default_instance", "default");
        cJSON *d = playtime_load();
        cJSON *insts = cJSON_GetObjectItemCaseSensitive(d, "instances");
        cJSON *it = cJSON_IsObject(insts) ? cJSON_GetObjectItemCaseSensitive(insts, inst) : NULL;
        cJSON *o = cJSON_CreateObject();
        if (!py_truthy(it)) {
            cJSON_AddNumberToObject(o, "total", 0);
            cJSON_AddItemToObject(o, "versions", cJSON_CreateObject());
            cJSON_AddItemToObject(o, "sessions", cJSON_CreateArray());
        } else {
            cJSON *t = cJSON_GetObjectItemCaseSensitive(it, "total");
            cJSON *vv = cJSON_GetObjectItemCaseSensitive(it, "versions");
            cJSON *ss = cJSON_GetObjectItemCaseSensitive(it, "sessions");
            cJSON_AddItemToObject(o, "total", t ? cJSON_Duplicate(t, 1) : cJSON_CreateNumber(0));
            cJSON_AddItemToObject(o, "versions", vv ? cJSON_Duplicate(vv, 1) : cJSON_CreateObject());
            cJSON_AddItemToObject(o, "sessions", ss ? py_list(ss) : cJSON_CreateArray());
        }
        cJSON_Delete(d);
        return o;
    }
    if (strcmp(method, "get_all_playtime") == 0) {
        cJSON *d = playtime_load();
        cJSON *insts = cJSON_DetachItemFromObjectCaseSensitive(d, "instances");
        cJSON_Delete(d);
        return insts ? insts : cJSON_CreateObject();
    }
    if (strcmp(method, "get_total_playtime") == 0) {
        cJSON *d = playtime_load();
        double total = 0;
        cJSON *it;
        cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(d, "instances")) {
            cJSON *t = cJSON_GetObjectItemCaseSensitive(it, "total");
            if (cJSON_IsNumber(t)) total += t->valuedouble;
        }
        cJSON_Delete(d);
        return cJSON_CreateNumber(total);
    }
    if (strcmp(method, "format_playtime") == 0) {
        char buf[64];
        format_duration(py_int_or(param(params, "seconds"), 0), buf, sizeof(buf));
        return cJSON_CreateString(buf);
    }

    /* java.java_vendor_list / java_vendor_label */
    if (strcmp(method, "java_vendor_list") == 0)
        return cJSON_Parse("[\"adoptium\",\"zulu\",\"microsoft\"]");
    if (strcmp(method, "java_vendor_label") == 0) {
        char v[128] = "";
        cJSON *raw = param(params, "vendor");
        if (py_truthy(raw)) py_str(raw, v, sizeof(v));
        char low[128];
        snprintf(low, sizeof(low), "%s", v);
        ascii_lower(low);
        if (strcmp(low, "adoptium") == 0) return cJSON_CreateString("Adoptium Temurin");
        if (strcmp(low, "zulu") == 0) return cJSON_CreateString("Azul Zulu");
        if (strcmp(low, "microsoft") == 0) return cJSON_CreateString("Microsoft OpenJDK");
        return cJSON_CreateString(v[0] ? v : "adoptium");
    }

    /* BackendAPI.game_root_name / game_root_path */
    if (strcmp(method, "game_root_name") == 0) {
        char rn[256];
        instance_root_name(rn, sizeof(rn));
        return cJSON_CreateString(rn);
    }
    if (strcmp(method, "game_root_path") == 0) {
        char ip[PYMCL_PATH];
        if (instance_open(NULL, ip, sizeof(ip)) != 0) return NULL;
        return cJSON_CreateString(ip);
    }

    /* BackendAPI.allow_multi_instance / set_multi_instance */
    if (strcmp(method, "allow_multi_instance") == 0)
        return cJSON_CreateBool(py_truthy(config_get("allow_multi_instance")));
    if (strcmp(method, "set_multi_instance") == 0) {
        config_set_bool("allow_multi_instance", py_truthy(param(params, "allow")));
        config_save();
        return cJSON_CreateNull();
    }

    /* BackendAPI.is_download_title：标题按中文原文拼，原文与译文前缀都认 */
    if (strcmp(method, "is_download_title") == 0) {
        char t[1024] = "";
        cJSON *raw = param(params, "title");
        if (py_truthy(raw)) py_str(raw, t, sizeof(t));
        static const char *keys[] = {"启动游戏", "微软登录", "皮肤站登录"};
        for (int i = 0; i < 3; i++) {
            if (pymcl_startswith(t, keys[i]) || pymcl_startswith(t, tr(keys[i]))) return cJSON_CreateFalse();
        }
        return cJSON_CreateTrue();
    }

    if (strcmp(method, "loader_of") == 0) {
        char vid[512] = "";
        cJSON *raw = param(params, "version_id");
        if (py_truthy(raw)) py_str(raw, vid, sizeof(vid));
        return loader_of(vid);
    }

    /* BackendAPI.get_version_isolation */
    if (strcmp(method, "get_version_isolation") == 0) {
        char ip[PYMCL_PATH];
        if (instance_open(NULL, ip, sizeof(ip)) != 0) return NULL;
        cJSON *vs = version_settings_load("", pstr(params, "version", ""));
        cJSON *r = cJSON_CreateString(vs_iso(vs));
        cJSON_Delete(vs);
        return r;
    }

    /* BackendAPI.get_version_rows */
    if (strcmp(method, "get_version_rows") == 0) {
        char ip[PYMCL_PATH];
        if (instance_open(NULL, ip, sizeof(ip)) != 0) return NULL;
        int show_hidden = py_truthy(param(params, "include_hidden")) || py_truthy(config_get("show_hidden_versions"));
        cJSON *ids = NULL;
        instance_installed_ids("", &ids);
        cJSON *rows = cJSON_CreateArray();
        cJSON *v;
        cJSON_ArrayForEach(v, ids) {
            const char *vid = v->valuestring;
            cJSON *s = version_settings_load("", vid);
            int hidden = py_truthy(cJSON_GetObjectItemCaseSensitive(s, "hidden"));
            if (hidden && !show_hidden) { cJSON_Delete(s); continue; }
            char gd[PYMCL_PATH], md[PYMCL_PATH];
            vs_game_dir("", vid, s, gd, sizeof(gd));
            pymcl_path_join(md, sizeof(md), gd, "mods");
            cJSON *lo = loader_of(vid);
            cJSON *vj = instance_version_json("", vid);
            char mc[512];
            cJSON *inh = cJSON_GetObjectItemCaseSensitive(vj, "inheritsFrom");
            cJSON *jid = cJSON_GetObjectItemCaseSensitive(vj, "id");
            if (py_truthy(inh)) py_str(inh, mc, sizeof(mc));
            else if (py_truthy(jid)) py_str(jid, mc, sizeof(mc));
            else snprintf(mc, sizeof(mc), "%s", vid);
            cJSON_Delete(vj);
            const char *iso = vs_iso(s);
            cJSON *row = cJSON_CreateObject();
            cJSON_AddStringToObject(row, "id", vid);
            cJSON_AddStringToObject(row, "loader", cJSON_GetArrayItem(lo, 0)->valuestring);
            cJSON_AddStringToObject(row, "loader_color", cJSON_GetArrayItem(lo, 1)->valuestring);
            cJSON_AddStringToObject(row, "mc", mc);
            cJSON_AddStringToObject(row, "isolation", iso);
            cJSON_AddStringToObject(row, "isolation_label", tr(isolation_label(iso)));
            cJSON_AddBoolToObject(row, "isolated", vs_is_isolated(s));
            cJSON_AddNumberToObject(row, "mods", count_jars(md));
            cJSON_AddStringToObject(row, "mods_dir", md);
            cJSON_AddBoolToObject(row, "hidden", hidden);
            cJSON *java = cJSON_GetObjectItemCaseSensitive(s, "java");
            cJSON_AddItemToObject(row, "java", py_truthy(java) ? cJSON_Duplicate(java, 1) : cJSON_CreateString(PYMCL_JAVA_AUTO));
            cJSON *mem = cJSON_GetObjectItemCaseSensitive(s, "memory_mb");
            cJSON_AddItemToObject(row, "memory_mb", py_truthy(mem) ? cJSON_Duplicate(mem, 1) : cJSON_CreateNumber(0));
            cJSON_AddItemToArray(rows, row);
            cJSON_Delete(lo);
            cJSON_Delete(s);
        }
        cJSON_Delete(ids);
        return rows;
    }

    /* BackendAPI.get_installed_mod_entries */
    if (strcmp(method, "get_installed_mod_entries") == 0) {
        const char *inst = pstr(params, "instance", "");
        const char *ver = pstr(params, "version", "");
        char ip[PYMCL_PATH], dir[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        if (ver[0]) {
            cJSON *s = version_settings_load(inst, ver);
            char gd[PYMCL_PATH];
            vs_game_dir(inst, ver, s, gd, sizeof(gd));
            cJSON_Delete(s);
            pymcl_path_join(dir, sizeof(dir), gd, "mods");
        } else {
            pymcl_path_join(dir, sizeof(dir), ip, "mods");
        }
        return mod_entries_at(dir);
    }

    /* BackendAPI.delete_modpack */
    if (strcmp(method, "delete_modpack") == 0) {
        const char *inst = pstr(params, "instance", "");
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
        cJSON *meta = instance_meta(inst);
        cJSON *pack = cJSON_GetObjectItemCaseSensitive(meta, "modpack");
        int ok = cJSON_IsObject(pack) && py_truthy(cJSON_GetObjectItemCaseSensitive(pack, "name"));
        cJSON_Delete(meta);
        if (!ok) { pymcl_set_error("%s", tr("该实例没有已安装整合包")); return NULL; }
        if (py_truthy(param(params, "purge_instance"))) {
            if (instance_delete(inst) != 0) return NULL;
        } else {
            cJSON *nul = cJSON_CreateNull();
            instance_set_meta(inst, "modpack", nul);
            cJSON_Delete(nul);
        }
        emit_ui_changed(emit);
        return cJSON_CreateNull();
    }

    /* content_export.default_export_dir / remember_export_dir */
    if (strcmp(method, "default_export_dir") == 0) {
        char d[PYMCL_PATH];
        default_export_dir(d, sizeof(d));
        return cJSON_CreateString(d);
    }
    if (strcmp(method, "remember_export_dir") == 0) {
        char p[PYMCL_PATH];
        pymcl_py_path(pstr(params, "path", ""), p, sizeof(p));
        if (!pymcl_dir_exists(p)) {
            char d[PYMCL_PATH];
            default_export_dir(d, sizeof(d));
            return cJSON_CreateString(d);
        }
        config_set_str("export_dir", p);
        config_save();
        return cJSON_CreateString(p);
    }

    /* BackendAPI.background_history / can_undo / undo / reset */
    if (strcmp(method, "background_history") == 0 || strcmp(method, "can_undo_background") == 0) {
        cJSON *images, *folders;
        bg_history(&images, &folders);
        cJSON_Delete(folders);
        if (strcmp(method, "background_history") == 0) return images;
        int any = cJSON_GetArraySize(images) > 0;
        cJSON_Delete(images);
        return cJSON_CreateBool(any);
    }
    if (strcmp(method, "undo_background") == 0) {
        cJSON *images, *folders;
        bg_history(&images, &folders);
        int n = cJSON_GetArraySize(images);
        if (!n) {
            cJSON_Delete(images);
            cJSON_Delete(folders);
            return current_background();
        }
        cJSON *prev = cJSON_CreateObject();
        cJSON_AddStringToObject(prev, "image", cJSON_GetArrayItem(images, n - 1)->valuestring);
        cJSON_AddStringToObject(prev, "folder", cJSON_GetArrayItem(folders, n - 1)->valuestring);
        cJSON_DeleteItemFromArray(images, n - 1);
        cJSON_DeleteItemFromArray(folders, n - 1);
        config_set("ui_background_history", images);
        config_set("ui_background_folder_history", folders);
        config_set_str("ui_background", cJSON_GetObjectItem(prev, "image")->valuestring);
        config_set_str("ui_background_folder", cJSON_GetObjectItem(prev, "folder")->valuestring);
        config_save();
        emit_ui_changed(emit);
        return prev;
    }
    if (strcmp(method, "reset_background") == 0) {
        cJSON *cur = current_background();
        const char *ci = cJSON_GetObjectItem(cur, "image")->valuestring;
        const char *cf = cJSON_GetObjectItem(cur, "folder")->valuestring;
        config_set_str("ui_background", "");
        config_set_str("ui_background_folder", "");
        if (ci[0] || cf[0]) {
            cJSON *images, *folders;
            bg_history(&images, &folders);
            int n = cJSON_GetArraySize(images);
            int same = n && strcmp(cJSON_GetArrayItem(images, n - 1)->valuestring, ci) == 0 &&
                       strcmp(cJSON_GetArrayItem(folders, n - 1)->valuestring, cf) == 0;
            if (!same) {
                cJSON_AddItemToArray(images, cJSON_CreateString(ci));
                cJSON_AddItemToArray(folders, cJSON_CreateString(cf));
                keep_last(images, 20);
                keep_last(folders, 20);
            }
            config_set("ui_background_history", images);
            config_set("ui_background_folder_history", folders);
        }
        cJSON_Delete(cur);
        config_save();
        emit_ui_changed(emit);
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "image", "");
        cJSON_AddStringToObject(o, "folder", "");
        return o;
    }

    /* help_content.search_articles / get_article（标题过词表，正文不翻） */
    if (strcmp(method, "help_articles") == 0) {
        char q[512];
        strip_copy(pstr(params, "query", ""), q, sizeof(q));
        ascii_lower(q);
        cJSON *out = cJSON_CreateArray();
        for (size_t i = 0; i < sizeof(k_articles) / sizeof(k_articles[0]); i++) {
            if (q[0]) {
                size_t len = strlen(k_articles[i][1]) + strlen(k_articles[i][2]) + 2;
                char *blob = (char *)malloc(len);
                if (!blob) continue;
                snprintf(blob, len, "%s\n%s", k_articles[i][1], k_articles[i][2]);
                ascii_lower(blob);
                int hit = strstr(blob, q) != NULL;
                free(blob);
                if (!hit) continue;
            }
            cJSON_AddItemToArray(out, article_json(i));
        }
        return out;
    }
    if (strcmp(method, "help_article") == 0) {
        char aid[256];
        strip_copy(pstr(params, "article_id", ""), aid, sizeof(aid));
        for (size_t i = 0; i < sizeof(k_articles) / sizeof(k_articles[0]); i++)
            if (strcmp(k_articles[i][0], aid) == 0) return article_json(i);
        return cJSON_CreateObject();
    }

    /* sysinfo.collect / format_text / get_smart_recommendation */
    if (strcmp(method, "collect_sysinfo") == 0)
        return sysinfo_collect(py_truthy(param(params, "force")), py_truthy(param(params, "scan_system_java")), 120);
    if (strcmp(method, "sysinfo_text") == 0) {
        char *t = sysinfo_format_text(param(params, "info"));
        cJSON *r = cJSON_CreateString(t ? t : "");
        free(t);
        return r;
    }
    if (strcmp(method, "get_smart_recommendation") == 0) return sysinfo_smart_recommendation();

    /* lan.local_ips / lan_hint */
    if (strcmp(method, "local_ips") == 0) return local_ips();
    if (strcmp(method, "lan_hint") == 0) {
        long long port = 25565;
        cJSON *p = param(params, "port");
        if (p) port = py_int_or(p, 25565);
        cJSON *ips = local_ips();
        size_t cap = 256 + (size_t)cJSON_GetArraySize(ips) * 32;
        char *text = (char *)malloc(cap);
        if (!text) { cJSON_Delete(ips); return NULL; }
        snprintf(text, cap, "%s", "房主在游戏里「对局域网开放」后，把下面地址发给好友：\n");
        int first = 1;
        cJSON *it;
        cJSON_ArrayForEach(it, ips) {
            char line[96];
            snprintf(line, sizeof(line), "%s%s:%lld", first ? "" : "\n", it->valuestring, port);
            strncat(text, line, cap - strlen(text) - 1);
            first = 0;
        }
        cJSON_Delete(ips);
        cJSON *r = cJSON_CreateString(text);
        free(text);
        return r;
    }

    return rpc_content_call(method, params, emit, handled);
}
