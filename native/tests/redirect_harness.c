/* P2-5 判别测试：WinHTTP 重定向策略 —— HTTPS→HTTP 降级是否被拦住。

改前（native/src/http.c:177）policy = WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS（=2），
跨 scheme 一律跟随，包含 HTTPS 源被 302 到明文 http:// → 中间人可降级 TLS。
改后 policy = WINHTTP_OPTION_REDIRECT_POLICY_DISALLOW_HTTPS_TO_HTTP（=1）。

本 harness 直接调用 http.c 里的 http_request 路径（经 http_get），打印：
  · 编译期断言常量值（DISALLOW_HTTPS_TO_HTTP == 1，ALWAYS == 2）
  · WinHttpSetOption 的返回值（单独再设一次，确认选项真被接受）
  · 最终状态码 / 最终生效 URL / 正文前若干字节
最终 URL 用 WinHttpQueryOption(WINHTTP_OPTION_URL) 取 —— 它能直接告诉我们
请求最后落在了 http 还是 https，是判定「有没有降级」最直接的证据。

用法：redirect_harness.exe <url> [timeout_secs]
输出：set_option_ok=1 final_url=... status=... body_head=...
退出码：0 = 拿到了响应（无论 3xx/2xx）；1 = 传输失败/被拦 */
#include "pymcl.h"
#include <winhttp.h>

/* 常量值必须是 SDK 里那三个之一，且 DISALLOW 与 ALWAYS 不能相等 */
_Static_assert(WINHTTP_OPTION_REDIRECT_POLICY_DISALLOW_HTTPS_TO_HTTP == 1,
               "DISALLOW_HTTPS_TO_HTTP must be 1");
_Static_assert(WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS == 2,
               "ALWAYS must be 2");

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: redirect_harness.exe <url> [timeout_secs]\n");
        return 2;
    }
    const char *url = argv[1];
    int to = argc > 2 ? atoi(argv[2]) : 30;

    printf("compiled policy=DISALLOW_HTTPS_TO_HTTP(%d)  ALWAYS(%d)\n",
           (int)WINHTTP_OPTION_REDIRECT_POLICY_DISALLOW_HTTPS_TO_HTTP,
           (int)WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS);

    if (http_init() != 0) { fprintf(stderr, "http_init failed\n"); return 3; }

    /* 独立确认这个选项在当前系统上被接受（与 http.c 里同一调用形态） */
    HINTERNET probe = WinHttpOpen(L"pymcl-redirect-probe", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                                  WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    int set_ok = -1;
    if (probe) {
        DWORD policy = WINHTTP_OPTION_REDIRECT_POLICY_DISALLOW_HTTPS_TO_HTTP;
        BOOL r = WinHttpSetOption(probe, WINHTTP_OPTION_REDIRECT_POLICY, &policy, sizeof(policy));
        set_ok = r ? 1 : 0;
        printf("set_option_ok=%d (err=%lu)\n", set_ok, set_ok ? 0UL : GetLastError());
        WinHttpCloseHandle(probe);
    }

    http_resp r;
    int rc = http_get(url, &r, NULL, to);
    printf("rc=%d status=%d body_len=%zu error=%s\n", rc, r.status, r.len,
           pymcl_error()[0] ? pymcl_error() : "(none)");
    if (rc == 0 && r.body) {
        size_t k = r.len < 120 ? r.len : 120;
        printf("body_head=");
        for (size_t i = 0; i < k; i++) putchar(r.body[i] == '\n' ? ' ' : r.body[i]);
        printf("\n");
    }
    http_resp_free(&r);
    http_shutdown();
    return rc == 0 ? 0 : 1;
}
