using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;

namespace PyMCL.Services;

public static class CrashUi
{
    public static async Task ShowAsync(FrameworkElement host, CrashReport report)
    {
        report ??= new CrashReport();
        var title = string.IsNullOrWhiteSpace(report.Title) ? "Minecraft 出现错误" : report.Title;
        var detail = string.IsNullOrWhiteSpace(report.Detail) ? report.Summary : report.Detail;
        var help = string.IsNullOrWhiteSpace(report.Help)
            ? "如果要寻求帮助，请把错误报告文件发给对方，而不是发送这个窗口的照片或者截图。"
            : report.Help;

        var box = new StackPanel { Spacing = 10, MaxWidth = 640 };
        if (!string.IsNullOrWhiteSpace(report.Headline) && report.Headline != title)
            box.Children.Add(new TextBlock { Text = report.Headline, TextWrapping = TextWrapping.Wrap, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        if (!string.IsNullOrWhiteSpace(report.ExitHint))
            box.Children.Add(new TextBlock { Text = report.ExitHint, TextWrapping = TextWrapping.Wrap, Opacity = 0.8 });
        box.Children.Add(new TextBlock
        {
            Text = detail ?? "",
            TextWrapping = TextWrapping.Wrap,
            IsTextSelectionEnabled = true,
        });
        box.Children.Add(new TextBlock
        {
            Text = help,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 12,
            Opacity = 0.78,
        });

        var dlg = new ContentDialog
        {
            Title = title,
            Content = new ScrollViewer
            {
                Content = box,
                MaxHeight = 440,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            },
            PrimaryButtonText = "确定",
            SecondaryButtonText = string.IsNullOrWhiteSpace(report.DirectFile) ? "" : "查看输出",
            CloseButtonText = "导出错误报告",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = host.XamlRoot,
        };

        var result = await dlg.ShowAsync();
        if (result == ContentDialogResult.Secondary)
            await OpenAsync(report);
        else if (result == ContentDialogResult.None)
            await ExportAsync(report);
    }

    public static CrashReport FromLaunchFail(string message) => new()
    {
        Title = "启动失败",
        Headline = "启动中止",
        Detail = string.IsNullOrWhiteSpace(message) ? "启动失败" : message,
        Help = "这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。",
    };

    private static async Task OpenAsync(CrashReport report)
    {
        if (AppServices.Client is null) return;
        try
        {
            await AppServices.Client.CallAsync("open_crash_file", new
            {
                path = report.DirectFile,
                task_id = report.TaskId,
            });
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("无法打开", ex.Message, InfoBarSeverity.Error);
        }
    }

    private static async Task ExportAsync(CrashReport report)
    {
        if (AppServices.Client is null) return;
        try
        {
            var path = await AppServices.Client.CallAsync<string>("export_crash_report", new { task_id = report.TaskId });
            if (!string.IsNullOrEmpty(path))
            {
                await AppServices.Client.CallAsync("open_crash_file", new { path });
                AppServices.Toast?.Invoke("错误报告已导出", path, InfoBarSeverity.Success);
            }
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("导出失败", ex.Message, InfoBarSeverity.Error);
        }
    }
}
