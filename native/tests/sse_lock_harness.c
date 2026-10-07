/* P1-10 判别测试：sse_emit 是否在持有 g_sse_mu 时做阻塞 send。

判别办法（直接量「锁被占住多久」）：
  1. 挂一个不读数据的假 SSE 客户端，把它的接收缓冲压到最小，并给服务端 socket
     设 SO_SNDTIMEO = 3000ms（模拟真实 client_th 的超时，但不掩盖锁的问题）。
  2. 起一个线程反复 sse_emit 大 payload —— 发送缓冲填满后，send 每次都要等超时。
  3. 主线程循环调用 sse_add/sse_remove（它们要拿同一把 g_sse_mu），量每次的耗时。
       改前：send 在锁内 → sse_add 排队等 send 返回 → 单次可达数秒
       改后：send 在锁外 → sse_add 立刻返回（毫秒级）

用法：sse_harness.exe <root>
输出：sse_add/sse_remove 的最大耗时。改前会是秒级，改后是毫秒级。 */
#include "pymcl.h"
#include <pthread.h>
#include <winsock2.h>
#include <ws2tcpip.h>

/* ---- 顶掉 server.c 需要的外部符号 ---- */
cJSON *backend_call(const char *method, cJSON *params) { (void)method; (void)params; return NULL; }
void backend_init(sse_emit_fn f) { (void)f; }
void backend_shutdown(void) {}

#include "../src/server.c"   /* 直接包含以拿到 static 的 sse_emit/sse_add/sse_remove */

static volatile int g_stop;
static SOCKET g_sink;   /* 假客户端连过来的那端，用来 sse_add */

static void *emitter(void *ud) {
    (void)ud;
    char *big = (char *)malloc(300000);
    memset(big, 'A', 299999);
    big[299999] = 0;
    while (!g_stop) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "blob", big);
        sse_emit("burst", o);
        cJSON_Delete(o);
    }
    free(big);
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: sse_harness.exe <root>\n"); return 2; }
    pymcl_set_root(argv[1]);
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);

    SOCKET srv = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int opt = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (char *)&opt, sizeof(opt));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(srv, (struct sockaddr *)&a, sizeof(a)) != 0) { printf("bind failed\n"); return 1; }
    listen(srv, 4);
    int alen = sizeof(a);
    getsockname(srv, (struct sockaddr *)&a, &alen);
    int port = ntohs(a.sin_port);
    printf("listener port=%d\n", port);

    /* 两个假客户端：一个挂着收事件（不读），一个留着做「锁探针」 */
    SOCKET cli = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int small = 512;
    setsockopt(cli, SOL_SOCKET, SO_RCVBUF, (char *)&small, sizeof(small));
    struct sockaddr_in ca;
    memset(&ca, 0, sizeof(ca));
    ca.sin_family = AF_INET;
    ca.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    ca.sin_port = htons((u_short)port);
    if (connect(cli, (struct sockaddr *)&ca, sizeof(ca)) != 0) { printf("connect failed\n"); return 1; }
    struct sockaddr_in peer;
    int plen = sizeof(peer);
    SOCKET acc = accept(srv, (struct sockaddr *)&peer, &plen);
    if (acc == INVALID_SOCKET) { printf("accept failed\n"); return 1; }
    int sndbuf = 512;
    setsockopt(acc, SOL_SOCKET, SO_SNDBUF, (char *)&sndbuf, sizeof(sndbuf));
    DWORD to = 3000;
    setsockopt(acc, SOL_SOCKET, SO_SNDTIMEO, (const char *)&to, sizeof(to));
    g_sink = acc;
    sse_add(acc);
    printf("SSE 假客户端已挂上（不读数据，SO_SNDTIMEO=3s）\n");
    fflush(stdout);

    pthread_t th;
    pthread_create(&th, NULL, emitter, NULL);
    Sleep(1500);   /* 让 emitter 把发送缓冲填满 */

    /* 锁探针：sse_add/sse_remove 要拿 g_sse_mu。send 在锁内时这里会排队等 send 超时。 */
    SOCKET probe = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    DWORD worst = 0;
    unsigned long long total = 0;
    int n = 0;
    for (int i = 0; i < 6; i++) {
        DWORD t0 = GetTickCount();
        sse_add(probe);
        sse_remove(probe);
        DWORD dt = GetTickCount() - t0;
        total += dt;
        if (dt > worst) worst = dt;
        n++;
        printf("lock probe #%d: %lu ms\n", i, (unsigned long)dt);
        fflush(stdout);
    }
    g_stop = 1;
    pthread_join(th, NULL);
    printf("lock probe: n=%d worst=%lu ms avg=%.1f ms\n", n, (unsigned long)worst,
           (double)total / n);
    printf(worst >= 500 ? "=> FAIL：锁被阻塞 send 占住（worst >= 500ms）\n"
                        : "=> PASS：锁未被阻塞 send 占住（worst < 500ms）\n");
    closesocket(probe);
    closesocket(acc);
    closesocket(cli);
    closesocket(srv);
    WSACleanup();
    return worst >= 500 ? 1 : 0;
}
