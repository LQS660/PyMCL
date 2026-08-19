#include "pymcl.h"
#include <winsock2.h>
#include <ws2tcpip.h>
#include <pthread.h>

#pragma comment(lib, "ws2_32.lib")

typedef struct sse_cli {
    SOCKET s;
    struct sse_cli *next;
} sse_cli;

static sse_cli *g_sse;
static pthread_mutex_t g_sse_mu = PTHREAD_MUTEX_INITIALIZER;
static SOCKET g_listen = INVALID_SOCKET;

static void sse_add(SOCKET s) {
    sse_cli *c = (sse_cli *)calloc(1, sizeof(*c));
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
    sse_cli *c = g_sse;
    while (c) {
        send(c->s, buf, n, 0);
        c = c->next;
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
        "Cache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n",
        code, ctype, blen);
    send_all(s, hdr, n);
    if (body && blen) send_all(s, body, blen);
}

static void send_json(SOCKET s, int code, cJSON *obj) {
    char *js = cJSON_PrintUnformatted(obj);
    send_resp(s, code, "application/json; charset=utf-8", js, js ? (int)strlen(js) : 0);
    cJSON_free(js);
}

static int recv_req(SOCKET s, char **out, int *len) {
    char *buf = (char *)malloc(65536);
    int n = 0, cap = 65536;
    for (;;) {
        int r = recv(s, buf + n, cap - n - 1, 0);
        if (r <= 0) { free(buf); return -1; }
        n += r; buf[n] = 0;
        char *hdrend = strstr(buf, "\r\n\r\n");
        if (hdrend) {
            int hlen = (int)(hdrend - buf + 4);
            int cl = 0;
            char *clp = strstr(buf, "Content-Length:");
            if (!clp) clp = strstr(buf, "content-length:");
            if (clp) cl = atoi(clp + 15);
            while (n < hlen + cl) {
                if (n + 4096 > cap) { cap *= 2; buf = (char *)realloc(buf, (size_t)cap); }
                r = recv(s, buf + n, cap - n - 1, 0);
                if (r <= 0) break;
                n += r;
            }
            buf[n] = 0;
            *out = buf; *len = n;
            return 0;
        }
        if (n + 1024 > cap) { cap *= 2; buf = (char *)realloc(buf, (size_t)cap); }
    }
}

static void handle_rpc(SOCKET s, const char *body) {
    cJSON *req = cJSON_Parse(body ? body : "{}");
    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "jsonrpc", "2.0");
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
    char method[16] = {0}, path[256] = {0};
    sscanf(req, "%15s %255s", method, path);
    char *body = strstr(req, "\r\n\r\n");
    if (body) body += 4;
    if (strcmp(method, "OPTIONS") == 0) {
        const char *h =
            "HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\n"
            "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
            "Access-Control-Allow-Headers: Content-Type\r\n\r\n";
        send_all(s, h, (int)strlen(h));
    } else if (strcmp(method, "GET") == 0 && (strcmp(path, "/health") == 0 || strcmp(path, "/") == 0)) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddTrueToObject(o, "ok");
        cJSON_AddStringToObject(o, "name", "pymcl-bridge");
        send_json(s, 200, o);
        cJSON_Delete(o);
    } else if (strcmp(method, "GET") == 0 && strcmp(path, "/events") == 0) {
        const char *h =
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\n"
            "Cache-Control: no-cache\r\nConnection: keep-alive\r\n"
            "Access-Control-Allow-Origin: *\r\n\r\n";
        send_all(s, h, (int)strlen(h));
        const char *hello = "event: hello\ndata: {\"ok\":true}\n\n";
        send_all(s, hello, (int)strlen(hello));
        sse_add(s);
        /* keepalive */
        for (;;) {
            Sleep(15000);
            if (send(s, ": keepalive\n\n", 13, 0) <= 0) break;
        }
        sse_remove(s);
    } else if (strcmp(method, "POST") == 0 && (strcmp(path, "/rpc") == 0 || strcmp(path, "/") == 0)) {
        handle_rpc(s, body);
    } else {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "error", "not found");
        send_json(s, 404, o);
        cJSON_Delete(o);
    }
    free(req);
    if (!(strcmp(method, "GET") == 0 && strcmp(path, "/events") == 0))
        closesocket(s);
    else
        closesocket(s);
    return NULL;
}

int server_run(const char *host, int port) {
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    backend_init(sse_emit);
    g_listen = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int opt = 1;
    setsockopt(g_listen, SOL_SOCKET, SO_REUSEADDR, (char *)&opt, sizeof(opt));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = inet_addr(host && host[0] ? host : "127.0.0.1");
    a.sin_port = htons((u_short)port);
    if (bind(g_listen, (struct sockaddr *)&a, sizeof(a)) != 0) {
        pymcl_set_error("bind 失败");
        return -1;
    }
    listen(g_listen, 16);
    int alen = sizeof(a);
    getsockname(g_listen, (struct sockaddr *)&a, &alen);
    int real = ntohs(a.sin_port);
    char banner[PYMCL_PATH + 64];
    snprintf(banner, sizeof(banner), "PYMCL_BRIDGE port=%d host=127.0.0.1 root=%s\n", real, g_root);
    fputs(banner, stdout); fflush(stdout);
    fputs(banner, stderr);
    for (;;) {
        SOCKET c = accept(g_listen, NULL, NULL);
        if (c == INVALID_SOCKET) break;
        pthread_t th;
        pthread_create(&th, NULL, client_th, (void *)(uintptr_t)c);
        pthread_detach(th);
    }
    backend_shutdown();
    closesocket(g_listen);
    WSACleanup();
    return 0;
}
