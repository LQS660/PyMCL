using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using Microsoft.Win32;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>Mod / 整合包 / 数据包 / 资源包 / 光影 / 世界共用的目录页，差异全在 CatalogKind 里。</summary>
public sealed class CatalogPage : PageBase
{
    public override string Title => _kind.Title;

    private static readonly string[] GameVersions =
    {
        "全部", "1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1",
        "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.7.10",
    };

    private readonly CatalogKind _kind;
    private readonly TextBox _search = Ui.Input();
    private readonly ComboBox _source;
    private readonly ComboBox _type;
    private readonly ComboBox _version = Ui.Combo(GameVersions, "全部", 120);
    private readonly ComboBox _inst = Ui.Combo(width: 150);
    private readonly SPanel _list = Ui.V(10);
    private readonly ToggleButton _modeSearch;
    private readonly ToggleButton _modeInstalled;
    private List<InstanceInfo> _instances = new();
    private bool _sync;
    private bool _installedMode;
    private int _searchToken;

    public CatalogPage(CatalogKind kind)
    {
        _kind = kind;
        _search.Tag = $"搜索{kind.Title}，留空看热门";

        var sources = new[] { "全部", "Modrinth", "CurseForge" };
        _source = Ui.Combo(sources, sources.Contains(kind.DefaultSource) ? kind.DefaultSource : "全部", 116);
        _type = Ui.Combo(kind.Types, "全部", 116);

        _modeSearch = new ToggleButton { Content = "搜索下载", Style = Ui.S("TabItemBtn"), IsChecked = true };
        _modeInstalled = new ToggleButton { Content = "已安装", Style = Ui.S("TabItemBtn") };
        _modeSearch.Click += (_, _) => SetMode(false);
        _modeInstalled.Click += (_, _) => SetMode(true);

        var searchBtn = Ui.Btn("搜索", BtnKind.Primary, (_, _) => Run(SearchAsync, "搜索失败"), Ico.Search);
        var linkBtn = Ui.Btn("链接安装", BtnKind.Chip, null, Ico.Link);
        linkBtn.Click += (_, _) => Run(() => InstallFromLinkAsync(linkBtn), "链接安装失败");
        var localBtn = Ui.Btn("导入本地文件", BtnKind.Chip, null, Ico.Import);
        localBtn.Click += (_, _) => ImportLocal(localBtn);
        var refresh = Ui.IconBtn(Ico.Refresh, "刷新", (_, _) => Run(ReloadCurrentAsync));

        _search.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) Run(SearchAsync, "搜索失败");
        };
        _source.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, "搜索失败"); };
        _type.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, "搜索失败"); };
        _version.SelectionChanged += (_, _) => { if (!_sync) Run(SearchAsync, "搜索失败"); };
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
        Labeled("来源", _source);
        Labeled("类型", _type);
        Labeled("游戏版本", _version);
        Labeled("实例", _inst);
        filters.Children.Add(Ui.H(7, linkBtn, localBtn, refresh).M(0, 0, 0, 8));

        var toolbar = Ui.Card(Ui.V(10, searchRow, filters), 14);

        UIElement? modeSwitch = _kind.InstalledMethod.Length > 0
            ? Ui.H(6, _modeSearch, _modeInstalled)
            : null;
        var head = Ui.Section(kind.Title, SubTitle(), modeSwitch);

        Content = ScrollBody(head, toolbar, _list);
    }

    private string SubTitle() => _kind.Key switch
    {
        "mod" => "从 Modrinth / CurseForge 搜模组，装进所选实例",
        "modpack" => "一键安装整合包到独立实例",
        "datapack" => "数据包会放进实例 datapacks 目录",
        "resourcepack" => "资源包会放进实例 resourcepacks 目录",
        "shader" => "光影包会放进实例 shaderpacks 目录",
        _ => "世界地图会解压成实例存档",
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

    // ==================== 加载 ====================
    protected override async Task LoadAsync()
    {
        _instances = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _sync = true;
        _inst.Fill(_instances.Select(i => i.Name), Win?.Prefs.CatalogInstance);
        _sync = false;
        await ReloadCurrentAsync();
    }

    private Task ReloadCurrentAsync() => _installedMode ? LoadInstalledAsync() : SearchAsync();

    private void SetMode(bool installed)
    {
        if (_kind.InstalledMethod.Length == 0) installed = false;
        _installedMode = installed;
        _modeSearch.IsChecked = !installed;
        _modeInstalled.IsChecked = installed;
        Run(ReloadCurrentAsync);
    }

    // ==================== 搜索 ====================
    private async Task SearchAsync()
    {
        var token = ++_searchToken;
        _list.Children.Clear();
        _list.Children.Add(Ui.Skeleton(64));
        _list.Children.Add(Ui.Skeleton(64));
        _list.Children.Add(Ui.Skeleton(64));
        var query = _search.Text?.Trim() ?? "";
        var gv = _version.Str();
        var cat = _type.Str();
        try
        {
            var rows = await Api.CallAsync<List<CatalogItem>>(_kind.SearchMethod, new
            {
                query,
                source = _source.Str(),
                extra = new
                {
                    game_version = gv.StartsWith("全部") ? "" : gv,
                    category = cat.StartsWith("全部") ? "" : cat,
                },
            }) ?? new();
            if (token != _searchToken) return;
            RenderResults(rows, query.Length == 0);
        }
        catch (Exception ex)
        {
            if (token != _searchToken) return;
            _list.Children.Clear();
            _list.Children.Add(Ui.Empty(Ico.Warning, "搜索失败", ex.Message));
        }
    }

    private void RenderResults(List<CatalogItem> rows, bool popular)
    {
        _list.Children.Clear();
        if (popular && rows.Count > 0)
            _list.Children.Add(Ui.Txt("热门推荐", 13, true).M(2, 0, 0, 0));
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Glyph(), _kind.Empty, "换个关键词，或切换来源 / 游戏版本试试"));
            return;
        }
        foreach (var item in rows) _list.Children.Add(ResultCard(item));
        Motion.Stagger(_list, 22, 200, 10);
    }

    private UIElement ResultCard(CatalogItem item)
    {
        var letter = new Border
        {
            Width = 42,
            Height = 42,
            CornerRadius = new CornerRadius(10),
            Child = Ui.Txt(string.IsNullOrEmpty(item.Name) ? "?" : item.Name[..1].ToUpper(), 17, true, "B.AccentDeep").Center(),
        };
        letter.SetResourceReference(Border.BackgroundProperty, "B.AccentSoft");
        letter.VCenter();

        var meta = Ui.H(7,
            Ui.Muted(string.IsNullOrEmpty(item.Author) ? "佚名" : item.Author).VCenter(),
            Ui.Muted("·").VCenter(),
            Ui.Muted(Fmt.Downloads(item.Downloads) + " 次下载").VCenter(),
            string.IsNullOrEmpty(item.Source) ? null : Ui.Tag(item.Source, "B.AccentDeep", "B.AccentSoft"));

        var texts = Ui.V(3, Ui.Txt(item.Name, 13.5, true).Trim(), meta);
        if (!string.IsNullOrWhiteSpace(item.Description))
            texts.Children.Add(Ui.Muted(item.Description).Wrap());
        if (item.Tags is { Count: > 0 })
        {
            var tags = Ui.H(5);
            foreach (var t in item.Tags.Take(5)) tags.Children.Add(Ui.Tag(t));
            texts.Children.Add(tags);
        }

        var install = Ui.Btn("安装", BtnKind.Soft, null, Ico.Download);
        install.VCenter();
        install.Click += (_, _) => Run(() => InstallAsync(item, install), "安装失败");

        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(letter.M(0, 0, 12, 0), 0, 0);
        g.Add(texts.VCenter(), 0, 1);
        g.Add(install.M(12, 0, 0, 0), 0, 2);
        var card = Ui.RowCard(g, padding: 13);
        Motion.HoverLift(card, 1.004, 1, 16);
        return card;
    }

    // ==================== 安装 ====================
    private Dictionary<string, object?> BaseExtra(string name)
    {
        var gv = _version.Str();
        return new Dictionary<string, object?>
        {
            ["name"] = name,
            ["source"] = _source.Str(),
            ["instance"] = CurrentInstance(),
            ["game_version"] = gv.StartsWith("全部") ? "" : gv,
            ["kind"] = _kind.FileKind,
        };
    }

    private async Task InstallAsync(CatalogItem item, FrameworkElement anchor)
    {
        var extra = BaseExtra(item.Name);
        extra["source"] = string.IsNullOrEmpty(item.Source) ? _source.Str() : item.Source;
        extra["slug"] = item.Slug;
        extra["id"] = item.IdValue;

        if (item.Slug is { Length: > 0 } || item.IdValue != null)
        {
            var picked = await PickVersionFileAsync(item, extra);
            if (picked is null) return;
            extra = picked;
        }
        await DoInstallAsync(extra, anchor);
    }

    /// <summary>弹出版本文件选择。返回 null = 取消；返回 extra = 安装最新或所选文件。</summary>
    private async Task<Dictionary<string, object?>?> PickVersionFileAsync(CatalogItem item, Dictionary<string, object?> extra)
    {
        List<CatalogFile> files;
        using (Dlg.Busy("正在获取版本文件…"))
            files = await Api.TryCallAsync<List<CatalogFile>>("list_catalog_files", new { extra }, new()) ?? new();

        if (files.Count == 0)
            return await Dlg.Confirm("没有找到版本文件", "在线列表为空，要直接尝试安装最新版吗？", "安装最新", "取消")
                ? extra
                : null;

        var chosen = files[0];
        var listHost = Ui.V(6);
        var scroll = Ui.Scroll(listHost);
        scroll.MaxHeight = 340;
        scroll.MinWidth = 560;

        var gvs = new List<string> { "全部" };
        var loaders = new List<string> { "全部" };
        foreach (var f in files)
        {
            foreach (var v in f.GameVersions ?? new()) if (!gvs.Contains(v)) gvs.Add(v);
            foreach (var l in f.Loaders ?? new()) if (!loaders.Contains(l)) loaders.Add(l);
        }
        var gvBox = Ui.Combo(gvs, "全部", 130);
        var loaderBox = Ui.Combo(loaders, "全部", 130);
        var count = Ui.Muted("");

        void Refill()
        {
            var gv = gvBox.Str();
            var ld = loaderBox.Str();
            var matched = files.Where(f =>
            {
                if (!gv.StartsWith("全部") && f.GameVersions is { Count: > 0 } && !f.GameVersions.Contains(gv)) return false;
                if (!ld.StartsWith("全部") && f.Loaders is { Count: > 0 } &&
                    !f.Loaders.Any(l => string.Equals(l, ld, StringComparison.OrdinalIgnoreCase))) return false;
                return true;
            }).ToList();
            if (matched.Count > 0 && !matched.Contains(chosen)) chosen = matched[0];
            listHost.Children.Clear();
            foreach (var f in matched.Take(80)) listHost.Children.Add(FileRow(f));
            count.Text = $"{matched.Count} 个匹配 / 共 {files.Count} 个文件";
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
            Ui.Txt("游戏版本", 12, fg: "B.InkMuted").VCenter(), gvBox.VCenter(),
            Ui.Txt("加载器", 12, fg: "B.InkMuted").VCenter(), loaderBox.VCenter(),
            count.VCenter());
        var idx = await Dlg.Choose($"选择版本文件 · {item.Name}",
            Ui.V(10, filters, scroll), new[] { "取消", "安装最新", "安装所选" }, 660);
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

    private async Task DoInstallAsync(Dictionary<string, object?> extra, FrameworkElement? anchor)
    {
        var name = extra.TryGetValue("name", out var n) ? n?.ToString() ?? _kind.Title : _kind.Title;
        if (_kind.IsModpack)
        {
            await Api.StartTaskAsync(_kind.InstallMethod, new
            {
                name,
                source = extra.TryGetValue("source", out var s) && s?.ToString() is { Length: > 0 } src ? src : "Modrinth",
                extra,
            });
        }
        else
        {
            await Api.StartTaskAsync(_kind.InstallMethod, new
            {
                name,
                instance = CurrentInstance(),
                extra,
            });
        }
        if (anchor != null && SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, name);
        Win?.Navigate("tasks");
    }

    private async Task InstallFromLinkAsync(FrameworkElement anchor)
    {
        var url = await Dlg.Prompt(_kind.Title + " · 链接安装", _kind.LinkHint, "", "https://…");
        if (string.IsNullOrWhiteSpace(url)) return;
        var extra = BaseExtra(url.Trim());
        extra["url"] = url.Trim();
        await DoInstallAsync(extra, anchor);
    }

    private void ImportLocal(FrameworkElement anchor)
    {
        var d = new OpenFileDialog
        {
            Filter = _kind.LocalFilter,
            Title = "导入本地" + _kind.Title,
            Multiselect = true,
            CheckFileExists = true,
        };
        if (d.ShowDialog() != true || d.FileNames.Length == 0) return;
        var files = d.FileNames;
        Run(async () =>
        {
            foreach (var f in files)
            {
                var extra = BaseExtra(System.IO.Path.GetFileName(f));
                extra["path"] = f;
                extra["source"] = "本地";
                await DoInstallAsync(extra, null);
            }
            if (SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, $"{files.Length} 个文件");
            Win?.Navigate("tasks");
        }, "导入失败");
    }

    // ==================== 已安装 ====================
    private async Task LoadInstalledAsync()
    {
        var token = ++_searchToken;
        _list.Children.Clear();
        _list.Children.Add(Ui.Skeleton(46));
        var inst = CurrentInstance();
        if (string.IsNullOrEmpty(inst))
        {
            _list.Children.Clear();
            _list.Children.Add(Ui.Empty(Glyph(), "还没有实例", "先到「实例」页新建一个"));
            return;
        }
        try
        {
            if (_kind.Key == "mod")
            {
                var entries = await Api.TryCallAsync<List<ModEntry>>("get_installed_mod_entries",
                    new { instance = inst, version = "" }, new()) ?? new();
                if (token != _searchToken) return;
                RenderModEntries(entries);
                return;
            }
            var names = await Api.TryCallAsync<List<string>>(_kind.InstalledMethod,
                new { instance = inst }, new()) ?? new();
            if (token != _searchToken) return;
            RenderInstalledNames(names);
        }
        catch (Exception ex)
        {
            if (token != _searchToken) return;
            _list.Children.Clear();
            _list.Children.Add(Ui.Empty(Ico.Warning, "读取失败", ex.Message));
        }
    }

    private void RenderModEntries(List<ModEntry> entries)
    {
        _list.Children.Clear();
        if (entries.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Glyph(), "这个实例还没有 Mod", "切回「搜索下载」装一个"));
            return;
        }
        var inst = CurrentInstance();
        foreach (var m in entries)
        {
            var file = m.Filename;
            var sw = Ui.Switch(m.Enabled);
            sw.Checked += async (_, _) => await Api.TryCallAsync<object>("enable_mod", new { instance = inst, filename = file, version = "" });
            sw.Unchecked += async (_, _) => await Api.TryCallAsync<object>("disable_mod", new { instance = inst, filename = file, version = "" });
            var del = Ui.Btn("删除", BtnKind.Ghost, (_, _) => Run(() => DeleteInstalledAsync(file), "删除失败"));
            var g = Ui.G(null, "Auto,*,Auto,Auto");
            g.Add(sw.M(0, 0, 10, 0).VCenter(), 0, 0);
            g.Add(Ui.V(1,
                Ui.Txt(string.IsNullOrWhiteSpace(m.Name) ? file : m.Name, 13).Trim(),
                Ui.Small(string.Join(" · ", new[] { file, m.Version, m.Size }.Where(x => !string.IsNullOrEmpty(x))))).VCenter(), 0, 1);
            g.Add(Ui.Small(m.Enabled ? "" : "已禁用").VCenter().M(8, 0, 0, 0), 0, 2);
            g.Add(del.VCenter().M(8, 0, 0, 0), 0, 3);
            _list.Children.Add(Ui.RowCard(g, padding: 10));
        }
        Motion.Stagger(_list, 16, 180, 8);
    }

    private void RenderInstalledNames(List<string> names)
    {
        _list.Children.Clear();
        if (names.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Glyph(), $"这个实例还没有{_kind.Title}", "切回「搜索下载」装一个"));
            return;
        }
        foreach (var file in names)
        {
            var del = Ui.Btn("删除", BtnKind.Ghost, (_, _) => Run(() => DeleteInstalledAsync(file), "删除失败"));
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.Txt(file, 12.5).Trim().VCenter(), 0, 0);
            g.Add(del.VCenter(), 0, 1);
            _list.Children.Add(Ui.RowCard(g, padding: 10));
        }
        Motion.Stagger(_list, 16, 180, 8);
    }

    private async Task DeleteInstalledAsync(string filename)
    {
        if (string.IsNullOrEmpty(_kind.DeleteMethod)) return;
        if (!await Dlg.Confirm("删除确认", $"将删除「{filename}」，不可恢复。", "删除", "取消", true)) return;
        var inst = CurrentInstance();
        if (_kind.DeleteMethod == "delete_mod")
            await Api.CallAsync(_kind.DeleteMethod, new { instance = inst, filename, version = "" });
        else
            await Api.CallAsync(_kind.DeleteMethod, new { instance = inst, filename });
        Toast("已删除", filename, ToastKind.Success);
        await LoadInstalledAsync();
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        if (ev.Event == "finished" && ev.Success && _installedMode)
            Run(LoadInstalledAsync);
    }
}
