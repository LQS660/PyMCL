#include "pymcl.h"
#include <winsock2.h>
#include <ws2tcpip.h>
#include <pthread.h>

#pragma comment(lib, "ws2_32.lib")

#define TOKEN_MAX 256
#define MAX_REQUEST_BYTES (4 * 1024 * 1024)

typedef struct sse_cli {
    SOCKET s;
    int alive;          /* 0 = 已摘链 / 已判死，等 refs 归零就 free */
    int refs;           /* in-flight 的 sse_emit 引用数 */
    struct sse_cli *next;
} sse_cli;

static sse_cli *g_sse;
static pthread_mutex_t g_sse_mu = PTHREAD_MUTEX_INITIALIZER;
static SOCKET g_listen = INVALID_SOCKET;
static char g_token[TOKEN_MAX];
static int g_port;

static int send_all(SOCKET s, const char *p, int n);
static void send_error(SOCKET s, int code, const char *message);

/* Origin 只放行 loopback 页面。审计 2026-09-28 P2-3：旧实现是纯前缀匹配 ——
     strncmp(origin, "http://localhost", 16) == 0
   于是攻击者可控的 http://localhost.evil.com / http://127.0.0.1.evil.com 也放行
   （前缀相同，后面的域名从没被看过）。这里改成解析出 authority 里的 host 再**精确**
   比较，任何后缀都不认：
     http://<host>[:port][/...]
   · host 必须恰好是 127.0.0.1 / localhost / [::1]（host 大小写不敏感；裸 ::1 也收）
   · 有端口时端口必须是纯数字（不校验范围：这一层只需确认它确实是端口，不是域名的一部分）
   · authority 里不允许出现 '@'（http://localhost@evil.com 这类 userinfo 混淆）
   · scheme 只认 http，与 Python 参考实现 bridge/server.py 的 _normalize_origin 一致
     （旧实现同样只认 http，https://localhost 在改前改后都是拒绝）
   注意：C 桥全程不发 Access-Control-Allow-Origin，所以这一层是纵深防御，
   真正的跨域读仍被浏览器同源策略挡住。 */
static int origin_is_loopback(const char *origin) {
    if (!origin || !*origin) return 0;
    const char *p = strstr(origin, "://");
    if (!p) return 0;
    if ((size_t)(p - origin) != 4 || _strnicmp(origin, "http", 4) != 0) return 0;
    const char *auth = p + 3;
    const char *end = auth;
    while (*end && *end != '/' && *end != '?' && *end != '#') end++;
    size_t alen = (size_t)(end - auth);
    if (alen == 0) return 0;
    if (memchr(auth, '@', alen)) return 0;                 /* userinfo 混淆一律拒绝 */
    if (alen == 3 && memcmp(auth, "::1", 3) == 0) return 1; /* 裸 ::1（无端口形态） */
    const char *host = auth, *host_end = auth;
    if (*host == '[') {
        const char *close = (const char *)memchr(host, ']', alen);
        if (!close) return 0;
        host_end = close + 1;                              /* host 含方括号：[::1] */
        if (host_end < end && *host_end != ':') return 0;   /* ']' 之后只能是端口或结束 */
    } else {
        while (host_end < end && *host_end != ':') host_end++;
    }
    size_t hlen = (size_t)(host_end - host);
    int host_ok = (hlen == 9 && _strnicmp(host, "127.0.0.1", 9) == 0)
               || (hlen == 9 && _strnicmp(host, "localhost", 9) == 0)
               || (hlen == 5 && memcmp(host, "[::1]", 5) == 0);
    if (!host_ok) return 0;
    if (host_end < end && *host_end == ':') {               /* 端口必须是纯数字 */
        const char *d = host_end + 1;
        if (d == end) return 0;                             /* "http://localhost:" 不是合法 origin */
        for (; d < end; d++) if (*d < '0' || *d > '9') return 0;
    }
    return 1;
}

static const char *mime_for(const char *path) {
    const char *dot = strrchr(path, '.');
    if (!dot) return NULL;   /* 无后缀：不认，见 www_asset_ok */
    if (pymcl_ieq(dot, ".html") || pymcl_ieq(dot, ".htm")) return "text/html; charset=utf-8";
    if (pymcl_ieq(dot, ".js") || pymcl_ieq(dot, ".mjs")) return "application/javascript; charset=utf-8";
    if (pymcl_ieq(dot, ".css")) return "text/css; charset=utf-8";
    if (pymcl_ieq(dot, ".json")) return "application/json; charset=utf-8";
    if (pymcl_ieq(dot, ".svg")) return "image/svg+xml";
    if (pymcl_ieq(dot, ".png")) return "image/png";
    if (pymcl_ieq(dot, ".jpg") || pymcl_ieq(dot, ".jpeg")) return "image/jpeg";
    if (pymcl_ieq(dot, ".gif")) return "image/gif";
    if (pymcl_ieq(dot, ".webp")) return "image/webp";
    if (pymcl_ieq(dot, ".ico")) return "image/x-icon";
    if (pymcl_ieq(dot, ".woff2")) return "font/woff2";
    if (pymcl_ieq(dot, ".woff")) return "font/woff";
    if (pymcl_ieq(dot, ".ttf")) return "font/ttf";
    if (pymcl_ieq(dot, ".txt")) return "text/plain; charset=utf-8";
    if (pymcl_ieq(dot, ".map")) return "application/json";
    return NULL;
}

/* 静态资源只放行「UI 会用到的那几种后缀」：www/ 里除了前端产物本来也没有别的东西，
   但这一层白名单让「万一有东西被写进 www/」也不会被原样吐出去。返回 0 = 不是 UI 资源。 */
static int www_asset_ok(const char *rel) {
    return mime_for(rel) != NULL;
}

/* url_path → www/ 下的相对路径。旧版只挡 ".." 和 "\"，盘符 / UNC 绝对路径能整体替换
   调用方的 www 前缀（pymcl_path_join 见到 "C:/..." 就丢掉 a），实测
   `GET /C:/Windows/win.ini` 把系统文件原样返回、且不需要 token。 */
static int safe_rel_path(const char *url_path, char *out, size_t n) {
    if (!url_path || url_path[0] != '/') return -1;
    const char *p = url_path + 1;
    if (!*p || strcmp(p, "/") == 0) p = "index.html";
    if (strstr(p, "..") || strchr(p, '\\')) return -1;
    if (p[0] == '/' || p[0] == '\\') return -1;                 /* 前导斜杠 / UNC */
    if (strchr(p, ':')) return -1;                              /* 盘符或 NTFS 数据流 */
    if (isalpha((unsigned char)p[0]) && p[1] == ':') return -1;
    snprintf(out, n, "%s", p);
    for (char *c = out; *c; c++) if (*c == '/') *c = '\\';
    return 0;
}

/* 规范化后确认 child 仍在 base 之下（纵深防御：rel 已经过滤过一遍，这里防 base 自身
   含 .. 或符号链接的情况）。 */
static int within_dir(const char *base, const char *child) {
    wchar_t wb[PYMCL_PATH], wc[PYMCL_PATH];
    wchar_t *ub = pymcl_u8_to_wide(base), *uc = pymcl_u8_to_wide(child);
    if (!ub || !uc) { free(ub); free(uc); return 0; }
    DWORD nb = GetFullPathNameW(ub, PYMCL_PATH, wb, NULL);
    DWORD nc = GetFullPathNameW(uc, PYMCL_PATH, wc, NULL);
    free(ub); free(uc);
    if (!nb || nb >= PYMCL_PATH || !nc || nc >= PYMCL_PATH) return 0;
    size_t lb = wcslen(wb);
    while (lb > 0 && (wb[lb - 1] == L'\\' || wb[lb - 1] == L'/')) wb[--lb] = 0;
    if (_wcsnicmp(wc, wb, lb) != 0) return 0;
    return wc[lb] == L'\\' || wc[lb] == L'/';
}

static int send_file(SOCKET s, const char *fs_path, const char *mime) {
    char *data = NULL;
    size_t len = 0;
    if (pymcl_read_file(fs_path, &data, &len) != 0 || !data) {
        send_error(s, 404, "not found");
        return -1;
    }
    char hdr[320];
    int n = snprintf(hdr, sizeof(hdr),
        "HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %zu\r\n"
        "Cache-Control: no-cache\r\nConnection: close\r\n\r\n",
        mime ? mime : "application/octet-stream", len);
    send_all(s, hdr, n);
    send_all(s, data, (int)len);
    free(data);
    return 0;
}

static int try_serve_www(SOCKET s, const char *url_path) {
    char rel[260], full[PYMCL_PATH], www[PYMCL_PATH];
    if (safe_rel_path(url_path, rel, sizeof(rel)) != 0) return -1;
    pymcl_path_join(www, sizeof(www), g_root, "www");
    if (!pymcl_dir_exists(www)) return -1;
    pymcl_path_join(full, sizeof(full), www, rel);
    if (!within_dir(www, full)) return -1;
    if (!pymcl_file_exists(full)) {
        /* SPA fallback */
        if (strchr(rel, '.') == NULL) {
            pymcl_path_join(full, sizeof(full), www, "index.html");
            if (pymcl_file_exists(full))
                return send_file(s, full, "text/html; charset=utf-8");
        }
        return -1;
    }
    if (!www_asset_ok(rel)) return -1;
    return send_file(s, full, mime_for(rel));
}

static void sse_add(SOCKET s) {
    sse_cli *c = (sse_cli *)calloc(1, sizeof(*c));
    if (!c) return;
    c->s = s;
    c->alive = 1;
    pthread_mutex_lock(&g_sse_mu);
    c->next = g_sse;
    g_sse = c;
    pthread_mutex_unlock(&g_sse_mu);
}

/* 客户端线程退出时调用：从链表摘掉并标记死亡。还有 in-flight 的 sse_emit 引用它
   （refs > 0）就先留着，等那个 emit 释放最后一份引用时再 free。 */
static void sse_remove(SOCKET s) {
    pthread_mutex_lock(&g_sse_mu);
    sse_cli **pp = &g_sse;
    while (*pp) {
        if ((*pp)->s == s) {
            sse_cli *d = *pp;
            d->alive = 0;
            *pp = d->next;
            if (d->refs == 0) free(d);
            break;
        }
        pp = &(*pp)->next;
    }
    pthread_mutex_unlock(&g_sse_mu);
}

/* 事件广播。旧版在 g_sse_mu 里直接 send()，而 send 是阻塞的、全进程又没设过
   SO_SNDTIMEO：一个连上 /events 却不读数据的客户端就能把锁一直占住，所有 emit
   的线程（任务进度 / AI 事件 / finish_task）全部挂起。现在锁内只做引用计数快照，
   send 全在锁外；socket 超时由 client_th 的 SO_SNDTIMEO 兜底，失败就标死。 */
static void sse_emit(const char *event, cJSON *data) {
    char *js = cJSON_PrintUnformatted(data ? data : cJSON_CreateObject());
    size_t need = (js ? strlen(js) : 2) + 64;
    char *buf = (char *)malloc(need);
    if (!buf) { cJSON_free(js); return; }
    int n = snprintf(buf, need, "event: %s\ndata: %s\n\n", event ? event : "message", js ? js : "{}");
    cJSON_free(js);
    sse_cli *snap[64];
    int ns = 0;
    pthread_mutex_lock(&g_sse_mu);
    for (sse_cli *c = g_sse; c && ns < 64; c = c->next) {
        c->refs++;
        snap[ns++] = c;
    }
    pthread_mutex_unlock(&g_sse_mu);
    for (int i = 0; i < ns; i++) {
        if (send(snap[i]->s, buf, n, 0) <= 0) snap[i]->alive = 0;
    }
    pthread_mutex_lock(&g_sse_mu);
    for (int i = 0; i < ns; i++) {
        if (--snap[i]->refs == 0 && !snap[i]->alive) free(snap[i]);
    }
    pthread_mutex_unlock(&g_sse_mu);
    free(buf);
}

static int send_all(SOCKET s, const char *p, int n) {
    int o = 0;
    while (o < n) {
        int r = send(s, p + o, n - o, 0);
        if (r <= 0) return -1;
        o += r;
    }
    return 0;
}

static void send_resp(SOCKET s, int code, const char *ctype, const char *body, int blen) {
    char hdr[512];
    int n = snprintf(hdr, sizeof(hdr),
        "HTTP/1.1 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\n\r\n",
        code, ctype, blen);
    send_all(s, hdr, n);
    if (body && blen) send_all(s, body, blen);
}

/* cJSON 的字符串不能含 NUL，而 AI 权限规则的 key 是 "工具\0内容"（与 Python 一致）。
   进出桥时把 JSON 里的 \u0000 与 \u001f 互换，内部一律用 0x1F 当分隔符。 */
static void swap_escape(char *js, const char *from, const char *to) {
    if (!js) return;
    for (char *p = strstr(js, from); p; p = strstr(p + 6, from)) memcpy(p, to, 6);
}

static void send_json(SOCKET s, int code, cJSON *obj) {
    char *js = cJSON_PrintUnformatted(obj);
    swap_escape(js, "\\u001f", "\\u0000");
    send_resp(s, code, "application/json; charset=utf-8", js, js ? (int)strlen(js) : 0);
    cJSON_free(js);
}

static void send_error(SOCKET s, int code, const char *message) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "error", message);
    send_json(s, code, o);
    cJSON_Delete(o);
}

static int header_value(const char *req, const char *name, char *out, size_t cap) {
    if (!req || !name || !out || cap == 0) return 0;
    out[0] = 0;
    size_t nlen = strlen(name);
    const char *p = strstr(req, "\r\n");
    if (!p) return 0;
    p += 2;
    while (p[0] && !(p[0] == '\r' && p[1] == '\n')) {
        const char *end = strstr(p, "\r\n");
        if (!end) return 0;
        const char *colon = memchr(p, ':', (size_t)(end - p));
        if (colon && (size_t)(colon - p) == nlen && _strnicmp(p, name, nlen) == 0) {
            const char *value = colon + 1;
            while (value < end && (*value == ' ' || *value == '\t')) value++;
            size_t len = (size_t)(end - value);
            while (len > 0 && (value[len - 1] == ' ' || value[len - 1] == '\t')) len--;
            if (len >= cap) return 0;
            memcpy(out, value, len);
            out[len] = 0;
            return 1;
        }
        p = end + 2;
    }
    return 0;
}

static int content_length(const char *req, int *out) {
    char text[32];
    if (!header_value(req, "Content-Length", text, sizeof(text))) {
        *out = 0;
        return 0;
    }
    char *end = NULL;
    long value = strtol(text, &end, 10);
    if (!end || *end || value < 0 || value > MAX_REQUEST_BYTES) return -1;
    *out = (int)value;
    return 0;
}

static int recv_req(SOCKET s, char **out, int *len) {
    char *buf = (char *)malloc(65536);
    if (!buf) return -1;
    int n = 0, cap = 65536;
    for (;;) {
        int r = recv(s, buf + n, cap - n - 1, 0);
        if (r <= 0) { free(buf); return -1; }
        n += r; buf[n] = 0;
        char *hdrend = strstr(buf, "\r\n\r\n");
        if (hdrend) {
            int hlen = (int)(hdrend - buf + 4), cl = 0;
            if (content_length(buf, &cl) != 0) { free(buf); return -1; }
            if (hlen > MAX_REQUEST_BYTES || cl > MAX_REQUEST_BYTES - hlen) { free(buf); return -1; }
            while (n < hlen + cl) {
                if (n + 4096 > cap) {
                    int next = cap * 2;
                    if (next > MAX_REQUEST_BYTES + hlen + 1) next = MAX_REQUEST_BYTES + hlen + 1;
                    char *grown = (char *)realloc(buf, (size_t)next);
                    if (!grown) { free(buf); return -1; }
                    buf = grown; cap = next;
                }
                r = recv(s, buf + n, cap - n - 1, 0);
                if (r <= 0) { free(buf); return -1; }
                n += r;
            }
            buf[n] = 0;
            *out = buf; *len = n;
            return 0;
        }
        if (n + 1024 > cap) {
            int next = cap * 2;
            if (next > MAX_REQUEST_BYTES) { free(buf); return -1; }
            char *grown = (char *)realloc(buf, (size_t)next);
            if (!grown) { free(buf); return -1; }
            buf = grown; cap = next;
        }
    }
}

static int query_token(const char *target, char *out, size_t cap) {
    const char *p = strchr(target, '?');
    if (!p || !*++p) return 0;
    while (*p) {
        const char *end = strchr(p, '&');
        if (!end) end = p + strlen(p);
        if ((size_t)(end - p) > 6 && strncmp(p, "token=", 6) == 0) {
            size_t len = (size_t)(end - (p + 6));
            if (len == 0 || len >= cap) return 0;
            memcpy(out, p + 6, len);
            out[len] = 0;
            return 1;
        }
        if (!*end) break;
        p = end + 1;
    }
    return 0;
}

static int token_equal(const char *value) {
    size_t expected = strlen(g_token);
    if (!value || strlen(value) != expected) return 0;
    unsigned char diff = 0;
    for (size_t i = 0; i < expected; i++) diff |= (unsigned char)(value[i] ^ g_token[i]);
    return diff == 0;
}

static int authenticated(const char *req, const char *target, int allow_query_token) {
    char value[TOKEN_MAX] = {0};
    if (!header_value(req, "X-PyMCL-Bridge-Token", value, sizeof(value)) && allow_query_token)
        query_token(target, value, sizeof(value));
    return token_equal(value);
}

static int has_browser_origin(const char *req) {
    char origin[256];
    return header_value(req, "Origin", origin, sizeof(origin)) && origin[0];
}

static void handle_rpc(SOCKET s, const char *body) {
    char *copy = pymcl_strdup(body ? body : "{}");
    swap_escape(copy, "\\u0000", "\\u001f");
    cJSON *req = cJSON_Parse(copy);
    free(copy);
    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "jsonrpc", "2.0");
    if (!req || !cJSON_IsObject(req)) {
        cJSON_AddNullToObject(resp, "id");
        cJSON *err = cJSON_CreateObject();
        cJSON_AddNumberToObject(err, "code", -32700);
        cJSON_AddStringToObject(err, "message", "invalid JSON-RPC request");
        cJSON_AddItemToObject(resp, "error", err);
        send_json(s, 400, resp);
        cJSON_Delete(resp);
        cJSON_Delete(req);
        return;
    }
    cJSON *id = cJSON_GetObjectItem(req, "id");
    if (id) cJSON_AddItemToObject(resp, "id", cJSON_Duplicate(id, 1));
    else cJSON_AddNullToObject(resp, "id");
    const char *method = cJSON_GetStringValue(cJSON_GetObjectItem(req, "method"));
    cJSON *params = cJSON_GetObjectItem(req, "params");
    if (!method) {
        cJSON *err = cJSON_CreateObject();
        cJSON_AddNumberToObject(err, "code", -32600);
        cJSON_AddStringToObject(err, "message", "method required");
        cJSON_AddItemToObject(resp, "error", err);
    } else if (method[0] == '_') {
        cJSON *err = cJSON_CreateObject();
        cJSON_AddNumberToObject(err, "code", -32601);
        cJSON_AddStringToObject(err, "message", "hidden method");
        cJSON_AddItemToObject(resp, "error", err);
    } else {
        pymcl_set_error("%s", "");
        cJSON *result = backend_call(method, params);
        if (!result) {
            cJSON *err = cJSON_CreateObject();
            cJSON_AddNumberToObject(err, "code", -32000);
            cJSON_AddStringToObject(err, "message", pymcl_error()[0] ? pymcl_error() : "error");
            cJSON_AddItemToObject(resp, "error", err);
        } else {
            cJSON_AddItemToObject(resp, "result", result);
        }
    }
    send_json(s, 200, resp);
    cJSON_Delete(resp);
    cJSON_Delete(req);
}

static void *client_th(void *p) {
    SOCKET s = (SOCKET)(uintptr_t)p;
    /* P1-5/P1-10：全进程此前没给任何 socket 设过超时，声明了 Content-Length 却不发
       body 的连接、或者连上 /events 不读数据的客户端，都能把线程/锁无限占住。
       读 30 秒、写 10 秒（SSE 的 keepalive 是 15 秒一次，10 秒足够判定死客户端）。 */
    DWORD rcv_to = 30000, snd_to = 10000;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&rcv_to, sizeof(rcv_to));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char *)&snd_to, sizeof(snd_to));
    char *req = NULL; int n = 0;
    if (recv_req(s, &req, &n) != 0) { closesocket(s); return NULL; }
    char method[16] = {0}, target[256] = {0}, path[256] = {0};
    sscanf(req, "%15s %255s", method, target);
    strncpy(path, target, sizeof(path) - 1);
    char *query = strchr(path, '?');
    if (query) *query = 0;
    char *body = strstr(req, "\r\n\r\n");
    if (body) body += 4;

    /* Routing: public endpoints first, then token-gated RPC/SSE. */
    char origin[256] = {0};
    int has_origin = header_value(req, "Origin", origin, sizeof(origin)) && origin[0];
    if (has_origin && !origin_is_loopback(origin)) {
        send_error(s, 403, "browser origins are not allowed");
    } else if (strcmp(method, "GET") == 0 &&
               (strcmp(path, "/health") == 0 || strcmp(path, "/health/") == 0)) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddTrueToObject(o, "ok");
        cJSON_AddStringToObject(o, "name", "pymcl-bridge");
        cJSON_AddNumberToObject(o, "port", g_port);
        send_json(s, 200, o);
        cJSON_Delete(o);
    } else if (strcmp(method, "GET") == 0 && strcmp(path, "/bridge-config.json") == 0) {
        /* 这里**不再回 token**（审计 2026-09-28 P2-4）。此前它无鉴权就回 {"token": …}，
           而它在 authenticated() 之前，于是同机任意进程一次 GET 就能拿到全部 RPC 权限。
           token 是唯一凭据，不能再从 HTTP 漏出去。
           前端怎么拿 token：由启动方注入，不经这个端点 ——
             · WPF / wpf32 / WinUI3：BridgeHost 自己生成 256 位令牌，写进子进程的
               PYMCL_BRIDGE_TOKEN 环境变量（见 Services/BridgeHost.cs）；
             · slim 包（pack/stub.c）：stub 生成令牌 → --token 给桥 → 用 URL fragment
               #pymcl_bridge=<b64 {rpc_url,token}> 交给网页端（fragment 不发往服务器，
               eziapp/src/bridge.ts 读走后立刻 replaceState 抹掉）；
             · eziapp_launcher.py：同样走 fragment（_with_runtime_config）。
           这个端点只保留「问出 RPC 地址」的用途，返回的都是非敏感信息。 */
        cJSON *o = cJSON_CreateObject();
        char rpc[128];
        snprintf(rpc, sizeof(rpc), "http://127.0.0.1:%d", g_port);
        cJSON_AddStringToObject(o, "rpc_url", rpc);
        cJSON_AddNumberToObject(o, "port", g_port);
        cJSON_AddStringToObject(o, "auth", "token");
        send_json(s, 200, o);
        cJSON_Delete(o);
    } else if (strcmp(method, "GET") == 0 && strcmp(path, "/rpc") != 0
               && strcmp(path, "/events") != 0 && try_serve_www(s, path) == 0) {
        /* static UI from www/ — public */
    } else if (!authenticated(req, target, strcmp(path, "/events") == 0)) {
        send_error(s, 401, "authentication required");
    } else if (strcmp(method, "OPTIONS") == 0) {
        send_error(s, 405, "method not allowed");
    } else if (strcmp(method, "GET") == 0 && strcmp(path, "/events") == 0) {
        const char *h =
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\n"
            "Cache-Control: no-cache, no-store\r\nConnection: keep-alive\r\n\r\n";
        send_all(s, h, (int)strlen(h));
        const char *hello = "event: hello\ndata: {\"ok\":true}\n\n";
        send_all(s, hello, (int)strlen(hello));
        sse_add(s);
        for (;;) {
            Sleep(15000);
            if (send(s, ": keepalive\n\n", 13, 0) <= 0) break;
        }
        sse_remove(s);
    } else if (strcmp(method, "POST") == 0 && (strcmp(path, "/rpc") == 0 || strcmp(path, "/") == 0)) {
        handle_rpc(s, body);
    } else {
        send_error(s, 404, "not found");
    }
    free(req);
    closesocket(s);
    return NULL;
}

int server_run(const char *host, int port, const char *token) {
    if (!host || strcmp(host, "127.0.0.1") != 0) {
        pymcl_set_error("bridge may only bind to 127.0.0.1");
        return -1;
    }
    if (!token || strlen(token) < 32 || strlen(token) >= sizeof(g_token)) {
        pymcl_set_error("invalid bridge token");
        return -1;
    }
    strcpy(g_token, token);
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    backend_init(sse_emit);
    g_listen = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (g_listen == INVALID_SOCKET) {
        pymcl_set_error("socket failed");
        backend_shutdown();
        WSACleanup();
        return -1;
    }
    int opt = 1;
    setsockopt(g_listen, SOL_SOCKET, SO_REUSEADDR, (char *)&opt, sizeof(opt));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = htons((u_short)port);
    if (bind(g_listen, (struct sockaddr *)&a, sizeof(a)) != 0) {
        pymcl_set_error("bind 失败");
        closesocket(g_listen);
        backend_shutdown();
        WSACleanup();
        return -1;
    }
    listen(g_listen, 16);
    int alen = sizeof(a);
    getsockname(g_listen, (struct sockaddr *)&a, &alen);
    int real = ntohs(a.sin_port);
    g_port = real;
    char banner[PYMCL_PATH + 96];
    snprintf(banner, sizeof(banner), "PYMCL_BRIDGE port=%d host=127.0.0.1 root=%s auth=token\n", real, g_root);
    fputs(banner, stdout); fflush(stdout);
    fputs(banner, stderr);
    for (;;) {
        struct sockaddr_in peer;
        int plen = sizeof(peer);
        SOCKET c = accept(g_listen, (struct sockaddr *)&peer, &plen);
        if (c == INVALID_SOCKET) break;
        if (peer.sin_addr.s_addr != htonl(INADDR_LOOPBACK)) {
            closesocket(c);
            continue;
        }
        pthread_t th;
        pthread_create(&th, NULL, client_th, (void *)(uintptr_t)c);
        pthread_detach(th);
    }
    backend_shutdown();
    closesocket(g_listen);
    SecureZeroMemory(g_token, sizeof(g_token));
    WSACleanup();
    return 0;
}
