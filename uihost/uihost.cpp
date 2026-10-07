// PyMCL 内嵌 UI 宿主：把本地 UI 显示成一个普通桌面窗口，不拉起浏览器。
//
// 用的是系统自带的 WebView2（跟着 Edge 一起装的显示组件），所以这个 exe 本身
// 只有几十 KB。它只干一件事：开窗、加载 --url 指的地址、窗口关了就退出。
// 后端（bridge + 静态服务器）由调它的人负责，见 eziapp_launcher.py：
// 那边把这个进程当界面的寿命，它一退，整个启动器就收摊。
//
// 退出码：0 = 正常关窗；2 = 没有 WebView2 运行时（调用方可以退回浏览器）；
//         1 = 其它启动失败。
//
// 编译见同目录 build.bat（mingw64 g++ + WebView2 SDK 头文件）。

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>
#include <objbase.h>
#include <shlwapi.h>

#include <string>

#include "WebView2.h"

namespace {

// MIDL 头里那几个回调接口的 IID。MinGW 不吃 __uuidof，直接把 GUID 摊开写。
const GUID kIidEnvCompleted =
    {0x4e8a3389, 0xc9d8, 0x4bd2, {0xb6, 0xb5, 0x12, 0x4f, 0xee, 0x6c, 0xc1, 0x4d}};
const GUID kIidControllerCompleted =
    {0x6c4819f3, 0xc9b7, 0x4260, {0x81, 0x27, 0xc9, 0xf5, 0xbd, 0xe7, 0xf6, 0x8c}};
const GUID kIidNewWindowRequested =
    {0xd4c185fe, 0xc81c, 0x4989, {0x97, 0xaf, 0x2d, 0x3f, 0xa7, 0xab, 0x56, 0x51}};
const GUID kIidWindowCloseRequested =
    {0x5c19e9e0, 0x092f, 0x486b, {0xaf, 0xfa, 0xca, 0x82, 0x31, 0x91, 0x30, 0x39}};
const GUID kIidPermissionRequested =
    {0x15e1c6a3, 0xc72a, 0x4df3, {0x91, 0xd7, 0xd0, 0x97, 0xfb, 0xec, 0x6b, 0xfd}};

const wchar_t kClassName[] = L"PyMCLUIHost";

struct Options {
    std::wstring url;
    std::wstring title = L"PyMCL 启动器";
    std::wstring user_data;
    std::wstring icon;
    int width = 1280;
    int height = 820;
    int min_width = 980;
    int min_height = 650;
};

Options g_opt;
HWND g_hwnd = nullptr;
ICoreWebView2Controller *g_controller = nullptr;
ICoreWebView2 *g_webview = nullptr;
int g_exit_code = 0;
int g_dpi = 96;
// WM_CLOSE 里已经调过 controller->Close()（要在父窗口销毁之前）；收尾时别再关一次。
bool g_controller_closed = false;

int dp(int px) { return MulDiv(px, g_dpi, 96); }

void fail(int code, const wchar_t *msg) {
    g_exit_code = code;
    MessageBoxW(g_hwnd, msg, L"PyMCL", MB_ICONERROR);
    PostQuitMessage(code);
}

// ---------------------------------------------------------------------------
// COM 回调：只被 WebView2 自己 QI，写最小实现就够
// ---------------------------------------------------------------------------
template <class I>
class ComHandler : public I {
public:
    explicit ComHandler(const GUID &iid) : iid_(iid) {}

    ULONG STDMETHODCALLTYPE AddRef() override { return (ULONG)InterlockedIncrement(&ref_); }

    ULONG STDMETHODCALLTYPE Release() override {
        LONG n = InterlockedDecrement(&ref_);
        if (n == 0) delete this;
        return (ULONG)n;
    }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **out) override {
        if (!out) return E_POINTER;
        if (IsEqualGUID(riid, IID_IUnknown) || IsEqualGUID(riid, iid_)) {
            *out = static_cast<I *>(this);
            AddRef();
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }

protected:
    virtual ~ComHandler() = default;

private:
    const GUID iid_;
    LONG ref_ = 1;
};

// 页面里 target=_blank / window.open 的链接：交给系统浏览器，别在启动器里
// 开出一个没有地址栏、退不回去的新窗口。
class NewWindowHandler : public ComHandler<ICoreWebView2NewWindowRequestedEventHandler> {
public:
    NewWindowHandler() : ComHandler(kIidNewWindowRequested) {}

    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                     ICoreWebView2NewWindowRequestedEventArgs *args) override {
        (void)sender;
        LPWSTR uri = nullptr;
        if (SUCCEEDED(args->get_Uri(&uri)) && uri) {
            ShellExecuteW(nullptr, L"open", uri, nullptr, nullptr, SW_SHOWNORMAL);
            CoTaskMemFree(uri);
        }
        args->put_Handled(TRUE);
        return S_OK;
    }
};

// 页面调 window.close()
class WindowCloseHandler : public ComHandler<ICoreWebView2WindowCloseRequestedEventHandler> {
public:
    WindowCloseHandler() : ComHandler(kIidWindowCloseRequested) {}

    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender, IUnknown *args) override {
        (void)sender;
        (void)args;
        if (g_hwnd) PostMessageW(g_hwnd, WM_CLOSE, 0, 0);
        return S_OK;
    }
};

// 权限请求。页面是我们自己的，读剪贴板（识别 Modrinth / CurseForge 链接）直接放行，
// 其余（摄像头、麦克风、定位、通知…）一律拒。不接管的话每次启动都会弹一次授权条：
// 静态服务器端口每次都变，WebView2 按 origin 记授权，等于永远记不住。
class PermissionHandler : public ComHandler<ICoreWebView2PermissionRequestedEventHandler> {
public:
    PermissionHandler() : ComHandler(kIidPermissionRequested) {}

    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                     ICoreWebView2PermissionRequestedEventArgs *args) override {
        (void)sender;
        COREWEBVIEW2_PERMISSION_KIND kind = COREWEBVIEW2_PERMISSION_KIND_UNKNOWN_PERMISSION;
        args->get_PermissionKind(&kind);
        args->put_State(kind == COREWEBVIEW2_PERMISSION_KIND_CLIPBOARD_READ
                            ? COREWEBVIEW2_PERMISSION_STATE_ALLOW
                            : COREWEBVIEW2_PERMISSION_STATE_DENY);
        return S_OK;
    }
};

void fit_webview() {
    if (!g_controller || !g_hwnd) return;
    RECT rc;
    GetClientRect(g_hwnd, &rc);
    g_controller->put_Bounds(rc);
}

class ControllerHandler : public ComHandler<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler> {
public:
    ControllerHandler() : ComHandler(kIidControllerCompleted) {}

    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Controller *controller) override {
        if (FAILED(result) || !controller) {
            fail(1, L"WebView2 控件创建失败，界面无法显示。");
            return S_OK;
        }
        g_controller = controller;
        g_controller->AddRef();
        g_controller->get_CoreWebView2(&g_webview);
        if (!g_webview) {
            fail(1, L"WebView2 初始化不完整，界面无法显示。");
            return S_OK;
        }

        ICoreWebView2Settings *settings = nullptr;
        if (SUCCEEDED(g_webview->get_Settings(&settings)) && settings) {
            // 这是一个应用窗口，不是浏览器：底部那条链接提示栏和 Ctrl+滚轮缩放都去掉
            settings->put_IsStatusBarEnabled(FALSE);
            settings->put_IsZoomControlEnabled(FALSE);
            settings->Release();
        }

        EventRegistrationToken token;
        NewWindowHandler *nw = new NewWindowHandler();
        g_webview->add_NewWindowRequested(nw, &token);
        nw->Release();
        WindowCloseHandler *wc = new WindowCloseHandler();
        g_webview->add_WindowCloseRequested(wc, &token);
        wc->Release();
        PermissionHandler *pm = new PermissionHandler();
        g_webview->add_PermissionRequested(pm, &token);
        pm->Release();

        fit_webview();
        g_webview->Navigate(g_opt.url.c_str());
        g_controller->put_IsVisible(TRUE);
        g_controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
        return S_OK;
    }
};

class EnvHandler : public ComHandler<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler> {
public:
    EnvHandler() : ComHandler(kIidEnvCompleted) {}

    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Environment *env) override {
        if (FAILED(result) || !env) {
            fail(2, L"没找到 Microsoft Edge WebView2 运行时。\n\n"
                    L"Windows 10 / 11 通常自带；被精简过的系统可能没有。\n"
                    L"到 https://go.microsoft.com/fwlink/p/?LinkId=2124703 装一次即可（官方免费）。");
            return S_OK;
        }
        ControllerHandler *handler = new ControllerHandler();
        HRESULT hr = env->CreateCoreWebView2Controller(g_hwnd, handler);
        handler->Release();
        if (FAILED(hr)) fail(1, L"WebView2 控件创建失败，界面无法显示。");
        return S_OK;
    }
};

// ---------------------------------------------------------------------------
// 窗口
// ---------------------------------------------------------------------------
LRESULT CALLBACK wnd_proc(HWND w, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_SIZE:
        fit_webview();
        return 0;
    case WM_GETMINMAXINFO: {
        MINMAXINFO *mmi = (MINMAXINFO *)lp;
        RECT rc = {0, 0, dp(g_opt.min_width), dp(g_opt.min_height)};
        AdjustWindowRect(&rc, (DWORD)GetWindowLongPtrW(w, GWL_STYLE), FALSE);
        mmi->ptMinTrackSize.x = rc.right - rc.left;
        mmi->ptMinTrackSize.y = rc.bottom - rc.top;
        return 0;
    }
    case WM_SETFOCUS:
        if (g_controller) g_controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
        return 0;
    case WM_DPICHANGED: {
        g_dpi = HIWORD(wp);
        RECT *r = (RECT *)lp;
        SetWindowPos(w, nullptr, r->left, r->top, r->right - r->left, r->bottom - r->top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
        return 0;
    }
    case WM_CLOSE:
        // WebView2 的 Close() 要在父窗口销毁**之前**调（官方建议；窗口先没
        // 了再 Close 是反过来的顺序）。WM_DESTROY 里只剩 Release。
        if (g_controller && !g_controller_closed) {
            g_controller->Close();
            g_controller_closed = true;
        }
        DestroyWindow(w);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(g_exit_code);
        return 0;
    default:
        break;
    }
    return DefWindowProcW(w, msg, wp, lp);
}

void init_dpi() {
    HMODULE u32 = GetModuleHandleW(L"user32.dll");
    if (u32) {
        typedef BOOL(WINAPI * ctx_fn)(HANDLE);
        // PER_MONITOR_AWARE_V2 = -4：WebView2 自己会按显示器缩放，进程得先声明
        ctx_fn set_ctx = (ctx_fn)(void *)GetProcAddress(u32, "SetProcessDpiAwarenessContext");
        if (!set_ctx || !set_ctx((HANDLE)-4)) {
            typedef BOOL(WINAPI * aware_fn)(void);
            aware_fn set_aware = (aware_fn)(void *)GetProcAddress(u32, "SetProcessDPIAware");
            if (set_aware) set_aware();
        }
    }
    HDC dc = GetDC(nullptr);
    if (dc) {
        g_dpi = GetDeviceCaps(dc, LOGPIXELSX);
        ReleaseDC(nullptr, dc);
    }
}

std::wstring exe_dir() {
    // MAX_PATH 定长缓冲在长路径下会被静默截断：GetModuleFileNameW 路径 ≥ 260
    // 时返回 260 且**不设** ERROR_INSUFFICIENT_BUFFER（Win32 历史行为），
    // 截断出来的目录会让后面 LoadLibraryW(exe_dir() + "\WebView2Loader.dll")
    // 找不到 DLL，报成「缺少 WebView2Loader.dll」。所以按返回值判断截断并扩容重试。
    std::wstring buf(MAX_PATH, L'\0');
    for (;;) {
        DWORD n = GetModuleFileNameW(nullptr, buf.data(), (DWORD)buf.size());
        if (n == 0) return L".";                     // 拿不到路径，退回当前目录
        if (n < buf.size()) { buf.resize(n); break; }
        buf.resize(buf.size() * 2);                  // 被截断：扩容重试
    }
    size_t slash = buf.find_last_of(L'\\');
    return slash == std::wstring::npos ? L"." : buf.substr(0, slash);
}

/** 读环境变量到 wstring；变量不存在或值比缓冲区还长（返回值 ≥ cap）都算失败。 */
bool read_env(const wchar_t *name, std::wstring &out) {
    DWORD need = GetEnvironmentVariableW(name, nullptr, 0);
    if (need == 0) return false;                     // 不存在或读不到
    std::wstring buf(need, L'\0');
    DWORD n = GetEnvironmentVariableW(name, buf.data(), need);
    if (n == 0 || n >= need) return false;           // 期间被改短/改长，别用半截值
    buf.resize(n);
    out.swap(buf);
    return true;
}

/** 默认的浏览器数据目录：exe 旁边 webview-data，不可写就退到 %LOCALAPPDATA%。 */
std::wstring default_user_data() {
    std::wstring here = exe_dir() + L"\\webview-data";
    if (CreateDirectoryW(here.c_str(), nullptr) || GetLastError() == ERROR_ALREADY_EXISTS) return here;
    std::wstring local;
    if (read_env(L"LOCALAPPDATA", local) && !local.empty()) {
        std::wstring p = local + L"\\PyMCL\\webview-data";
        // 用 std::wstring 拼接，不再走 _snwprintf：MinGW 下它映射到 UCRT 的
        // snwprintf，宽字符格式化里 %s 是**窄**串、%ls 才是宽串，原来的
        // L"%s\\PyMCL" + wchar_t* 是格式串与实参类型不匹配（UB）。MSVC 的
        // _snwprintf 把 %s 当宽串，所以这行"看起来能跑"，但依赖实现细节。
        std::wstring parent = local + L"\\PyMCL";
        CreateDirectoryW(parent.c_str(), nullptr);
        CreateDirectoryW(p.c_str(), nullptr);
        return p;
    }
    return here;
}

bool parse_args(Options &o) {
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return false;
    auto val = [&](int &i) -> std::wstring {
        return (i + 1 < argc) ? std::wstring(argv[++i]) : std::wstring();
    };
    for (int i = 1; i < argc; i++) {
        std::wstring a = argv[i];
        if (a == L"--url") o.url = val(i);
        else if (a == L"--title") o.title = val(i);
        else if (a == L"--userdata") o.user_data = val(i);
        else if (a == L"--icon") o.icon = val(i);
        else if (a == L"--width") o.width = _wtoi(val(i).c_str());
        else if (a == L"--height") o.height = _wtoi(val(i).c_str());
        else if (a == L"--min-width") o.min_width = _wtoi(val(i).c_str());
        else if (a == L"--min-height") o.min_height = _wtoi(val(i).c_str());
    }
    LocalFree(argv);
    if (o.width < 320) o.width = 1280;
    if (o.height < 240) o.height = 820;
    if (o.min_width < 200) o.min_width = 980;
    if (o.min_height < 200) o.min_height = 650;
    return !o.url.empty();
}

}  // namespace

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)prev;
    (void)cmdline;
    (void)show;

    if (!parse_args(g_opt)) {
        MessageBoxW(nullptr,
                    L"用法：pymcl-ui.exe --url <地址> [--title 标题] [--width 宽] [--height 高]\n"
                    L"      [--min-width 最小宽] [--min-height 最小高] [--userdata 目录] [--icon 图标]",
                    L"PyMCL UI 宿主", MB_ICONINFORMATION);
        return 1;
    }
    if (g_opt.user_data.empty()) g_opt.user_data = default_user_data();

    init_dpi();
    HRESULT co = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(co)) {
        // 宿主进程可能已被某个 shell 扩展/loader 以 COINIT_MULTITHREADED
        // 初始化过（返回 RPC_E_CHANGED_MODE）。继续往下走的话，后面
        // CreateCoreWebView2EnvironmentWithOptions 的 COM 回调可能在错误的
        // apartment 上派发。这里直接报错退出，别装作没事。
        MessageBoxW(nullptr,
                    L"COM 初始化失败（进程可能已被以其他 apartment 模型初始化），界面无法显示。",
                    L"PyMCL", MB_ICONERROR);
        return 1;
    }

    WNDCLASSW wc;
    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = wnd_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = kClassName;
    if (!g_opt.icon.empty()) {
        wc.hIcon = (HICON)LoadImageW(nullptr, g_opt.icon.c_str(), IMAGE_ICON, 0, 0,
                                     LR_LOADFROMFILE | LR_DEFAULTSIZE);
    }
    if (!wc.hIcon) wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(1));
    if (!wc.hIcon) wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    RegisterClassW(&wc);

    RECT rc = {0, 0, dp(g_opt.width), dp(g_opt.height)};
    AdjustWindowRect(&rc, WS_OVERLAPPEDWINDOW, FALSE);
    int ww = rc.right - rc.left;
    int wh = rc.bottom - rc.top;
    RECT work;
    if (!SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0)) {
        work.left = work.top = 0;
        work.right = GetSystemMetrics(SM_CXSCREEN);
        work.bottom = GetSystemMetrics(SM_CYSCREEN);
    }
    g_hwnd = CreateWindowExW(0, kClassName, g_opt.title.c_str(), WS_OVERLAPPEDWINDOW,
                             work.left + ((work.right - work.left) - ww) / 2,
                             work.top + ((work.bottom - work.top) - wh) / 2,
                             ww, wh, nullptr, nullptr, inst, nullptr);
    if (!g_hwnd) {
        if (SUCCEEDED(co)) CoUninitialize();
        return 1;
    }
    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);

    // 静态链接 WebView2Loader 需要 MSVC 的 .lib，这里改成运行时加载同目录那个 DLL
    HMODULE loader = LoadLibraryW((exe_dir() + L"\\WebView2Loader.dll").c_str());
    if (!loader) loader = LoadLibraryW(L"WebView2Loader.dll");
    typedef HRESULT(STDAPICALLTYPE * create_env_fn)(PCWSTR, PCWSTR, ICoreWebView2EnvironmentOptions *,
                                                    ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *);
    create_env_fn create_env =
        loader ? (create_env_fn)(void *)GetProcAddress(loader, "CreateCoreWebView2EnvironmentWithOptions")
               : nullptr;
    if (!create_env) {
        MessageBoxW(g_hwnd, L"缺少 WebView2Loader.dll，界面无法显示。\n请把它放在 pymcl-ui.exe 旁边。",
                    L"PyMCL", MB_ICONERROR);
        if (SUCCEEDED(co)) CoUninitialize();
        return 2;
    }

    EnvHandler *env_handler = new EnvHandler();
    HRESULT hr = create_env(nullptr, g_opt.user_data.c_str(), nullptr, env_handler);
    env_handler->Release();
    if (FAILED(hr)) {
        MessageBoxW(g_hwnd,
                    L"没找到 Microsoft Edge WebView2 运行时。\n\n"
                    L"Windows 10 / 11 通常自带；被精简过的系统可能没有。\n"
                    L"到 https://go.microsoft.com/fwlink/p/?LinkId=2124703 装一次即可（官方免费）。",
                    L"PyMCL", MB_ICONERROR);
        if (SUCCEEDED(co)) CoUninitialize();
        return 2;
    }

    // GetMessageW 返回 -1 是错误（不是「没有消息」）：循环条件为假会静默退出，
    // 而失败时它**不写** msg，接着 `return msg.wParam` 返回的就是栈上垃圾值。
    // eziapp_launcher.py 用 window.wait() 取退出码，垃圾值会让退出码不可靠。
    MSG msg;
    memset(&msg, 0, sizeof(msg));
    BOOL gm;
    while ((gm = GetMessageW(&msg, nullptr, 0, 0)) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    if (gm == -1) {
        if (!g_exit_code) g_exit_code = 1;
        msg.wParam = 0;                              // 失败时 msg 未被填充，别读它
    }

    if (g_webview) g_webview->Release();
    if (g_controller) {
        if (!g_controller_closed) g_controller->Close();   // WM_CLOSE 里通常已经关过
        g_controller->Release();
    }
    if (SUCCEEDED(co)) CoUninitialize();
    return g_exit_code ? g_exit_code : (int)msg.wParam;
}
