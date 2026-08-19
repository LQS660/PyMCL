#define WIN32_LEAN_AND_MEAN
#include <windows.h>
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
    wchar_t runtime[MAX_PATH], marker[MAX_PATH], zip[MAX_PATH], ui[MAX_PATH], uidll[MAX_PATH], bridge[MAX_PATH];
    _snwprintf(runtime, MAX_PATH, L"%s\\PyMCL\\runtime\\%s", local, ver);
    _snwprintf(marker, MAX_PATH, L"%s\\%s", runtime, VER_NAME);
    _snwprintf(ui, MAX_PATH, L"%s\\ui\\PyMCL.WinUI.exe", runtime);
    _snwprintf(uidll, MAX_PATH, L"%s\\ui\\PyMCL.WinUI.dll", runtime);
    _snwprintf(bridge, MAX_PATH, L"%s\\native\\build\\pymcl-bridge.exe", runtime);

    char have[32] = {0};
    char want[32];
    snprintf(want, sizeof(want), "%llu", (unsigned long long)zlen);
    int need = 1;
    if (ui_ready(ui, uidll, bridge) && file_exists(marker)) {
        read_all(marker, have, sizeof(have));
        if (strcmp(have, want) == 0) need = 0;
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
        if (!ui_ready(ui, uidll, bridge)) {
            if (splash) DestroyWindow(splash);
            die(L"解压后缺少 UI 或 C 桥");
        }
        if (splash) { DestroyWindow(splash); splash = NULL; }
    } else {
        fclose(f);
    }

    SetEnvironmentVariableW(L"PYMCL_HOME", home);
    SetEnvironmentVariableW(L"PYMCL_BRIDGE_EXE", bridge);
    set_dotnet_root();

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
