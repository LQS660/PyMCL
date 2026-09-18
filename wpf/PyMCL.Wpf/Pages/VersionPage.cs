using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class VersionPage : PageBase
{
    public override string Title => L("原版游戏");

    private static readonly string[] Loaders = { L("无"), "Fabric", "Forge", "Quilt", "NeoForge" };

    private readonly TextBox _search = Ui.Input(L("过滤版本号，例如 1.20"));
    private readonly ListBox _list = new() { Style = Ui.S("PlainList"), ItemTemplate = (DataTemplate)Application.Current.FindResource("Tpl.Version") };
    private readonly ComboBox _inst = Ui.Combo();
    private readonly ComboBox _loader = Ui.Combo(Loaders);
    private readonly ComboBox _loaderVer = Ui.Combo(new[] { L("最新") });
    private readonly CheckBox _release = Ui.Check(L("正式版"), true);
    private readonly CheckBox _snapshot = Ui.Check(L("快照"), false);
    private readonly CheckBox _oldBeta = Ui.Check(L("旧测试"), false);
    private readonly CheckBox _oldAlpha = Ui.Check(L("旧阿尔法"), false);
    private readonly CheckBox _optifine = Ui.Check("OptiFine");
    private readonly CheckBox _lite = Ui.Check("LiteLoader");
    private readonly Button _install;
    private readonly TextBlock _count = Ui.Muted("");
    private readonly TextBlock _instCount = Ui.Muted("");
    private readonly WrapPanel _cards = new();
    private readonly TextBox _mineSearch = Ui.Input(L("过滤已安装版本"), width: 170);
    private readonly CheckBox _showHidden = Ui.Switch();
    private readonly SPanel _installedEmpty = Ui.Empty(Ico.Box, L("这个实例还没有版本"), L("在左边挑一个装上"));
    private List<Row> _all = new();
    private List<Installed> _mine = new();

    /// <summary>
    /// 在线拉取版本清单的超时（毫秒），与目录页搜索同一口径；冒烟 --smoke-search-timeout 把两个一起压低做负向对照。
    /// 到点就掐掉请求、显示错误条与「重试」，页面不会一直挂着「正在拉取」等网络。
    /// </summary>
    public static int FetchTimeoutMs = 9000;

    private CancellationTokenSource? _fetchCts;
    /// <summary>最新那次拉取还没收场（结果没落地、也没进错误态）。</summary>
    private bool _fetchInFlight;
    /// <summary>上一次拉取是被切页掐掉的（不是超时、不是被新拉取顶掉）：回到这一页时要补一次。</summary>
    private bool _fetchInterrupted;
    // 拉取失败 / 超时的错误条：一句原因 + 「重试」。有缓存清单时列表照旧显示，错误条只是叠在上面提醒。
    private readonly TextBlock _fetchErrorText = Ui.Muted("");
    private readonly Border _fetchError;

    /// <summary>一张已安装版本卡要显示的东西。</summary>
    private sealed class Installed
    {
        public string Id = "";
        public bool Hidden;
        public bool Isolated;
        public int Mods;
        public string Loader = "";
        public string Mc = "";
        public string IsolationLabel = "";
    }

    /// <summary>Tpl.Version 模板绑定 TypeLabel，包一层视图模型把类型翻译成中文。</summary>
    private sealed class Row
    {
        public string Version { get; init; } = "";
        public string Type { get; init; } = "";
        public string Date { get; init; } = "";
        public string TypeLabel => Type switch
        {
            "release" => L("正式版"),
            "snapshot" => L("快照"),
            "old_beta" => L("旧测试"),
            "old_alpha" => L("旧阿尔法"),
            _ => string.IsNullOrEmpty(Type) ? L("未知") : Type,
        };
    }

    private static Row Map(VersionRow r) => new() { Version = r.Version, Type = r.Type, Date = r.Date };

    public VersionPage()
    {
        _install = Ui.Btn(L("安装所选版本"), BtnKind.Primary, (_, _) => Run(InstallAsync), Ico.Download);
        _install.IsEnabled = false;

        var refresh = Ui.Btn(L("刷新清单"), BtnKind.Chip, (_, _) => Run(FetchAsync), Ico.Refresh);
        var head = Ui.Section(L("原版游戏"), L("Mojang 全量版本 + Fabric / Forge / Quilt / NeoForge 加载器"),
            Ui.H(8, _count.VCenter(), refresh));

        _search.TextChanged += (_, _) => ApplyFilter();
        foreach (var c in new[] { _release, _snapshot, _oldBeta, _oldAlpha })
        {
            c.Checked += (_, _) => ApplyFilter();
            c.Unchecked += (_, _) => ApplyFilter();
        }
        _list.SelectionChanged += (_, _) =>
        {
            _install.IsEnabled = _list.SelectedItem is Row;
            // 加载器版本跟着 MC 版本走，换版本要重拉。
            if (_loader.Str() != L("无")) Run(LoadLoaderVersionsAsync);
        };
        _list.MouseDoubleClick += (_, _) => Run(InstallAsync);
        _loader.SelectionChanged += (_, _) =>
        {
            var l = _loader.Str();
            _loaderVer.IsEnabled = l != L("无");
            _optifine.IsEnabled = l == L("无") || l == "Forge";
            if (!_optifine.IsEnabled) _optifine.IsChecked = false;
            Run(LoadLoaderVersionsAsync);
        };

        var filters = Ui.H(14, _release, _snapshot, _oldBeta, _oldAlpha);
        // 错误条：拉取超时 / 出错时出现在列表上方，带「重试」；成功一次就收起
        var retry = Ui.Btn(L("重试"), BtnKind.Soft, (_, _) => Run(FetchAsync, L("版本清单刷新失败")), Ico.Refresh);
        var errRow = Ui.G(null, "Auto,*,Auto");
        errRow.Add(Ui.Glyph(Ico.Warning, 14, "B.Warn").VCenter().M(0, 0, 8, 0), 0, 0);
        errRow.Add(_fetchErrorText.Wrap().VCenter(), 0, 1);
        errRow.Add(retry.VCenter().M(8, 0, 0, 0), 0, 2);
        _fetchError = Ui.RowCard(errRow, padding: 10);
        _fetchError.Visibility = Visibility.Collapsed;
        var listCard = Ui.Card(Ui.V(10,
            Ui.H(10, _search, filters.VCenter()),
            _fetchError,
            _list), 14);
        _search.MinWidth = 240;
        _list.Height = 330;

        var setup = Ui.Card(Ui.V(10,
            Ui.H3(L("安装设置")),
            Ui.Field(L("目标实例"), _inst, labelWidth: 88),
            Ui.Field(L("加载器"), _loader, labelWidth: 88),
            Ui.Field(L("加载器版本"), _loaderVer, labelWidth: 88),
            Ui.H(16, _optifine, _lite),
            _install.Stretch()), 14);

        _mineSearch.TextChanged += (_, _) => RenderInstalled();
        _showHidden.Checked += (_, _) => Run(ReloadInstalledAsync);
        _showHidden.Unchecked += (_, _) => Run(ReloadInstalledAsync);
        var openGameDir = Ui.Btn(L("打开游戏目录"), BtnKind.Chip,
            (_, _) => Run(async () => await Api.CallAsync("open_version_folder",
                new { instance = _inst.Str(), version = "", which = "game" }), L("打开失败")), Ico.Folder);

        var installedHead = Ui.Section(L("已安装"), L("每个版本一张卡：启动、模组、设置都在卡上，「更多」里是重命名 / 复制 / 快捷方式 / 卸载"),
            Ui.H(8, _instCount.VCenter(), _mineSearch.VCenter(),
                Ui.H(6, Ui.Txt(L("显示隐藏"), 12, fg: "B.InkMuted").VCenter(), _showHidden).VCenter(),
                openGameDir));
        var installedCard = Ui.Card(Ui.V(10, installedHead, _cards, _installedEmpty), 14);

        var cols = Ui.G(null, "*,320");
        cols.Add(Ui.V(14, listCard, installedCard), 0, 0);
        cols.Add(Ui.V(14, setup).M(14, 0, 0, 0), 0, 1);

        Content = ScrollBody(head, cols);

        // 版本页最常被拖进来的是整合包；其余类型按内容认，装进本页选中的实例
        EnableDrop(() => new FileDrop.DropContext
        {
            Instance = _inst.Str(),
            PreferKind = FileKinds.Modpack,
        });
    }

    protected override async Task LoadAsync()
    {
        var insts = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _inst.Fill(insts.Select(i => i.Name));
        var cached = await Api.TryCallAsync<List<VersionRow>>("get_version_list", null, new()) ?? new();
        if (cached.Count > 0)
        {
            _all = cached.Select(Map).ToList();
            ApplyFilter();
        }
        await ReloadInstalledAsync();
        // 在线拉取另起一条（令牌 + 超时），首载不等它：有缓存先显示缓存，没有就先看「正在拉取…」。
        // 以前没缓存时同步等它返回，网络一慢首载就随着走十几秒到一分钟。
        Run(FetchAsync, L("版本清单刷新失败"));
    }

    /// <summary>
    /// 在线拉取版本清单。带令牌 + FetchTimeoutMs 超时；重拉时掐掉上一次，切页也掐掉（回来补）。
    /// 三种收场：清单落地 / 超时或出错 → 错误条 + 重试（有缓存清单时列表照旧，只多一条提醒）/ 被掐掉 → 什么都不画。
    /// 照 CatalogPage.SearchAsync 那套：用 cts 引用区分「被新拉取顶掉」，用 _fetchInterrupted 区分「切页」。
    /// </summary>
    private async Task FetchAsync()
    {
        CancelFetch();
        var cts = _fetchCts = new CancellationTokenSource(FetchTimeoutMs);
        _fetchInterrupted = false;
        _fetchInFlight = true;
        _fetchError.Visibility = Visibility.Collapsed;
        _count.Text = L("正在拉取版本清单…");
        try
        {
            var rows = await Api.CallAsync<List<VersionRow>>("fetch_version_list", null, cts.Token) ?? new();
            if (!ReferenceEquals(cts, _fetchCts)) return; // 被更新的一次顶掉了：那一次自己会画
            if (rows.Count > 0)
            {
                _all = rows.Select(Map).ToList();
                ApplyFilter();
            }
            else ShowFetchFailure(L("版本清单刷新失败"), L("拉取失败，检查网络后点刷新"));
        }
        catch (OperationCanceledException)
        {
            if (!ReferenceEquals(cts, _fetchCts) || _fetchInterrupted) return;
            ShowFetchFailure(L("拉取超时"), L("{0} 秒内没等到版本清单。检查网络后重试。", Math.Max(1, (FetchTimeoutMs + 999) / 1000)));
        }
        catch (Exception ex)
        {
            if (!ReferenceEquals(cts, _fetchCts)) return;
            ShowFetchFailure(L("版本清单刷新失败"), ex.Message);
        }
        finally
        {
            // 只有最新那一次有资格说「拉取收场了」
            if (ReferenceEquals(cts, _fetchCts)) _fetchInFlight = false;
        }
    }

    /// <summary>掐掉在飞的拉取（如果有）。</summary>
    private void CancelFetch()
    {
        _fetchInFlight = false;
        var cts = _fetchCts;
        _fetchCts = null;
        if (cts is null) return;
        try { cts.Cancel(); } catch (ObjectDisposedException) { }
        cts.Dispose();
    }

    /// <summary>错误态：错误条说清原因、给「重试」。有缓存清单就沿用并照旧计数，一条都没有才把计数换成失败提示。</summary>
    private void ShowFetchFailure(string title, string detail)
    {
        _fetchErrorText.Text = title + " · " + detail;
        _fetchError.Visibility = Visibility.Visible;
        if (_all.Count == 0) _count.Text = L("拉取失败，检查网络后点刷新");
        else
        {
            ApplyFilter();
            Toast(L("版本清单刷新失败"), L("沿用已缓存的清单"), ToastKind.Warning);
        }
    }

    private void ApplyFilter()
    {
        var q = _search.Text?.Trim() ?? "";
        var want = new HashSet<string>();
        if (_release.IsChecked == true) want.Add("release");
        if (_snapshot.IsChecked == true) want.Add("snapshot");
        if (_oldBeta.IsChecked == true) want.Add("old_beta");
        if (_oldAlpha.IsChecked == true) want.Add("old_alpha");
        var rows = _all.Where(r => want.Contains(r.Type));
        if (q.Length > 0) rows = rows.Where(r => r.Version.Contains(q, StringComparison.OrdinalIgnoreCase));
        var final = rows.ToList();
        _list.ItemsSource = final;
        _count.Text = L("{0} / {1} 个版本", final.Count, _all.Count);
        if (final.Count > 0 && _list.SelectedIndex < 0) _list.SelectedIndex = 0;
    }

    /// <summary>
    /// 读一遍已装版本。走 get_version_rows：隔离状态、模组数、加载器标签与配色后端一次算好，
    /// 不再逐个版本问「设置 + 模组清单」两条 RPC——20 个版本从 40 次往返降到 1 次。
    /// </summary>
    private async Task ReloadInstalledAsync()
    {
        var inst = _inst.Str();
        var showHidden = _showHidden.IsChecked == true;
        if (string.IsNullOrEmpty(inst))
        {
            _mine = new List<Installed>();
            RenderInstalled();
            return;
        }
        var rows = await Api.TryCallAsync<List<VersionRowDto>>("get_version_rows",
            new { include_hidden = true }, new()) ?? new();
        _mine = rows
            .Where(r => showHidden || !r.Hidden)
            .Select(r => new Installed
            {
                Id = r.Id,
                Hidden = r.Hidden,
                Isolated = r.Isolated,
                Mods = r.Mods,
                Loader = string.IsNullOrEmpty(r.Loader) ? L("原版") : r.Loader,
                Mc = r.Mc,
                IsolationLabel = r.IsolationLabel,
            })
            .ToList();
        RenderInstalled();
    }

    private void RenderInstalled()
    {
        var q = _mineSearch.Text?.Trim() ?? "";
        var shown = q.Length == 0
            ? _mine
            : _mine.Where(r => r.Id.Contains(q, StringComparison.OrdinalIgnoreCase)).ToList();
        _instCount.Text = q.Length == 0 ? L("{0} 个", _mine.Count) : L("{0} / {1} 个", shown.Count, _mine.Count);
        _cards.Children.Clear();
        _installedEmpty.Show(shown.Count == 0);
        foreach (var row in shown) _cards.Children.Add(VersionCard(row));
        Motion.StaggerItems(_cards.Children.Cast<UIElement>(), 26, 210, 10);
    }

    private UIElement VersionCard(Installed row)
    {
        var inst = _inst.Str();
        var id = row.Id;

        var chips = Ui.H(6,
            Ui.Tag(row.Loader, "B.AccentDeep", "B.AccentSoft"),
            Ui.Tag(L("模组 {0}", row.Mods)),
            string.IsNullOrEmpty(row.IsolationLabel) ? null : Ui.Tag(row.IsolationLabel),
            row.Hidden ? Ui.Tag(L("已隐藏")) : null);

        var iso = Ui.Switch(row.Isolated);
        iso.Checked += (_, _) => Run(() => ToggleIsolationAsync(id, true), L("切换失败"));
        iso.Unchecked += (_, _) => Run(() => ToggleIsolationAsync(id, false), L("切换失败"));
        var isoRow = Ui.H(8,
            Ui.Txt(L("独立模组"), 12, fg: "B.InkMuted").VCenter(),
            iso);
        isoRow.ToolTip = L("开：这个版本用自己的 mods / config；关：与实例里其它版本共用那一份");

        var play = Ui.Btn(L("启动"), BtnKind.Soft, (_, _) => Run(() => LaunchAsync(id)), Ico.Play);
        var mods = Ui.IconBtn(Ico.Puzzle, L("管理这个版本的模组"),
            (_, _) => Run(async () => { await ModsDialog.ShowAsync(inst, id); await ReloadInstalledAsync(); }));
        var setup = Ui.IconBtn(Ico.Gear, L("版本设置"),
            (_, _) => Run(async () => { await VersionSetupDialog.ShowAsync(inst, id); await ReloadInstalledAsync(); }));
        var more = Ui.IconBtn(Ico.More, L("更多"), (s, _) => MoreMenu((FrameworkElement)s, id, row));

        var body = Ui.V(8,
            Ui.H(10,
                new ThumbTile(id, 38, 10),
                Ui.V(2, Ui.Txt(id, 13.5, true).Trim(),
                    Ui.Small(string.IsNullOrEmpty(row.Mc) ? (row.Hidden ? L("在列表中隐藏") : L("已安装"))
                                                          : "Minecraft " + row.Mc)).VCenter()),
            chips,
            isoRow,
            Ui.Sep(),
            Ui.H(6, play, mods, setup, more));
        var card = Ui.Card(body, 14);
        card.Width = 252;
        card.Margin = new Thickness(0, 0, 12, 12);
        Motion.HoverLift(card, 1.006, 2, 18);
        return card;
    }

    /// <summary>
    /// 独立模组开关。走 toggle_version_isolation 正门（t-490 之前桥上没有这个方法，
    /// 只能拿 save_version_settings 改 isolation 字段绕过去，那条路不会帮你复制现有模组）。
    /// 转成独立时问一句要不要把共享池里的模组带一份过去——对齐 Qt 的 seed 参数。
    /// </summary>
    private async Task ToggleIsolationAsync(string version, bool isolated)
    {
        var seed = false;
        if (isolated)
        {
            var pick = await Dlg.Choose(L("转为独立模组"),
                Ui.Muted(L("「{0}」将拥有自己的 mods / config 目录。\n\n", version)
                         + L("要把游戏目录里现有的共享模组复制一份过去吗？\n")
                         + L("选「复制一份」保持现在能玩的样子；选「留空」从零开始装。")).Wrap().MinW(380),
                new[] { L("取消"), L("留空"), L("复制一份") }, 540);
            if (pick <= 0) { await ReloadInstalledAsync(); return; }
            seed = pick == 2;
        }
        await Api.CallAsync("toggle_version_isolation", new { version, isolated, seed });
        Toast(isolated ? L("已转为独立模组") : L("已改回共用"),
            isolated
                ? L("「{0}」以后用自己的 mods / config", version) + (seed ? L("，已复制一份现有模组") : "")
                : L("「{0}」与实例里其它版本共用 mods", version), ToastKind.Success);
        await ReloadInstalledAsync();
    }

    private async Task LaunchAsync(string version)
    {
        var inst = _inst.Str();
        await InstancePage.SetDefaultAsync(inst);
        if (Win?.GetPage("launch") is LaunchPage lp) lp.PreferInstance(inst, version);
        Win?.Navigate("launch");
    }

    private void MoreMenu(FrameworkElement anchor, string version, Installed row)
    {
        var inst = _inst.Str();
        var menu = new ContextMenu();
        void Item(string head, Func<Task> act)
        {
            var mi = new MenuItem { Header = head };
            mi.Click += (_, _) => Run(act);
            menu.Items.Add(mi);
        }
        Item(L("打开版本文件夹"), async () =>
            await Api.CallAsync("open_version_folder", new { instance = inst, version, which = "root" }));
        Item(L("打开游戏文件夹"), async () =>
            await Api.CallAsync("open_version_folder", new { instance = inst, version, which = "game" }));
        Item(L("存档管理…"), async () => await SavesDialog.ShowAsync(inst, version));
        Item(L("隔离细分…"), () => IsolationDetailAsync(version));
        menu.Items.Add(new Separator());
        Item(L("重命名"), async () =>
        {
            var name = await Dlg.Prompt(L("重命名版本"), L("新版本 ID"), version);
            if (string.IsNullOrWhiteSpace(name) || name == version) return;
            await Api.CallAsync("rename_version", new { instance = inst, version, new_id = name });
            await ReloadInstalledAsync();
        });
        Item(L("复制一份"), async () =>
        {
            var copy = await Dlg.Prompt(L("复制版本"), L("新版本 ID"), version + "-copy");
            if (string.IsNullOrWhiteSpace(copy)) return;
            await Api.CallAsync("copy_version", new { instance = inst, version, new_id = copy });
            await ReloadInstalledAsync();
        });
        Item(row.Hidden ? L("取消隐藏") : L("在列表中隐藏"), async () =>
        {
            // 隐藏只影响列表显示，版本文件一个不动；启动页的下拉会跟着少一项。
            await Api.CallAsync("hide_version", new { instance = inst, version, hidden = !row.Hidden });
            await ReloadInstalledAsync();
            Toast(row.Hidden ? L("已取消隐藏") : L("已隐藏"), version, ToastKind.Success);
        });
        Item(L("创建桌面快捷方式"), async () =>
        {
            var path = await Api.CallAsync<string>("create_desktop_shortcut", new { instance = inst, version });
            await Dlg.Alert(L("已创建"), L("桌面快捷方式：\n{0}\n\n双击即可直接启动该版本。", path));
        });
        Item(L("导出启动脚本"), async () =>
        {
            var dest = Dlg.SaveFile(L("批处理 (*.bat)|*.bat"), $"launch-{inst}-{version}.bat", L("导出启动脚本"));
            if (dest is null) return;
            await Api.StartTaskAsync("export_launch_script", new { instance = inst, version, dest });
            Win?.FlyToTasks(anchor, L("导出中"));
        });
        Item(L("修复（补全缺失文件）"), async () =>
        {
            await Api.StartTaskAsync("repair_version", new { instance = inst, version });
            Win?.FlyToTasks(anchor, L("修复中"));
        });
        menu.Items.Add(new Separator());
        Item(L("卸载这个版本"), async () =>
        {
            if (!await Dlg.Confirm(L("卸载版本"),
                    L("确定卸载「{0}」？该版本目录下的独立模组与存档会一并删除。", version), L("卸载"), L("取消"), true)) return;
            await Api.CallAsync("uninstall_version", new { spec = $"{inst} / {version}" });
            await ReloadInstalledAsync();
            Toast(L("已卸载"), version, ToastKind.Success);
        });
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    /// <summary>隔离细分：跟 Qt 的「隔离细分…」同一组档位，读写都走桥上的隔离接口。</summary>
    private async Task IsolationDetailAsync(string version)
    {
        string[] labels = { L("关闭（共用游戏目录）"), L("隔离存档"), L("隔离 Mod 与配置"), L("隔离全部") };
        string[] values = { "none", "saves", "mods", "all" };
        var cur = await Api.TryCallAsync<string>("get_version_isolation", new { version }, "none") ?? "none";
        var idx = Math.Max(0, Array.IndexOf(values, cur));
        var pick = Ui.Combo(labels, labels[idx]);
        var seed = Ui.Check(L("把共享池里的模组复制一份过去"), false);
        if (!await Dlg.Ask(L("隔离细分 · {0}", version),
                Ui.V(8,
                    Ui.Muted(L("决定这个版本的存档 / 模组是自己一份，还是与游戏目录里其它版本共用")),
                    pick, seed), L("保存"))) return;
        await Api.CallAsync("set_version_isolation", new
        {
            version,
            mode = values[Math.Max(0, pick.SelectedIndex)],
            seed = seed.IsChecked == true,
        });
        await ReloadInstalledAsync();
    }

    private async Task LoadLoaderVersionsAsync()
    {
        var loader = _loader.Str();
        if (loader == L("无") || _list.SelectedItem is not Row row)
        {
            _loaderVer.Fill(new[] { L("最新") });
            return;
        }
        _loaderVer.Fill(new[] { L("最新（加载中…）") });
        var rows = await Api.TryCallAsync<List<LoaderVer>>("list_loader_versions",
            new { mc_version = row.Version, loader = loader.ToLowerInvariant() }, new()) ?? new();
        var labels = new List<string> { L("最新") };
        labels.AddRange(rows.Select(r => string.IsNullOrEmpty(r.Label) ? r.Id : r.Label));
        _loaderVer.Fill(labels, L("最新"));
        _loaderVer.Tag = rows;
    }

    private async Task InstallAsync()
    {
        if (_list.SelectedItem is not Row row)
        {
            Toast(L("先选一个版本"), "", ToastKind.Warning);
            return;
        }
        var loader = _loader.Str();
        var none = loader == L("无");
        var loaderVersion = "";
        if (!none && _loaderVer.SelectedIndex > 0 && _loaderVer.Tag is List<LoaderVer> rows)
        {
            var idx = _loaderVer.SelectedIndex - 1;
            if (idx >= 0 && idx < rows.Count) loaderVersion = rows[idx].Id;
        }
        var extra = new Dictionary<string, object?>
        {
            ["optifine"] = _optifine.IsChecked == true,
            ["liteloader"] = _lite.IsChecked == true,
        };
        await Api.StartTaskAsync("install_game", new
        {
            version = row.Version,
            // 桥的 install_game 把空串和「无」都当作不装加载器；发空串，不把界面词当协议值
            loader = none ? "" : loader,
            loader_version = loaderVersion,
            instance = _inst.Str(),
            extra,
        });
        Win?.FlyToTasks(_install, row.Version);
        Toast(L("已加入队列"), $"{row.Version}{(none ? "" : " + " + loader)}", ToastKind.Success);
        Win?.Navigate("tasks");
    }

    public override async Task RefreshAsync() => await ReloadInstalledAsync();

    public override void OnShown()
    {
        _inst.SelectionChanged -= InstChanged;
        _inst.SelectionChanged += InstChanged;
        // 切走时被掐掉的那次拉取，回来补上——「正在拉取」不能一直挂着
        if (_fetchInterrupted) Run(FetchAsync, L("版本清单刷新失败"));
    }

    /// <summary>切页就把在飞的拉取掐掉：省一次没人看的网络请求，也别让它回头改一个看不见的页面。</summary>
    public override void OnHidden()
    {
        if (!_fetchInFlight) return;
        _fetchInterrupted = true;
        CancelFetch();
    }

    private void InstChanged(object? s, SelectionChangedEventArgs e) => Run(ReloadInstalledAsync);
}
