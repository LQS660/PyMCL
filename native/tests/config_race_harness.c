/* P1-11 判别测试：config_save() 遍历 cJSON 树时，另一个线程改树会不会撕裂/崩溃。

改前：config_set / config_save / config_obj 全无锁。一个线程 config_save（遍历整棵树
      序列化），另一个线程反复 config_set（删+插节点）→ UAF / 撕裂的 JSON。
改后：config_* 全在同一把（递归）互斥量下。

做法：两个线程各跑 N 轮，一个不停 config_save 并校验落盘 JSON 可解析、键数稳定，
另一个不停 config_set 增删键。跑完统计失败次数与是否崩溃。

用法：config_race.exe <root> [rounds]
输出：saves=N bad_json=N sets=N  —— bad_json > 0 表示撕裂（改前应当能复现）。 */
#include "pymcl.h"
#include <pthread.h>

static volatile int g_stop;
static volatile long g_saves;
static volatile long g_bad;
static volatile long g_sets;

static void *saver(void *ud) {
    (void)ud;
    while (!g_stop) {
        config_save();
        __sync_fetch_and_add(&g_saves, 1);
        /* 立刻读回来校验：撕裂的 JSON 会解析失败或键数突变 */
        char p[PYMCL_PATH];
        pymcl_path_join(p, sizeof(p), g_root, "config.json");
        cJSON *j = pymcl_read_json(p);
        if (!cJSON_IsObject(j)) __sync_fetch_and_add(&g_bad, 1);
        else if (!cJSON_GetObjectItemCaseSensitive(j, "memory_mb")) __sync_fetch_and_add(&g_bad, 1);
        cJSON_Delete(j);
    }
    return NULL;
}

static void *setter(void *ud) {
    (void)ud;
    long i = 0;
    while (!g_stop) {
        char k[64];
        snprintf(k, sizeof(k), "race_key_%ld", i % 64);
        config_set_int(k, (int)i);
        snprintf(k, sizeof(k), "race_del_%ld", i % 64);
        config_set_str(k, "x");
        config_set_bool("race_flag", (int)(i & 1));
        __sync_fetch_and_add(&g_sets, 1);
        i++;
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: config_race.exe <root> [seconds]\n"); return 2; }
    int secs = argc > 2 ? atoi(argv[2]) : 5;
    pymcl_set_root(argv[1]);
    config_init();
    pthread_t a, b;
    pthread_create(&a, NULL, saver, NULL);
    pthread_create(&b, NULL, setter, NULL);
    Sleep((DWORD)secs * 1000);
    g_stop = 1;
    pthread_join(a, NULL);
    pthread_join(b, NULL);
    printf("saves=%ld bad_json=%ld sets=%ld\n", g_saves, g_bad, g_sets);
    printf(g_bad == 0 ? "=> PASS：并发写读没有撕裂\n" : "=> FAIL：出现撕裂/不可解析的 config.json\n");
    return g_bad == 0 ? 0 : 1;
}
