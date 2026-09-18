#include "pymcl.h"
#include <winhttp.h>
#include <pthread.h>

/* MinGW 的 winhttp.h 比 Windows SDK 旧一截，下面这几个常量在老头文件里没有。
   值取自 SDK，运行时不支持的系统上 WinHttpSetOption 只是返回失败，不影响请求。 */
#ifndef WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY
#define WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY 4
#endif
#ifndef WINHTTP_OPTION_ENABLE_HTTP_PROTOCOL
#define WINHTTP_OPTION_ENABLE_HTTP_PROTOCOL 133
#endif
#ifndef WINHTTP_PROTOCOL_FLAG_HTTP2
#define WINHTTP_PROTOCOL_FLAG_HTTP2 0x1
#endif

static pthread_mutex_t g_path_mu = PTHREAD_MUTEX_INITIALIZER;
static char g_locked_paths[64][PYMCL_PATH];
static int g_nlocked;

typedef struct { char *buf; size_t len, cap; } mem_buf;

static int mem_sink(void *ud, const char *data, size_t n) {
    mem_buf *m = (mem_buf *)ud;
    if (m->len + n + 1 > m->cap) {
        size_t nc = (m->len + n + 1) * 2 + 4096;
        char *nb = (char *)realloc(m->buf, nc);
        if (!nb) return -1;
        m->buf = nb; m->cap = nc;
    }
    memcpy(m->buf + m->len, data, n);
    m->len += n;
    m->buf[m->len] = 0;
    return 0;
}

void http_resp_free(http_resp *r) {
    if (!r) return;
    free(r->body);
    r->body = NULL; r->len = 0;
}

static HINTERNET g_session;

int http_init(void) {
    wchar_t *ua = pymcl_u8_to_wide(PYMCL_UA);
    g_session = WinHttpOpen(ua ? ua : L"PyMCL", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                            WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!g_session)
        g_session = WinHttpOpen(ua ? ua : L"PyMCL", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    free(ua);
    if (!g_session) { pymcl_set_error("WinHttpOpen 失败 (%lu)", GetLastError()); return -1; }
    DWORD proto = WINHTTP_PROTOCOL_FLAG_HTTP2;
    WinHttpSetOption(g_session, WINHTTP_OPTION_ENABLE_HTTP_PROTOCOL, &proto, sizeof(proto));
    return 0;
}

void http_shutdown(void) {
    if (g_session) { WinHttpCloseHandle(g_session); g_session = NULL; }
}

/* WinHTTP 的错误码落在 12000 段，FormatMessage 要去 winhttp.dll 里取表，
   不是默认的系统消息表。 */
static void set_winhttp_error(const char *what, const char *url) {
    DWORD e = GetLastError();
    wchar_t *msg = NULL;
    HMODULE mod = GetModuleHandleW(L"winhttp.dll");
    DWORD n = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_HMODULE |
                             FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                             mod, e, 0, (wchar_t *)&msg, 0, NULL);
    char *u8 = (n && msg) ? pymcl_wide_to_u8(msg) : NULL;
    if (u8) {
        for (char *p = u8; *p; p++) if (*p == '\r' || *p == '\n') *p = ' ';
        pymcl_set_error("%s %s: %s (%lu)", what, url ? url : "", u8, e);
    } else {
        pymcl_set_error("%s %s: WinHTTP 错误 %lu", what, url ? url : "", e);
    }
    free(u8);
    if (msg) LocalFree(msg);
}

typedef struct {
    wchar_t host[512];
    wchar_t path[8192];
    INTERNET_PORT port;
    int secure;
} url_parts;

static int parse_url(const char *url, url_parts *up) {
    memset(up, 0, sizeof(*up));
    wchar_t *w = pymcl_u8_to_wide(url);
    if (!w) return -1;
    wchar_t extra[4096];
    URL_COMPONENTSW uc;
    memset(&uc, 0, sizeof(uc));
    uc.dwStructSize = sizeof(uc);
    uc.lpszHostName = up->host;   uc.dwHostNameLength = 512;
    uc.lpszUrlPath = up->path;    uc.dwUrlPathLength = 6144;
    uc.lpszExtraInfo = extra;     uc.dwExtraInfoLength = 4096;
    if (!WinHttpCrackUrl(w, 0, ICU_ESCAPE, &uc)) { free(w); return -1; }
    free(w);
    if (uc.dwExtraInfoLength) wcsncat(up->path, extra, 8191 - wcslen(up->path));
    if (!up->path[0]) wcscpy(up->path, L"/");
    up->port = uc.nPort;
    up->secure = (uc.nScheme == INTERNET_SCHEME_HTTPS);
    return 0;
}

/* 入参里的额外头是 '\n' 分隔的，WinHTTP 要 CRLF。 */
static wchar_t *join_headers(const char *extra_hdr) {
    size_t cap = (extra_hdr ? strlen(extra_hdr) : 0) * 2 + 128;
    char *acc = (char *)calloc(1, cap);
    if (!acc) return NULL;
    size_t at = 0;
    at += (size_t)snprintf(acc + at, cap - at, "Accept-Encoding: identity\r\n");
    const char *p = extra_hdr;
    while (p && *p) {
        const char *nl = strchr(p, '\n');
        size_t n = nl ? (size_t)(nl - p) : strlen(p);
        while (n && (p[n - 1] == '\r' || p[n - 1] == ' ')) n--;
        if (n && at + n + 3 < cap) {
            memcpy(acc + at, p, n); at += n;
            acc[at++] = '\r'; acc[at++] = '\n'; acc[at] = 0;
        }
        p = nl ? nl + 1 : p + strlen(p);
    }
    wchar_t *w = pymcl_u8_to_wide(acc);
    free(acc);
    return w;
}

typedef int (*sink_fn)(void *ud, const char *data, size_t n);

/* 传输层成功就回 0（4xx/5xx 也算成功，状态码交给调用方判断），连不上才回 -1。 */
static int http_request(const char *verb, const char *url,
                        const void *body, size_t bodylen,
                        const char *extra_hdr, int timeout,
                        sink_fn sink, void *sink_ud,
                        int *out_status, long long *out_clen) {
    if (out_status) *out_status = 0;
    if (out_clen) *out_clen = -1;
    if (!g_session && http_init() != 0) return -1;

    url_parts up;
    if (parse_url(url, &up) != 0) { pymcl_set_error("URL 无法解析: %s", url); return -1; }

    HINTERNET conn = WinHttpConnect(g_session, up.host, up.port, 0);
    if (!conn) { set_winhttp_error("连接失败", url); return -1; }

    wchar_t *wverb = pymcl_u8_to_wide(verb);
    HINTERNET req = WinHttpOpenRequest(conn, wverb, up.path, NULL, WINHTTP_NO_REFERER,
                                       WINHTTP_DEFAULT_ACCEPT_TYPES,
                                       up.secure ? WINHTTP_FLAG_SECURE : 0);
    free(wverb);
    if (!req) { set_winhttp_error("请求创建失败", url); WinHttpCloseHandle(conn); return -1; }

    int secs = timeout > 0 ? timeout : 60;
    WinHttpSetTimeouts(req, 20000, 20000, secs * 1000, secs * 1000);
    DWORD policy = WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS;
    WinHttpSetOption(req, WINHTTP_OPTION_REDIRECT_POLICY, &policy, sizeof(policy));
    DWORD maxred = 8;
    WinHttpSetOption(req, WINHTTP_OPTION_MAX_HTTP_AUTOMATIC_REDIRECTS, &maxred, sizeof(maxred));

    wchar_t *hdrs = join_headers(extra_hdr);
    BOOL ok = WinHttpSendRequest(req, hdrs ? hdrs : WINHTTP_NO_ADDITIONAL_HEADERS,
                                 hdrs ? (DWORD)-1 : 0,
                                 (LPVOID)body, (DWORD)bodylen, (DWORD)bodylen, 0);
    free(hdrs);
    if (!ok || !WinHttpReceiveResponse(req, NULL)) {
        set_winhttp_error("HTTP 失败", url);
        WinHttpCloseHandle(req); WinHttpCloseHandle(conn);
        return -1;
    }

    DWORD code = 0, sz = sizeof(code);
    WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &code, &sz, WINHTTP_NO_HEADER_INDEX);
    if (out_status) *out_status = (int)code;

    wchar_t clbuf[64]; sz = sizeof(clbuf);
    if (WinHttpQueryHeaders(req, WINHTTP_QUERY_CONTENT_LENGTH, WINHTTP_HEADER_NAME_BY_INDEX,
                            clbuf, &sz, WINHTTP_NO_HEADER_INDEX)) {
        if (out_clen) *out_clen = _wtoi64(clbuf);
    }

    int rc = 0;
    char *buf = (char *)malloc(65536);
    if (!buf) rc = -1;
    while (rc == 0) {
        DWORD got = 0;
        if (!WinHttpReadData(req, buf, 65536, &got)) { set_winhttp_error("读取失败", url); rc = -1; break; }
        if (got == 0) break;
        if (sink && sink(sink_ud, buf, got) != 0) { rc = -1; break; }
    }
    free(buf);
    WinHttpCloseHandle(req);
    WinHttpCloseHandle(conn);
    return rc;
}

static int do_get(const char *url, http_resp *r, const char *extra, int timeout) {
    memset(r, 0, sizeof(*r));
    mem_buf m = {0};
    int code = 0; long long cl = -1;
    int rc = http_request("GET", url, NULL, 0, extra, timeout, mem_sink, &m, &code, &cl);
    r->status = code;
    r->body = m.buf;
    r->len = m.len;
    r->content_length = cl;
    if (rc != 0) return -1;
    if (code >= 400) {
        pymcl_set_error("HTTP %d: %s", code, url);
        return -1;
    }
    return 0;
}

int http_get(const char *url, http_resp *r, const char *extra_hdr, int timeout) {
    return do_get(url, r, extra_hdr, timeout);
}

int http_get_query(const char *url, const char *query, http_resp *r, const char *extra_hdr, int timeout) {
    if (!query || !query[0]) return http_get(url, r, extra_hdr, timeout);
    char full[4096];
    snprintf(full, sizeof(full), "%s%s%s", url, strchr(url, '?') ? "&" : "?", query);
    return http_get(full, r, extra_hdr, timeout);
}

int http_post_form(const char *url, const char *form, http_resp *r, int timeout) {
    memset(r, 0, sizeof(*r));
    mem_buf m = {0};
    int code = 0;
    int rc = http_request("POST", url, form, form ? strlen(form) : 0,
                          "Content-Type: application/x-www-form-urlencoded",
                          timeout, mem_sink, &m, &code, NULL);
    r->status = code;
    r->body = m.buf;
    r->len = m.len;
    return rc;
}

int http_post_json(const char *url, const char *json, http_resp *r, const char *extra_hdr, int timeout) {
    memset(r, 0, sizeof(*r));
    mem_buf m = {0};
    char hdrs[2048];
    snprintf(hdrs, sizeof(hdrs), "Content-Type: application/json\n%s", extra_hdr ? extra_hdr : "");
    int code = 0;
    int rc = http_request("POST", url, json, json ? strlen(json) : 0, hdrs, timeout,
                          mem_sink, &m, &code, NULL);
    r->status = code;
    r->body = m.buf;
    r->len = m.len;
    if (rc != 0) return -1;
    if (code >= 400) { pymcl_set_error("HTTP %d: %s", code, url); return -1; }
    return 0;
}

cJSON *http_get_json(const char *url, int timeout) {
    return http_get_json_hdr(url, NULL, timeout);
}
cJSON *http_get_json_hdr(const char *url, const char *extra_hdr, int timeout) {
    http_resp r;
    if (http_get(url, &r, extra_hdr, timeout) != 0) { http_resp_free(&r); return NULL; }
    cJSON *j = cJSON_Parse(r.body ? r.body : "{}");
    http_resp_free(&r);
    return j;
}

static int is_github(const char *u) {
    return u && (strstr(u, "github.com") || strstr(u, "githubusercontent.com"));
}

int expand_urls(const char *url, char ***out, int *n) {
    *out = NULL; *n = 0;
    if (!url || !url[0]) return 0;
    char tmp[16][PYMCL_PATH];
    int c = 0;
    if (is_github(url)) {
        static const char *px[] = {
            "https://gitproxy.mrhjx.cn/", "https://ghproxy.vip/",
            "https://gh-proxy.com/", "https://v6.gh-proxy.org/", "https://cdn.gh-proxy.com/",
        };
        for (int i = 0; i < 5; i++) {
            snprintf(tmp[c], sizeof(tmp[c]), "%s%s", px[i], url);
            c++;
        }
        snprintf(tmp[c++], sizeof(tmp[0]), "%s", url);
    } else {
        struct { const char *off, *mir; } mv[] = {
            {"https://maven.minecraftforge.net/", BMCLAPI "/maven/"},
            {"https://files.minecraftforge.net/maven/", BMCLAPI "/maven/"},
            {"https://maven.neoforged.net/releases/", BMCLAPI "/maven/"},
            {"https://libraries.minecraft.net/", BMCLAPI "/maven/"},
        };
        int hit = 0;
        for (int i = 0; i < 4; i++) {
            size_t L = strlen(mv[i].off);
            if (strncmp(url, mv[i].off, L) == 0) {
                snprintf(tmp[c++], sizeof(tmp[0]), "%s%s", mv[i].mir, url + L);
                snprintf(tmp[c++], sizeof(tmp[0]), "%s", url);
                hit = 1;
                break;
            }
        }
        if (!hit) snprintf(tmp[c++], sizeof(tmp[0]), "%s", url);
    }
    *out = (char **)calloc((size_t)c, sizeof(char *));
    for (int i = 0; i < c; i++) (*out)[i] = pymcl_strdup(tmp[i]);
    *n = c;
    return 0;
}
void free_urls(char **u, int n) {
    if (!u) return;
    for (int i = 0; i < n; i++) free(u[i]);
    free(u);
}

static void cf_headers(const char *url, char *out, size_t n) {
    out[0] = 0;
    if (url && (strstr(url, "api.curseforge.com") || strstr(url, "/curseforge/v1/"))) {
        const char *key = config_str("curseforge_api_key", "");
        if (key && key[0]) snprintf(out, n, "x-api-key: %s", key);
    }
}

typedef struct {
    FILE *f;
    long long got, expected;
    pymcl_ctx *ctx;
    const char *name;
    DWORD last;
} dl_state;

static int dl_sink(void *ud, const char *data, size_t n) {
    dl_state *s = (dl_state *)ud;
    if (fwrite(data, 1, n, s->f) != n) return -1;
    s->got += (long long)n;
    if (s->ctx && s->ctx->on_progress) {
        DWORD now = GetTickCount();
        if (now - s->last > 150) {
            s->last = now;
            char msg[256];
            snprintf(msg, sizeof(msg), "下载中 %s", s->name ? s->name : "");
            s->ctx->on_progress(s->ctx->ud, msg, s->got, s->expected);
        }
    }
    if (s->ctx && s->ctx->cancel && s->ctx->cancel(s->ctx->ud)) return -1;
    return 0;
}

int http_download_one(const char *url, const char *dest, pymcl_ctx *ctx,
                      const char *sha1, long long size, const char *sha512, int timeout) {
    char parent[PYMCL_PATH];
    pymcl_parent(dest, parent, sizeof(parent));
    pymcl_ensure_dir(parent);
    char part[PYMCL_PATH];
    snprintf(part, sizeof(part), "%s.part", dest);
    wchar_t *w = pymcl_u8_to_wide(part);
    FILE *f = w ? _wfopen(w, L"wb") : NULL;
    free(w);
    if (!f) { pymcl_set_error("无法写入 %s", part); return -1; }
    char extra[512];
    cf_headers(url, extra, sizeof(extra));
    dl_state st = { f, 0, size, ctx, pymcl_basename(dest), 0 };
    int code = 0; long long cl = -1;
    int rc = http_request("GET", url, NULL, 0, extra[0] ? extra : NULL,
                          timeout > 0 ? timeout : 300, dl_sink, &st, &code, &cl);
    fclose(f);
    if (rc != 0 || code >= 400) {
        pymcl_remove_tree(part);
        if (code >= 400) pymcl_set_error("HTTP %d: %s", code, url);
        return -1;
    }
    if (cl > 0 && st.got != cl) {
        pymcl_remove_tree(part);
        pymcl_set_error("下载不完整 %s (%lld/%lld)", url, st.got, cl);
        return -1;
    }
    if (!pymcl_file_matches(part, sha1, size >= 0 ? size : -1)) {
        pymcl_remove_tree(part);
        pymcl_set_error("校验失败: %s", url);
        return -1;
    }
    if (sha512 && sha512[0]) {
        char hex[129];
        if (pymcl_sha512_file(part, hex) != 0 || _stricmp(hex, sha512) != 0) {
            pymcl_remove_tree(part);
            pymcl_set_error("sha512 校验失败: %s", url);
            return -1;
        }
    }
    wchar_t *wp = pymcl_u8_to_wide(part);
    wchar_t *wd = pymcl_u8_to_wide(dest);
    DeleteFileW(wd);
    BOOL ok = MoveFileW(wp, wd);
    free(wp); free(wd);
    if (!ok) { pymcl_set_error("无法重命名 %s", dest); return -1; }
    return 0;
}

int download_file(const char *url, const char **extra, int nextra, const char *dest,
                  pymcl_ctx *ctx, const char *sha1, long long size, const char *sha512) {
    if (pymcl_file_matches(dest, sha1, size >= 0 ? size : -1)) {
        if (!sha512 || !sha512[0]) return 0;
        char hex[129];
        if (pymcl_sha512_file(dest, hex) == 0 && _stricmp(hex, sha512) == 0) return 0;
    }
    char **cands = NULL; int nc = 0;
    expand_urls(url, &cands, &nc);
    for (int i = 0; i < nextra; i++) {
        char **more = NULL; int nm = 0;
        expand_urls(extra[i], &more, &nm);
        cands = (char **)realloc(cands, sizeof(char *) * (size_t)(nc + nm));
        for (int j = 0; j < nm; j++) cands[nc++] = more[j];
        free(more);
    }
    int last = -1;
    for (int i = 0; i < nc; i++) {
        if (ctx && ctx->cancel && ctx->cancel(ctx->ud)) {
            pymcl_set_error("用户取消");
            free_urls(cands, nc);
            return -1;
        }
        if (http_download_one(cands[i], dest, ctx, sha1, size, sha512, 300) == 0) {
            free_urls(cands, nc);
            return 0;
        }
        last = -1;
    }
    free_urls(cands, nc);
    return last;
}

typedef struct {
    cJSON *task;
    pymcl_ctx *ctx;
    int ok;
    char err[256];
} dl_job;

static void *dl_worker(void *p) {
    dl_job *j = (dl_job *)p;
    cJSON *t = j->task;
    const char *dest = cJSON_GetStringValue(cJSON_GetObjectItem(t, "dest"));
    const char *sha1 = cJSON_GetStringValue(cJSON_GetObjectItem(t, "sha1"));
    const char *sha512 = cJSON_GetStringValue(cJSON_GetObjectItem(t, "sha512"));
    long long size = -1;
    cJSON *sz = cJSON_GetObjectItem(t, "size");
    if (cJSON_IsNumber(sz)) size = (long long)sz->valuedouble;
    cJSON *urls = cJSON_GetObjectItem(t, "urls");
    const char *first = NULL;
    const char *extras[32]; int ne = 0;
    if (cJSON_IsArray(urls) && cJSON_GetArraySize(urls) > 0) {
        first = cJSON_GetArrayItem(urls, 0)->valuestring;
        for (int i = 1; i < cJSON_GetArraySize(urls) && ne < 32; i++)
            extras[ne++] = cJSON_GetArrayItem(urls, i)->valuestring;
    } else {
        first = cJSON_GetStringValue(cJSON_GetObjectItem(t, "url"));
    }
    if (download_file(first, extras, ne, dest, j->ctx, sha1, size, sha512) != 0) {
        j->ok = 0;
        snprintf(j->err, sizeof(j->err), "%s: %s", pymcl_basename(dest), pymcl_error());
    } else j->ok = 1;
    return NULL;
}

int download_all(cJSON *tasks, const char *message, pymcl_ctx *ctx) {
    if (!cJSON_IsArray(tasks)) return 0;
    int n = cJSON_GetArraySize(tasks);
    if (n == 0) return 0;
    int threads = ctx && ctx->threads > 0 ? ctx->threads : config_int("download_threads", 8);
    if (threads > 16) threads = 16;
    int done = 0, fail = 0;
    char first_err[256] = {0};
    for (int i = 0; i < n; ) {
        int batch = n - i; if (batch > threads) batch = threads;
        pthread_t th[16];
        dl_job jobs[16];
        for (int k = 0; k < batch; k++) {
            memset(&jobs[k], 0, sizeof(jobs[k]));
            jobs[k].task = cJSON_GetArrayItem(tasks, i + k);
            jobs[k].ctx = ctx;
            pthread_create(&th[k], NULL, dl_worker, &jobs[k]);
        }
        for (int k = 0; k < batch; k++) {
            pthread_join(th[k], NULL);
            if (!jobs[k].ok) {
                fail++;
                if (!first_err[0]) snprintf(first_err, sizeof(first_err), "%s", jobs[k].err);
            }
            done++;
            if (ctx && ctx->on_progress)
                ctx->on_progress(ctx->ud, message ? message : "下载中", done, n);
        }
        i += batch;
        if (ctx && ctx->cancel && ctx->cancel(ctx->ud)) {
            pymcl_set_error("用户取消");
            return -1;
        }
    }
    if (fail) {
        pymcl_set_error("%s失败（%d/%d 个文件）: %s", message ? message : "下载", fail, n, first_err);
        return -1;
    }
    return 0;
}

cJSON *fetch_json_mirrors(const char **urls, int n, int timeout) {
    for (int i = 0; i < n; i++) {
        char **exp = NULL; int ne = 0;
        expand_urls(urls[i], &exp, &ne);
        for (int j = 0; j < ne; j++) {
            cJSON *o = http_get_json(exp[j], timeout);
            if (o) { free_urls(exp, ne); return o; }
        }
        free_urls(exp, ne);
    }
    return NULL;
}
char *fetch_text_mirrors(const char **urls, int n, int timeout) {
    for (int i = 0; i < n; i++) {
        char **exp = NULL; int ne = 0;
        expand_urls(urls[i], &exp, &ne);
        for (int j = 0; j < ne; j++) {
            http_resp r;
            if (http_get(exp[j], &r, NULL, timeout) == 0 && r.body) {
                free_urls(exp, ne);
                return r.body; /* caller frees */
            }
            http_resp_free(&r);
        }
        free_urls(exp, ne);
    }
    return NULL;
}
