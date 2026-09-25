using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Threading;
using Microsoft.Win32;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>Mod / 整合包 / 数据包 / 资源包 / 光影 / 世界共用的目录页，差异全在 CatalogKind 里。</summary>
public sealed class CatalogPage : PageBase
{
    public override string Title => _installedFirst ? L("模组") : _kind.Title;

    private static readonly string[] GameVersions =
    {
        L("全部"), "1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1",
        "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.7.10",
    };

    private enum Mode { Search, Installed, Favorites }

    private readonly CatalogKind _kind;
    private readonly TextBox _search = Ui.Input();
    private readonly ComboBox _source;
    private readonly ComboBox _type;
    // 可输入：清单里没有的冷门版本，用户自己敲一个（对齐 Qt 的 EditableComboBox）
    private readonly ComboBox _version = Ui.Combo(GameVersions, L("全部"), 140, editable: true);
    private readonly ComboBox _inst = Ui.Combo(width: 150);
    private readonly ComboBox _installedVer = Ui.Combo(width: 150);
    private static string _clipSeen = "";
    private readonly ListBox _results;
    private readonly SPanel _placeholder = Ui.V(10);
    private readonly Grid _listHost = new();
    private readonly ToggleButton _modeSearch;
    private readonly ToggleButton _modeInstalled;
    private readonly ToggleButton _modeFav;
    private readonly DispatcherTimer _debounce = new() { Interval = TimeSpan.FromMilliseconds(320) };
    private List<InstanceInfo> _instances = new();
    private HashSet<string> _favKeys = new();
    private bool _sync;
    private Mode _mode;
    private readonly bool _installedFirst;
    private int _searchToken;

    /// <summary>
    /// 在线搜索的超时（毫秒）。到点就掐掉请求、显示错误态与「重试」，页面不会一直挂着骨架等网络。
    /// 冒烟用 --smoke-search-timeout 把它压到 1ms 做负向对照（证明超时路径是活的）。
    /// </summary>
    public static int SearchTimeoutMs = 9000;

    private CancellationTokenSource? _searchCts;
    /// <summary>最新那次在线搜索还没收场（结果没落地、也没进错误态）。</summary>
    private bool _searchInFlight;
    /// <summary>上一次搜索是被切页掐掉的（不是超时、不是被新搜索顶掉）：回到这一页时要补一次。</summary>
    private bool _searchInterrupted;

    /// <param name="installedFirst">true = 当「模组管理」页用：打开先看已安装，标题叫「模组」（对齐 Qt 的 mods 子页）。</param>
    public CatalogPage(CatalogKind kind, bool installedFirst = false)
    {
        _kind = kind;
        _installedFirst = installedFirst && kind.InstalledMethod.Length > 0;
        _mode = _installedFirst ? Mode.Installed : Mode.Search;
        _search.Tag = L("搜索{0}，留空看热门", kind.Title);

        var sources = new[] { L("全部"), "Modrinth", "CurseForge" };
        _source = Ui.Combo(sources, sources.Contains(kind.DefaultSource) ? kind.DefaultSource : L("全部"), 116);
        // 分类名是后端的映射键（中文），下拉里显示译文，发请求时再换回键（见 CategoryParam）
        _type = Ui.Combo(kind.Types.Select(t => L(t)), L("全部"), 116);

        _modeSearch = new ToggleButton { Content = L("搜索下载"), Style = Ui.S("TabItemBtn"), IsChecked = !_installedFirst };
        _modeInstalled = new ToggleButton { Content = L("已安装"), Style = Ui.S("TabItemBtn"), IsChecked = _installedFirst };
        _modeFav = new ToggleButton { Content = L("收藏"), Style = Ui.S("TabItemBtn") };
        _modeSearch.Click += (_, _) => SetMode(Mode.Search);
        _modeInstalled.Click += (_, _) => SetMode(Mode.Installed);
        _modeFav.Click += (_, _) => SetMode(Mode.Favorites);

        var searchBtn = Ui.Btn(L("搜索"), BtnKind.Primary, (_, _) => Run(SearchAsync, L("搜索失败")), Ico.Search);
        var resetBtn = Ui.Btn(L("重置条件"), BtnKind.Chip, (_, _) => ResetFilters(), Ico.Refresh);
        var updateBtn = Ui.Btn(L("检查更新"), BtnKind.Chip,
            (_, _) => Run(async () =>
            {
                await ModsDialog.CheckUpdatesAsync(CurrentInstance());
                if (_mode == Mode.Installed) await LoadInstalledAsync();
            }, L("检查更新失败")), Ico.Refresh);
        updateBtn.Visibility = _kind.Key == "mod" ? Visibility.Visible : Visibility.Collapsed;
        var exportAllBtn = Ui.Btn(L("全部导出"), BtnKind.Chip,
            (_, _) => Run(() => ExportAllInstalledAsync(_installedNames), L("导出失败")), Ico.Export);
        exportAllBtn.Visibility = ExportKind().Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        _installedVer.SelectionChanged += (_, _) => { if (!_sync && _mode == Mode.Installed) Run(LoadInstalledAsync); };
        var linkBtn = Ui.Btn(L("链接安装"), BtnKind.Chip, null, Ico.Link);
        linkBtn.Click += (_, _) => Run(() => InstallFromLinkAsync(linkBtn), L("链接安装失败"));
        var localBtn = Ui.Btn(L("导入本地文件"), BtnKind.Chip, null, Ico.Import);
        localBtn.Click += (_, _) => ImportLocal(localBtn);
        var refresh = Ui.IconBtn(Ico.Refresh, L("刷新"), (_, _) => Run(ReloadCurrentAsync));

        // 打字即搜，320ms 去抖：逐字符发请求会把后端和上游 API 都刷爆。
        _debounce.Tick += (_, _) =>
        {
            _debounce.Stop();
            if (_mode == Mode.Search) Run(SearchAsync, L("搜索失败"));
        };
        _search.TextChanged += (_, _) =>
        {
            if (_sync || _mode != Mode.Search) return;
            _debounce.Stop();
            _debounce.Start();
        };
        _search.KeyDown += (_, e) =>
        {
            if (e.Key != Key.Enter) return;
            _debounce.Stop();
            Run(SearchAsync, L("搜索失败"));
        };
        _source.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, L("搜索失败")); };
        _type.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, L("搜索失败")); };
        _version.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, L("搜索失败")); };
        _inst.SelectionChanged += (_, _) =>
        {
            if (_sync) return;
            if (Win != null)
            {
                Win.Prefs.CatalogInstance = CurrentInstance();
                Win.SaveUiPrefs();
            }
            Run(ReloadCurrentAsync);
        };

        var searchRow = Ui.G(null, "*,Auto");
        searchRow.Add(_search, 0, 0);
        searchRow.Add(searchBtn.M(8, 0, 0, 0), 0, 1);

        var filters = new WrapPanel();
        void Labeled(string label, FrameworkElement ctl)
        {
            filters.Children.Add(Ui.H(6, Ui.Txt(label, 12, fg: "B.InkMuted").VCenter(), ctl.VCenter())
                .M(0, 0, 14, 8));
        }
        Labeled(L("来源"), _source);
        Labeled(L("类型"), _type);
        Labeled(L("游戏版本"), _version);
        Labeled(L("实例"), _inst);
        if (_kind.InstalledMethod.Length > 0) Labeled(L("已装于版本"), _installedVer);
        filters.Children.Add(Ui.H(7, resetBtn, linkBtn, localBtn, updateBtn, exportAllBtn, refresh).M(0, 0, 0, 8));

        var toolbar = Ui.Card(Ui.V(10, searchRow, filters), 14);

        var modes = Ui.H(6, _modeSearch,
            _kind.InstalledMethod.Length > 0 ? _modeInstalled : null,
            _modeFav);
        var head = Ui.Section(Title, SubTitle(), modes);

        // 结果列表独占一块有限高度的区域，虚拟化才会生效（外层不能再套 ScrollViewer）。
        _results = Ui.VirtualList<object>(BuildRow);
        _listHost.Children.Add(_results);
        _listHost.Children.Add(Ui.Scroll(_placeholder));

        var root = Ui.G("Auto,Auto,*");
        root.Add(head, 0, 0);
        root.Add(toolbar.M(0, 14, 0, 14), 1, 0);
        root.Add(_listHost, 2, 0);
        root.Margin = new Thickness(26, 20, 26, 20);
        Content = root;

        // 落在这一页的文件用这一页选中的实例；类型认不准时，这一页主营什么就当什么
        EnableDrop(() => new FileDrop.DropContext
        {
            Instance = CurrentInstance(),
            PreferKind = PreferredKind(),
        });
    }

    /// <summary>本页主营的文件类型。与 FileKinds 的常量对齐，对不上的（世界）留空不干预。</summary>
    private string PreferredKind() => _kind.Key switch
    {
        "mod" => FileKinds.Mod,
        "modpack" => FileKinds.Modpack,
        "datapack" => FileKinds.DataPack,
        "resourcepack" => FileKinds.ResourcePack,
        "shader" => FileKinds.ShaderPack,
        "world" => FileKinds.World,
        _ => "",
    };

    private string SubTitle() => _installedFirst ? L("管理所选实例里已装的模组；要装新的切到「搜索下载」") : _kind.Key switch
    {
        "mod" => L("从 Modrinth / CurseForge 搜模组，装进所选实例"),
        "modpack" => L("一键安装整合包到独立实例"),
        "datapack" => L("数据包会放进实例 datapacks 目录"),
        "resourcepack" => L("资源包会放进实例 resourcepacks 目录"),
        "shader" => L("光影包会放进实例 shaderpacks 目录"),
        _ => L("世界地图会解压成实例存档"),
    };

    private string Glyph() => _kind.Key switch
    {
        "mod" => Ico.Puzzle,
        "modpack" => Ico.Package,
        "datapack" => Ico.Data,
        "resourcepack" => Ico.Image,
        "shader" => Ico.Sun,
        _ => Ico.World,
    };

    private string CurrentInstance() => _inst.Str();

    /// <summary>已安装模式看哪个版本的目录。空 = 实例共享那一份。</summary>
    private string InstalledVersion()
    {
        var i = _installedVer.SelectedIndex;
        return i >= 0 && i < _installedVerValues.Count ? _installedVerValues[i] : "";
    }

    /// <summary>把筛选条件退回出厂值并重搜一遍，对齐 Qt 的「重置条件」。</summary>
    private void ResetFilters()
    {
        _sync = true;
        _search.Clear();
        _source.SelectedItem = _source.Items.Contains(_kind.DefaultSource) ? _kind.DefaultSource : L("全部");
        _type.SelectedIndex = 0;
        _version.Text = L("全部");
        _version.SelectedIndex = 0;
        _sync = false;
        Run(ReloadCurrentAsync);
    }

    /// <summary>用户输入的版本号（可编辑下拉）。「全部」与空串都当不限。</summary>
    private string GameVersionFilter()
    {
        var text = (_version.Text ?? "").Trim();
        if (text.Length == 0 || text == L("全部")) return "";
        return text;
    }

    /// <summary>来源下拉：「全部」发给桥要用它认识的 all，其余原样（Modrinth / CurseForge）。</summary>
    private string SourceParam()
    {
        var s = _source.Str();
        return s == L("全部") ? "all" : s;
    }

    /// <summary>分类下拉：显示的是译文，桥要的是中文键；首项永远是「全部」= 不限。</summary>
    private string CategoryParam()
    {
        if (_type.SelectedIndex <= 0) return "";
        var shown = _type.Str();
        return _kind.Types.FirstOrDefault(t => L(t) == shown) ?? shown;
    }

    // ==================== 列表宿主 ====================
    /// <summary>只有一条空状态 / 骨架时走占位层，真有数据时才让虚拟化列表出来。</summary>
    private void ShowPlaceholder(params UIElement[] kids)
    {
        _results.ItemsSource = null;
        _placeholder.Children.Clear();
        foreach (var k in kids) _placeholder.Children.Add(k);
        _placeholder.Visibility = Visibility.Visible;
        _listHost.Children[1].Visibility = Visibility.Visible;
        _results.Visibility = Visibility.Collapsed;
    }

    private void ShowRows(System.Collections.IEnumerable rows)
    {
        _placeholder.Children.Clear();
        _listHost.Children[1].Visibility = Visibility.Collapsed;
        _results.Visibility = Visibility.Visible;
        _results.ItemsSource = rows;
        // 换了一批结果就回到顶部，否则容器复用会把滚动位置留在上一次的深处。
        if (_results.Items.Count > 0) _results.ScrollIntoView(_results.Items[0]);
    }

    private UIElement BuildRow(object item) => item switch
    {
        CatalogItem c => ResultCard(c),
        ModEntry m => ModRow(m),
        string s => InstalledRow(s),
        _ => Ui.Txt(item?.ToString() ?? ""),
    };

    // ==================== 加载 ====================
    /// <summary>
    /// 首载只等本地这两样（实例表、收藏键），到这里页面就算「加载完」；在线搜索另起一条带取消与超时的异步，
    /// 列表位置先摆骨架——照 Qt 的 _search：call_async 丢给工作线程，界面不等它。
    /// 以前是同步等在线搜索返回，首载时长随网络抖到十几秒，冒烟按 9 秒预算就把这三页判成超时。
    /// </summary>
    protected override async Task LoadAsync()
    {
        _instances = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _sync = true;
        _inst.Fill(_instances.Select(i => i.Name), Win?.Prefs.CatalogInstance);
        _sync = false;
        await ReloadFavoritesAsync();
        Run(ReloadCurrentAsync, L("搜索失败"));
    }

    /// <summary>
    /// 开一轮新搜索用的令牌：上一轮还在飞就掐掉（重搜、换筛选、换模式都走这里），这一轮挂上 SearchTimeoutMs 的超时。
    /// 令牌一取消，桥那边的 HTTP 请求随即中断，不再等结果。
    /// </summary>
    private CancellationToken NextSearchToken()
    {
        CancelSearch();
        _searchCts = new CancellationTokenSource(SearchTimeoutMs);
        _searchInterrupted = false;
        return _searchCts.Token;
    }

    /// <summary>掐掉在飞的搜索（如果有）。</summary>
    private void CancelSearch()
    {
        _searchInFlight = false;
        var cts = _searchCts;
        _searchCts = null;
        if (cts is null) return;
        try { cts.Cancel(); } catch (ObjectDisposedException) { }
        cts.Dispose();
    }

    /// <summary>错误态：说清原因，给一个「重试」。Qt 只有一行「搜索失败: …」的空态，这里多一个能点的按钮。</summary>
    private void ShowFailure(string title, string detail)
    {
        var retry = Ui.Btn(L("重试"), BtnKind.Soft, (_, _) => Run(ReloadCurrentAsync, L("搜索失败")), Ico.Refresh);
        retry.HorizontalAlignment = HorizontalAlignment.Center;
        retry.Margin = new Thickness(0, -30, 0, 0);
        ShowPlaceholder(Ui.Empty(Ico.Warning, title, detail), retry);
    }

    private Task ReloadCurrentAsync() => _mode switch
    {
        Mode.Installed => LoadInstalledAsync(),
        Mode.Favorites => LoadFavoritesAsync(),
        _ => SearchAsync(),
    };

    private void SetMode(Mode mode)
    {
        if (mode == Mode.Installed && _kind.InstalledMethod.Length == 0) mode = Mode.Search;
        _mode = mode;
        _modeSearch.IsChecked = mode == Mode.Search;
        _modeInstalled.IsChecked = mode == Mode.Installed;
        _modeFav.IsChecked = mode == Mode.Favorites;
        Run(ReloadCurrentAsync);
    }

    // ==================== 收藏 ====================
    private async Task ReloadFavoritesAsync()
    {
        var rows = await Api.TryCallAsync<List<CatalogItem>>("catalog_favorites", null, new()) ?? new();
        _favKeys = rows.Select(FavKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>与后端 toggle_favorite 认的键一致：来源 + slug/id/name。</summary>
    private static string FavKey(CatalogItem item) =>
        $"{item.Source}|{item.Slug ?? item.IdValue?.ToString() ?? item.Name}";

    private async Task ToggleFavAsync(CatalogItem item, ToggleButton star)
    {
        var rows = await Api.CallAsync<List<CatalogItem>>("toggle_favorite", new
        {
            item = new { name = item.Name, source = item.Source, slug = item.Slug, id = item.IdValue },
        }) ?? new();
        _favKeys = rows.Select(FavKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var on = _favKeys.Contains(FavKey(item));
        star.IsChecked = on;
        star.Content = Ui.Glyph(on ? Ico.StarFill : Ico.Star, 13, on ? "B.Accent" : "B.InkMuted");
        Toast(on ? L("已收藏") : L("已取消收藏"), item.Name);
        if (_mode == Mode.Favorites) await LoadFavoritesAsync();
    }

    private async Task LoadFavoritesAsync()
    {
        var token = ++_searchToken;
        CancelSearch(); // 切到收藏就别再等那次在线搜索了
        ShowPlaceholder(Ui.Skeleton(56));
        var rows = await Api.TryCallAsync<List<CatalogItem>>("catalog_favorites", null, new()) ?? new();
        if (token != _searchToken) return;
        _favKeys = rows.Select(FavKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (rows.Count == 0)
        {
            ShowPlaceholder(Ui.Empty(Ico.Star, L("还没有收藏"), L("在搜索结果里点右边的星星就能收藏")));
            return;
        }
        ShowRows(rows);
    }

    // ==================== 搜索 ====================
    /// <summary>
    /// 在线搜索。三种收场：结果落地 / 超时或出错 → 错误态 + 重试 / 被掐掉 → 什么都不画。
    /// 「被掐掉」又分两种：被更新的一次搜索顶掉（token 变了，那一次自己会画）、切页打断（骨架留着，回来补）。
    /// </summary>
    private async Task SearchAsync()
    {
        var token = ++_searchToken;
        var ct = NextSearchToken();
        ShowPlaceholder(Ui.Skeleton(64), Ui.Skeleton(64), Ui.Skeleton(64));
        var query = _search.Text?.Trim() ?? "";
        _searchInFlight = true;
        try
        {
            var rows = await Api.CallAsync<List<CatalogItem>>(_kind.SearchMethod, new
            {
                query,
                source = SourceParam(),
                extra = new
                {
                    game_version = GameVersionFilter(),
                    category = CategoryParam(),
                },
            }, ct) ?? new();
            if (token != _searchToken) return;
            if (rows.Count == 0)
            {
                ShowPlaceholder(Ui.Empty(Glyph(), _kind.Empty, L("换个关键词，或切换来源 / 游戏版本试试")));
                return;
            }
            ShowRows(rows);
        }
        catch (OperationCanceledException)
        {
            if (token != _searchToken || _searchInterrupted) return;
            ShowFailure(L("搜索超时"), L("{0} 秒内没等到结果。检查网络或换个来源再试。", Math.Max(1, (SearchTimeoutMs + 999) / 1000)));
        }
        catch (Exception ex)
        {
            if (token != _searchToken) return;
            ShowFailure(L("搜索失败"), ex.Message);
        }
        finally
        {
            // 只有最新那一次有资格说「搜索收场了」；被顶掉的旧搜索不能把新搜索的在飞标记清掉
            if (token == _searchToken) _searchInFlight = false;
        }
    }

    private UIElement ResultCard(CatalogItem item)
    {
        var thumb = new ThumbTile(item.Name, 46);
        thumb.SetUrl(item.IconUrl);
        thumb.VerticalAlignment = VerticalAlignment.Center;

        var meta = Ui.H(7,
            Ui.Muted(string.IsNullOrEmpty(item.Author) ? L("佚名") : item.Author).VCenter(),
            Ui.Muted("·").VCenter(),
            Ui.Muted(Fmt.Downloads(item.Downloads) + L(" 次下载")).VCenter(),
            string.IsNullOrEmpty(item.Source) ? null : Ui.Tag(item.Source, "B.AccentDeep", "B.AccentSoft"));

        var texts = Ui.V(3, Ui.Txt(item.Name, 13.5, true).Trim(), meta);
        if (!string.IsNullOrWhiteSpace(item.Description))
            texts.Children.Add(Ui.Muted(item.Description).Trim());
        if (item.Tags is { Count: > 0 })
        {
            var tags = Ui.H(5);
            foreach (var t in item.Tags.Take(5)) tags.Children.Add(Ui.Tag(t));
            texts.Children.Add(tags);
        }

        var fav = _favKeys.Contains(FavKey(item));
        var star = new ToggleButton
        {
            Style = Ui.S("Btn.Icon"),
            IsChecked = fav,
            ToolTip = L("收藏"),
            Content = Ui.Glyph(fav ? Ico.StarFill : Ico.Star, 13, fav ? "B.Accent" : "B.InkMuted"),
        };
        star.Click += (s, _) => Run(() => ToggleFavAsync(item, (ToggleButton)s), L("收藏失败"));

        var install = Ui.Btn(L("安装"), BtnKind.Soft, null, Ico.Download);
        install.Click += (_, _) => Run(() => InstallAsync(item, install), L("安装失败"));

        var g = Ui.G(null, "Auto,*,Auto,Auto");
        g.Add(thumb.M(0, 0, 12, 0), 0, 0);
        g.Add(texts.VCenter(), 0, 1);
        g.Add(star.VCenter().M(8, 0, 0, 0), 0, 2);
        g.Add(install.VCenter().M(8, 0, 0, 0), 0, 3);
        var card = Ui.RowCard(g, padding: 13);
        Motion.HoverLift(card, 1.004, 1, 16);
        return card;
    }

    // ==================== 安装 ====================
    private Dictionary<string, object?> BaseExtra(string name) => new()
    {
        ["name"] = name,
        ["source"] = SourceParam(),
        ["instance"] = CurrentInstance(),
        ["version"] = InstalledVersion(),
        ["game_version"] = GameVersionFilter(),
        ["kind"] = _kind.FileKind,
    };

    private async Task InstallAsync(CatalogItem item, FrameworkElement anchor)
    {
        var extra = BaseExtra(item.Name);
        extra["source"] = string.IsNullOrEmpty(item.Source) ? SourceParam() : item.Source;
        extra["slug"] = item.Slug;
        extra["id"] = item.IdValue;

        if (item.Slug is { Length: > 0 } || item.IdValue != null)
        {
            var picked = await PickVersionFileAsync(item, extra);
            if (picked is null) return;
            extra = picked;
        }
        if (_kind.Key == "datapack") extra = await PickSaveAsync(extra);
        else if (_kind.Key == "world")
        {
            // 世界装进哪个版本的 saves：开了存档隔离的版本各有一份
            var target = await SavesDialog.PickSaveTargetAsync(CurrentInstance(), L("装进哪里 · {0}", item.Name));
            if (target is null) return;
            extra["version"] = target;
        }
        await DoInstallAsync(extra, anchor);
    }

    /// <summary>数据包可以顺手装进某个存档；不选就只落到 datapacks 目录。</summary>
    private async Task<Dictionary<string, object?>> PickSaveAsync(Dictionary<string, object?> extra)
    {
        var inst = CurrentInstance();
        if (string.IsNullOrEmpty(inst)) return extra;
        var saves = await Api.TryCallAsync<List<SaveRow>>("list_saves", new { instance = inst, version = "" }, new()) ?? new();
        if (saves.Count == 0) return extra;
        var pick = Ui.Combo(new[] { L("不装进存档") }.Concat(saves.Select(s => s.Name)));
        if (!await Dlg.Ask(L("装进存档"),
                Ui.V(8, Ui.Muted(L("可选：把数据包直接装进某个世界，或只放到 datapacks 文件夹。")), pick), L("继续"))) return extra;
        if (pick.SelectedIndex <= 0) return extra;
        var next = new Dictionary<string, object?>(extra) { ["save"] = pick.Str() };
        return next;
    }

    /// <summary>弹出版本文件选择。返回 null = 取消；返回 extra = 安装最新或所选文件。</summary>
    private async Task<Dictionary<string, object?>?> PickVersionFileAsync(CatalogItem item, Dictionary<string, object?> extra)
    {
        List<CatalogFile> files;
        using (Dlg.Busy(L("正在获取版本文件…")))
            files = await Api.TryCallAsync<List<CatalogFile>>("list_catalog_files", new { extra }, new()) ?? new();

        if (files.Count == 0)
            return await Dlg.Confirm(L("没有找到版本文件"), L("在线列表为空，要直接尝试安装最新版吗？"), L("安装最新"), L("取消"))
                ? extra
                : null;

        var chosen = files[0];
        var listHost = Ui.V(6);
        var scroll = Ui.Scroll(listHost);
        scroll.MaxHeight = 340;
        scroll.MinWidth = 560;

        var gvs = new List<string> { L("全部") };
        var loaders = new List<string> { L("全部") };
        foreach (var f in files)
        {
            foreach (var v in f.GameVersions ?? new()) if (!gvs.Contains(v)) gvs.Add(v);
            foreach (var l in f.Loaders ?? new()) if (!loaders.Contains(l)) loaders.Add(l);
        }
        var gvBox = Ui.Combo(gvs, L("全部"), 130);
        var loaderBox = Ui.Combo(loaders, L("全部"), 130);
        var count = Ui.Muted("");

        void Refill()
        {
            var gv = gvBox.Str();
            var ld = loaderBox.Str();
            var anyGv = gvBox.SelectedIndex <= 0;
            var anyLd = loaderBox.SelectedIndex <= 0;
            var matched = files.Where(f =>
            {
                if (!anyGv && f.GameVersions is { Count: > 0 } && !f.GameVersions.Contains(gv)) return false;
                if (!anyLd && f.Loaders is { Count: > 0 } &&
                    !f.Loaders.Any(l => string.Equals(l, ld, StringComparison.OrdinalIgnoreCase))) return false;
                return true;
            }).ToList();
            if (matched.Count > 0 && !matched.Contains(chosen)) chosen = matched[0];
            listHost.Children.Clear();
            foreach (var f in matched.Take(80)) listHost.Children.Add(FileRow(f));
            count.Text = L("{0} 个匹配 / 共 {1} 个文件", matched.Count, files.Count);
            MarkSelected();
        }

        void MarkSelected()
        {
            foreach (var row in listHost.Children.OfType<Border>())
            {
                var on = ReferenceEquals(row.Tag, chosen);
                row.SetResourceReference(Border.BorderBrushProperty, on ? "B.Accent" : "B.Line");
                row.SetResourceReference(Border.BackgroundProperty, on ? "B.AccentSoft" : "B.Paper");
            }
        }

        Border FileRow(CatalogFile f)
        {
            var title = Ui.Txt(string.IsNullOrEmpty(f.VersionNumber) ? f.Name : f.VersionNumber, 12.5, true).Trim();
            var meta = Ui.Small(
                $"{string.Join(", ", (f.GameVersions ?? new()).Take(4))} · {string.Join(", ", f.Loaders ?? new())}" +
                $" · {f.Date} · {Fmt.Downloads(f.Downloads)} · {(string.IsNullOrEmpty(f.ReleaseType) ? "release" : f.ReleaseType)}");
            var row = Ui.RowCard(Ui.V(2, title, meta.Wrap()), padding: 9);
            row.Tag = f;
            row.MouseLeftButtonUp += (_, _) =>
            {
                chosen = f;
                MarkSelected();
            };
            return row;
        }

        gvBox.SelectionChanged += (_, _) => Refill();
        loaderBox.SelectionChanged += (_, _) => Refill();
        Refill();

        var filters = Ui.H(8,
            Ui.Txt(L("游戏版本"), 12, fg: "B.InkMuted").VCenter(), gvBox.VCenter(),
            Ui.Txt(L("加载器"), 12, fg: "B.InkMuted").VCenter(), loaderBox.VCenter(),
            count.VCenter());
        var idx = await Dlg.Choose(L("选择版本文件 · {0}", item.Name),
            Ui.V(10, filters, scroll), new[] { L("取消"), L("安装最新"), L("安装所选") }, 660);
        if (idx == 1) return extra;
        if (idx != 2 || chosen is null) return null;

        var next = new Dictionary<string, object?>(extra)
        {
            ["version_id"] = chosen.IdValue,
            ["filename"] = chosen.Filename,
        };
        var src = (item.Source ?? "").ToLowerInvariant();
        if (src.StartsWith("curse") || chosen.Source == "curseforge") next["file_id"] = chosen.IdValue;
        return next;
    }

    private async Task<string> DoInstallAsync(Dictionary<string, object?> extra, FrameworkElement? anchor)
    {
        var name = extra.TryGetValue("name", out var n) ? n?.ToString() ?? _kind.Title : _kind.Title;
        string taskId;
        if (_kind.IsModpack)
        {
            taskId = await Api.StartTaskAsync(_kind.InstallMethod, new
            {
                name,
                source = extra.TryGetValue("source", out var s) && s?.ToString() is { Length: > 0 } src ? src : "Modrinth",
                extra,
            });
        }
        else
        {
            taskId = await Api.StartTaskAsync(_kind.InstallMethod, new
            {
                name,
                instance = CurrentInstance(),
                extra,
            });
        }
        if (anchor != null && SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, name);
        return taskId;
    }

    private async Task InstallFromLinkAsync(FrameworkElement anchor)
    {
        var url = await Dlg.Prompt(_kind.Title + L(" · 链接安装"), _kind.LinkHint, "", "https://…");
        if (string.IsNullOrWhiteSpace(url)) return;
        var extra = BaseExtra(url.Trim());
        extra["url"] = url.Trim();
        await DoInstallAsync(extra, anchor);
        Win?.Navigate("tasks");
    }

    private void ImportLocal(FrameworkElement anchor)
    {
        // 统一走 Dlg：生产路径行为不变；无人值守冒烟可在一个入口安全地代按「取消」，
        // 不会留下一个 Win32 文件选择器把整轮卡到看门狗。
        var files = Dlg.PickFiles(_kind.LocalFilter, L("导入本地") + _kind.Title);
        if (files is null || files.Length == 0) return;
        Run(async () =>
        {
            if (SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, L("{0} 个文件", files.Length));
            Win?.Navigate("tasks");
            foreach (var f in files)
            {
                var extra = BaseExtra(System.IO.Path.GetFileName(f));
                extra["path"] = f;
                extra["source"] = "本地"; // i18n:ignore 桥的协议值（原文比对），不是界面词
                var taskId = await DoInstallAsync(extra, null);
                // 一个一个来：多个安装任务同时往同一个 mods 目录里写，解压和改名会互相踩。
                if (!string.IsNullOrEmpty(taskId))
                    await Api.TryCallAsync<OpResult>("wait_task", new { task_id = taskId, timeout = 1800 });
            }
            if (_mode != Mode.Search) await ReloadCurrentAsync();
        }, L("导入失败"));
    }

    // ==================== 已安装 ====================
    private async Task LoadInstalledAsync()
    {
        var token = ++_searchToken;
        CancelSearch(); // 切到已安装就别再等那次在线搜索了
        ShowPlaceholder(Ui.Skeleton(46));
        var inst = CurrentInstance();
        if (string.IsNullOrEmpty(inst))
        {
            ShowPlaceholder(Ui.Empty(Glyph(), L("还没有实例"), L("先到「实例」页新建一个")));
            return;
        }
        await FillInstalledVersionsAsync(inst);
        var ver = InstalledVersion();
        try
        {
            if (_kind.Key == "mod")
            {
                var entries = await Api.TryCallAsync<List<ModEntry>>("get_installed_mod_entries",
                    new { instance = inst, version = ver }, new()) ?? new();
                if (token != _searchToken) return;
                if (entries.Count == 0)
                {
                    ShowPlaceholder(Ui.Empty(Glyph(), L("这个实例还没有 Mod"), L("切回「搜索下载」装一个")));
                    return;
                }
                ShowRows(entries);
                return;
            }
            var names = await Api.TryCallAsync<List<string>>(_kind.InstalledMethod,
                new { instance = inst }, new()) ?? new();
            if (token != _searchToken) return;
            if (names.Count == 0)
            {
                ShowPlaceholder(Ui.Empty(Glyph(), L("这个实例还没有{0}", _kind.Title), L("切回「搜索下载」装一个")));
                return;
            }
            _installedNames = names;
            ShowRows(names);
        }
        catch (Exception ex)
        {
            if (token != _searchToken) return;
            ShowPlaceholder(Ui.Empty(Ico.Warning, L("读取失败"), ex.Message));
        }
    }

    /// <summary>「已装于版本」下拉：实例共享那一份，加上开了 mods 隔离的各版本。</summary>
    private async Task FillInstalledVersionsAsync(string instance)
    {
        var targets = await Api.TryCallAsync<List<ModsTarget>>("get_mods_targets", new { instance }, new()) ?? new();
        if (targets.Count == 0) targets.Add(new ModsTarget { Label = L("实例共享目录"), Value = "" });
        var keep = _installedVer.SelectedIndex;
        _sync = true;
        _installedVer.Items.Clear();
        foreach (var t in targets) _installedVer.Items.Add(t.Label);
        _installedVer.SelectedIndex = keep >= 0 && keep < targets.Count ? keep : 0;
        _installedVerValues = targets.Select(t => t.Value).ToList();
        _sync = false;
    }

    private List<string> _installedVerValues = new();
    private List<string> _installedNames = new();

    private UIElement ModRow(ModEntry m)
    {
        var inst = CurrentInstance();
        var ver = InstalledVersion();
        var file = m.Filename;
        var sw = Ui.Switch(m.Enabled);
        sw.Checked += (_, _) => Run(() => Api.TryCallAsync<object>("enable_mod", new { instance = inst, filename = file, version = ver }));
        sw.Unchecked += (_, _) => Run(() => Api.TryCallAsync<object>("disable_mod", new { instance = inst, filename = file, version = ver }));
        var del = Ui.Btn(L("删除"), BtnKind.Ghost, (_, _) => Run(() => DeleteInstalledAsync(file), L("删除失败")));
        var g = Ui.G(null, "Auto,*,Auto,Auto");
        g.Add(sw.M(0, 0, 10, 0).VCenter(), 0, 0);
        g.Add(Ui.V(1,
            Ui.Txt(string.IsNullOrWhiteSpace(m.Name) ? file : m.Name, 13).Trim(),
            Ui.Small(string.Join(" · ", new[] { file, m.Version, m.Size }.Where(x => !string.IsNullOrEmpty(x))))).VCenter(), 0, 1);
        g.Add(Ui.Small(m.Enabled ? "" : L("已禁用")).VCenter().M(8, 0, 0, 0), 0, 2);
        g.Add(del.VCenter().M(8, 0, 0, 0), 0, 3);
        return Ui.RowCard(g, padding: 10);
    }

    private UIElement InstalledRow(string file)
    {
        var del = Ui.Btn(_kind.IsModpack ? L("移除标记") : L("删除"), BtnKind.Ghost,
            (_, _) => Run(() => DeleteInstalledAsync(file), L("删除失败")));
        var g = Ui.G(null, "*,Auto,Auto");
        g.Add(Ui.Txt(file, 12.5).Trim().VCenter(), 0, 0);
        var kind = ExportKind();
        if (kind.Length > 0)
            g.Add(Ui.Btn(L("导出"), BtnKind.Chip, (_, _) => Run(() => ExportInstalledAsync(file), L("导出失败")), Ico.Export)
                .VCenter().M(0, 0, 6, 0), 0, 1);
        g.Add(del.VCenter(), 0, 2);
        return Ui.RowCard(g, padding: 10);
    }

    /// <summary>本页的内容在 content_export 里叫什么。整合包没法单文件导出。</summary>
    private string ExportKind() => _kind.Key switch
    {
        "mod" => "mod",
        "shader" => "shader",
        "resourcepack" => "resourcepack",
        "datapack" => "datapack",
        "world" => "world",
        _ => "",
    };

    /// <summary>
    /// 把已装的这一项导出去。导出目录记在后端（remember_export_dir），
    /// 下次默认落在同一个地方——别让用户每次都重新翻一遍文件夹。
    /// </summary>
    private async Task ExportInstalledAsync(string name)
    {
        var kind = ExportKind();
        if (kind.Length == 0) return;
        var start = await Api.TryCallAsync<string>("default_export_dir", null, "") ?? "";
        var folder = Dlg.PickFolder(string.IsNullOrEmpty(start) ? L("选择导出位置") : L("选择导出位置（上次：{0}）", start));
        if (folder is null) return;
        await Api.TryCallAsync<string>("remember_export_dir", new { path = folder }, folder);
        var path = await Api.CallAsync<string>("export_content", new
        {
            kind, name, dest_dir = folder, version = InstalledVersion(), instance = CurrentInstance(),
        });
        Toast(L("已导出"), path ?? folder, ToastKind.Success);
    }

    /// <summary>整页一次导出：走 export_contents，后端逐个搬并回报成败清单。</summary>
    private async Task ExportAllInstalledAsync(List<string> names)
    {
        var kind = ExportKind();
        if (kind.Length == 0 || names.Count == 0) return;
        var start = await Api.TryCallAsync<string>("default_export_dir", null, "") ?? "";
        var folder = Dlg.PickFolder(string.IsNullOrEmpty(start) ? L("选择导出位置") : L("选择导出位置（上次：{0}）", start));
        if (folder is null) return;
        await Api.TryCallAsync<string>("remember_export_dir", new { path = folder }, folder);
        ExportResult? r;
        using (Dlg.Busy(L("正在导出 {0} 个…", names.Count)))
            r = await Api.CallAsync<ExportResult>("export_contents", new
            {
                kind, names, dest_dir = folder, version = InstalledVersion(), instance = CurrentInstance(),
            });
        if (r is null) return;
        if (r.Failed.Count == 0) Toast(L("已导出"), L("{0} 个 → {1}", r.Ok.Count, folder), ToastKind.Success);
        else await Dlg.Alert(L("部分没能导出"),
            L("成功 {0} 个，失败 {1} 个：\n\n", r.Ok.Count, r.Failed.Count) + string.Join("\n", r.Failed));
    }

    /// <summary>
    /// 切到这一页时瞄一眼剪贴板：刚从 Modrinth / CurseForge 网页复制的链接直接填进搜索框，
    /// 省掉一次粘贴。同一串只认一次，对齐 Qt catalog_page.showEvent。
    /// </summary>
    private void SniffClipboard()
    {
        string clip;
        try { clip = (Clipboard.GetText() ?? "").Trim(); }
        catch { return; }
        if (clip.Length == 0 || clip == _clipSeen) return;
        var low = clip.ToLowerInvariant();
        if (!low.Contains("modrinth.com") && !low.Contains("curseforge.com")) return;
        _clipSeen = clip;
        if ((_search.Text ?? "").Trim().Length == 0) _search.Text = clip;
        Toast(L("识别到剪贴板链接"), clip.Length > 96 ? clip.Substring(0, 96) + "…" : clip);
    }

    private async Task DeleteInstalledAsync(string filename)
    {
        if (string.IsNullOrEmpty(_kind.DeleteMethod)) return;
        var inst = CurrentInstance();
        if (_kind.DeleteMethod == "delete_modpack")
        {
            // 不提供「连整个实例一起删」：单游戏目录下那等于删掉全部版本，后端会直接拒绝。
            if (!await Dlg.Confirm(L("移除整合包标记"),
                    L("只清掉「已安装整合包」这条记录，游戏目录里的模组与存档一个不动。\n要腾空间的话，到「原版游戏」里逐个卸载版本。"),
                    L("移除标记"), L("取消"))) return;
            await Api.CallAsync("delete_modpack", new { instance = inst, filename, purge_instance = false });
        }
        else
        {
            if (!await Dlg.Confirm(L("删除确认"), L("将删除「{0}」，不可恢复。", filename), L("删除"), L("取消"), true)) return;
            if (_kind.DeleteMethod == "delete_mod")
                await Api.CallAsync(_kind.DeleteMethod, new { instance = inst, filename, version = "" });
            else
                await Api.CallAsync(_kind.DeleteMethod, new { instance = inst, filename });
        }
        Toast(L("已处理"), filename, ToastKind.Success);
        await LoadInstalledAsync();
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        if (ev.Event == "finished" && ev.Success && _mode == Mode.Installed)
            Run(LoadInstalledAsync);
    }

    public override void OnShown()
    {
        SniffClipboard();
        // 切走时被掐掉的那次搜索，回来补上——骨架不能一直挂着
        if (_searchInterrupted) Run(ReloadCurrentAsync, L("搜索失败"));
    }

    /// <summary>切页就把在飞的搜索掐掉：省一次没人看的网络请求，也别让它回头改一个看不见的页面。</summary>
    public override void OnHidden()
    {
        _debounce.Stop();
        if (!_searchInFlight) return;
        _searchInterrupted = true;
        CancelSearch();
    }
}
