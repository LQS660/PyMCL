using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PyMCL.Models;
using PyMCL.Services;
using Windows.UI;

namespace PyMCL.Pages;

public sealed partial class VersionPage : UserControl
{
    private List<VersionRow> _all = new();
    private readonly List<(CheckBox Box, string Spec)> _installed = new();
    private bool _fetched;

    public VersionPage()
    {
        InitializeComponent();
        LoaderBox.SelectedIndex = 0;
    }

    private void Page_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (PageRoot is null) return;
        var pad = e.NewSize.Width < 640 ? new Thickness(12, 10, 12, 10) : new Thickness(28, 20, 28, 20);
        if (PageRoot.Padding != pad) PageRoot.Padding = pad;
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        await FillInstances();
        _all = await AppServices.Client.CallAsync<List<VersionRow>>("get_version_list") ?? new();
        Refill();
        await ReloadInstalled();
        if (_fetched) return;
        _fetched = true;
        _ = FetchRemote();
    }

    private async Task FetchRemote()
    {
        try
        {
            var rows = await AppServices.Client.CallAsync<List<VersionRow>>("fetch_version_list") ?? new();
            _all = rows;
            Refill();
        }
        catch { }
    }

    private async Task FillInstances()
    {
        var insts = await AppServices.Client.CallAsync<List<InstanceInfo>>("get_instances") ?? new();
        var cur = InstanceBox.SelectedItem as string;
        InstanceBox.SelectionChanged -= Instance_Changed;
        InstanceBox.Items.Clear();
        foreach (var i in insts) InstanceBox.Items.Add(i.Name);
        if (cur != null && insts.Any(x => x.Name == cur)) InstanceBox.SelectedItem = cur;
        else if (InstanceBox.Items.Count > 0) InstanceBox.SelectedIndex = 0;
        InstanceBox.SelectionChanged += Instance_Changed;
    }

    private void Filter_Changed(object sender, object e) => Refill();

    private async void Instance_Changed(object sender, SelectionChangedEventArgs e) => await ReloadInstalled();

    private void Refill()
    {
        var text = (SearchBox.Text ?? "").Trim().ToLowerInvariant();
        var vtype = "all";
        if (TypePivot.SelectedItem is RadioButton rb && rb.Tag is string tag)
            vtype = tag;
        var rows = _all.Where(v =>
            (string.IsNullOrEmpty(text) || v.Version.ToLowerInvariant().Contains(text)) &&
            (vtype == "all" || v.Type == vtype)).Take(80).ToList();
        var cards = new List<UIElement>();
        if (rows.Count == 0)
            cards.Add(new TextBlock { Text = "没有匹配的版本", Foreground = new SolidColorBrush(Color.FromArgb(255, 136, 136, 136)), Margin = new Thickness(8) });
        foreach (var v in rows)
            cards.Add(BuildCard(v));
        for (var i = 0; i < cards.Count; i++)
        {
            if (cards[i] is Border)
                Motion.CardEnter(cards[i], Math.Min(i, 14) * 32);
        }
        VersionGrid.ItemsSource = cards;
    }

    private Border BuildCard(VersionRow info)
    {
        var labels = new Dictionary<string, (string, Color)>
        {
            ["release"] = ("正式版", Color.FromArgb(255, 47, 163, 107)),
            ["snapshot"] = ("快照", Color.FromArgb(255, 232, 134, 46)),
            ["old_alpha"] = ("远古", Color.FromArgb(255, 124, 92, 214)),
            ["old_beta"] = ("远古", Color.FromArgb(255, 124, 92, 214)),
        };
        var (lab, col) = labels.TryGetValue(info.Type, out var t) ? t : ("快照", Color.FromArgb(255, 232, 134, 46));
        var card = new Border
        {
            MinWidth = 180, Height = 132, Padding = new Thickness(16, 14, 16, 14),
            Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
            BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
            Translation = new System.Numerics.Vector3(0, 0, 16),
            Shadow = new ThemeShadow(),
        };
        var g = new Grid();
        g.RowDefinitions.Add(new RowDefinition());
        g.RowDefinitions.Add(new RowDefinition());
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var top = new Grid();
        top.Children.Add(new TextBlock { Text = info.Version, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        top.Children.Add(Pill(lab, col));
        g.Children.Add(top);
        var date = new TextBlock { Text = "发布于 " + info.Date, Foreground = new SolidColorBrush(Color.FromArgb(255, 136, 136, 136)), FontSize = 12, Margin = new Thickness(0, 6, 0, 0) };
        Grid.SetRow(date, 1);
        g.Children.Add(date);
        var btn = new Button { Content = "安装", Height = 30, HorizontalAlignment = HorizontalAlignment.Right };
        btn.Click += async (_, _) =>
        {
            if (AppServices.Client is null) return;
            var loader = LoaderBox.SelectedItem as string ?? "无";
            var inst = InstanceBox.SelectedItem as string ?? "default";
            try
            {
                await AppServices.Client.StartTaskAsync("install_game", new { version = info.Version, loader, instance = inst });
            }
            catch (Exception ex) { AppServices.Toast?.Invoke("安装失败", ex.Message, InfoBarSeverity.Error); }
        };
        Grid.SetRow(btn, 3);
        g.Children.Add(btn);
        card.Child = g;
        return card;
    }

    private static Border Pill(string text, Color color)
    {
        return new Border
        {
            HorizontalAlignment = HorizontalAlignment.Right,
            Background = new SolidColorBrush(Color.FromArgb(38, color.R, color.G, color.B)),
            CornerRadius = new CornerRadius(9),
            Padding = new Thickness(10, 2, 10, 2),
            Child = new TextBlock { Text = text, Foreground = new SolidColorBrush(color), FontSize = 12, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold },
        };
    }

    private async Task ReloadInstalled()
    {
        InstalledList.Children.Clear();
        _installed.Clear();
        var instance = InstanceBox.SelectedItem as string ?? "default";
        var vers = await AppServices.Client.CallAsync<List<string>>("get_installed_versions", new { instance }) ?? new();
        foreach (var v in vers)
        {
            var row = new Grid();
            var cb = new CheckBox { Content = v };
            var label = v.Contains("fabric", StringComparison.OrdinalIgnoreCase) ? "Fabric"
                : v.Contains("forge", StringComparison.OrdinalIgnoreCase) && !v.Contains("neoforge", StringComparison.OrdinalIgnoreCase) ? "Forge"
                : v.Contains("quilt", StringComparison.OrdinalIgnoreCase) ? "Quilt"
                : v.Contains("neoforge", StringComparison.OrdinalIgnoreCase) ? "NeoForge" : "原版";
            var col = label == "Fabric" ? Color.FromArgb(255, 124, 92, 214)
                : label is "Forge" or "NeoForge" ? Color.FromArgb(255, 232, 134, 46)
                : label == "Quilt" ? Color.FromArgb(255, 124, 92, 214)
                : Color.FromArgb(255, 76, 139, 245);
            row.Children.Add(cb);
            row.Children.Add(Pill(label, col));
            InstalledList.Children.Add(row);
            _installed.Add((cb, $"{instance} / {v}"));
        }
    }

    private async void Uninstall_Click(object sender, RoutedEventArgs e)
    {
        var selected = _installed.Where(x => x.Box.IsChecked == true).Select(x => x.Spec).ToList();
        if (selected.Count == 0)
        {
            AppServices.Toast?.Invoke("未选择", "请先勾选要卸载的版本", InfoBarSeverity.Warning);
            return;
        }
        var dlg = new ContentDialog
        {
            Title = "确认卸载",
            Content = "将卸载 " + selected.Count + " 个版本：\n" + string.Join("\n", selected),
            PrimaryButtonText = "确定",
            CloseButtonText = "取消",
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        foreach (var spec in selected)
        {
            try { await AppServices.Client.CallAsync("uninstall_version", new { spec }); }
            catch (Exception ex) { AppServices.Toast?.Invoke("卸载失败", ex.Message, InfoBarSeverity.Error); }
        }
        await ReloadInstalled();
    }
}
