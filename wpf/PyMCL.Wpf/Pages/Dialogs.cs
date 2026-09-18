using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;
// 这些静态对话框不是 PageBase，但按钮的异步处理器同样走 PageBase.Run：异常兜底 + 冒烟计数，全工程一个口子
using static PyMCL.Pages.PageBase;

namespace PyMCL.Pages;

/// <summary>崩溃分析弹窗。后端给什么修复动作就渲染什么按钮，点了直接调 apply_crash_action。</summary>
public static class CrashUi
{
    public static async Task<bool> ShowAsync(CrashReport report)
    {
        var api = AppServices.Client;
        var relaunch = false;
        var head = string.IsNullOrWhiteSpace(report.Headline) ? report.Title : report.Headline;
        if (string.IsNullOrWhiteSpace(head)) head = L("游戏异常退出");

        var body = Ui.V(12);
        body.MinWidth = 520;
        body.Children.Add(Ui.Txt(head, 15, true).Wrap());
        if (!string.IsNullOrWhiteSpace(report.Summary)) body.Children.Add(Ui.Muted(report.Summary));
        if (report.ExitCode is { } code)
        {
            var hint = string.IsNullOrWhiteSpace(report.ExitHint) ? "" : " · " + report.ExitHint;
            body.Children.Add(Ui.Small(L("退出码 {0}{1}", code, hint)));
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
            b.Click += (_, _) => Run(async () =>
            {
                b.IsEnabled = false;
                try
                {
                    var r = await api.CallAsync<OpResult>("apply_crash_action", new { action = act, report });
                    AppServices.Toast(r?.Ok == true ? L("已处理") : L("没能处理"), r?.Message ?? "", r?.Ok == true ? ToastKind.Success : ToastKind.Warning);
                }
                finally { b.IsEnabled = true; }
            }, L("处理失败"));
            actionRow.Children.Add(b);
        }

        void Extra(string text, string glyph, Func<Task> act)
        {
            var b = Ui.Btn(text, BtnKind.Chip, glyph: glyph);
            b.Margin = new Thickness(0, 0, 7, 7);
            b.Click += (_, _) => Run(act, L("失败"));
            actionRow.Children.Add(b);
        }

        Extra(L("打开日志文件"), Ico.Open, async () =>
        {
            var p = await api.CallAsync<string>("open_crash_file", new { task_id = report.TaskId, path = report.DirectFile });
            AppServices.Toast(L("已打开"), p ?? "", ToastKind.Success);
        });
        Extra(L("导出报告"), Ico.Export, async () =>
        {
            var dest = Dlg.SaveFile(L("文本 (*.txt)|*.txt"), "pymcl-crash.txt", L("导出崩溃报告"));
            if (dest is null) return;
            var p = await api.CallAsync<string>("export_crash_report", new { task_id = report.TaskId, dest });
            AppServices.Toast(L("已导出"), p ?? dest, ToastKind.Success);
        });
        Extra(L("上传给开发者"), Ico.Send, async () =>
        {
            var msg = await api.CallAsync<string>("submit_crash_report", new { task_id = report.TaskId });
            AppServices.Toast(L("已上传"), msg ?? "", ToastKind.Success);
        });
        Extra(L("附说明反馈"), Ico.Chat, async () =>
        {
            // submit_crash_feedback 走的是反馈服务，可以带一段用户自己写的复现步骤，
            // 比只丢一份日志的 submit_crash_report 更容易定位。
            var note = Ui.Multi(L("崩溃前在做什么？装了什么模组？（可空）"), height: 110);
            if (!await Dlg.Ask(L("反馈这次崩溃"), Ui.V(8,
                    Ui.Muted(L("会把崩溃报告连同下面这段说明发给开发者，不含账号密码。")), note), L("发送"))) return;
            var r = await api.CallAsync<OpResult>("submit_crash_feedback",
                new { report, extra = note.Text?.Trim() ?? "" });
            AppServices.Toast(r?.Ok == true ? L("已反馈") : L("反馈失败"), r?.Message ?? "",
                r?.Ok == true ? ToastKind.Success : ToastKind.Error);
        });
        Extra(L("复制全文"), Ico.Copy, () =>
        {
            try { Clipboard.SetText($"{head}\n{report.Summary}\n\n{report.Detail}"); AppServices.Toast(L("已复制")); }
            catch { }
            return Task.CompletedTask;
        });

        var pick = await Dlg.Choose(L("启动出问题了"), body, new[] { L("关闭"), L("重新启动") }, 760);
        relaunch = pick == 1;
        return relaunch;
    }
}

/// <summary>单版本设置：隔离、内存、JVM、GC、窗口、直连、启动前后脚本、账号绑定。</summary>
public static class VersionSetupDialog
{
    private static readonly string[] IsoLabels = { L("跟随全局"), L("关闭（共用实例目录）"), L("隔离存档"), L("隔离全部") };
    private static readonly string[] IsoValues = { "", "none", "saves", "all" };
    private static readonly string[] GcLabels = { L("自动"), L("G1（通用）"), L("ZGC（大内存）"), L("Serial（老电脑）"), L("不指定") };
    private static readonly string[] GcValues = { "auto", "g1", "zgc", "serial", "none" };

    public static async Task ShowAsync(string instance, string version)
    {
        var api = AppServices.Client;
        var data = await api.TryCallAsync<VersionSettingsDto>("get_version_settings",
            new { instance, version }, new VersionSettingsDto()) ?? new VersionSettingsDto();
        var accounts = await api.TryCallAsync<List<string>>("get_accounts", null, new()) ?? new();
        accounts.Insert(0, L("（不绑定）"));

        var iso = Ui.Combo(IsoLabels, IsoLabels[Math.Max(0, Array.IndexOf(IsoValues, data.Isolation ?? ""))]);
        var mem = Ui.Input(L("留空则用全局设置"), data.MemoryMb?.ToString() ?? "");
        var jvm = Ui.Input("-XX:+UseG1GC …", data.JvmArgs ?? "");
        var gc = Ui.Combo(GcLabels, GcLabels[Math.Max(0, Array.IndexOf(GcValues, string.IsNullOrEmpty(data.Gc) ? "auto" : data.Gc))]);
        var server = Ui.Input(L("进游戏直连的服务器"), data.Server ?? "");
        var port = Ui.Input("25565", data.Port ?? "");
        var pre = Ui.Input(L("启动前执行的命令"), data.PreLaunch ?? "");
        var preWait = Ui.Check(L("等待启动前命令结束"), data.PreLaunchWait);
        var post = Ui.Input(L("退出后执行的命令"), data.PostLaunch ?? "");
        var title = Ui.Input(L("自定义游戏窗口标题"), data.WindowTitle ?? "");
        var winMode = Ui.Combo(new[] { L("窗口"), L("全屏"), L("最大化") },
            data.WindowMode == "fullscreen" ? L("全屏") : data.WindowMode == "maximized" ? L("最大化") : L("窗口"));
        var acc = Ui.Combo(accounts, string.IsNullOrEmpty(data.LoginAccount) ? L("（不绑定）") : data.LoginAccount);
        var nide8 = Ui.Input(L("统一通行证 ServerId（可空）"), data.Nide8Id ?? "");
        var hidden = Ui.Check(L("在版本列表中隐藏"), data.Hidden);

        var body = Ui.Scroll(Ui.V(4,
            Ui.Field(L("版本隔离"), iso, L("存档/配置是否与实例其它版本分开")),
            Ui.Field(L("独占内存"), mem, L("单位 MB")),
            Ui.Field(L("JVM 参数"), jvm),
            Ui.Field(L("垃圾回收器"), gc),
            Ui.Field(L("直连服务器"), server),
            Ui.Field(L("端口"), port),
            Ui.Field(L("启动前命令"), pre),
            Ui.Field("", preWait),
            Ui.Field(L("退出后命令"), post),
            Ui.Field(L("窗口标题"), title),
            Ui.Field(L("窗口模式"), winMode),
            Ui.Field(L("绑定账号"), acc, L("启动这个版本时强制用该账号")),
            Ui.Field(L("统一通行证"), nide8),
            Ui.Field("", hidden)));
        body.MaxHeight = 460;
        body.MinWidth = 560;

        var save = await Dlg.Ask(L("版本设置 · ") + version, body, L("保存"));
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
            AppServices.Toast(L("已保存"), L("版本设置已写入"), ToastKind.Success);
        }
        catch (Exception ex) { AppServices.Toast(L("保存失败"), ex.Message, ToastKind.Error); }
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
            if (saves.Count == 0) list.Children.Add(Ui.Empty(Ico.Save, L("这个版本还没有存档"), L("进游戏创建世界后会出现在这里")));
            foreach (var s in saves)
            {
                var name = s.Name;
                var info = Ui.V(2,
                    Ui.Txt(name, 13, true).Trim(),
                    Ui.Small(string.Join(" · ", new[] { s.Size, s.LastPlayed, s.Mode }.Where(x => !string.IsNullOrWhiteSpace(x)))));
                var ops = Ui.H(6,
                    Ui.Btn(L("备份"), BtnKind.Chip, (_, _) => Run(async () =>
                    {
                        await api.StartTaskAsync("backup_save", new { instance, name, version });
                        AppServices.Toast(L("已开始备份"), name);
                    }, L("备份失败"))),
                    Ui.Btn(L("导出"), BtnKind.Chip, (_, _) => Run(async () =>
                    {
                        var dest = Dlg.SaveFile(L("压缩包 (*.zip)|*.zip"), name + ".zip", L("导出存档"));
                        if (dest is null) return;
                        await api.CallAsync("export_save", new { instance, name, dest, version });
                        AppServices.Toast(L("已导出"), dest, ToastKind.Success);
                    }, L("导出失败"))),
                    Ui.Btn(L("打开"), BtnKind.Chip, (_, _) => Run(() => api.CallAsync("open_save", new { instance, name, version }))),
                    Ui.Btn(L("装数据包"), BtnKind.Chip, (_, _) => Run(() => InstallDatapackAsync(instance, version, name), L("安装失败"))),
                    Ui.Btn(L("删除"), BtnKind.Danger, (_, _) => Run(async () =>
                    {
                        if (!await Dlg.Confirm(L("删除存档"), L("「{0}」会被永久删除，其中的建筑与进度都无法恢复。", name),
                                L("永久删除"), L("取消"), true)) return;
                        await api.CallAsync("delete_save", new { instance, name, version });
                        await Reload();
                    }, L("删除失败"))));
                var g = Ui.G(null, "*,Auto");
                g.Add(info.VCenter(), 0, 0);
                g.Add(ops.VCenter(), 0, 1);
                list.Children.Add(Ui.RowCard(g));
            }
            Motion.Stagger(list);

            var rows = await api.TryCallAsync<List<BackupRow>>("list_save_backups", new { instance, version }, new()) ?? new();
            backups.Children.Add(Ui.Txt(L("备份（{0}）", rows.Count), 12.5, true));
            foreach (var b in rows.Take(20))
            {
                var bn = b.Name;
                var g = Ui.G(null, "*,Auto");
                g.Add(Ui.V(1, Ui.Txt(bn, 12).Trim(), Ui.Small($"{b.Size} · {b.Date}")).VCenter(), 0, 0);
                g.Add(Ui.H(6,
                    Ui.Btn(L("还原"), BtnKind.Chip, (_, _) => Run(async () =>
                    {
                        if (!await Dlg.Confirm(L("还原备份"), L("用「{0}」覆盖现有存档？", bn), L("还原"))) return;
                        await api.CallAsync("restore_save_backup", new { instance, backup_name = bn, version, overwrite = true });
                        AppServices.Toast(L("已还原"), bn, ToastKind.Success);
                        await Reload();
                    }, L("还原失败"))),
                    Ui.Btn(L("删除"), BtnKind.Ghost, (_, _) => Run(async () =>
                    {
                        await api.CallAsync("delete_save_backup", new { instance, backup_name = bn, version });
                        await Reload();
                    }, L("删除失败")))).VCenter(), 0, 1);
                backups.Children.Add(g);
            }
        }

        var media = Ui.V(6);
        var mediaScroll = Ui.Scroll(media);
        mediaScroll.MaxHeight = 170;
        var kind = Ui.Combo(new[] { L("截图"), L("崩溃报告"), L("日志") }, width: 130);
        var mediaCount = Ui.Small("");

        async Task ReloadMedia()
        {
            media.Children.Clear();
            var picked = kind.Str();
            var key = picked == L("崩溃报告") ? "crash-reports" : picked == L("日志") ? "logs" : "screenshots";
            var rows = await api.TryCallAsync<List<MediaRow>>("list_media",
                new { instance, kind = key, version }, new()) ?? new();
            mediaCount.Text = L("{0} 个文件", rows.Count);
            if (rows.Count == 0)
            {
                media.Children.Add(Ui.Muted(L("这个目录还是空的")));
                return;
            }
            foreach (var m in rows.Take(60))
            {
                var path = m.Path;
                var g = Ui.G(null, "*,Auto,Auto");
                g.Add(Ui.V(1, Ui.Txt(m.Name, 12.5).Trim(), Ui.Small(Fmt.Size(m.Bytes))).VCenter(), 0, 0);
                g.Add(Ui.Btn(L("打开"), BtnKind.Chip, (_, _) =>
                    Run(() => api.TryCallAsync<bool>("open_media", new { path }))).VCenter(), 0, 1);
                g.Add(Ui.Btn(L("导出"), BtnKind.Ghost, (_, _) =>
                {
                    var dest = Dlg.SaveFile(L("全部文件|*.*"), m.Name, L("导出文件"));
                    if (dest is null) return;
                    try
                    {
                        System.IO.File.Copy(path, dest, true);
                        AppServices.Toast(L("已导出"), dest, ToastKind.Success);
                    }
                    catch (Exception ex) { AppServices.Toast(L("导出失败"), ex.Message, ToastKind.Error); }
                }).VCenter().M(6, 0, 0, 0), 0, 2);
                media.Children.Add(g);
            }
        }

        kind.SelectionChanged += (_, _) => Run(ReloadMedia, L("读取失败"));

        var mediaHead = Ui.G(null, "Auto,Auto,*");
        mediaHead.Add(Ui.Txt(L("截图 / 日志"), 12.5, true).VCenter(), 0, 0);
        mediaHead.Add(kind.M(10, 0, 10, 0).VCenter(), 0, 1);
        mediaHead.Add(mediaCount.VCenter(), 0, 2);

        var body = Ui.V(12, scroll, Ui.Sep(), backScroll, Ui.Sep(), mediaHead, mediaScroll);
        layer = Dlg.Panel(L("存档管理 · {0}", instance) + (string.IsNullOrEmpty(version) ? "" : " / " + version), body, 780);
        await Reload();
        await ReloadMedia();
    }

    /// <summary>
    /// 世界 / 存档的安装去处：共享 saves，加上开了存档隔离的各版本目录。
    /// 走桥上的 get_saves_targets，跟 mods 那边的 get_mods_targets 是同一套形状。
    /// </summary>
    public static async Task<string?> PickSaveTargetAsync(string instance, string title)
    {
        var api = AppServices.Client;
        var rows = await api.TryCallAsync<List<ModsTarget>>("get_saves_targets", new { instance }, new()) ?? new();
        if (rows.Count <= 1) return rows.Count == 1 ? rows[0].Value : "";
        var pick = Ui.Combo(rows.Select(r => r.Label));
        if (!await Dlg.Ask(title, Ui.V(8, Ui.Muted(L("装进哪个版本的存档目录？")), pick), L("继续"))) return null;
        var idx = Math.Max(0, pick.SelectedIndex);
        return idx < rows.Count ? rows[idx].Value : "";
    }

    /// <summary>把已装的数据包塞进某个存档的 datapacks 目录，对齐 Qt 的「装进存档」。</summary>
    private static async Task InstallDatapackAsync(string instance, string version, string save)
    {
        var api = AppServices.Client;
        var packs = await api.TryCallAsync<List<string>>("get_installed_datapacks", new { instance }, new()) ?? new();
        if (packs.Count == 0)
        {
            await Dlg.Alert(L("没有数据包"), L("先到「数据包」页装一个，再回来装进存档。"));
            return;
        }
        var pick = Ui.Combo(packs);
        if (!await Dlg.Ask(L("装进存档 · {0}", save), Ui.V(8, Ui.Muted(L("选择要装进这个世界的数据包")), pick), L("安装"))) return;
        var msg = await api.CallAsync<string>("install_datapack_into_save", new
        {
            instance, filename = pick.Str(), save_name = save, version,
        });
        AppServices.Toast(L("已安装"), string.IsNullOrWhiteSpace(msg) ? pick.Str() : msg, ToastKind.Success);
    }
}

/// <summary>实例模组管理：目标目录、启用 / 禁用 / 删除 / 更新 / 本地导入。</summary>
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
        var target = Ui.Combo(width: 230);
        var targets = new List<ModsTarget>();
        var sync = false;

        // 当前生效的 mods 目录：实例共享那一份，或某个开了 mods 隔离的版本。
        string CurrentVersion()
        {
            var idx = target.SelectedIndex;
            return idx >= 0 && idx < targets.Count ? targets[idx].Value : version;
        }

        async Task Reload()
        {
            var ver = CurrentVersion();
            list.Children.Clear();
            var entries = await api.TryCallAsync<List<ModEntry>>("get_installed_mod_entries",
                new { instance, version = ver }, new()) ?? new();
            count.Text = L("共 {0} 个模组", entries.Count);
            if (entries.Count == 0) list.Children.Add(Ui.Empty(Ico.Puzzle, L("还没有模组"), L("到 Mod 页搜索安装，或直接导入 jar")));
            foreach (var m in entries)
            {
                var file = m.Filename;
                var sw = Ui.Switch(m.Enabled);
                sw.Checked += (_, _) => Run(() => api.TryCallAsync<object>("enable_mod", new { instance, filename = file, version = ver }));
                sw.Unchecked += (_, _) => Run(() => api.TryCallAsync<object>("disable_mod", new { instance, filename = file, version = ver }));
                var g = Ui.G(null, "Auto,*,Auto");
                g.Add(sw.M(0, 0, 12, 0).VCenter(), 0, 0);
                g.Add(Ui.V(1,
                    Ui.Txt(string.IsNullOrWhiteSpace(m.Name) ? file : m.Name, 13).Trim(),
                    Ui.Small(file)).VCenter(), 0, 1);
                g.Add(Ui.Btn(L("删除"), BtnKind.Ghost, (_, _) => Run(async () =>
                {
                    if (!await Dlg.Confirm(L("删除模组"), file, L("删除"), L("取消"), true)) return;
                    await api.CallAsync("delete_mod", new { instance, filename = file, version = ver });
                    await Reload();
                }, L("删除失败"))).VCenter(), 0, 2);
                list.Children.Add(Ui.RowCard(g, padding: 10));
            }
            Motion.Stagger(list, 16);
        }

        async Task ReloadTargets()
        {
            targets = await api.TryCallAsync<List<ModsTarget>>("get_mods_targets", new { instance }, new()) ?? new();
            if (targets.Count == 0) targets.Add(new ModsTarget { Label = L("实例共享 mods 目录"), Value = "" });
            sync = true;
            var keep = Math.Max(0, targets.FindIndex(t => t.Value == version));
            target.Items.Clear();
            foreach (var t in targets) target.Items.Add(t.Label);
            target.SelectedIndex = keep;
            sync = false;
            await Reload();
        }

        target.SelectionChanged += (_, _) => { if (!sync) Run(Reload, L("读取失败")); };

        var tools = Ui.H(8,
            Ui.Btn(L("导入 jar"), BtnKind.Soft, (_, _) => Run(async () =>
            {
                var files = Dlg.PickFiles(L("模组 (*.jar)|*.jar"), L("导入模组"));
                if (files is null) return;
                foreach (var f in files)
                    await api.StartTaskAsync("install_mod", new
                    {
                        name = System.IO.Path.GetFileName(f),
                        instance,
                        extra = new { path = f, instance, name = System.IO.Path.GetFileName(f) },
                    });
                AppServices.Toast(L("已加入队列"), L("{0} 个模组", files.Length));
            }, L("导入失败")), Ico.Import),
            Ui.Btn(L("检查更新"), BtnKind.Chip, (_, _) => Run(async () =>
            {
                await CheckUpdatesAsync(instance);
                await Reload();
            }, L("检查更新失败")), Ico.Refresh),
            Ui.Btn(L("打开目录"), BtnKind.Chip, (_, _) => Run(async () =>
            {
                var folder = await api.CallAsync<string>("open_mods_folder",
                    new { instance, version = CurrentVersion() });
                AppServices.Toast(L("已打开"), folder ?? "", ToastKind.Success);
            }), Ico.Folder),
            Ui.Btn(L("全局模组"), BtnKind.Chip, (_, _) => Run(GlobalModsDialog.ShowAsync), Ico.Grid),
            Ui.Btn(L("刷新"), BtnKind.Chip, (_, _) => Run(Reload, L("读取失败")), Ico.Refresh));

        var head = Ui.G(null, "Auto,Auto,*");
        head.Add(Ui.Txt(L("目标"), 12, fg: "B.InkMuted").VCenter(), 0, 0);
        head.Add(target.M(8, 0, 12, 0).VCenter(), 0, 1);
        head.Add(count.VCenter(), 0, 2);
        Dlg.Panel(L("模组管理 · {0}", instance), Ui.V(12, head, tools, scroll), 800);
        await ReloadTargets();
    }

    /// <summary>
    /// 联网比对每个已装模组的最新版本，逐条挑着更新。
    /// 扫描要逐个 jar 算 sha1 再查 Modrinth / CurseForge，必须在忙碌遮罩后面等，不能占着 UI 线程。
    /// </summary>
    public static async Task CheckUpdatesAsync(string instance)
    {
        var api = AppServices.Client;
        List<ModUpdateRow> rows;
        using (Dlg.Busy(L("正在比对模组版本…")))
            rows = await api.TryCallAsync<List<ModUpdateRow>>("check_mod_updates", new { instance }, new()) ?? new();

        if (rows.Count == 0)
        {
            AppServices.Toast(L("都是最新的"), L("没有找到可更新的模组"), ToastKind.Success);
            return;
        }

        var host = Ui.V(6);
        var scroll = Ui.Scroll(host);
        scroll.MaxHeight = 360;
        scroll.MinWidth = 600;
        var picks = new List<(CheckBox Box, ModUpdateRow Row)>();
        foreach (var r in rows)
        {
            var box = Ui.Check("", true);
            var g = Ui.G(null, "Auto,*,Auto");
            g.Add(box.M(0, 0, 10, 0).VCenter(), 0, 0);
            g.Add(Ui.V(1,
                Ui.Txt(string.IsNullOrWhiteSpace(r.Name) ? r.Filename : r.Name, 13, true).Trim(),
                Ui.Small($"{r.Current} → {r.Latest}  ·  {r.Source}  ·  {Fmt.Size(r.Size)}").Wrap()).VCenter(), 0, 1);
            g.Add(Ui.Tag(string.IsNullOrWhiteSpace(r.McVersion) ? "—" : r.McVersion).VCenter(), 0, 2);
            host.Children.Add(Ui.RowCard(g, padding: 10));
            picks.Add((box, r));
        }

        if (!await Dlg.Ask(L("{0} 个模组有更新", rows.Count),
                Ui.V(10, Ui.Muted(L("勾上要更新的，旧文件会在新包校验通过后才删除。")), scroll), L("更新所选"))) return;

        var want = picks.Where(p => p.Box.IsChecked == true).Select(p => p.Row).ToList();
        if (want.Count == 0) return;

        var done = 0;
        var failed = new List<string>();
        using (Dlg.Busy(L("正在更新 {0} 个模组…", want.Count)))
            foreach (var row in want)
            {
                try
                {
                    await api.CallAsync<string>("apply_mod_update", new { instance, row });
                    done++;
                }
                catch (Exception ex) { failed.Add(L("{0}：{1}", row.Filename, ex.Message)); }
            }

        if (failed.Count == 0) AppServices.Toast(L("已更新"), L("{0} 个模组", done), ToastKind.Success);
        else await Dlg.Alert(L("部分模组没能更新"), L("成功 {0} 个，失败 {1} 个：\n\n", done, failed.Count) + string.Join("\n", failed));
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
                list.Children.Add(Ui.Empty(Ico.Grid, L("全局模组目录是空的"), L("放进去的模组会自动注入每个实例")));
            foreach (var r in rows)
            {
                var file = r.Filename;
                var sw = Ui.Switch(r.Enabled);
                sw.Checked += (_, _) => Run(() => api.TryCallAsync<object>("set_global_mod_enabled", new { filename = file, enabled = true }));
                sw.Unchecked += (_, _) => Run(() => api.TryCallAsync<object>("set_global_mod_enabled", new { filename = file, enabled = false }));
                var g = Ui.G(null, "Auto,*,Auto");
                g.Add(sw.M(0, 0, 12, 0).VCenter(), 0, 0);
                g.Add(Ui.Txt(file, 12.5).Trim().VCenter(), 0, 1);
                g.Add(Ui.Small(r.Size).VCenter(), 0, 2);
                list.Children.Add(Ui.RowCard(g, padding: 9));
            }
        }

        var open = Ui.Btn(L("打开目录"), BtnKind.Soft, (_, _) => Run(() => api.CallAsync("open_global_mods")), Ico.Folder);
        var refresh = Ui.Btn(L("刷新"), BtnKind.Chip, (_, _) => Run(Reload, L("读取失败")), Ico.Refresh);
        Dlg.Panel(L("全局模组"), Ui.V(12, Ui.H(8, open, refresh), scroll), 620);
        await Reload();
    }
}
