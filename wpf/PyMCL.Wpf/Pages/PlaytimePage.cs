using System.Collections.Concurrent;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>游玩时长。总览按实例汇总，选中某个实例后走 get_playtime 看它的版本与最近会话。</summary>
public sealed class PlaytimePage : PageBase
{
    private static string AllInstances => L("全部实例");

    private readonly SPanel _list = Ui.V(10);
    private readonly TextBlock _total = new() { FontSize = 34, FontWeight = FontWeights.Bold };
    private readonly TextBlock _sub = Ui.Muted("");
    private readonly ComboBox _inst = Ui.Combo(new[] { AllInstances }, width: 190);
    private bool _sync;

    /// <summary>秒数 → 后端文案。format_playtime 一个值问一次，同一个值不重复问。</summary>
    private static readonly ConcurrentDictionary<long, string> _durCache = new();

    public override string Title => L("游戏时长");

    public PlaytimePage()
    {
        var clear = Ui.Btn(L("清空统计"), BtnKind.Ghost, (_, _) => Run(ClearAllAsync), Ico.Broom);
        var refresh = Ui.Btn(L("刷新"), BtnKind.Chip, (_, _) => Run(LoadAsync), Ico.Refresh);
        _inst.SelectionChanged += (_, _) => { if (!_sync) Run(ReloadAsync); };

        _total.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        var hero = Ui.Card(Ui.G(null, "*,Auto")
            .Add(Ui.V(4, Ui.Muted(L("累计游玩")), _total, _sub), 0, 0)
            .Add(Ui.Glyph(Ico.Clock, 44, "B.AccentSoft2").VCenter(), 0, 1), 20);

        var bar = Ui.Card(Ui.H(10,
            Ui.Txt(L("范围"), 12, fg: "B.InkMuted").VCenter(), _inst.VCenter()), 12);

        Content = ScrollBody(
            Ui.Section(L("游戏时长"), L("按实例与版本统计，每次退出游戏后自动累加"), Ui.H(8, refresh, clear)),
            hero, bar, _list);
    }

    protected override async Task LoadAsync()
    {
        var insts = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _sync = true;
        _inst.Fill(new[] { AllInstances }.Concat(insts.Select(i => i.Name)));
        _sync = false;
        await ReloadAsync();
    }

    public override Task RefreshAsync() => ReloadAsync();

    private Task ReloadAsync() =>
        _inst.Str() is { Length: > 0 } pick && pick != AllInstances ? ReloadOneAsync(pick) : ReloadAllAsync();

    // ==================== 全部实例 ====================
    private async Task ReloadAllAsync()
    {
        var total = await Api.TryCallAsync<long>("get_total_playtime", null, 0L);
        Motion.CountUp(_total, 0, total / 3600.0, "0.0");
        _total.Text = await FormatAsync(total);
        var all = await Api.TryCallAsync<Dictionary<string, JsonElement>>("get_all_playtime", null, new()) ?? new();
        _sub.Text = L("{0} 个实例有记录", all.Count);
        _list.Children.Clear();
        if (all.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Clock, L("还没有游玩记录"), L("启动一次游戏后这里就有数据了")));
            return;
        }

        var ordered = all.OrderByDescending(k => Secs(k.Value)).ToList();
        var max = Math.Max(1L, ordered.Max(k => Secs(k.Value)));
        // 所有要显示的秒数一次性问完，避免逐行 await 把一页拉成几十个往返。
        await WarmAsync(ordered.SelectMany(kv => Versions(kv.Value).Select(v => v.Value).Concat(new[] { Secs(kv.Value) })));

        foreach (var kv in ordered)
        {
            var name = kv.Key;
            var secs = Secs(kv.Value);
            var bar = Ui.Prog(0);
            bar.Height = 6;
            var versions = Versions(kv.Value)
                .OrderByDescending(v => v.Value)
                .Take(6)
                .Select(v => $"{v.Key} {Cached(v.Value)}")
                .ToList();

            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.V(6,
                Ui.Txt(name, 14, true),
                bar,
                Ui.Small(versions.Count == 0 ? "—" : string.Join(" · ", versions)).Wrap()), 0, 0);
            g.Add(Ui.V(2,
                Ui.Txt(Cached(secs), 13, true, "B.AccentDeep").Right(),
                Ui.Btn(L("查看"), BtnKind.Chip, (_, _) =>
                {
                    _sync = true;
                    _inst.Fill(_inst.Items.Cast<string>(), name);
                    _sync = false;
                    Run(() => ReloadOneAsync(name));
                }).Right(),
                Ui.Btn(L("清除"), BtnKind.Ghost, (_, _) => Run(() => ClearOneAsync(name))).Right())
                .M(14, 0, 0, 0).VCenter(), 0, 1);
            _list.Children.Add(Ui.Card(g, 14));
            Motion.Progress(bar, secs * 100.0 / max);
        }
        Motion.Stagger(_list, 30);
    }

    // ==================== 单个实例 ====================
    private async Task ReloadOneAsync(string instance)
    {
        var data = await Api.TryCallAsync<JsonElement>("get_playtime", new { instance });
        var total = Secs(data);
        Motion.CountUp(_total, 0, total / 3600.0, "0.0");
        _total.Text = await FormatAsync(total);

        var versions = Versions(data).OrderByDescending(v => v.Value).ToList();
        var sessions = Sessions(data);
        _sub.Text = L("实例「{0}」 · {1} 个版本 · {2} 次会话", instance, versions.Count, sessions.Count);

        _list.Children.Clear();
        if (total <= 0 && versions.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Clock, L("这个实例还没有记录"), L("启动一次游戏后这里就有数据了")));
            return;
        }

        await WarmAsync(versions.Select(v => v.Value));
        var max = versions.Count == 0 ? 1L : Math.Max(1L, versions.Max(v => v.Value));
        foreach (var (vid, secs) in versions)
        {
            var bar = Ui.Prog(0);
            bar.Height = 6;
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.V(6, Ui.Txt(vid, 13.5, true), bar), 0, 0);
            g.Add(Ui.V(2,
                Ui.Txt(Cached(secs), 13, true, "B.AccentDeep").Right(),
                Ui.Btn(L("清除"), BtnKind.Ghost, (_, _) => Run(() => ClearOneAsync(instance, vid))).Right())
                .M(14, 0, 0, 0).VCenter(), 0, 1);
            _list.Children.Add(Ui.Card(g, 13));
            Motion.Progress(bar, secs * 100.0 / max);
        }
        if (sessions.Count > 0)
        {
            var body = Ui.V(4, Ui.Txt(L("最近会话"), 13, true));
            foreach (var s in sessions.Take(10)) body.Children.Add(Ui.Small(s).Wrap());
            _list.Children.Add(Ui.Card(body, 13));
        }
        Motion.Stagger(_list, 26);
    }

    // ==================== 清除 ====================
    private async Task ClearAllAsync()
    {
        if (!await Dlg.Confirm(L("清空游戏时长"), L("所有实例的时长记录都会归零。"), L("清空"), L("取消"), true)) return;
        await Api.CallAsync("clear_playtime", new { instance = "", version = "" });
        await LoadAsync();
    }

    private async Task ClearOneAsync(string instance, string version = "")
    {
        await Api.CallAsync("clear_playtime", new { instance, version });
        await ReloadAsync();
    }

    // ==================== 时长文案 ====================
    private static string Cached(long secs) => _durCache.GetValueOrDefault(secs) ?? Fmt.Duration(secs);

    /// <summary>后端文案（「3 小时 12 分钟」）是对齐基准；拿不到就退回本地格式化。</summary>
    private static async Task<string> FormatAsync(long seconds)
    {
        if (_durCache.TryGetValue(seconds, out var hit)) return hit;
        var text = await Api.TryCallAsync<string>("format_playtime", new { seconds }, "") ?? "";
        if (string.IsNullOrWhiteSpace(text)) text = Fmt.Duration(seconds);
        _durCache[seconds] = text;
        return text;
    }

    private static Task WarmAsync(IEnumerable<long> values)
    {
        var want = values.Where(v => v > 0 && !_durCache.ContainsKey(v)).Distinct().Take(60).ToList();
        return want.Count == 0 ? Task.CompletedTask : Task.WhenAll(want.Select(v => FormatAsync(v)));
    }

    // ==================== JSON 取值 ====================
    private static long Secs(JsonElement el) =>
        el.ValueKind == JsonValueKind.Object && el.TryGetProperty("total", out var t) && t.TryGetInt64(out var n) ? n : 0;

    private static List<KeyValuePair<string, long>> Versions(JsonElement el)
    {
        var rows = new List<KeyValuePair<string, long>>();
        if (el.ValueKind != JsonValueKind.Object ||
            !el.TryGetProperty("versions", out var vs) || vs.ValueKind != JsonValueKind.Object) return rows;
        foreach (var v in vs.EnumerateObject())
            if (v.Value.TryGetInt64(out var n) && n > 0) rows.Add(new(v.Name, n));
        return rows;
    }

    private static List<string> Sessions(JsonElement el)
    {
        var rows = new List<string>();
        if (el.ValueKind != JsonValueKind.Object ||
            !el.TryGetProperty("sessions", out var ss) || ss.ValueKind != JsonValueKind.Array) return rows;
        foreach (var s in ss.EnumerateArray().Reverse())
        {
            if (s.ValueKind != JsonValueKind.Object) continue;
            var ver = s.TryGetProperty("version", out var v) ? v.ToString() : "";
            var start = s.TryGetProperty("start", out var st) ? st.ToString() : "";
            var secs = s.TryGetProperty("seconds", out var sec) && sec.TryGetInt64(out var n) ? n : 0;
            rows.Add(string.Join(" · ", new[] { ver, start, Cached(secs) }.Where(x => !string.IsNullOrWhiteSpace(x))));
        }
        return rows;
    }
}
