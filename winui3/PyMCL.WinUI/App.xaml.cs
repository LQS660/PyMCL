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
        _window = new MainWindow();
        _window.Closed += (_, _) =>
        {
            AppServices.Host?.Dispose();
            AppServices.Host = null;
        };
        _window.Activate();
    }
}
