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
        // XAML 里不写死中文：这几处文案在这里按当前语言取
        Title = L("PyMCL 启动器");
        PageTitle.Text = L("启动");
        BridgeText.Text = L("连接中");
        ThemeBtn.ToolTip = L("切换深色 / 浅色");
        DropVeilTitle.Text = L("松手就装");
        DropVeilHint.Text = L("整合包、模组、资源包、光影、数据包、存档、皮肤、壁纸都认；认不准会问你一句。");
        AppServices.Window = this;
        Dlg.Host = DialogHost;

        Wallpaper.Attach(WallHost, ChromeBar, SideBar, PageWash);

        MinBtn.Click += (_, _) => WindowState = WindowState.Minimized;
        MaxBtn.Click += (_, _) => ToggleMax();
        CloseBtn.Click += (_, _) => Close();
        ThemeBtn.Click += (_, _) => ToggleTheme();
        StateChanged += (_, _) =>
        {
            SyncMaxGlyph();
            // 最小化时动态壁纸一帧也不用解：屏幕上看不见，解了也是白烧 CPU
            Wallpaper.SetWindowActive(WindowState != WindowState.Minimized);
        };
        Activated += (_, _) => Wallpaper.SetWindowActive(WindowState != WindowState.Minimized);
        Deactivated += (_, _) => Wallpaper.SetWindowActive(false);

        // 用 Preview 只为了亮提示罩：页面那一层也走隧道，亮罩不能被它们截掉。
        // 真正的落地仍挂在冒泡上（见 OnDrop），页面先接得住就轮不到主窗口。
        PreviewDragEnter += (_, e) => ShowDropVeil(e.Data.GetDataPresent(DataFormats.FileDrop));
        PreviewDragOver += (_, e) => ShowDropVeil(e.Data.GetDataPresent(DataFormats.FileDrop));
        PreviewDragLeave += (_, _) => ShowDropVeil(false);
        PreviewDrop += (_, _) => ShowDropVeil(false);
        DragEnter += OnDragOver;
        DragOver += OnDragOver;
        Drop += OnDrop;
        SideGrip.DragDelta += SideGrip_DragDelta;
        SideGrip.DragCompleted += SideGrip_DragCompleted;
        PreviewKeyDown += OnShortcut;
        Closing += OnClosing;
        Closed += (_, _) =>
        {
            Wallpaper.Shutdown();
            AppServices.Host?.Dispose();
        };

        TaskStore.Added += _ => Dispatcher.Invoke(SyncTasks);
        TaskStore.Updated += _ => Dispatcher.Invoke(SyncDock);
        TaskStore.Cleared += () => Dispatcher.Invoke(SyncTasks);

        LoadUiPrefs();
        BuildNav();
        BuildDock();
        Navigate("launch", instant: true);
        Loaded += (_, _) => Run(ConnectAsync);
    }

    // ==================== 桥接 ====================
    private bool _drained;

    /// <summary>
    /// 关窗先让桥收拢后台任务（shutdown，预算 800ms），再杀进程；直接 Kill 会把下载砍在半截。
    /// e.Cancel 得在同步段就置好（事件返回后 WPF 立刻读它），异步的收拢走统一的 Run。
    /// </summary>
    private void OnClosing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        if (_drained || !_bridgeReady) return;
        e.Cancel = true;
        _drained = true;
        Run(async () =>
        {
            try
            {
                var drain = AppServices.Client.TryCallAsync<object>("shutdown", new { timeout_ms = 800 });
                await Task.WhenAny(drain, Task.Delay(1500));
            }
            catch { }
            Close();
        });
    }

    private readonly TaskCompletionSource _bridgeSettled = new(TaskCreationOptions.RunContinuationsAsynchronously);

    /// <summary>连桥这件事有结果了（连上或确定连不上）。冒烟脚本靠它决定什么时候开始逐页走。</summary>
    public Task BridgeSettled => _bridgeSettled.Task;

    private async Task ConnectAsync()
    {
        SetBridgeState(L("连接中"), "B.Warn");
        try
        {
            var host = await BridgeHost.StartAsync();
            AppServices.Host = host;
            AppServices.Client = host.Client;
            host.Client.EventReceived += OnBridgeEvent;
            host.Client.StreamStateChanged += (_, ok) => Dispatcher.BeginInvoke(() =>
            {
                SetBridgeState(ok ? host.Backend : L("重连中"), ok ? "B.Accent" : "B.Warn");
                BridgePill.ToolTip = ok
                    ? $"{host.Backend} · 127.0.0.1:{host.Port}"
                    : L("事件流断开：") + host.Client.LastStreamError;
            });
            _bridgeReady = true;
            SetBridgeState(host.Backend, "B.Accent");
            // 侧栏排法跟 Qt / 网页版共用 config.json 里的 ui_nav_*，连上桥才知道用户排成了什么样
            await LoadNavFromBridgeAsync();
            // 壁纸配置也在 config.json 里（ui_background*），跟 Qt / 网页版是同一份
            await Wallpaper.ReloadAsync();
            await ReloadCurrentAsync();
            _bridgeSettled.TrySetResult();
            // 第一次开：先把目录 / 下载源问清楚，顺带指一遍容易错过的功能。
            // 冒烟模式跳过——它是个等人点的框，无人值守时会把整轮挂死。
            if (!Smoke.Active) await FirstRunWizard.MaybeShowAsync();
            // 再问一次「是否上传诊断数据」（对齐 Qt _boot_extras 的顺序：向导 → 同意提示）；选过就不再弹
            if (!Smoke.Active) await FeedbackConsent.MaybeAskAsync();
            _ = WarmUpAsync();
        }
        catch (Exception ex)
        {
            SetBridgeState(L("未连接"), "B.Danger");
            _bridgeSettled.TrySetResult();
            if (Smoke.Active)
            {
                // 冒烟要的就是「桥没起来会不会崩」这条降级路径，不能在这儿停下来等人选
                Smoke.Note("bridge", ex.ToString());
                return;
            }
            var retry = await Dlg.Confirm(L("连接后端失败"),
                ex.Message + L("\n\n需要仓库根目录下的 bridge/server.py 或 native/build/pymcl-bridge.exe。"),
                L("重试"), L("退出"));
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
            case "finished" when !ev.Success && ev.Message is { Length: > 0 } && ev.Message != "已取消": // i18n:ignore 桥返回的原文，不是界面词
                Toast(TaskStore.Get(ev.TaskId)?.Title ?? L("任务失败"), ev.Message, ToastKind.Error);
                break;
            case "finished" when ev.Success:
                var t = TaskStore.Get(ev.TaskId);
                if (t != null && !t.Title.StartsWith("启动游戏", StringComparison.Ordinal)) // i18n:ignore 桥起的任务标题原文
                    Toast(t.Title, string.IsNullOrEmpty(ev.Message) ? L("已完成") : ev.Message, ToastKind.Success);
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

    private void RefreshTick(object? sender, EventArgs e)
    {
        _refreshTimer?.Stop();
        if (_current is { } page) Run(page.RefreshAsync);
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

    /// <summary>主窗口的异步处理器也走 PageBase.Run 这一个口子（异常兜底 + 冒烟计数），只是提示标题不同。</summary>
    private static void Run(Func<Task> work) => PageBase.Run(work, L("出错"));

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

    // ==================== 拖拽安装 ====================
    /// <summary>
    /// 拖文件进窗口：整合包 / 模组 / 资源包 / 光影 / 数据包 / 存档 / 皮肤 / 壁纸都认，
    /// 认不准的弹一次框让用户指。判定口径与 Qt 端 app/file_kinds.py 同一套。
    /// </summary>
    /// <summary>拖着文件在窗口上方时亮一层提示罩，松手或拖走就收掉。</summary>
    private void ShowDropVeil(bool on)
    {
        if (!_bridgeReady) on = false;
        if (on == (DropVeil.Visibility == Visibility.Visible)) return;
        if (on)
        {
            DropVeil.Visibility = Visibility.Visible;
            Motion.Fade(DropVeil, 1, 120);
        }
        else Motion.FadeOut(DropVeil, 110, () => DropVeil.Visibility = Visibility.Collapsed);
    }

    private void OnDragOver(object sender, DragEventArgs e)
    {
        e.Effects = _bridgeReady && e.Data.GetDataPresent(DataFormats.FileDrop)
            ? DragDropEffects.Copy
            : DragDropEffects.None;
        e.Handled = true;
    }

    private void OnDrop(object sender, DragEventArgs e)
    {
        e.Handled = true;
        if (!_bridgeReady || !e.Data.GetDataPresent(DataFormats.FileDrop)) return;
        if (e.Data.GetData(DataFormats.FileDrop) is not string[] paths || paths.Length == 0) return;
        Activate();
        Run(() => FileDrop.HandleAsync(this, paths));
    }

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
        var openBtn = Ui.Btn(L("查看"), BtnKind.Soft, (_, _) => Navigate("tasks"));
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
        // 下载坞只报下载类任务。启动游戏 / 登录那几条有自己的界面在管，
        // 归类口径问后端（is_download_title），别在前端各写一套。
        var running = TaskStore.Rows.LastOrDefault(r => !r.Finished && IsDownloadTitle(r.Title));
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

    private readonly Dictionary<string, bool> _downloadTitle = new();

    /// <summary>
    /// 这个任务标题算不算「下载」。后端 is_download_title 说了算，问过的标题记下来——
    /// SyncDock 每条进度事件都会跑一遍，不能每次都发一次 RPC。
    /// 还没问到答案时先当下载显示，答案回来再纠正，不会闪。
    /// </summary>
    private bool IsDownloadTitle(string title)
    {
        if (string.IsNullOrEmpty(title)) return true;
        if (_downloadTitle.TryGetValue(title, out var hit)) return hit;
        _downloadTitle[title] = true;
        Run(async () =>
        {
            var ok = await AppServices.Client.TryCallAsync<bool>("is_download_title", new { title }, true);
            if (_downloadTitle.TryGetValue(title, out var was) && was == ok) return;
            _downloadTitle[title] = ok;
            SyncDock();
        });
        return true;
    }

    // ==================== 飞入动画 ====================
    /// <summary>从来源控件飞一个小球到侧栏「下载任务」，告诉用户任务已经进队列了。</summary>
    public void FlyToTasks(FrameworkElement source, string text = "", string? colorKey = null)
    {
        if (!Motion.Enabled || !IsLoaded) return;
        var target = _navRows.TryGetValue("tasks", out var row) ? row.Button : null;
        if (target is null || !source.IsVisible || !target.IsVisible) return;
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
            Child = Ui.Txt(string.IsNullOrEmpty(text) ? L("已加入队列") : text, 11.5, true, "B.OnAccent"),
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
