#include "pymcl.h"
#include <ctype.h>

static cJSON *load_parent_ud(const char *pid, void *ud) {
    const char *inst = (const char *)ud;
    return instance_version_json(inst, pid);
}

/* 与 pymcl_replace_placeholders 同一套替换规则，但结果按需增长：${classpath} 常常上万字节，
   定长缓冲区会把排在最后的客户端 jar 静默截掉 */
static char *subst_dup(const char *text, cJSON *ph) {
    size_t cap = strlen(text) + 1, o = 0;
    char *out = (char *)malloc(cap);
    for (const char *p = text; *p;) {
        const char *val = NULL;
        size_t skip = 1;
        if (p[0] == '$' && p[1] == '{') {
            const char *e = strchr(p + 2, '}');
            if (e) {
                char key[128];
                size_t kn = (size_t)(e - (p + 2));
                if (kn > sizeof(key) - 1) kn = sizeof(key) - 1;
                memcpy(key, p + 2, kn); key[kn] = 0;
                val = cJSON_GetStringValue(cJSON_GetObjectItem(ph, key));
                if (val) skip = (size_t)(e + 1 - p);
            }
        }
        size_t len = val ? strlen(val) : 1;
        if (o + len + 1 > cap) {
            while (o + len + 1 > cap) cap *= 2;
            out = (char *)realloc(out, cap);
        }
        memcpy(out + o, val ? val : p, len);
        o += len;
        p += skip;
    }
    out[o] = 0;
    return out;
}

/* 替换后还剩未知占位符的参数整条丢掉（同 Python _expand_args） */
static void push_expanded(char ***out, int *n, const char *text, cJSON *ph) {
    char *v = subst_dup(text, ph);
    if (pymcl_has_placeholder(v)) { free(v); return; }
    *out = (char **)realloc(*out, sizeof(char *) * (size_t)(*n + 1));
    (*out)[(*n)++] = v;
}

static void expand_args(cJSON *raw, cJSON *ph, int custom_res, char ***out, int *n) {
    *out = NULL; *n = 0;
    if (!cJSON_IsArray(raw)) return;
    cJSON *e;
    cJSON_ArrayForEach(e, raw) {
        if (cJSON_IsString(e)) {
            push_expanded(out, n, e->valuestring, ph);
        } else if (cJSON_IsObject(e)) {
            if (!pymcl_check_rules(cJSON_GetObjectItem(e, "rules"), custom_res)) continue;
            cJSON *val = cJSON_GetObjectItem(e, "value");
            if (cJSON_IsString(val)) {
                push_expanded(out, n, val->valuestring, ph);
            } else if (cJSON_IsArray(val)) {
                cJSON *x;
                cJSON_ArrayForEach(x, val)
                    if (cJSON_IsString(x)) push_expanded(out, n, x->valuestring, ph);
            }
        }
    }
}

static const char *jvm_val_flags[] = {
    "-p", "-cp", "-classpath", "--class-path", "--module-path",
    "--add-modules", "--add-opens", "--add-exports", "--add-reads", NULL
};
static int is_val_flag(const char *a) {
    for (int i = 0; jvm_val_flags[i]; i++) if (strcmp(a, jvm_val_flags[i]) == 0) return 1;
    return 0;
}
static void drop_orphan(char ***args, int *n) {
    char **in = *args; int nin = *n;
    char **out = (char **)calloc((size_t)nin, sizeof(char *));
    int no = 0;
    for (int i = 0; i < nin; i++) {
        if (is_val_flag(in[i])) {
            const char *nxt = (i + 1 < nin) ? in[i + 1] : "";
            if (!nxt[0] || nxt[0] == '-') { free(in[i]); continue; }
            out[no++] = in[i];
            out[no++] = in[++i];
            continue;
        }
        out[no++] = in[i];
    }
    free(in);
    *args = out; *n = no;
}

static void apply_memory(char ***args, int *n, int memory_mb) {
    if (memory_mb < 512) memory_mb = 512;
    int xms = memory_mb / 2; if (xms > 1024) xms = 1024;
    char **in = *args; int nin = *n;
    char **out = (char **)calloc((size_t)nin + 4, sizeof(char *));
    int no = 0;
    for (int i = 0; i < nin; i++) {
        if (pymcl_startswith(in[i], "-Xmx") || pymcl_startswith(in[i], "-Xms")) { free(in[i]); continue; }
        out[no++] = in[i];
    }
    char a[32], b[32];
    snprintf(a, sizeof(a), "-Xmx%dM", memory_mb);
    snprintf(b, sizeof(b), "-Xms%dM", xms);
    out[no++] = pymcl_strdup(a);
    out[no++] = pymcl_strdup(b);
    free(in);
    *args = out; *n = no;
}

/* 把客户端 jar 等补进 -DignoreList=（同 Python _patch_ignore_list）：BootstrapLauncher 按「文件名以某前缀开头」
   排除 jar，所以只有没有任何前缀能匹配时才补；空项丢掉。漏补的原版 jar 会变成自动模块，Forge 1.17+ 直接起不来 */
static void patch_ignore(char **args, int n, const char **names, int nn) {
    static const char key[] = "-DignoreList=";
    for (int i = 0; i < n; i++) {
        if (!pymcl_startswith(args[i], key)) continue;
        size_t cap = strlen(args[i]) + 1;
        for (int k = 0; k < nn; k++) if (names[k]) cap += strlen(names[k]) + 1;
        char *list = pymcl_strdup(args[i] + sizeof(key) - 1);
        const char **prefixes = (const char **)calloc((size_t)nn + strlen(list) + 1, sizeof(char *));
        int np = 0;
        for (char *p = list; *p;) {
            char *comma = strchr(p, ',');
            if (comma) *comma = 0;
            if (*p) prefixes[np++] = p;
            if (!comma) break;
            p = comma + 1;
        }
        for (int k = 0; k < nn; k++) {
            if (!names[k] || !names[k][0]) continue;
            int covered = 0;
            for (int j = 0; j < np && !covered; j++) covered = pymcl_startswith(names[k], prefixes[j]);
            if (!covered) prefixes[np++] = names[k];
        }
        char *out = (char *)malloc(cap), *w = out;
        memcpy(w, key, sizeof(key) - 1);
        w += sizeof(key) - 1;
        for (int j = 0; j < np; j++) {
            if (j) *w++ = ',';
            size_t L = strlen(prefixes[j]);
            memcpy(w, prefixes[j], L);
            w += L;
        }
        *w = 0;
        free(prefixes);
        free(list);
        free(args[i]);
        args[i] = out;
    }
}

/* 有库声明了本平台的 natives 分类器，启动前就必须真的解压出来了（同 Python） */
static int needs_natives(cJSON *resolved) {
    cJSON *lib;
    cJSON_ArrayForEach(lib, cJSON_GetObjectItem(resolved, "libraries")) {
        if (cJSON_IsFalse(cJSON_GetObjectItem(lib, "clientreq"))) continue;
        if (!pymcl_check_rules(cJSON_GetObjectItem(lib, "rules"), 0)) continue;
        char *cls = select_native_classifier(lib);
        if (cls) { free(cls); return 1; }
    }
    return 0;
}

/* authlib.injector_path / nide8.jar_path：代码根目录下的固定文件名。
   源码布局下 exe 在 native/build/，代码根要往上两级；打包布局下就是 exe 旁边 */
static void code_root_jar(const char *name, char *out, size_t n) {
    wchar_t w[PYMCL_PATH];
    DWORD len = GetModuleFileNameW(NULL, w, PYMCL_PATH);
    char exe[PYMCL_PATH];
    if (len > 0 && len < PYMCL_PATH) {
        char *u = pymcl_wide_to_u8(w);
        snprintf(exe, sizeof(exe), "%s", u ? u : ".");
        free(u);
    } else snprintf(exe, sizeof(exe), ".");
    char d[PYMCL_PATH];
    pymcl_parent(exe, d, sizeof(d));
    char cand[PYMCL_PATH];
    pymcl_path_join(cand, sizeof(cand), d, name);
    if (pymcl_file_exists(cand)) { snprintf(out, n, "%s", cand); return; }
    char up[PYMCL_PATH];
    pymcl_parent(d, up, sizeof(up));
    char up2[PYMCL_PATH];
    pymcl_parent(up, up2, sizeof(up2));
    pymcl_path_join(cand, sizeof(cand), up2, name);
    snprintf(out, n, "%s", cand);
}

/* authlib.normalize_api：去空白与尾斜杠，无 scheme 补 https://，必须有主机。
   urlparse 认不出的裸 "http…"（没有 ://）按 netloc 为空处理 */
static int normalize_api_url(const char *in, char *out, size_t n) {
    const char *p = in ? in : "";
    while (*p && isspace((unsigned char)*p)) p++;
    char raw[512];
    snprintf(raw, sizeof(raw), "%s", p);
    size_t L = strlen(raw);
    while (L && (raw[L - 1] == '/' || isspace((unsigned char)raw[L - 1]))) raw[--L] = 0;
    if (!L) { pymcl_set_error("请填写皮肤站 Yggdrasil API 地址"); return -1; }
    if (strncmp(raw, "http", 4) != 0) {
        char t[600];
        snprintf(t, sizeof(t), "https://%s", raw);
        snprintf(raw, sizeof(raw), "%s", t);
    }
    const char *host = strstr(raw, "://");
    host = host ? host + 3 : "";
    if (!host[0] || *host == '/') { pymcl_set_error("皮肤站地址无效"); return -1; }
    snprintf(out, n, "%s", raw);
    return 0;
}

/* nide8.normalize_server_id：正文里找第一段 32 位十六进制（与 _SID_RE.search 一致），小写化 */
static int normalize_server_sid(const char *in, char *out, size_t n) {
    const char *p = in ? in : "";
    while (*p && isspace((unsigned char)*p)) p++;
    char raw[512];
    snprintf(raw, sizeof(raw), "%s", p);
    size_t L = strlen(raw);
    while (L && isspace((unsigned char)raw[L - 1])) raw[--L] = 0;
    if (!L) { pymcl_set_error("请填写统一通行证服务器 ID"); return -1; }
    for (const char *q = raw; *q; q++) {
        size_t k = 0;
        while (k < 32 && isxdigit((unsigned char)q[k])) k++;
        if (k == 32) {
            for (size_t i = 0; i < 32; i++) out[i] = (char)tolower((unsigned char)q[i]);
            out[32] = 0;
            return 0;
        }
    }
    pymcl_set_error("服务器 ID 应为 32 位十六进制，或含该 ID 的链接");
    return -1;
}

/* 加 -javaagent: 时先摘掉已有的（同 Python launcher.py 468-480） */
static void prepend_agent(char ***pjvm, int *pn, const char *agent) {
    char **jvm = *pjvm;
    int n = *pn;
    char **out = (char **)calloc((size_t)n + 2, sizeof(char *));
    int no = 0;
    out[no++] = pymcl_strdup(agent);
    for (int i = 0; i < n; i++) {
        if (pymcl_startswith(jvm[i], "-javaagent:")) { free(jvm[i]); continue; }
        out[no++] = jvm[i];
    }
    free(jvm);
    *pjvm = out;
    *pn = no;
}

/* 启动前最后一次核对 Java（同 Python _coerce_java_exe）：给定的不能用就换自动挑选，
   再不行把已下载的、系统里的 Java 挨个试；都不行才报错 */
static char *coerce_java(cJSON *resolved, const char *java_exe) {
    if (java_exe && java_usable_for(resolved, java_exe)) return pymcl_strdup(java_exe);
    char *alt = java_pick(resolved, NULL);
    if (alt && java_usable_for(resolved, alt)) return alt;
    free(alt);
    cJSON *(*listers[])(void) = { java_list_installed, java_list_system };
    for (size_t i = 0; i < sizeof(listers) / sizeof(listers[0]); i++) {
        cJSON *rows = listers[i]();
        char *found = NULL;
        cJSON *row;
        cJSON_ArrayForEach(row, rows) {
            const char *cand = cJSON_GetStringValue(cJSON_GetObjectItem(row, "exe"));
            if (!found && cand && cand[0] && java_usable_for(resolved, cand)) found = pymcl_strdup(cand);
        }
        cJSON_Delete(rows);
        if (found) return found;
    }
    int got = (java_exe && java_exe[0]) ? java_get_major(java_exe) : -1;
    char gs[16];
    if (got > 0) snprintf(gs, sizeof(gs), "%d", got);
    else snprintf(gs, sizeof(gs), "?");
    pymcl_set_error("Java %s 无法启动此版本（需要 Java %d+）。"
                    "Forge 1.17+ 会向 JVM 传入 --module-path，Java 8 会报 Unrecognized option: -p。"
                    "请到「Java」页下载 Java 17，启动页 Java 选「自动选择」。",
                    gs, java_required_major(resolved));
    return NULL;
}

int build_launch_command_ex(const char *instance, const char *version, cJSON *account_props,
                            const char *java_exe, int memory_mb, int width, int height,
                            const char *game_dir_override,
                            char **extra_game_args, int n_ega,
                            char **extra_jvm_args, int n_eja,
                            char ***argv, int *argc, char *natives_out, size_t nn) {
    cJSON *vjson = instance_version_json(instance, version);
    if (!vjson) { pymcl_set_error("版本 %s 未安装，请先安装。", version); return -1; }
    /* 合并完继承链就没有 inheritsFrom 了，找客户端 jar 的回退得看原始 JSON（同 Python _client_jar_path）：
       Fabric、Forge 1.13+ 的版本目录里通常没有自己的 jar，也不写 jar 字段 */
    char child_jar[256], child_parent[256];
    snprintf(child_jar, sizeof(child_jar), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(vjson, "jar")) ?: "");
    snprintf(child_parent, sizeof(child_parent), "%s",
             cJSON_GetStringValue(cJSON_GetObjectItem(vjson, "inheritsFrom")) ?: "");
    cJSON *resolved = manifest_resolve_inherits(vjson, load_parent_ud, (void *)instance);
    cJSON_Delete(vjson);
    if (!resolved) return -1;

    char *jexe = coerce_java(resolved, java_exe);
    if (!jexe) { cJSON_Delete(resolved); return -1; }

    char vdir[PYMCL_PATH], jar[PYMCL_PATH];
    instance_versions_dir(instance, vdir, sizeof(vdir));
    char jn[256]; snprintf(jn, sizeof(jn), "%s.jar", version);
    pymcl_path_join3(jar, sizeof(jar), vdir, version, jn);
    if (!pymcl_file_exists(jar)) {
        const char *alts[] = {
            child_jar,
            cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "jar")),
            child_parent,
            cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "inheritsFrom")),
        };
        int found = 0;
        for (size_t i = 0; i < sizeof(alts) / sizeof(alts[0]) && !found; i++) {
            if (!alts[i] || !alts[i][0]) continue;
            char alt[PYMCL_PATH], an[256];
            snprintf(an, sizeof(an), "%s.jar", alts[i]);
            pymcl_path_join3(alt, sizeof(alt), vdir, alts[i], an);
            if (pymcl_file_exists(alt)) { snprintf(jar, sizeof(jar), "%s", alt); found = 1; }
        }
        if (!found) {
            pymcl_set_error("客户端 jar 缺失: %s\n请重新安装版本 %s。", jar, version);
            cJSON_Delete(resolved); free(jexe); return -1;
        }
    }

    char natives[PYMCL_PATH];
    extract_natives(instance, resolved, version, natives, sizeof(natives));
    if (natives_out) snprintf(natives_out, nn, "%s", natives);
    if (needs_natives(resolved) && !natives_present(natives)) {
        pymcl_set_error("缺少 LWJGL 本地库（natives）。请重新安装该 Minecraft 版本后再启动。");
        cJSON_Delete(resolved); free(jexe); return -1;
    }

    char libs[PYMCL_PATH], assets[PYMCL_PATH], ip[PYMCL_PATH];
    instance_libraries_dir(instance, libs, sizeof(libs));
    instance_assets_dir(instance, assets, sizeof(assets));
    instance_path(instance, ip, sizeof(ip));

    char **cp = NULL; int ncp = 0;
    cJSON *seen = cJSON_CreateObject();
    cJSON *lib;
    cJSON_ArrayForEach(lib, cJSON_GetObjectItem(resolved, "libraries")) {
        if (cJSON_IsFalse(cJSON_GetObjectItem(lib, "clientreq"))) continue;
        if (!pymcl_check_rules(cJSON_GetObjectItem(lib, "rules"), 0)) continue;
        const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(lib, "name"));
        if (!name) continue;
        cJSON *art = cJSON_GetObjectItem(cJSON_GetObjectItem(lib, "downloads"), "artifact");
        char rel[512] = {0};
        if (art && cJSON_GetStringValue(cJSON_GetObjectItem(art, "path")))
            snprintf(rel, sizeof(rel), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(art, "path")));
        else if (!cJSON_GetObjectItem(lib, "natives"))
            pymcl_maven_path(name, "jar", rel, sizeof(rel));
        else continue;
        pymcl_replace_char(rel, '/', '\\');
        char path[PYMCL_PATH];
        pymcl_path_join(path, sizeof(path), libs, rel);
        char key[256];
        library_identity(lib, key, sizeof(key));
        if (cJSON_GetObjectItem(seen, key)) {
            /* replace path kept at first position — skip extra append */
            continue;
        }
        cJSON_AddTrueToObject(seen, key);
        cp = (char **)realloc(cp, sizeof(char *) * (size_t)(ncp + 1));
        cp[ncp++] = pymcl_strdup(path);
    }
    cJSON_Delete(seen);
    cp = (char **)realloc(cp, sizeof(char *) * (size_t)(ncp + 1));
    cp[ncp++] = pymcl_strdup(jar);
    size_t cplen = 1;
    for (int i = 0; i < ncp; i++) cplen += strlen(cp[i]) + 1;
    char *classpath = (char *)malloc(cplen), *cw = classpath;
    for (int i = 0; i < ncp; i++) {
        if (i) *cw++ = ';';
        size_t L = strlen(cp[i]);
        memcpy(cw, cp[i], L);
        cw += L;
    }
    *cw = 0;

    cJSON *ph = cJSON_CreateObject();
    const char *pname = cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "name")) ?: "Player";
    const char *puuid = cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "uuid")) ?: "00000000-0000-0000-0000-000000000000";
    const char *ptok = cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "token")) ?: "0";
    char sess[256]; snprintf(sess, sizeof(sess), "token:%s:%s", ptok, puuid);
    cJSON_AddStringToObject(ph, "auth_player_name", pname);
    cJSON_AddStringToObject(ph, "auth_uuid", puuid);
    cJSON_AddStringToObject(ph, "auth_access_token", ptok);
    cJSON_AddStringToObject(ph, "auth_session", sess);
    cJSON_AddStringToObject(ph, "user_type", cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "user_type")) ?: "legacy");
    cJSON_AddStringToObject(ph, "user_properties", "{}");
    cJSON_AddStringToObject(ph, "auth_xuid", cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "xuid")) ?: "");
    cJSON_AddStringToObject(ph, "clientid", config_str("microsoft_client_id", PYMCL_MS_CLIENT_DEFAULT));
    cJSON_AddStringToObject(ph, "version_name", version);
    cJSON_AddStringToObject(ph, "version_type", cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "type")) ?: "release");
    cJSON_AddStringToObject(ph, "game_directory",
                            game_dir_override && game_dir_override[0] ? game_dir_override : ip);
    cJSON_AddStringToObject(ph, "assets_root", assets);
    cJSON *idx = cJSON_GetObjectItem(resolved, "assetIndex");
    cJSON_AddStringToObject(ph, "assets_index_name", cJSON_GetStringValue(cJSON_GetObjectItem(idx, "id")) ?: "legacy");
    char ga[PYMCL_PATH];
    pymcl_path_join3(ga, sizeof(ga), assets, "virtual", cJSON_GetStringValue(cJSON_GetObjectItem(idx, "id")) ?: "legacy");
    cJSON_AddStringToObject(ph, "game_assets", ga);
    cJSON_AddStringToObject(ph, "natives_directory", natives);
    cJSON_AddStringToObject(ph, "classpath", classpath);
    cJSON_AddStringToObject(ph, "library_directory", libs);
    cJSON_AddStringToObject(ph, "classpath_separator", ";");
    cJSON_AddStringToObject(ph, "launcher_name", PYMCL_LAUNCHER_NAME);
    cJSON_AddStringToObject(ph, "launcher_version", PYMCL_LAUNCHER_VERSION);
    char ws[16], hs[16];
    snprintf(ws, sizeof(ws), "%d", width > 0 ? width : 854);
    snprintf(hs, sizeof(hs), "%d", height > 0 ? height : 480);
    cJSON_AddStringToObject(ph, "resolution_width", ws);
    cJSON_AddStringToObject(ph, "resolution_height", hs);

    char **jvm = NULL, **game = NULL; int nj = 0, ng = 0;
    cJSON *args = cJSON_GetObjectItem(resolved, "arguments");
    const char *mine_args = cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "minecraftArguments"));
    int custom = width || height;
    if (cJSON_IsObject(args)) {
        expand_args(cJSON_GetObjectItem(args, "jvm"), ph, custom, &jvm, &nj);
        expand_args(cJSON_GetObjectItem(args, "game"), ph, custom, &game, &ng);
        int has_lp = 0, has_cp = 0;
        for (int i = 0; i < nj; i++) {
            if (pymcl_startswith(jvm[i], "-Djava.library.path")) has_lp = 1;
            if (strcmp(jvm[i], "-cp") == 0 || strcmp(jvm[i], "--class-path") == 0) has_cp = 1;
        }
        if (!has_lp) {
            char lp[PYMCL_PATH + 32];
            snprintf(lp, sizeof(lp), "-Djava.library.path=%s", natives);
            jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 1));
            memmove(jvm + 1, jvm, sizeof(char *) * (size_t)nj);
            jvm[0] = pymcl_strdup(lp); nj++;
        }
        if (!has_cp) {
            jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 2));
            jvm[nj++] = pymcl_strdup("-cp");
            jvm[nj++] = pymcl_strdup(classpath);
        }
    } else {
        /* 先按空格切模板再逐段替换（同 Python）：先替换再切，游戏目录里的空格会把一个参数拆成几段 */
        for (const char *p = mine_args ? mine_args : ""; *p;) {
            if (*p == ' ') { p++; continue; }
            const char *e = strchr(p, ' ');
            size_t len = e ? (size_t)(e - p) : strlen(p);
            char *tok = (char *)malloc(len + 1);
            memcpy(tok, p, len);
            tok[len] = 0;
            push_expanded(&game, &ng, tok, ph);
            free(tok);
            p += len;
        }
        char lp[PYMCL_PATH + 32];
        snprintf(lp, sizeof(lp), "-Djava.library.path=%s", natives);
        jvm = (char **)realloc(jvm, sizeof(char *) * 4);
        jvm[nj++] = pymcl_strdup(lp);
        jvm[nj++] = pymcl_strdup("-cp");
        jvm[nj++] = pymcl_strdup(classpath);
    }
    drop_orphan(&jvm, &nj);
    const char **ign = (const char **)calloc((size_t)ncp + 2, sizeof(char *));
    int ni = 0;
    ign[ni++] = pymcl_basename(jar);
    const char *parent = cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "inheritsFrom"));
    if (!parent) parent = cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "jar"));
    char pjar[256];
    if (parent) { snprintf(pjar, sizeof(pjar), "%s.jar", parent); ign[ni++] = pjar; }
    for (int i = 0; i < ncp; i++) if (pymcl_endswith(cp[i], "-extra.jar")) ign[ni++] = pymcl_basename(cp[i]);
    patch_ignore(jvm, nj, ign, ni);
    free(ign);
    /* 旧 Forge（LaunchWrapper）的 tweakClass 也可能写在新格式参数里（同 Python） */
    int tweak = !cJSON_IsObject(args) && mine_args && strstr(mine_args, "tweakClass");
    for (int i = 0; i < ng && !tweak; i++) tweak = strstr(game[i], "tweakClass") != NULL;
    if (tweak) {
        jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 2));
        jvm[nj++] = pymcl_strdup("-Dfml.ignoreInvalidMinecraftCertificates=true");
        jvm[nj++] = pymcl_strdup("-Dfml.ignorePatchDiscrepancies=true");
    }
    if (manifest_is_legacy(resolved) && memory_mb > 1024) memory_mb = 1024;
    for (int i = 0; i < nj; i++) if (strcmp(jvm[i], "-p") == 0) { free(jvm[i]); jvm[i] = pymcl_strdup("--module-path"); }
    apply_memory(&jvm, &nj, memory_mb);
    int has_brand = 0, has_ver = 0;
    for (int i = 0; i < nj; i++) {
        if (strstr(jvm[i], "-Dminecraft.launcher.brand")) has_brand = 1;
        if (strstr(jvm[i], "-Dminecraft.launcher.version")) has_ver = 1;
    }
    if (!has_brand) {
        char b[128]; snprintf(b, sizeof(b), "-Dminecraft.launcher.brand=%s", PYMCL_LAUNCHER_NAME);
        jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 1));
        jvm[nj++] = pymcl_strdup(b);
    }
    if (!has_ver) {
        char b[128]; snprintf(b, sizeof(b), "-Dminecraft.launcher.version=%s", PYMCL_LAUNCHER_VERSION);
        jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 1));
        jvm[nj++] = pymcl_strdup(b);
    }
    cJSON *logc = cJSON_GetObjectItem(cJSON_GetObjectItem(resolved, "logging"), "client");
    const char *lid = cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(logc, "file"), "id"));
    if (lid) {
        char lp[PYMCL_PATH];
        pymcl_path_join3(lp, sizeof(lp), assets, "log_configs", lid);
        if (pymcl_file_exists(lp)) {
            char a[PYMCL_PATH + 40];
            snprintf(a, sizeof(a), "-Dlog4j.configurationFile=%s", lp);
            jvm = (char **)realloc(jvm, sizeof(char *) * (size_t)(nj + 1));
            jvm[nj++] = pymcl_strdup(a);
        }
    }
    /* CONFIG default_jvm_args 与调用方的 extra_jvm_args 前置，再吃一次内存旗标；
       然后 authlib / nide8 的 -javaagent 前置并摘掉旧的（同 Python launcher.py 461-483） */
    {
        char **dj = NULL;
        int ndj = 0;
        pymcl_split_args(config_str("default_jvm_args", ""), &dj, &ndj);
        char **nj2 = (char **)calloc((size_t)ndj + (size_t)n_eja + (size_t)nj + 4, sizeof(char *));
        int k2 = 0;
        for (int i = 0; i < ndj; i++) nj2[k2++] = dj[i];
        for (int i = 0; i < n_eja; i++)
            if (extra_jvm_args && extra_jvm_args[i] && extra_jvm_args[i][0])
                nj2[k2++] = pymcl_strdup(extra_jvm_args[i]);
        for (int i = 0; i < nj; i++) nj2[k2++] = jvm[i];
        free(jvm);
        free(dj);
        jvm = nj2;
        nj = k2;
        apply_memory(&jvm, &nj, memory_mb);
        const char *api = cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "authlib_api")) ?: "";
        if (api[0]) {
            char api_n[512], jar[PYMCL_PATH], agent[PYMCL_PATH + 560];
            if (normalize_api_url(api, api_n, sizeof(api_n)) != 0) {
                for (int i = 0; i < nj; i++) free(jvm[i]);
                free(jvm);
                for (int i = 0; i < ng; i++) free(game[i]);
                free(game);
                for (int i = 0; i < ncp; i++) free(cp[i]);
                free(cp);
                free(classpath);
                free(jexe);
                cJSON_Delete(ph);
                cJSON_Delete(resolved);
                return -1;
            }
            code_root_jar("authlib-injector.jar", jar, sizeof(jar));
            snprintf(agent, sizeof(agent), "-javaagent:%s=%s", jar, api_n);
            prepend_agent(&jvm, &nj, agent);
        }
        const char *sid = cJSON_GetStringValue(cJSON_GetObjectItem(account_props, "nide8_id")) ?: "";
        if (sid[0]) {
            char sid_n[64], jar[PYMCL_PATH], agent[PYMCL_PATH + 96];
            if (normalize_server_sid(sid, sid_n, sizeof(sid_n)) != 0) {
                for (int i = 0; i < nj; i++) free(jvm[i]);
                free(jvm);
                for (int i = 0; i < ng; i++) free(game[i]);
                free(game);
                for (int i = 0; i < ncp; i++) free(cp[i]);
                free(cp);
                free(classpath);
                free(jexe);
                cJSON_Delete(ph);
                cJSON_Delete(resolved);
                return -1;
            }
            code_root_jar("nide8auth.jar", jar, sizeof(jar));
            snprintf(agent, sizeof(agent), "-javaagent:%s=%s", jar, sid_n);
            prepend_agent(&jvm, &nj, agent);
        }
    }
    const char *mainc = cJSON_GetStringValue(cJSON_GetObjectItem(resolved, "mainClass")) ?: "net.minecraft.client.main.Main";
    int total = 1 + nj + 1 + ng + n_ega;
    char **cmd = (char **)calloc((size_t)total, sizeof(char *));
    int k = 0;
    cmd[k++] = pymcl_strdup(jexe);
    for (int i = 0; i < nj; i++) cmd[k++] = jvm[i];
    cmd[k++] = pymcl_strdup(mainc);
    for (int i = 0; i < ng; i++) cmd[k++] = game[i];
    for (int i = 0; n_ega > 0 && extra_game_args && i < n_ega; i++)
        if (extra_game_args[i] && extra_game_args[i][0]) cmd[k++] = pymcl_strdup(extra_game_args[i]);
    /* Java 8 不认模块参数，带着它们必崩（同 Python 的最后一道拦截）；命令里真有模块参数才去问 Java 版本 */
    int jmajor = 0;
    for (int i = 0; i < k && !jmajor; i++)
        if (!strcmp(cmd[i], "-p") || !strcmp(cmd[i], "--module-path") || !strcmp(cmd[i], "--add-modules"))
            jmajor = java_get_major(jexe);
    free(jvm); free(game);
    for (int i = 0; i < ncp; i++) free(cp[i]);
    free(cp);
    free(classpath);
    free(jexe);
    cJSON_Delete(ph);
    cJSON_Delete(resolved);
    if (jmajor > 0 && jmajor < 9) {
        for (int i = 0; i < k; i++) free(cmd[i]);
        free(cmd);
        pymcl_set_error("拒绝用 Java %d 启动：命令含模块参数。请改用 Java 17。", jmajor);
        return -1;
    }
    *argv = cmd;
    *argc = k;
    return 0;
}

int build_launch_command(const char *instance, const char *version, cJSON *account_props,
                         const char *java_exe, int memory_mb, int width, int height,
                         char ***argv, int *argc, char *natives_out, size_t nn) {
    return build_launch_command_ex(instance, version, account_props, java_exe, memory_mb,
                                   width, height, NULL, NULL, 0, NULL, 0,
                                   argv, argc, natives_out, nn);
}

HANDLE game_spawn(const char **argv, int argc, const char *cwd, HANDLE *pipe) {
    return pymcl_spawn_process(argv, argc, cwd, pipe);
}
void game_kill(HANDLE proc) {
    if (proc) TerminateProcess(proc, 1);
}
