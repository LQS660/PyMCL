#include "pymcl.h"

static void usage(void) {
    fprintf(stderr, "pymcl-bridge --root <dir> [--host 127.0.0.1] [--port 0]\n");
}

static char *arg_u8(int i, int wargc, LPWSTR *wargv) {
    if (i < 0 || i >= wargc) return NULL;
    return pymcl_wide_to_u8(wargv[i]);
}

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    SetConsoleOutputCP(65001);
    int wargc = 0;
    LPWSTR *wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
    if (!wargv) return 2;

    char *root = NULL;
    char *host = pymcl_strdup("127.0.0.1");
    int port = 0;
    for (int i = 1; i < wargc; i++) {
        char *a = arg_u8(i, wargc, wargv);
        if (!a) continue;
        if (strcmp(a, "--root") == 0 && i + 1 < wargc) {
            free(root);
            root = arg_u8(++i, wargc, wargv);
        } else if (strcmp(a, "--host") == 0 && i + 1 < wargc) {
            free(host);
            host = arg_u8(++i, wargc, wargv);
        } else if (strcmp(a, "--port") == 0 && i + 1 < wargc) {
            char *p = arg_u8(++i, wargc, wargv);
            if (p) { port = atoi(p); free(p); }
        } else if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            free(a); usage(); LocalFree(wargv); return 0;
        }
        free(a);
    }
    LocalFree(wargv);

    if (!root || !root[0]) {
        wchar_t envw[PYMCL_PATH];
        DWORD n = GetEnvironmentVariableW(L"PYMCL_HOME", envw, PYMCL_PATH);
        if (n > 0 && n < PYMCL_PATH) root = pymcl_wide_to_u8(envw);
    }
    if (!root || !root[0]) {
        usage();
        free(host);
        return 2;
    }
    pymcl_set_root(root);
    free(root);
    config_init();
    if (http_init() != 0) {
        fprintf(stderr, "curl init failed\n");
        free(host);
        return 1;
    }
    int r = server_run(host, port);
    free(host);
    http_shutdown();
    return r == 0 ? 0 : 1;
}
