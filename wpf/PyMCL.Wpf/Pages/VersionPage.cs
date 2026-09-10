using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class VersionPage : PageBase
{
    public override string Title => "原版游戏";

    private static readonly string[] Loaders = { "无", "Fabric", "Forge", "Quilt", "NeoForge" };

    private readonly TextBox _search = Ui.Input("过滤版本号，例如 1.20");
    private readonly ListBox _list = new() { Style = Ui.S("PlainList"), ItemTemplate = (DataTemplate)Application.Current.FindResource("Tpl.Version") };
    private readonly ListBox _installed = new() { Style = Ui.S("PlainList"), ItemTemplate = (DataTemplate)Application.Current.FindResource("Tpl.Installed") };
    private readonly ComboBox _inst = Ui.Combo();
    private readonly ComboBox _loader = Ui.Combo(Loaders);
    private readonly ComboBox _loaderVer = Ui.Combo(new[] { "最新" });
    private readonly CheckBox _release = Ui.Check("正式版", true);
    private readonly CheckBox _snapshot = Ui.Check("快照", false);
    private readonly CheckBox _oldBeta = Ui.Check("旧测试", false);
    private readonly CheckBox _oldAlpha = Ui.Check("旧阿尔法", false);
    private readonly CheckBox _optifine = Ui.Check("OptiFine");
    private readonly CheckBox _lite = Ui.Check("LiteLoader");
    private readonly Button _install;
    private readonly TextBlock _count = Ui.Muted("");
    private readonly TextBlock _instCount = Ui.Muted("");
    private List<Row> _all = new();

    /// <summary>Tpl.Version 模板绑定 TypeLabel，包一层视图模型把类型翻译成中文。</summary>
    private sealed class Row
    {
        public string Version { get; init; } = "";
        public string Type { get; init; } = "";
        public string Date { get; init; } = "";
        public string TypeLabel => Type switch
        {
            "release" => "正式版",
            "snapshot" => "快照",
            "old_beta" => "旧测试",
            "old_alpha" => "旧阿尔法",
            _ => string.IsNullOrEmpty(Type) ? "未知" : Type,
        };
    }

    private static Row Map(VersionRow r) => new() { Version = r.Version, Type = r.Type, Date = r.Date };

    public VersionPage()
    {
        _install = Ui.Btn("安装所选版本", BtnKind.Primary, (_, _) => Run(InstallAsync), Ico.Download);
        _install.IsEnabled = false;

        var refresh = Ui.Btn("刷新清单", BtnKind.Chip, (_, _) => Run(FetchAsync), Ico.Refresh);
        var head = Ui.Section("原版游戏", "Mojang 全量版本 + Fabric / Forge / Quilt / NeoForge 加载器",
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
            if (_loader.Str() != "无") Run(LoadLoaderVersionsAsync);
        };
        _list.MouseDoubleClick += (_, _) => Run(InstallAsync);
        _loader.SelectionChanged += (_, _) =>
        {
            var l = _loader.Str();
            _loaderVer.IsEnabled = l != "无";
            _optifine.IsEnabled = l is "无" or "Forge";
            if (!_optifine.IsEnabled) _optifine.IsChecked = false;
            Run(LoadLoaderVersionsAsync);
        };
        _installed.MouseDoubleClick += (_, _) => Run(async () => await InstalledMenuAsync());

        var filters = Ui.H(14, _release, _snapshot, _oldBeta, _oldAlpha);
        var listCard = Ui.Card(Ui.V(10,
            Ui.H(10, _search, filters.VCenter()),
            _list), 14);
        _search.MinWidth = 240;
        _list.Height = 330;

        var setup = Ui.Card(Ui.V(10,
            Ui.H3("安装设置"),
            Ui.Field("目标实例", _inst, labelWidth: 88),
            Ui.Field("加载器", _loader, labelWidth: 88),
            Ui.Field("加载器版本", _loaderVer, labelWidth: 88),
            Ui.H(16, _optifine, _lite),
            _install.Stretch()), 14);

        var installedCard = Ui.Card(Ui.V(10,
            Ui.Section("已安装", null, _instCount),
            _installed,
            Ui.Muted("双击一行查看启动 / 设置 / 重命名 / 复制 / 修复 / 卸载")), 14);
        _installed.Height = 190;

        var cols = Ui.G(null, "*,320");
        cols.Add(Ui.V(14, listCard, installedCard), 0, 0);
        cols.Add(Ui.V(14, setup).M(14, 0, 0, 0), 0, 1);

        Content = ScrollBody(head, cols);
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
        if (cached.Count == 0) await FetchAsync();
        else _ = FetchAsync();
    }

    private async Task FetchAsync()
    {
        _count.Text = "正在拉取版本清单…";
        var rows = await Api.TryCallAsync<List<VersionRow>>("fetch_version_list");
        if (rows is { Count: > 0 })
        {
            _all = rows.Select(Map).ToList();
            ApplyFilter();
        }
        else if (_all.Count == 0) _count.Text = "拉取失败，检查网络后点刷新";
        else Toast("版本清单刷新失败", "沿用已缓存的清单", ToastKind.Warning);
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
        _count.Text = $"{final.Count} / {_all.Count} 个版本";
        if (final.Count > 0 && _list.SelectedIndex < 0) _list.SelectedIndex = 0;
    }

    private async Task ReloadInstalledAsync()
    {
        var inst = _inst.Str();
        var ids = string.IsNullOrEmpty(inst)
            ? new List<string>()
            : await Api.TryCallAsync<List<string>>("get_installed_versions", new { instance = inst, include_hidden = true }, new()) ?? new();
        _installed.ItemsSource = ids;
        _instCount.Text = $"{ids.Count} 个";
    }

    private async Task LoadLoaderVersionsAsync()
    {
        var loader = _loader.Str();
        if (loader == "无" || _list.SelectedItem is not Row row)
        {
            _loaderVer.Fill(new[] { "最新" });
            return;
        }
        _loaderVer.Fill(new[] { "最新（加载中…）" });
        var rows = await Api.TryCallAsync<List<LoaderVer>>("list_loader_versions",
            new { mc_version = row.Version, loader = loader.ToLowerInvariant() }, new()) ?? new();
        var labels = new List<string> { "最新" };
        labels.AddRange(rows.Select(r => string.IsNullOrEmpty(r.Label) ? r.Id : r.Label));
        _loaderVer.Fill(labels, "最新");
        _loaderVer.Tag = rows;
    }

    private async Task InstallAsync()
    {
        if (_list.SelectedItem is not Row row)
        {
            Toast("先选一个版本", "", ToastKind.Warning);
            return;
        }
        var loader = _loader.Str();
        var loaderVersion = "";
        if (loader != "无" && _loaderVer.SelectedIndex > 0 && _loaderVer.Tag is List<LoaderVer> rows)
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
            loader = loader == "无" ? "无" : loader,
            loader_version = loaderVersion,
            instance = _inst.Str(),
            extra,
        });
        Win?.FlyToTasks(_install, row.Version);
        Toast("已加入队列", $"{row.Version}{(loader == "无" ? "" : " + " + loader)}", ToastKind.Success);
        Win?.Navigate("tasks");
    }

    private async Task InstalledMenuAsync()
    {
        if (_installed.SelectedItem is not string ver) return;
        var inst = _inst.Str();
        var options = new[] { "取消", "启动", "版本设置", "重命名", "复制", "打开文件夹", "修复", "卸载" };
        var pick = await Dlg.Choose($"版本 {ver}", Ui.Muted($"实例：{inst}"), options, 560);
        switch (pick)
        {
            case 1:
                // 后端暂无 set_default_instance，先探测，缺了再退 update_settings 补丁。
                if (await Api.TryCallAsync<object>("set_default_instance", new { name = inst }) is null)
                    await Api.TryCallAsync<object>("update_settings", new { settings = new { default_instance = inst } });
                if (Win?.GetPage("launch") is LaunchPage lp) lp.PreferInstance(inst, ver);
                Win?.Navigate("launch");
                break;
            case 2:
                await VersionSetupDialog.ShowAsync(inst, ver);
                break;
            case 3:
                var name = await Dlg.Prompt("重命名版本", "新版本 ID", ver);
                if (!string.IsNullOrWhiteSpace(name) && name != ver)
                {
                    await Api.CallAsync("rename_version", new { instance = inst, version = ver, new_id = name });
                    await ReloadInstalledAsync();
                }
                break;
            case 4:
                var copy = await Dlg.Prompt("复制版本", "新版本 ID", ver + "-copy");
                if (!string.IsNullOrWhiteSpace(copy))
                {
                    await Api.CallAsync("copy_version", new { instance = inst, version = ver, new_id = copy });
                    await ReloadInstalledAsync();
                }
                break;
            case 5:
                await Api.CallAsync("open_version_folder", new { instance = inst, version = ver, which = "root" });
                break;
            case 6:
                await Api.StartTaskAsync("repair_version", new { instance = inst, version = ver });
                Toast("已开始修复", ver);
                break;
            case 7:
                if (!await Dlg.Confirm("卸载版本", $"删除「{inst} / {ver}」的版本文件？", "卸载", "取消", true)) return;
                await Api.CallAsync("uninstall_version", new { spec = $"{inst} / {ver}" });
                await ReloadInstalledAsync();
                Toast("已卸载", ver, ToastKind.Success);
                break;
        }
    }

    public override async Task RefreshAsync() => await ReloadInstalledAsync();

    public override void OnShown()
    {
        _inst.SelectionChanged -= InstChanged;
        _inst.SelectionChanged += InstChanged;
    }

    private void InstChanged(object? s, SelectionChangedEventArgs e) => Run(ReloadInstalledAsync);
}
