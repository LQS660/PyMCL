/* P2-3 判别测试：origin_is_loopback 的前缀匹配绕过。

改前（native/src/server.c:27-32）是纯前缀匹配：
    strncmp(origin, "http://127.0.0.1", 15) == 0
    || strncmp(origin, "http://localhost", 16) == 0
    || strncmp(origin, "http://[::1]", 12) == 0
`http://localhost.evil.com`、`http://127.0.0.1.attacker.net` 这类攻击者可注册的域名
前缀与之相同 → 放行。改后解析 authority 里的 host 做精确比较，后缀一律不认。

本 harness 直接 #include ../src/server.c 拿到 static 的 origin_is_loopback，
对一张用例表逐个断言。用同一份 harness 分别对「改前快照」和「改后源码」构建，
输出对比即为证据。

构建（在 native/ 下）：
  C:\\msys64\\mingw64\\bin\\gcc -O1 -std=c11 -Wall -Wno-unused-parameter \
    -Wno-unused-function -DUNICODE -D_UNICODE -DWIN32_LEAN_AND_MEAN \
    -Iinclude -Ivendor -o build/origin_harness.exe tests/origin_harness.c \
    src/util.c src/config.c src/pyval.c vendor/cJSON.c \
    -static -lz -lbcrypt -lws2_32 -lwinhttp -lpthread -lole32 -lshell32

用法：origin_harness.exe
输出：逐条 PASS/FAIL + 结尾 failures=N（0 为通过）。 */
#include "pymcl.h"
#include <winsock2.h>
#include <ws2tcpip.h>

/* ---- 顶掉 server.c 需要的外部符号 ---- */
cJSON *backend_call(const char *method, cJSON *params) { (void)method; (void)params; return NULL; }
void backend_init(sse_emit_fn f) { (void)f; }
void backend_shutdown(void) {}

#include "../src/server.c"   /* 直接包含以拿到 static 的 origin_is_loopback */

typedef struct { const char *origin; int want; const char *why; } Case;

int main(void) {
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    const Case cases[] = {
        /* ---- 应当放行（真 loopback 页面） ---- */
        { "http://127.0.0.1",              1, "loopback IP" },
        { "http://127.0.0.1:8000",         1, "loopback IP + 端口" },
        { "http://localhost",              1, "localhost" },
        { "http://localhost:1234",         1, "localhost + 端口" },
        { "http://LOCALHOST:8080",         1, "host 大小写不敏感" },
        { "http://LocalHost",              1, "host 大小写不敏感（无端口）" },
        { "http://[::1]",                  1, "IPv6 loopback" },
        { "http://[::1]:8080",             1, "IPv6 loopback + 端口" },
        { "http://127.0.0.1/",             1, "带尾斜杠" },
        { "http://localhost/path",         1, "带路径（host 仍是 localhost）" },
        /* ---- 必须拒绝：前缀相同但 host 不是 loopback ---- */
        { "http://localhost.evil.com",     0, "攻击者可控域名（改前放行 = 缺陷）" },
        { "http://127.0.0.1.attacker.net", 0, "攻击者可控域名（改前放行 = 缺陷）" },
        { "http://localhost.evil.com:80",  0, "恶意域名 + 端口" },
        { "http://127.0.0.1.evil.com/",    0, "恶意域名 + 路径" },
        { "http://[::1].evil.com",         0, "IPv6 括号后的恶意后缀" },
        { "http://[::1]evil.com",          0, "']' 后直接跟域名" },
        /* ---- 必须拒绝：userinfo / 其他混淆 ---- */
        { "http://localhost@evil.com",     0, "userinfo 混淆" },
        { "http://127.0.0.1@evil.com",     0, "userinfo 混淆" },
        { "http://evil.com",               0, "完全无关的域名" },
        { "http://notlocalhost",           0, "后缀式域名" },
        { "http://localhostx",             0, "localhost + 一个字符" },
        { "http://xlocalhost",             0, "前缀式域名" },
        /* ---- 必须拒绝：scheme / 端口形态 ---- */
        { "https://localhost",             0, "https（改前也拒绝，保持一致）" },
        { "null",                          0, "null origin" },
        { "http://localhost:80a",          0, "端口位不是纯数字" },
        { "http://localhost:",             0, "空端口" },
        { "file://localhost",              0, "非 http scheme" },
        { "http://127.0.0.1:8080.evil.com",0, "端口后跟域名" },
        { "",                              0, "空 origin" },
    };
    int n = (int)(sizeof(cases) / sizeof(cases[0])), bad = 0;
    for (int i = 0; i < n; i++) {
        int got = origin_is_loopback(cases[i].origin);
        int ok = got == cases[i].want;
        if (!ok) bad++;
        printf("%-4s origin=%-34s got=%d want=%d  %s\n",
               ok ? "PASS" : "FAIL", cases[i].origin[0] ? cases[i].origin : "(empty)",
               got, cases[i].want, cases[i].why);
        fflush(stdout);
    }
    printf("cases=%d failures=%d\n", n, bad);
    printf(bad ? "=> FAIL：仍有 origin 判定不符合预期\n"
               : "=> PASS：全部 origin 判定符合预期\n");
    WSACleanup();
    return bad ? 1 : 0;
}
