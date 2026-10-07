using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Services;

namespace PyMCL;

public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
        AppDomain.CurrentDomain.UnhandledException += (_, e) => WriteLog("domain", e.ExceptionObject);
        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            WriteLog("task", e.Exception);
            e.SetObserved();
        };
        UnhandledException += (_, e) =>
        {
            WriteLog("xaml", e.Exception);
            e.Handled = true;
            AppServices.OnUi(() =>
            {
                try
                {
                    AppServices.Toast?.Invoke("启动器出现错误", e.Exception.Message, InfoBarSeverity.Error);
                }
                catch { }
            });
        };
    }

    private static void WriteLog(string kind, object? error)
    {
        try
        {
            var root = Environment.GetEnvironmentVariable("PYMCL_HOME");
            var log = string.IsNullOrEmpty(root)
                ? Path.Combine(AppContext.BaseDirectory, "winui-error.log")
                : Path.Combine(root, "winui-error.log");
            File.AppendAllText(log, DateTime.Now + " [" + kind + "] " + error + Environment.NewLine);
        }
        catch { }
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var window = new MainWindow();
        _window = window;
        window.Closed += (_, _) =>
        {
            // 先标记「主动退出」：DrainAndDispose 里的 Host.Dispose 会杀桥，
            // 桥的 Exited 事件随即到达，不置位的话会触发一次没人需要的重连。
            window.MarkDrained();
            DrainAndDispose();
        };
        window.Activate();
    }

    /// <summary>
    /// 关窗先让桥收拢后台任务（shutdown，预算 800ms），再杀进程。
    /// 以前直接 <c>Host.Dispose()</c> → <c>_proc.Kill(true)</c>，进行中的下载被硬砍在半截：
    /// 落盘的 .part 残留、已下载分片丢失。WPF 侧一直有这一步，WinUI 全工程原本零处调 shutdown。
    /// Closed 是同步事件，这里同步等一个有上限的预算，超时也必须放行，不能卡住退出。
    /// </summary>
    private static void DrainAndDispose()
    {
        var client = AppServices.Client;
        if (client is not null)
        {
            try
            {
                // 预算 800ms（后端 shutdown 自己也是这个上限），外层再留 1500ms 的硬顶，
                // 后端若已死或没响应，超时就走，绝不吊着窗口不放。
                using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(1500));
                client.CallAsync("shutdown", new { timeout_ms = 800 }, cts.Token)
                      .GetAwaiter().GetResult();
            }
            catch { }
        }
        AppServices.Host?.Dispose();
        AppServices.Host = null;
    }
}
