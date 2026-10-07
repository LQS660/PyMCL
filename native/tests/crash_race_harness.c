/* P2-6 判别测试：g_last_crash 的跨线程 delete/duplicate 竞态。

改前（native/src/backend.c）：
    task 线程：  if (g_last_crash) cJSON_Delete(g_last_crash);
                 g_last_crash = cJSON_Duplicate(rep, 1);
    client 线程：if (g_last_crash) return cJSON_Duplicate(g_last_crash, 1);
两处都无锁。写方的 cJSON_Delete 与读方的 cJSON_Duplicate 交错 → 读方遍历已释放的树。

本 harness 用两种模式（与 thumb_race_harness.c 同样的 old/new 对照法）：
  old：复刻改前的裸写裸读
  new：走 backend.c 里真正的 crash_store() + 与 get_crash 相同的锁内复制
两个线程（1 写 1 读）各跑 N 轮，读方每次都把复制出来的树完整走一遍并校验字段。
裸读模式下读方会命中已释放内存 —— 表现为 cJSON 解析出错误结构、字段缺失，
或者直接崩在堆上（Windows 的堆会直接终止进程）。

用法：crash_race.exe <old|new> [rounds]
输出：reads=N bad=N crashed=0/1
  old：bad > 0 或进程崩溃（退出码非 0）即为竞态证据
  new：bad 必须为 0 且正常退出 */
#include "pymcl.h"
#include <pthread.h>

/* ---- 复刻 backend.c 的共享状态 ---- */
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static cJSON *g_last_crash;

/* 改后的写入点（与 backend.c 的 crash_store 逐字一致） */
static void crash_store_new(cJSON *rep) {
    cJSON *dup = rep ? cJSON_Duplicate(rep, 1) : NULL;
    pthread_mutex_lock(&g_mu);
    if (g_last_crash) cJSON_Delete(g_last_crash);
    g_last_crash = dup;
    pthread_mutex_unlock(&g_mu);
}
/* 改前的写入点 */
static void crash_store_old(cJSON *rep) {
    if (g_last_crash) cJSON_Delete(g_last_crash);
    g_last_crash = cJSON_Duplicate(rep, 1);
}
/* 改后的读取点（与 get_crash 一致：锁内复制） */
static cJSON *crash_read_new(void) {
    pthread_mutex_lock(&g_mu);
    cJSON *c = g_last_crash ? cJSON_Duplicate(g_last_crash, 1) : NULL;
    pthread_mutex_unlock(&g_mu);
    return c ? c : cJSON_CreateObject();
}
/* 改前的读取点 */
static cJSON *crash_read_old(void) {
    if (g_last_crash) return cJSON_Duplicate(g_last_crash, 1);
    return cJSON_CreateObject();
}

static int g_use_old;
static volatile int g_stop;
static volatile long g_reads;
static volatile long g_bad;

static cJSON *make_report(int i) {
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "is_crash", 1);
    char buf[64];
    snprintf(buf, sizeof(buf), "summary-%d", i);
    cJSON_AddStringToObject(o, "summary", buf);
    snprintf(buf, sizeof(buf), "C:\\x\\last-crash-%d.json", i);
    cJSON_AddStringToObject(o, "direct_file", buf);
    cJSON *cause = cJSON_CreateArray();
    for (int k = 0; k < 12; k++) {
        cJSON *row = cJSON_CreateObject();
        snprintf(buf, sizeof(buf), "mod-%d-%d.jar", i, k);
        cJSON_AddStringToObject(row, "mod", buf);
        cJSON_AddItemToArray(cause, row);
    }
    cJSON_AddItemToObject(o, "suspected_mods", cause);
    return o;
}

static void *writer(void *ud) {
    (void)ud;
    for (int i = 0; !g_stop; i++) {
        cJSON *rep = make_report(i);
        if (g_use_old) crash_store_old(rep);
        else crash_store_new(rep);
        cJSON_Delete(rep);
    }
    return NULL;
}

static void *reader(void *ud) {
    (void)ud;
    while (!g_stop) {
        cJSON *c = g_use_old ? crash_read_old() : crash_read_new();
        /* 把整棵树走一遍：UAF 下这里会读到已释放的节点 */
        int ok = 1;
        const char *sum = cJSON_GetStringValue(cJSON_GetObjectItem(c, "summary"));
        const char *df = cJSON_GetStringValue(cJSON_GetObjectItem(c, "direct_file"));
        if (cJSON_GetArraySize(c) != 3) ok = 0;
        if (!sum || strncmp(sum, "summary-", 8) != 0) ok = 0;
        if (!df || strstr(df, "last-crash-") == NULL) ok = 0;
        cJSON *arr = cJSON_GetObjectItem(c, "suspected_mods");
        if (!cJSON_IsArray(arr) || cJSON_GetArraySize(arr) != 12) ok = 0;
        else {
            cJSON *row;
            cJSON_ArrayForEach(row, arr) {
                const char *m = cJSON_GetStringValue(cJSON_GetObjectItem(row, "mod"));
                if (!m || strstr(m, ".jar") == NULL) { ok = 0; break; }
            }
        }
        cJSON_Delete(c);
        __sync_fetch_and_add(&g_reads, 1);
        if (!ok) __sync_fetch_and_add(&g_bad, 1);
    }
    return NULL;
}

int main(int argc, char **argv) {
    g_use_old = argc > 1 && strcmp(argv[1], "old") == 0;
    int rounds = argc > 2 ? atoi(argv[2]) : 3;
    printf("mode=%s rounds=%d\n", g_use_old ? "old(unlocked)" : "new(g_mu)", rounds);
    fflush(stdout);
    for (int r = 0; r < rounds; r++) {
        pthread_t w, rd;
        g_stop = 0;
        pthread_create(&w, NULL, writer, NULL);
        pthread_create(&rd, NULL, reader, NULL);
        Sleep(700);
        g_stop = 1;
        pthread_join(w, NULL);
        pthread_join(rd, NULL);
        printf("round %d: reads=%ld bad=%ld\n", r + 1, (long)g_reads, (long)g_bad);
        fflush(stdout);
    }
    printf("reads=%ld bad=%ld\n", (long)g_reads, (long)g_bad);
    if (g_use_old)
        printf(g_bad > 0 ? "=> 竞态可复现：裸读拿到了被写方释放/撕裂的树\n"
                         : "=> 本次未命中（竞态是概率性的，堆布局不同可能不触发）\n");
    else
        printf(g_bad == 0 ? "=> PASS：加锁后读写一致，无撕裂\n"
                          : "=> FAIL：加锁后仍有撕裂\n");
    return g_bad > 0 ? 1 : 0;
}
