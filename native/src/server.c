#include "pymcl.h"
#include <winsock2.h>
#include <ws2tcpip.h>
#include <pthread.h>

#pragma comment(lib, "ws2_32.lib")

#define TOKEN_MAX 256
#define MAX_REQUEST_BYTES (4 * 1024 * 1024)

typedef struct sse_cli {
    SOCKET s;
    struct sse_cli *next;
} sse_cli;

static sse_cli *g_sse;
static pthread_mutex_t g_sse_mu = PTHREAD_MUTEX_INITIALIZER;
static SOCKET g_listen = INVALID_SOCKET;
static char g_token[TOKEN_MAX];
static int g_port;

static int send_all(SOCKET s, const char *p, int n);
static void send_error(SOCKET s, int code, const char *message);

static int origin_is_loopback(const char *origin) {
    if (!origin || !*origin) return 0;
    return strncmp(origin, "http://127.0.0.1", 15) == 0
        || strncmp(origin, "http://localhost", 16) == 0
        || strncmp(origin, "http://[::1]", 12) == 0;
}

static const char *mime_for(const char *path) {
    const char *dot = strrchr(path, '.');
    if (!dot) return "application/octet-stream";
    if (pymcl_ieq(dot, ".html") || pymcl_ieq(dot, ".htm")) return "text/html; charset=utf-8";
    if (pymcl_ieq(dot, ".js") || pymcl_ieq(dot, ".mjs")) return "application/javascript; charset=utf-8";
    if (pymcl_ieq(dot, ".css")) return "text/css; charset=utf-8";
    if (pymcl_ieq(dot, ".json")) return "application/json; charset=utf-8";
    if (pymcl_ieq(dot, ".svg")) return "image/svg+xml";
    if (pymcl_ieq(dot, ".png")) return "image/png";
    if (pymcl_ieq(dot, ".jpg") || pymcl_ieq(dot, ".jpeg")) return "image/jpeg";
    if (pymcl_ieq(dot, ".ico")) return "image/x-icon";
    if (pymcl_ieq(dot, ".woff2")) return "font/woff2";
    if (pymcl_ieq(dot, ".map")) return "application/json";
    return "application/octet-stream";
}

static int safe_rel_path(const char *url_path, char *out, size_t n) {
    if (!url_path || url_path[0] != '/') return -1;
    const char *p = url_path + 1;
    if (!*p || strcmp(p, "/") == 0) p = "index.html";
    if (strstr(p, "..") || strchr(p, '\\')) return -1;
    snprintf(out, n, "%s", p);
    for (char *c = out; *c; c++) if (*c == '/') *c = '\\';
    return 0;
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
    if (!pymcl_file_exists(full)) {
        /* SPA fallback */
        if (strchr(rel, '.') == NULL) {
            pymcl_path_join(full, sizeof(full), www, "index.html");
            if (pymcl_file_exists(full))
                return send_file(s, full, "text/html; charset=utf-8");
        }
        return -1;
    }
    return send_file(s, full, mime_for(rel));
}

static void sse_add(SOCKET s) {
    sse_cli *c = (sse_cli *)calloc(1, sizeof(*c));
    if (!c) return;
    c->s = s;
    pthread_mutex_lock(&g_sse_mu);
    c->next = g_sse;
    g_sse = c;
    pthread_mutex_unlock(&g_sse_mu);
}

static void sse_remove(SOCKET s) {
    pthread_mutex_lock(&g_sse_mu);
    sse_cli **pp = &g_sse;
    while (*pp) {
        if ((*pp)->s == s) {
            sse_cli *d = *pp;
            *pp = d->next;
            free(d);
            break;
        }
        pp = &(*pp)->next;
    }
    pthread_mutex_unlock(&g_sse_mu);
}

static void sse_emit(const char *event, cJSON *data) {
    char *js = cJSON_PrintUnformatted(data ? data : cJSON_CreateObject());
    size_t need = (js ? strlen(js) : 2) + 64;
    char *buf = (char *)malloc(need);
    if (!buf) { cJSON_free(js); return; }
    int n = snprintf(buf, need, "event: %s\ndata: %s\n\n", event ? event : "message", js ? js : "{}");
    cJSON_free(js);
    pthread_mutex_lock(&g_sse_mu);
    for (sse_cli *c = g_sse; c; c = c->next)
        send(c->s, buf, n, 0);
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

static void send_json(SOCKET s, int code, cJSON *obj) {
    char *js = cJSON_PrintUnformatted(obj);
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
    cJSON *req = cJSON_Parse(body ? body : "{}");
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
        cJSON *o = cJSON_CreateObject();
        char rpc[128];
        snprintf(rpc, sizeof(rpc), "http://127.0.0.1:%d", g_port);
        cJSON_AddStringToObject(o, "rpc_url", rpc);
        cJSON_AddStringToObject(o, "token", g_token);
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
