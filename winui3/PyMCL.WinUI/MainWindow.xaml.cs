using Microsoft.UI;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using PyMCL.Models;
using PyMCL.Pages;
using PyMCL.Services;
using Windows.UI;
using WinRT.Interop;

namespace PyMCL;

public sealed partial class MainWindow : Window
{
    private LaunchPage? _launch;
    private InstancePage? _instance;
    private AccountPage? _account;
    private MultiplayerPage? _multiplayer;
    private DownloadHubPage? _download;
    private AiPage? _ai;
    private SettingsPage? _settings;
    private TasksPage? _tasks;
    private string _current = "launch";
    private bool _navLock;
    private int _navGen;
    private readonly Dictionary<string, string> _dockActive = new();
    private bool _dockExpanded;
    private readonly SemaphoreSlim _dockLock = new(1, 1);

    public MainWindow()
    {
        InitializeComponent();
        Title = "PyMCL 启动器 WinUI 3";
        AppServices.Dispatcher = DispatcherQueue;
        AppServices.Toast = ShowToast;
        AppServices.OpenDownload = OpenDownload;
        ApplyChrome();
        if (Content is FrameworkElement root)
            root.Loaded += OnLoaded;
    }

    private void ApplyChrome()
    {
        try
        {
            var hwnd = WindowNative.GetWindowHandle(this);
            AppServices.WindowHandle = hwnd;
            var id = Win32Interop.GetWindowIdFromWindow(hwnd);
            var app = AppWindow.GetFromWindowId(id);
            app.Resize(new Windows.Graphics.SizeInt32(1180, 760));
            ExtendsContentIntoTitleBar = true;
            SetTitleBar(AppTitleBar);
            var tb = app.TitleBar;
            tb.ExtendsContentIntoTitleBar = true;
            tb.ButtonBackgroundColor = Colors.Transparent;
            tb.ButtonInactiveBackgroundColor = Colors.Transparent;
            tb.ButtonHoverBackgroundColor = Color.FromArgb(24, 0, 0, 0);
            tb.ButtonPressedBackgroundColor = Color.FromArgb(48, 0, 0, 0);
        }
        catch { }

        try
        {
            if (MicaController.IsSupported())
                SystemBackdrop = new MicaBackdrop { Kind = MicaKind.Base };
            else if (DesktopAcrylicController.IsSupported())
                SystemBackdrop = new DesktopAcrylicBackdrop();
        }
        catch { }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            AppServices.Host = await BridgeHost.StartAsync();
            AppServices.Client = AppServices.Host.Client;
            AppServices.Client.EventReceived += OnBridgeEvent;
            _launch = new LaunchPage();
            _instance = new InstancePage();
            _account = new AccountPage();
            _multiplayer = new MultiplayerPage();
            _download = new DownloadHubPage();
            _ai = new AiPage();
            _settings = new SettingsPage();
            _tasks = new TasksPage();
            NavView.SelectedItem = NavView.MenuItems[0];
            SwapPage(_launch);
            await _launch.ReloadAsync();
        }
        catch (Exception ex)
        {
            ShowToast("启动失败", ex.Message, InfoBarSeverity.Error);
            ContentFrame.Content = new TextBlock
            {
                Text = "无法连接后端：\n" + ex.Message,
                Margin = new Thickness(28),
                TextWrapping = TextWrapping.Wrap,
            };
        }
    }

    private bool _dockSizing;

    private void Nav_PaneClosing(NavigationView sender, NavigationViewPaneClosingEventArgs args)
    {
        args.Cancel = true;
    }

    private void ContentRoot_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (_dockSizing) return;
        var next = Math.Clamp(Math.Max(0, e.NewSize.Width - 32), 1, 640);
        if (Math.Abs(DockHost.Width - next) < 0.5) return;
        _dockSizing = true;
        DockHost.Width = next;
        _dockSizing = false;
    }

    private void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (_navLock) return;
        if (args.SelectedItem is NavigationViewItem item && item.Tag is string key)
            Navigate(key);
    }

    public void Navigate(string key)
    {
        _current = key;
        FrameworkElement? page = key switch
        {
            "launch" => _launch,
            "instance" => _instance,
            "account" => _account,
            "multiplayer" => _multiplayer,
            "download" => _download,
            "ai" => _ai,
            "settings" => _settings,
            "tasks" => _tasks,
            _ => null,
        };
        var item = FindNav(key);
        if (item != null && !Equals(NavView.SelectedItem, item))
        {
            _navLock = true;
            NavView.SelectedItem = item;
            _navLock = false;
        }
        if (page != null)
            SwapPage(page);
        PlaceDock();
        _ = ReloadCurrentAsync();
    }

    private async void SwapPage(FrameworkElement page)
    {
        if (ReferenceEquals(ContentFrame.Content, page) && page.Opacity >= 0.99)
            return;
        var gen = ++_navGen;
        ContentFrame.ContentTransitions.Clear();
        if (ContentFrame.Content is UIElement old && !ReferenceEquals(old, page))
            await Motion.PageOutAsync(old);
        if (gen != _navGen) return;
        ContentFrame.Content = page;
        await Motion.PageInAsync(page);
    }

    private NavigationViewItem? FindNav(string key)
    {
        foreach (var o in NavView.MenuItems.Concat(NavView.FooterMenuItems))
        {
            if (o is NavigationViewItem n && n.Tag as string == key)
                return n;
        }
        return null;
    }

    public void OpenDownload(string? cat = null)
    {
        Navigate("download");
        if (cat != null)
            _download?.ShowCategory(cat);
    }

    private async Task ReloadCurrentAsync()
    {
        try
        {
            if (_current == "launch") await (_launch?.ReloadAsync() ?? Task.CompletedTask);
            else if (_current == "instance") await (_instance?.ReloadAsync() ?? Task.CompletedTask);
            else if (_current == "account") await (_account?.ReloadAsync() ?? Task.CompletedTask);
            else if (_current == "multiplayer") await (_multiplayer?.ReloadAsync() ?? Task.CompletedTask);
            else if (_current == "download") _download?.ReloadCurrent();
            else if (_current == "ai") await (_ai?.ReloadAsync() ?? Task.CompletedTask);
            else if (_current == "settings") await (_settings?.ReloadAsync() ?? Task.CompletedTask);
        }
        catch { }
    }

    private void OnBridgeEvent(object? sender, BridgeEvent ev)
    {
        AppServices.OnUi(() =>
        {
            _tasks?.HandleEvent(ev);
            _launch?.HandleEvent(ev);
            _ai?.HandleEvent(ev);
            HandleDock(ev);
            if (ev.Event == "task_count_changed")
            {
                if (ev.Count <= 0)
                {
                    TaskBadge.Visibility = Visibility.Collapsed;
                    TaskBadge.Value = 0;
                }
                else
                {
                    TaskBadge.Value = ev.Count > 99 ? 99 : ev.Count;
                    TaskBadge.Visibility = Visibility.Visible;
                }
            }
            if (ev.Event == "ui_changed")
                _ = ReloadCurrentAsync();
            if (ev.Event == "finished")
            {
                var title = ev.Title;
                if (!string.IsNullOrEmpty(ev.TaskId))
                    title = _tasks?.TitleOf(ev.TaskId) ?? title;
                if (!string.IsNullOrEmpty(title) && title.StartsWith("启动游戏", StringComparison.Ordinal))
                    return;
                if (ev.Success)
                    ShowToast(string.IsNullOrEmpty(title) ? "完成" : title, ev.Message, InfoBarSeverity.Success);
                else if (ev.Message != "已取消")
                    ShowToast(string.IsNullOrEmpty(title) ? "失败" : title, ev.Message, InfoBarSeverity.Error);
            }
        });
    }

    private void HandleDock(BridgeEvent ev)
    {
        if (ev.Event == "task_added" && !string.IsNullOrEmpty(ev.TaskId))
        {
            _dockActive[ev.TaskId] = ev.Title;
            DockTitle.Text = $"下载任务（{_dockActive.Count}）";
            DockStatus.Text = ev.Title;
            DockProgress.Value = 0;
            DockSpeed.Text = "";
            if (_dockActive.Count == 1) DockLog.Text = "";
            DockLog.Text += $"—— {ev.Title} ——\n";
            if (ev.Title.Contains("整合包") && !_dockExpanded)
            {
                _dockExpanded = true;
                DockLog.Visibility = Visibility.Visible;
                DockChevron.Glyph = "\uE70E";
            }
            PlaceDock();
        }
        else if (ev.Event == "progress" && _dockActive.ContainsKey(ev.TaskId))
        {
            if (ev.Total > 0) DockProgress.Value = ev.Current * 100.0 / ev.Total;
            SplitMsg(ev.Message, out var st, out var sp);
            DockStatus.Text = string.IsNullOrEmpty(st) ? _dockActive[ev.TaskId] : st;
            DockSpeed.Text = sp;
            DockTitle.Text = $"下载任务（{_dockActive.Count}）";
        }
        else if (ev.Event == "log" && _dockActive.ContainsKey(ev.TaskId) && !string.IsNullOrEmpty(ev.Text))
        {
            DockLog.Text += ev.Text + "\n";
        }
        else if (ev.Event == "finished")
        {
            _dockActive.Remove(ev.TaskId);
            if (!string.IsNullOrEmpty(ev.Message)) DockLog.Text += ev.Message + "\n";
            if (_dockActive.Count == 0)
            {
                DockTitle.Text = "下载任务";
                DockStatus.Text = ev.Success ? "✔ 全部完成" : (ev.Message ?? "已结束");
                DockSpeed.Text = "";
                if (ev.Success) DockProgress.Value = 100;
                PlaceDock();
            }
            else
            {
                DockTitle.Text = $"下载任务（{_dockActive.Count}）";
                DockStatus.Text = _dockActive.Values.FirstOrDefault() ?? "";
            }
        }
    }

    private async void PlaceDock()
    {
        await _dockLock.WaitAsync();
        try
        {
            var want = _dockActive.Count > 0 && _current != "tasks";
            if (want && DockHost.Visibility != Visibility.Visible)
                await Motion.DockShowAsync(DockHost);
            else if (!want && DockHost.Visibility == Visibility.Visible)
                await Motion.DockHideAsync(DockHost);
        }
        finally
        {
            _dockLock.Release();
        }
    }

    private async void DockToggle_Click(object sender, RoutedEventArgs e)
    {
        _dockExpanded = !_dockExpanded;
        DockChevron.Glyph = _dockExpanded ? "\uE70E" : "\uE70D";
        if (_dockExpanded)
        {
            DockLog.Visibility = Visibility.Visible;
            var t = Motion.Tx(DockLog);
            DockLog.Opacity = 0;
            t.TranslateY = 12;
            await Motion.AnimateAsync(DockLog, 1, 0, 0, 1, 200);
        }
        else
        {
            await Motion.AnimateAsync(DockLog, 0, 0, 10, 1, 140, EasingMode.EaseIn);
            DockLog.Visibility = Visibility.Collapsed;
            DockLog.Opacity = 1;
            Motion.Tx(DockLog).TranslateY = 0;
        }
    }

    public void ShowToast(string title, string message, InfoBarSeverity sev)
    {
        ToastBar.Title = title;
        ToastBar.Message = message;
        ToastBar.Severity = sev;
        ToastBar.IsOpen = true;
    }

    public static void SplitMsg(string? message, out string status, out string speed)
    {
        var text = message ?? "";
        if (text.Contains("  |  ", StringComparison.Ordinal))
        {
            var i = text.IndexOf("  |  ", StringComparison.Ordinal);
            status = text[..i].Trim();
            speed = text[(i + 5)..].Trim();
            return;
        }
        status = text;
        speed = "";
    }
}
