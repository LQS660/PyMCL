#include "pymcl.h"
#include <bcrypt.h>

static void usage(void) {
    fprintf(stderr, "pymcl-bridge --root <dir> [--host 127.0.0.1] [--port 0] [--token <secret>]\n");
}

static char *arg_u8(int i, int wargc, LPWSTR *wargv) {
    if (i < 0 || i >= wargc) return NULL;
    return pymcl_wide_to_u8(wargv[i]);
}

static char *new_token(void) {
    unsigned char bytes[32];
    if (BCryptGenRandom(NULL, bytes, sizeof(bytes), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
        return NULL;
    char *out = (char *)malloc(sizeof(bytes) * 2 + 1);
    if (!out) return NULL;
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(bytes); i++) {
        out[i * 2] = hex[bytes[i] >> 4];
        out[i * 2 + 1] = hex[bytes[i] & 15];
    }
    out[sizeof(bytes) * 2] = 0;
    SecureZeroMemory(bytes, sizeof(bytes));
    return out;
}

static int valid_token(const char *token) {
    return token && strlen(token) >= 32 && strlen(token) < 256;
}

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    SetConsoleOutputCP(65001);
    int wargc = 0;
    LPWSTR *wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
    if (!wargv) return 2;

    char *root = NULL;
    char *host = pymcl_strdup("127.0.0.1");
    char *token = NULL;
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
            if (p) {
                char *end = NULL;
                long parsed = strtol(p, &end, 10);
                if (!end || *end || parsed < 0 || parsed > 65535) {
                    free(p); free(a); LocalFree(wargv); free(root); free(host); return 2;
                }
                port = (int)parsed;
                free(p);
            }
        } else if (strcmp(a, "--token") == 0 && i + 1 < wargc) {
            free(token);
            token = arg_u8(++i, wargc, wargv);
        } else if (strcmp(a, "-h") == 0 || strcmp(a, "--help") == 0) {
            free(a); usage(); LocalFree(wargv); free(root); free(host); free(token); return 0;
        }
        free(a);
    }
    LocalFree(wargv);

    if (!root || !root[0]) {
        wchar_t envw[PYMCL_PATH];
        DWORD n = GetEnvironmentVariableW(L"PYMCL_HOME", envw, PYMCL_PATH);
        if (n > 0 && n < PYMCL_PATH) root = pymcl_wide_to_u8(envw);
    }
    if (!token || !token[0]) {
        free(token);
        token = pymcl_strdup(getenv("PYMCL_BRIDGE_TOKEN") ? getenv("PYMCL_BRIDGE_TOKEN") : "");
    }
    if (!token || !token[0]) {
        free(token);
        token = new_token();
    }
    if (!root || !root[0] || !host || strcmp(host, "127.0.0.1") != 0 || !valid_token(token)) {
        usage();
        if (token) { SecureZeroMemory(token, strlen(token)); free(token); }
        free(root);
        free(host);
        return 2;
    }
    pymcl_set_root(root);
    free(root);
    config_init();
    if (http_init() != 0) {
        fprintf(stderr, "curl init failed\n");
        SecureZeroMemory(token, strlen(token));
        free(token);
        free(host);
        return 1;
    }
    int r = server_run(host, port, token);
    SecureZeroMemory(token, strlen(token));
    free(token);
    free(host);
    http_shutdown();
    return r == 0 ? 0 : 1;
}
