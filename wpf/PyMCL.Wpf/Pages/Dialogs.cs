using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>崩溃分析弹窗。后端给什么修复动作就渲染什么按钮，点了直接调 apply_crash_action。</summary>
public static class CrashUi
{
    public static async Task<bool> ShowAsync(CrashReport report)
    {
        var api = AppServices.Client;
        var relaunch = false;
        var head = string.IsNullOrWhiteSpace(report.Headline) ? report.Title : report.Headline;
        if (string.IsNullOrWhiteSpace(head)) head = "游戏异常退出";

        var body = Ui.V(12);
        body.MinWidth = 520;
        body.Children.Add(Ui.Txt(head, 15, true).Wrap());
        if (!string.IsNullOrWhiteSpace(report.Summary)) body.Children.Add(Ui.Muted(report.Summary));
        if (report.ExitCode is { } code)
        {
            var hint = string.IsNullOrWhiteSpace(report.ExitHint) ? "" : " · " + report.ExitHint;
            body.Children.Add(Ui.Small($"退出码 {code}{hint}"));
        }
        if (!string.IsNullOrWhiteSpace(report.Help)) body.Children.Add(Ui.Muted(report.Help));

        if (!string.IsNullOrWhiteSpace(report.Detail))
        {
            var detail = new TextBox
            {
                Style = Ui.S("Input.Log"),
                Text = report.Detail,
                Height = 190,
                TextWrapping = TextWrapping.Wrap,
            };
            body.Children.Add(detail);
        }

        var actionRow = new WrapPanel();
        body.Children.Add(actionRow);

        foreach (var act in report.Actions ?? new List<CrashAction>())
        {
            var b = Ui.Btn(act.Label, BtnKind.Soft);
            b.Margin = new Thickness(0, 0, 7, 7);
            b.Click += async (_, _) =>
            {
                b.IsEnabled = false;
                try
                {
                    var r = await api.CallAsync<OpResult>("apply_crash_action", new { action = act, report });
                    AppServices.Toast(r?.Ok == true ? "已处理" : "没能处理", r?.Message ?? "", r?.Ok == true ? ToastKind.Success : ToastKind.Warning);
                }
                catch (Exception ex) { AppServices.Toast("处理失败", ex.Message, ToastKind.Error); }
                finally { b.IsEnabled = true; }
            };
            actionRow.Children.Add(b);
        }

        void Extra(string text, string glyph, Func<Task> act)
        {
            var b = Ui.Btn(text, BtnKind.Chip, glyph: glyph);
            b.Margin = new Thickness(0, 0, 7, 7);
            b.Click += async (_, _) =>
            {
                try { await act(); }
                catch (Exception ex) { AppServices.Toast("失败", ex.Message, ToastKind.Error); }
            };
            actionRow.Children.Add(b);
        }

        Extra("打开日志文件", Ico.Open, async () =>
        {
            var p = await api.CallAsync<string>("open_crash_file", new { task_id = report.TaskId, path = report.DirectFile });
            AppServices.Toast("已打开", p ?? "", ToastKind.Success);
        });
        Extra("导出报告", Ico.Export, async () =>
        {
            var dest = Dlg.SaveFile("文本 (*.txt)|*.txt", "pymcl-crash.txt", "导出崩溃报告");
            if (dest is null) return;
            var p = await api.CallAsync<string>("export_crash_report", new { task_id = report.TaskId, dest });
            AppServices.Toast("已导出", p ?? dest, ToastKind.Success);
        });
        Extra("上传给开发者", Ico.Send, async () =>
        {
            var msg = await api.CallAsync<string>("submit_crash_report", new { task_id = report.TaskId });
            AppServices.Toast("已上传", msg ?? "", ToastKind.Success);
        });
        Extra("复制全文", Ico.Copy, () =>
        {
            try { Clipboard.SetText($"{head}\n{report.Summary}\n\n{report.Detail}"); AppServices.Toast("已复制"); }
            catch { }
            return Task.CompletedTask;
        });

        var pick = await Dlg.Choose("启动出问题了", body, new[] { "关闭", "重新启动" }, 760);
        relaunch = pick == 1;
        return relaunch;
    }
}

/// <summary>单版本设置：隔离、内存、JVM、GC、窗口、直连、启动前后脚本、账号绑定。</summary>
public static class VersionSetupDialog
{
    private static readonly string[] IsoLabels = { "跟随全局", "关闭（共用实例目录）", "隔离存档", "隔离全部" };
    private static readonly string[] IsoValues = { "", "none", "saves", "all" };
    private static readonly string[] GcLabels = { "自动", "G1（通用）", "ZGC（大内存）", "Serial（老电脑）", "不指定" };
    private static readonly string[] GcValues = { "auto", "g1", "zgc", "serial", "none" };

    public static async Task ShowAsync(string instance, string version)
    {
        var api = AppServices.Client;
        var data = await api.TryCallAsync<VersionSettingsDto>("get_version_settings",
            new { instance, version }, new VersionSettingsDto()) ?? new VersionSettingsDto();
        var accounts = await api.TryCallAsync<List<string>>("get_accounts", null, new()) ?? new();
        accounts.Insert(0, "（不绑定）");

        var iso = Ui.Combo(IsoLabels, IsoLabels[Math.Max(0, Array.IndexOf(IsoValues, data.Isolation ?? ""))]);
        var mem = Ui.Input("留空则用全局设置", data.MemoryMb?.ToString() ?? "");
        var jvm = Ui.Input("-XX:+UseG1GC …", data.JvmArgs ?? "");
        var gc = Ui.Combo(GcLabels, GcLabels[Math.Max(0, Array.IndexOf(GcValues, string.IsNullOrEmpty(data.Gc) ? "auto" : data.Gc))]);
        var server = Ui.Input("进游戏直连的服务器", data.Server ?? "");
        var port = Ui.Input("25565", data.Port ?? "");
        var pre = Ui.Input("启动前执行的命令", data.PreLaunch ?? "");
        var preWait = Ui.Check("等待启动前命令结束", data.PreLaunchWait);
        var post = Ui.Input("退出后执行的命令", data.PostLaunch ?? "");
        var title = Ui.Input("自定义游戏窗口标题", data.WindowTitle ?? "");
        var winMode = Ui.Combo(new[] { "窗口", "全屏", "最大化" },
            data.WindowMode == "fullscreen" ? "全屏" : data.WindowMode == "maximized" ? "最大化" : "窗口");
        var acc = Ui.Combo(accounts, string.IsNullOrEmpty(data.LoginAccount) ? "（不绑定）" : data.LoginAccount);
        var nide8 = Ui.Input("统一通行证 ServerId（可空）", data.Nide8Id ?? "");
        var hidden = Ui.Check("在版本列表中隐藏", data.Hidden);

        var body = Ui.Scroll(Ui.V(4,
            Ui.Field("版本隔离", iso, "存档/配置是否与实例其它版本分开"),
            Ui.Field("独占内存", mem, "单位 MB"),
            Ui.Field("JVM 参数", jvm),
            Ui.Field("垃圾回收器", gc),
            Ui.Field("直连服务器", server),
            Ui.Field("端口", port),
            Ui.Field("启动前命令", pre),
            Ui.Field("", preWait),
            Ui.Field("退出后命令", post),
            Ui.Field("窗口标题", title),
            Ui.Field("窗口模式", winMode),
            Ui.Field("绑定账号", acc, "启动这个版本时强制用该账号"),
            Ui.Field("统一通行证", nide8),
            Ui.Field("", hidden)));
        body.MaxHeight = 460;
        body.MinWidth = 560;

        var save = await Dlg.Ask("版本设置 · " + version, body, "保存");
        if (!save) return;

        var payload = new Dictionary<string, object?>
        {
            ["isolation"] = IsoValues[Math.Max(0, iso.SelectedIndex)],
            ["jvm_args"] = jvm.Text ?? "",
            ["gc"] = GcValues[Math.Max(0, gc.SelectedIndex)],
            ["server"] = server.Text ?? "",
            ["port"] = port.Text ?? "",
            ["pre_launch"] = pre.Text ?? "",
            ["pre_launch_wait"] = preWait.IsChecked == true,
            ["post_launch"] = post.Text ?? "",
            ["window_title"] = title.Text ?? "",
            ["window_mode"] = winMode.SelectedIndex switch { 1 => "fullscreen", 2 => "maximized", _ => "window" },
            ["login_account"] = acc.SelectedIndex <= 0 ? "" : acc.Str(),
            ["nide8_id"] = nide8.Text ?? "",
            ["hidden"] = hidden.IsChecked == true,
        };
        if (int.TryParse(mem.Text?.Trim(), out var mb) && mb > 0) payload["memory_mb"] = mb;
        else payload["memory_mb"] = null;

        try
        {
            await api.CallAsync("save_version_settings", new { instance, version, data = payload });
            AppServices.Toast("已保存", "版本设置已写入", ToastKind.Success);
        }
        catch (Exception ex) { AppServices.Toast("保存失败", ex.Message, ToastKind.Error); }
    }
}

/// <summary>存档管理：备份 / 还原 / 导出 / 删除 / 打开。</summary>
public static class SavesDialog
{
    public static async Task ShowAsync(string instance, string version)
    {
        var api = AppServices.Client;
        var list = Ui.V(8);
        var backups = Ui.V(6);
        var scroll = Ui.Scroll(list);
        scroll.MaxHeight = 320;
        scroll.MinWidth = 620;
        var backScroll = Ui.Scroll(backups);
        backScroll.MaxHeight = 150;

        Dlg.Layer? layer = null;

        async Task Reload()
        {
            list.Children.Clear();
            backups.Children.Clear();
            var saves = await api.TryCallAsync<List<SaveRow>>("list_saves", new { instance, version }, new()) ?? new();
            if (saves.Count == 0) list.Children.Add(Ui.Empty(Ico.Save, "这个版本还没有存档", "进游戏创建世界后会出现在这里"));
            foreach (var s in saves)
            {
                var name = s.Name;
                var info = Ui.V(2,
                    Ui.Txt(name, 13, true).Trim(),
                    Ui.Small(string.Join(" · ", new[] { s.Size, s.LastPlayed, s.Mode }.Where(x => !string.IsNullOrWhiteSpace(x)))));
                var ops = Ui.H(6,
                    Ui.Btn("备份", BtnKind.Chip, async (_, _) =>
                    {
                        await api.StartTaskAsync("backup_save", new { instance, name, version });
                        AppServices.Toast("已开始备份", name);
                    }),
                    Ui.Btn("导出", BtnKind.Chip, async (_, _) =>
                    {
                        var dest = Dlg.SaveFile("压缩包 (*.zip)|*.zip", name + ".zip", "导出存档");
                        if (dest is null) return;
                        await api.CallAsync("export_save", new { instance, name, dest, version });
                        AppServices.Toast("已导出", dest, ToastKind.Success);
                    }),
                    Ui.Btn("打开", BtnKind.Chip, async (_, _) => await api.CallAsync("open_save", new { instance, name, version })),
                    Ui.Btn("删除", BtnKind.Danger, async (_, _) =>
                    {
                        if (!await Dlg.Confirm("删除存档", $"「{name}」会被永久删除。", "删除", "取消", true)) return;
                        await api.CallAsync("delete_save", new { instance, name, version });
                        await Reload();
                    }));
                var g = Ui.G(null, "*,Auto");
                g.Add(info.VCenter(), 0, 0);
                g.Add(ops.VCenter(), 0, 1);
                list.Children.Add(Ui.RowCard(g));
            }
            Motion.Stagger(list);

            var rows = await api.TryCallAsync<List<BackupRow>>("list_save_backups", new { instance, version }, new()) ?? new();
            backups.Children.Add(Ui.Txt($"备份（{rows.Count}）", 12.5, true));
            foreach (var b in rows.Take(20))
            {
                var bn = b.Name;
                var g = Ui.G(null, "*,Auto");
                g.Add(Ui.V(1, Ui.Txt(bn, 12).Trim(), Ui.Small($"{b.Size} · {b.Date}")).VCenter(), 0, 0);
                g.Add(Ui.H(6,
                    Ui.Btn("还原", BtnKind.Chip, async (_, _) =>
                    {
                        if (!await Dlg.Confirm("还原备份", $"用「{bn}」覆盖现有存档？", "还原")) return;
                        await api.CallAsync("restore_save_backup", new { instance, backup_name = bn, version, overwrite = true });
                        AppServices.Toast("已还原", bn, ToastKind.Success);
                        await Reload();
                    }),
                    Ui.Btn("删除", BtnKind.Ghost, async (_, _) =>
                    {
                        await api.CallAsync("delete_save_backup", new { instance, backup_name = bn, version });
                        await Reload();
                    })).VCenter(), 0, 1);
                backups.Children.Add(g);
            }
        }

        var body = Ui.V(12, scroll, Ui.Sep(), backScroll);
        layer = Dlg.Panel($"存档管理 · {instance}" + (string.IsNullOrEmpty(version) ? "" : " / " + version), body, 780);
        await Reload();
    }
}

/// <summary>实例模组管理：启用 / 禁用 / 删除 / 更新 / 本地导入。</summary>
public static class ModsDialog
{
    public static async Task ShowAsync(string instance, string version = "")
    {
        var api = AppServices.Client;
        var list = Ui.V(6);
        var scroll = Ui.Scroll(list);
        scroll.MaxHeight = 400;
        scroll.MinWidth = 620;
        var count = Ui.Muted("");

        async Task Reload()
        {
            list.Children.Clear();
            var entries = await api.TryCallAsync<List<ModEntry>>("get_installed_mod_entries",
                new { instance, version }, new()) ?? new();
            count.Text = $"共 {entries.Count} 个模组";
            if (entries.Count == 0) list.Children.Add(Ui.Empty(Ico.Puzzle, "还没有模组", "到 Mod 页搜索安装，或直接导入 jar"));
            foreach (var m in entries)
            {
                var file = m.Filename;
                var sw = Ui.Switch(m.Enabled);
                sw.Checked += async (_, _) => await api.TryCallAsync<object>("enable_mod", new { instance, filename = file, version });
                sw.Unchecked += async (_, _) => await api.TryCallAsync<object>("disable_mod", new { instance, filename = file, version });
                var g = Ui.G(null, "Auto,*,Auto");
                g.Add(sw.M(0, 0, 12, 0).VCenter(), 0, 0);
                g.Add(Ui.V(1,
                    Ui.Txt(string.IsNullOrWhiteSpace(m.Name) ? file : m.Name, 13).Trim(),
                    Ui.Small(file)).VCenter(), 0, 1);
                g.Add(Ui.Btn("删除", BtnKind.Ghost, async (_, _) =>
                {
                    if (!await Dlg.Confirm("删除模组", file, "删除", "取消", true)) return;
                    await api.CallAsync("delete_mod", new { instance, filename = file, version });
                    await Reload();
                }).VCenter(), 0, 2);
                list.Children.Add(Ui.RowCard(g, padding: 10));
            }
            Motion.Stagger(list, 16);
        }

        var tools = Ui.H(8,
            Ui.Btn("导入 jar", BtnKind.Soft, async (_, _) =>
            {
                var files = Dlg.PickFiles("模组 (*.jar)|*.jar", "导入模组");
                if (files is null) return;
                foreach (var f in files)
                    await api.StartTaskAsync("install_mod", new
                    {
                        name = System.IO.Path.GetFileName(f),
                        instance,
                        extra = new { path = f, instance, name = System.IO.Path.GetFileName(f) },
                    });
                AppServices.Toast("已加入队列", $"{files.Length} 个模组");
            }, Ico.Import),
            Ui.Btn("检查更新", BtnKind.Chip, async (_, _) =>
            {
                await api.StartTaskAsync("start_mod_updates", new { instance });
                AppServices.Toast("已开始检查模组更新", instance);
            }, Ico.Refresh),
            Ui.Btn("全局模组", BtnKind.Chip, async (_, _) => await GlobalModsDialog.ShowAsync(), Ico.Grid),
            Ui.Btn("刷新", BtnKind.Chip, async (_, _) => await Reload(), Ico.Refresh));

        var head = Ui.G(null, "*,Auto");
        head.Add(count.VCenter(), 0, 0);
        head.Add(tools, 0, 1);
        Dlg.Panel($"模组管理 · {instance}", Ui.V(12, head, scroll), 800);
        await Reload();
    }
}

public static class GlobalModsDialog
{
    public static async Task ShowAsync()
    {
        var api = AppServices.Client;
        var list = Ui.V(6);
        var scroll = Ui.Scroll(list);
        scroll.MaxHeight = 380;
        scroll.MinWidth = 520;

        async Task Reload()
        {
            list.Children.Clear();
            var rows = await api.TryCallAsync<List<GlobalModRow>>("list_global_mods", null, new()) ?? new();
            if (rows.Count == 0)
                list.Children.Add(Ui.Empty(Ico.Grid, "全局模组目录是空的", "放进去的模组会自动注入每个实例"));
            foreach (var r in rows)
            {
                var file = r.Filename;
                var sw = Ui.Switch(r.Enabled);
                sw.Checked += async (_, _) => await api.TryCallAsync<object>("set_global_mod_enabled", new { filename = file, enabled = true });
                sw.Unchecked += async (_, _) => await api.TryCallAsync<object>("set_global_mod_enabled", new { filename = file, enabled = false });
                var g = Ui.G(null, "Auto,*,Auto");
                g.Add(sw.M(0, 0, 12, 0).VCenter(), 0, 0);
                g.Add(Ui.Txt(file, 12.5).Trim().VCenter(), 0, 1);
                g.Add(Ui.Small(r.Size).VCenter(), 0, 2);
                list.Children.Add(Ui.RowCard(g, padding: 9));
            }
        }

        var open = Ui.Btn("打开目录", BtnKind.Soft, async (_, _) => await api.CallAsync("open_global_mods"), Ico.Folder);
        var refresh = Ui.Btn("刷新", BtnKind.Chip, async (_, _) => await Reload(), Ico.Refresh);
        Dlg.Panel("全局模组", Ui.V(12, Ui.H(8, open, refresh), scroll), 620);
        await Reload();
    }
}
