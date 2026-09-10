using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using PyMCL.Pages;
using PyMCL.Services;

namespace PyMCL;

public partial class MainWindow : Window
{
    private readonly Dictionary<string, PageBase> _pages = new();
    private PageBase? _current;
    private string _currentId = "";
    private Border? _dockCard;
    private ProgressBar? _dockBar;
    private TextBlock? _dockTitle, _dockStatus;
    private bool _bridgeReady;

    public string CurrentPageId => _currentId;

    public MainWindow()
    {
        InitializeComponent();
        AppServices.Window = this;
        Dlg.Host = DialogHost;

        MinBtn.Click += (_, _) => WindowState = WindowState.Minimized;
        MaxBtn.Click += (_, _) => ToggleMax();
        CloseBtn.Click += (_, _) => Close();
        ThemeBtn.Click += (_, _) => ToggleTheme();
        StateChanged += (_, _) => SyncMaxGlyph();
        SideGrip.DragDelta += SideGrip_DragDelta;
        PreviewKeyDown += OnShortcut;
        Closed += (_, _) => AppServices.Host?.Dispose();

        TaskStore.Added += _ => Dispatcher.Invoke(SyncTasks);
        TaskStore.Updated += _ => Dispatcher.Invoke(SyncDock);
        TaskStore.Cleared += () => Dispatcher.Invoke(SyncTasks);

        LoadUiPrefs();
        BuildNav();
        BuildDock();
        Navigate("launch", instant: true);
        Loaded += async (_, _) => await ConnectAsync();
    }

    // ==================== 桥接 ====================
    private async Task ConnectAsync()
    {
        SetBridgeState("连接中", "B.Warn");
        try
        {
            var host = await BridgeHost.StartAsync();
            AppServices.Host = host;
            AppServices.Client = host.Client;
            host.Client.EventReceived += OnBridgeEvent;
            host.Client.StreamStateChanged += (_, ok) => Dispatcher.BeginInvoke(() =>
            {
                SetBridgeState(ok ? host.Backend : "重连中", ok ? "B.Accent" : "B.Warn");
                BridgePill.ToolTip = ok
                    ? $"{host.Backend} · 127.0.0.1:{host.Port}"
                    : "事件流断开：" + host.Client.LastStreamError;
            });
            _bridgeReady = true;
            SetBridgeState(host.Backend, "B.Accent");
            await ReloadCurrentAsync();
            _ = WarmUpAsync();
        }
        catch (Exception ex)
        {
            SetBridgeState("未连接", "B.Danger");
            var retry = await Dlg.Confirm("连接后端失败",
                ex.Message + "\n\n需要仓库根目录下的 bridge/server.py 或 native/build/pymcl-bridge.exe。",
                "重试", "退出");
            if (retry) await ConnectAsync();
            else Close();
        }
    }

    /// <summary>窗口空闲时预热重资源页面，切过去就是现成的。</summary>
    private async Task WarmUpAsync()
    {
        await Task.Delay(900);
        foreach (var id in new[] { "instance", "version", "tasks" })
        {
            if (_currentId == id) continue;
            var p = GetPage(id);
            if (p != null) await p.EnsureLoadedAsync();
            await Task.Delay(140);
        }
    }

    private void SetBridgeState(string text, string brushKey)
    {
        BridgeText.Text = text;
        BridgeDot.SetResourceReference(System.Windows.Shapes.Shape.FillProperty, brushKey);
    }

    private void OnBridgeEvent(object? sender, BridgeEvent ev)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(DispatcherPriority.Background, () => OnBridgeEvent(sender, ev));
            return;
        }
        TaskStore.Handle(ev);
        switch (ev.Event)
        {
            case "task_count_changed":
                SyncTasks();
                break;
            case "ui_changed":
                ScheduleRefresh();
                break;
            case "finished" when !ev.Success && ev.Message is { Length: > 0 } && ev.Message != "已取消":
                Toast(TaskStore.Get(ev.TaskId)?.Title ?? "任务失败", ev.Message, ToastKind.Error);
                break;
            case "finished" when ev.Success:
                var t = TaskStore.Get(ev.TaskId);
                if (t != null && !t.Title.StartsWith("启动游戏", StringComparison.Ordinal))
                    Toast(t.Title, string.IsNullOrEmpty(ev.Message) ? "已完成" : ev.Message, ToastKind.Success);
                break;
        }
        foreach (var p in _pages.Values) p.OnEvent(ev);
        SyncDock();
    }

    private DispatcherTimer? _refreshTimer;

    /// <summary>ui_changed 会连着来好几条，这里合并成一次刷新。</summary>
    private void ScheduleRefresh()
    {
        _refreshTimer ??= new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(420) };
        _refreshTimer.Stop();
        _refreshTimer.Tick -= RefreshTick;
        _refreshTimer.Tick += RefreshTick;
        _refreshTimer.Start();
    }

    private async void RefreshTick(object? sender, EventArgs e)
    {
        _refreshTimer?.Stop();
        if (_current != null)
        {
            try { await _current.RefreshAsync(); }
            catch { }
        }
    }

    private async Task ReloadCurrentAsync()
    {
        if (_current is null) return;
        await _current.EnsureLoadedAsync();
        _current.OnShown();
    }

    // ==================== 导航 ====================
    public void Navigate(string id, bool instant = false)
    {
        if (_currentId == id) return;
        var page = GetPage(id);
        if (page is null) return;
        var forward = NavOrderIndex(id) >= NavOrderIndex(_currentId);
        _current?.OnHidden();
        _currentId = id;
        _current = page;
        PageTitle.Text = page.Title;
        SyncNavSelection();
        if (instant || !Motion.Enabled) PageHost.Content = page;
        else Motion.PageSwap(PageHost, page, forward);
        SyncDock();
        if (_bridgeReady) Run(async () =>
        {
            await page.EnsureLoadedAsync();
            page.OnShown();
        });
    }

    private static async void Run(Func<Task> work)
    {
        try { await work(); }
        catch (Exception ex) { AppServices.Toast("出错", ex.Message, ToastKind.Error); }
    }

    public PageBase? GetPage(string id)
    {
        if (_pages.TryGetValue(id, out var p)) return p;
        var def = NavDefs.FirstOrDefault(d => d.Id == id);
        if (def is null) return null;
        p = def.Create();
        p.Id = id;
        _pages[id] = p;
        return p;
    }

    // ==================== 窗口 ====================
    private void ToggleMax() =>
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;

    private void SyncMaxGlyph()
    {
        var max = WindowState == WindowState.Maximized;
        MaxBtn.Content = max ? "\uE923" : "\uE922";
        RootBorder.BorderThickness = new Thickness(max ? 0 : 1);
    }

    private void ToggleTheme()
    {
        var dark = !App.IsDark;
        App.ApplyTheme(dark);
        ThemeBtn.Content = dark ? "\uE706" : "\uE708";
        SaveUiPrefs();
        if (_bridgeReady)
            _ = AppServices.Client.TryCallAsync<object>("update_settings", new { settings = new { ui_dark = dark } });
        Motion.Pulse(ThemeBtn, 1.14);
    }

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);
        var handle = new WindowInteropHelper(this).Handle;
        HwndSource.FromHwnd(handle)?.AddHook(WndProc);
        SyncMaxGlyph();
    }

    private void OnShortcut(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.F5)
        {
            if (_current != null) Run(async () => await _current.RefreshAsync());
            e.Handled = true;
            return;
        }
        if (Keyboard.Modifiers != ModifierKeys.Control) return;
        var idx = e.Key switch
        {
            Key.D1 => 0, Key.D2 => 1, Key.D3 => 2, Key.D4 => 3, Key.D5 => 4,
            Key.D6 => 5, Key.D7 => 6, Key.D8 => 7, Key.D9 => 8, _ => -1,
        };
        if (idx >= 0)
        {
            var visible = VisibleFlatOrder();
            if (idx < visible.Count) Navigate(visible[idx]);
            e.Handled = true;
        }
        else if (e.Key == Key.OemComma)
        {
            Navigate("settings");
            e.Handled = true;
        }
    }

    // 最大化时不盖住任务栏（WPF 无边框窗默认会溢出工作区）。
    private static IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg != 0x0024) return IntPtr.Zero;
        var mmi = Marshal.PtrToStructure<MINMAXINFO>(lParam);
        var monitor = MonitorFromWindow(hwnd, 2);
        if (monitor != IntPtr.Zero)
        {
            var info = new MONITORINFO { cbSize = Marshal.SizeOf<MONITORINFO>() };
            if (GetMonitorInfo(monitor, ref info))
            {
                var work = info.rcWork;
                var full = info.rcMonitor;
                mmi.ptMaxPosition.x = Math.Abs(work.left - full.left);
                mmi.ptMaxPosition.y = Math.Abs(work.top - full.top);
                mmi.ptMaxSize.x = Math.Abs(work.right - work.left);
                mmi.ptMaxSize.y = Math.Abs(work.bottom - work.top);
                mmi.ptMinTrackSize.x = 900;
                mmi.ptMinTrackSize.y = 580;
                Marshal.StructureToPtr(mmi, lParam, true);
                handled = true;
            }
        }
        return IntPtr.Zero;
    }

    [StructLayout(LayoutKind.Sequential)] private struct POINT { public int x, y; }
    [StructLayout(LayoutKind.Sequential)] private struct RECT { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct MINMAXINFO
    {
        public POINT ptReserved, ptMaxSize, ptMaxPosition, ptMinTrackSize, ptMaxTrackSize;
    }
    [StructLayout(LayoutKind.Sequential)] private struct MONITORINFO
    {
        public int cbSize;
        public RECT rcMonitor, rcWork;
        public int dwFlags;
    }

    [DllImport("user32.dll")] private static extern IntPtr MonitorFromWindow(IntPtr hwnd, int flags);
    [DllImport("user32.dll")] private static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFO info);

    // ==================== 通知 ====================
    public void Toast(string title, string body = "", ToastKind kind = ToastKind.Info)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(() => Toast(title, body, kind));
            return;
        }
        while (ToastHost.Children.Count >= 4) ToastHost.Children.RemoveAt(0);
        var (glyph, accent) = kind switch
        {
            ToastKind.Success => (Ico.Success, "B.Ok"),
            ToastKind.Warning => (Ico.Warning, "B.Warn"),
            ToastKind.Error => (Ico.Error, "B.Danger"),
            _ => (Ico.Info, "B.Info"),
        };
        var bar = new Border { Width = 3, CornerRadius = new CornerRadius(2) };
        bar.SetResourceReference(Border.BackgroundProperty, accent);
        var texts = Ui.V(2,
            Ui.Txt(title, 13, true).Wrap(),
            string.IsNullOrWhiteSpace(body) ? null : Ui.Muted(body.Length > 220 ? body[..220] + "…" : body));
        texts.MaxWidth = 300;
        var card = new Border
        {
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(12, 10, 14, 11),
            BorderThickness = new Thickness(1),
            Margin = new Thickness(0, 0, 0, 8),
            Cursor = Cursors.Hand,
            Child = Ui.H(10, bar, Ui.Glyph(glyph, 15, accent), texts),
        };
        card.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        card.SetResourceReference(Border.BorderBrushProperty, "B.Line");
        Motion.Shadow(card, 22, 0.14, 4);
        ToastHost.Children.Add(card);
        Motion.SlideIn(card);

        var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(kind == ToastKind.Error ? 7 : 4) };
        void Kill()
        {
            timer.Stop();
            if (!ToastHost.Children.Contains(card)) return;
            Motion.SlideOut(card, () => ToastHost.Children.Remove(card));
        }
        timer.Tick += (_, _) => Kill();
        timer.Start();
        card.MouseLeftButtonUp += (_, _) => Kill();
        card.MouseEnter += (_, _) => timer.Stop();
        card.MouseLeave += (_, _) => timer.Start();
    }

    // ==================== 下载坞 ====================
    private void BuildDock()
    {
        _dockTitle = Ui.Txt("", 12.5, true).Trim();
        _dockStatus = Ui.Small("");
        _dockBar = Ui.Prog();
        _dockBar.Height = 4;
        var openBtn = Ui.Btn("查看", BtnKind.Soft, (_, _) => Navigate("tasks"));
        openBtn.Padding = new Thickness(11, 4, 11, 5);
        var grid = Ui.G(null, "Auto,*,Auto");
        grid.Add(Ui.Glyph(Ico.Download, 15, "B.Accent").M(0, 0, 10, 0), 0, 0);
        grid.Add(Ui.V(3, _dockTitle, _dockStatus, _dockBar).VCenter(), 0, 1);
        grid.Add(openBtn.M(12, 0, 0, 0).VCenter(), 0, 2);
        _dockCard = new Border
        {
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(14, 10, 12, 11),
            BorderThickness = new Thickness(1),
            Child = grid,
        };
        _dockCard.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        _dockCard.SetResourceReference(Border.BorderBrushProperty, "B.Line");
        Motion.Shadow(_dockCard, 26, 0.14, 5);
        DockHost.Child = _dockCard;
    }

    private void SyncDock()
    {
        var running = TaskStore.Rows.LastOrDefault(r => !r.Finished);
        var show = running != null && _currentId != "tasks";
        if (!show)
        {
            if (DockHost.Visibility == Visibility.Visible)
                Motion.FadeOut(DockHost, 140, () => DockHost.Visibility = Visibility.Collapsed);
            return;
        }
        if (DockHost.Visibility != Visibility.Visible)
        {
            DockHost.Visibility = Visibility.Visible;
            Motion.FadeIn(DockHost, 220, 14);
        }
        _dockTitle!.Text = running!.Title;
        _dockStatus!.Text = string.IsNullOrEmpty(running.Speed) ? running.Status : running.Status + "    " + running.Speed;
        _dockBar!.IsIndeterminate = running.Indeterminate;
        if (!running.Indeterminate) Motion.Progress(_dockBar, running.Progress);
    }

    // ==================== 飞入动画 ====================
    /// <summary>从来源控件飞一个小球到侧栏「下载任务」，告诉用户任务已经进队列了。</summary>
    public void FlyToTasks(FrameworkElement source, string text = "", string? colorKey = null)
    {
        if (!Motion.Enabled || !IsLoaded) return;
        var target = _navRows.TryGetValue("tasks", out var row) ? row : null;
        if (target is null || !source.IsVisible) return;
        Point from, to;
        try
        {
            from = source.TransformToAncestor(this).Transform(new Point(source.ActualWidth / 2, source.ActualHeight / 2));
            to = target.TransformToAncestor(this).Transform(new Point(target.ActualWidth / 2, target.ActualHeight / 2));
        }
        catch { return; }

        var chip = new Border
        {
            CornerRadius = new CornerRadius(999),
            Padding = new Thickness(10, 4, 10, 5),
            Child = Ui.Txt(string.IsNullOrEmpty(text) ? "已加入队列" : text, 11.5, true, "B.OnAccent"),
        };
        chip.SetResourceReference(Border.BackgroundProperty, colorKey ?? "B.Accent");
        Motion.Shadow(chip, 16, 0.3, 3);
        FlyHost.Children.Add(chip);
        chip.Measure(new Size(500, 60));
        var w = chip.DesiredSize.Width;
        var h = chip.DesiredSize.Height;
        Canvas.SetLeft(chip, from.X - w / 2);
        Canvas.SetTop(chip, from.Y - h / 2);

        var tt = new TranslateTransform();
        var sc = new ScaleTransform(0.7, 0.7);
        var grp = new TransformGroup();
        grp.Children.Add(sc);
        grp.Children.Add(tt);
        chip.RenderTransform = grp;
        chip.RenderTransformOrigin = new Point(0.5, 0.5);

        var dur = TimeSpan.FromMilliseconds(620);
        var ease = new CubicEase { EasingMode = EasingMode.EaseInOut };
        var ax = new DoubleAnimation(0, to.X - from.X, dur) { EasingFunction = ease };
        var ky = new DoubleAnimationUsingKeyFrames { Duration = dur };
        var dy = to.Y - from.Y;
        ky.KeyFrames.Add(new EasingDoubleKeyFrame(dy * 0.28 - 46, KeyTime.FromPercent(0.45), new CubicEase { EasingMode = EasingMode.EaseOut }));
        ky.KeyFrames.Add(new EasingDoubleKeyFrame(dy, KeyTime.FromPercent(1), new CubicEase { EasingMode = EasingMode.EaseIn }));
        var fade = new DoubleAnimationUsingKeyFrames { Duration = dur };
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.15)));
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(1, KeyTime.FromPercent(0.72)));
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1)));
        var shrink = new DoubleAnimation(0.7, 0.42, dur) { EasingFunction = ease };
        shrink.Completed += (_, _) =>
        {
            FlyHost.Children.Remove(chip);
            if (target != null) Motion.Pulse(target, 1.06);
        };
        tt.BeginAnimation(TranslateTransform.XProperty, ax);
        tt.BeginAnimation(TranslateTransform.YProperty, ky);
        chip.BeginAnimation(OpacityProperty, fade);
        sc.BeginAnimation(ScaleTransform.ScaleXProperty, shrink);
        sc.BeginAnimation(ScaleTransform.ScaleYProperty, shrink.Clone());
    }
}
