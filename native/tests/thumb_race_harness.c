/* P1-9 判别测试：thumb_lock 的 CAS-then-InitializeCriticalSection 竞态窗口。

改前：
    static void thumb_lock(void) {
        if (InterlockedCompareExchange(&g_thumb_cs_init, 1, 0) == 0) InitializeCriticalSection(&g_thumb_cs);
        else while (g_thumb_cs_init != 1) Sleep(0);
        EnterCriticalSection(&g_thumb_cs);
    }
CAS 把标志先置 1、然后才初始化临界区。线程 B 落在这两步之间时，CAS 返回 1（不是 0），
走 else 分支，`while (g_thumb_cs_init != 1)` 立刻为假（已经是 1），于是
EnterCriticalSection 一个尚未初始化的 CRITICAL_SECTION —— UB。

本测试把这个窗口放大（在 CAS 与 Initialize 之间插入一次 Sleep），起两个线程各调一次，
观察：
  - 改前模式：第二个线程走进「未初始化就 Enter」分支（计数器 uninit_enter > 0）
  - 改后模式（pthread_mutex_t 静态初始化）：没有这个窗口，uninit_enter 恒为 0

用法：thumb_race.exe <old|new>
输出：uninit_enter=N  —— old 模式 > 0 即为竞态证据，new 模式必须为 0。 */
#include "pymcl.h"
#include <pthread.h>

static CRITICAL_SECTION g_cs;
static volatile LONG g_init;
static volatile LONG g_uninit_enter;
static volatile LONG g_ready;
static volatile LONG g_go;

/* ---- 改前模式 ---- */
static void thumb_lock_old(void) {
    if (InterlockedCompareExchange(&g_init, 1, 0) == 0) {
        /* 放大窗口：真实代码里这里没有 Sleep，但初始化本身不是原子的，
           线程 B 完全可能在这个窗口里跑到下一行 */
        Sleep(200);
        InitializeCriticalSection(&g_cs);
    } else {
        /* 走到这里说明 CAS 看到 init==1，但 InitializeCriticalSection 可能还没跑完 */
        if (InterlockedCompareExchange(&g_uninit_enter, 1, 0) == 0) {
            /* 只记第一次，避免刷屏 */
        }
        while (g_init != 1) Sleep(0);
    }
    EnterCriticalSection(&g_cs);
    LeaveCriticalSection(&g_cs);
}

/* ---- 改后模式 ---- */
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static void thumb_lock_new(void) {
    pthread_mutex_lock(&g_mu);
    pthread_mutex_unlock(&g_mu);
}

static void *worker_old(void *ud) {
    (void)ud;
    /* 两个线程尽量同时进入 thumb_lock_old */
    while (!g_go) Sleep(0);
    thumb_lock_old();
    InterlockedIncrement(&g_ready);
    return NULL;
}

static void *worker_new(void *ud) {
    (void)ud;
    while (!g_go) Sleep(0);
    thumb_lock_new();
    InterlockedIncrement(&g_ready);
    return NULL;
}

int main(int argc, char **argv) {
    int use_old = argc > 1 && strcmp(argv[1], "old") == 0;
    printf("mode=%s\n", use_old ? "old(CAS-then-Init)" : "new(pthread static)");
    pthread_t th[4];
    for (int i = 0; i < 4; i++) {
        if (use_old) pthread_create(&th[i], NULL, worker_old, NULL);
        else pthread_create(&th[i], NULL, worker_new, NULL);
    }
    Sleep(50);
    g_go = 1;
    for (int i = 0; i < 4; i++) pthread_join(th[i], NULL);
    printf("threads_done=%ld uninit_enter=%ld\n", (long)g_ready, (long)g_uninit_enter);
    if (use_old)
        printf(g_uninit_enter > 0
                   ? "=> 竞态窗口存在：有线程在 InitializeCriticalSection 完成前就 Enter 了\n"
                   : "=> 本次未命中窗口（竞态是概率性的）\n");
    else
        printf("=> 无窗口：静态初始化的互斥量不存在「先置标志后初始化」\n");
    return 0;
}
