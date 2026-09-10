using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>Java 运行时管理：已装列表、系统扫描、按版本下载、实例默认 Java。</summary>
public sealed class JavaPage : PageBase
{
    public override string Title => "Java";

    private static readonly string[] Majors = { "8", "11", "17", "21" };

    private readonly SPanel _list = Ui.V(8);
    private readonly TextBlock _count = Ui.Muted("");
    private readonly ComboBox _inst = Ui.Combo(width: 170);
    private readonly ComboBox _java = Ui.Combo();
    private List<InstanceInfo> _instances = new();
    private List<JavaOption> _javaOpts = new();
    private bool _sync;

    public JavaPage()
    {
        var scan = Ui.Btn("扫描系统 Java", BtnKind.Soft, null, Ico.Search);
        scan.Click += (_, _) => Run(() => ReloadListAsync(true), "扫描失败");
        var refresh = Ui.IconBtn(Ico.Refresh, "刷新", (_, _) => Run(LoadAsync));
        var head = Ui.Section("Java", "游戏按版本挑 Java：1.20.5+ 要 21，1.18+ 要 17，老版本用 8",
            Ui.H(8, _count.VCenter(), refresh, scan));

        var dlRow = Ui.H(8, Ui.Txt("下载 Java（Adoptium）", 13).VCenter());
        foreach (var m in Majors)
        {
            var major = m;
            var b = Ui.Btn("Java " + major, BtnKind.Chip, null, Ico.Download);
            b.Click += (_, _) => Run(() => DownloadAsync(major, b), "下载失败");
            dlRow.Children.Add(b);
        }
        var dlCard = Ui.Card(dlRow, 13);

        _inst.SelectionChanged += (_, _) => { if (!_sync) Run(ReloadJavaOptionsAsync); };
        _java.SelectionChanged += (_, _) => { if (!_sync) Run(SaveJavaAsync, "保存失败"); };
        var instCard = Ui.Card(Ui.V(4,
            Ui.Field("实例", _inst),
            Ui.Field("默认 Java", _java, "「自动选择」由启动器按游戏版本匹配")), 13);

        Content = ScrollBody(head, dlCard, instCard, _list);
    }

    protected override async Task LoadAsync()
    {
        _instances = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _sync = true;
        _inst.Fill(_instances.Select(i => i.Name));
        _sync = false;
        await ReloadJavaOptionsAsync();
        await ReloadListAsync(false);
    }

    private async Task ReloadJavaOptionsAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance = inst, scan_system = false }, new()) ?? new();
        if (opts.Count == 0) return;
        var want = await Api.TryCallAsync<string>("java_combo_label_for",
            new { instance = inst, options = opts }, "自动选择");
        _sync = true;
        _javaOpts = opts;
        _java.Fill(opts.Select(o => o.Label), want);
        _sync = false;
    }

    private async Task SaveJavaAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var label = _java.Str();
        var value = _javaOpts.FirstOrDefault(o => o.Label == label)?.Value
                    ?? (string.IsNullOrEmpty(label) ? "自动选择" : label);
        await Api.CallAsync<object>("set_instance_java", new { name = inst, java = value });
        Toast("已保存", $"「{inst}」默认 Java：{label}", ToastKind.Success);
    }

    private async Task ReloadListAsync(bool scan)
    {
        _list.Children.Clear();
        _list.Children.Add(Ui.Skeleton(52));
        _list.Children.Add(Ui.Skeleton(52));
        List<JavaInfo> rows;
        if (scan)
        {
            using (Dlg.Busy("正在扫描系统 Java…"))
                rows = await Api.TryCallAsync<List<JavaInfo>>("get_java_list",
                    new { scan_system = true }, new()) ?? new();
        }
        else
        {
            rows = await Api.TryCallAsync<List<JavaInfo>>("get_java_list",
                new { scan_system = false }, new()) ?? new();
        }
        _list.Children.Clear();
        _count.Text = $"共 {rows.Count} 个";
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Coffee, "没有找到 Java", "点上面「下载 Java」装一个，或扫描系统已有安装"));
            return;
        }
        foreach (var j in rows) _list.Children.Add(Row(j));
        Motion.Stagger(_list, 18, 190, 8);
    }

    private UIElement Row(JavaInfo j)
    {
        var badge = new Border
        {
            Width = 42,
            Height = 42,
            CornerRadius = new CornerRadius(10),
            Child = Ui.Txt(j.Major, 14, true, "B.AccentDeep").Center(),
        };
        badge.SetResourceReference(Border.BackgroundProperty, "B.AccentSoft");
        badge.VCenter();

        var setDef = Ui.Btn("设为默认", BtnKind.Chip, (_, _) => Run(async () =>
        {
            await Api.CallAsync<object>("update_settings", new { settings = new { default_java = j.Path } });
            Toast("已设为默认", j.Name, ToastKind.Success);
        }, "保存失败"));
        var open = Ui.IconBtn(Ico.Folder, "打开所在目录", (_, _) => Run(() => OpenFolderAsync(j.Path), "打开失败"));

        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(badge.M(0, 0, 12, 0), 0, 0);
        g.Add(Ui.V(2, Ui.Txt(j.Name, 13, true).Trim(), Ui.Mono(j.Path).Trim()).VCenter(), 0, 1);
        g.Add(Ui.H(6, setDef, open).VCenter().M(12, 0, 0, 0), 0, 2);
        return Ui.RowCard(g, padding: 11);
    }

    private async Task OpenFolderAsync(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        // 后端若有 open_java_folder / open_path 就优先走桥（未来原生桥可统一接管），否则本地 explorer。
        var viaBridge = await Api.TryCallAsync<string>("open_java_folder", new { path }, "");
        if (!string.IsNullOrEmpty(viaBridge)) return;
        try
        {
            if (File.Exists(path)) Process.Start("explorer.exe", $"/select,\"{path}\"");
            else if (Directory.Exists(path)) Process.Start("explorer.exe", $"\"{path}\"");
        }
        catch (Exception ex)
        {
            Toast("打开失败", ex.Message, ToastKind.Warning);
        }
    }

    private async Task DownloadAsync(string major, FrameworkElement anchor)
    {
        await Api.StartTaskAsync("download_java", new { major, vendor = "adoptium" });
        if (SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, "Java " + major);
        Toast("已加入队列", $"正在下载 Java {major}，进度看下载任务");
    }

    public override void OnEvent(BridgeEvent ev)
    {
        if (ev.Event == "finished" && ev.Success &&
            TaskStore.Get(ev.TaskId)?.Title.Contains("Java", StringComparison.OrdinalIgnoreCase) == true)
            Run(async () =>
            {
                await ReloadListAsync(false);
                await ReloadJavaOptionsAsync();
            });
    }
}
