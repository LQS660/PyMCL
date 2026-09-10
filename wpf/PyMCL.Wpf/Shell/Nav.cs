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

public sealed class UiPrefs
{
    public double SideWidth { get; set; } = 196;
    public bool Dark { get; set; }
    public bool Anim { get; set; } = true;
    public double AnimScale { get; set; } = 1;
    public List<string> Top { get; set; } = new();
    public Dictionary<string, List<string>> Groups { get; set; } = new();
    public List<string> Hidden { get; set; } = new();
    public Dictionary<string, bool> Expanded { get; set; } = new();
    public string LayoutJson { get; set; } = "";
    public string Notes { get; set; } = "";
    public string LastUser { get; set; } = "";
    public string CatalogInstance { get; set; } = "";
}

public partial class MainWindow
{
    public static readonly List<NavDef> NavDefs = new()
    {
        new("launch", "启动", Ico.Rocket, () => new LaunchPage()),
        new("instance", "实例", Ico.Grid, () => new InstancePage()),
        new("version", "原版游戏", Ico.Box, () => new VersionPage()),
        new("mod", "Mod", Ico.Puzzle, () => new CatalogPage(Models.CatalogKind.Mod)),
        new("modpack", "整合包", Ico.Package, () => new CatalogPage(Models.CatalogKind.Modpack)),
        new("datapack", "数据包", Ico.Data, () => new CatalogPage(Models.CatalogKind.Datapack)),
        new("resourcepack", "资源包", Ico.Image, () => new CatalogPage(Models.CatalogKind.ResourcePack)),
        new("shader", "光影包", Ico.Sun, () => new CatalogPage(Models.CatalogKind.Shader)),
        new("world", "世界", Ico.World, () => new CatalogPage(Models.CatalogKind.World)),
        new("account", "账号", Ico.User, () => new AccountPage()),
        new("java", "Java", Ico.Coffee, () => new JavaPage()),
        new("ai", "AI 助手", Ico.Robot, () => new AiPage()),
        new("multiplayer", "联机", Ico.Wifi, () => new MultiplayerPage()),
        new("servers", "服务器", Ico.Server, () => new ServersPage()),
        new("playtime", "游戏时长", Ico.Clock, () => new PlaytimePage()),
        new("feedback", "反馈与帮助", Ico.Chat, () => new FeedbackPage()),
        new("settings", "设置", Ico.Gear, () => new SettingsPage()),
        new("tasks", "下载任务", Ico.Download, () => new TasksPage()),
    };

    private static readonly Dictionary<string, string> GroupTitles = new()
    {
        ["#download"] = "下载",
        ["#more"] = "更多",
    };

    private readonly Dictionary<string, ToggleButton> _navRows = new();
    private readonly Dictionary<string, StackPanel> _groupPanels = new();
    private UiPrefs _prefs = new();
    private Border? _taskBadge;
    private TextBlock? _taskBadgeText;

    private static UiPrefs DefaultPrefs() => new()
    {
        Top = new List<string> { "launch", "instance", "#download", "#more", "settings" },
        Groups = new Dictionary<string, List<string>>
        {
            ["#download"] = new() { "version", "mod", "modpack", "datapack", "resourcepack", "shader", "world" },
            ["#more"] = new() { "account", "java", "ai", "multiplayer", "servers", "playtime", "feedback" },
        },
        Expanded = new Dictionary<string, bool> { ["#download"] = true, ["#more"] = false },
    };

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
            if (File.Exists(PrefsPath))
                _prefs = JsonSerializer.Deserialize<UiPrefs>(File.ReadAllText(PrefsPath)) ?? DefaultPrefs();
            else
                _prefs = DefaultPrefs();
        }
        catch { _prefs = DefaultPrefs(); }

        if (_prefs.Top.Count == 0) _prefs = DefaultPrefs();
        // 补齐新增页面，别让升级后的新入口凭空消失。
        var known = new HashSet<string>(_prefs.Top);
        foreach (var kv in _prefs.Groups)
            foreach (var id in kv.Value) known.Add(id);
        foreach (var def in NavDefs)
        {
            if (def.Id == "tasks" || known.Contains(def.Id)) continue;
            var target = DefaultPrefs().Groups.FirstOrDefault(g => g.Value.Contains(def.Id)).Key;
            if (target != null && _prefs.Groups.TryGetValue(target, out var list)) list.Add(def.Id);
            else _prefs.Top.Add(def.Id);
        }

        SideCol.Width = new GridLength(Math.Clamp(_prefs.SideWidth, 150, 320));
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

    public void ResetNavLayout()
    {
        var keep = _prefs;
        _prefs = DefaultPrefs();
        _prefs.SideWidth = 196;
        _prefs.Dark = keep.Dark;
        _prefs.Anim = keep.Anim;
        _prefs.AnimScale = keep.AnimScale;
        _prefs.LayoutJson = keep.LayoutJson;
        SideCol.Width = new GridLength(196);
        BuildNav();
        SaveUiPrefs();
    }

    private void SideGrip_DragDelta(object sender, DragDeltaEventArgs e)
    {
        var w = Math.Clamp(SideCol.Width.Value + e.HorizontalChange, 150, 320);
        SideCol.Width = new GridLength(w);
        _prefs.SideWidth = w;
    }

    // ==================== 构建 ====================
    private void BuildNav()
    {
        NavHost.Children.Clear();
        PinnedHost.Children.Clear();
        _navRows.Clear();
        _groupPanels.Clear();

        foreach (var entry in _prefs.Top.ToList())
        {
            if (entry.StartsWith('#')) NavHost.Children.Add(BuildGroup(entry));
            else
            {
                var def = NavDefs.FirstOrDefault(d => d.Id == entry);
                if (def != null && !_prefs.Hidden.Contains(entry)) NavHost.Children.Add(MakeRow(def));
            }
        }

        PinnedHost.Children.Add(Ui.Sep().M(14, 0, 14, 6));
        var tasks = NavDefs.First(d => d.Id == "tasks");
        PinnedHost.Children.Add(MakeRow(tasks, pinned: true));
        SyncNavSelection();
        SyncTasks();
    }

    private UIElement BuildGroup(string key)
    {
        var open = _prefs.Expanded.TryGetValue(key, out var v) && v;
        var chev = Ui.Glyph(Ico.ChevronRight, 10, "B.InkFaint");
        var rot = new RotateTransform(open ? 90 : 0);
        chev.RenderTransform = rot;
        chev.RenderTransformOrigin = new Point(0.5, 0.5);

        var header = new Border
        {
            Height = 30,
            Margin = new Thickness(8, 6, 8, 2),
            CornerRadius = new CornerRadius(7),
            Background = Brushes.Transparent,
            Cursor = Cursors.Hand,
            Child = Ui.H(8, chev, Ui.Txt(GroupTitles.GetValueOrDefault(key, key), 11.5, fg: "B.InkFaint")).M(12, 0, 0, 0).VCenter(),
            Tag = key,
        };

        var panel = new StackPanel { ClipToBounds = true };
        _groupPanels[key] = panel;
        foreach (var id in _prefs.Groups.GetValueOrDefault(key, new List<string>()))
        {
            var def = NavDefs.FirstOrDefault(d => d.Id == id);
            if (def != null && !_prefs.Hidden.Contains(id)) panel.Children.Add(MakeRow(def, sub: true));
        }
        panel.Visibility = open ? Visibility.Visible : Visibility.Collapsed;

        header.MouseLeftButtonUp += (_, _) =>
        {
            var nowOpen = panel.Visibility != Visibility.Visible;
            _prefs.Expanded[key] = nowOpen;
            SaveUiPrefs();
            chev.RenderTransform = rot;
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
        header.MouseEnter += (_, _) => header.SetResourceReference(Border.BackgroundProperty, "B.Hover");
        header.MouseLeave += (_, _) => header.Background = Brushes.Transparent;
        header.ContextMenu = GroupMenu(key);

        var wrap = new StackPanel { Tag = key };
        wrap.Children.Add(header);
        wrap.Children.Add(panel);
        return wrap;
    }

    private ToggleButton MakeRow(NavDef def, bool sub = false, bool pinned = false)
    {
        var glyph = Ui.Glyph(def.Glyph, 14);
        var text = Ui.Txt(def.Title, 13).VCenter();
        text.TextTrimming = TextTrimming.CharacterEllipsis;
        var row = Ui.G(null, "18,*,Auto");
        row.Add(glyph, 0, 0);
        row.Add(text.M(10, 0, 0, 0), 0, 1);
        if (def.Id == "tasks")
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

        var btn = new ToggleButton
        {
            Style = Ui.S("NavItem"),
            Content = row,
            Tag = def.Id,
            Margin = new Thickness(sub ? 12 : 0, 0, 0, 0),
        };
        if (sub) glyph.Opacity = 0.85;
        btn.Click += (_, _) =>
        {
            btn.IsChecked = true;
            Navigate(def.Id);
        };
        btn.ContextMenu = RowMenu(def, sub, pinned);
        if (!pinned) AttachDrag(btn, def.Id, sub);
        _navRows[def.Id] = btn;
        return btn;
    }

    private ContextMenu RowMenu(NavDef def, bool sub, bool pinned)
    {
        var menu = new ContextMenu();
        if (!pinned)
        {
            foreach (var (key, title) in GroupTitles)
            {
                if (sub && _prefs.Groups.GetValueOrDefault(key, new()).Contains(def.Id)) continue;
                var mi = new MenuItem { Header = $"移到「{title}」分区" };
                mi.Click += (_, _) => MoveTo(def.Id, key, -1);
                menu.Items.Add(mi);
            }
            if (sub)
            {
                var up = new MenuItem { Header = "提为一级入口" };
                up.Click += (_, _) => MoveTo(def.Id, null, -1);
                menu.Items.Add(up);
            }
            var hide = new MenuItem { Header = "隐藏此入口" };
            hide.Click += (_, _) =>
            {
                if (!_prefs.Hidden.Contains(def.Id)) _prefs.Hidden.Add(def.Id);
                if (_currentId == def.Id) Navigate("launch");
                BuildNav();
                SaveUiPrefs();
                Toast("已隐藏", $"「{def.Title}」可在设置 → 侧栏里恢复");
            };
            menu.Items.Add(hide);
        }
        var reset = new MenuItem { Header = "恢复默认侧栏" };
        reset.Click += (_, _) => ResetNavLayout();
        menu.Items.Add(reset);
        return menu;
    }

    private ContextMenu GroupMenu(string key)
    {
        var menu = new ContextMenu();
        var all = new MenuItem { Header = "全部展开 / 收起" };
        all.Click += (_, _) =>
        {
            var target = !(_prefs.Expanded.GetValueOrDefault(key));
            foreach (var k in GroupTitles.Keys) _prefs.Expanded[k] = target;
            BuildNav();
            SaveUiPrefs();
        };
        menu.Items.Add(all);
        var reset = new MenuItem { Header = "恢复默认侧栏" };
        reset.Click += (_, _) => ResetNavLayout();
        menu.Items.Add(reset);
        return menu;
    }

    // ==================== 模型操作 ====================
    private void MoveTo(string id, string? group, int index)
    {
        _prefs.Top.Remove(id);
        foreach (var list in _prefs.Groups.Values) list.Remove(id);
        if (group is null)
        {
            var at = index < 0 ? _prefs.Top.Count : Math.Clamp(index, 0, _prefs.Top.Count);
            _prefs.Top.Insert(at, id);
        }
        else
        {
            var list = _prefs.Groups.TryGetValue(group, out var l) ? l : _prefs.Groups[group] = new List<string>();
            var at = index < 0 ? list.Count : Math.Clamp(index, 0, list.Count);
            list.Insert(at, id);
            _prefs.Expanded[group] = true;
        }
        _prefs.Hidden.Remove(id);
        BuildNav();
        SaveUiPrefs();
    }

    public void ShowNavItem(string id, bool visible)
    {
        if (visible) _prefs.Hidden.Remove(id);
        else if (!_prefs.Hidden.Contains(id)) _prefs.Hidden.Add(id);
        BuildNav();
        SaveUiPrefs();
    }

    public bool IsNavHidden(string id) => _prefs.Hidden.Contains(id);

    private List<string> VisibleFlatOrder()
    {
        var list = new List<string>();
        foreach (var e in _prefs.Top)
        {
            if (e.StartsWith('#'))
            {
                foreach (var id in _prefs.Groups.GetValueOrDefault(e, new()))
                    if (!_prefs.Hidden.Contains(id)) list.Add(id);
            }
            else if (!_prefs.Hidden.Contains(e)) list.Add(e);
        }
        list.Add("tasks");
        return list;
    }

    private int NavOrderIndex(string id)
    {
        var i = VisibleFlatOrder().IndexOf(id);
        return i < 0 ? 99 : i;
    }

    private void SyncNavSelection()
    {
        foreach (var (id, btn) in _navRows) btn.IsChecked = id == _currentId;
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

    // ==================== 拖拽排序 ====================
    private Point _dragStart;
    private ToggleButton? _dragRow;
    private bool _dragging;
    private Border? _dropLine;
    private string? _dropGroup;
    private int _dropIndex = -1;

    private void AttachDrag(ToggleButton row, string id, bool sub)
    {
        row.PreviewMouseLeftButtonDown += (_, e) =>
        {
            _dragStart = e.GetPosition(this);
            _dragRow = row;
            _dragging = false;
        };
        row.PreviewMouseMove += (_, e) =>
        {
            if (_dragRow != row || e.LeftButton != MouseButtonState.Pressed) return;
            var p = e.GetPosition(this);
            if (!_dragging && (Math.Abs(p.Y - _dragStart.Y) > 6 || Math.Abs(p.X - _dragStart.X) > 10))
            {
                _dragging = true;
                row.Opacity = 0.45;
                row.CaptureMouse();
                EnsureDropLine();
            }
            if (_dragging) UpdateDrop(p);
        };
        row.PreviewMouseLeftButtonUp += (_, _) =>
        {
            if (_dragRow == row && _dragging)
            {
                row.ReleaseMouseCapture();
                row.Opacity = 1;
                RemoveDropLine();
                if (_dropIndex >= 0) MoveTo(id, _dropGroup, _dropIndex);
            }
            _dragRow = null;
            _dragging = false;
            _dropIndex = -1;
        };
    }

    private void EnsureDropLine()
    {
        _dropLine ??= new Border { Height = 2, CornerRadius = new CornerRadius(1), Margin = new Thickness(14, 1, 14, 1) };
        _dropLine.SetResourceReference(Border.BackgroundProperty, "B.Accent");
    }

    private void RemoveDropLine()
    {
        if (_dropLine?.Parent is Panel p) p.Children.Remove(_dropLine);
    }

    private void UpdateDrop(Point mouse)
    {
        RemoveDropLine();
        _dropGroup = null;
        _dropIndex = -1;

        foreach (var (key, panel) in _groupPanels)
        {
            if (panel.Visibility != Visibility.Visible || panel.ActualHeight <= 0) continue;
            var local = panel.PointFromScreen(PointToScreen(mouse));
            if (local.Y < -6 || local.Y > panel.ActualHeight + 6) continue;
            _dropGroup = key;
            _dropIndex = IndexAt(panel, local.Y);
            panel.Children.Insert(Math.Min(_dropIndex, panel.Children.Count), _dropLine!);
            return;
        }

        var topLocal = NavHost.PointFromScreen(PointToScreen(mouse));
        if (topLocal.Y < -20 || topLocal.Y > NavHost.ActualHeight + 20) return;
        _dropGroup = null;
        _dropIndex = IndexAt(NavHost, topLocal.Y);
        NavHost.Children.Insert(Math.Min(_dropIndex, NavHost.Children.Count), _dropLine!);
    }

    private static int IndexAt(Panel panel, double y)
    {
        double acc = 0;
        var i = 0;
        foreach (UIElement c in panel.Children)
        {
            var h = c.RenderSize.Height;
            if (y < acc + h / 2) return i;
            acc += h;
            i++;
        }
        return i;
    }
}
