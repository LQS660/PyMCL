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
    public override string Title => L("启动");

    private readonly ComboBox _inst = Ui.Combo(width: double.NaN);
    private readonly ComboBox _ver = Ui.Combo();
    private readonly ComboBox _acc = Ui.Combo();
    private readonly ComboBox _java = Ui.Combo();
    private readonly TextBox _user = Ui.Input("Player");
    private readonly TextBox _server = Ui.Input(L("直连服务器 ip:port（可空）"));
    private readonly TextBox _wBox = Ui.Input("854", width: 74);
    private readonly TextBox _hBox = Ui.Input("480", width: 74);
    private readonly Slider _mem = Ui.Sld(1024, 32768, 4096, 256);
    private readonly TextBlock _memLbl = Ui.Txt("4096 MB", 12, true);
    private readonly Button _launchBtn = Ui.Btn(L("启动游戏"), BtnKind.Primary, glyph: Ico.Play);
    private readonly Button _stopBtn = Ui.Btn(L("停止"), BtnKind.Danger, glyph: Ico.Stop);
    private readonly ProgressBar _prog = Ui.Prog();
    private readonly TextBlock _status = Ui.Small(L("就绪"));
    private readonly TextBox _log = Ui.LogBox();
    private readonly TextBlock _bTitle = new() { FontSize = 27, FontWeight = FontWeights.Bold, Foreground = Brushes.White };
    private readonly TextBlock _bSub = new() { FontSize = 12.5, Foreground = new SolidColorBrush(Color.FromArgb(200, 255, 255, 255)) };
    private readonly SPanel _newsHost = Ui.V(6);
    private readonly SPanel _taskHost = Ui.V(6);
    private readonly TextBlock _playTotal = new() { FontSize = 26, FontWeight = FontWeights.Bold };
    private readonly TextBox _notes = Ui.Multi(L("随手记点什么…"), height: 90);
    private readonly DashHost _dash = new();
    private readonly List<string> _logLines = new();
    private List<JavaOption> _javaOpts = new();
    private List<InstanceInfo> _instances = new();
    private LayoutState _layoutState = new();
    private readonly DispatcherTimer _layoutSaveTimer = new() { Interval = TimeSpan.FromMilliseconds(300) };
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
        ("banner", L("启动横幅")), ("config", L("启动配置")), ("log", L("实时日志")), ("news", L("新闻主页")),
        ("quick", L("快捷入口")), ("notes", L("便签")), ("playtime", L("游戏时长")), ("tasks", L("任务摘要")),
    };

    public LaunchPage()
    {
        _dash.ContentFactory = BuildCard;
        _dash.TitleFactory = t => CardTypes.FirstOrDefault(c => c.Key == t).Title ?? t;
        _dash.Changed += PersistLayout;
        _layoutSaveTimer.Tick += (_, _) =>
        {
            _layoutSaveTimer.Stop();
            Run(SaveLayoutNowAsync, L("布局未能保存"));
        };

        var root = Ui.G("Auto,*");
        root.Add(BuildToolbar(), 0, 0);
        root.Add(new Border { Child = _dash, Margin = new Thickness(18, 4, 18, 16) }, 1, 0);
        Content = root;

        _stopBtn.IsEnabled = false;
        _launchBtn.Click += (_, _) => Run(LaunchAsync, L("启动失败"));
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
        var edit = Ui.Btn(L("编辑布局"), BtnKind.Chip, glyph: Ico.Edit);
        var add = Ui.Btn(L("添加卡片"), BtnKind.Chip, glyph: Ico.Add);
        var snap = Ui.Btn(L("网格吸附"), BtnKind.Chip, glyph: Ico.Grid);
        var scheme = Ui.Btn(L("方案"), BtnKind.Chip, glyph: Ico.List);
        var io = Ui.Btn(L("导入 / 导出"), BtnKind.Chip, glyph: Ico.Export);
        var reset = Ui.Btn(L("恢复默认"), BtnKind.Chip, glyph: Ico.Refresh);
        var hint = Ui.Small(L("拖动卡片移动，边角八向缩放；布局按比例自适应窗口"));
        hint.Visibility = Visibility.Collapsed;

        edit.Click += (_, _) =>
        {
            _editMode = !_editMode;
            _dash.EditMode = _editMode;
            edit.Content = Ui.H(6, Ui.Glyph(_editMode ? Ico.Check : Ico.Edit, 12.5), Ui.Txt(_editMode ? L("完成编辑") : L("编辑布局"), 13));
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
            if (menu.Items.Count == 0) menu.Items.Add(new MenuItem { Header = L("卡片都在画布上了"), IsEnabled = false });
            menu.PlacementTarget = add;
            menu.IsOpen = true;
        };
        snap.Click += (_, _) =>
        {
            // 与 Qt 的「吸附」下拉同一套档位：关了就是自由，开回来默认 8px
            var lay = _dash.Layout;
            lay.Grid = lay.Snap ? 0 : 8;
            _dash.EditMode = false;
            _dash.EditMode = _editMode;
            PersistLayout();
            Toast(L("网格吸附"), lay.Snap ? L("已开启（{0}px）", lay.Grid) : L("已关闭"));
        };
        scheme.Click += (_, _) => ShowSchemeMenu(scheme);
        io.Click += (_, _) => ShowIoMenu(io);
        reset.Click += (_, _) => Run(async () =>
        {
            var what = string.IsNullOrEmpty(_layoutState.Profile)
                ? L("回到内置默认布局。")
                : L("退出方案「{0}」，回到内置默认布局（方案本身保留）。", _layoutState.Profile);
            if (!await Dlg.Confirm(L("恢复默认布局"), what)) return;
            ApplyLayoutState(await Api.CallAsync("reset_layout"));
            await FillCardData();
        });

        var bar = Ui.H(8, edit, add, snap, scheme, io, reset, hint);
        bar.Margin = new Thickness(18, 14, 18, 0);
        foreach (UIElement c in bar.Children) c.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        return bar;
    }

    private void ShowSchemeMenu(FrameworkElement anchor)
    {
        var menu = new ContextMenu();
        var active = _layoutState.Profile;
        var def = new MenuItem { Header = (active.Length == 0 ? "● " : L("　")) + L("默认布局") };
        def.Click += (_, _) => Run(() => SwitchProfileAsync(""));
        menu.Items.Add(def);
        foreach (var name in _layoutState.Profiles)
        {
            var mi = new MenuItem { Header = (name == active ? "● " : L("　")) + name };
            mi.Click += (_, _) => Run(() => SwitchProfileAsync(name));
            menu.Items.Add(mi);
        }
        menu.Items.Add(new Separator());
        var add = new MenuItem { Header = L("把当前布局存为方案…") };
        add.Click += (_, _) => Run(async () =>
        {
            var name = await Dlg.Prompt(L("新建布局方案"), L("方案名称"), L("方案 {0}", _layoutState.Profiles.Count + 1));
            name = name?.Trim();
            if (string.IsNullOrEmpty(name)) return;
            if (_layoutState.Profiles.Contains(name) &&
                !await Dlg.Confirm(L("覆盖方案"), L("已有同名方案「{0}」，覆盖它？", name), L("覆盖"), L("取消"), true)) return;
            await FlushLayoutAsync();
            ApplyLayoutState(await Api.CallAsync("save_layout_profile", new { name, doc = _dash.Layout.ToDict() }));
            await FillCardData();
            Toast(L("已保存方案"), name, ToastKind.Success);
        });
        menu.Items.Add(add);
        var ren = new MenuItem { Header = L("重命名当前方案…"), IsEnabled = active.Length > 0 };
        ren.Click += (_, _) => Run(async () =>
        {
            var name = (await Dlg.Prompt(L("重命名方案"), L("方案名称"), active))?.Trim();
            if (string.IsNullOrEmpty(name) || name == active) return;
            // 桥上没有单独的改名：另存成新名字再删掉旧的
            await FlushLayoutAsync();
            await Api.CallAsync("save_layout_profile", new { name, doc = _dash.Layout.ToDict() });
            ApplyLayoutState(await Api.CallAsync("delete_layout_profile", new { name = active }));
            if (_layoutState.Profile != name) ApplyLayoutState(await Api.CallAsync("activate_layout_profile", new { name }));
            await FillCardData();
        });
        menu.Items.Add(ren);
        var del = new MenuItem { Header = L("删除当前方案"), IsEnabled = active.Length > 0 };
        del.Click += (_, _) => Run(async () =>
        {
            if (!await Dlg.Confirm(L("删除方案"), L("删除「{0}」？画布会回到内置默认布局。", active), L("删除"), L("取消"), true)) return;
            ApplyLayoutState(await Api.CallAsync("delete_layout_profile", new { name = active }));
            await FillCardData();
        });
        menu.Items.Add(del);
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private async Task SwitchProfileAsync(string name)
    {
        if (name == _layoutState.Profile) return;
        await FlushLayoutAsync();
        ApplyLayoutState(await Api.CallAsync("activate_layout_profile", new { name }));
        await FillCardData();
    }

    private void ShowIoMenu(FrameworkElement anchor)
    {
        var menu = new ContextMenu();
        var exp = new MenuItem { Header = L("导出布局 JSON…") };
        exp.Click += (_, _) =>
        {
            var path = Dlg.SaveFile(L("布局 (*.json)|*.json"), "pymcl-layout.json", L("导出布局"));
            if (path is null) return;
            try
            {
                // 与 Qt export_doc 同一个文件格式，导出去的文件三端都能导回来
                File.WriteAllText(path, _dash.Layout.ToJson());
                Toast(L("已导出"), path, ToastKind.Success);
            }
            catch (Exception ex) { Toast(L("导出失败"), ex.Message, ToastKind.Error); }
        };
        menu.Items.Add(exp);
        var imp = new MenuItem { Header = L("导入布局 JSON…") };
        imp.Click += (_, _) => Run(async () =>
        {
            var path = Dlg.PickFile(L("布局 (*.json)|*.json"), L("导入布局"));
            if (path is null) return;
            JsonElement doc;
            try
            {
                using var parsed = JsonDocument.Parse(File.ReadAllText(path));
                doc = parsed.RootElement.Clone();
            }
            catch (Exception ex)
            {
                Toast(L("导入失败"), L("不是有效的 JSON：") + ex.Message, ToastKind.Error);
                return;
            }
            // 结构校验在桥上（parse_doc）：不是布局文档会直接报错，不会悄悄换成默认
            ApplyLayoutState(await Api.CallAsync("import_layout", new { doc }));
            await FillCardData();
            Toast(L("已导入"), L("{0} 张卡片", _dash.Layout.Items.Count), ToastKind.Success);
        }, L("导入失败"));
        menu.Items.Add(imp);
        var grid = new MenuItem { Header = L("吸附网格") };
        foreach (var step in DashLayout.GridChoices)
        {
            var mi = new MenuItem
            {
                Header = step == 0 ? L("自由") : $"{step}px",
                IsCheckable = true,
                IsChecked = _dash.Layout.Grid == step,
            };
            mi.Click += (_, _) =>
            {
                _dash.Layout.Grid = step;
                _dash.EditMode = false;
                _dash.EditMode = _editMode;
                _dash.Rebuild();
                Run(FillCardData);
                PersistLayout();
            };
            grid.Items.Add(mi);
        }
        menu.Items.Add(grid);
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    /// <summary>get_layout / *_layout_profile / reset_layout / import_layout 回来的整份状态落到画布上。</summary>
    private void ApplyLayoutState(JsonElement state)
    {
        _layoutState = LayoutState.FromJson(state);
        _dash.MinSizes = _layoutState.MinSizes;
        _dash.Load(_layoutState.Doc);
    }

    /// <summary>画布一动就记一笔，300ms 内合并成一次 save_layout（对齐 Qt 的 300ms 去抖）。</summary>
    private void PersistLayout()
    {
        _layoutSaveTimer.Stop();
        _layoutSaveTimer.Start();
    }

    /// <summary>切方案 / 另存之前先把手上没落盘的改动写掉，免得被切走的那份覆盖。</summary>
    private async Task FlushLayoutAsync()
    {
        if (!_layoutSaveTimer.IsEnabled) return;
        _layoutSaveTimer.Stop();
        await SaveLayoutNowAsync();
    }

    private async Task SaveLayoutNowAsync()
    {
        if (!AppServices.Ready) return;
        var res = await Api.CallAsync("save_layout", new { doc = _dash.Layout.ToDict() });
        if (res.ValueKind == JsonValueKind.Object && res.TryGetProperty("profile", out var p) && p.ValueKind == JsonValueKind.String)
            _layoutState.Profile = p.GetString() ?? "";
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
        "playtime" => Ui.V(4, _playTotal, Ui.Muted(L("累计游玩时间"))),
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
        _launchBtn.Content = Ui.H(8, Ui.Glyph(Ico.Play, 15), Ui.Txt(L("启动游戏"), 15, true));
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

        var login = Ui.Btn(L("微软登录"), BtnKind.Soft, (_, _) => Run(MicrosoftLoginAsync), Ico.User);
        var skin = Ui.Btn(L("皮肤站"), BtnKind.Chip, (_, _) => Run(AuthlibLoginAsync));
        var verSet = Ui.Btn(L("版本设置"), BtnKind.Chip, (_, _) => Run(VersionSettingsAsync), Ico.Gear);
        // 新闻卡不一定摆在画布上，刷新入口跟着配置卡走，与 Qt 的 news_btn 同位置
        var news = Ui.Btn(L("刷新新闻"), BtnKind.Chip, (_, _) => Run(LoadNewsAsync), Ico.Refresh);
        var more = Ui.IconBtn(Ico.More, L("更多操作"), (s, _) => ShowMoreMenu((FrameworkElement)s));

        var body = Ui.V(9,
            Field(L("实例"), _inst),
            Field(L("版本"), _ver),
            Field(L("账号"), _acc),
            Field(L("用户名"), _user),
            Field("Java", _java),
            Field(L("内存"), memRow),
            Field(L("分辨率"), res),
            Field(L("直连"), _server),
            Ui.Sep().M(0, 4, 0, 2),
            Ui.H(7, login, skin, verSet, news, more));
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
        Item(L("查看启动命令"), ShowLaunchCommandAsync);
        Item(L("导出启动脚本 (.bat)"), ExportScriptAsync);
        Item(L("创建桌面快捷方式"), ShortcutAsync);
        Item(L("修复当前版本"), RepairAsync);
        Item(L("打开实例文件夹"), async () =>
        {
            await Api.CallAsync("open_instance_folder", new { name = _inst.Str() });
        });
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private UIElement BuildLog()
    {
        var head = Ui.H(6,
            // Qt 的日志卡上直接摆着这个按钮，不是埋在菜单里——排错时用得最多
            Ui.Btn(L("复制启动命令"), BtnKind.Chip, (_, _) => Run(ShowLaunchCommandAsync, L("生成失败")), Ico.Copy),
            Ui.IconBtn(Ico.List, L("复制日志"), (_, _) =>
            {
                try { Clipboard.SetText(_log.Text); Toast(L("已复制"), L("日志已放进剪贴板"), ToastKind.Success); }
                catch { }
            }),
            Ui.IconBtn(Ico.Trash, L("清空"), (_, _) =>
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

    /// <summary>快捷入口卡上可以摆哪些格子。key 与 Qt home_cards.QUICK_TARGETS 同一套。</summary>
    private static readonly (string Key, string Glyph, string Label)[] QuickTargets =
    {
        ("version", Ico.Box, L("下载游戏")),
        ("mod", Ico.Puzzle, L("装模组")),
        ("modpack", Ico.Package, L("整合包")),
        ("instance", Ico.Grid, L("实例")),
        ("account", Ico.User, L("账号")),
        ("ai", Ico.Robot, L("问 AI")),
        ("multiplayer", Ico.Wifi, L("联机")),
        ("settings", Ico.Gear, L("设置")),
        ("tasks", Ico.Download, L("下载任务")),
        ("saves", Ico.Save, L("存档管理")),
        ("folder", Ico.Folder, L("实例目录")),
    };

    private static readonly string[] QuickDefault =
        { "version", "mod", "modpack", "instance", "account", "settings", "tasks", "ai" };

    private readonly SPanel _quickHost = Ui.V(0);

    private UIElement BuildQuick()
    {
        RenderQuick();
        return _quickHost;
    }

    /// <summary>选了哪些格子存在卡片自己的 settings 里，跟着 save_layout 走，与 Qt 同一份文档。</summary>
    private List<string> QuickPicked()
    {
        var card = _dash.Layout.Items.FirstOrDefault(c => c.Type == "quick");
        if (card?.Settings is { ValueKind: JsonValueKind.Object } s &&
            s.TryGetProperty("targets", out var t) && t.ValueKind == JsonValueKind.Array)
        {
            var picked = t.EnumerateArray()
                .Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString() ?? "")
                .Where(k => QuickTargets.Any(q => q.Key == k))
                .ToList();
            if (picked.Count > 0) return picked;
        }
        return QuickDefault.ToList();
    }

    private void RenderQuick()
    {
        _quickHost.Children.Clear();
        var wrap = new WrapPanel();
        foreach (var key in QuickPicked())
        {
            var hit = QuickTargets.FirstOrDefault(q => q.Key == key);
            if (hit.Key is null) continue;
            var k = hit.Key;
            var b = Ui.Btn(hit.Label, BtnKind.Chip, (_, _) => QuickGo(k), hit.Glyph);
            b.Margin = new Thickness(0, 0, 7, 7);
            wrap.Children.Add(b);
        }
        var config = Ui.Btn(L("选择入口…"), BtnKind.Ghost, (_, _) => Run(PickQuickAsync), Ico.Edit);
        config.Margin = new Thickness(0, 0, 7, 7);
        wrap.Children.Add(config);
        _quickHost.Children.Add(wrap);
    }

    private void QuickGo(string key)
    {
        switch (key)
        {
            case "saves":
                Run(async () => await SavesDialog.ShowAsync(_inst.Str(), _ver.Str()));
                break;
            case "folder":
                Run(async () => await Api.CallAsync("open_instance_folder", new { name = _inst.Str() }));
                break;
            default:
                Win?.Navigate(key);
                break;
        }
    }

    /// <summary>勾选要显示在卡片上的入口，对齐 Qt 的 QuickSettingsDialog。</summary>
    private async Task PickQuickAsync()
    {
        var current = QuickPicked().ToHashSet(StringComparer.Ordinal);
        var boxes = new List<(CheckBox Box, string Key)>();
        var body = Ui.V(4, Ui.Muted(L("勾选要显示在卡片上的入口：")));
        foreach (var (key, _, label) in QuickTargets)
        {
            var cb = Ui.Check(label, current.Contains(key));
            boxes.Add((cb, key));
            body.Children.Add(cb);
        }
        if (!await Dlg.Ask(L("选择快捷入口"), body, L("确定"), L("取消"), false, 380)) return;
        var picked = boxes.Where(b => b.Box.IsChecked == true).Select(b => b.Key).ToList();
        if (picked.Count == 0) return;

        var card = _dash.Layout.Items.FirstOrDefault(c => c.Type == "quick");
        if (card != null)
        {
            using var doc = JsonDocument.Parse(JsonSerializer.Serialize(new { targets = picked }));
            card.Settings = doc.RootElement.Clone();
            PersistLayout();
        }
        RenderQuick();
    }

    // ==================== 数据 ====================
    private bool _layoutLoaded;

    protected override async Task LoadAsync()
    {
        if (!_layoutLoaded)
        {
            _layoutLoaded = true;
            try
            {
                ApplyLayoutState(await Api.CallAsync("get_layout"));
            }
            catch (Exception ex)
            {
                // 桥上拿不到就先按内置默认画，别让启动页空着；下次刷新再取
                _layoutLoaded = false;
                _dash.Load(DashLayout.Default());
                Toast(L("布局读取失败"), ex.Message, ToastKind.Warning);
            }
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
            if (accounts.Count == 0) accounts.Add(L("离线模式"));
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
            _status.Text = L("这个实例还没有版本，先去「原版游戏」装一个");
            _bSub.Text = L("还没有可启动的版本 · 去下载页安装");
        }
    }

    private async Task ReloadJavaAsync(bool scan)
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance = inst, scan_system = scan }, new()) ?? new();
        if (_inst.Str() != inst || opts.Count == 0) return;
        var want = await Api.TryCallAsync<string>("java_combo_label_for", new { instance = inst, options = opts }, "自动选择"); // i18n:ignore 桥的协议值（原文比对），不是界面词
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
        return _javaOpts.FirstOrDefault(o => o.Label == label)?.Value ?? (string.IsNullOrEmpty(label) ? "自动选择" : label); // i18n:ignore 桥的协议值（原文比对），不是界面词
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
            bits.Add(L("实例 ") + instance);
            _bTitle.Text = row.Pack;
            _bSub.Text = string.Join(" · ", bits);
        }
        else
        {
            _bTitle.Text = string.IsNullOrEmpty(version) ? L("未选择版本") : version;
            _bSub.Text = string.IsNullOrEmpty(version)
                ? L("先到「原版游戏」安装一个版本")
                : L("实例 {0} · 点「启动游戏」进入世界", instance);
            if (!string.IsNullOrEmpty(version)) Run(() => TagLoaderAsync(version));
        }
    }

    /// <summary>
    /// 横幅上标一句这个版本是什么加载器。认法交给后端 loader_of——
    /// 版本 id 里认加载器的那张对照表 Qt / 网页 / WPF 三端共用一份，别各写各的。
    /// </summary>
    private async Task TagLoaderAsync(string version)
    {
        var pair = await Api.TryCallAsync<List<string>>("loader_of", new { version_id = version }, new());
        if (pair is not { Count: >= 1 } || _ver.Str() != version) return;
        var label = pair[0];
        if (string.IsNullOrWhiteSpace(label)) return;
        _bSub.Text = $"{label} · " + _bSub.Text;
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
            _newsHost.Children.Add(Ui.Muted(L("主页已设为空白")));
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
                    : L("未设置自定义主页。到设置 → 启动页主页 填本地 HTML 路径。");
                _newsHost.Children.Add(Ui.Muted(body.Length > 2000 ? body[..2000] + "…" : body));
            }
            catch (Exception ex) { _newsHost.Children.Add(Ui.Muted(L("读不了自定义主页：") + ex.Message)); }
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
            _newsHost.Children.Add(Ui.Muted(L("暂无新闻")));
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
            _taskHost.Children.Add(Ui.Muted(L("暂无下载任务")));
            return;
        }
        foreach (var r in rows)
        {
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.Txt(r.Title, 12).Trim(), 0, 0);
            g.Add(Ui.Small(r.Finished ? (r.Success ? L("完成") : L("失败")) : $"{r.Progress:0}%").M(8, 0, 0, 0), 0, 1);
            _taskHost.Children.Add(g);
        }
    }

    // ==================== 启动 ====================
    private async Task LaunchAsync()
    {
        var version = _ver.Str();
        if (string.IsNullOrEmpty(version))
        {
            Toast(L("没有版本"), L("请先到「原版游戏」安装"), ToastKind.Warning);
            Win?.Navigate("version");
            return;
        }
        var instance = _inst.Str();
        var memory = (int)_mem.Value;
        var java = SelectedJava();

        if (!await CheckMultiInstanceAsync()) return;

        var pf = await Api.TryCallAsync<PreflightResult>("preflight_launch",
            new { instance, version, memory_mb = memory, java });
        var force = false;
        if (pf is null)
        {
            // 预检调用本身失败（桥过旧 / 方法缺失）：明示用户，由用户决定是否裸启。
            if (!await Dlg.Confirm(L("启动预检不可用"),
                    L("preflight_launch 调用失败，无法检查 Java / 内存 / 文件完整性。\n跳过预检直接启动？"), L("继续启动"), L("取消"))) return;
        }
        else
        {
            // errors / warns 并存时合成一个框、一次拍板，不连弹两个（对齐 Qt launch_page）
            var errors = pf.Items.Where(i => i.Level == "error").ToList();
            var warns = pf.Items.Where(i => i.Level == "warn").ToList();
            if (errors.Count > 0)
            {
                var body = string.Join("\n\n", errors.Select(i => $"· {i.Title}\n{i.Detail}"));
                if (warns.Count > 0)
                    body += "\n\n" + string.Join("\n\n", warns.Select(i => $"· {i.Title}\n{i.Detail}"));
                body += "\n\n" + L("这些问题可能导致启动失败。仍要强制启动？");
                if (!await Dlg.Confirm(L("启动预检未通过"), body, L("仍要启动"))) return;
                force = true;
            }
            else if (warns.Count > 0)
            {
                var body = string.Join("\n\n", warns.Select(i => $"· {i.Title}\n{i.Detail}")) + L("\n\n仍要继续启动？");
                if (!await Dlg.Confirm(L("启动预检有警告"), body, L("继续启动"))) return;
            }
        }

        _logLines.Clear();
        _log.Clear();
        _prog.Value = 0;
        _status.Text = L("准备启动…");
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
                account = _acc.Str() is { Length: > 0 } a ? a : L("离线模式"),
                username = string.IsNullOrWhiteSpace(_user.Text) ? "Player" : _user.Text.Trim(),
                memory_mb = memory,
                width = Int(_wBox.Text, 854),
                height = Int(_hBox.Text, 480),
                java,
                extra_game_args = ExtraArgs(),
                force,
            });
        }
        catch (Exception ex)
        {
            _launchBtn.IsEnabled = true;
            _stopBtn.IsEnabled = false;
            Toast(L("启动失败"), ex.Message, ToastKind.Error);
        }
    }

    /// <summary>
    /// 游戏已经开着、而多开又没打开时，后端会直接拒掉这次启动。
    /// 与其让用户对着一句报错发呆，先在这儿问清楚：要么放弃，要么就地把多开打开。
    /// </summary>
    private async Task<bool> CheckMultiInstanceAsync()
    {
        if (!await Api.TryCallAsync<bool>("is_game_running", null, false)) return true;
        if (await Api.TryCallAsync<bool>("allow_multi_instance", null, false)) return true;

        var pick = await Dlg.Choose(L("游戏已经在运行"),
            Ui.Muted(L("当前设置不允许多开。可以先关掉正在跑的那个，或者打开多开后再启动一个。")).Wrap().MinW(360),
            new[] { L("取消"), L("打开多开并启动") }, 520);
        if (pick != 1) return false;
        await Api.CallAsync<object>("set_multi_instance", new { allow = true });
        Toast(L("已允许多开"), L("可以在设置页再关掉"), ToastKind.Success);
        return true;
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
        _loginHint = Ui.Muted(L("正在获取登录代码…"));
        _loginCode = new TextBlock { Text = "------", FontSize = 26, FontWeight = FontWeights.Bold };
        _loginCode.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        var copy = Ui.Btn(L("复制代码"), BtnKind.Chip, (_, _) =>
        {
            try { Clipboard.SetText(_loginCode!.Text); Toast(L("已复制"), L("代码已放进剪贴板"), ToastKind.Success); }
            catch { }
        }, Ico.Copy);
        var open = Ui.Btn(L("打开浏览器"), BtnKind.Primary, (_, _) =>
        {
            if (!string.IsNullOrEmpty(_loginUri)) Ui.OpenUrl(_loginUri);
        }, Ico.Link);
        var body = Ui.V(10, _loginHint, _loginCode, Ui.H(8, copy, open));
        _loginLayer = Dlg.Panel(L("微软账号登录"), body, 460, () => _loginLayer = null);
        _loginTask = await Api.StartTaskAsync("start_microsoft_login");
    }

    private async Task AuthlibLoginAsync()
    {
        var presets = await Api.TryCallAsync<List<AuthlibPreset>>("authlib_presets", null, new()) ?? new();
        var api = Ui.Input("https://littleskin.cn/api/yggdrasil", presets.FirstOrDefault()?.Api ?? "");
        var user = Ui.Input(L("邮箱 / 用户名"));
        var pw = Ui.Pw();
        var pick = Ui.Combo(presets.Select(p => p.Name));
        pick.SelectionChanged += (_, _) =>
        {
            var hit = presets.FirstOrDefault(p => p.Name == pick.Str());
            if (hit != null) api.Text = hit.Api;
        };
        var body = Ui.V(8, Ui.Muted(L("选择皮肤站，或直接填 Yggdrasil API")), pick, api, user, pw);
        var ok = await Dlg.Ask(L("皮肤站登录"), body, L("登录"));
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
            Toast(L("未选择版本"), L("先安装并选中一个版本"), ToastKind.Warning);
            return;
        }
        await VersionSetupDialog.ShowAsync(inst, ver);
    }

    /// <summary>
    /// 按页面上当前这组参数生成启动命令文本（不启动）。
    /// 走 build_launch_command 而不是 get_launch_command：前者认分辨率与 Java 选择，
    /// 拼出来的命令和真按「启动游戏」跑的那条一致，拿去排错才有意义。
    /// </summary>
    private async Task ShowLaunchCommandAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        using (Dlg.Busy(L("正在生成启动命令…")))
        {
            string? cmd;
            try
            {
                cmd = await Api.CallAsync<string>("build_launch_command", new
                {
                    instance = _inst.Str(),
                    version = ver,
                    account = _acc.Str() is { Length: > 0 } a ? a : L("离线模式"),
                    username = string.IsNullOrWhiteSpace(_user.Text) ? "Player" : _user.Text.Trim(),
                    memory_mb = (int)_mem.Value,
                    width = Int(_wBox.Text, 854),
                    height = Int(_hBox.Text, 480),
                    java = SelectedJava(),
                });
            }
            catch (BridgeCallException)
            {
                // 选中的 Java 不可用时 build_launch_command 会直接报错。
                // get_launch_command 自己解析 Java（必要时还会下一个），拿它兜底至少能看到命令长什么样。
                cmd = await Api.CallAsync<string>("get_launch_command", new
                {
                    instance = _inst.Str(),
                    version = ver,
                    account = _acc.Str(),
                    username = _user.Text?.Trim() ?? "",
                    memory_mb = (int)_mem.Value,
                });
            }
            await Dlg.Alert(L("启动命令"), cmd ?? "");
        }
    }

    private async Task ExportScriptAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        var dest = Dlg.SaveFile(L("批处理 (*.bat)|*.bat"), $"launch-{_inst.Str()}-{ver}.bat", L("导出启动脚本"));
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
        Toast(L("已创建快捷方式"), msg ?? "", ToastKind.Success);
    }

    private async Task RepairAsync()
    {
        var ver = _ver.Str();
        if (string.IsNullOrEmpty(ver)) return;
        if (!await Dlg.Confirm(L("修复版本"), L("重新校验并补齐「{0}」的依赖库与资源？", ver))) return;
        await Api.StartTaskAsync("repair_version", new { instance = _inst.Str(), version = ver });
        Win?.FlyToTasks(_launchBtn, L("修复中"));
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "login_code" when _loginLayer != null:
                _loginUri = ev.Uri;
                if (_loginCode != null) _loginCode.Text = ev.Code;
                if (_loginHint != null) _loginHint.Text = L("在浏览器打开下面的地址并输入代码：\n") + ev.Uri;
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
                    _status.Text = L("游戏进程已启动，正在加载世界…");
                    Motion.Progress(_prog, Math.Max(_prog.Value, 92));
                    break;
                case "game_exited":
                    var code = ev.Payload.ValueKind == JsonValueKind.Object
                               && ev.Payload.TryGetProperty("code", out var c)
                               && c.ValueKind == JsonValueKind.Number
                        ? c.GetInt32() : (int?)null;
                    _status.Text = code is null ? L("游戏已退出") : L("游戏已退出（退出码 {0}）", code);
                    break;
            }
        }

        if (ev.TaskId != _taskId) return;
        switch (ev.Event)
        {
            case "progress":
                Motion.Progress(_prog, ev.Total > 0 ? ev.Current * 100.0 / ev.Total : 0);
                Fmt.SplitMsg(ev.Message, out var st, out var sp);
                _status.Text = (string.IsNullOrEmpty(st) ? L("处理中…") : st) + (string.IsNullOrEmpty(sp) ? "" : "    " + sp);
                break;
            case "log":
                AppendLog(ev.Text);
                break;
            case "finished":
                _launchBtn.IsEnabled = true;
                _stopBtn.IsEnabled = false;
                _status.Text = string.IsNullOrEmpty(ev.Message) ? L("已结束") : ev.Message;
                if (ev.Success) Motion.Progress(_prog, 100);
                else if (!_crashShown && ev.Message != "已取消") // i18n:ignore 桥返回的原文，不是界面词
                {
                    _crashShown = true;
                    Run(() => HandleCrashAsync(new CrashReport
                    {
                        Title = L("启动失败"),
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
