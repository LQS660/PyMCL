#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <wininet.h>
#include <winioctl.h>   /* FSCTL_SET/GET_REPARSE_POINT：数据目录里的 www / ai_gateway 联接 */
#include <wincrypt.h>   /* CryptAcquireContextW / CryptGenRandom：生成桥令牌 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "zipmin.h"
/* 静态链 liblzma 必须先定义它，否则 lzma.h 按 dllimport 声明，链接时找不到符号 */
#define LZMA_API_STATIC
#include <lzma.h>

#define MAGIC "PML1PACK"
#define VER_NAME L".payload.ver"

/* ---- 用户数据目录与解包缓存的分离 -------------------------------------------
   旧版把两者混在同一个 runtime\<载荷字节数>\ 下（PYMCL_HOME 指的就是它）。载荷每
   重新打包一次字节数就变，目录名跟着变：用户的 config.json / 账号 / AI 对话 /
   wpf-ui.json 全留在上一个目录里读不到，表现就是「升级一次设置全丢」，而且每打
   一次包就多堆一个目录。

   现在分开：
     · 解包缓存  %LOCALAPPDATA%\PyMCL\runtime\<载荷字节数>\  只放程序文件。目录名
       仍是内容指纹，marker/want/have 的「同包跳过解包」优化原样保留；
     · 用户数据  %LOCALAPPDATA%\PyMCL\home\                 固定名，跨版本连续。

   数据目录用固定名、不按应用版本号：这套目录存在的意义就是「升级后接着用」，
   按版本换名等于把这次的 bug 换个理由再犯一遍（APP_VERSION 在 Python 侧，stub 读
   不到，硬编码进 C 还会多一处要同步的地方）。数据结构的不兼容由既有的键级迁移
   兜着：mclauncher/config.py 与 native/src/config.c 里的 migrate_* 就是为此写的，
   它们本来就在同一个目录里就地升级 config.json。 */
#define DATA_DIR_NAME L"home"

/* mingw 的 winioctl.h 有 FSCTL_* 常量但不导出 REPARSE_DATA_BUFFER（那在 ddk/ntifs.h
   里，-mwindows 构建不该去拉 ddk 头）。mount point 的磁盘布局固定：8 字节头
   （tag + ReparseDataLength + Reserved）+ 4 个 USHORT 偏移/长度 + 名字，路径从第 16
   字节开始。按 ddk 头的字段顺序自己声明一份。注意 sizeof 不能用（尾部对齐会多算），
   长度一律用 MOUNT_POINT_NAMES_OFFSET 推。 */
typedef struct {
    ULONG ReparseTag;
    USHORT ReparseDataLength;
    USHORT Reserved;
    USHORT SubstituteNameOffset;
    USHORT SubstituteNameLength;
    USHORT PrintNameOffset;
    USHORT PrintNameLength;
    WCHAR PathBuffer[1];
} PYMCL_MOUNT_POINT_BUF;

#define MOUNT_POINT_NAMES_OFFSET ((size_t)&((PYMCL_MOUNT_POINT_BUF *)0)->PathBuffer)
#define MOUNT_POINT_BUF_BYTES(names_bytes) (MOUNT_POINT_NAMES_OFFSET + (names_bytes))

static void die(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"PyMCL", MB_ICONERROR);
    ExitProcess(1);
}

/* ---- window chrome ------------------------------------------------------
   Controls created without an explicit font inherit SYSTEM_FONT, a bitmap
   face from the Windows 3.x days: jagged at 100% and stretched to mush on any
   scaled display. Everything below draws with the shell's own UI font instead
   and sizes itself from the real DPI. */
static int g_dpi = 96;
static HFONT g_ui_font;
static HFONT g_ui_font_title;

/* design pixels (96 dpi) -> device pixels */
static int dp(int px) { return MulDiv(px, g_dpi, 96); }

static void ui_init(void) {
    HMODULE u32 = GetModuleHandleW(L"user32.dll");
    if (u32) {
        typedef BOOL(WINAPI * set_aware_fn)(void);
        set_aware_fn set_aware = (set_aware_fn)(void *)GetProcAddress(u32, "SetProcessDPIAware");
        if (set_aware) set_aware(); /* without this Windows bitmap-stretches the whole window */
    }
    HDC dc = GetDC(NULL);
    if (dc) {
        g_dpi = GetDeviceCaps(dc, LOGPIXELSX);
        ReleaseDC(NULL, dc);
    }
    NONCLIENTMETRICSW ncm;
    memset(&ncm, 0, sizeof(ncm));
    ncm.cbSize = sizeof(ncm);
    if (!SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, ncm.cbSize, &ncm, 0)) {
        /* pre-Vista layout has no iPaddedBorderWidth; retry with the short struct */
        memset(&ncm, 0, sizeof(ncm));
        ncm.cbSize = sizeof(ncm) - sizeof(int);
        if (!SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, ncm.cbSize, &ncm, 0)) {
            g_ui_font = g_ui_font_title = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
            return;
        }
    }
    g_ui_font = CreateFontIndirectW(&ncm.lfMessageFont);
    ncm.lfMessageFont.lfWeight = FW_SEMIBOLD;
    ncm.lfMessageFont.lfHeight = MulDiv(ncm.lfMessageFont.lfHeight, 5, 4); /* lfHeight is negative */
    g_ui_font_title = CreateFontIndirectW(&ncm.lfMessageFont);
    if (!g_ui_font) g_ui_font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    if (!g_ui_font_title) g_ui_font_title = g_ui_font;
}

static void ui_font(HWND w, HFONT f) {
    if (w && f) SendMessageW(w, WM_SETFONT, (WPARAM)f, TRUE);
}

/* place a window of the given client size in the middle of the work area */
static void ui_center(HWND w, int client_w, int client_h) {
    RECT rc = { 0, 0, client_w, client_h };
    AdjustWindowRect(&rc, (DWORD)GetWindowLongPtrW(w, GWL_STYLE), FALSE);
    int ww = rc.right - rc.left;
    int wh = rc.bottom - rc.top;
    RECT work;
    if (!SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0)) {
        work.left = work.top = 0;
        work.right = GetSystemMetrics(SM_CXSCREEN);
        work.bottom = GetSystemMetrics(SM_CYSCREEN);
    }
    SetWindowPos(w, NULL,
                 work.left + ((work.right - work.left) - ww) / 2,
                 work.top + ((work.bottom - work.top) - wh) / 2,
                 ww, wh, SWP_NOZORDER | SWP_NOACTIVATE);
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

static int dir_exists(const wchar_t *p) {
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

/* 建目录联接（junction，IO_REPARSE_TAG_MOUNT_POINT）。普通用户权限即可，
   符号链接才要管理员/开发者模式——这也是这里不用 CreateSymbolicLinkW 的原因。
   用途见 link_program_dir：把数据目录里的 www 指回解包缓存。 */
static int make_junction(const wchar_t *link, const wchar_t *target) {
    wchar_t sub[MAX_PATH + 8];
    _snwprintf(sub, MAX_PATH + 8, L"\\??\\%s", target);
    size_t sub_b = wcslen(sub) * sizeof(wchar_t);
    size_t print_b = wcslen(target) * sizeof(wchar_t);
    /* 两个名字各带一个结尾 NUL；ReparseDataLength = 4 个偏移/长度(8) + 两个名字 */
    size_t paths = sub_b + sizeof(wchar_t) + print_b + sizeof(wchar_t);
    size_t total = MOUNT_POINT_BUF_BYTES(paths);
    PYMCL_MOUNT_POINT_BUF *r = (PYMCL_MOUNT_POINT_BUF *)calloc(1, total);
    if (!r) return -1;
    r->ReparseTag = IO_REPARSE_TAG_MOUNT_POINT;
    r->ReparseDataLength = (USHORT)(8 + paths);
    r->SubstituteNameOffset = 0;
    r->SubstituteNameLength = (USHORT)sub_b;
    r->PrintNameOffset = (USHORT)(sub_b + sizeof(wchar_t));
    r->PrintNameLength = (USHORT)print_b;
    memcpy(r->PathBuffer, sub, sub_b);
    memcpy((unsigned char *)r->PathBuffer + sub_b + sizeof(wchar_t), target, print_b);

    int rc = -1;
    if (CreateDirectoryW(link, NULL) || GetLastError() == ERROR_ALREADY_EXISTS) {
        HANDLE h = CreateFileW(link, GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
                               FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
        if (h != INVALID_HANDLE_VALUE) {
            DWORD ret = 0;
            /* 输入长度按文档取 8 + ReparseDataLength（两个名字各含结尾 NUL） */
            DWORD in_len = (DWORD)(8 + r->ReparseDataLength);
            if (DeviceIoControl(h, FSCTL_SET_REPARSE_POINT, r, in_len, NULL, 0, &ret, NULL))
                rc = 0;
            CloseHandle(h);
        }
    }
    free(r);
    return rc;
}

/* 读联接当前指向（SubstituteName 形如 \??\C:\...）。不是联接或读不到返回 0。 */
static int junction_target(const wchar_t *link, wchar_t *out, size_t cap) {
    HANDLE h = CreateFileW(link, GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           NULL, OPEN_EXISTING,
                           FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    unsigned char buf[MOUNT_POINT_BUF_BYTES(4096)];
    DWORD got = 0;
    int ok = 0;
    if (DeviceIoControl(h, FSCTL_GET_REPARSE_POINT, NULL, 0, buf, sizeof(buf), &got, NULL)) {
        PYMCL_MOUNT_POINT_BUF *r = (PYMCL_MOUNT_POINT_BUF *)buf;
        if (r->ReparseTag == IO_REPARSE_TAG_MOUNT_POINT) {
            USHORT off = r->SubstituteNameOffset / sizeof(wchar_t);
            USHORT len = r->SubstituteNameLength / sizeof(wchar_t);
            if (len && (size_t)len < cap) {
                memcpy(out, r->PathBuffer + off, (size_t)len * sizeof(wchar_t));
                out[len] = 0;
                ok = 1;
            }
        }
    }
    CloseHandle(h);
    return ok;
}

/* 联接是否已指向当前缓存目录。
   cur 是 FSCTL_GET_REPARSE_POINT 读回来的目标，形如 \??\D:\...\runtime\<指纹>\<name>；
   要挑出的是 <指纹> 这一段跟 runtime 的最后一段比（不能拿 cur 和 src 直接比最后一段：
   两边都以 \name 结尾，那样永远相等，新载荷就重指不过去了）。比最后一段而不是整串，
   是为了绕开 \??\ 前缀、大小写、8.3 短名这些差异带来的假不匹配。 */
static int junction_points_at(const wchar_t *cur, const wchar_t *runtime) {
    if (!cur || !cur[0]) return 0;
    wchar_t tmp[MAX_PATH];
    wcsncpy(tmp, cur, MAX_PATH);
    tmp[MAX_PATH - 1] = 0;
    wchar_t *s = wcsrchr(tmp, L'\\');           /* 去掉结尾的 \<name>，留下 runtime\<指纹> */
    if (s) *s = 0;
    const wchar_t *cb = wcsrchr(tmp, L'\\');
    cb = cb ? cb + 1 : tmp;
    const wchar_t *rb = wcsrchr(runtime, L'\\');
    rb = rb ? rb + 1 : runtime;
    return _wcsicmp(cb, rb) == 0;
}

/* 数据目录里缺某个程序目录时，用联接指回解包缓存。
   必需的是 www：C 桥只从 --root 找它（native/src/server.c 的 g_root/www 没有
   exe 相对兜底），而 --root 现在指向固定数据目录——不联接的话 slim 包（Edge 壳）
   桥起来了却打不开界面。ai_gateway 一并带上：报错文案让用户「见 ai_gateway/README.md」，
   而它同样是按根目录找的。
   目标已存在就不动；是联接但指向旧缓存（新包换了指纹）就删掉重建——RemoveDirectoryW
   对联接只删链接本身，不会动到缓存里的真目录。 */
static void link_program_dir(const wchar_t *datahome, const wchar_t *runtime, const wchar_t *name) {
    wchar_t src[MAX_PATH], dst[MAX_PATH];
    _snwprintf(src, MAX_PATH, L"%s\\%s", runtime, name);
    if (!dir_exists(src)) return;
    _snwprintf(dst, MAX_PATH, L"%s\\%s", datahome, name);
    DWORD a = GetFileAttributesW(dst);
    if (a != INVALID_FILE_ATTRIBUTES) {
        if (!(a & FILE_ATTRIBUTE_REPARSE_POINT)) return;   /* 用户自己的真目录，不碰 */
        wchar_t cur[MAX_PATH];
        if (junction_target(dst, cur, MAX_PATH) && junction_points_at(cur, runtime))
            return;                                        /* 已指向当前缓存 */
        if (!RemoveDirectoryW(dst)) return;                /* 有进程占着：留旧的，照样能用 */
    }
    make_junction(dst, src);
}

/* 把旧版 runtime\<载荷指纹>\ 下的用户数据一次性搬进固定的数据目录。

   只搬一次（.migrated 标记）：避免用户主动删掉 config.json 想重置设置时，下一次启动
   又把旧目录里那份配置搬回来。标记写在最后，所以搬到一半崩了下次会接着搬（已搬的条目
   由「目标已存在就跳过」挡住，不会重复搬）。
   源目录挑 config.json 修改时间最新的那个——30 个目录里最新的正是用户最后在用的
   那份配置；一个 config.json 都没有时退回目录本身最新的一个。
   逐条目只在目标不存在时搬（MoveFileW 同卷瞬时完成，几个 GB 的 .minecraft / java 不
   会被拷一遍）。任何一步失败都只是跳过：迁移是尽力而为，绝不能拦住启动。 */
#define MIGRATE_MARK L".migrated"

static void migrate_user_data(const wchar_t *datahome, const wchar_t *runtime_root) {
    /* 与 mclauncher / C 桥写在 PYMCL_HOME 下的东西一一对应；程序文件（ui/ native/
       www/ mclauncher/ bridge/ tools/ app.7z/ .payload.ver）不在此列，它们留在缓存里
       由 marker 复用。 */
    static const wchar_t *entries[] = {
        L"config.json", L"accounts.json", L"ai_chats.json", L"ai_permissions.json",
        L"wpf-ui.json", L"wpf-theme.json", L"playtime.json", L"device_id",
        L"feedback_history.json", L"authlib-injector.jar", L"nide8auth.jar",
        L".minecraft", L"instances", L"cache", L"shared", L"java", L"global_mods",
        L"themes", L"skins", L"uploads", L"exports", L"terracotta",
        NULL
    };
    wchar_t marker[MAX_PATH];
    _snwprintf(marker, MAX_PATH, L"%s\\%s", datahome, MIGRATE_MARK);
    if (file_exists(marker)) return;

    wchar_t best[MAX_PATH] = {0};
    FILETIME best_cfg = {0}, best_dir = {0};
    int best_has_cfg = 0;
    wchar_t pat[MAX_PATH];
    _snwprintf(pat, MAX_PATH, L"%s\\*", runtime_root);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (fd.cFileName[0] == L'.' && (fd.cFileName[1] == 0 ||
            (fd.cFileName[1] == L'.' && fd.cFileName[2] == 0))) continue;
        wchar_t dir[MAX_PATH], cfg[MAX_PATH];
        _snwprintf(dir, MAX_PATH, L"%s\\%s", runtime_root, fd.cFileName);
        _snwprintf(cfg, MAX_PATH, L"%s\\config.json", dir);
        WIN32_FILE_ATTRIBUTE_DATA ca;
        int has_cfg = GetFileAttributesExW(cfg, GetFileExInfoStandard, &ca) != 0;
        if (has_cfg) {
            if (!best_has_cfg || CompareFileTime(&ca.ftLastWriteTime, &best_cfg) > 0) {
                best_has_cfg = 1;
                best_cfg = ca.ftLastWriteTime;
                wcsncpy(best, dir, MAX_PATH);
            }
        } else if (!best_has_cfg && CompareFileTime(&fd.ftLastWriteTime, &best_dir) > 0) {
            best_dir = fd.ftLastWriteTime;
            wcsncpy(best, dir, MAX_PATH);
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    if (!best[0]) return;   /* 没有旧目录（全新安装）：下次再看 */

    if (!dir_exists(datahome) && !CreateDirectoryW(datahome, NULL)) return;
    for (int i = 0; entries[i]; i++) {
        wchar_t src[MAX_PATH], dst[MAX_PATH];
        _snwprintf(src, MAX_PATH, L"%s\\%s", best, entries[i]);
        if (!file_exists(src) && !dir_exists(src)) continue;
        _snwprintf(dst, MAX_PATH, L"%s\\%s", datahome, entries[i]);
        if (file_exists(dst) || dir_exists(dst)) continue;   /* 目标已存在：不覆盖 */
        MoveFileW(src, dst);                                 /* 失败就跳过（可能被占用） */
    }
    write_all(marker, "1", 1);
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
    HWND w = CreateWindowExW(WS_EX_TOPMOST, L"PyMCLSplash", L"PyMCL",
        WS_POPUP | WS_CAPTION, 0, 0, dp(400), dp(104),
        NULL, NULL, wc.hInstance, NULL);
    ui_center(w, dp(400), dp(64));
    HWND text = CreateWindowExW(0, L"STATIC", L"正在解压运行时，请稍候…",
        WS_CHILD | WS_VISIBLE | SS_CENTER, dp(12), dp(22), dp(376), dp(26),
        w, NULL, wc.hInstance, NULL);
    ui_font(text, g_ui_font);
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
    /* net48 起 ui 是单托管 exe（无独立 dll）：dll 存在才参与校验（兼容旧 net8 包） */
    return file_nonempty(ui) && file_nonempty(bridge) && (!file_exists(dll) || file_nonempty(dll));
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

#define STAY_ID_TITLE 101
#define STAY_ID_BODY  102
#define STAY_ID_QUIT  103

static LRESULT CALLBACK stay_wnd_proc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_CTLCOLORSTATIC: {
        /* headline in near-black, explanation in grey, both on the window face */
        HDC dc = (HDC)wp;
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, GetDlgCtrlID((HWND)lp) == STAY_ID_TITLE ? RGB(26, 26, 26) : RGB(92, 92, 92));
        return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
    }
    case WM_COMMAND:
        if (LOWORD(wp) == STAY_ID_QUIT) {
            PostQuitMessage(0);
            return 0;
        }
        break;
    case WM_CLOSE:
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        break;
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
    wc.hIcon = LoadIconW(wc.hInstance, MAKEINTRESOURCEW(1));
    if (!wc.hIcon) wc.hIcon = LoadIconW(NULL, IDI_APPLICATION);
    wc.lpszClassName = L"PyMCLStay";
    RegisterClassW(&wc);
    const int cw = dp(480);
    const int ch = dp(178);
    const int pad = dp(24);
    HWND w = CreateWindowExW(0, L"PyMCLStay", L"PyMCL 运行中",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        0, 0, cw, ch, NULL, NULL, wc.hInstance, NULL);
    ui_center(w, cw, ch);
    HWND title = CreateWindowExW(0, L"STATIC", L"PyMCL 正在运行",
        WS_CHILD | WS_VISIBLE | SS_LEFT, pad, dp(18), cw - pad * 2, dp(26),
        w, (HMENU)STAY_ID_TITLE, wc.hInstance, NULL);
    HWND body = CreateWindowExW(0, L"STATIC",
        L"启动器后端已在运行，界面在 Edge 应用窗口里。\r\n"
        L"关掉这个窗口就会退出 PyMCL。",
        WS_CHILD | WS_VISIBLE | SS_LEFT, pad, dp(52), cw - pad * 2, dp(52),
        w, (HMENU)STAY_ID_BODY, wc.hInstance, NULL);
    HWND quit = CreateWindowExW(0, L"BUTTON", L"退出 PyMCL",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
        cw - pad - dp(112), ch - dp(50), dp(112), dp(32),
        w, (HMENU)STAY_ID_QUIT, wc.hInstance, NULL);
    ui_font(title, g_ui_font_title);
    ui_font(body, g_ui_font);
    ui_font(quit, g_ui_font);
    ShowWindow(w, SW_SHOW);
    UpdateWindow(w);

    MSG msg;
    for (;;) {
        /* Sleep in the wait instead of spinning on Sleep(200): the window stays
           responsive to clicks while the bridge handle is still watched. */
        DWORD r = MsgWaitForMultipleObjects(1, &bridge_proc, FALSE, 200, QS_ALLINPUT);
        if (r == WAIT_OBJECT_0) {
            MessageBoxW(NULL, L"C 桥已退出，界面将无法连接。", L"PyMCL", MB_ICONERROR);
            return 1;
        }
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                TerminateProcess(bridge_proc, 0);
                return 0;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        /* If health dies unexpectedly, still keep the stay window. */
        (void)port;
    }
}

/* ---- 桥令牌：由本进程生成并注入，不从 HTTP 端点取 --------------------------
   此前 slim 路径不带 --token 起 C 桥（桥就自己随机生成一个），再让 Edge 打开
   http://127.0.0.1:<port>/ —— 而网页端唯一的取令牌途径是 GET /bridge-config.json，
   那个端点**无鉴权**就回 {"token": …}，于是同机任意进程都能拿到全部 RPC 权限。

   现在反过来：这里生成 256 位令牌，随 --token 交给桥，再用 URL fragment 传给 UI。
   fragment 按定义不会发给服务器，eziapp/src/bridge.ts 的 runtimeConfigFromFragment
   会读走它（并以 history.replaceState 立刻抹掉），所以网页端拿得到、旁路进程拿不到。
   eziapp_launcher.py 的 _runtime_fragment 是同一套编码：urlsafe-b64、去掉 '=' 填充。 */
static const char k_b64url[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

static int b64url_encode(const unsigned char *data, size_t len, char *out, size_t cap) {
    size_t need = 4 * ((len + 2) / 3) + 1;
    if (need > cap) return -1;
    size_t o = 0;
    for (size_t i = 0; i < len; i += 3) {
        uint32_t v = (uint32_t)data[i] << 16;
        if (i + 1 < len) v |= (uint32_t)data[i + 1] << 8;
        if (i + 2 < len) v |= data[i + 2];
        out[o++] = k_b64url[(v >> 18) & 63];
        out[o++] = k_b64url[(v >> 12) & 63];
        if (i + 1 < len) out[o++] = k_b64url[(v >> 6) & 63];
        if (i + 2 < len) out[o++] = k_b64url[v & 63];
    }
    out[o] = 0;
    return (int)o;
}

/* 32 字节随机 → 64 位十六进制（桥要求 32..255 字符）。拿不到 CSPRNG 就返回 0。 */
static int make_bridge_token(char *out, size_t cap) {
    if (cap < 65) return 0;
    unsigned char raw[32];
    HCRYPTPROV prov = 0;
    if (!CryptAcquireContextW(&prov, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT | CRYPT_SILENT))
        return 0;
    BOOL ok = CryptGenRandom(prov, (DWORD)sizeof(raw), raw);
    CryptReleaseContext(prov, 0);
    if (!ok) return 0;
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(raw); i++) {
        out[i * 2] = hex[raw[i] >> 4];
        out[i * 2 + 1] = hex[raw[i] & 15];
    }
    out[sizeof(raw) * 2] = 0;
    SecureZeroMemory(raw, sizeof(raw));
    return 1;
}

/* "http://127.0.0.1:<port>/#pymcl_bridge=<urlsafe-b64 {rpc_url,token}>" */
static int build_ui_url(wchar_t *out, size_t cap, int port, const char *token) {
    char json[512];
    int n = snprintf(json, sizeof(json), "{\"rpc_url\":\"http://127.0.0.1:%d\",\"token\":\"%s\"}", port, token);
    if (n <= 0 || (size_t)n >= sizeof(json)) return -1;
    char enc[768];
    if (b64url_encode((const unsigned char *)json, (size_t)n, enc, sizeof(enc)) < 0) return -1;
    wchar_t wenc[768];
    if (MultiByteToWideChar(CP_UTF8, 0, enc, -1, wenc, 768) <= 0) return -1;
    _snwprintf(out, cap, L"http://127.0.0.1:%d/#pymcl_bridge=%s", port, wenc);
    SecureZeroMemory(json, sizeof(json));
    return 0;
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

/* 把 exe 尾部的载荷写成 payload.zip：xz 包着的边读边解，老格式的裸 zip 原样拷。 */
static int write_payload(FILE *f, uint64_t zlen, FILE *o) {
    static const uint8_t xz_magic[6] = {0xFD, '7', 'z', 'X', 'Z', 0x00};
    static uint8_t in[1 << 16], out[1 << 16];
    lzma_stream xz = LZMA_STREAM_INIT;
    lzma_ret ret = LZMA_OK;
    int is_xz = -1;
    uint64_t left = zlen;
    while (left) {
        size_t chunk = left > sizeof(in) ? sizeof(in) : (size_t)left;
        size_t got = fread(in, 1, chunk, f);
        if (!got) break;
        left -= got;
        if (is_xz < 0) {
            is_xz = got >= sizeof(xz_magic) && memcmp(in, xz_magic, sizeof(xz_magic)) == 0;
            if (is_xz && lzma_stream_decoder(&xz, UINT64_MAX, 0) != LZMA_OK) return -1;
        }
        if (!is_xz) {
            if (fwrite(in, 1, got, o) != got) return -1;
        } else {
            xz.next_in = in;
            xz.avail_in = got;
            while (xz.avail_in && ret != LZMA_STREAM_END) {
                xz.next_out = out;
                xz.avail_out = sizeof(out);
                ret = lzma_code(&xz, LZMA_RUN);
                size_t n = sizeof(out) - xz.avail_out;
                if ((ret != LZMA_OK && ret != LZMA_STREAM_END) || (n && fwrite(out, 1, n, o) != n)) {
                    lzma_end(&xz);
                    return -1;
                }
            }
        }
        pump();
    }
    if (is_xz <= 0) return left ? -1 : 0;
    while (!left && ret == LZMA_OK) {
        xz.next_out = out;
        xz.avail_out = sizeof(out);
        ret = lzma_code(&xz, LZMA_FINISH);
        size_t n = sizeof(out) - xz.avail_out;
        if (n && fwrite(out, 1, n, o) != n) ret = LZMA_BUF_ERROR;
    }
    lzma_end(&xz);
    return ret == LZMA_STREAM_END ? 0 : -1;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)inst; (void)prev; (void)cmdline; (void)show;
    ui_init(); /* DPI + shell UI font, before anything puts a window on screen */
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
    /* 解包缓存目录：名字就是载荷字节数（内容指纹），同包复用 marker 跳过解包 */
    wchar_t runtime[MAX_PATH], marker[MAX_PATH], zip[MAX_PATH], ui[MAX_PATH], uidll[MAX_PATH], bridge[MAX_PATH], www[MAX_PATH];
    wchar_t ui_wpf[MAX_PATH], uidll_wpf[MAX_PATH], ui_winui[MAX_PATH], uidll_winui[MAX_PATH];
    /* 用户数据目录：固定名，不随载荷变（见文件头 DATA_DIR_NAME 的说明） */
    wchar_t datahome[MAX_PATH], runtime_root[MAX_PATH];
    _snwprintf(runtime, MAX_PATH, L"%s\\PyMCL\\runtime\\%s", local, ver);
    _snwprintf(runtime_root, MAX_PATH, L"%s\\PyMCL\\runtime", local);
    _snwprintf(datahome, MAX_PATH, L"%s\\PyMCL\\%s", local, DATA_DIR_NAME);
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
        int wrote = write_payload(f, zlen, o);
        fclose(o);
        fclose(f);
        if (wrote != 0) {
            DeleteFileW(zip);
            die(L"写出 payload 不完整或已损坏");
        }
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

    /* 用户数据落到固定目录。放在这里而不是更早：解包与完整性校验都已经过了，
       确认这个包能起来，才去动用户散在旧 runtime\<指纹>\ 里的老数据——否则一个坏包
       刚跑一次就把数据搬走，用户换回旧版反而读不到了。 */
    {
        wchar_t pymcl_dir[MAX_PATH];
        _snwprintf(pymcl_dir, MAX_PATH, L"%s\\PyMCL", local);
        CreateDirectoryW(pymcl_dir, NULL);
        migrate_user_data(datahome, runtime_root);
        CreateDirectoryW(datahome, NULL);
        /* www / ai_gateway 按根目录找，但它们是程序文件、留在缓存里；用联接指过去。
           catalog.json 不用管：C 桥有 exe 相对兜底（native/src/catalog.c 会往上找
           native\data\catalog.json），而 www 没有，缺了就是空白页。 */
        link_program_dir(datahome, runtime, L"www");
        link_program_dir(datahome, runtime, L"ai_gateway");
    }

    /* Slim fallback only when native UI is absent (legacy Edge --app pack). */
    if (slim && !use_winui) {
        SetEnvironmentVariableW(L"PYMCL_HOME", datahome);
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
        /* 令牌由这里生成并注入：桥不再需要靠 /bridge-config.json 把它漏给任何人 */
        char token[80];
        if (!make_bridge_token(token, sizeof(token))) {
            CloseHandle(rd); CloseHandle(wr);
            die(L"无法生成桥令牌（CryptGenRandom 失败）");
        }
        wchar_t wtoken[80];
        MultiByteToWideChar(CP_UTF8, 0, token, -1, wtoken, 80);
        wchar_t cline[2048];
        /* --root 指数据目录（= PYMCL_HOME）：桥的 config.json / .minecraft / cache 全在
           g_root 下，指 runtime 的话配置又会写回随指纹变的缓存目录，等于没修。
           静态资源走数据目录里的 www 联接，桥读到的是同一份文件。 */
        _snwprintf(cline, 2048, L"\"%s\" --root \"%s\" --host 127.0.0.1 --port 0 --token %s",
                   bridge, datahome, wtoken);
        SecureZeroMemory(wtoken, sizeof(wtoken));
        if (!CreateProcessW(bridge, cline, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, bridgedir, &si, &pi)) {
            CloseHandle(rd); CloseHandle(wr);
            SecureZeroMemory(token, sizeof(token));
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
        /* UI 地址带 #pymcl_bridge=<b64>：令牌走 fragment（不发给服务器），
           网页端读走并立刻 replaceState 抹掉，无需再暴露 HTTP 取令牌端点 */
        wchar_t url[1024];
        if (build_ui_url(url, 1024, port, token) != 0) {
            TerminateProcess(pi.hProcess, 1);
            CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
            die(L"无法构造 UI 地址");
        }
        SecureZeroMemory(token, sizeof(token));
        HANDLE edge = open_edge_app(url);
        if (edge) CloseHandle(edge); /* Edge launcher often exits immediately — ignore */
        CloseHandle(pi.hThread);
        int code = stay_until_closed(pi.hProcess, port);
        CloseHandle(pi.hProcess);
        return code;
    }

    SetEnvironmentVariableW(L"PYMCL_HOME", datahome);
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
