using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class PlaytimePage : PageBase
{
    public override string Title => "游戏时长";

    private readonly SPanel _list = Ui.V(10);
    private readonly TextBlock _total = new() { FontSize = 34, FontWeight = FontWeights.Bold };
    private readonly TextBlock _sub = Ui.Muted("");

    public PlaytimePage()
    {
        var clear = Ui.Btn("清空统计", BtnKind.Ghost, (_, _) => Run(async () =>
        {
            if (!await Dlg.Confirm("清空游戏时长", "所有实例的时长记录都会归零。", "清空", "取消", true)) return;
            await Api.CallAsync("clear_playtime", new { instance = "", version = "" });
            await LoadAsync();
        }), Ico.Broom);
        var refresh = Ui.Btn("刷新", BtnKind.Chip, (_, _) => Run(LoadAsync), Ico.Refresh);

        _total.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        var hero = Ui.Card(Ui.G(null, "*,Auto")
            .Add(Ui.V(4, Ui.Muted("累计游玩"), _total, _sub), 0, 0)
            .Add(Ui.Glyph(Ico.Clock, 44, "B.AccentSoft2").VCenter(), 0, 1), 20);

        Content = ScrollBody(
            Ui.Section("游戏时长", "按实例与版本统计，每次退出游戏后自动累加", Ui.H(8, refresh, clear)),
            hero, _list);
    }

    protected override async Task LoadAsync()
    {
        var total = await Api.TryCallAsync<long>("get_total_playtime", null, 0L);
        Motion.CountUp(_total, 0, total / 3600.0, "0.0");
        _total.Text = Fmt.Duration(total);
        var all = await Api.TryCallAsync<Dictionary<string, JsonElement>>("get_all_playtime", null, new()) ?? new();
        _sub.Text = $"{all.Count} 个实例有记录";
        _list.Children.Clear();
        if (all.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Clock, "还没有游玩记录", "启动一次游戏后这里就有数据了"));
            return;
        }
        var max = 1L;
        foreach (var kv in all)
            if (kv.Value.TryGetProperty("total", out var t) && t.TryGetInt64(out var sec)) max = Math.Max(max, sec);

        foreach (var kv in all.OrderByDescending(k => Secs(k.Value)))
        {
            var name = kv.Key;
            var secs = Secs(kv.Value);
            var bar = Ui.Prog(0);
            bar.Height = 6;
            var versions = new List<string>();
            if (kv.Value.TryGetProperty("versions", out var vs) && vs.ValueKind == JsonValueKind.Object)
                foreach (var v in vs.EnumerateObject())
                    versions.Add($"{v.Name} {Fmt.Duration(v.Value.TryGetInt64(out var n) ? n : 0)}");

            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.V(6,
                Ui.Txt(name, 14, true),
                bar,
                Ui.Small(versions.Count == 0 ? "—" : string.Join(" · ", versions.Take(6))).Wrap()), 0, 0);
            g.Add(Ui.V(2,
                Ui.Txt(Fmt.Duration(secs), 13, true, "B.AccentDeep").Right(),
                Ui.Btn("清除", BtnKind.Ghost, (_, _) => Run(async () =>
                {
                    await Api.CallAsync("clear_playtime", new { instance = name, version = "" });
                    await LoadAsync();
                })).Right()).M(14, 0, 0, 0).VCenter(), 0, 1);
            _list.Children.Add(Ui.Card(g, 14));
            Motion.Progress(bar, secs * 100.0 / max);
        }
        Motion.Stagger(_list, 30);
    }

    private static long Secs(JsonElement el) =>
        el.TryGetProperty("total", out var t) && t.TryGetInt64(out var n) ? n : 0;
}
