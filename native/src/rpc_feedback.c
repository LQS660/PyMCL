/* 反馈上报（docs/GOAL-c-bridge-no-python.md M2）：与 mclauncher/feedback.py 对齐。
 * 启动器只打反馈中心，不带管理令牌；URL 解析顺序 config feedback_url >
 * 环境变量 PYMCL_FEEDBACK_URL > feedback_defaults.DEFAULT_FEEDBACK_URL。
 * 对拍时两边都用 PYMCL_FEEDBACK_URL 指本地 mock，保证条件一致。 */
#include "pymcl.h"
#include <bcrypt.h>

#define FB_MAX_HISTORY 30
#define FB_TITLE_MAX_SAFE (120 * 4 + 1)
#define FB_BODY_MAX_SAFE (16000 * 4 + 1)
#define FB_CONTACT_MAX_SAFE (120 * 4 + 1)

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(o, k));
    return (v && v[0]) ? v : def;
}

static const char *FB_CATEGORIES[] = {
    "bug", "crash", "download", "multiplayer", "ai", "ui", "suggest", "other",
};

static void fb_resolve_url(char *out, size_t n) {
    const char *url = config_str("feedback_url", "");
    if (!url[0]) { const char *e = getenv("PYMCL_FEEDBACK_URL"); url = (e && e[0]) ? e : ""; }
    if (!url[0]) url = "http://114.66.28.184:53611";
    snprintf(out, n, "%s", url);
    size_t len = strlen(out);
    while (len > 0 && out[len - 1] == '/') out[--len] = '\0';
}

static int fb_has_consent(void) {
    cJSON *v = config_get("feedback_consent");
    return cJSON_IsTrue(v) ? 1 : 0;
}

/* device_id：config > root/device_id 文件 > 新生成 32 位 hex 写回（与 Python uuid4().hex 对位） */
static void fb_device_id(char *out, size_t n) {
    const char *stored = config_str("device_id", "");
    if (stored && stored[0]) { snprintf(out, n, "%s", stored); return; }
    char path[PYMCL_PATH];
    pymcl_path_join(path, sizeof(path), g_root, "device_id");
    char buf[96] = "";
    FILE *f = fopen(path, "rb");
    if (f) { size_t r = fread(buf, 1, sizeof(buf) - 1, f); fclose(f); buf[r] = '\0'; }
    char *trim = buf; while (*trim==' '||*trim=='\t'||*trim=='\r'||*trim=='\n') trim++;
    size_t tl = strlen(trim); while (tl > 0 && (trim[tl-1]=='\r'||trim[tl-1]=='\n')) trim[--tl] = '\0';
    if (trim[0]) { snprintf(out, n, "%s", trim); return; }
    unsigned int rnd[8];
    {
        unsigned char raw[32];
        if (BCryptGenRandom(NULL, raw, sizeof(raw), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0) {
            srand((unsigned)time(NULL));
            for (int i = 0; i < (int)sizeof(raw); i++) raw[i] = (unsigned char)(rand() & 0xff);
        }
        memcpy(rnd, raw, sizeof(rnd));
    }
    static const char hexd[] = "0123456789abcdef";
    unsigned char *b = (unsigned char *)rnd;
    for (int i = 0; i < 16; i++) { out[i*2] = hexd[b[i] >> 4]; out[i*2+1] = hexd[b[i] & 0xf]; }
    out[32] = '\0';
    FILE *w = fopen(path, "wb");
    if (w) { fputs(out, w); fclose(w); }
    config_set_str("device_id", out);
    config_save();
}

/* 按 UTF-8 字符数截断（Python [:n] 的语义），out 容量 n*4+1 足够 */
static void fb_trunc(const char *src, size_t max, char *out, size_t cap) {
    size_t chars = 0, i = 0, end = 0;
    while (src[i] && chars < max) {
        unsigned char c = (unsigned char)src[i];
        i += (c < 0x80) ? 1 : (c < 0xE0) ? 2 : (c < 0xF0) ? 3 : 4;
        chars++;
    }
    end = src[i] ? i - 0 : i; /* 循环退出时 i 即目标字节数（完整字符边界） */
    if (end > cap - 1) end = cap - 1;
    memcpy(out, src, end); out[end] = '\0';
}

static cJSON *fb_history_load(void) {
    char path[PYMCL_PATH];
    pymcl_path_join(path, sizeof(path), g_root, "feedback_history.json");
    cJSON *rows = pymcl_read_json(path);
    if (!cJSON_IsArray(rows)) { cJSON_Delete(rows); return cJSON_CreateArray(); }
    return rows;
}

static void fb_history_add(cJSON *row) {
    cJSON *rows = fb_history_load();
    cJSON_InsertItemInArray(rows, 0, row);
    while (cJSON_GetArraySize(rows) > FB_MAX_HISTORY)
        cJSON_DeleteItemFromArray(rows, cJSON_GetArraySize(rows) - 1);
    char path[PYMCL_PATH];
    pymcl_path_join(path, sizeof(path), g_root, "feedback_history.json");
    pymcl_write_json(path, rows);
    cJSON_Delete(rows);
}

/* POST {base}{path}；失败按 Python 的文案 set_error 返回 NULL */
static cJSON *fb_post(const char *path, cJSON *payload, int timeout) {
    char base[512]; fb_resolve_url(base, sizeof(base));
    if (!base[0]) { pymcl_set_error("未配置反馈服务器。开发者请启动 feedback_hub，并在设置里填写地址。"); return NULL; }
    char url[1024]; snprintf(url, sizeof(url), "%s%s", base, path);
    char *body = cJSON_PrintUnformatted(payload);
    char ua[80]; snprintf(ua, sizeof(ua), "PyMCL/%s", PYMCL_APP_VERSION);
    char hdr[256]; snprintf(hdr, sizeof(hdr), "X-PyMCL-Client: %s\r\n", ua);
    http_resp resp;
    int rc = http_post_json(url, body, &resp, hdr, timeout);
    free(body);
    if (rc != 0) {
        char inner[512];
        snprintf(inner, sizeof(inner), "%s", pymcl_error());
        pymcl_set_error("连不上反馈服务器: %s (%s)", url, inner);
        return NULL;
    }
    char text[801];
    size_t cp = resp.len < 800 ? resp.len : 800;
    memcpy(text, resp.body ? resp.body : "", cp); text[cp] = '\0';
    if (resp.status >= 400) {
        pymcl_set_error("反馈服务器 HTTP %d: %s", resp.status, text);
        http_resp_free(&resp);
        return NULL;
    }
    cJSON *data = cJSON_ParseWithLength(resp.body ? resp.body : "", resp.len);
    http_resp_free(&resp);
    if (!data) { pymcl_set_error("反馈服务器返回了无法解析的内容"); return NULL; }
    if (!cJSON_IsObject(data)) { cJSON_Delete(data); pymcl_set_error("反馈服务器返回格式不对"); return NULL; }
    cJSON *okf = cJSON_GetObjectItem(data, "ok");
    if (cJSON_IsFalse(okf)) {
        const char *err = cJSON_GetStringValue(cJSON_GetObjectItem(data, "error"));
        pymcl_set_error("%s", err ? err : "提交失败");
        cJSON_Delete(data);
        return NULL;
    }
    return data;
}

static int fb_cat_valid(const char *cat) {
    for (size_t i = 0; i < sizeof(FB_CATEGORIES)/sizeof(FB_CATEGORIES[0]); i++)
        if (strcmp(cat, FB_CATEGORIES[i]) == 0) return 1;
    return 0;
}

static cJSON *fb_submit(const char *category, const char *title_in, const char *body_in,
                        const char *contact_in, int include_sysinfo, cJSON *crash) {
    if (!fb_has_consent()) {
        pymcl_set_error("需要先同意上传诊断数据。第一次打开启动器时会询问，也可在设置里开启。");
        return NULL;
    }
    char cat[32];
    {
        char low[64]; size_t i = 0;
        const char *s = category ? category : "";
        while (s[i] && i < sizeof(low)-1) { low[i] = (char)tolower((unsigned char)s[i]); i++; }
        low[i] = '\0';
        char *t = low; while (*t==' '||*t=='\t') t++;
        snprintf(cat, sizeof(cat), "%s", t);
        for (char *p = cat; *p; p++) if (*p==' '||*p=='\t') { *p = '\0'; break; }
    }
    if (!fb_cat_valid(cat)) snprintf(cat, sizeof(cat), "other");

    char title[FB_TITLE_MAX_SAFE], body[FB_BODY_MAX_SAFE], contact[FB_CONTACT_MAX_SAFE];
    fb_trunc(title_in ? title_in : "", 120, title, sizeof(title));
    fb_trunc(body_in ? body_in : "", 16000, body, sizeof(body));
    fb_trunc(contact_in ? contact_in : "", 120, contact, sizeof(contact));

    if (!title[0] && !body[0]) { pymcl_set_error("请填写标题或内容"); return NULL; }
    if (!title[0]) {
        fb_trunc(body, 80, title, sizeof(title));
        char *nl = strchr(title, '\n'); if (nl) *nl = '\0';
        if (!title[0]) snprintf(title, sizeof(title), "未命名反馈");
    }

    char device[80]; fb_device_id(device, sizeof(device));
    cJSON *payload = cJSON_CreateObject();
    cJSON_AddStringToObject(payload, "device_id", device);
    cJSON_AddStringToObject(payload, "category", cat);
    cJSON_AddStringToObject(payload, "title", title);
    cJSON_AddStringToObject(payload, "body", body);
    cJSON_AddStringToObject(payload, "contact", contact);
    cJSON_AddStringToObject(payload, "app_version", PYMCL_APP_VERSION);
    if (cJSON_IsObject(crash)) cJSON_AddItemToObject(payload, "crash", cJSON_Duplicate(crash, 1));
    else cJSON_AddNullToObject(payload, "crash");
    if (include_sysinfo) cJSON_AddItemToObject(payload, "sysinfo", sysinfo_collect(1, 1, 0));

    cJSON *data = fb_post("/api/v1/feedback", payload, 25);
    cJSON_Delete(payload);
    if (!data) return NULL;

    cJSON *row = cJSON_CreateObject();
    cJSON_AddStringToObject(row, "id", cJSON_GetStringValue(cJSON_GetObjectItem(data, "id")) ? : "");
    cJSON_AddNumberToObject(row, "ts", (double)time(NULL));
    cJSON_AddStringToObject(row, "category", cat);
    cJSON_AddStringToObject(row, "title", title);
    cJSON_AddBoolToObject(row, "ok", 1);
    fb_history_add(row);
    return data;
}

cJSON *rpc_feedback_call(const char *method, cJSON *params, int *handled) {
    if (strcmp(method, "feedback_history") == 0) {
        *handled = 1;
        return fb_history_load();
    }
    if (strcmp(method, "submit_feedback") == 0) {
        *handled = 1;
        cJSON *sysf = cJSON_GetObjectItem(params, "include_sysinfo");
        int inc = cJSON_IsFalse(sysf) ? 0 : 1;
        return fb_submit(pstr(params, "category", ""), pstr(params, "title", ""),
                         pstr(params, "body", ""), pstr(params, "contact", ""), inc, NULL);
    }
    if (strcmp(method, "submit_crash_feedback") == 0) {
        *handled = 1;
        cJSON *report = cJSON_GetObjectItem(params, "report");
        cJSON *own = NULL;
        if (!cJSON_IsObject(report)) report = own = cJSON_CreateObject();

        const char *t = cJSON_GetStringValue(cJSON_GetObjectItem(report, "headline"));
        if (!t || !t[0]) t = cJSON_GetStringValue(cJSON_GetObjectItem(report, "title"));
        if (!t || !t[0]) t = cJSON_GetStringValue(cJSON_GetObjectItem(report, "summary"));
        char title[512];
        snprintf(title, sizeof(title), "%s", (t && t[0]) ? t : "游戏崩溃");
        fb_trunc(title, 120, title, sizeof(title));

        /* body = extra + summary + (detail|output_tail) 用空行拼接，detail 截 8000 */
        char detail[32001]; detail[0] = '\0';
        const char *det = cJSON_GetStringValue(cJSON_GetObjectItem(report, "detail"));
        const char *tail = cJSON_GetStringValue(cJSON_GetObjectItem(report, "output_tail"));
        fb_trunc((tail && tail[0]) ? tail : (det ? det : ""), 8000, detail, sizeof(detail));
        char body[66001]; body[0] = '\0'; size_t off = 0; int any = 0;
        const char *parts[3] = { pstr(params, "extra", ""),
                                 cJSON_GetStringValue(cJSON_GetObjectItem(report, "summary")) ? : "",
                                 detail };
        for (int i = 0; i < 3; i++) {
            char piece[8000];
            fb_trunc(parts[i] ? parts[i] : "", 7900, piece, sizeof(piece));
            for (char *e = piece + strlen(piece);
                 e > piece && (e[-1]=='\r'||e[-1]=='\n'||e[-1]==' '||e[-1]=='\t'); e--) *e = '\0';
            if (!piece[0]) continue;
            if (any && off + 2 < sizeof(body)) { memcpy(body + off, "\n\n", 2); off += 2; }
            size_t pl = strlen(piece), allow = sizeof(body) - 1 - off;
            size_t cp = pl < allow ? pl : allow;
            memcpy(body + off, piece, cp); off += cp; any = 1;
        }
        body[off] = '\0';
        if (!body[0]) snprintf(body, sizeof(body), "%s", title);

        cJSON *crash = cJSON_CreateObject();
        const char *keys[] = { "headline", "summary", "title", "help", "direct_file" };
        for (size_t k = 0; k < sizeof(keys)/sizeof(keys[0]); k++) {
            const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(report, keys[k]));
            cJSON_AddStringToObject(crash, keys[k], v ? v : "");
        }
        cJSON *res = fb_submit("crash", title, body, "", 1, crash);
        cJSON_Delete(crash);
        cJSON_Delete(own);
        return res;
    }
    if (strcmp(method, "submit_crash_report") == 0) {
        *handled = 1;
        /* 与 Python 的 get_crash(task_id) 对位：读内存中的最近一次崩溃；没有就报错 */
        (void)pstr(params, "task_id", "");
        cJSON *report = backend_last_crash();
        if (!cJSON_IsObject(report) || cJSON_GetArraySize(report) == 0) {
            cJSON_Delete(report);
            pymcl_set_error("没有可上传的崩溃报告");
            return NULL;
        }
        cJSON *wrap = cJSON_CreateObject();
        cJSON_AddItemToObject(wrap, "report", report);
        int h2 = 0;
        cJSON *res = rpc_feedback_call("submit_crash_feedback", wrap, &h2);
        cJSON_Delete(wrap);
        if (res) {
            const char *msg = cJSON_GetStringValue(cJSON_GetObjectItem(res, "message"));
            cJSON_Delete(res);
            return cJSON_CreateString(msg && msg[0] ? msg : "已上传");
        }
        return NULL;
    }
    return NULL;
}
