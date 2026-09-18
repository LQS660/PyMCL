using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Interop;
using System.Windows.Threading;
using PyMCL.Services;

namespace PyMCL;

public partial class App : Application
{
    public static bool IsDark { get; private set; }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hwnd, int index);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hwnd, int index, int value);

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--nav-dump"))
        {
            // 侧栏模型的跨端对照入口：tests/test_nav_parity.py 拿它跟 Qt / TS 的结果逐条比
            Environment.ExitCode = NavDump.Run();
            Shutdown(Environment.ExitCode);
            return;
        }
        if (e.Args.Contains("--ime-check"))
        {
            // 输入法回车判定的真值表自检。自动化里敲不出真键盘，让逻辑自己受考。
            Environment.ExitCode = ImeGuard.SelfTest();
            Shutdown(Environment.ExitCode);
            return;
        }
        if (e.Args.Contains("--i18n-check"))
        {
            // 多语言自检：源码里还有没有没包 L() 的中文、L() 的 key 词表里缺不缺
            Environment.ExitCode = I18nCheck.Run(e.Args);
            Shutdown(Environment.ExitCode);
            return;
        }
        if (e.Args.Contains("--consent-check"))
        {
            // 反馈同意提示的状态机真值表：首次问、选过不再问。tests/test_wpf_feedback.py 拿它当依据
            Environment.ExitCode = Pages.FeedbackConsent.SelfTest();
            Shutdown(Environment.ExitCode);
            return;
        }
        // 语言只在启动时定一次（--lang / PYMCL_LANG / config.json 的 language），切语言照 Qt 提示重启。
        // 放在探针分支之后：--nav-dump 要跟 Qt 的中文标签逐条比，不能被 config 里的语言带偏。
        I18n.Init(e.Args);
        // 动画帧率：WPF 默认 60，桌面高刷屏下拉满更跟手。
        Timeline.DesiredFrameRateProperty.OverrideMetadata(
            typeof(Timeline), new FrameworkPropertyMetadata(60));
        RenderOptions.ProcessRenderMode = RenderMode.Default;
        DispatcherUnhandledException += OnUnhandled;
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            LogCrash(args.ExceptionObject as Exception);
        if (e.Args.Contains("--smoke"))
        {
            // 运行期冒烟：自带看门狗，跑完自己退，不会留窗口等人点
            Smoke.Run(e.Args);
            return;
        }
        if (e.Args.Contains("--nav-test"))
        {
            // 临时调试入口：静默起一个不激活、不上任务栏、屏幕外的窗口，
            // 供后台（无障碍注入）驱动侧栏点击排查用，查完删掉。
            var win = new MainWindow();
            win.ShowActivated = false;
            win.ShowInTaskbar = false;
            win.WindowStartupLocation = WindowStartupLocation.Manual;
            win.Left = 200;
            win.Top = 120;
            win.SourceInitialized += (_, _) =>
            {
                var hwnd = new WindowInteropHelper(win).Handle;
                SetWindowLong(hwnd, -20, GetWindowLong(hwnd, -20) | 0x08000000); // WS_EX_NOACTIVATE
            };
            win.Show();
            return;
        }
        new MainWindow().Show();
    }

    private void OnUnhandled(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        LogCrash(e.Exception);
        Smoke.Note("unhandled", e.Exception.ToString());
        e.Handled = true;
        try
        {
            var w = Current?.MainWindow as MainWindow;
            w?.Toast(L("出错了"), e.Exception.Message, ToastKind.Error);
        }
        catch { }
    }

    private static void LogCrash(Exception? ex)
    {
        if (ex is null) return;
        try
        {
            var dir = AppContext.BaseDirectory;
            System.IO.File.AppendAllText(System.IO.Path.Combine(dir, "pymcl-wpf-error.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {ex}\n\n");
        }
        catch { }
    }

    /// <summary>整字典热替换调色板，避免逐个改画刷造成的闪烁。</summary>
    public static void ApplyTheme(bool dark)
    {
        IsDark = dark;
        var dicts = Current.Resources.MergedDictionaries;
        var uri = new Uri(dark ? "Themes/Palette.Dark.xaml" : "Themes/Palette.Light.xaml", UriKind.Relative);
        var next = new ResourceDictionary { Source = uri };
        if (dicts.Count > 0) dicts[0] = next;
        else dicts.Add(next);
        // 壁纸的遮罩色与让位用的半透明底都跟着主题走，整字典一换就得重刷一遍
        Wallpaper.OnThemeChanged();
    }
}
