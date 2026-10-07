/* P0-1 验证台：download_file / http_download_one 在各种 sha1/size 组合下的行为。
   配合 Python http.server 提供的无哈希文件使用（见 tests/run_download_check.sh）。

   构建（在 native/ 下）：
     C:\msys64\mingw64\bin\gcc -O1 -g -std=c11 -Wall -Wno-unused-parameter \
       -DUNICODE -D_UNICODE -DWIN32_LEAN_AND_MEAN -Iinclude -Ivendor \
       -o build/download_harness.exe tests/download_harness.c src/util.c src/http.c \
       src/config.c src/pyval.c vendor/cJSON.c -static -lz -lbcrypt -lws2_32 -lwinhttp -lpthread -lole32 -lshellapi

   用法：download_harness.exe <mode> <url> <dest>
     mode 0: 无 sha1 / size=-1（mods.c、java.c、installer.c:543 的调用形态）
     mode 1: sha1 + size（installer.c:218 asset 路径）
     mode 2: 只有 size
     mode 3: 无 sha1 但内容是 HTML 错误页（应被 _looks_complete 挡下）
     mode 4: 无 sha1 但内容 < 16 字节（应被挡下）
     mode 5: 无 sha1，.jar 后缀但内容不是 PK（应被挡下）
     mode 6: 无 sha1，dest 已存在且完整（应直接跳过，不下载） */
#include "pymcl.h"

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: download_harness.exe <mode> <url> <dest>\n");
        return 2;
    }
    int mode = atoi(argv[1]);
    const char *url = argv[2];
    const char *dest = argv[3];
    char parent[PYMCL_PATH];
    pymcl_parent(dest, parent, sizeof(parent));
    pymcl_set_root(parent[0] ? parent : ".");
    if (http_init() != 0) { fprintf(stderr, "http_init failed\n"); return 3; }

    const char *sha1 = NULL;
    long long size = -1;
    const char *sha512 = NULL;
    if (mode == 1) {
        /* hello world\n 的 sha1/size（测试脚本把内容固定成这个） */
        sha1 = getenv("PYMCL_TEST_SHA1");
        size = 12;
    } else if (mode == 2) {
        size = 12;
    } else if (mode == 7) {
        sha512 = getenv("PYMCL_TEST_SHA512");
    }
    int rc = download_file(url, NULL, 0, dest, NULL, sha1, size, sha512);
    printf("mode=%d rc=%d err=[%s] dest_exists=%d dest_size=%lld\n",
           mode, rc, pymcl_error(), pymcl_file_exists(dest), pymcl_file_size(dest));
    http_shutdown();
    return rc == 0 ? 0 : 1;
}
