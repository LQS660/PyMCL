using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PyMCL.Models;
using PyMCL.Services;
using Windows.UI;

namespace PyMCL.Pages;

public sealed partial class JavaPage : UserControl
{
    private int _dlCols = -1;

    public JavaPage()
    {
        InitializeComponent();
        Loaded += (_, _) => ApplyDlLayout(ActualWidth);
    }

    private void Page_SizeChanged(object sender, SizeChangedEventArgs e) => ApplyDlLayout(e.NewSize.Width);

    private void ApplyDlLayout(double width)
    {
        if (DlGrid is null) return;
        var pad = width < 640 ? new Thickness(12, 10, 12, 10) : new Thickness(28, 20, 28, 20);
        if (PageRoot.Padding != pad) PageRoot.Padding = pad;
        var cols = width < 520 ? 1 : width < 780 ? 2 : 4;
        if (cols == _dlCols) return;
        _dlCols = cols;
        for (var i = 0; i < DlGrid.ColumnDefinitions.Count; i++)
            DlGrid.ColumnDefinitions[i].Width = i < cols ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
        var cards = new[] { Dl8Card, Dl11Card, Dl17Card, Dl21Card };
        for (var i = 0; i < cards.Length; i++)
        {
            Grid.SetColumn(cards[i], i % cols);
            Grid.SetRow(cards[i], i / cols);
        }
    }

    public async Task ReloadAsync(bool scanSystem)
    {
        if (AppServices.Client is null) return;
        var local = await AppServices.Client.CallAsync<List<JavaInfo>>("get_java_list", new { scan_system = false }) ?? new();
        Fill(local);
        if (!scanSystem) return;
        try
        {
            var all = await AppServices.Client.CallAsync<List<JavaInfo>>("get_java_list", new { scan_system = true }) ?? new();
            Fill(all);
        }
        catch { }
    }

    private void Fill(List<JavaInfo> javas)
    {
        EnvList.Children.Clear();
        if (javas.Count == 0)
        {
            EnvList.Children.Add(new TextBlock { Text = "未检测到 Java，请从下方下载", Foreground = ThemeBrushes.Mute });
            return;
        }
        foreach (var j in javas)
        {
            var card = new Border
            {
                Height = 76, Padding = new Thickness(16, 12, 16, 12),
                Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
                BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
                Translation = new System.Numerics.Vector3(0, 0, 16),
                Shadow = new ThemeShadow(),
            };
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.Children.Add(new Border
            {
                Width = 46, Height = 46, CornerRadius = new CornerRadius(10),
                Background = new SolidColorBrush(Color.FromArgb(255, 232, 134, 46)),
                Child = new TextBlock { Text = "J", Foreground = new SolidColorBrush(Microsoft.UI.Colors.White), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, FontWeight = Microsoft.UI.Text.FontWeights.Bold },
            });
            var info = new StackPanel { Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
            var title = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            title.Children.Add(new TextBlock { Text = "Java " + j.Major, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
            title.Children.Add(new TextBlock { Text = "可用", Foreground = new SolidColorBrush(Color.FromArgb(255, 47, 163, 107)), FontSize = 12 });
            info.Children.Add(title);
            info.Children.Add(new TextBlock { Text = string.IsNullOrEmpty(j.Path) ? j.Name : j.Path, Foreground = ThemeBrushes.Mute, FontSize = 12, TextWrapping = TextWrapping.Wrap });
            Grid.SetColumn(info, 1);
            g.Children.Add(info);
            card.Child = g;
            Motion.CardEnter(card, Math.Min(EnvList.Children.Count, 10) * 40);
            EnvList.Children.Add(card);
        }
    }

    private void Refresh_Click(object sender, RoutedEventArgs e) => _ = ReloadAsync(true);
    private void Dl8(object sender, RoutedEventArgs e) => _ = Download("8");
    private void Dl11(object sender, RoutedEventArgs e) => _ = Download("11");
    private void Dl17(object sender, RoutedEventArgs e) => _ = Download("17");
    private void Dl21(object sender, RoutedEventArgs e) => _ = Download("21");

    private async Task Download(string major)
    {
        if (AppServices.Client is null) return;
        AppServices.FlyToTasks?.Invoke(this, "J", "#E8862E");
        try { await AppServices.Client.StartTaskAsync("download_java", new { major }); }
        catch (Exception ex) { AppServices.Toast?.Invoke("下载失败", ex.Message, InfoBarSeverity.Error); }
    }
}
