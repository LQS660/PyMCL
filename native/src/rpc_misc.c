#include "pymcl.h"
#include <objbase.h>
#include <shobjidl.h>
#include <shlobj.h>
#include <ctype.h>

/* Windows COM 头链会把 NULL 重定义成整数 0，令 cJSON_ArrayForEach 里的
   (cJSON*) 三目表达式报 -Wint-conversion；恢复标准 C 的 (void*)0 口径。 */
#undef NULL
#define NULL ((void *)0)

/* T3 残余（M1 收尾，docs/GOAL-c-bridge-no-python.md）：
   create_desktop_shortcut / set_account_skin / export_crash_report 的原生实现。
   参考实现：mclauncher/shortcut.py create_launch_shortcut、bridge/api.py set_account_skin、
   mclauncher/crash.py export_report。文案/返回结构逐字对齐 Python，错误文案沿用
   Python 的原文（tr 的走 tr，Python 里没走 tr 的保持原文）。 */

cJSON *rpc_misc_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled);

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = o ? cJSON_GetStringValue(cJSON_GetObjectItem(o, k)) : NULL;
    return s ? s : def;
}

static int misc_is_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

static void misc_delete_file(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    if (w) {
        DeleteFileW(w);
        free(w);
    }
}

/* ---------- create_desktop_shortcut（mclauncher/shortcut.py） ---------- */

/* MinGW 未链 libuuid，GUID 本地自给（值即 Windows 官方定义） */
static const GUID MISC_CLSID_ShellLink =
    {0x00021401, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
static const GUID MISC_IID_IShellLinkW =
    {0x000214F9, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
static const GUID MISC_IID_IPersistFile =
    {0x0000010B, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
/* FOLDERID_Desktop，同 shortcut.py _FOLDERID_DESKTOP */
static const GUID MISC_FOLDERID_Desktop =
    {0xB4BFCC3A, 0xDB2C, 0x424C, {0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41}};

static void misc_exe_path(char *out, size_t n) {
    out[0] = 0;
    wchar_t w[PYMCL_PATH];
    DWORD got = GetModuleFileNameW(NULL, w, PYMCL_PATH);
    if (!got) return;
    char *u = pymcl_wide_to_u8(w);
    if (!u) return;
    snprintf(out, n, "%s", u);
    free(u);
}

/* shortcut.desktop_dir：SHGetKnownFolderPath 优先（OneDrive 重定向也拿得对），
   拿不到再 USERPROFILE/Desktop、USERPROFILE/桌面、USERPROFILE */
static void misc_desktop_dir(char *out, size_t n) {
    out[0] = 0;
    PWSTR w = NULL;
    if (SUCCEEDED(SHGetKnownFolderPath(&MISC_FOLDERID_Desktop, 0, NULL, &w)) && w) {
        char *u = pymcl_wide_to_u8(w);
        if (u) {
            snprintf(out, n, "%s", u);
            free(u);
        }
        CoTaskMemFree(w);
    }
    if (out[0] && pymcl_dir_exists(out)) return;
    const char *home = getenv("USERPROFILE");
    if (!home || !home[0]) {
        snprintf(out, n, "%s", out[0] ? out : ".");
        return;
    }
    static const char *const CAND[] = {"Desktop", "桌面"};
    for (int i = 0; i < 2; i++) {
        char cand[PYMCL_PATH];
        pymcl_path_join(cand, sizeof(cand), home, CAND[i]);
        if (pymcl_dir_exists(cand)) {
            snprintf(out, n, "%s", cand);
            return;
        }
    }
    snprintf(out, n, "%s", home);
}

/* shortcut.launcher_command 的 C 版：桥 exe 旁优先 PyMCL-CLI.exe（带控制台的 CLI），
   没有再退 PyMCL.exe / 桥 exe 本身。Python 冻结态同构；开发态 Python 用
   [python, main.py]，C-only 桥不可能起 Python，属已登记差异。 */
static void misc_launcher_target(char *out, size_t n) {
    char exe[PYMCL_PATH];
    misc_exe_path(exe, sizeof(exe));
    if (!exe[0]) {
        snprintf(out, n, "PyMCL.exe");
        return;
    }
    char dir[PYMCL_PATH];
    pymcl_parent(exe, dir, sizeof(dir));
    if (!dir[0]) {
        snprintf(out, n, "%s", exe);
        return;
    }
    char cand[PYMCL_PATH];
    pymcl_path_join(cand, sizeof(cand), dir, "PyMCL-CLI.exe");
    if (pymcl_file_exists(cand)) {
        snprintf(out, n, "%s", cand);
        return;
    }
    pymcl_path_join(cand, sizeof(cand), dir, "PyMCL.exe");
    if (pymcl_file_exists(cand)) {
        snprintf(out, n, "%s", cand);
        return;
    }
    snprintf(out, n, "%s", exe);
}

/* shortcut.safe_filename：先去首尾空白，坏字符换 '_'，再去首尾 ". "，空了回 Minecraft */
static void misc_safe_filename(const char *in, char *out, size_t n) {
    const char *s = in ? in : "";
    while (*s && isspace((unsigned char)*s)) s++;
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) len--;
    size_t o = 0;
    for (size_t i = 0; i < len && o + 1 < n; i++) {
        char c = s[i];
        if (c == '\\' || c == '/' || c == ':' || c == '*' || c == '?' || c == '"' || c == '<' || c == '>' || c == '|')
            c = '_';
        out[o++] = c;
    }
    out[o] = 0;
    size_t bl = strlen(out);
    while (bl && (out[bl - 1] == '.' || out[bl - 1] == ' ')) out[--bl] = 0;
    char *b = out;
    while (*b == '.' || *b == ' ') b++;
    bl = strlen(b);
    if (!bl) {
        snprintf(out, n, "Minecraft");
    } else if (b != out) {
        memmove(out, b, bl + 1);
    }
}

/* shortcut._quote：含空格或空串才加引号，不做内部转义（同 Python） */
static void misc_quote_arg(const char *a, char *out, size_t n) {
    if (!a) a = "";
    if (strchr(a, ' ') || !a[0]) snprintf(out, n, "\"%s\"", a);
    else snprintf(out, n, "%s", a);
}

/* shortcut._create_windows 的 COM 原生版：IShellLinkW + IPersistFile::Save */
static int misc_create_lnk(const char *lnk, const char *target, const char *arguments,
                           const char *workdir, const char *icon, const char *description) {
    HRESULT chi = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    int ok = 0;
    IShellLinkW *psl = NULL;
    if (SUCCEEDED(CoCreateInstance(&MISC_CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
                                   &MISC_IID_IShellLinkW, (void **)&psl)) && psl) {
        wchar_t *wtarget = pymcl_u8_to_wide(target);
        wchar_t *wargs = pymcl_u8_to_wide(arguments);
        wchar_t *wdir = pymcl_u8_to_wide(workdir);
        wchar_t *wdesc = pymcl_u8_to_wide(description);
        psl->lpVtbl->SetPath(psl, wtarget);
        psl->lpVtbl->SetArguments(psl, wargs);
        psl->lpVtbl->SetWorkingDirectory(psl, wdir);
        psl->lpVtbl->SetDescription(psl, wdesc);
        if (icon && icon[0]) {
            wchar_t *wicon = pymcl_u8_to_wide(icon);
            psl->lpVtbl->SetIconLocation(psl, wicon, 0);
            free(wicon);
        }
        IPersistFile *ppf = NULL;
        if (SUCCEEDED(psl->lpVtbl->QueryInterface(psl, &MISC_IID_IPersistFile, (void **)&ppf)) && ppf) {
            wchar_t *wlnk = pymcl_u8_to_wide(lnk);
            if (wlnk && SUCCEEDED(ppf->lpVtbl->Save(ppf, wlnk, TRUE))) ok = 1;
            free(wlnk);
            ppf->lpVtbl->Release(ppf);
        }
        free(wtarget);
        free(wargs);
        free(wdir);
        free(wdesc);
        psl->lpVtbl->Release(psl);
    }
    if (SUCCEEDED(chi)) CoUninitialize();
    return ok;
}

static cJSON *misc_create_desktop_shortcut(cJSON *params) {
    const char *instance = pstr(params, "instance", "");
    const char *version = pstr(params, "version", "");
    const char *username = pstr(params, "username", "");
    const char *account = pstr(params, "account", "");
    const char *name = pstr(params, "name", "");
    if (!version[0]) {
        pymcl_set_error("请先选择要创建快捷方式的版本");
        return NULL;
    }

    char target[PYMCL_PATH], exedir[PYMCL_PATH];
    {
        char exe[PYMCL_PATH];
        misc_launcher_target(target, sizeof(target));
        snprintf(exe, sizeof(exe), "%s", target);
        pymcl_parent(exe, exedir, sizeof(exedir));
    }

    /* launch_args：-i <instance> launch <version> [--account|--username]（同 shortcut.launch_args） */
    const char *raw[8];
    int np = 0;
    raw[np++] = "-i";
    raw[np++] = instance;
    raw[np++] = "launch";
    raw[np++] = version;
    if (account[0]) {
        raw[np++] = "--account";
        raw[np++] = account;
    } else if (username[0]) {
        raw[np++] = "--username";
        raw[np++] = username;
    }
    size_t cap = 4;
    for (int i = 0; i < np; i++) cap += strlen(raw[i]) * 2 + 4;
    char *arguments = (char *)malloc(cap);
    if (!arguments) {
        pymcl_set_error("内存不足");
        return NULL;
    }
    arguments[0] = 0;
    for (int i = 0; i < np; i++) {
        char q[PYMCL_PATH];
        misc_quote_arg(raw[i], q, sizeof(q));
        if (i) strcat(arguments, " ");
        strcat(arguments, q);
    }

    /* label：name or (f"{version} - {instance}" if instance else version) */
    char label_src[PYMCL_PATH], label[PYMCL_PATH];
    if (name[0]) snprintf(label_src, sizeof(label_src), "%s", name);
    else if (instance[0]) snprintf(label_src, sizeof(label_src), "%s - %s", version, instance);
    else snprintf(label_src, sizeof(label_src), "%s", version);
    misc_safe_filename(label_src, label, sizeof(label));

    /* icon：Python 参考认「代码根 / icon.ico」，其次可执行文件本身；C 的代码根
       近似为桥 exe 目录，再兜数据根，最后用可执行文件 */
    char icon[PYMCL_PATH] = "";
    {
        char cand[PYMCL_PATH];
        if (exedir[0]) {
            pymcl_path_join(cand, sizeof(cand), exedir, "icon.ico");
            if (pymcl_file_exists(cand)) snprintf(icon, sizeof(icon), "%s", cand);
        }
        if (!icon[0]) {
            pymcl_path_join(cand, sizeof(cand), g_root, "icon.ico");
            if (pymcl_file_exists(cand)) snprintf(icon, sizeof(icon), "%s", cand);
        }
        if (!icon[0]) snprintf(icon, sizeof(icon), "%s", target);
    }

    char desc[1024];
    snprintf(desc, sizeof(desc), "PyMCL 启动 %s / %s", instance[0] ? instance : "default", version);

    char desk[PYMCL_PATH], lnkname[PYMCL_PATH], lnk[PYMCL_PATH];
    misc_desktop_dir(desk, sizeof(desk));
    snprintf(lnkname, sizeof(lnkname), "%s.lnk", label);
    pymcl_path_join(lnk, sizeof(lnk), desk, lnkname);

    /* workdir：Python 用代码根 _PROJECT_ROOT；C-only 布局下启动器就在 exe 目录里 */
    const char *workdir = exedir[0] ? exedir : g_root;
    int ok = misc_create_lnk(lnk, target, arguments, workdir, icon, desc);
    free(arguments);
    if (!ok) {
        /* Python 走 PowerShell，失败文案取 stderr；COM 原生没有 stderr，
           保留其兜底文案，语义（创建失败）与调用方提示一致 */
        pymcl_set_error("PowerShell 创建快捷方式失败");
        return NULL;
    }
    if (!pymcl_file_exists(lnk)) {
        pymcl_set_error("快捷方式未生成: %s", lnk);
        return NULL;
    }
    return cJSON_CreateString(lnk);
}

/* ---------- set_account_skin（bridge/api.py + mclauncher/skin.py） ---------- */

static void misc_skins_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "skins");
    pymcl_ensure_dir(out);
}

/* skin.validate_skin / png_size：只读 PNG 头，尺寸只认 64x64 / 64x32 */
static int misc_png_valid_skin(const unsigned char *d, size_t len, char *err, size_t en) {
    static const unsigned char sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    if (len < 24 || memcmp(d, sig, 8) != 0 || memcmp(d + 12, "IHDR", 4) != 0) {
        snprintf(err, en, "这不是一个有效的 PNG 文件");
        return 0;
    }
    uint32_t w = ((uint32_t)d[16] << 24) | ((uint32_t)d[17] << 16) | ((uint32_t)d[18] << 8) | d[19];
    uint32_t h = ((uint32_t)d[20] << 24) | ((uint32_t)d[21] << 16) | ((uint32_t)d[22] << 8) | d[23];
    if (!(w == 64 && (h == 64 || h == 32))) {
        snprintf(err, en, "皮肤尺寸必须是 64x64 或 64x32，这张是 %ux%u", w, h);
        return 0;
    }
    return 1;
}

/* skin._dest_for：safe = 非字母数字（Unicode 口径）和 -_ 以外全换 '_' */
static void misc_skin_dest(const char *account_name, char *out, size_t n) {
    char d[PYMCL_PATH], safe[512];
    misc_skins_dir(d, sizeof(d));
    wchar_t *w = pymcl_u8_to_wide(account_name && account_name[0] ? account_name : "player");
    if (w) {
        for (wchar_t *p = w; *p; p++)
            if (!(IsCharAlphaNumericW(*p) || *p == L'-' || *p == L'_')) *p = L'_';
        char *u = pymcl_wide_to_u8(w);
        snprintf(safe, sizeof(safe), "%s", u && u[0] ? u : "player");
        free(u);
        free(w);
    } else {
        snprintf(safe, sizeof(safe), "player");
    }
    char fn[600];
    snprintf(fn, sizeof(fn), "%s.png", safe);
    pymcl_path_join(out, n, d, fn);
}

/* skin.skin_model */
static const char *misc_skin_model(cJSON *acc) {
    const char *m = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_model"));
    return (m && !_stricmp(m, "slim")) ? "slim" : "classic";
}

/* skin.skin_file_for 的路径部分：只认 skins 目录下的文件名 */
static void misc_skin_file_path(cJSON *acc, char *out, size_t n) {
    out[0] = 0;
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_file"));
    char s[512] = "";
    if (nm) {
        while (*nm && isspace((unsigned char)*nm)) nm++;
        snprintf(s, sizeof(s), "%s", nm);
        size_t len = strlen(s);
        while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    }
    if (!s[0]) return;
    char d[PYMCL_PATH];
    misc_skins_dir(d, sizeof(d));
    pymcl_path_join(out, n, d, pymcl_basename(s));
}

static void misc_set_skin_keys(cJSON *acc, const char *fname, const char *model) {
    cJSON_DeleteItemFromObjectCaseSensitive(acc, "skin_file");
    cJSON_AddStringToObject(acc, "skin_file", fname);
    cJSON_DeleteItemFromObjectCaseSensitive(acc, "skin_model");
    cJSON_AddStringToObject(acc, "skin_model", (!_stricmp(model, "slim")) ? "slim" : "classic");
}

static cJSON *misc_set_account_skin(cJSON *params, sse_emit_fn emit) {
    const char *name = pstr(params, "name", "");
    const char *path = pstr(params, "path", "");
    const char *model = pstr(params, "model", "classic");
    const char *data = pstr(params, "data", "");
    cJSON *root = accounts_load();
    cJSON *arr = cJSON_IsObject(root) ? cJSON_GetObjectItem(root, "accounts") : NULL;
    cJSON *acc = NULL;
    cJSON *it;
    /* 注意：cJSON_ArrayForEach 宏体对参数不加括号（array != NULL），
       传三目表达式必须自己再包一层括号，否则优先级被拆坏 */
    cJSON_ArrayForEach(it, (cJSON_IsArray(arr) ? arr : NULL)) {
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "name"));
        if (nm && strcmp(nm, name) == 0) {
            acc = it;
            break;
        }
    }
    if (!acc) {
        cJSON_Delete(root);
        char m[PYMCL_ERR];
        tr_fmt0(m, sizeof(m), "没有这个账号：{0}", name);
        pymcl_set_error("%s", m);
        return NULL;
    }
    const char *type = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "type")) ?: "";
    if (strcmp(type, "offline") != 0) {
        cJSON_Delete(root);
        pymcl_set_error("%s", tr("自定义皮肤只对离线账号有效；正版和皮肤站账号的皮肤在各自的网站上改"));
        return NULL;
    }

    const char *blob = data;
    while (*blob && isspace((unsigned char)*blob)) blob++;
    size_t blen = strlen(blob);
    while (blen && isspace((unsigned char)blob[blen - 1])) blen--;
    char err[256];

    if (blen) {
        /* data 路径：base64（可带 data: 前缀），Python validate=True 口径 */
        const char *raw = blob;
        size_t rlen = blen;
        if (blen >= 5 && strncmp(blob, "data:", 5) == 0) {
            const char *comma = memchr(blob, ',', blen);
            /* 无逗号时 Python split(",",1)[-1] 还是原串，解码必失败——保持一致 */
            if (comma) {
                raw = comma + 1;
                rlen = blen - (size_t)(raw - blob);
            }
        }
        char *tmp = (char *)malloc(rlen + 1);
        if (!tmp) {
            cJSON_Delete(root);
            pymcl_set_error("内存不足");
            return NULL;
        }
        memcpy(tmp, raw, rlen);
        tmp[rlen] = 0;
        size_t pn = 0;
        unsigned char *png = pymcl_b64decode(tmp, &pn);
        free(tmp);
        if (!png) {
            cJSON_Delete(root);
            pymcl_set_error("%s", tr("皮肤数据不是有效的 base64"));
            return NULL;
        }
        if (!misc_png_valid_skin(png, pn, err, sizeof(err))) {
            free(png);
            cJSON_Delete(root);
            pymcl_set_error("%s", err);
            return NULL;
        }
        char dest[PYMCL_PATH];
        misc_skin_dest(name, dest, sizeof(dest));
        pymcl_write_file(dest, png, pn);
        free(png);
        misc_set_skin_keys(acc, pymcl_basename(dest), model);
    } else {
        const char *p = path;
        while (*p && isspace((unsigned char)*p)) p++;
        size_t plen = strlen(p);
        while (plen && isspace((unsigned char)p[plen - 1])) plen--;
        if (!plen) {
            /* 清除：remove_skin + pop(skin_file/skin_model) */
            char fp[PYMCL_PATH];
            misc_skin_file_path(acc, fp, sizeof(fp));
            if (fp[0] && pymcl_file_exists(fp)) misc_delete_file(fp);
            cJSON_DeleteItemFromObjectCaseSensitive(acc, "skin_file");
            cJSON_DeleteItemFromObjectCaseSensitive(acc, "skin_model");
        } else {
            /* import_skin：expanduser → 存在性 → 2MB 上限 → 校验 → 收进 skins */
            char pth[PYMCL_PATH];
            snprintf(pth, sizeof(pth), "%.*s", (int)plen, p);
            if (strcmp(pth, "~") == 0 || strncmp(pth, "~/", 2) == 0 || strncmp(pth, "~\\", 2) == 0) {
                const char *home = getenv("USERPROFILE");
                if (home) {
                    char ex[PYMCL_PATH];
                    snprintf(ex, sizeof(ex), "%s%s", home, pth + 1);
                    snprintf(pth, sizeof(pth), "%s", ex);
                }
            }
            pymcl_replace_char(pth, '/', '\\');
            if (!pymcl_file_exists(pth)) {
                cJSON_Delete(root);
                pymcl_set_error("找不到文件：%s", pth);
                return NULL;
            }
            long long sz = pymcl_file_size(pth);
            if (sz > 2 * 1024 * 1024) {
                cJSON_Delete(root);
                pymcl_set_error("皮肤文件过大（上限 2 MB）");
                return NULL;
            }
            char *buf = NULL;
            size_t pn = 0;
            if (pymcl_read_file(pth, &buf, &pn) != 0 || !buf) {
                pn = 0;
                buf = (char *)calloc(1, 1);
            }
            int valid = misc_png_valid_skin((const unsigned char *)buf, pn, err, sizeof(err));
            free(buf);
            if (!valid) {
                cJSON_Delete(root);
                pymcl_set_error("%s", err);
                return NULL;
            }
            char dest[PYMCL_PATH];
            misc_skin_dest(name, dest, sizeof(dest));
            if (_stricmp(pth, dest) != 0) pymcl_copy_file(pth, dest);
            misc_set_skin_keys(acc, pymcl_basename(dest), model);
        }
    }

    accounts_save(root);
    if (emit) emit("ui_changed", cJSON_CreateObject());
    const char *sf = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_file"));
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "name", name);
    cJSON_AddStringToObject(o, "skin_file", sf ? sf : "");
    cJSON_AddStringToObject(o, "skin_model", misc_skin_model(acc));
    cJSON_Delete(root);
    return o;
}

/* ---------- export_crash_report（bridge/api.py + mclauncher/crash.py export_report） ---------- */

/* crash._TOKEN_RE：(?i)((?:access[_-]?token|session[_-]?token|refresh[_-]?token
   |client[_-]?secret|authorization)\s*[:=]\s*)([^\s"']+) → 组2 换 *** */
static const char *const MISC_TOKEN_KEYS[] = {
    "access_token", "access-token", "accesstoken",
    "session_token", "session-token", "sessiontoken",
    "refresh_token", "refresh-token", "refreshtoken",
    "client_secret", "client-secret", "clientsecret",
    "authorization",
};
/* crash._UUID_AUTH_RE：(?i)(--(?:accessToken|uuid|xuid|clientId)\s+)\S+ → 组2 换 *** */
static const char *const MISC_ARG_KEYS[] = {"--accesstoken", "--uuid", "--xuid", "--clientid"};

static void misc_mask_values(char *s, const char *const *keys, size_t nkeys, int space_sep) {
    for (size_t i = 0; s[i]; i++) {
        for (size_t k = 0; k < nkeys; k++) {
            size_t kl = strlen(keys[k]);
            if (_strnicmp(s + i, keys[k], kl) != 0) continue;
            size_t j = i + kl;
            size_t ws = 0;
            while (s[j + ws] && misc_is_space(s[j + ws])) ws++;
            if (space_sep) {
                if (!ws) break; /* \s+ 至少一个 */
                j += ws;
            } else {
                j += ws;
                if (s[j] != ':' && s[j] != '=') break;
                j++;
                while (s[j] && misc_is_space(s[j])) j++;
            }
            size_t vs = j;
            while (s[j] && !misc_is_space(s[j]) && (space_sep || (s[j] != '"' && s[j] != '\''))) j++;
            if (j == vs) break; /* 值至少 1 字符，否则整体不匹配 */
            memmove(s + vs + 3, s + j, strlen(s + j) + 1);
            memcpy(s + vs, "***", 3);
            i = vs + 2; /* 跳过掩码 */
            break;
        }
    }
}

static char *misc_filter_secrets(const char *text) {
    if (!text || !text[0]) return pymcl_strdup("");
    char *s = pymcl_strdup(text);
    if (!s) return NULL;
    misc_mask_values(s, MISC_TOKEN_KEYS, sizeof(MISC_TOKEN_KEYS) / sizeof(MISC_TOKEN_KEYS[0]), 0);
    misc_mask_values(s, MISC_ARG_KEYS, sizeof(MISC_ARG_KEYS) / sizeof(MISC_ARG_KEYS[0]), 1);
    return s;
}

/* Path.write_text 在 Windows 把 '\n' 全量译成 '\r\n'（newline=None 默认），照做 */
static int misc_write_text_nl(const char *path, const char *text, size_t len) {
    size_t nl = 0;
    for (size_t i = 0; i < len; i++)
        if (text[i] == '\n') nl++;
    char *buf = (char *)malloc(len + nl + 1);
    if (!buf) return -1;
    size_t o = 0;
    for (size_t i = 0; i < len; i++) {
        if (text[i] == '\n') buf[o++] = '\r';
        buf[o++] = text[i];
    }
    buf[o] = 0;
    int rc = pymcl_write_file(path, buf, o);
    free(buf);
    return rc;
}

static int misc_utf8_valid(const char *s, size_t n) {
    if (!n) return 1;
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, (int)n, NULL, 0) > 0;
}

/* crash.read_text：utf-8-sig → utf-8 → gb18030 → gbk → utf-8(replace) */
static char *misc_read_text(const char *path, size_t *out_len) {
    *out_len = 0;
    char *raw = NULL;
    size_t n = 0;
    if (pymcl_read_file(path, &raw, &n) != 0 || !raw) {
        free(raw);
        return pymcl_strdup("");
    }
    char *data = (char *)realloc(raw, n + 1);
    if (!data) {
        free(raw);
        return pymcl_strdup("");
    }
    data[n] = 0;
    size_t off = (n >= 3 && (unsigned char)data[0] == 0xEF && (unsigned char)data[1] == 0xBB &&
                  (unsigned char)data[2] == 0xBF)
                     ? 3 : 0;
    if (off && misc_utf8_valid(data + off, n - off)) {
        memmove(data, data + off, n - off);
        data[n - off] = 0;
        *out_len = n - off;
        return data;
    }
    if (misc_utf8_valid(data, n)) {
        *out_len = n;
        return data;
    }
    static const UINT CODES[] = {54936, 936}; /* gb18030, gbk */
    for (size_t c = 0; c < sizeof(CODES) / sizeof(CODES[0]); c++) {
        int wl = MultiByteToWideChar(CODES[c], MB_ERR_INVALID_CHARS, data, (int)n, NULL, 0);
        if (wl <= 0) continue;
        wchar_t *w = (wchar_t *)malloc((size_t)wl * sizeof(wchar_t));
        if (!w) break;
        MultiByteToWideChar(CODES[c], 0, data, (int)n, w, wl);
        int ul = WideCharToMultiByte(CP_UTF8, 0, w, wl, NULL, 0, NULL, NULL);
        char *u = ul > 0 ? (char *)malloc((size_t)ul + 1) : NULL;
        if (u && WideCharToMultiByte(CP_UTF8, 0, w, wl, u, ul, NULL, NULL) > 0) {
            u[ul] = 0;
            free(w);
            free(data);
            *out_len = (size_t)ul;
            return u;
        }
        free(u);
        free(w);
    }
    /* 兜底 errors="replace"：非 ASCII 字节逐个换 U+FFFD（Python 按序列换，
       极端字节串下 FFFD 个数可能有出入，日志场景几乎不会走到） */
    char *rep = (char *)malloc(n * 3 + 1);
    if (!rep) {
        free(data);
        return pymcl_strdup("");
    }
    size_t o = 0;
    for (size_t i = 0; i < n; i++) {
        unsigned char b = (unsigned char)data[i];
        if (b < 0x80) {
            rep[o++] = (char)b;
        } else {
            rep[o++] = (char)0xEF;
            rep[o++] = (char)0xBF;
            rep[o++] = (char)0xBD;
        }
    }
    rep[o] = 0;
    free(data);
    *out_len = o;
    return rep;
}

static const char *misc_jstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

/* crash.export_report：报告 → 分析结论/输出末尾/日志文件（脱敏）→ zip */
static int misc_export_report(cJSON *report, const char *dest, char *out, size_t on) {
    char stamp[40];
    time_t now = time(NULL);
    struct tm lt;
    if (localtime_s(&lt, &now) != 0) {
        pymcl_set_error("导出失败：本地时间不可用");
        return -1;
    }
    strftime(stamp, sizeof(stamp), "%Y-%m-%d_%H.%M.%S", &lt);
    char destp[PYMCL_PATH];
    if (dest && dest[0]) {
        snprintf(destp, sizeof(destp), "%s", dest);
    } else {
        char defname[128];
        snprintf(defname, sizeof(defname), "错误报告-%s.zip", stamp);
        pymcl_path_join(destp, sizeof(destp), g_root, defname);
    }

    /* tmp = dest_path.with_suffix(".tmpdir")：去掉最后一个后缀再接 .tmpdir，没有后缀则追加 */
    char tmp[PYMCL_PATH];
    snprintf(tmp, sizeof(tmp), "%s", destp);
    {
        char *b1 = strrchr(tmp, '\\'), *b2 = strrchr(tmp, '/');
        char *base = b1 > b2 ? b1 : b2;
        char *dot = strrchr(base ? base + 1 : tmp, '.');
        if (dot && dot > tmp && dot[-1] != '\\' && dot[-1] != '/')
            *dot = 0;
        size_t tl = strlen(tmp);
        snprintf(tmp + tl, sizeof(tmp) - tl, ".tmpdir");
    }

    if (pymcl_dir_exists(tmp)) pymcl_remove_tree(tmp);
    pymcl_ensure_dir(tmp);

    /* 分析结论.txt：f"实例: {}\n版本: {}\n退出码: {} {}\n\n{}\n"（缺键同 Python f"{None}"） */
    const char *inst = misc_jstr(report, "instance", "None");
    const char *ver = misc_jstr(report, "version", "None");
    char codebuf[32] = "None";
    cJSON *ec = cJSON_GetObjectItemCaseSensitive(report, "exit_code");
    if (cJSON_IsNumber(ec)) snprintf(codebuf, sizeof(codebuf), "%lld", (long long)ec->valuedouble);
    const char *hint = misc_jstr(report, "exit_hint", "");
    const char *detail = misc_jstr(report, "detail", "");
    size_t cap = strlen(inst) + strlen(ver) + strlen(codebuf) + strlen(hint) + strlen(detail) + 96;
    char *analysis = (char *)malloc(cap);
    if (!analysis) {
        pymcl_set_error("内存不足");
        return -1;
    }
    snprintf(analysis, cap, "实例: %s\n版本: %s\n退出码: %s %s\n\n%s\n", inst, ver, codebuf, hint, detail);
    char *fa = misc_filter_secrets(analysis);
    free(analysis);
    if (!fa) {
        pymcl_set_error("内存不足");
        return -1;
    }
    {
        char f1[PYMCL_PATH];
        pymcl_path_join(f1, sizeof(f1), tmp, "分析结论.txt");
        misc_write_text_nl(f1, fa, strlen(fa));
    }
    free(fa);

    const char *tail = misc_jstr(report, "output_tail", "");
    if (tail[0]) {
        char *ft = misc_filter_secrets(tail);
        if (ft) {
            char f2[PYMCL_PATH];
            pymcl_path_join(f2, sizeof(f2), tmp, "游戏崩溃前的输出.txt");
            misc_write_text_nl(f2, ft, strlen(ft));
            free(ft);
        }
    }

    /* files：逐个脱敏拷入，重名走 stem_N.suffix（同 Python while in copied/exists） */
    cJSON *files = cJSON_GetObjectItemCaseSensitive(report, "files");
    if (cJSON_IsArray(files)) {
        cJSON *fi;
        cJSON_ArrayForEach(fi, files) {
            const char *raw = cJSON_GetStringValue(fi);
            if (!raw || !raw[0] || !pymcl_file_exists(raw)) continue;
            char name[512], stem[512], suffix[64];
            snprintf(name, sizeof(name), "%s", pymcl_basename(raw));
            snprintf(stem, sizeof(stem), "%s", name);
            suffix[0] = 0;
            char *dot = strrchr(stem, '.');
            if (dot && dot != stem) {
                *dot = 0;
                snprintf(suffix, sizeof(suffix), "%s", dot);
            }
            char target[PYMCL_PATH];
            pymcl_path_join(target, sizeof(target), tmp, name);
            int n2 = 1;
            while (pymcl_file_exists(target)) {
                snprintf(name, sizeof(name), "%s_%d%s", stem, n2++, suffix);
                pymcl_path_join(target, sizeof(target), tmp, name);
            }
            size_t tl = 0;
            char *txt = misc_read_text(raw, &tl);
            char *ftx = misc_filter_secrets(txt);
            free(txt);
            if (ftx) {
                misc_write_text_nl(target, ftx, strlen(ftx));
                free(ftx);
            }
        }
    }

    /* 打 zip（ZIP_DEFLATED，arcname 相对 tmp 的 posix 路径） */
    if (pymcl_file_exists(destp)) misc_delete_file(destp);
    pymcl_zipw *z = pymcl_zipw_open(destp);
    if (!z) {
        pymcl_remove_tree(tmp);
        return -1; /* 错误已由 zipw_open 设置 */
    }
    cJSON *walk = pymcl_walk_files(tmp);
    int fail = 0;
    cJSON *wi;
    cJSON_ArrayForEach(wi, walk) {
        char abs[PYMCL_PATH];
        pymcl_path_join(abs, sizeof(abs), tmp, wi->valuestring);
        if (pymcl_zipw_add_file(z, abs, wi->valuestring, 6) != 0) {
            fail = 1;
            break;
        }
    }
    cJSON_Delete(walk);
    if (fail) {
        pymcl_zipw_abort(z);
        pymcl_remove_tree(tmp);
        pymcl_set_error("打包崩溃报告失败");
        return -1;
    }
    if (pymcl_zipw_close(z) != 0) {
        pymcl_remove_tree(tmp);
        if (!pymcl_error()[0]) pymcl_set_error("打包崩溃报告失败");
        return -1;
    }
    pymcl_remove_tree(tmp);
    snprintf(out, on, "%s", destp);
    return 0;
}

static cJSON *misc_export_crash_report(cJSON *params) {
    const char *dest = pstr(params, "dest", "");
    cJSON *rep = backend_last_crash();
    if (!cJSON_IsObject(rep) || cJSON_GetArraySize(rep) == 0) {
        cJSON_Delete(rep);
        pymcl_set_error("%s", tr("没有可导出的错误报告"));
        return NULL;
    }
    char out[PYMCL_PATH];
    int rc = misc_export_report(rep, dest, out, sizeof(out));
    cJSON_Delete(rep);
    if (rc != 0) return NULL;
    return cJSON_CreateString(out);
}

/* ---------- 分发 ---------- */

cJSON *rpc_misc_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    int dummy;
    if (!handled) handled = &dummy;
    *handled = 0;
    if (!method || !params) return NULL;
    if (strcmp(method, "create_desktop_shortcut") == 0) {
        *handled = 1;
        return misc_create_desktop_shortcut(params);
    }
    if (strcmp(method, "set_account_skin") == 0) {
        *handled = 1;
        return misc_set_account_skin(params, emit);
    }
    if (strcmp(method, "export_crash_report") == 0) {
        *handled = 1;
        return misc_export_crash_report(params);
    }
    return NULL;
}
