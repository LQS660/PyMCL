using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class PlaytimePage : UserControl
{
    /// <summary>
    /// 秒数 → 后端文案。format_playtime 是纯格式化（native/src/rpc_local.c 与 Python 侧同），
    /// 同一个值问一次就够，缓存起来避免每个版本各发一次往返。
    /// </summary>
    private static readonly ConcurrentDictionary<int, string> DurationCache = new();
    /// <summary>缓存上限：键是秒数，不设上限会随游玩时长一直长（Thumbs 那边是 400 条上限）。</summary>
    private const int DurationCacheMax = 400;

    public PlaytimePage()
    {
        InitializeComponent();
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        ListHost.Children.Clear();
        var all = await AppServices.Client.CallAsync<JsonElement>("get_all_playtime");
        // 先只把原始秒数收集起来，不在这里逐条 await：格式化统一放到 WarmAsync 里并发做。
        var raw = new List<(string Inst, int Total, List<(string Ver, int Sec)> Vers)>();
        var wanted = new List<int>();
        if (all.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in all.EnumerateObject())
            {
                if (prop.Value.ValueKind != JsonValueKind.Object) continue;
                var total = prop.Value.TryGetProperty("total", out var t) && t.TryGetInt32(out var sec) ? sec : 0;
                if (total <= 0) continue;
                wanted.Add(total);
                var vers = new List<(string, int)>();
                if (prop.Value.TryGetProperty("versions", out var vobj) && vobj.ValueKind == JsonValueKind.Object)
                {
                    foreach (var v in vobj.EnumerateObject())
                    {
                        if (v.Value.TryGetInt32(out var vs) && vs > 0)
                        {
                            vers.Add((v.Name, vs));
                            wanted.Add(vs);
                        }
                    }
                }
                raw.Add((prop.Name, total, vers));
            }
        }
        // 这一屏要用的秒数并发预热（最多 8 个在飞），随后取用全是缓存命中——
        // 原本每个版本一次串行 await，10 实例 × 5 版本就是 60 次串行往返。
        await WarmAsync(wanted);
        var rows = raw
            .Select(r => (Inst: r.Inst, Total: r.Total,
                Versions: string.Join(" · ", r.Vers.Select(v => $"{v.Ver}: {FormatCached(v.Sec)}"))))
            .ToList();
        Empty.Visibility = rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        foreach (var row in rows.OrderByDescending(r => r.Total))
            ListHost.Children.Add(await BuildCardAsync(row.Inst, row.Total, row.Versions));
    }

    /// <summary>同步取缓存文案；未命中就退回本地格式（预热已尽量覆盖）。</summary>
    private static string FormatCached(int seconds) =>
        DurationCache.TryGetValue(seconds, out var hit) ? hit : FmtDuration(seconds);

    /// <summary>与后端 format_duration 同口径的本地兜底：x 小时 y 分钟。</summary>
    private static string FmtDuration(int seconds)
    {
        if (seconds < 60) return $"{seconds} 秒";
        var minutes = seconds / 60;
        if (minutes < 60) return $"{minutes} 分钟";
        var hours = minutes / 60;
        var rest = minutes % 60;
        return rest == 0 ? $"{hours} 小时" : $"{hours} 小时 {rest} 分钟";
    }

    /// <summary>
    /// 秒数 → 文案。以前每个版本串行 await 一次 format_playtime，10 实例 × 5 版本就是 60 次
    /// 串行 HTTP 往返，首屏肉眼可见地卡。现在先把这一屏要用的值去重、并发预热（同时最多 8 个在飞），
    /// 之后逐条取都是缓存命中，剩下的只有 BuildCardAsync 那一次可能未命中的值。
    /// </summary>
    private static async Task WarmAsync(IEnumerable<int> seconds)
    {
        if (AppServices.Client is null) return;
        var want = seconds.Where(v => v > 0 && !DurationCache.ContainsKey(v)).Distinct().ToList();
        if (want.Count == 0) return;
        using var gate = new SemaphoreSlim(8, 8);
        await Task.WhenAll(want.Select(async v =>
        {
            await gate.WaitAsync();
            try { await FormatAsync(v); }
            finally { gate.Release(); }
        }));
    }

    private static async Task<string> FormatAsync(int seconds)
    {
        if (DurationCache.TryGetValue(seconds, out var hit)) return hit;
        if (AppServices.Client is null) return $"{seconds} 秒";
        string text;
        try
        {
            var got = await AppServices.Client.CallAsync<string>("format_playtime", new { seconds });
            text = string.IsNullOrWhiteSpace(got) ? $"{seconds} 秒" : got;
        }
        catch
        {
            text = $"{seconds} 秒";
        }
        // 键是秒数，随游玩时长一直增长；不设上限就是一个只进不出的字典。
        if (DurationCache.Count >= DurationCacheMax) DurationCache.Clear();
        DurationCache[seconds] = text;
        return text;
    }

    private async Task<Border> BuildCardAsync(string instance, int totalSeconds, string versions)
    {
        var card = new Border
        {
            Padding = new Thickness(16, 14, 16, 14),
            CornerRadius = new CornerRadius(8),
            BorderThickness = new Thickness(1),
            Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
            BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
        };
        var box = new StackPanel { Spacing = 6 };
        box.Children.Add(new TextBlock
        {
            Text = instance,
            FontSize = 16,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
        });
        box.Children.Add(new TextBlock { Text = $"总计：{await FormatAsync(totalSeconds)}", Opacity = 0.85 });
        if (!string.IsNullOrWhiteSpace(versions))
            box.Children.Add(new TextBlock { Text = versions, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        card.Child = box;
        return card;
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        if (!await Dialogs.ConfirmAsync(XamlRoot, "清除记录", "将清除所有实例的游玩时长记录，此操作不可恢复。", "清除"))
            return;
        try
        {
            await AppServices.Client.CallAsync("clear_playtime", new { instance = "" });
            await ReloadAsync();
            AppServices.Toast?.Invoke("已清除", "游玩时长记录已清空", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("清除失败", ex.Message, InfoBarSeverity.Error);
        }
    }
}
