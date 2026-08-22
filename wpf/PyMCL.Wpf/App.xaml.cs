using System.Windows;
using PyMCL.Services;

namespace PyMCL;

public partial class App : Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += (_, args) =>
        {
            MessageBox.Show(args.Exception.Message, "PyMCL", MessageBoxButton.OK, MessageBoxImage.Error);
            args.Handled = true;
        };
        try
        {
            AppServices.Host = await BridgeHost.StartAsync();
            AppServices.Client = AppServices.Host.Client;
            var win = new MainWindow();
            MainWindow = win;
            win.Show();
        }
        catch (Exception ex)
        {
            MessageBox.Show("无法启动后端：\n" + ex.Message + "\n\n请确认已编译 native/build/pymcl-bridge.exe，或设置 PYMCL_HOME。",
                "PyMCL", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        AppServices.Host?.Dispose();
        base.OnExit(e);
    }
}
