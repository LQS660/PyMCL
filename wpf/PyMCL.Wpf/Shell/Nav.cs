using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Pages;
using PyMCL.Services;

namespace PyMCL;

public sealed record NavDef(string Id, string Title, string Glyph, Func<PageBase> Create);

/// <summary>
/// 只属于这台机器这套前端的偏好（窗口、主题、动画、分区折叠态、草稿）。
/// 侧栏排法与启动页布局不在这里——它们走桥上的 ui_* 键，三端共用一份。
/// </summary>
public sealed class UiPrefs
{
    /// <summary>桥连上之前先按这个宽度画，连上后以 ui_sidebar_width 为准。</summary>
    public double SideWidth { get; set; } = 196;
    public bool Dark { get; set; }
    public bool Anim { get; set; } = true;
    public double AnimScale { get; set; } = 1;
    public Dictionary<string, bool> Expanded { get; set; } = new();
    public string Notes { get; set; } = "";
    public string LastUser { get; set; } = "";
    public string CatalogInstance { get; set; } = "";
}

public partial class MainWindow
{
    public const int SideMinWidth = 140;
    public const int SideMaxWidth = 320;
    private const double SideDefaultWidth = 196;

    /// <summary>页面注册表，按 WPF 页面 id。侧栏键到页面 id 的映射见 NavModel.PageForNavKey。</summary>
    public static readonly List<NavDef> NavDefs = new()
    {
        new("launch", L("启动"), Ico.Rocket, () => new LaunchPage()),
        new("instance", L("版本管理"), Ico.Grid, () => new InstancePage()),
        new("version", L("原版游戏"), Ico.Box, () => new VersionPage()),
        new("mod", "Mod", Ico.Puzzle, () => new CatalogPage(Models.CatalogKind.Mod)),
        new("mods", L("模组"), Ico.Puzzle, () => new CatalogPage(Models.CatalogKind.Mod, installedFirst: true)),
        new("modpack", L("整合包"), Ico.Package, () => new CatalogPage(Models.CatalogKind.Modpack)),
        new("datapack", L("数据包"), Ico.Data, () => new CatalogPage(Models.CatalogKind.Datapack)),
        new("resourcepack", L("资源包"), Ico.Image, () => new CatalogPage(Models.CatalogKind.ResourcePack)),
        new("shader", L("光影包"), Ico.Sun, () => new CatalogPage(Models.CatalogKind.Shader)),
        new("world", L("世界"), Ico.World, () => new CatalogPage(Models.CatalogKind.World)),
        new("account", L("账号"), Ico.User, () => new AccountPage()),
        new("java", "Java", Ico.Coffee, () => new JavaPage()),
        new("ai", L("AI 助手"), Ico.Robot, () => new AiPage()),
        new("multiplayer", L("联机"), Ico.Wifi, () => new MultiplayerPage()),
        new("servers", L("服务器"), Ico.Server, () => new ServersPage()),
        new("playtime", L("游戏时长"), Ico.Clock, () => new PlaytimePage()),
        new("feedback", L("反馈与帮助"), Ico.Chat, () => new FeedbackPage()),
        new("settings", L("设置"), Ico.Gear, () => new SettingsPage()),
        new("tasks", L("下载任务"), Ico.Download, () => new TasksPage()),
    };

    private static readonly Dictionary<string, string> NavGlyphs = new()
    {
        ["launch"] = Ico.Rocket, ["download"] = Ico.Download, ["ai"] = Ico.Robot, ["more"] = Ico.More,
        ["tasks"] = Ico.Download, ["version"] = Ico.Box, ["mod"] = Ico.Puzzle, ["modpack"] = Ico.Package,
        ["datapack"] = Ico.Data, ["resource"] = Ico.Image, ["shader"] = Ico.Sun, ["world"] = Ico.World,
        ["java"] = Ico.Coffee, ["instance"] = Ico.Grid, ["mods"] = Ico.Puzzle, ["account"] = Ico.User,
        ["multiplayer"] = Ico.Wifi, ["servers"] = Ico.Server, ["playtime"] = Ico.Clock,
        ["feedback"] = Ico.Chat, ["settings"] = Ico.Gear,
    };

    /// <summary>侧栏一行：一级项 / 固定子页 / 分区标题 / 分区里的子页。</summary>
    private sealed class NavRow
    {
        public required string Key { get; init; }
        public required ToggleButton Button { get; init; }
        /// <summary>所在分区（download / more）；null = 顶层。</summary>
        public string? Section { get; init; }
        public bool IsSectionHeader => NavModel.IsSection(Key) && Section is null;
    }

    private readonly Dictionary<string, NavRow> _navRows = new();
    private readonly Dictionary<string, StackPanel> _groupPanels = new();
    private UiPrefs _prefs = new();
    private NavConfig _navCfg = new();
    private Border? _taskBadge;
    private TextBlock? _taskBadgeText;

    private static string PrefsPath
    {
        get
        {
            string root;
            try { root = BridgeHost.FindRoot(); }
            catch { root = AppContext.BaseDirectory; }
            return Path.Combine(root, "wpf-ui.json");
        }
    }

    private void LoadUiPrefs()
    {
        try
        {
            _prefs = File.Exists(PrefsPath)
                ? JsonSerializer.Deserialize<UiPrefs>(File.ReadAllText(PrefsPath)) ?? new UiPrefs()
                : new UiPrefs();
        }
        catch { _prefs = new UiPrefs(); }

        // 老版本把分区键写成 "#download"，读回来去掉井号
        foreach (var key in _prefs.Expanded.Keys.Where(k => k.StartsWith('#')).ToList())
        {
            _prefs.Expanded[key[1..]] = _prefs.Expanded[key];
            _prefs.Expanded.Remove(key);
        }
        _prefs.Expanded.TryAdd("download", true);
        _prefs.Expanded.TryAdd("more", false);

        SideCol.Width = new GridLength(ClampSide(_prefs.SideWidth));
        Motion.Enabled = _prefs.Anim;
        Motion.Scale = Math.Clamp(_prefs.AnimScale, 0.4, 2.2);
        if (_prefs.Dark)
        {
            App.ApplyTheme(true);
            ThemeBtn.Content = "\uE706";
        }
    }

    public void SaveUiPrefs()
    {
        _prefs.SideWidth = SideCol.Width.Value;
        _prefs.Dark = App.IsDark;
        _prefs.Anim = Motion.Enabled;
        _prefs.AnimScale = Motion.Scale;
        try
        {
            File.WriteAllText(PrefsPath, JsonSerializer.Serialize(_prefs,
                new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { }
    }

    public UiPrefs Prefs => _prefs;

    /// <summary>当前生效的侧栏配置（桥上 get_settings 的 ui_nav_* 键）。</summary>
    public NavConfig NavConfig => _navCfg;

    private static double ClampSide(double w) =>
        w is >= SideMinWidth and <= SideMaxWidth ? w : SideDefaultWidth;

    // ==================== 与桥同步 ====================
    /// <summary>桥连上后拉一次设置，侧栏按 Qt / 网页版同一份 ui_nav_* 重画。</summary>
    public async Task LoadNavFromBridgeAsync()
    {
        JsonElement el;
        try { el = await AppServices.Client.CallAsync("get_settings"); }
        catch (Exception ex)
        {
            Toast(L("侧栏设置读取失败"), ex.Message, ToastKind.Warning);
            return;
        }
        ApplyNavSettings(el);
    }

    public void ApplyNavSettings(JsonElement settings)
    {
        _navCfg = NavConfig.FromJson(settings);
        if (_navCfg.SidebarWidth is >= SideMinWidth and <= SideMaxWidth)
        {
            SideCol.Width = new GridLength(_navCfg.SidebarWidth);
            _prefs.SideWidth = _navCfg.SidebarWidth;
        }
        BuildNav();
    }

    /// <summary>先按 patch 重画（立刻可见），再写回桥；写失败提示但不回滚——下次连上会以桥为准。</summary>
    private async Task ApplyNavPatchAsync(IReadOnlyDictionary<string, object?> patch)
    {
        _navCfg = _navCfg.With(patch);
        BuildNav();
        if (!AppServices.Ready) return;
        try
        {
            await AppServices.Client.CallAsync<object>("update_settings",
                new { settings = NavModel.ToRpcArgs(patch) });
        }
        catch (Exception ex)
        {
            Toast(L("侧栏设置未能保存"), ex.Message, ToastKind.Warning);
        }
    }

    public void ResetNavLayout() =>
        Run(() => ApplyNavPatchAsync(NavModel.DefaultNavPatch()));

    public void SetNavStyle(string style)
    {
        if (!NavModel.StyleLabels.ContainsKey(style) || style == NavModel.NavStyle(_navCfg)) return;
        Run(() => ApplyNavPatchAsync(new Dictionary<string, object?> { ["ui_nav_style"] = style }));
    }

    private void SideGrip_DragDelta(object sender, DragDeltaEventArgs e)
    {
        var w = Math.Clamp(SideCol.Width.Value + e.HorizontalChange, SideMinWidth, SideMaxWidth);
        SideCol.Width = new GridLength(w);
        _prefs.SideWidth = w;
    }

    private void SideGrip_DragCompleted(object sender, DragCompletedEventArgs e)
    {
        var w = (int)Math.Round(SideCol.Width.Value);
        SaveUiPrefs();
        if (w == _navCfg.SidebarWidth) return;
        _navCfg.SidebarWidth = w;
        if (!AppServices.Ready) return;
        Run(async () =>
        {
            try
            {
                await AppServices.Client.CallAsync<object>("update_settings",
                    new { settings = new Dictionary<string, object?> { ["ui_sidebar_width"] = w } });
            }
            catch { }
        });
    }

    // ==================== 构建 ====================
    private void BuildNav()
    {
        NavHost.Children.Clear();
        PinnedHost.Children.Clear();
        _navRows.Clear();
        _groupPanels.Clear();
        _taskBadge = null;
        _taskBadgeText = null;

        var members = NavModel.SectionMembersFromConfig(_navCfg);
        Panel host = NavHost;
        foreach (var entry in NavModel.NavItemsFromConfig(_navCfg))
        {
            switch (entry.Kind)
            {
                case NavEntryKind.Header:
                    host.Children.Add(MakeHeader(entry.Label));
                    break;
                case NavEntryKind.Stretch:
                    // 分隔线以下的都沉到侧栏底部
                    PinnedHost.Children.Add(Ui.Sep().M(14, 0, 14, 6));
                    host = PinnedHost;
                    break;
                // 两种排法都能拖：精简档挪混合序列，分组档在组间挪（对齐 Qt move_within_groups）
                case NavEntryKind.Item when NavModel.IsSection(entry.Key):
                    host.Children.Add(BuildGroup(entry.Key, entry.Label, members[entry.Key]));
                    break;
                case NavEntryKind.Item:
                    host.Children.Add(MakeRow(entry.Key, entry.Label, null, draggable: true));
                    break;
            }
        }
        SideFooter.Visibility = PinnedHost.Children.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        SyncNavSelection();
        SyncTasks();
    }

    private static UIElement MakeHeader(string label)
    {
        var text = Ui.Txt(label, 11, fg: "B.InkFaint");
        text.Margin = new Thickness(22, 10, 8, 3);
        return text;
    }

    /// <summary>分区（下载 / 更多）：一行可折叠的标题 + 里面还没被固定到侧栏的子页。</summary>
    private UIElement BuildGroup(string sec, string label, List<string> memberKeys)
    {
        var open = _prefs.Expanded.TryGetValue(sec, out var v) && v;
        var chev = Ui.Glyph(Ico.ChevronRight, 10, "B.InkFaint");
        var rot = new RotateTransform(open ? 90 : 0);
        chev.RenderTransform = rot;
        chev.RenderTransformOrigin = new Point(0.5, 0.5);

        var header = MakeRow(sec, label, null, draggable: true, trailing: chev);
        var panel = new StackPanel { ClipToBounds = true };
        _groupPanels[sec] = panel;
        foreach (var key in memberKeys)
            panel.Children.Add(MakeRow(key, NavModel.NavLabel(key), sec, draggable: true));
        panel.Visibility = open ? Visibility.Visible : Visibility.Collapsed;

        header.Click += (_, _) =>
        {
            header.IsChecked = false;
            SyncNavSelection();
            var nowOpen = panel.Visibility != Visibility.Visible;
            _prefs.Expanded[sec] = nowOpen;
            SaveUiPrefs();
            var an = new System.Windows.Media.Animation.DoubleAnimation(nowOpen ? 90 : 0,
                TimeSpan.FromMilliseconds(Motion.Enabled ? 180 : 1))
            { EasingFunction = new System.Windows.Media.Animation.CubicEase() };
            rot.BeginAnimation(RotateTransform.AngleProperty, an);
            if (nowOpen)
            {
                panel.Visibility = Visibility.Visible;
                panel.Measure(new Size(SideCol.Width.Value, double.PositiveInfinity));
                var h = panel.DesiredSize.Height;
                panel.Height = 0;
                Motion.AnimateHeight(panel, h, 200, () => panel.Height = double.NaN);
            }
            else
            {
                panel.Height = panel.ActualHeight;
                Motion.AnimateHeight(panel, 0, 170, () =>
                {
                    panel.Visibility = Visibility.Collapsed;
                    panel.Height = double.NaN;
                });
            }
        };

        var wrap = new StackPanel { Tag = sec };
        wrap.Children.Add(header);
        wrap.Children.Add(panel);
        return wrap;
    }

    private ToggleButton MakeRow(string key, string label, string? section, bool draggable, FrameworkElement? trailing = null)
    {
        var sub = section != null;
        var glyph = Ui.Glyph(NavGlyphs.GetValueOrDefault(key, Ico.Grid), 14);
        var text = Ui.Txt(label, 13).VCenter();
        text.TextTrimming = TextTrimming.CharacterEllipsis;
        var row = Ui.G(null, "18,*,Auto");
        row.Add(glyph, 0, 0);
        row.Add(text.M(10, 0, 0, 0), 0, 1);
        if (key == "tasks")
        {
            _taskBadgeText = new TextBlock
            {
                Text = "0", FontSize = 11, FontWeight = FontWeights.SemiBold,
                Foreground = Brushes.White, HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            };
            _taskBadge = new Border
            {
                CornerRadius = new CornerRadius(999), MinWidth = 18, Height = 17,
                Padding = new Thickness(5, 0, 5, 1), Visibility = Visibility.Collapsed,
                VerticalAlignment = VerticalAlignment.Center, Child = _taskBadgeText,
            };
            _taskBadge.SetResourceReference(Border.BackgroundProperty, "B.Accent");
            row.Add(_taskBadge, 0, 2);
        }
        else if (trailing != null)
        {
            row.Add(trailing.VCenter(), 0, 2);
        }

        var btn = new ToggleButton
        {
            Style = Ui.S("NavItem"),
            Content = row,
            Tag = key,
            Margin = new Thickness(sub ? 12 : 0, 0, 0, 0),
        };
        if (sub) glyph.Opacity = 0.85;
        var navRow = new NavRow { Key = key, Button = btn, Section = section };
        if (!navRow.IsSectionHeader)
        {
            btn.Click += (_, _) =>
            {
                btn.IsChecked = true;
                if (NavModel.PageForNavKey.TryGetValue(key, out var page)) Navigate(page);
            };
        }
        btn.ContextMenu = RowMenu(navRow);
        if (draggable) AttachDrag(navRow);
        // 同一个键在侧栏上只会出现一次（固定了就不在分区里），直接覆盖即可
        _navRows[key] = navRow;
        return btn;
    }

    // ==================== 右键菜单 ====================
    private ContextMenu RowMenu(NavRow row)
    {
        var menu = new ContextMenu();
        var grouped = NavModel.NavStyle(_navCfg) == NavModel.StyleGrouped;
        var title = NavModel.NavLabel(row.Key);

        if (row.Section != null)
        {
            // 分区里的子页：固定出去 / 挪到另一个分区
            Item(menu, L("固定到侧栏"), () =>
            {
                var res = NavModel.PinNavConfig(_navCfg, row.Key);
                if (res is null) return;
                if (res.Error != null) { Toast(L("无法移出"), res.Error, ToastKind.Warning); return; }
                Run(() => ApplyNavPatchAsync(res.Patch!));
            });
            foreach (var other in NavModel.SectionIds.Where(s => s != row.Section))
                Item(menu, L("移到「{0}」分区", NavModel.NavLabel(other)), () => MoveMember(row.Key, row.Section!, other, -1));
        }
        else if (NavModel.AllSubKeys.Contains(row.Key))
        {
            // 固定在侧栏上的子页：放回某个分区
            foreach (var sec in NavModel.VisibleSections(_navCfg))
                Item(menu, L("放回「{0}」分区", NavModel.NavLabel(sec)), () =>
                {
                    var res = NavModel.UnpinNavConfig(_navCfg, row.Key, sec);
                    if (res is null) return;
                    Run(() => ApplyNavPatchAsync(res.Value.Patch));
                    Toast(L("已取消固定"), L("「{0}」放回了「{1}」", title, NavModel.NavLabel(res.Value.Section)));
                });
        }

        // ui_nav_hidden：精简档只对一级项生效，分组档对任何键生效
        var hideable = row.Section is null && (NavModel.IsTop(row.Key) || grouped);
        if (hideable)
        {
            Item(menu, row.IsSectionHeader ? L("隐藏此分区") : L("隐藏此入口"), () =>
            {
                var hidden = _navCfg.Hidden.Where(k => k != row.Key).Append(row.Key).ToList();
                Run(() => ApplyNavPatchAsync(new Dictionary<string, object?> { ["ui_nav_hidden"] = hidden }));
                if (PageOf(row.Key) == _currentId) Navigate("launch");
                Toast(L("已隐藏"), L("「{0}」可在侧栏右键菜单或设置里恢复", title));
            });
        }
        if (_navCfg.Hidden.Count > 0)
        {
            var restore = new MenuItem { Header = L("恢复隐藏的入口") };
            foreach (var k in _navCfg.Hidden.Where(k => NavModel.IsTop(k) || NavModel.AllSubKeys.Contains(k)))
            {
                var key = k;
                Item(restore, NavModel.NavLabel(key), () => ShowNavItem(key, true));
            }
            if (restore.Items.Count > 0) menu.Items.Add(restore);
        }

        menu.Items.Add(new Separator());
        if (row.IsSectionHeader)
        {
            Item(menu, L("全部展开 / 收起"), () =>
            {
                var target = !_prefs.Expanded.GetValueOrDefault(row.Key);
                foreach (var s in NavModel.SectionIds) _prefs.Expanded[s] = target;
                SaveUiPrefs();
                BuildNav();
            });
        }
        var otherStyle = grouped ? NavModel.StyleCompact : NavModel.StyleGrouped;
        Item(menu, L("切换排法：") + NavModel.StyleLabels[otherStyle], () => SetNavStyle(otherStyle));
        Item(menu, L("恢复默认侧栏"), ResetNavLayout);
        return menu;
    }

    private static void Item(ItemsControl menu, string header, Action act)
    {
        var mi = new MenuItem { Header = header };
        mi.Click += (_, _) => act();
        menu.Items.Add(mi);
    }

    private static string? PageOf(string navKey) =>
        NavModel.PageForNavKey.TryGetValue(navKey, out var p) ? p : null;

    /// <summary>分区内挪动成员：换分区或换位置，写 ui_section_members。</summary>
    private void MoveMember(string key, string from, string to, int index)
    {
        var members = NavModel.SectionMembersFromConfig(_navCfg);
        if (!members[from].Remove(key) && !members[to].Contains(key)) return;
        members[to].Remove(key);
        var bucket = members[to];
        bucket.Insert(index >= 0 && index <= bucket.Count ? index : bucket.Count, key);
        if (members[from].Count == 0 && from != to)
        {
            Toast(L("无法移出"), L("该分区只剩这一个子页，移走会变空栏"), ToastKind.Warning);
            return;
        }
        _prefs.Expanded[to] = true;
        Run(() => ApplyNavPatchAsync(new Dictionary<string, object?> { ["ui_section_members"] = members }));
    }

    public void ShowNavItem(string navKey, bool visible)
    {
        var hidden = _navCfg.Hidden.Where(k => k != navKey).ToList();
        if (!visible) hidden.Add(navKey);
        Run(() => ApplyNavPatchAsync(new Dictionary<string, object?> { ["ui_nav_hidden"] = hidden }));
    }

    public bool IsNavHidden(string navKey) => _navCfg.Hidden.Contains(navKey);

    /// <summary>侧栏上能点进去的页面 id，按显示顺序（Ctrl+数字快捷键用）。</summary>
    private List<string> VisibleFlatOrder()
    {
        var list = new List<string>();
        var members = NavModel.SectionMembersFromConfig(_navCfg);
        foreach (var entry in NavModel.NavItemsFromConfig(_navCfg))
        {
            if (entry.Kind != NavEntryKind.Item) continue;
            if (NavModel.IsSection(entry.Key))
            {
                foreach (var k in members[entry.Key])
                    if (PageOf(k) is { } p && !list.Contains(p)) list.Add(p);
            }
            else if (PageOf(entry.Key) is { } p && !list.Contains(p)) list.Add(p);
        }
        return list;
    }

    private int NavOrderIndex(string pageId)
    {
        var i = VisibleFlatOrder().IndexOf(pageId);
        return i < 0 ? 99 : i;
    }

    private void SyncNavSelection()
    {
        foreach (var row in _navRows.Values)
            row.Button.IsChecked = !row.IsSectionHeader && PageOf(row.Key) == _currentId;
    }

    private void SyncTasks()
    {
        var n = TaskStore.RunningCount;
        if (_taskBadge is null || _taskBadgeText is null) return;
        _taskBadgeText.Text = n > 99 ? "99+" : n.ToString();
        var show = n > 0;
        if (show && _taskBadge.Visibility != Visibility.Visible)
        {
            _taskBadge.Visibility = Visibility.Visible;
            Motion.Pulse(_taskBadge, 1.25);
        }
        else if (!show) _taskBadge.Visibility = Visibility.Collapsed;
        SyncDock();
    }

    // ==================== 拖拽排序 / 固定 / 取消固定 ====================
    private Point _dragStart;
    private NavRow? _dragRow;
    private bool _dragging;
    private Border? _dropLine;
    private NavRow? _dropTarget;
    private bool _dropBefore;

    private void AttachDrag(NavRow row)
    {
        var btn = row.Button;
        btn.PreviewMouseLeftButtonDown += (_, e) =>
        {
            _dragStart = e.GetPosition(this);
            _dragRow = row;
            _dragging = false;
        };
        btn.PreviewMouseMove += (_, e) =>
        {
            if (_dragRow != row || e.LeftButton != MouseButtonState.Pressed) return;
            var p = e.GetPosition(this);
            // 阈值要盖过人手点一下的自然抖动：太窄会把「点一下」误判成拖拽，
            // 松手时把 Click 吞掉，看起来就是「点了没反应」（Qt 原版用框架 DnD，没有这个问题）
            if (!_dragging && (Math.Abs(p.Y - _dragStart.Y) > 14 || Math.Abs(p.X - _dragStart.X) > 20))
            {
                _dragging = true;
                btn.Opacity = 0.45;
                btn.CaptureMouse();
                _dropLine ??= new Border { Height = 2, CornerRadius = new CornerRadius(1), Margin = new Thickness(14, 1, 14, 1) };
                _dropLine.SetResourceReference(Border.BackgroundProperty, "B.Accent");
            }
            if (_dragging) UpdateDrop(p);
        };
        btn.PreviewMouseLeftButtonUp += (_, e) =>
        {
            if (_dragRow == row && _dragging)
            {
                btn.ReleaseMouseCapture();
                btn.Opacity = 1;
                RemoveDropLine();
                // 只有真的换到别的落点才算拖拽完成、吞掉 Click；
                // 拖回原地 / 没有落点 = 用户其实就是想点一下，不能吞
                var moved = _dropTarget != null && _dropTarget.Key != row.Key;
                if (_dropTarget != null) CommitDrop(row, _dropTarget, _dropBefore);
                if (moved) e.Handled = true;
            }
            _dragRow = null;
            _dragging = false;
            _dropTarget = null;
        };
    }

    private void RemoveDropLine()
    {
        if (_dropLine?.Parent is Panel p) p.Children.Remove(_dropLine);
    }

    /// <summary>找鼠标下面那一行（顶层行、分区标题或分区里的子页），把落点线画在它上方或下方。</summary>
    private void UpdateDrop(Point mouse)
    {
        RemoveDropLine();
        _dropTarget = null;
        var screen = PointToScreen(mouse);
        foreach (var row in _navRows.Values)
        {
            if (row == _dragRow || !row.Button.IsVisible) continue;
            var local = row.Button.PointFromScreen(screen);
            var h = row.Button.ActualHeight;
            if (local.Y < -3 || local.Y > h + 3) continue;
            _dropTarget = row;
            _dropBefore = local.Y < h / 2;
            if (row.Button.Parent is Panel panel)
            {
                var at = panel.Children.IndexOf(row.Button) + (_dropBefore ? 0 : 1);
                panel.Children.Insert(Math.Min(at, panel.Children.Count), _dropLine!);
            }
            return;
        }
    }

    private void CommitDrop(NavRow dragged, NavRow target, bool before)
    {
        if (dragged.Key == target.Key) return;
        Dictionary<string, object?>? patch = null;

        if (dragged.Section != null)
        {
            if (target.Section != null)
            {
                // 分区内 / 分区间挪子页
                var members = NavModel.SectionMembersFromConfig(_navCfg);
                var at = members[target.Section].IndexOf(target.Key);
                if (at < 0) return;
                if (dragged.Section == target.Section && members[target.Section].IndexOf(dragged.Key) < at) at--;
                MoveMember(dragged.Key, dragged.Section, target.Section, at + (before ? 0 : 1));
                return;
            }
            if (target.IsSectionHeader)
            {
                // 拖到另一个分区的标题上 = 换分区，排在末尾
                if (target.Key != dragged.Section) MoveMember(dragged.Key, dragged.Section, target.Key, -1);
                return;
            }
            // 拖到侧栏顶层 = 固定
            var res = NavModel.PinNavConfig(_navCfg, dragged.Key, target.Key, before);
            if (res is null) return;
            if (res.Error != null) { Toast(L("无法移出"), res.Error, ToastKind.Warning); return; }
            patch = res.Patch;
        }
        else if (NavModel.AllSubKeys.Contains(dragged.Key) && (target.IsSectionHeader || target.Section != null))
        {
            // 固定子页拖回分区标题 / 分区里 = 放回那个分区（直觉手势）
            var sec = target.Section ?? target.Key;
            var index = -1;
            if (target.Section != null)
            {
                var members = NavModel.SectionMembersFromConfig(_navCfg);
                var at = members[sec].IndexOf(target.Key);
                index = at < 0 ? -1 : at + (before ? 0 : 1);
            }
            var res = NavModel.UnpinNavConfig(_navCfg, dragged.Key, sec, index);
            if (res is null) return;
            patch = res.Value.Patch;
            _prefs.Expanded[res.Value.Section] = true;
            Toast(L("已取消固定"), L("「{0}」放回了「{1}」", NavModel.NavLabel(dragged.Key), NavModel.NavLabel(res.Value.Section)));
        }
        else if (target.Section is null)
        {
            patch = NavModel.ReorderNavConfig(_navCfg, dragged.Key, target.Key, before);
        }

        if (patch != null) Run(() => ApplyNavPatchAsync(patch));
    }
}
