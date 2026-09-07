using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace PyMCL;

public partial class App : Application
{
    public static bool IsDark { get; private set; }

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        // 动画帧率：WPF 默认 60，桌面高刷屏下拉满更跟手。
        Timeline.DesiredFrameRateProperty.OverrideMetadata(
            typeof(Timeline), new FrameworkPropertyMetadata(60));
        RenderOptions.ProcessRenderMode = RenderMode.Default;
        DispatcherUnhandledException += OnUnhandled;
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            LogCrash(args.ExceptionObject as Exception);
        new MainWindow().Show();
    }

    private void OnUnhandled(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        LogCrash(e.Exception);
        e.Handled = true;
        try
        {
            var w = Current?.MainWindow as MainWindow;
            w?.Toast("出错了", e.Exception.Message, ToastKind.Error);
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
    }
}
