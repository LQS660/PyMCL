#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <wininet.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "zipmin.h"

#define MAGIC "PML1PACK"
#define VER_NAME L".payload.ver"

static void die(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"PyMCL", MB_ICONERROR);
    ExitProcess(1);
}

static int read_all(const wchar_t *path, char *out, int cap) {
    FILE *f = _wfopen(path, L"rb");
    if (!f) return 0;
    int n = (int)fread(out, 1, (size_t)(cap - 1), f);
    fclose(f);
    if (n < 0) n = 0;
    out[n] = 0;
    return n;
}

static int write_all(const wchar_t *path, const void *p, size_t n) {
    FILE *f = _wfopen(path, L"wb");
    if (!f) return -1;
    size_t w = fwrite(p, 1, n, f);
    fclose(f);
    return w == n ? 0 : -1;
}

static int file_exists(const wchar_t *p) {
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static int file_nonempty(const wchar_t *p) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!GetFileAttributesExW(p, GetFileExInfoStandard, &d)) return 0;
    return d.nFileSizeLow != 0 || d.nFileSizeHigh != 0;
}

static void pump(void) {
    MSG msg;
    while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
}

static HWND show_splash(void) {
    WNDCLASSW wc;
    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_WAIT);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = L"PyMCLSplash";
    RegisterClassW(&wc);
    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    HWND w = CreateWindowExW(WS_EX_TOPMOST, L"PyMCLSplash", L"PyMCL",
        WS_POPUP | WS_CAPTION | WS_VISIBLE, sw / 2 - 200, sh / 2 - 50, 400, 100,
        NULL, NULL, wc.hInstance, NULL);
    CreateWindowExW(0, L"STATIC", L"正在解压运行时，请稍候…",
        WS_CHILD | WS_VISIBLE | SS_CENTER, 10, 28, 370, 24, w, NULL, wc.hInstance, NULL);
    ShowWindow(w, SW_SHOW);
    UpdateWindow(w);
    pump();
    return w;
}

static int run_hidden(const wchar_t *exe, const wchar_t *cmd, const wchar_t *cwd) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    wchar_t buf[4096];
    wcsncpy(buf, cmd, 4095);
    buf[4095] = 0;
    if (!CreateProcessW(exe, buf, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, cwd, &si, &pi))
        return -1;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return code == 0 ? 0 : -1;
}

static void set_dotnet_root(void) {
    wchar_t user[MAX_PATH], extra[MAX_PATH], probe[MAX_PATH];
    const wchar_t *cands[4];
    int n = 0;
    cands[n++] = L"C:\\Program Files\\dotnet";
    if (GetEnvironmentVariableW(L"USERPROFILE", user, MAX_PATH)) {
        _snwprintf(extra, MAX_PATH, L"%s\\dotnet", user);
        cands[n++] = extra;
    }
    cands[n++] = L"C:\\Users\\Administrator\\dotnet";
    for (int i = 0; i < n; i++) {
        _snwprintf(probe, MAX_PATH, L"%s\\shared\\Microsoft.WindowsDesktop.App", cands[i]);
        DWORD a = GetFileAttributesW(probe);
        if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY)) {
            SetEnvironmentVariableW(L"DOTNET_ROOT", cands[i]);
            SetEnvironmentVariableW(L"DOTNET_ROOT(x64)", cands[i]);
            return;
        }
    }
}

static int ui_ready(const wchar_t *ui, const wchar_t *dll, const wchar_t *bridge) {
    return file_nonempty(ui) && file_nonempty(dll) && file_nonempty(bridge);
}

static int slim_ready(const wchar_t *www, const wchar_t *bridge) {
    return file_nonempty(www) && file_nonempty(bridge);
}

static int read_bridge_port(HANDLE out_read, DWORD timeout_ms) {
    char buf[1024];
    DWORD got = 0, total = 0;
    ULONGLONG start = GetTickCount64();
    while (GetTickCount64() - start < timeout_ms) {
        DWORD avail = 0;
        if (!PeekNamedPipe(out_read, NULL, 0, NULL, &avail, NULL)) break;
        if (avail == 0) { Sleep(50); continue; }
        if (total + avail >= sizeof(buf) - 1) avail = (DWORD)(sizeof(buf) - 1 - total);
        if (!ReadFile(out_read, buf + total, avail, &got, NULL) || got == 0) break;
        total += got;
        buf[total] = 0;
        char *p = strstr(buf, "port=");
        if (p) {
            int port = atoi(p + 5);
            if (port > 0 && port < 65536) return port;
        }
    }
    return 0;
}

static int tcp_port_open(int port) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int ok = 0;
    if (s != INVALID_SOCKET) {
        struct sockaddr_in a;
        memset(&a, 0, sizeof(a));
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        a.sin_port = htons((u_short)port);
        DWORD timeout = 500;
        setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char *)&timeout, sizeof(timeout));
        setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (char *)&timeout, sizeof(timeout));
        if (connect(s, (struct sockaddr *)&a, sizeof(a)) == 0) ok = 1;
        closesocket(s);
    }
    WSACleanup();
    return ok;
}

static int http_health_ok(int port) {
    if (tcp_port_open(port)) {
        HINTERNET ses = InternetOpenW(L"PyMCL", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
        if (!ses) return 1; /* port open is enough if WinINet unavailable */
        HINTERNET con = InternetConnectW(ses, L"127.0.0.1", (INTERNET_PORT)port, NULL, NULL,
                                         INTERNET_SERVICE_HTTP, 0, 0);
        int ok = 0;
        if (con) {
            HINTERNET req = HttpOpenRequestW(con, L"GET", L"/health", NULL, NULL, NULL,
                                             INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE |
                                             INTERNET_FLAG_NO_UI | INTERNET_FLAG_PRAGMA_NOCACHE, 0);
            if (req) {
                if (HttpSendRequestW(req, NULL, 0, NULL, 0)) {
                    DWORD status = 0, slen = sizeof(status);
                    if (HttpQueryInfoW(req, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &slen, NULL))
                        ok = (status == 200);
                }
                InternetCloseHandle(req);
            }
            InternetCloseHandle(con);
        }
        InternetCloseHandle(ses);
        return ok;
    }
    return 0;
}

static int bridge_dlls_ok(const wchar_t *bridgedir, wchar_t *missing, size_t miss_n) {
    const wchar_t *need[] = {
        L"libcurl-4.dll", L"zlib1.dll", L"libwinpthread-1.dll",
        L"libssl-3-x64.dll", L"libcrypto-3-x64.dll", NULL
    };
    missing[0] = 0;
    for (int i = 0; need[i]; i++) {
        wchar_t p[MAX_PATH];
        _snwprintf(p, MAX_PATH, L"%s\\%s", bridgedir, need[i]);
        if (GetFileAttributesW(p) == INVALID_FILE_ATTRIBUTES) {
            _snwprintf(missing, (int)miss_n, L"%s", need[i]);
            return 0;
        }
    }
    return 1;
}

static LRESULT CALLBACK stay_wnd_proc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    if (m == WM_CLOSE || m == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(w, m, wp, lp);
}

/* Keep bridge alive; Edge's CreateProcess handle often exits immediately when
   an existing msedge instance takes the --app window. Do NOT kill bridge on that. */
static int stay_until_closed(HANDLE bridge_proc, int port) {
    WNDCLASSW wc;
    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = stay_wnd_proc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = L"PyMCLStay";
    RegisterClassW(&wc);
    HWND w = CreateWindowExW(0, L"PyMCLStay", L"PyMCL 运行中",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 360, 140, NULL, NULL, wc.hInstance, NULL);
    CreateWindowExW(0, L"STATIC",
        L"启动器后端已在运行。\r\n关闭本窗口将退出 PyMCL。\r\n界面在 Edge 应用窗中。",
        WS_CHILD | WS_VISIBLE | SS_LEFT, 16, 24, 320, 70, w, NULL, wc.hInstance, NULL);
    ShowWindow(w, SW_SHOW);
    UpdateWindow(w);

    MSG msg;
    for (;;) {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                TerminateProcess(bridge_proc, 0);
                return 0;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if (WaitForSingleObject(bridge_proc, 0) == WAIT_OBJECT_0) {
            MessageBoxW(NULL, L"C 桥已退出，界面将无法连接。", L"PyMCL", MB_ICONERROR);
            return 1;
        }
        /* If health dies unexpectedly, still keep the stay window. */
        Sleep(200);
        (void)port;
    }
}

static HANDLE open_edge_app(const wchar_t *url) {
    const wchar_t *cands[] = {
        L"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        L"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    };
    for (int i = 0; i < 2; i++) {
        if (GetFileAttributesW(cands[i]) == INVALID_FILE_ATTRIBUTES) continue;
        STARTUPINFOW si; PROCESS_INFORMATION pi;
        memset(&si, 0, sizeof(si)); memset(&pi, 0, sizeof(pi));
        si.cb = sizeof(si);
        wchar_t cline[4096];
        _snwprintf(cline, 4096, L"\"%s\" --app=\"%s\" --disable-features=msSmartScreenProtection", cands[i], url);
        if (CreateProcessW(cands[i], cline, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
            CloseHandle(pi.hThread);
            return pi.hProcess;
        }
    }
    ShellExecuteW(NULL, L"open", url, NULL, NULL, SW_SHOWNORMAL);
    return NULL;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)inst; (void)prev; (void)cmdline; (void)show;
    wchar_t self[MAX_PATH];
    if (!GetModuleFileNameW(NULL, self, MAX_PATH)) die(L"无法定位自身");

    wchar_t home[MAX_PATH];
    wcsncpy(home, self, MAX_PATH);
    wchar_t *slash = wcsrchr(home, L'\\');
    if (slash) *slash = 0;

    FILE *f = _wfopen(self, L"rb");
    if (!f) die(L"无法打开自身");
    if (_fseeki64(f, 0, SEEK_END) != 0) { fclose(f); die(L"读取失败"); }
    int64_t sz = _ftelli64(f);
    if (sz < 24) { fclose(f); die(L"文件不完整"); }
    unsigned char tail[16];
    if (_fseeki64(f, -16, SEEK_END) != 0 || fread(tail, 1, 16, f) != 16) {
        fclose(f); die(L"读取包尾失败");
    }
    if (memcmp(tail + 8, MAGIC, 8) != 0) {
        fclose(f); die(L"不是有效的 PyMCL 单文件包");
    }
    uint64_t zlen = 0;
    memcpy(&zlen, tail, 8);
    if (zlen == 0 || zlen > (uint64_t)sz - 16) { fclose(f); die(L"包大小异常"); }

    wchar_t ver[17];
    _snwprintf(ver, 17, L"%08X%08X", (unsigned)(zlen >> 32), (unsigned)zlen);

    wchar_t local[MAX_PATH];
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH)) die(L"找不到 LOCALAPPDATA");
    wchar_t runtime[MAX_PATH], marker[MAX_PATH], zip[MAX_PATH], ui[MAX_PATH], uidll[MAX_PATH], bridge[MAX_PATH], www[MAX_PATH];
    wchar_t ui_wpf[MAX_PATH], uidll_wpf[MAX_PATH], ui_winui[MAX_PATH], uidll_winui[MAX_PATH];
    _snwprintf(runtime, MAX_PATH, L"%s\\PyMCL\\runtime\\%s", local, ver);
    _snwprintf(marker, MAX_PATH, L"%s\\%s", runtime, VER_NAME);
    _snwprintf(ui_wpf, MAX_PATH, L"%s\\ui\\PyMCL.Wpf.exe", runtime);
    _snwprintf(uidll_wpf, MAX_PATH, L"%s\\ui\\PyMCL.Wpf.dll", runtime);
    _snwprintf(ui_winui, MAX_PATH, L"%s\\ui\\PyMCL.WinUI.exe", runtime);
    _snwprintf(uidll_winui, MAX_PATH, L"%s\\ui\\PyMCL.WinUI.dll", runtime);
    _snwprintf(bridge, MAX_PATH, L"%s\\native\\build\\pymcl-bridge.exe", runtime);
    _snwprintf(www, MAX_PATH, L"%s\\www\\index.html", runtime);
    /* Prefer WPF (PCL UI stack) over WinUI over Edge/www. */
    if (ui_ready(ui_wpf, uidll_wpf, bridge)) {
        wcsncpy(ui, ui_wpf, MAX_PATH);
        wcsncpy(uidll, uidll_wpf, MAX_PATH);
    } else {
        wcsncpy(ui, ui_winui, MAX_PATH);
        wcsncpy(uidll, uidll_winui, MAX_PATH);
    }

    char have[32] = {0};
    char want[32];
    snprintf(want, sizeof(want), "%llu", (unsigned long long)zlen);
    int need = 1;
    int slim = 0;
    int use_winui = 0;
    if (ui_ready(ui, uidll, bridge) && file_exists(marker)) {
        read_all(marker, have, sizeof(have));
        if (strcmp(have, want) == 0) { need = 0; use_winui = 1; }
    } else if (slim_ready(www, bridge) && file_exists(marker)) {
        read_all(marker, have, sizeof(have));
        if (strcmp(have, want) == 0) { need = 0; slim = 1; }
    }
    HWND splash = NULL;
    if (need) {
        splash = show_splash();
        CreateDirectoryW(local, NULL);
        wchar_t base[MAX_PATH];
        _snwprintf(base, MAX_PATH, L"%s\\PyMCL", local);
        CreateDirectoryW(base, NULL);
        _snwprintf(base, MAX_PATH, L"%s\\PyMCL\\runtime", local);
        CreateDirectoryW(base, NULL);
        CreateDirectoryW(runtime, NULL);
        _snwprintf(zip, MAX_PATH, L"%s\\payload.zip", runtime);
        FILE *o = _wfopen(zip, L"wb");
        if (!o) { fclose(f); die(L"无法写出 payload"); }
        if (_fseeki64(f, (int64_t)((uint64_t)sz - 16 - zlen), SEEK_SET) != 0) {
            fclose(o); fclose(f); die(L"定位 payload 失败");
        }
        char buf[1 << 16];
        uint64_t left = zlen;
        while (left) {
            size_t chunk = left > sizeof(buf) ? sizeof(buf) : (size_t)left;
            size_t got = fread(buf, 1, chunk, f);
            if (!got) break;
            fwrite(buf, 1, got, o);
            left -= got;
            pump();
        }
        fclose(o);
        fclose(f);
        if (left) die(L"写出 payload 不完整");
        if (zipmin_extract(zip, runtime) != 0) {
            DeleteFileW(zip);
            die(L"解压失败");
        }
        DeleteFileW(zip);

        wchar_t seven[MAX_PATH], app7z[MAX_PATH], tools[MAX_PATH];
        _snwprintf(seven, MAX_PATH, L"%s\\tools\\7z.exe", runtime);
        _snwprintf(app7z, MAX_PATH, L"%s\\app.7z", runtime);
        _snwprintf(tools, MAX_PATH, L"%s\\tools", runtime);
        if (file_exists(app7z) && file_exists(seven)) {
            wchar_t cmd[4096];
            _snwprintf(cmd, 4096, L"\"%s\" x -y \"-o%s\" \"%s\"", seven, runtime, app7z);
            if (run_hidden(seven, cmd, tools) != 0) {
                if (splash) DestroyWindow(splash);
                die(L"7z 解压失败");
            }
            DeleteFileW(app7z);
            DeleteFileW(seven);
            wchar_t dll7[MAX_PATH];
            _snwprintf(dll7, MAX_PATH, L"%s\\tools\\7z.dll", runtime);
            DeleteFileW(dll7);
            RemoveDirectoryW(tools);
        }
        write_all(marker, want, strlen(want));
        if (ui_ready(ui_wpf, uidll_wpf, bridge)) {
            wcsncpy(ui, ui_wpf, MAX_PATH);
            wcsncpy(uidll, uidll_wpf, MAX_PATH);
        } else {
            wcsncpy(ui, ui_winui, MAX_PATH);
            wcsncpy(uidll, uidll_winui, MAX_PATH);
        }
        use_winui = ui_ready(ui, uidll, bridge);
        slim = !use_winui && slim_ready(www, bridge);
        if (!use_winui && !slim) {
            if (splash) DestroyWindow(splash);
            die(L"解压后缺少 UI 或 C 桥");
        }
        if (splash) { DestroyWindow(splash); splash = NULL; }
    } else {
        fclose(f);
        if (ui_ready(ui_wpf, uidll_wpf, bridge)) {
            wcsncpy(ui, ui_wpf, MAX_PATH);
            wcsncpy(uidll, uidll_wpf, MAX_PATH);
        } else {
            wcsncpy(ui, ui_winui, MAX_PATH);
            wcsncpy(uidll, uidll_winui, MAX_PATH);
        }
        use_winui = ui_ready(ui, uidll, bridge);
        slim = !use_winui && slim_ready(www, bridge);
    }

    /* Slim fallback only when native UI is absent (legacy Edge --app pack). */
    if (slim && !use_winui) {
        SetEnvironmentVariableW(L"PYMCL_HOME", runtime);
        SetEnvironmentVariableW(L"PYMCL_BRIDGE_EXE", bridge);
        wchar_t bridgedir[MAX_PATH];
        wcsncpy(bridgedir, bridge, MAX_PATH);
        wchar_t *bs = wcsrchr(bridgedir, L'\\');
        if (bs) *bs = 0;
        wchar_t pathenv[32768];
        DWORD pn = GetEnvironmentVariableW(L"PATH", pathenv, 32768);
        if (pn == 0 || pn >= 32000) pathenv[0] = 0;
        wchar_t newpath[32768];
        _snwprintf(newpath, 32768, L"%s;%s", bridgedir, pathenv);
        SetEnvironmentVariableW(L"PATH", newpath);

        wchar_t miss[64];
        if (!bridge_dlls_ok(bridgedir, miss, 64)) {
            wchar_t msg[256];
            _snwprintf(msg, 256, L"缺少依赖 DLL：%s\n目录：%s", miss, bridgedir);
            die(msg);
        }

        SECURITY_ATTRIBUTES sa;
        memset(&sa, 0, sizeof(sa));
        sa.nLength = sizeof(sa);
        sa.bInheritHandle = TRUE;
        HANDLE rd = NULL, wr = NULL;
        if (!CreatePipe(&rd, &wr, &sa, 0)) die(L"无法创建管道");
        SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);

        STARTUPINFOW si; PROCESS_INFORMATION pi;
        memset(&si, 0, sizeof(si)); memset(&pi, 0, sizeof(pi));
        si.cb = sizeof(si);
        si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_HIDE;
        si.hStdOutput = wr;
        si.hStdError = wr;
        si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        wchar_t cline[2048];
        _snwprintf(cline, 2048, L"\"%s\" --root \"%s\" --host 127.0.0.1 --port 0", bridge, runtime);
        if (!CreateProcessW(bridge, cline, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, bridgedir, &si, &pi)) {
            CloseHandle(rd); CloseHandle(wr);
            die(L"无法启动 C 桥");
        }
        CloseHandle(wr);
        int port = read_bridge_port(rd, 15000);
        CloseHandle(rd);
        if (port <= 0) {
            TerminateProcess(pi.hProcess, 1);
            CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
            die(L"C 桥未输出端口");
        }
        /* Wait until /health actually answers — banner alone is not enough. */
        int healthy = 0;
        for (int i = 0; i < 50; i++) {
            if (WaitForSingleObject(pi.hProcess, 0) == WAIT_OBJECT_0) break;
            if (http_health_ok(port)) { healthy = 1; break; }
            Sleep(100);
        }
        if (!healthy) {
            DWORD exit_code = 0;
            GetExitCodeProcess(pi.hProcess, &exit_code);
            TerminateProcess(pi.hProcess, 1);
            CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
            wchar_t msg[320];
            _snwprintf(msg, 320,
                L"C 桥已启动但 /health 无响应（port=%d, exit=0x%08X）。\n"
                L"请确认 native/build 旁 DLL 齐全，或查看杀软是否拦截。",
                port, (unsigned)exit_code);
            die(msg);
        }
        wchar_t url[128];
        _snwprintf(url, 128, L"http://127.0.0.1:%d/", port);
        HANDLE edge = open_edge_app(url);
        if (edge) CloseHandle(edge); /* Edge launcher often exits immediately — ignore */
        CloseHandle(pi.hThread);
        int code = stay_until_closed(pi.hProcess, port);
        CloseHandle(pi.hProcess);
        return code;
    }

    SetEnvironmentVariableW(L"PYMCL_HOME", runtime);
    SetEnvironmentVariableW(L"PYMCL_BRIDGE_EXE", bridge);
    set_dotnet_root();

    /* Ensure curl DLLs resolve when WinUI spawns the C bridge. */
    {
        wchar_t bridgedir[MAX_PATH], pathenv[32768], newpath[32768];
        wcsncpy(bridgedir, bridge, MAX_PATH);
        wchar_t *bs = wcsrchr(bridgedir, L'\\');
        if (bs) *bs = 0;
        DWORD pn = GetEnvironmentVariableW(L"PATH", pathenv, 32768);
        if (pn == 0 || pn >= 32000) pathenv[0] = 0;
        _snwprintf(newpath, 32768, L"%s;%s", bridgedir, pathenv);
        SetEnvironmentVariableW(L"PATH", newpath);
    }

    wchar_t uidir[MAX_PATH];
    wcsncpy(uidir, ui, MAX_PATH);
    slash = wcsrchr(uidir, L'\\');
    if (slash) *slash = 0;

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);
    wchar_t cline[MAX_PATH + 8];
    _snwprintf(cline, MAX_PATH + 8, L"\"%s\"", ui);
    if (!CreateProcessW(ui, cline, NULL, NULL, FALSE, 0, NULL, uidir, &si, &pi)) {
        DWORD err = GetLastError();
        wchar_t msg[256];
        _snwprintf(msg, 256, L"无法启动界面（Win32 %u）。请安装 .NET 8 桌面运行时。", (unsigned)err);
        die(msg);
    }
    CloseHandle(pi.hThread);
    DWORD wr = WaitForSingleObject(pi.hProcess, 4000);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    if (wr == WAIT_OBJECT_0 && code != 0) {
        CloseHandle(pi.hProcess);
        wchar_t msg[320];
        _snwprintf(msg, 320,
            L"界面启动失败（退出码 0x%08X）。\n需要 .NET 8 桌面运行时：\nhttps://aka.ms/dotnet/download",
            (unsigned)code);
        die(msg);
    }
    if (wr != WAIT_OBJECT_0)
        WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
