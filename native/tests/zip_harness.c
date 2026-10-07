/* 畸形 zip 测试台（审计 02-native-c-bridge.md 的 P0-2 / P0-3 / P0-4 / P1-1 / P1-2）。
   把 zip.c 的解压路径单独链出来喂恶意包，看它是安全返回错误还是崩。

   构建（在 native/ 下）：
     C:\msys64\mingw64\bin\gcc -O1 -g -std=c11 -Wall -Wno-unused-parameter \
       -DUNICODE -D_UNICODE -DWIN32_LEAN_AND_MEAN -Iinclude -Ivendor \
       -o build/zip_harness.exe tests/zip_harness.c src/util.c src/zip.c src/pyval.c \
       src/config.c vendor/cJSON.c -static -lz -lbcrypt -lws2_32 -lpthread -lole32 -lshellapi

   用法：zip_harness.exe <zip> <outdir>
     rc=0  解压成功
     rc=1  安全拒绝（pymcl_error 有原因）——这是修复后恶意包应有的结果
     rc=-2 harness 自己判定为「本不该成功却成功了」
*/
#include "pymcl.h"

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: zip_harness.exe <zip> <outdir>\n");
        return 2;
    }
    /* zip.c 只用到 g_root（写错误信息时不用它），设成 outdir 的父目录即可 */
    pymcl_set_root(argv[2]);
    int rc = pymcl_extract_zip(argv[1], argv[2]);
    printf("extract_zip rc=%d err=[%s]\n", rc, pymcl_error());
    return rc == 0 ? 0 : 1;
}
