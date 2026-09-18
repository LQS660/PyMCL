using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class InstancePage : PageBase
{
    public override string Title => L("实例");

    private readonly WrapPanel _grid = new();
    private readonly TextBlock _count = Ui.Muted("");
    private readonly TextBox _search = Ui.Input(L("过滤实例名"), width: 200);
    private readonly SPanel _empty = Ui.Empty(Ico.Grid, L("还没有实例"), L("点右上角「新建实例」建一个"));
    private readonly TextBlock _emptyTitle;
    private readonly DispatcherTimer _debounce = new() { Interval = TimeSpan.FromMilliseconds(220) };
    private readonly Dictionary<string, Card> _cards = new();
    private List<InstanceInfo> _rows = new();
    private string _defaultInstance = "";

    /// <summary>一张实例卡上会随刷新变化的那几处。卡本身按实例名复用，不重建。</summary>
    private sealed class Card
    {
        public required Border Root { get; init; }
        public required TextBlock Name { get; init; }
        public required TextBlock Sub { get; init; }
        public required SPanel Chips { get; init; }
        public InstanceInfo Info = new();
        public bool Default;
    }

    public InstancePage()
    {
        _emptyTitle = _empty.Children.OfType<TextBlock>().Skip(1).First();
        var create = Ui.Btn(L("新建实例"), BtnKind.Primary, (_, _) => Run(CreateAsync), Ico.Add);
        var import = Ui.Btn(L("导入官方启动器"), BtnKind.Chip, (_, _) => Run(MigrateAsync), Ico.Import);
        var openDir = Ui.Btn(L("打开游戏目录"), BtnKind.Chip, (_, _) => Run(OpenGameDirAsync, L("打开失败")), Ico.Folder);
        var refresh = Ui.Btn(L("刷新"), BtnKind.Chip, (_, _) => Run(LoadAsync), Ico.Refresh);
        var head = Ui.Section(L("实例"), L("每个实例是一份独立的 .minecraft，互不干扰"),
            Ui.H(8, _count.VCenter(), _search.VCenter(), openDir, import, refresh, create));

        _debounce.Tick += (_, _) =>
        {
            _debounce.Stop();
            Render();
        };
        _search.TextChanged += (_, _) =>
        {
            _debounce.Stop();
            _debounce.Start();
        };

        _empty.Visibility = Visibility.Collapsed;
        Content = ScrollBody(head, _grid, _empty);
    }

    protected override async Task LoadAsync()
    {
        _rows = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        // get_settings 目前不带 default_instance，先试 get_setting 单键读取；拿不到就沿用页内状态。
        var def = await Api.TryCallAsync<string>("get_setting", new { key = "default_instance", @default = "" }, "");
        if (!string.IsNullOrEmpty(def)) _defaultInstance = def;
        Render();
    }

    public override void OnHidden() => _debounce.Stop();

    /// <summary>
    /// 差量渲染：卡按实例名复用，只改名字 / 副标题 / 标签这几处。
    /// 全删全建的话每刷新一次主线程就被堵住几十毫秒，那几十毫秒里所有动画都是定住的。
    /// </summary>
    private void Render()
    {
        var q = _search.Text?.Trim() ?? "";
        var shown = q.Length == 0
            ? _rows
            : _rows.Where(r => r.Name.Contains(q, StringComparison.OrdinalIgnoreCase)).ToList();

        _count.Text = q.Length == 0 ? L("共 {0} 个", _rows.Count) : L("{0} / {1} 个", shown.Count, _rows.Count);
        _empty.Show(shown.Count == 0);
        _emptyTitle.Text = _rows.Count > 0 ? L("没有匹配的实例") : L("还没有实例");

        var wanted = shown.Select(r => r.Name).ToHashSet(StringComparer.Ordinal);
        foreach (var name in _cards.Keys.Where(k => !wanted.Contains(k)).ToList())
        {
            _grid.Children.Remove(_cards[name].Root);
            _cards.Remove(name);
        }

        var fresh = new List<UIElement>();
        for (var i = 0; i < shown.Count; i++)
        {
            var info = shown[i];
            if (!_cards.TryGetValue(info.Name, out var card))
            {
                card = BuildCard(info);
                _cards[info.Name] = card;
                _grid.Children.Add(card.Root);
                fresh.Add(card.Root);
            }
            Sync(card, info);
            // 过滤后顺序会变，只挪索引不碰控件本身。
            var at = _grid.Children.IndexOf(card.Root);
            if (at != i)
            {
                _grid.Children.RemoveAt(at);
                _grid.Children.Insert(i, card.Root);
            }
        }
        if (fresh.Count > 0) Motion.StaggerItems(fresh, 30, 220, 12);
    }

    private void Sync(Card card, InstanceInfo info)
    {
        var isDefault = info.Name == _defaultInstance;
        if (card.Info.Name == info.Name && card.Default == isDefault &&
            card.Info.Versions == info.Versions && card.Info.Pack == info.Pack &&
            card.Info.PackVersion == info.PackVersion && card.Info.McVersion == info.McVersion &&
            card.Info.JavaLabel == info.JavaLabel) return;

        card.Info = info;
        card.Default = isDefault;
        card.Name.Text = info.Name;
        card.Sub.Text = string.IsNullOrEmpty(info.Pack) ? info.Mc : $"{info.Pack} {info.PackVersion}".Trim();
        card.Chips.Children.Clear();
        if (isDefault) card.Chips.Children.Add(Ui.Tag(L("默认"), "B.OnAccent", "B.Accent"));
        card.Chips.Children.Add(Ui.Tag(L("{0} 个版本", info.Versions)));
        if (!string.IsNullOrEmpty(info.JavaLabel)) card.Chips.Children.Add(Ui.Tag(info.JavaLabel, "B.AccentDeep", "B.AccentSoft"));
        if (!string.IsNullOrEmpty(info.McVersion)) card.Chips.Children.Add(Ui.Tag("MC " + info.McVersion));
    }

    private Card BuildCard(InstanceInfo seed)
    {
        var name = Ui.Txt("", 15, true).Trim();
        var sub = Ui.Muted("");
        var chips = Ui.H(6);
        var instName = seed.Name;

        var play = Ui.Btn(L("启动"), BtnKind.Soft, (_, _) => Run(() => LaunchWithAsync(instName)), Ico.Play);
        var mods = Ui.IconBtn(Ico.Puzzle, L("管理这个实例的模组"),
            (_, _) => Run(async () => await ModsDialog.ShowAsync(instName)));
        var saves = Ui.IconBtn(Ico.Save, L("存档管理"),
            (_, _) => Run(async () => await SavesDialog.ShowAsync(instName, "")));
        var more = Ui.IconBtn(Ico.More, L("更多"), (s, _) => Menu((FrameworkElement)s, instName));

        var body = Ui.V(9,
            Ui.H(10, Icon(seed), Ui.V(2, name, sub).VCenter()),
            chips,
            Ui.Sep(),
            Ui.H(6, play, mods, saves, more));
        var card = Ui.Card(body, 15);
        card.Width = 268;
        card.Margin = new Thickness(0, 0, 12, 12);
        Motion.HoverLift(card);
        card.MouseLeftButtonUp += (_, e) =>
        {
            if (e.OriginalSource is DependencyObject d && FindButton(d) != null) return;
            Run(() => LaunchWithAsync(instName));
        };
        card.Cursor = Cursors.Hand;
        return new Card { Root = card, Name = name, Sub = sub, Chips = chips };
    }

    /// <summary>设为默认实例并跳到启动页。default_instance 是设置里的一个键，走 save_settings。</summary>
    private async Task LaunchWithAsync(string instance)
    {
        await SetDefaultAsync(instance);
        _defaultInstance = instance;
        if (Win?.GetPage("launch") is LaunchPage lp) lp.PreferInstance(instance);
        Win?.Navigate("launch");
        await LoadAsync();
    }

    internal static Task SetDefaultAsync(string instance) =>
        Api.CallAsync<object>("save_settings", new { data = new { default_instance = instance } });

    private static Button? FindButton(DependencyObject d)
    {
        while (d is not null)
        {
            if (d is Button b) return b;
            d = System.Windows.Media.VisualTreeHelper.GetParent(d);
        }
        return null;
    }

    private static UIElement Icon(InstanceInfo info)
    {
        var b = new Border
        {
            Width = 40, Height = 40, CornerRadius = new CornerRadius(10),
            Child = Ui.Glyph(string.IsNullOrEmpty(info.Pack) ? Ico.Grid : Ico.Package, 17, "B.AccentDeep").Center(),
        };
        b.SetResourceReference(Border.BackgroundProperty, "B.AccentSoft");
        return b;
    }

    private void Menu(FrameworkElement anchor, string instance)
    {
        var menu = new ContextMenu();
        void Item(string head, Func<Task> act)
        {
            var mi = new MenuItem { Header = head };
            mi.Click += (_, _) => Run(act);
            menu.Items.Add(mi);
        }
        Item(L("打开文件夹"), async () => await Api.CallAsync("open_instance_folder", new { name = instance }));
        Item(L("设为默认实例"), async () =>
        {
            await SetDefaultAsync(instance);
            _defaultInstance = instance;
            await LoadAsync();
            Toast(L("默认实例"), L("之后的启动将默认使用「{0}」", instance), ToastKind.Success);
        });
        Item(L("选择 Java…"), () => PickJavaAsync(instance));
        // 两条都留着：一条当场列出来挑着更新，一条丢后台扫、结果进下载任务。
        Item(L("挑着更新模组…"), () => ModsDialog.CheckUpdatesAsync(instance));
        Item(L("后台检查模组更新"), async () =>
        {
            await Api.StartTaskAsync("start_mod_updates", new { instance });
            Win?.FlyToTasks(anchor, L("检查更新"));
        });
        Item(L("导出为整合包"), async () =>
        {
            var dest = Dlg.SaveFile(L("Modrinth 整合包 (*.mrpack)|*.mrpack"), instance + ".mrpack", L("导出整合包"));
            if (dest is null) return;
            await Api.StartTaskAsync("export_modpack", new { instance, dest });
            Win?.FlyToTasks(anchor, L("导出中"));
        });
        menu.Items.Add(new Separator());
        Item(L("重命名…"), async () =>
        {
            var name = await Dlg.Prompt(L("重命名实例"), L("新名称"), instance);
            if (string.IsNullOrWhiteSpace(name) || name == instance) return;
            await Api.CallAsync("rename_instance", new { name = instance, new_name = name });
            await LoadAsync();
        });
        Item(L("删除实例"), async () =>
        {
            if (!await Dlg.Confirm(L("删除实例"), L("「{0}」下的版本、模组、存档都会被删除，且不可恢复。", instance),
                    L("永久删除"), L("取消"), true)) return;
            await Api.CallAsync("delete_instance", new { name = instance });
            await LoadAsync();
            Toast(L("已删除"), instance, ToastKind.Success);
        });
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private async Task PickJavaAsync(string instance)
    {
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance, scan_system = true }, new()) ?? new();
        if (opts.Count == 0)
        {
            Toast(L("没找到 Java"), L("去 Java 页下载一个"), ToastKind.Warning);
            return;
        }
        var cur = await Api.TryCallAsync<string>("java_combo_label_for", new { instance, options = opts }, "自动选择"); // i18n:ignore 桥的协议值（原文比对），不是界面词
        var combo = Ui.Combo(opts.Select(o => o.Label), cur);
        var label = await Api.TryCallAsync<string>("instance_java_label", new { name = instance }, "") ?? "";
        var body = Ui.V(8,
            Ui.Muted(L("留「自动选择」由启动器按版本匹配")),
            string.IsNullOrEmpty(label) ? null : Ui.Small(L("当前记录：") + label),
            combo);
        if (!await Dlg.Ask(L("为「{0}」选择 Java", instance), body, L("保存"))) return;
        var val = opts.FirstOrDefault(o => o.Label == combo.Str())?.Value ?? "自动选择"; // i18n:ignore 桥的协议值（原文比对），不是界面词
        await Api.CallAsync("set_instance_java", new { name = instance, java = val });
        await LoadAsync();
    }

    /// <summary>打开游戏根目录。路径直接问后端要（game_root_path），不再从设置键里拼。</summary>
    private async Task OpenGameDirAsync()
    {
        var root = await Api.TryCallAsync<string>("game_root_path", null, "") ?? "";
        var name = await Api.TryCallAsync<string>("game_root_name", null, "") ?? "";
        if (string.IsNullOrWhiteSpace(root) || !await Api.TryCallAsync<bool>("open_media", new { path = root }))
        {
            Toast(L("打不开游戏目录"), string.IsNullOrWhiteSpace(root) ? L("后端没给出目录") : root, ToastKind.Warning);
            return;
        }
        Toast(L("已打开"), string.IsNullOrEmpty(name) ? root : $"{name} · {root}", ToastKind.Success);
    }

    private async Task CreateAsync()
    {
        var name = await Dlg.Prompt(L("新建实例"), L("实例名称（会创建独立的 .minecraft）"), "", L("例如：1.20.1 生存"));
        if (string.IsNullOrWhiteSpace(name)) return;
        await Api.CallAsync("create_instance", new { name });
        await LoadAsync();
        Toast(L("已创建"), name, ToastKind.Success);
    }

    private async Task MigrateAsync()
    {
        var found = await Api.TryCallAsync<bool>("detect_official_launcher", null, false);
        if (!found)
        {
            Toast(L("没找到官方启动器"), L("未检测到 .minecraft 目录"), ToastKind.Warning);
            return;
        }
        var dir = await Api.TryCallAsync<string>("official_launcher_dir", null, "");
        var versions = await Api.TryCallAsync<List<string>>("scan_official_versions", null, new()) ?? new();
        var target = Ui.Input("default", "default");
        var body = Ui.V(8,
            Ui.Muted(L("检测到：{0}", dir)),
            Ui.Muted(L("可导入 {0} 个版本：{1}{2}", versions.Count, string.Join(L("、"), versions.Take(8)), (versions.Count > 8 ? " …" : ""))),
            Ui.Txt(L("导入到实例"), 12, fg: "B.InkMuted"),
            target);
        if (!await Dlg.Ask(L("导入官方启动器"), body, L("开始导入"))) return;
        await Api.StartTaskAsync("migrate_official_launcher", new { instance = target.Text?.Trim() ?? "default" });
        Toast(L("已开始导入"), L("进度看下载任务"));
    }
}
