using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class LaunchPage : PageBase
{
    public override string Title => "启动";

    private readonly ComboBox _inst = Ui.Combo(width: double.NaN);
    private readonly ComboBox _ver = Ui.Combo();
    private readonly ComboBox _acc = Ui.Combo();
    private readonly ComboBox _java = Ui.Combo();
    private readonly TextBox _user = Ui.Input("Player");
    private readonly TextBox _server = Ui.Input("直连服务器 ip:port（可空）");
    private readonly TextBox _wBox = Ui.Input("854", width: 74);
    private readonly TextBox _hBox = Ui.Input("480", width: 74);
    private readonly Slider _mem = Ui.Sld(1024, 32768, 4096, 256);
    private readonly TextBlock _memLbl = Ui.Txt("4096 MB", 12, true);
    private readonly Button _launchBtn = Ui.Btn("启动游戏", BtnKind.Primary, glyph: Ico.Play);
    private readonly Button _stopBtn = Ui.Btn("停止", BtnKind.Danger, glyph: Ico.Stop);
    private readonly ProgressBar _prog = Ui.Prog();
    private readonly TextBlock _status = Ui.Small("就绪");
    private readonly TextBox _log = Ui.LogBox();
    private readonly TextBlock _bTitle = new() { FontSize = 27, FontWeight = FontWeights.Bold, Foreground = Brushes.White };
    private readonly TextBlock _bSub = new() { FontSize = 12.5, Foreground = new SolidColorBrush(Color.FromArgb(200, 255, 255, 255)) };
    private readonly SPanel _newsHost = Ui.V(6);
    private readonly SPanel _taskHost = Ui.V(6);
    private readonly TextBlock _playTotal = new() { FontSize = 26, FontWeight = FontWeights.Bold };
    private readonly TextBox _notes = Ui.Multi("随手记点什么…", height: 90);
    private readonly DashHost _dash = new();
    private readonly List<string> _logLines = new();
    private List<JavaOption> _javaOpts = new();
    private List<InstanceInfo> _instances = new();
    private DashStore _store = DashStore.Default();
    private string? _taskId;
    private string? _loginTask;
    private bool _syncing;
    private bool _crashShown;
    private bool _editMode;
    private TextBlock? _loginHint, _loginCode;
    private string _loginUri = "";
    private Dlg.Layer? _loginLayer;
    private string? _preferredInstance;
    private string? _preferredVersion;
    private readonly DispatcherTimer _memSaveTimer = new() { Interval = TimeSpan.FromMilliseconds(650) };

    private static readonly (string Key, string Title)[] CardTypes =
    {
        ("banner", "启动横幅"), ("config", "启动配置"), ("log", "实时日志"), ("news", "新闻主页"),
        ("quick", "快捷入口"), ("notes", "便签"), ("playtime", "游戏时长"), ("tasks", "任务摘要"),
    };

    public LaunchPage()
    {
        _dash.ContentFactory = BuildCard;
        _dash.TitleFactory = t => CardTypes.FirstOrDefault(c => c.Key == t).Title ?? t;
        _dash.Changed += PersistLayout;

        var root = Ui.G("Auto,*");
        root.Add(BuildToolbar(), 0, 0);
        root.Add(new Border { Child = _dash, Margin = new Thickness(18, 4, 18, 16) }, 1, 0);
        Content = root;

        _stopBtn.IsEnabled = false;
        _launchBtn.Click += (_, _) => Run(LaunchAsync, "启动失败");
        _stopBtn.Click += (_, _) => Run(StopAsync);
        _inst.SelectionChanged += (_, _) => { if (!_syncing) Run(OnInstanceChanged); };
        _ver.SelectionChanged += (_, _) => { if (!_syncing) SyncBanner(); };
        _java.SelectionChanged += (_, _) => { if (!_syncing) Run(SaveJavaAsync); };
        _mem.ValueChanged += (_, e) =>
        {
            _memLbl.Text = $"{(int)e.NewValue} MB";
            if (!_syncing)
            {
                _memSaveTimer.Stop();
                _memSaveTimer.Start();
            }
        };
        _memSaveTimer.Tick += (_, _) =>
        {
            _memSaveTimer.Stop();
            if (!_syncing) Run(SaveDisplayPrefsAsync);
        };
        _wBox.LostFocus += (_, _) => { if (!_syncing) Run(SaveDisplayPrefsAsync); };
        _hBox.LostFocus += (_, _) => { if (!_syncing) Run(SaveDisplayPrefsAsync); };
        _notes.LostFocus += (_, _) =>
        {
            if (Win is null) return;
            Win.Prefs.Notes = _notes.Text;
            Win.SaveUiPrefs();
        };
    }

    // ==================== 工具栏 ====================
    private UIElement BuildToolbar()
    {
        var edit = Ui.Btn("编辑布局", BtnKind.Chip, glyph: Ico.Edit);
        var add = Ui.Btn("添加卡片", BtnKind.Chip, glyph: Ico.Add);
        var snap = Ui.Btn("网格吸附", BtnKind.Chip, glyph: Ico.Grid);
        var scheme = Ui.Btn("方案", BtnKind.Chip, glyph: Ico.List);
        var io = Ui.Btn("导入 / 导出", BtnKind.Chip, glyph: Ico.Export);
        var reset = Ui.Btn("恢复默认", BtnKind.Chip, glyph: Ico.Refresh);
        var hint = Ui.Small("拖动卡片移动，边角八向缩放；布局按比例自适应窗口");
        hint.Visibility = Visibility.Collapsed;

        edit.Click += (_, _) =>
        {
            _editMode = !_editMode;
            _dash.EditMode = _editMode;
            edit.Content = Ui.H(6, Ui.Glyph(_editMode ? Ico.Check : Ico.Edit, 12.5), Ui.Txt(_editMode ? "完成编辑" : "编辑布局", 13));
            hint.Visibility = _editMode ? Visibility.Visible : Visibility.Collapsed;
            add.IsEnabled = snap.IsEnabled = _editMode;
        };
        add.IsEnabled = snap.IsEnabled = false;
        add.Click += (_, _) =>
        {
            var menu = new ContextMenu();
            foreach (var (key, title) in CardTypes)
            {
                if (_dash.Has(key)) continue;
                var mi = new MenuItem { Header = title };
                mi.Click += (_, _) =>
                {
                    _dash.AddCard(key);
                    Run(FillCardData);
                };
                menu.Items.Add(mi);
            }
            if (menu.Items.Count == 0) menu.Items.Add(new MenuItem { Header = "卡片都在画布上了", IsEnabled = false });
            menu.PlacementTarget = add;
            menu.IsOpen = true;
        };
        snap.Click += (_, _) =>
        {
            var lay = _dash.Layout;
            lay.Snap = !lay.Snap;
            _dash.EditMode = false;
            _dash.EditMode = _editMode;
            PersistLayout();
            Toast("网格吸附", lay.Snap ? $"已开启（{lay.Grid} 格）" : "已关闭");
        };
        scheme.Click += (_, _) => ShowSchemeMenu(scheme);
        io.Click += (_, _) => ShowIoMenu(io);
        reset.Click += (_, _) => Run(async () =>
        {
            if (!await Dlg.Confirm("恢复默认布局", "当前方案的卡片位置会被重置。")) return;
            var cur = _store.Current;
            var def = DashStore.DefaultLayout(cur.Name);
            cur.Cards = def.Cards;
            _dash.Load(cur);
            await FillCardData();
            PersistLayout();
        });

        var bar = Ui.H(8, edit, add, snap, scheme, io, reset, hint);
        bar.Margin = new Thickness(18, 14, 18, 0);
        foreach (UIElement c in bar.Children) c.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        return bar;
    }

    private void ShowSchemeMenu(FrameworkElement anchor)
    {
        var menu = new ContextMenu();
        for (var i = 0; i < _store.Layouts.Count; i++)
        {
            var idx = i;
            var mi = new MenuItem { Header = (i == _store.Active ? "● " : "　") + _store.Layouts[i].Name };
            mi.Click += (_, _) =>
            {
                _store.Active = idx;
                _dash.Load(_store.Current);
                Run(FillCardData);
                PersistLayout();
            };
            menu.Items.Add(mi);
        }
        menu.Items.Add(new Separator());
        var add = new MenuItem { Header = "新建方案…" };
        add.Click += (_, _) => Run(async () =>
        {
            var name = await Dlg.Prompt("新建布局方案", "方案名称", $"方案 {_store.Layouts.Count + 1}");
            if (string.IsNullOrWhiteSpace(name)) return;
            _store.Layouts.Add(_store.Current.Clone());
            _store.Layouts[^1].Name = name;
            _store.Active = _store.Layouts.Count - 1;
            _dash.Load(_store.Current);
            await FillCardData();
            PersistLayout();
        });
        menu.Items.Add(add);
        var ren = new MenuItem { Header = "重命名当前方案…" };
        ren.Click += (_, _) => Run(async () =>
        {
            var name = await Dlg.Prompt("重命名方案", "方案名称", _store.Current.Name);
            if (string.IsNullOrWhiteSpace(name)) return;
            _store.Current.Name = name;
            PersistLayout();
        });
        menu.Items.Add(ren);
        var del = new MenuItem { Header = "删除当前方案", IsEnabled = _store.Layouts.Count > 1 };
        del.Click += (_, _) => Run(async () =>
        {
            if (!await Dlg.Confirm("删除方案", $"删除「{_store.Current.Name}」？", "删除", "取消", true)) return;
            _store.Layouts.RemoveAt(_store.Active);
            _store.Active = 0;
            _dash.Load(_store.Current);
            await FillCardData();
            PersistLayout();
        });
        menu.Items.Add(del);
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private void ShowIoMenu(FrameworkElement anchor)
    {
        var menu = new ContextMenu();
        var exp = new MenuItem { Header = "导出布局 JSON…" };
        exp.Click += (_, _) =>
        {
            var path = Dlg.SaveFile("布局 (*.json)|*.json", "pymcl-layout.json", "导出布局");
            if (path is null) return;
            try
            {
                File.WriteAllText(path, _store.ToJson());
                Toast("已导出", path, ToastKind.Success);
            }
            catch (Exception ex) { Toast("导出失败", ex.Message, ToastKind.Error); }
        };
        menu.Items.Add(exp);
        var imp = new MenuItem { Header = "导入布局 JSON…" };
        imp.Click += (_, _) => Run(async () =>
        {
            var path = Dlg.PickFile("布局 (*.json)|*.json", "导入布局");
            if (path is null) return;
            _store = DashStore.FromJson(File.ReadAllText(path));
            _dash.Load(_store.Current);
            await FillCardData();
            PersistLayout();
            Toast("已导入", $"{_store.Layouts.Count} 套方案", ToastKind.Success);
        });
        menu.Items.Add(imp);
        var grid = new MenuItem { Header = "网格密度…" };
        grid.Click += (_, _) => Run(async () =>
        {
            var v = await Dlg.Prompt("网格密度", "每边格数（8 ~ 64）", _dash.Layout.Grid.ToString());
            if (!int.TryParse(v, out var n)) return;
            _dash.Layout.Grid = Math.Clamp(n, 8, 64);
            _dash.EditMode = false;
            _dash.EditMode = _editMode;
            _dash.Rebuild();
            await FillCardData();
            PersistLayout();
        });
        menu.Items.Add(grid);
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private void PersistLayout()
    {
        if (Win is null) return;
        Win.Prefs.LayoutJson = _store.ToJson();
        Win.SaveUiPrefs();
    }

    // ==================== 卡片内容 ====================
    private UIElement? BuildCard(string type) => type switch
    {
        "banner" => BuildBanner(),
        "config" => BuildConfig(),
        "log" => BuildLog(),
        "news" => Ui.Scroll(_newsHost),
        "quick" => BuildQuick(),
        "notes" => _notes,
        "playtime" => Ui.V(4, _playTotal, Ui.Muted("累计游玩时间")),
        "tasks" => Ui.Scroll(_taskHost),
        _ => null,
    };

    private UIElement BuildBanner()
    {
        var shine = new Border
        {
            Width = 180,
            HorizontalAlignment = HorizontalAlignment.Left,
            Background = new LinearGradientBrush(new GradientStopCollection
            {
                new(Color.FromArgb(0, 255, 255, 255), 0),
                new(Color.FromArgb(90, 255, 255, 255), 0.5),
                new(Color.FromArgb(0, 255, 255, 255), 1),
            }, 0),
            IsHitTestVisible = false,
            Opacity = 0,
        };
        Motion.Shine(shine, new TranslateTransform(-200, 0));

        var btns = Ui.H(10, _launchBtn, _stopBtn);
        _launchBtn.Padding = new Thickness(26, 10, 26, 11);
        _launchBtn.Content = Ui.H(8, Ui.Glyph(Ico.Play, 15), Ui.Txt("启动游戏", 15, true));
        _stopBtn.Padding = new Thickness(16, 10, 16, 11);
        Motion.HoverLift(_launchBtn, 1.05, 1, 16);

        _prog.Height = 5;
        var texts = Ui.V(4, _bTitle, _bSub);
        var row = Ui.G(null, "*,Auto");
        row.Add(texts.VCenter(), 0, 0);
        row.Add(btns.VCenter(), 0, 1);

        var statusRow = Ui.V(5, _prog, _status);
        _status.Foreground = new SolidColorBrush(Color.FromArgb(215, 255, 255, 255));

        var inner = Ui.V(12, row, statusRow);
        inner.Margin = new Thickness(24, 18, 24, 18);

        var fill = new Border { CornerRadius = new CornerRadius(12), ClipToBounds = true };
        fill.SetResourceReference(BackgroundProperty, "B.BannerFill");
        var g = new Grid();
        g.Children.Add(shine);
        g.Children.Add(inner);
        fill.Child = g;
        return fill;
    }

    private UIElement BuildConfig()
    {
        var res = Ui.H(6, _wBox, Ui.Txt("×", 13).VCenter(), _hBox);
        var memRow = Ui.G(null, "*,Auto");
        memRow.Add(_mem.VCenter(), 0, 0);
        memRow.Add(_memLbl.M(10, 0, 0, 0).VCenter(), 0, 1);

        var login = Ui.Btn("微软登录", BtnKind.Soft, (_, _) => Run(MicrosoftLoginAsync), Ico.User);
        var skin = Ui.Btn("皮肤站", BtnKind.Chip, (_, _) => Run(AuthlibLoginAsync));
        var verSet = Ui.Btn("版本设置", BtnKind.Chip, (_, _) => Run(VersionSettingsAsync), Ico.Gear);
        var more = Ui.IconBtn(Ico.More, "更多操作", (s, _) => ShowMoreMenu((FrameworkElement)s));

        var body = Ui.V(9,
            Field("实例", _inst),
            Field("版本", _ver),
            Field("账号", _acc),
            Field("用户名", _user),
            Field("Java", _java),
            Field("内存", memRow),
            Field("分辨率", res),
            Field("直连", _server),
            Ui.Sep().M(0, 4, 0, 2),
            Ui.H(7, login, skin, verSet, more));
        return Ui.Scroll(body);
    }

    private static UIElement Field(string label, UIElement control)
    {
        var g = Ui.G(null, "58,*");
        g.Add(Ui.Txt(label, 12, fg: "B.InkMuted").VCenter(), 0, 0);
        control.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        g.Add(control, 0, 1);
        return g;
    }

    private void ShowMoreMenu(FrameworkElement anchor)
    {
        var menu = new ContextMenu();
        void Item(string head, Func<Task> act)
        {
            var mi = new MenuItem { Header = head };
            mi.Click += (_, _) => Run(act);
            menu.Items.Add(mi);
        }
        Item("查看启动命令", ShowLaunchCommandAsync);
        Item("导出启动脚本 (.bat)", ExportScriptAsync);
        Item("创建桌面快捷方式", ShortcutAsync);
        Item("修复当前版本", RepairAsync);
        Item("打开实例文件夹", async () =>
        {
            await Api.CallAsync("open_instance_folder", new { name = _inst.Str() });
        });
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private UIElement BuildLog()
    {
        var head = Ui.H(6,
            Ui.IconBtn(Ico.Copy, "复制日志", (_, _) =>
            {
                try { Clipboard.SetText(_log.Text); Toast("已复制", "日志已放进剪贴板", ToastKind.Success); }
                catch { }
            }),
            Ui.IconBtn(Ico.Trash, "清空", (_, _) =>
            {
                _logLines.Clear();
                _log.Clear();
            })).Right();
        var g = Ui.G("Auto,*");
        g.Add(head, 0, 0);
        g.Add(_log.M(0, 4, 0, 0), 1, 0);
        _log.BorderThickness = new Thickness(0);
        _log.Background = Brushes.Transparent;
        _log.Padding = new Thickness(0);
        return g;
    }

    private UIElement BuildQuick()
    {
        var wrap = new WrapPanel();
        void Q(string glyph, string text, Action act)
        {
            var b = Ui.Btn(text, BtnKind.Chip, (_, _) => act(), glyph);
            b.Margin = new Thickness(0, 0, 7, 7);
            wrap.Children.Add(b);
        }
        Q(Ico.Box, "下载游戏", () => Win?.Navigate("version"));
        Q(Ico.Puzzle, "装模组", () => Win?.Navigate("mod"));
        Q(Ico.Package, "整合包", () => Win?.Navigate("modpack"));
        Q(Ico.Robot, "问 AI", () => Win?.Navigate("ai"));
        Q(Ico.Folder, "实例目录", () => Run(async () =>
            await Api.CallAsync("open_instance_folder", new { name = _inst.Str() })));
        Q(Ico.Save, "存档管理", () => Run(async () =>
            await SavesDialog.ShowAsync(_inst.Str(), _ver.Str())));
        Q(Ico.Wifi, "联机", () => Win?.Navigate("multiplayer"));
        Q(Ico.Gear, "设置", () => Win?.Navigate("settings"));
        return wrap;
    }

    // ==================== 数据 ====================
    private bool _layoutLoaded;

    protected override async Task LoadAsync()
    {
        if (!_layoutLoaded)
        {
            _layoutLoaded = true;
            if (Win != null && !string.IsNullOrWhiteSpace(Win.Prefs.LayoutJson))
                _store = DashStore.FromJson(Win.Prefs.LayoutJson);
            _dash.Load(_store.Current);
            if (Win != null) _notes.Text = Win.Prefs.Notes;
        }
        await FillCardData();
    }

    private async Task FillCardData()
    {
        _syncing = true;
        try
        {
            _instances = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
            _inst.Fill(_instances.Select(i => i.Name));
            var accounts = await Api.TryCallAsync<List<string>>("get_accounts", null, new()) ?? new();
            if (accounts.Count == 0) accounts.Add("离线模式");
            _acc.Fill(accounts);
            var s = await Api.TryCallAsync<Dictionary<string, System.Text.Json.JsonElement>>("get_settings");
            if (s != null)
            {
                if (s.TryGetValue("default_memory_mb", out var m) && m.TryGetInt32(out var mb)) _mem.Value = Math.Clamp(mb, 1024, 32768);
                if (s.TryGetValue("default_resolution", out var r) && r.ValueKind == System.Text.Json.JsonValueKind.Array && r.GetArrayLength() >= 2)
                {
                    _wBox.Text = r[0].ToString();
                    _hBox.Text = r[1].ToString();
                }
            }
            _memLbl.Text = $"{(int)_mem.Value} MB";
            if (Win != null && !string.IsNullOrEmpty(Win.Prefs.Notes)) _notes.Text = Win.Prefs.Notes;
            if (string.IsNullOrWhiteSpace(_user.Text)) _user.Text = Win?.Prefs.LastUser ?? "";
        }
        finally { _syncing = false; }

        await ReloadVersionsAsync();
        await ReloadJavaAsync(false);
        _ = ReloadJavaAsync(true);
        SyncBanner();
        await ApplyPreferenceAsync();
        _ = LoadNewsAsync();
        _ = LoadPlaytimeAsync();
        SyncTaskCard();
    }

    private async Task OnInstanceChanged()
    {
        await ReloadVersionsAsync();
        await ReloadJavaAsync(false);
        SyncBanner();
    }

    private async Task ReloadVersionsAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var ids = await Api.TryCallAsync<List<string>>("get_installed_versions", new { instance = inst }, new()) ?? new();
        _syncing = true;
        _ver.Fill(ids);
        _syncing = false;
        _launchBtn.IsEnabled = ids.Count > 0 && _taskId is null;
        if (ids.Count == 0)
        {
            _status.Text = "这个实例还没有版本，先去「原版游戏」装一个";
            _bSub.Text = "还没有可启动的版本 · 去下载页安装";
        }
    }

    private async Task ReloadJavaAsync(bool scan)
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance = inst, scan_system = scan }, new()) ?? new();
        if (_inst.Str() != inst || opts.Count == 0) return;
        var want = await Api.TryCallAsync<string>("java_combo_label_for", new { instance = inst, options = opts }, "自动选择");
        _syncing = true;
        _javaOpts = opts;
        _java.Fill(opts.Select(o => o.Label), want);
        _syncing = false;
    }

    private async Task SaveJavaAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        await Api.TryCallAsync<object>("set_instance_java", new { name = inst, java = SelectedJava() });
    }

    /// <summary>内存 / 分辨率是全局启动默认值，改动后落回 settings。</summary>
    private async Task SaveDisplayPrefsAsync()
    {
        await Api.TryCallAsync<object>("update_settings", new
        {
            settings = new
            {
                default_memory_mb = (int)_mem.Value,
                default_resolution = new[] { Int(_wBox.Text, 854), Int(_hBox.Text, 480) },
            },
        });
    }

    /// <summary>实例页 / 版本页点「启动」时把选择带过来；页面还没加载完就先存着。</summary>
    public void PreferInstance(string name, string? version = null)
    {
        _preferredInstance = name;
        _preferredVersion = version;
        if (_instances.Count > 0) Run(ApplyPreferenceAsync);
    }

    private async Task ApplyPreferenceAsync()
    {
        var name = _preferredInstance;
        if (string.IsNullOrEmpty(name) || _instances.All(i => i.Name != name)) return;
        _preferredInstance = null;
        if (_inst.Str() != name)
        {
            _syncing = true;
            _inst.Fill(_instances.Select(i => i.Name), name);
            _syncing = false;
            await ReloadVersionsAsync();
            await ReloadJavaAsync(false);
        }
        var ver = _preferredVersion;
        _preferredVersion = null;
        if (!string.IsNullOrEmpty(ver) && _ver.Items.Contains(ver))
        {
            _syncing = true;
            _ver.Fill(_ver.Items.Cast<string>(), ver);
            _syncing = false;
        }
        SyncBanner();
    }

    private string SelectedJava()
    {
        var label = _java.Str();
        return _javaOpts.FirstOrDefault(o => o.Label == label)?.Value ?? (string.IsNullOrEmpty(label) ? "自动选择" : label);
    }

    private void SyncBanner()
    {
        var version = _ver.Str();
        var instance = _inst.Str();
        var row = _instances.FirstOrDefault(x => x.Name == instance);
        if (row != null && !string.IsNullOrEmpty(row.Pack))
        {
            var bits = new List<string>();
            if (!string.IsNullOrEmpty(row.PackVersion)) bits.Add(row.PackVersion);
            if (!string.IsNullOrEmpty(row.McVersion)) bits.Add("Minecraft " + row.McVersion);
            bits.Add("实例 " + instance);
            _bTitle.Text = row.Pack;
            _bSub.Text = string.Join(" · ", bits);
        }
        else
        {
            _bTitle.Text = string.IsNullOrEmpty(version) ? "未选择版本" : version;
            _bSub.Text = string.IsNullOrEmpty(version)
                ? "先到「原版游戏」安装一个版本"
                : $"实例 {instance} · 点「启动游戏」进入世界";
        }
    }

    private async Task LoadNewsAsync()
    {
        _newsHost.Children.Clear();
        _newsHost.Children.Add(Ui.Skeleton(14));
        _newsHost.Children.Add(Ui.Skeleton(12, 180));
        var mode = await Api.TryCallAsync<string>("get_setting", new { key = "homepage_mode", @default = "news" }, "news");
        if (mode == "blank")
        {
            _newsHost.Children.Clear();
            _newsHost.Children.Add(Ui.Muted("主页已设为空白"));
            return;
        }
        if (mode == "custom")
        {
            var path = await Api.TryCallAsync<string>("get_setting", new { key = "custom_homepage", @default = "" }, "");
            _newsHost.Children.Clear();
            try
            {
                var body = !string.IsNullOrWhiteSpace(path) && File.Exists(path)
                    ? await File.ReadAllTextAsync(path)
                    : "未设置自定义主页。到设置 → 启动页主页 填本地 HTML 路径。";
                _newsHost.Children.Add(Ui.Muted(body.Length > 2000 ? body[..2000] + "…" : body));
            }
            catch (Exception ex) { _newsHost.Children.Add(Ui.Muted("读不了自定义主页：" + ex.Message)); }
            return;
        }
        var rows = await Api.TryCallAsync<List<NewsRow>>("cached_news", null, new()) ?? new();
        FillNews(rows);
        var fresh = await Api.TryCallAsync<List<NewsRow>>("fetch_news");
        if (fresh is { Count: > 0 }) FillNews(fresh);
    }

    private void FillNews(List<NewsRow> rows)
    {
        _newsHost.Children.Clear();
        if (rows.Count == 0)
        {
            _newsHost.Children.Add(Ui.Muted("暂无新闻"));
            return;
        }
        foreach (var r in rows.Take(6))
        {
            _newsHost.Children.Add(Ui.Txt(r.Title, 12.5, true).Wrap());
            if (!string.IsNullOrEmpty(r.Body)) _newsHost.Children.Add(Ui.Small(r.Body).Wrap());
        }
        Motion.Stagger(_newsHost, 20, 200, 8);
    }

    private async Task LoadPlaytimeAsync()
    {
        var total = await Api.TryCallAsync<long>("get_total_playtime", null, 0L);
        _playTotal.Text = Fmt.Duration(total);
    }

    private void SyncTaskCard()
    {
        _taskHost.Children.Clear();
        var rows = TaskStore.Rows.Reverse().Take(5).ToList();
        if (rows.Count == 0)
        {
            _taskHost.Children.Add(Ui.Muted("暂无下载任务"));
            return;
        }
        foreach (var r in rows)
        {
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.Txt(r.Title, 12).Trim(), 0, 0);
            g.Add(Ui.Small(r.Finished ? (r.Success ? "完成" : "失败") : $"{r.Progress:0}%").M(8, 0, 0, 0), 0, 1);
            _taskHost.Children.Add(g);
        }
    }

    // ==================== 启动 ====================
    private async Task LaunchAsync()
    {
        var version = _ver.Str();
        if (string.IsNullOrEmpty(version))
        {
            Toast("没有版本", "请先到「原版游戏」安装", ToastKind.Warning);
            Win?.Navigate("version");
            return;
        }
        var instance = _inst.Str();
        var memory = (int)_mem.Value;
        var java = SelectedJava();

        var pf = await Api.TryCallAsync<PreflightResult>("preflight_launch",
            new { instance, version, memory_mb = memory, java });
        if (pf is null)
        {
            // 预检调用本身失败（桥过旧 / 方法缺失）：明示用户，由用户决定是否裸启。
            if (!await Dlg.Confirm("启动预检不可用",
                    "preflight_launch 调用失败，无法检查 Java / 内存 / 文件完整性。\n跳过预检直接启动？", "继续启动", "取消")) return;
        }
        else
        {
            var errors = pf.Items.Where(i => i.Level == "error").ToList();
            if (errors.Count > 0)
            {
                await Dlg.Alert("启动预检未通过",
                    string.Join("\n\n", errors.Select(i => $"· {i.Title}\n{i.Detail}")));
                return;
            }
            var warns = pf.Items.Where(i => i.Level == "warn").ToList();
            if (warns.Count > 0)
            {
                var body = string.Join("\n\n", warns.Select(i => $"· {i.Title}\n{i.Detail}")) + "\n\n仍要继续启动？";
                if (!await Dlg.Confirm("启动预检有警告", body, "继续启动")) return;
            }
        }

        _logLines.Clear();
        _log.Clear();
        _prog.Value = 0;
        _status.Text = "准备启动…";
        _launchBtn.IsEnabled = false;
        _stopBtn.IsEnabled = true;
        _crashShown = false;
        Motion.Pulse(_launchBtn);

        if (Win != null)
        {
            Win.Prefs.LastUser = _user.Text?.Trim() ?? "";
            Win.SaveUiPrefs();
        }

        try
        {
            _taskId = await Api.StartTaskAsync("launch_game", new
            {
                instance,
                version,
                account = _acc.Str() is { Length: > 0 } a ? a : "离线模式",
                username = string.IsNullOrWhiteSpace(_user.Text) ? "Player" : _user.Text.Trim(),
                memory_mb = memory,
                width = Int(_wBox.Text, 854),
                height = Int(_hBox.Text, 480),
                java,
                extra_game_args = ExtraArgs(),
            });
        }
        catch (Exception ex)
        {
            _launchBtn.IsEnabled = true;
            _stopBtn.IsEnabled = false;
            Toast("启动失败", ex.Message, ToastKind.Error);
        }
    }

    private static int Int(string? s, int fallback) =>
        int.TryParse(s?.Trim(), out var v) && v > 0 ? v : fallback;

    private string[]? ExtraArgs()
    {
        var server = _server.Text?.Trim();
        if (string.IsNullOrEmpty(server)) return null;
        var i = server.LastIndexOf(':');
        return i > 0
            ? new[] { "--server", server[..i], "--port", server[(i + 1)..] }
            : new[] { "--server", server, "--port", "25565" };
    }

    private async Task StopAsync()
    {
        if (_taskId is null) return;
        await Api.TryCallAsync<object>("cancel_task", new { task_id = _taskId });
    }

    // ==================== 附属操作 ====================
    private async Task MicrosoftLoginAsync()
    {
        if (_loginLayer != null) return;
        _loginHint = Ui.Muted("正在获取登录代码…");
        _loginCode = new TextBlock { Text = "------", FontSize = 26, FontWeight = FontWeights.Bold };
        _loginCode.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        var copy = Ui.Btn("复制代码", BtnKind.Chip, (_, _) =>
        {
            try { Clipboard.SetText(_loginCode!.Text); Toast("已复制", "代码已放进剪贴板", ToastKind.Success); }
            catch { }
        }, Ico.Copy);
        var open = Ui.Btn("打开浏览器", BtnKind.Primary, (_, _) =>
        {
            if (!string.IsNullOrEmpty(_loginUri)) Ui.OpenUrl(_loginUri);
        }, Ico.Link);
        var body = Ui.V(10, _loginHint, _loginCode, Ui.H(8, copy, open));
        _loginLayer = Dlg.Panel("微软账号登录", body, 460, () => _loginLayer = null);
        _loginTask = await Api.StartTaskAsync("start_microsoft_login");
    }

    private async Task AuthlibLoginAsync()
    {
        var presets = await Api.TryCallAsync<List<AuthlibPreset>>("authlib_presets", null, new()) ?? new();
        var api = Ui.Input("https://littleskin.cn/api/yggdrasil", presets.FirstOrDefault()?.Api ?? "");
        var user = Ui.Input("邮箱 / 用户名");
        var pw = Ui.Pw();
        var pick = Ui.Combo(presets.Select(p => p.Name));
        pick.SelectionChanged += (_, _) =>
        {
            var hit = presets.FirstOrDefault(p => p.Name == pick.Str());
            if (hit != null) api.Text = hit.Api;
        };
        var body = Ui.V(8, Ui.Muted("选择皮肤站，或直接填 Yggdrasil API"), pick, api, user, pw);
        var ok = await Dlg.Ask("皮肤站登录", body, "登录");
        if (!ok) return;
        await Api.StartTaskAsync("start_authlib_login", new
        {
            api = api.Text?.Trim() ?? "",
            username = user.Text?.Trim() ?? "",
            password = pw.Password ?? "",
        });
    }

    private async Task VersionSettingsAsync()
    {
        var inst = _inst.Str();
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver))
        {
            Toast("未选择版本", "先安装并选中一个版本", ToastKind.Warning);
            return;
        }
        await VersionSetupDialog.ShowAsync(inst, ver);
    }

    private async Task ShowLaunchCommandAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        using (Dlg.Busy("正在生成启动命令…"))
        {
            var cmd = await Api.CallAsync<string>("get_launch_command", new
            {
                instance = _inst.Str(),
                version = ver,
                account = _acc.Str(),
                username = _user.Text?.Trim() ?? "",
                memory_mb = (int)_mem.Value,
            });
            await Dlg.Alert("启动命令", cmd ?? "");
        }
    }

    private async Task ExportScriptAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        var dest = Dlg.SaveFile("批处理 (*.bat)|*.bat", $"launch-{_inst.Str()}-{ver}.bat", "导出启动脚本");
        if (dest is null) return;
        await Api.StartTaskAsync("export_launch_script", new { instance = _inst.Str(), version = ver, dest });
    }

    private async Task ShortcutAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        var msg = await Api.CallAsync<string>("create_desktop_shortcut", new
        {
            instance = _inst.Str(),
            version = ver,
            username = _user.Text?.Trim() ?? "",
            account = _acc.Str(),
        });
        Toast("已创建快捷方式", msg ?? "", ToastKind.Success);
    }

    private async Task RepairAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        if (!await Dlg.Confirm("修复版本", $"重新校验并补齐「{ver}」的依赖库与资源？")) return;
        await Api.StartTaskAsync("repair_version", new { instance = _inst.Str(), version = ver });
        Win?.FlyToTasks(_launchBtn, "修复中");
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "login_code" when _loginLayer != null:
                _loginUri = ev.Uri;
                if (_loginCode != null) _loginCode.Text = ev.Code;
                if (_loginHint != null) _loginHint.Text = "在浏览器打开下面的地址并输入代码：\n" + ev.Uri;
                break;
            case "login_status" when _loginHint != null:
                _loginHint.Text = ev.Text;
                break;
            case "task_added":
            case "finished" when ev.TaskId != _taskId:
            case "progress" when ev.TaskId != _taskId:
                SyncTaskCard();
                break;
        }

        if (ev.Event == "finished" && ev.TaskId == _loginTask)
        {
            if (ev.Success)
            {
                _loginLayer?.Close();
                _loginLayer = null;
                Run(FillCardData);
            }
            else if (_loginHint != null) _loginHint.Text = ev.Message;
        }

        if (ev.Event == "crash" && (string.IsNullOrEmpty(ev.TaskId) || ev.TaskId == _taskId))
        {
            _crashShown = true;
            var report = ev.Crash ?? new CrashReport { Title = ev.Title, Detail = ev.Message, TaskId = ev.TaskId };
            Run(() => HandleCrashAsync(report));
        }

        // game_started / game_exited 不带 task_id，只在本页有启动任务在跑时认领。
        if (_taskId != null)
        {
            switch (ev.Event)
            {
                case "game_started":
                    _status.Text = "游戏进程已启动，正在加载世界…";
                    Motion.Progress(_prog, Math.Max(_prog.Value, 92));
                    break;
                case "game_exited":
                    var code = ev.Payload.ValueKind == JsonValueKind.Object
                               && ev.Payload.TryGetProperty("code", out var c)
                               && c.ValueKind == JsonValueKind.Number
                        ? c.GetInt32() : (int?)null;
                    _status.Text = code is null ? "游戏已退出" : $"游戏已退出（退出码 {code}）";
                    break;
            }
        }

        if (ev.TaskId != _taskId) return;
        switch (ev.Event)
        {
            case "progress":
                Motion.Progress(_prog, ev.Total > 0 ? ev.Current * 100.0 / ev.Total : 0);
                Fmt.SplitMsg(ev.Message, out var st, out var sp);
                _status.Text = (string.IsNullOrEmpty(st) ? "处理中…" : st) + (string.IsNullOrEmpty(sp) ? "" : "    " + sp);
                break;
            case "log":
                AppendLog(ev.Text);
                break;
            case "finished":
                _launchBtn.IsEnabled = true;
                _stopBtn.IsEnabled = false;
                _status.Text = string.IsNullOrEmpty(ev.Message) ? "已结束" : ev.Message;
                if (ev.Success) Motion.Progress(_prog, 100);
                else if (!_crashShown && ev.Message != "已取消")
                {
                    _crashShown = true;
                    Run(() => HandleCrashAsync(new CrashReport
                    {
                        Title = "启动失败",
                        Headline = ev.Message,
                        Detail = ev.Message,
                        Instance = _inst.Str(),
                        Version = _ver.Str(),
                    }));
                }
                _taskId = null;
                _ = LoadPlaytimeAsync();
                break;
        }
    }

    private async Task HandleCrashAsync(CrashReport report)
    {
        var relaunch = await CrashUi.ShowAsync(report);
        if (relaunch) await LaunchAsync();
    }

    private const int MaxLines = 2500;

    private void AppendLog(string text)
    {
        if (string.IsNullOrEmpty(text)) return;
        _logLines.Add(text);
        if (_logLines.Count > MaxLines) _logLines.RemoveRange(0, _logLines.Count - MaxLines);
        var atEnd = _log.VerticalOffset >= _log.ExtentHeight - _log.ViewportHeight - 24;
        _log.Text = string.Join('\n', _logLines);
        if (atEnd) _log.ScrollToEnd();
    }

    public override void OnShown() => SyncTaskCard();
}
