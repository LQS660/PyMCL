/* P2-8 判别测试：http_get_query 的 4096 字节栈缓冲静默截断。

改前（native/src/http.c:252-257）：
    char full[4096];
    snprintf(full, sizeof(full), "%s%s%s", url, strchr(url, '?') ? "&" : "?", query);
    return http_get(full, r, extra_hdr, timeout);
返回值被丢掉 —— url+query 超过 4095 字节时 URL 被截断成一个**语法合法但语义不同**的
URL，请求照发，调用方拿到的是「另一个 URL 的正常响应」，没有任何错误。

用法：query_harness.exe <url> <query_bytes> <fill_char>
  query_bytes：生成的 query 长度（形如 "q=aaaa..."）
输出：rc=<0/-1> status=<n> body_len=<n> error=<...>

配合 tests/run_query_check.py 使用：本地 http.server 会把每个请求的路径记到日志，
所以「截断请求是否真的发出去了」可以直接数出来：
  改前 query=5000：rc=0（请求发出、被截断）且服务器日志里有记录
  改后 query=5000：rc=-1、error="URL 过长"，服务器日志里没有新记录 */
#include "pymcl.h"

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: query_harness.exe <url> <query_bytes> <fill_char>\n");
        return 2;
    }
    const char *url = argv[1];
    int nbytes = atoi(argv[2]);
    char fill = argv[3][0];
    if (nbytes < 0) nbytes = 0;
    /* query = "q=" + fill*(nbytes-2) */
    char *q = (char *)malloc((size_t)nbytes + 1);
    if (!q) return 3;
    q[0] = 'q'; q[1] = '=';
    for (int i = 2; i < nbytes; i++) q[i] = fill;
    q[nbytes > 0 ? nbytes : 0] = 0;
    if (nbytes < 2) { q[0] = 0; }

    if (http_init() != 0) { fprintf(stderr, "http_init failed\n"); free(q); return 4; }
    http_resp r;
    int rc = http_get_query(url, q, &r, NULL, 20);
    printf("rc=%d status=%d body_len=%zu error=%s\n", rc, r.status, r.len,
           pymcl_error()[0] ? pymcl_error() : "(none)");
    if (rc == 0 && r.body) {
        /* 打印正文前 80 字节，方便确认拿到的是哪个资源的响应 */
        size_t k = r.len < 80 ? r.len : 80;
        printf("body[0..%zu]=", k);
        fwrite(r.body, 1, k, stdout);
        printf("\n");
    }
    http_resp_free(&r);
    http_shutdown();
    free(q);
    return rc == 0 ? 0 : 1;
}
