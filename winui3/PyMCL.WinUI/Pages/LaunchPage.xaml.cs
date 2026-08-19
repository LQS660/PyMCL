using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class LaunchPage : UserControl
{
    private string? _taskId;
    private string? _loginTaskId;
    private List<JavaOption> _javaOpts = new();
    private bool _syncingJava;
    private ContentDialog? _loginDlg;
    private TextBlock? _loginHint;
    private TextBlock? _loginCode;
    private string _loginUri = "";
    private int _layoutMode = -1;
    private bool _layoutBusy;
    private bool _crashShown;

    public LaunchPage()
    {
        InitializeComponent();
        Loaded += OnFirstLoaded;
    }

    private void OnFirstLoaded(object sender, RoutedEventArgs e)
    {
        Loaded -= OnFirstLoaded;
        Motion.EnableHoverLift(Banner, 1.02);
        Motion.EnableHoverLift(LaunchBtn, 1.07);
        Motion.EnableHoverLift(ConfigCard, 1.02);
        Motion.EnableHoverLift(LogCard, 1.015);
        Motion.StartShine(Shine, ShineTx);
        ApplyResponsive(ActualWidth);
    }

    private void Page_SizeChanged(object sender, SizeChangedEventArgs e) => ApplyResponsive(e.NewSize.Width);

    private void ApplyResponsive(double width)
    {
        if (_layoutBusy || width <= 0 || BodyCol0 is null) return;
        var narrow = width < 760;
        var tight = width < 560;
        var mode = tight ? 2 : narrow ? 1 : 0;
        if (mode == _layoutMode) return;
        _layoutMode = mode;
        _layoutBusy = true;
        LaunchRoot.Padding = tight ? new Thickness(12, 10, 12, 10) : narrow ? new Thickness(16, 14, 16, 14) : new Thickness(28, 20, 28, 20);
        Banner.Height = narrow ? double.NaN : 180;
        Banner.MinHeight = tight ? 120 : 132;
        BannerInner.Padding = tight ? new Thickness(16, 14, 16, 14) : new Thickness(32, 22, 32, 22);
        BannerTitle.FontSize = tight ? 22 : 30;

        if (narrow)
        {
            BannerCol1.Width = new GridLength(0);
            BannerRow1.Height = GridLength.Auto;
            Grid.SetColumn(BannerBtns, 0);
            Grid.SetRow(BannerBtns, 1);
            BannerBtns.Margin = new Thickness(0, 12, 0, 0);
            BannerBtns.HorizontalAlignment = HorizontalAlignment.Left;
            LaunchBtn.Width = tight ? double.NaN : 170;
            StopBtn.Width = tight ? double.NaN : 170;
            if (tight)
            {
                LaunchBtn.HorizontalAlignment = HorizontalAlignment.Stretch;
                StopBtn.HorizontalAlignment = HorizontalAlignment.Stretch;
            }

            BodyCol0.Width = new GridLength(1, GridUnitType.Star);
            BodyCol1.Width = new GridLength(0);
            BodyRow0.Height = GridLength.Auto;
            BodyRow1.Height = new GridLength(1, GridUnitType.Star);
            Grid.SetColumn(LogCard, 0);
            Grid.SetRow(LogCard, 1);
            ConfigScroll.MaxHeight = 280;
        }
        else
        {
            BannerCol1.Width = GridLength.Auto;
            BannerRow1.Height = new GridLength(0);
            Grid.SetColumn(BannerBtns, 1);
            Grid.SetRow(BannerBtns, 0);
            BannerBtns.Margin = new Thickness(0);
            BannerBtns.HorizontalAlignment = HorizontalAlignment.Right;
            LaunchBtn.Width = 170;
            StopBtn.Width = 170;
            LaunchBtn.HorizontalAlignment = HorizontalAlignment.Stretch;
            StopBtn.HorizontalAlignment = HorizontalAlignment.Stretch;

            BodyCol0.Width = new GridLength(Math.Min(360, Math.Max(280, width * 0.38)));
            BodyCol1.Width = new GridLength(1, GridUnitType.Star);
            BodyRow0.Height = new GridLength(1, GridUnitType.Star);
            BodyRow1.Height = new GridLength(0);
            Grid.SetColumn(LogCard, 1);
            Grid.SetRow(LogCard, 0);
            ConfigScroll.MaxHeight = double.PositiveInfinity;
        }
        _layoutBusy = false;
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        var insts = await AppServices.Client.CallAsync<List<InstanceInfo>>("get_instances") ?? new();
        var cur = InstanceBox.SelectedItem as string;
        InstanceBox.SelectionChanged -= Instance_Changed;
        InstanceBox.Items.Clear();
        foreach (var i in insts) InstanceBox.Items.Add(i.Name);
        if (cur != null && insts.Any(x => x.Name == cur)) InstanceBox.SelectedItem = cur;
        else if (InstanceBox.Items.Count > 0) InstanceBox.SelectedIndex = 0;
        InstanceBox.SelectionChanged += Instance_Changed;

        var acc = await AppServices.Client.CallAsync<List<string>>("get_accounts") ?? new();
        var curA = AccountBox.SelectedItem as string;
        AccountBox.Items.Clear();
        foreach (var a in acc) AccountBox.Items.Add(a);
        if (curA != null && acc.Contains(curA)) AccountBox.SelectedItem = curA;
        else if (AccountBox.Items.Count > 0) AccountBox.SelectedIndex = 0;

        await ReloadVersionsAsync();
        await ReloadJavaAsync(false);
        _ = ReloadJavaAsync(true);
        SyncBanner(insts);
    }

    private async Task ReloadVersionsAsync()
    {
        var inst = InstanceBox.SelectedItem as string ?? "default";
        var ids = await AppServices.Client.CallAsync<List<string>>("get_installed_versions", new { instance = inst }) ?? new();
        var cur = VersionBox.SelectedItem as string;
        VersionBox.SelectionChanged -= Version_Changed;
        VersionBox.Items.Clear();
        foreach (var v in ids) VersionBox.Items.Add(v);
        if (cur != null && ids.Contains(cur)) VersionBox.SelectedItem = cur;
        else if (VersionBox.Items.Count > 0) VersionBox.SelectedIndex = 0;
        VersionBox.SelectionChanged += Version_Changed;
    }

    private async Task ReloadJavaAsync(bool scan)
    {
        var inst = InstanceBox.SelectedItem as string ?? "default";
        var opts = await AppServices.Client.CallAsync<List<JavaOption>>("java_combo_options",
            new { instance = inst, scan_system = scan }) ?? new();
        if ((InstanceBox.SelectedItem as string ?? "default") != inst) return;
        _syncingJava = true;
        try
        {
            _javaOpts = opts;
            var want = await AppServices.Client.CallAsync<string>("java_combo_label_for",
                new { instance = inst, options = opts }) ?? "自动选择";
            JavaBox.SelectionChanged -= Java_Changed;
            JavaBox.Items.Clear();
            foreach (var o in opts) JavaBox.Items.Add(o.Label);
            JavaBox.SelectedItem = opts.Any(o => o.Label == want) ? want : (opts.FirstOrDefault()?.Label);
            JavaBox.SelectionChanged += Java_Changed;
        }
        finally { _syncingJava = false; }
    }

    private async void Instance_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (AppServices.Client is null) return;
        await ReloadVersionsAsync();
        await ReloadJavaAsync(false);
        _ = ReloadJavaAsync(true);
        var insts = await AppServices.Client.CallAsync<List<InstanceInfo>>("get_instances") ?? new();
        SyncBanner(insts);
    }

    private async void Version_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var insts = await AppServices.Client.CallAsync<List<InstanceInfo>>("get_instances") ?? new();
        SyncBanner(insts);
    }

    private async void Java_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_syncingJava || AppServices.Client is null) return;
        var inst = InstanceBox.SelectedItem as string;
        if (string.IsNullOrEmpty(inst)) return;
        try { await AppServices.Client.CallAsync("set_instance_java", new { name = inst, java = SelectedJava() }); }
        catch { }
    }

    private void Memory_Changed(object sender, Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        if (MemoryLabel != null)
            MemoryLabel.Text = $"{(int)MemorySlider.Value} MB";
    }

    private string SelectedJava()
    {
        var text = JavaBox.SelectedItem as string ?? "自动选择";
        return _javaOpts.FirstOrDefault(o => o.Label == text)?.Value ?? text;
    }

    private void SyncBanner(List<InstanceInfo> insts)
    {
        var version = VersionBox.SelectedItem as string ?? "—";
        var instance = InstanceBox.SelectedItem as string ?? "default";
        var row = insts.FirstOrDefault(x => x.Name == instance);
        if (row != null && !string.IsNullOrEmpty(row.Pack))
        {
            var bits = new List<string>();
            if (!string.IsNullOrEmpty(row.PackVersion)) bits.Add(row.PackVersion);
            if (!string.IsNullOrEmpty(row.McVersion)) bits.Add("Minecraft " + row.McVersion);
            bits.Add("实例 " + instance);
            BannerTitle.Text = row.Pack;
            BannerSub.Text = string.Join(" · ", bits);
        }
        else
        {
            BannerTitle.Text = version;
            BannerSub.Text = $"实例 {instance} · 点击「启动游戏」进入世界";
        }
    }

    private async void Launch_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var version = VersionBox.SelectedItem as string;
        if (string.IsNullOrEmpty(version))
        {
            AppServices.Toast?.Invoke("没有版本", "请先到下载页安装原版游戏", InfoBarSeverity.Warning);
            return;
        }
        LogEdit.Text = "";
        LaunchProgress.Value = 0;
        StatusLabel.Text = "准备启动…";
        LaunchBtn.IsEnabled = false;
        StopBtn.IsEnabled = true;
        _crashShown = false;
        _ = Motion.PulseOnceAsync(LaunchBtn);
        try
        {
            _taskId = await AppServices.Client.StartTaskAsync("launch_game", new
            {
                instance = InstanceBox.SelectedItem as string ?? "default",
                version,
                account = AccountBox.SelectedItem as string ?? "离线模式",
                username = UsernameEdit.Text?.Trim() ?? "Player",
                memory_mb = (int)MemorySlider.Value,
                width = (int)WidthSpin.Value,
                height = (int)HeightSpin.Value,
                java = SelectedJava(),
            });
        }
        catch (Exception ex)
        {
            LaunchBtn.IsEnabled = true;
            StopBtn.IsEnabled = false;
            AppServices.Toast?.Invoke("启动失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        if (_taskId is null || AppServices.Client is null) return;
        try { await AppServices.Client.CallAsync("cancel_task", new { task_id = _taskId }); }
        catch { }
    }

    private async void Login_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null || _loginDlg != null) return;
        _loginHint = new TextBlock { Text = "正在获取登录代码…", TextWrapping = TextWrapping.Wrap };
        _loginCode = new TextBlock { Text = "------", FontSize = 22, FontWeight = Microsoft.UI.Text.FontWeights.Bold };
        var uriTb = new TextBlock { Text = "", TextWrapping = TextWrapping.Wrap };
        var box = new StackPanel { Spacing = 8 };
        box.Children.Add(_loginHint);
        box.Children.Add(_loginCode);
        box.Children.Add(uriTb);
        _loginDlg = new ContentDialog
        {
            Title = "微软账号登录",
            Content = box,
            PrimaryButtonText = "打开浏览器",
            CloseButtonText = "关闭",
            XamlRoot = XamlRoot,
        };
        _loginDlg.PrimaryButtonClick += async (_, _) =>
        {
            if (!string.IsNullOrEmpty(_loginUri))
            {
                try { await Windows.System.Launcher.LaunchUriAsync(new Uri(_loginUri)); } catch { }
            }
        };
        try
        {
            _loginTaskId = await AppServices.Client.StartTaskAsync("start_microsoft_login");
            await _loginDlg.ShowAsync();
        }
        finally
        {
            _loginDlg = null;
            await ReloadAsync();
        }
    }

    public void HandleEvent(BridgeEvent ev)
    {
        if (ev.Event == "login_code" && _loginDlg != null)
        {
            _loginUri = ev.Uri;
            if (_loginCode != null) _loginCode.Text = ev.Code;
            if (_loginHint != null) _loginHint.Text = "请在浏览器打开下面的地址并输入代码：";
        }
        if (ev.Event == "login_status" && _loginHint != null)
            _loginHint.Text = ev.Text;
        if (ev.Event == "finished" && ev.TaskId == _loginTaskId)
        {
            if (ev.Success) _loginDlg?.Hide();
            else if (_loginHint != null) _loginHint.Text = ev.Message;
            if (ev.Success) _ = ReloadAsync();
        }
        if (ev.Event == "crash" && (string.IsNullOrEmpty(ev.TaskId) || ev.TaskId == _taskId))
        {
            _crashShown = true;
            var report = ev.Crash ?? new CrashReport { Title = ev.Title, Detail = ev.Detail, TaskId = ev.TaskId };
            if (string.IsNullOrEmpty(report.TaskId)) report.TaskId = ev.TaskId;
            _ = CrashUi.ShowAsync(this, report);
        }
        if (ev.TaskId != _taskId) return;
        if (ev.Event == "progress")
        {
            LaunchProgress.Value = ev.Total > 0 ? ev.Current * 100.0 / ev.Total : 0;
            MainWindow.SplitMsg(ev.Message, out var st, out var sp);
            StatusLabel.Text = (string.IsNullOrEmpty(st) ? "处理中…" : st) + (string.IsNullOrEmpty(sp) ? "" : "    " + sp);
        }
        else if (ev.Event == "log" && !string.IsNullOrEmpty(ev.Text))
            LogEdit.Text += ev.Text + "\n";
        else if (ev.Event == "finished")
        {
            LaunchBtn.IsEnabled = true;
            StopBtn.IsEnabled = false;
            StatusLabel.Text = ev.Message;
            if (ev.Success) LaunchProgress.Value = 100;
            else if (!_crashShown && ev.Message != "已取消")
            {
                _crashShown = true;
                _ = CrashUi.ShowAsync(this, CrashUi.FromLaunchFail(ev.Message));
            }
        }
    }

}
