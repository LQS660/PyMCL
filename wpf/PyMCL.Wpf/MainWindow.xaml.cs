using System.Windows;
using System.Windows.Controls;
using PyMCL.Pages;
using PyMCL.Services;

namespace PyMCL;

public partial class MainWindow : Window
{
    private readonly Dictionary<string, UserControl> _pages = new();

    public MainWindow()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            SelectNav("launch");
            if (AppServices.Client != null)
            {
                AppServices.Client.EventStreamStateChanged += (_, ok) =>
                    Dispatcher.Invoke(() => BridgeStatus.Text = ok ? "桥接已连接" : "桥接重连中…");
                AppServices.Client.EventReceived += OnBridgeEvent;
                BridgeStatus.Text = AppServices.Client.EventStreamConnected ? "桥接已连接" : "桥接连接中…";
            }
            await Task.CompletedTask;
        };
        Closed += (_, _) => AppServices.Host?.Dispose();
    }

    private void Minimize_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    private void Maximize_Click(object sender, RoutedEventArgs e) =>
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;

    private void Close_Click(object sender, RoutedEventArgs e) => Close();

    private void OnBridgeEvent(object? sender, BridgeEvent e)
    {
        Dispatcher.Invoke(() =>
        {
            if (e.Event is "progress" or "task_progress")
            {
                TaskProgress.Visibility = Visibility.Visible;
                if (e.Total > 0)
                    TaskProgress.Value = Math.Min(100, e.Current * 100.0 / e.Total);
                StatusText.Text = string.IsNullOrEmpty(e.Message) ? e.Text : e.Message;
            }
            else if (e.Event is "finished" or "task_finished")
            {
                TaskProgress.Visibility = Visibility.Collapsed;
                StatusText.Text = e.Success
                    ? (string.IsNullOrEmpty(e.Message) ? "完成" : e.Message)
                    : ("失败: " + e.Message);
            }
            else if (e.Event is "task_count_changed" or "tasks_changed" or "task_count")
            {
                NavTasks.Content = e.Count > 0 ? $"下载任务 ({e.Count})" : "下载任务";
            }
        });
    }

    private void Nav_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is string key)
            SelectNav(key);
    }

    private void SelectNav(string key)
    {
        NavLaunch.Tag = key == "launch" ? "selected" : "launch";
        NavInstance.Tag = key == "instance" ? "selected" : "instance";
        NavDownload.Tag = key == "download" ? "selected" : "download";
        NavSettings.Tag = key == "settings" ? "selected" : "settings";
        NavTasks.Tag = key == "tasks" ? "selected" : "tasks";

        PageTitle.Text = key switch
        {
            "launch" => "启动",
            "instance" => "实例",
            "download" => "下载",
            "settings" => "设置",
            "tasks" => "下载任务",
            _ => "PyMCL",
        };

        if (!_pages.TryGetValue(key, out var page))
        {
            page = key switch
            {
                "launch" => new LaunchPage(),
                "instance" => new InstancePage(),
                "download" => new DownloadPage(),
                "settings" => new SettingsPage(),
                "tasks" => new TasksPage(),
                _ => new LaunchPage(),
            };
            _pages[key] = page;
        }
        PageHost.Content = page;
    }
}
