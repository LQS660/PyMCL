using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class InstancePage : PageBase
{
    public override string Title => "实例";

    private readonly WrapPanel _grid = new();
    private readonly TextBlock _count = Ui.Muted("");
    private string _defaultInstance = "";

    public InstancePage()
    {
        var create = Ui.Btn("新建实例", BtnKind.Primary, (_, _) => Run(CreateAsync), Ico.Add);
        var import = Ui.Btn("导入官方启动器", BtnKind.Chip, (_, _) => Run(MigrateAsync), Ico.Import);
        var refresh = Ui.Btn("刷新", BtnKind.Chip, (_, _) => Run(LoadAsync), Ico.Refresh);
        var head = Ui.Section("实例", "每个实例是一份独立的 .minecraft，互不干扰",
            Ui.H(8, _count.VCenter(), import, refresh, create));
        Content = ScrollBody(head, _grid);
    }

    protected override async Task LoadAsync()
    {
        var rows = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        // get_settings 目前不带 default_instance，先试 get_setting 单键读取；拿不到就沿用页内状态。
        var def = await Api.TryCallAsync<string>("get_setting", new { key = "default_instance", @default = "" }, "");
        if (!string.IsNullOrEmpty(def)) _defaultInstance = def;
        _grid.Children.Clear();
        _count.Text = $"共 {rows.Count} 个";
        foreach (var r in rows) _grid.Children.Add(BuildCard(r));
        Motion.StaggerItems(_grid.Children.Cast<UIElement>(), 30, 220, 12);
    }

    private UIElement BuildCard(InstanceInfo info)
    {
        var name = Ui.Txt(info.Name, 15, true).Trim();
        var mc = Ui.Muted(string.IsNullOrEmpty(info.Pack) ? info.Mc : $"{info.Pack} {info.PackVersion}".Trim());
        var chips = Ui.H(6,
            info.Name == _defaultInstance ? Ui.Tag("默认", "B.OnAccent", "B.Accent") : null,
            Ui.Tag($"{info.Versions} 个版本"),
            string.IsNullOrEmpty(info.JavaLabel) ? null : Ui.Tag(info.JavaLabel, "B.AccentDeep", "B.AccentSoft"),
            string.IsNullOrEmpty(info.McVersion) ? null : Ui.Tag("MC " + info.McVersion));

        var play = Ui.Btn("启动", BtnKind.Soft, (_, _) => Run(() => LaunchWithAsync(info)), Ico.Play);
        var more = Ui.IconBtn(Ico.More, "更多", (s, _) => Menu((FrameworkElement)s, info));

        var body = Ui.V(9,
            Ui.H(10, Icon(info), Ui.V(2, name, mc).VCenter()),
            chips,
            Ui.Sep(),
            Ui.H(6, play, more));
        var card = Ui.Card(body, 15);
        card.Width = 268;
        card.Margin = new Thickness(0, 0, 12, 12);
        Motion.HoverLift(card);
        card.MouseLeftButtonUp += (_, e) =>
        {
            if (e.OriginalSource is DependencyObject d && FindButton(d) != null) return;
            Run(() => LaunchWithAsync(info));
        };
        card.Cursor = Cursors.Hand;
        return card;
    }

    /// <summary>设为默认实例并跳到启动页。后端还没有 set_default_instance，缺了就用 update_settings 补丁兜底。</summary>
    private async Task LaunchWithAsync(InstanceInfo info)
    {
        if (await Api.TryCallAsync<object>("set_default_instance", new { name = info.Name }) is null)
            await Api.TryCallAsync<object>("update_settings", new { settings = new { default_instance = info.Name } });
        _defaultInstance = info.Name;
        if (Win?.GetPage("launch") is LaunchPage lp) lp.PreferInstance(info.Name);
        Win?.Navigate("launch");
        await LoadAsync();
    }

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

    private void Menu(FrameworkElement anchor, InstanceInfo info)
    {
        var menu = new ContextMenu();
        void Item(string head, Func<Task> act)
        {
            var mi = new MenuItem { Header = head };
            mi.Click += (_, _) => Run(act);
            menu.Items.Add(mi);
        }
        Item("打开文件夹", async () => await Api.CallAsync("open_instance_folder", new { name = info.Name }));
        Item("设为默认实例", async () =>
        {
            if (await Api.TryCallAsync<object>("set_default_instance", new { name = info.Name }) is null)
                await Api.TryCallAsync<object>("update_settings", new { settings = new { default_instance = info.Name } });
            _defaultInstance = info.Name;
            await LoadAsync();
            Toast("默认实例", $"之后的启动将默认使用「{info.Name}」", ToastKind.Success);
        });
        Item("存档管理", async () => await SavesDialog.ShowAsync(info.Name, ""));
        Item("模组管理", async () => await ModsDialog.ShowAsync(info.Name));
        Item("选择 Java…", () => PickJavaAsync(info));
        Item("导出为整合包", async () =>
        {
            var dest = Dlg.SaveFile("Modrinth 整合包 (*.mrpack)|*.mrpack", info.Name + ".mrpack", "导出整合包");
            if (dest is null) return;
            await Api.StartTaskAsync("export_modpack", new { instance = info.Name, dest });
            Win?.FlyToTasks(anchor, "导出中");
        });
        Item("检查模组更新", async () =>
        {
            await Api.StartTaskAsync("start_mod_updates", new { instance = info.Name });
            Win?.FlyToTasks(anchor, "检查更新");
        });
        menu.Items.Add(new Separator());
        Item("重命名…", async () =>
        {
            var name = await Dlg.Prompt("重命名实例", "新名称", info.Name);
            if (string.IsNullOrWhiteSpace(name) || name == info.Name) return;
            await Api.CallAsync("rename_instance", new { name = info.Name, new_name = name });
            await LoadAsync();
        });
        Item("删除实例", async () =>
        {
            if (!await Dlg.Confirm("删除实例", $"「{info.Name}」下的版本、模组、存档都会被删除，且不可恢复。",
                    "永久删除", "取消", true)) return;
            await Api.CallAsync("delete_instance", new { name = info.Name });
            await LoadAsync();
            Toast("已删除", info.Name, ToastKind.Success);
        });
        menu.PlacementTarget = anchor;
        menu.IsOpen = true;
    }

    private async Task PickJavaAsync(InstanceInfo info)
    {
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance = info.Name, scan_system = true }, new()) ?? new();
        if (opts.Count == 0)
        {
            Toast("没找到 Java", "去 Java 页下载一个", ToastKind.Warning);
            return;
        }
        var cur = await Api.TryCallAsync<string>("java_combo_label_for", new { instance = info.Name, options = opts }, "自动选择");
        var combo = Ui.Combo(opts.Select(o => o.Label), cur);
        var ok = await Dlg.Ask("为「" + info.Name + "」选择 Java", Ui.V(8, Ui.Muted("留「自动选择」由启动器按版本匹配"), combo), "保存");
        if (!ok) return;
        var val = opts.FirstOrDefault(o => o.Label == combo.Str())?.Value ?? "自动选择";
        await Api.CallAsync("set_instance_java", new { name = info.Name, java = val });
        await LoadAsync();
    }

    private async Task CreateAsync()
    {
        var name = await Dlg.Prompt("新建实例", "实例名称（会创建独立的 .minecraft）", "", "例如：1.20.1 生存");
        if (string.IsNullOrWhiteSpace(name)) return;
        await Api.CallAsync("create_instance", new { name });
        await LoadAsync();
        Toast("已创建", name, ToastKind.Success);
    }

    private async Task MigrateAsync()
    {
        var found = await Api.TryCallAsync<bool>("detect_official_launcher", null, false);
        if (!found)
        {
            Toast("没找到官方启动器", "未检测到 .minecraft 目录", ToastKind.Warning);
            return;
        }
        var dir = await Api.TryCallAsync<string>("official_launcher_dir", null, "");
        var versions = await Api.TryCallAsync<List<string>>("scan_official_versions", null, new()) ?? new();
        var target = Ui.Input("default", "default");
        var body = Ui.V(8,
            Ui.Muted($"检测到：{dir}"),
            Ui.Muted($"可导入 {versions.Count} 个版本：{string.Join("、", versions.Take(8))}{(versions.Count > 8 ? " …" : "")}"),
            Ui.Txt("导入到实例", 12, fg: "B.InkMuted"),
            target);
        if (!await Dlg.Ask("导入官方启动器", body, "开始导入")) return;
        await Api.StartTaskAsync("migrate_official_launcher", new { instance = target.Text?.Trim() ?? "default" });
        Toast("已开始导入", "进度看下载任务");
    }
}
