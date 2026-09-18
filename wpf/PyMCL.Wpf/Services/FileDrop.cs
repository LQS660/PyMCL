using System.IO;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Pages;

namespace PyMCL.Services;

/// <summary>
/// 拖进窗口的文件往哪儿放。认类型的活在 FileKinds，这里只负责
/// 「认准了就直接办、拿不准就问一句」以及真正的落地动作，与 Qt 端 file_drop.py 同一套行为。
/// </summary>
public static class FileDrop
{
    /// <summary>走 install_&lt;x&gt;(name, instance, extra) 那一套的类型。</summary>
    private static readonly Dictionary<string, string> Installers = new()
    {
        [FileKinds.Mod] = "install_mod",
        [FileKinds.ResourcePack] = "install_resourcepack",
        [FileKinds.ShaderPack] = "install_shader",
        [FileKinds.DataPack] = "install_datapack",
        [FileKinds.World] = "install_world",
    };

    /// <summary>
    /// 拖到哪个页面上的。落到页面上的文件该用这一页正在操作的实例 / 版本，
    /// 而不是从配置里推一个——在 Mod 页选了实例 A 却把 jar 装进 B，用户是不会原谅的。
    /// </summary>
    public sealed class DropContext
    {
        /// <summary>这一页当前选中的实例；空串表示没有上下文，退回默认实例。</summary>
        public string Instance { get; init; } = "";

        /// <summary>这一页当前选中的版本（用于开了 mods 隔离的版本）。</summary>
        public string Version { get; init; } = "";

        /// <summary>这一页主营什么。只在文件「认不准」且这个类型在候选里时用来免去提问。</summary>
        public string PreferKind { get; init; } = "";

        public static readonly DropContext None = new();
    }

    /// <summary>拖进主窗口的一批文件：认准的直接办，拿不准的问一句再办。</summary>
    public static async Task HandleAsync(MainWindow window, IReadOnlyList<string> paths, DropContext? context = null)
    {
        var ctx = context ?? DropContext.None;
        if (paths.Count == 0) return;
        // 认类型要读 zip 目录、扫文件夹，几十 MB 的包别占着 UI 线程。
        var infos = await Task.Run(() => paths.Where(p => !string.IsNullOrWhiteSpace(p))
            .Select(FileKinds.Identify).ToList());
        if (infos.Count == 0) return;

        var buckets = new Dictionary<string, List<string>>();
        var unsure = new List<FileKinds.Verdict>();
        foreach (var info in infos)
        {
            // 页面主营的类型正好在候选里：这一页就是答案，不用再问
            var kind = info.Sure && info.Kinds.Count == 1
                ? info.Kinds[0]
                : ctx.PreferKind.Length > 0 && info.Kinds.Contains(ctx.PreferKind)
                    ? ctx.PreferKind
                    : "";
            if (kind.Length > 0)
            {
                if (!buckets.TryGetValue(kind, out var list)) buckets[kind] = list = new List<string>();
                list.Add(info.Path);
            }
            else unsure.Add(info);
        }

        if (unsure.Count > 0)
        {
            // 只问一次：剩下候选完全相同的那些照这个答案办，别连弹 N 个框
            var head = unsure[0];
            var same = unsure.Where(i => i.KindSig == head.KindSig).ToList();
            var kind = await AskKindAsync(head, same.Count - 1);
            if (!string.IsNullOrEmpty(kind))
            {
                if (!buckets.TryGetValue(kind, out var list)) buckets[kind] = list = new List<string>();
                list.AddRange(same.Select(i => i.Path));
            }
            var skipped = unsure.Except(same).ToList();
            if (skipped.Count > 0)
                AppServices.Toast(L("有文件没处理"),
                    L("这些认不出来，可以单独拖进来再选：") + string.Join(L("、"), skipped.Take(3).Select(i => i.Name)),
                    ToastKind.Info);
        }

        foreach (var (kind, group) in buckets)
        {
            try
            {
                var message = await ApplyAsync(window, kind, group, ctx);
                if (!string.IsNullOrEmpty(message))
                    AppServices.Toast(FileKinds.Label(kind), message, ToastKind.Success);
            }
            catch (Exception ex)
            {
                AppServices.Toast(L("没能处理"), $"{Path.GetFileName(group[0])} — {ex.Message}", ToastKind.Error);
            }
        }
    }

    /// <summary>拿不准这个文件是什么时，让用户指一下。</summary>
    private static async Task<string> AskKindAsync(FileKinds.Verdict info, int others)
    {
        var kinds = info.Kinds.Count > 0 ? info.Kinds : FileKinds.AllKinds.ToList();
        var body = Ui.V(8,
            Ui.Txt(info.Name, 13.5, true).Wrap(),
            string.IsNullOrWhiteSpace(info.Detail) ? null : Ui.Muted(info.Detail).Wrap());

        var picks = new List<(RadioButton Btn, string Kind)>();
        var host = Ui.V(6);
        foreach (var kind in kinds)
        {
            var rb = new RadioButton
            {
                Content = $"{FileKinds.Label(kind)} — {FileKinds.Action(kind)}",
                IsChecked = picks.Count == 0,
                Margin = new Thickness(0, 2, 0, 2),
            };
            picks.Add((rb, kind));
            host.Children.Add(rb);
        }
        body.Children.Add(host);
        if (others > 0)
            body.Children.Add(Ui.Small(L("这一批里还有 {0} 个同样认不准的文件，会照同一个选择处理。", others)).Wrap());

        if (!await Dlg.Ask(L("这个文件放哪儿？"), body, L("就这么放"), L("算了"), false, 460)) return "";
        return picks.FirstOrDefault(p => p.Btn.IsChecked == true).Kind ?? "";
    }

    private static async Task<string> ApplyAsync(MainWindow window, string kind, List<string> paths, DropContext ctx)
    {
        if (kind == FileKinds.Modpack)
        {
            // 一次只处理一个：每个包都要单独确认版本名，连弹 N 个框没法用
            await ImportModpackAsync(window, paths[0]);
            return "";
        }
        if (kind == FileKinds.Wallpaper) return await SetWallpaperAsync(paths[0]);
        if (kind == FileKinds.Skin) return await SetSkinAsync(paths[0]);
        if (!Installers.TryGetValue(kind, out var method)) throw new InvalidOperationException(L("还不支持这种文件"));

        // 页面给了实例就用页面的，没给才退回默认实例
        var instance = ctx.Instance.Length > 0 ? ctx.Instance : await CurrentInstanceAsync();
        foreach (var path in paths)
            await AppServices.Client.StartTaskAsync(method, new
            {
                name = Path.GetFileName(path),
                instance,
                extra = new { path, instance, version = ctx.Version, source = "本地" }, // i18n:ignore 桥的协议值（原文比对），不是界面词
            });
        window.Navigate("tasks");
        var where = ctx.Instance.Length > 0 ? L("实例「{0}」", instance) : L("默认实例");
        return L("已加入下载任务，装进{0}的{1}", where, FileKinds.Label(kind));
    }

    /// <summary>整合包：先把探到的信息摆给用户看，确认版本名后再建任务。</summary>
    public static async Task ImportModpackAsync(MainWindow window, string path)
    {
        var info = await Task.Run(() => FileKinds.ModpackProbe.Probe(path));
        if (info is null)
        {
            AppServices.Toast(L("这不是整合包"), Path.GetFileName(path), ToastKind.Warning);
            return;
        }
        var name = Ui.Input(L("新版本名称"), SuggestName(info));
        var body = Ui.V(8,
            Ui.Txt(string.IsNullOrEmpty(info.Name) ? Path.GetFileName(path) : info.Name, 14, true).Wrap(),
            Ui.Muted(info.Format).Wrap(),
            Ui.Small(string.Join(" · ", new[]
            {
                string.IsNullOrEmpty(info.McVersion) ? "" : "Minecraft " + info.McVersion,
                FileKinds.ModpackProbe.LoaderLabel(info.Loader, info.LoaderVersion),
                info.Files > 0 ? L("{0} 个文件", info.Files) : "",
            }.Where(x => !string.IsNullOrEmpty(x)))).Wrap(),
            Ui.Field(L("装成版本"), name, L("会建成一个新版本，原有版本不受影响"), 78));
        if (!await Dlg.Ask(L("安装整合包"), body, L("开始安装"))) return;

        var target = name.Text?.Trim();
        if (string.IsNullOrEmpty(target)) target = SuggestName(info);
        await AppServices.Client.StartTaskAsync("install_modpack", new
        {
            name = target,
            source = "本地", // i18n:ignore 桥的协议值（原文比对），不是界面词
            extra = new { path, name = target, source = "本地", kind = "modpack" }, // i18n:ignore 桥的协议值（原文比对），不是界面词
        });
        window.Navigate("tasks");
        AppServices.Toast(L("已加入队列"), L("正在安装「{0}」", target), ToastKind.Success);
    }

    private static string SuggestName(FileKinds.ModpackProbe.Info info)
    {
        var bits = new[] { info.Name, info.Version }.Where(x => !string.IsNullOrWhiteSpace(x));
        var joined = string.Join(" ", bits).Trim();
        if (joined.Length > 0) return joined;
        return string.IsNullOrEmpty(info.McVersion) ? L("整合包") : L("整合包 ") + info.McVersion;
    }

    /// <summary>设为启动器壁纸。文件夹轮播优先级更高，得一起关掉才看得见这一张。</summary>
    private static async Task<string> SetWallpaperAsync(string path)
    {
        var folder = await AppServices.Client.TryCallAsync<string>("get_setting",
            new { key = "ui_background_folder", @default = "" }, "") ?? "";
        var hadFolder = !string.IsNullOrWhiteSpace(folder);
        await AppServices.Client.CallAsync<object>("save_settings", new
        {
            data = new { ui_background = path, ui_background_folder = "" },
        });
        await Wallpaper.ReloadAsync();
        var kind = FileKinds.IsVideo(path) ? L("动态壁纸") : L("背景图");
        return hadFolder ? L("已设为{0}，文件夹轮播一并停掉了", kind) : L("已设为{0}", kind);
    }

    /// <summary>给离线账号换皮肤。挑哪个账号、宽臂还是细臂，交给账号页那个框。</summary>
    private static async Task<string> SetSkinAsync(string path)
    {
        var rows = await AppServices.Client.TryCallAsync<List<AccountRow>>("get_account_rows", null, new()) ?? new();
        var offline = rows.Where(r => r.Type == "offline").ToList();
        if (offline.Count == 0)
            throw new InvalidOperationException(L("还没有离线账号；先到「账号」页建一个，再把皮肤拖进来"));
        var target = offline.FirstOrDefault(r => r.Active) ?? offline[0];
        return await AccountPage.EditSkinExternalAsync(target, path);
    }

    private static async Task<string> CurrentInstanceAsync()
    {
        var pref = AppServices.Window?.Prefs.CatalogInstance;
        if (!string.IsNullOrWhiteSpace(pref)) return pref;
        var def = await AppServices.Client.TryCallAsync<string>("get_setting",
            new { key = "default_instance", @default = "" }, "") ?? "";
        if (!string.IsNullOrWhiteSpace(def)) return def;
        var rows = await AppServices.Client.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        return rows.FirstOrDefault()?.Name ?? "default";
    }
}
