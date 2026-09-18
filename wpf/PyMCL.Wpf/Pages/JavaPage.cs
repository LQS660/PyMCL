using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>Java 运行时管理：已装列表、系统扫描、按发行版下载、实例默认 Java。</summary>
public sealed class JavaPage : PageBase
{
    public override string Title => "Java";

    private static readonly (string Major, string Note)[] Majors =
    {
        ("8", L("1.16 及以下旧版本")),
        ("11", L("部分旧模组环境")),
        ("17", L("1.18 – 1.20.4 推荐")),
        ("21", L("1.20.5+ 新版本")),
    };

    private readonly SPanel _list = Ui.V(8);
    private readonly TextBlock _count = Ui.Muted("");
    private readonly ComboBox _inst = Ui.Combo(width: 170);
    private readonly ComboBox _java = Ui.Combo();
    private readonly ComboBox _vendor = Ui.Combo(width: 170);
    private readonly TextBlock _instJava = Ui.Small("");
    private readonly TextBox _manual = Ui.Input(L("手动填 java.exe 路径（可空）"));
    private List<InstanceInfo> _instances = new();
    private List<JavaOption> _javaOpts = new();
    private List<string> _vendors = new();
    private bool _sync;

    public JavaPage()
    {
        var scan = Ui.Btn(L("扫描系统 Java"), BtnKind.Soft, null, Ico.Search);
        scan.Click += (_, _) => Run(() => ReloadListAsync(true), L("扫描失败"));
        var refresh = Ui.IconBtn(Ico.Refresh, L("刷新"), (_, _) => Run(LoadAsync));
        var head = Ui.Section("Java", L("游戏按版本挑 Java：1.20.5+ 要 21，1.18+ 要 17，老版本用 8"),
            Ui.H(8, _count.VCenter(), refresh, scan));

        var tiles = new WrapPanel();
        foreach (var (major, note) in Majors)
        {
            var m = major;
            var btn = Ui.Btn(L("下载"), BtnKind.Chip, null, Ico.Download);
            btn.Click += (_, _) => Run(() => DownloadAsync(m, btn), L("下载失败"));
            var tile = Ui.Card(Ui.V(6,
                Ui.Txt("Java " + major, 15, true),
                Ui.Small(note).Wrap(),
                btn.Stretch()), 13);
            tile.Width = 158;
            tile.Margin = new Thickness(0, 0, 10, 10);
            Motion.HoverLift(tile, 1.01, 2, 18);
            tiles.Children.Add(tile);
        }
        var dlHead = Ui.G(null, "*,Auto,Auto");
        dlHead.Add(Ui.Txt(L("下载新运行时"), 13, true).VCenter(), 0, 0);
        dlHead.Add(Ui.Txt(L("发行版"), 12, fg: "B.InkMuted").M(0, 0, 8, 0).VCenter(), 0, 1);
        dlHead.Add(_vendor.VCenter(), 0, 2);
        var dlCard = Ui.Card(Ui.V(10, dlHead, tiles), 13);

        _inst.SelectionChanged += (_, _) => { if (!_sync) Run(ReloadJavaOptionsAsync); };
        _java.SelectionChanged += (_, _) => { if (!_sync) Run(SaveJavaAsync, L("保存失败")); };
        var applyManual = Ui.Btn(L("用这个路径"), BtnKind.Chip, (_, _) => Run(ApplyManualAsync, L("保存失败")), Ico.Check);
        var manualRow = Ui.G(null, "*,Auto");
        manualRow.Add(_manual, 0, 0);
        manualRow.Add(applyManual.M(8, 0, 0, 0).VCenter(), 0, 1);

        var instCard = Ui.Card(Ui.V(4,
            Ui.Field(L("实例"), _inst),
            Ui.Field(L("默认 Java"), _java, L("「自动选择」由启动器按游戏版本匹配")),
            Ui.Field(L("自定义路径"), manualRow, L("填绝对路径后点右边按钮，会先做一次规范化")),
            Ui.Field("", _instJava)), 13);

        Content = ScrollBody(head, dlCard, instCard, _list);
    }

    protected override async Task LoadAsync()
    {
        _instances = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _sync = true;
        _inst.Fill(_instances.Select(i => i.Name));
        _sync = false;
        // 发行版清单与已装 Java 列表互不依赖，一起发出去
        var vendors = ReloadVendorsAsync();
        var list = ReloadListAsync(false);
        await vendors;
        await ReloadJavaOptionsAsync();
        await list;
    }

    /// <summary>
    /// 发行版清单由后端给，标签也由后端翻译，前端不写死 Adoptium / Zulu 这些名字。
    /// 标签一次性并发问完：逐个 await 的话 N 个发行版就是 N 次串行往返，
    /// 运行期冒烟里这一页因此卡到 9 秒以上。
    /// </summary>
    private async Task ReloadVendorsAsync()
    {
        _vendors = await Api.TryCallAsync<List<string>>("java_vendor_list", null, new()) ?? new();
        if (_vendors.Count == 0) _vendors = new List<string> { "adoptium" };
        var labels = (await Task.WhenAll(_vendors.Select(v =>
            Api.TryCallAsync<string>("java_vendor_label", new { vendor = v }, v)))).ToList();
        for (var i = 0; i < labels.Count; i++)
            if (string.IsNullOrEmpty(labels[i])) labels[i] = _vendors[i];
        _sync = true;
        _vendor.Items.Clear();
        foreach (var l in labels) _vendor.Items.Add(l);
        var def = _vendors.IndexOf("adoptium");
        _vendor.SelectedIndex = def >= 0 ? def : 0;
        _sync = false;
    }

    private string SelectedVendor()
    {
        var idx = _vendor.SelectedIndex;
        return idx >= 0 && idx < _vendors.Count ? _vendors[idx] : "adoptium";
    }

    private async Task ReloadJavaOptionsAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var opts = await Api.TryCallAsync<List<JavaOption>>("java_combo_options",
            new { instance = inst, scan_system = false }, new()) ?? new();
        if (opts.Count == 0) return;
        var want = await Api.TryCallAsync<string>("java_combo_label_for",
            new { instance = inst, options = opts }, "自动选择"); // i18n:ignore 桥的协议值（原文比对），不是界面词
        _sync = true;
        _javaOpts = opts;
        _java.Fill(opts.Select(o => o.Label), want);
        _sync = false;
        await ShowInstanceJavaAsync(inst);
    }

    /// <summary>实例名下真正存着的那条 Java 偏好，连同后端给的简称一起显示出来。</summary>
    private async Task ShowInstanceJavaAsync(string inst)
    {
        var stored = await Api.TryCallAsync<string>("get_instance_java", new { name = inst }, "") ?? "";
        var label = await Api.TryCallAsync<string>("instance_java_label", new { name = inst }, "") ?? "";
        _instJava.Text = string.IsNullOrEmpty(stored)
            ? ""
            : L("当前记录：{0}", label) + (stored == label ? "" : L("（{0}）", stored));
    }

    private async Task SaveJavaAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var label = _java.Str();
        var value = _javaOpts.FirstOrDefault(o => o.Label == label)?.Value
                    ?? (string.IsNullOrEmpty(label) ? "自动选择" : label); // i18n:ignore 桥的协议值（原文比对），不是界面词
        await Api.CallAsync<object>("set_instance_java", new { name = inst, java = value });
        await ShowInstanceJavaAsync(inst);
        Toast(L("已保存"), L("「{0}」默认 Java：{1}", inst, label), ToastKind.Success);
    }

    /// <summary>手填路径先过一遍 normalize_java_pref：认得出的写成规范值，认不出的原样留着。</summary>
    private async Task ApplyManualAsync()
    {
        var inst = _inst.Str();
        var raw = _manual.Text?.Trim() ?? "";
        if (string.IsNullOrEmpty(inst) || raw.Length == 0)
        {
            Toast(L("先填路径"), L("填一个 java.exe 的绝对路径"), ToastKind.Warning);
            Motion.Shake(_manual);
            return;
        }
        var normalized = await Api.CallAsync<string>("normalize_java_pref", new { java = raw }) ?? raw;
        if (normalized != raw) Toast(L("已规范化"), $"{raw}\n→ {normalized}");
        await Api.CallAsync<object>("set_instance_java", new { name = inst, java = normalized });
        _manual.Clear();
        await ReloadJavaOptionsAsync();
        Toast(L("已保存"), L("「{0}」默认 Java：{1}", inst, normalized), ToastKind.Success);
    }

    private async Task ReloadListAsync(bool scan)
    {
        _list.Children.Clear();
        _list.Children.Add(Ui.Skeleton(52));
        _list.Children.Add(Ui.Skeleton(52));
        List<JavaInfo> rows;
        if (scan)
        {
            using (Dlg.Busy(L("正在扫描系统 Java…")))
                rows = await Api.TryCallAsync<List<JavaInfo>>("get_java_list",
                    new { scan_system = true }, new()) ?? new();
        }
        else
        {
            rows = await Api.TryCallAsync<List<JavaInfo>>("get_java_list",
                new { scan_system = false }, new()) ?? new();
        }
        _list.Children.Clear();
        _count.Text = L("共 {0} 个", rows.Count);
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Coffee, L("没有找到 Java"), L("点上面「下载」装一个，或扫描系统已有安装")));
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

        var setDef = Ui.Btn(L("设为默认"), BtnKind.Chip, (_, _) => Run(async () =>
        {
            await Api.CallAsync<object>("save_settings", new { data = new { default_java = j.Path } });
            Toast(L("已设为默认"), j.Name, ToastKind.Success);
        }, L("保存失败")));
        var forInst = Ui.Btn(L("给本实例"), BtnKind.Chip, (_, _) => Run(async () =>
        {
            var inst = _inst.Str();
            if (string.IsNullOrEmpty(inst)) return;
            await Api.CallAsync<object>("set_instance_java", new { name = inst, java = j.Path });
            await ReloadJavaOptionsAsync();
            Toast(L("已保存"), L("「{0}」默认 Java：{1}", inst, j.Name), ToastKind.Success);
        }, L("保存失败")));
        var open = Ui.IconBtn(Ico.Folder, L("打开所在目录"), (_, _) => Run(() => OpenFolderAsync(j.Path), L("打开失败")));

        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(badge.M(0, 0, 12, 0), 0, 0);
        g.Add(Ui.V(2, Ui.Txt(j.Name, 13, true).Trim(), Ui.Mono(j.Path).Trim()).VCenter(), 0, 1);
        g.Add(Ui.H(6, setDef, forInst, open).VCenter().M(12, 0, 0, 0), 0, 2);
        return Ui.RowCard(g, padding: 11);
    }

    private async Task OpenFolderAsync(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        // 桥上的 open_media 就是「用系统默认方式打开这个路径」；不通再退回本地 explorer。
        var dir = File.Exists(path) ? Path.GetDirectoryName(path) ?? path : path;
        if (await Api.TryCallAsync<bool>("open_media", new { path = dir })) return;
        try
        {
            if (File.Exists(path)) Process.Start("explorer.exe", $"/select,\"{path}\"");
            else if (Directory.Exists(path)) Process.Start("explorer.exe", $"\"{path}\"");
        }
        catch (Exception ex)
        {
            Toast(L("打开失败"), ex.Message, ToastKind.Warning);
        }
    }

    /// <summary>
    /// 两个下载入口都自带建任务、返回 task_id，进度走下载任务页。
    /// 分工与后端一致：Adoptium 走 download_java 那条专用实现，别家发行版走通用的 install_java。
    /// </summary>
    private async Task DownloadAsync(string major, FrameworkElement anchor)
    {
        var vendor = SelectedVendor();
        if (vendor == "adoptium")
            await Api.StartTaskAsync("download_java", new { major, vendor });
        else
            await Api.StartTaskAsync("install_java", new { major = int.Parse(major), vendor });
        if (SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, "Java " + major);
        Toast(L("已加入队列"), L("正在下载 {0} Java {1}，进度看下载任务", vendor, major));
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
