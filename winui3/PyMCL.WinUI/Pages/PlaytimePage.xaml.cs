using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class PlaytimePage : UserControl
{
    public PlaytimePage()
    {
        InitializeComponent();
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        ListHost.Children.Clear();
        var all = await AppServices.Client.CallAsync<JsonElement>("get_all_playtime");
        var rows = new List<(string inst, int total, string versions)>();
        if (all.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in all.EnumerateObject())
            {
                if (prop.Value.ValueKind != JsonValueKind.Object) continue;
                var total = prop.Value.TryGetProperty("total", out var t) && t.TryGetInt32(out var sec) ? sec : 0;
                if (total <= 0) continue;
                var verParts = new List<string>();
                if (prop.Value.TryGetProperty("versions", out var vers) && vers.ValueKind == JsonValueKind.Object)
                {
                    foreach (var v in vers.EnumerateObject())
                    {
                        if (v.Value.TryGetInt32(out var vs) && vs > 0)
                            verParts.Add($"{v.Name}: {await FormatAsync(vs)}");
                    }
                }
                rows.Add((prop.Name, total, string.Join(" · ", verParts)));
            }
        }
        Empty.Visibility = rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        foreach (var (inst, total, versions) in rows.OrderByDescending(r => r.total))
            ListHost.Children.Add(await BuildCardAsync(inst, total, versions));
    }

    private async Task<string> FormatAsync(int seconds)
    {
        if (AppServices.Client is null) return $"{seconds} 秒";
        try
        {
            var text = await AppServices.Client.CallAsync<string>("format_playtime", new { seconds });
            return string.IsNullOrWhiteSpace(text) ? $"{seconds} 秒" : text;
        }
        catch
        {
            return $"{seconds} 秒";
        }
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
