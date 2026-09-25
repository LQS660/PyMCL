using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// 首次运行向导，对齐 Qt 端 app/pages/first_run.py。
///
/// 前三步问设置，最后一步纯介绍——「文件能直接拖进窗口」「侧栏可以排」「壁纸在哪」
/// 这些功能用户只能自己撞见，而多数人撞不见。每一步都能跳过，跳了也不会再弹
/// （first_run 落盘）；想再看，设置页有「重新运行向导」。
/// </summary>
public static class FirstRunWizard
{
    /// <summary>最后一步里指给用户看的那几件事。</summary>
    private static readonly (string Title, string Body)[] Highlights =
    {
        (L("把文件直接拖进窗口"),
            L("整合包、模组、资源包、光影、存档、皮肤、壁纸都认；认不准会问你一句，不用先找对页面。")),
        (L("侧栏是可以排的"),
            L("「游戏」「更多」里的子页拖到侧栏就固定成一级项，从侧栏拖回去就还原；排法和显隐在设置里。")),
        (L("换个背景"),
            L("设置页能设静态壁纸、mp4 动态壁纸，或者指一个文件夹轮播；模糊和遮罩也在那儿调。")),
        (L("AI 助手在侧栏「通用」组里"),
            L("崩溃日志看不懂、模组冲突理不清，可以直接问它。")),
        (L("这个向导随时能再看"),
            L("「设置 → 启动向导」点「重新运行」，目录、下载源、内存、隔离会再问一遍。")),
    };

    private static readonly (string Key, string Label)[] SrcOpts =
    {
        ("auto", L("自动（官方慢则 BMCLAPI）")), ("official", L("仅官方")), ("bmclapi", L("仅 BMCLAPI")),
    };

    private static readonly (string Key, string Label)[] IsoOpts =
    {
        ("all", L("完全独立（推荐）")), ("mods", L("隔离 Mod 与配置")), ("saves", L("隔离存档")), ("none", L("不隔离")),
    };

    private static readonly string[] Hints =
    {
        L("先把游戏目录和下载源定下来。"),
        L("版本都会装在这个目录里；下载源决定从哪儿拉文件。"),
        L("这两项只影响以后新建的版本，已经装好的不受影响。"),
        L("最后几句，都是容易错过的地方。"),
    };

    /// <summary>启动时看一眼要不要弹。用户点过「跳过向导」就不会再来。</summary>
    public static async Task MaybeShowAsync()
    {
        var first = await AppServices.Client.TryCallAsync<bool>("get_setting",
            new { key = "first_run", @default = false }, false);
        if (!first) return;
        await ShowAsync();
    }

    /// <summary>跑一遍向导。用户跳过时只把 first_run 落成 false，其余一项不动。</summary>
    public static async Task ShowAsync()
    {
        var api = AppServices.Client;
        var settings = await api.TryCallAsync<Dictionary<string, JsonElement>>("get_settings", null, new()) ?? new();

        string Str(string k) => settings.TryGetValue(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
        int Int(string k, int def) => settings.TryGetValue(k, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n) ? n : def;

        var gameDir = Ui.Input(L("游戏目录"), Str("game_dir").Length > 0 ? Str("game_dir") : Str("root"));
        var browse = Ui.Btn(L("浏览…"), BtnKind.Chip, (_, _) =>
        {
            var p = Dlg.PickFolder(L("选择游戏目录"));
            if (p != null) gameDir.Text = p;
        }, Ico.Folder);
        var dirRow = Ui.G(null, "*,Auto");
        dirRow.Add(gameDir, 0, 0);
        dirRow.Add(browse.M(8, 0, 0, 0).VCenter(), 0, 1);

        var src = Ui.Combo(SrcOpts.Select(o => o.Label));
        src.SelectedIndex = Math.Max(0, Array.FindIndex(SrcOpts, o => o.Key == (Str("download_source") is { Length: > 0 } s ? s : "auto")));
        var mem = Ui.Sld(512, 32768, Clamp.Of(Int("default_memory_mb", 4096), 512, 32768), 256);
        var memLbl = Ui.Txt($"{(int)mem.Value} MB", 12, true);
        mem.ValueChanged += (_, e) => memLbl.Text = $"{(int)e.NewValue} MB";
        var memRow = Ui.G(null, "*,Auto");
        memRow.Add(mem.VCenter(), 0, 0);
        memRow.Add(memLbl.M(10, 0, 0, 0).VCenter(), 0, 1);
        var iso = Ui.Combo(IsoOpts.Select(o => o.Label));
        iso.SelectedIndex = Math.Max(0, Array.FindIndex(IsoOpts, o => o.Key == (Str("default_isolation") is { Length: > 0 } i ? i : "all")));

        // ---- 四个步骤 ----
        var welcome = Ui.V(6,
            Ui.Txt(L("三步就能开始玩"), 14, true),
            Ui.Muted(L("1. 选游戏目录和下载源")),
            Ui.Muted(L("2. 定默认内存和版本隔离")),
            Ui.Muted(L("3. 看一眼几个容易错过的功能")),
            Ui.Small(L("这些以后都能在设置里改；不想现在弄就点「跳过向导」。")).Wrap());

        var paths = Ui.V(8,
            Ui.Txt(L("游戏目录（版本都装在这里）"), 13),
            dirRow,
            Ui.Txt(L("文件下载源"), 13),
            src,
            Ui.Small(L("国内网络建议保持「自动」：官方慢的时候会自己切到 BMCLAPI 镜像。")).Wrap());

        var game = Ui.V(8,
            Ui.Txt(L("默认内存"), 13), memRow,
            Ui.Txt(L("新版本默认隔离"), 13), iso,
            Ui.Small(L("「完全独立」= 每个版本有自己的 mods / 配置 / 存档，换版本不会把上一个版本的模组拖进去。")).Wrap());

        var tips = Ui.V(9);
        foreach (var (title, detail) in Highlights)
        {
            tips.Children.Add(Ui.Txt(title, 13, true));
            tips.Children.Add(Ui.Small(detail).Wrap());
        }

        var pages = new UIElement[] { welcome, paths, game, tips };

        // ---- 步进外壳 ----
        var hint = Ui.Muted("");
        hint.TextWrapping = TextWrapping.Wrap;
        var step = Ui.Small("");
        var host = new Grid { MinWidth = 470, MinHeight = 250 };
        foreach (var p in pages)
        {
            p.Visibility = Visibility.Collapsed;
            host.Children.Add(p);
        }

        var back = Ui.Btn(L("上一步"));
        var next = Ui.Btn(L("下一步"), BtnKind.Primary);
        var skip = Ui.Btn(L("跳过向导"), BtnKind.Ghost);
        var index = 0;
        var tcs = new TaskCompletionSource<bool>();

        void Show(int i)
        {
            index = Clamp.Of(i, 0, pages.Length - 1);
            for (var k = 0; k < pages.Length; k++)
                pages[k].Visibility = k == index ? Visibility.Visible : Visibility.Collapsed;
            hint.Text = Hints[index];
            step.Text = L("第 {0} / {1} 步", index + 1, pages.Length);
            back.IsEnabled = index > 0;
            next.Content = index == pages.Length - 1 ? L("开始使用") : L("下一步");
            Motion.FadeIn(pages[index], 200, 8);
        }

        var body = Ui.V(12, hint, host, Ui.Sep(),
            Ui.G(null, "Auto,*,Auto,Auto")
                .Add(step.VCenter(), 0, 0)
                .Add(skip.Right().VCenter(), 0, 1)
                .Add(back.M(8, 0, 0, 0).VCenter(), 0, 2)
                .Add(next.M(8, 0, 0, 0).VCenter(), 0, 3));

        Dlg.Layer? layer = null;
        layer = Dlg.Panel(L("欢迎使用 PyMCL"), body, 560, () => tcs.TrySetResult(false));
        back.Click += (_, _) => Show(index - 1);
        next.Click += (_, _) =>
        {
            if (index < pages.Length - 1)
            {
                Show(index + 1);
                return;
            }
            tcs.TrySetResult(true);
            layer!.Close();
        };
        skip.Click += (_, _) =>
        {
            tcs.TrySetResult(false);
            layer!.Close();
        };
        Show(0);

        var finished = await tcs.Task;

        // 跳过也要落 first_run，否则下次开机又弹一遍
        if (!finished)
        {
            await api.TryCallAsync<object>("save_settings", new { data = new { first_run = false } });
            return;
        }

        // 游戏目录不走普通配置项：切目录要经 set_game_dir 校验可写性
        var typed = gameDir.Text?.Trim() ?? "";
        var current = Str("game_dir").Length > 0 ? Str("game_dir") : Str("root");
        if (typed.Length > 0 && typed != current)
        {
            try { await api.CallAsync<string>("set_game_dir", new { path = typed }); }
            catch (Exception ex)
            {
                await Dlg.Alert(L("游戏目录没能设置"),
                    L("{0}\n\n{1}\n\n已保留原来的目录，可到「设置」里重新选择。", typed, ex.Message));
            }
        }

        await api.CallAsync<object>("save_settings", new
        {
            data = new Dictionary<string, object?>
            {
                ["download_source"] = SrcOpts[Math.Max(0, src.SelectedIndex)].Key,
                ["default_memory_mb"] = (int)mem.Value,
                ["default_isolation"] = IsoOpts[Math.Max(0, iso.SelectedIndex)].Key,
                ["first_run"] = false,
            },
        });
        AppServices.Toast(L("向导已完成"), L("目录、下载源、内存、隔离已按你的选择写入"), ToastKind.Success);
        if (AppServices.Window?.GetPage("settings") is SettingsPage sp) await sp.RefreshAsync();
    }
}
