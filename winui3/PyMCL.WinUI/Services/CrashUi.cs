using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;

namespace PyMCL.Services;

public static class CrashUi
{
    /// <summary>返回 true 表示用户点了「重新启动」。</summary>
    public static async Task<bool> ShowAsync(FrameworkElement host, CrashReport report)
    {
        report ??= new CrashReport();
        var title = string.IsNullOrWhiteSpace(report.Title) ? "Minecraft 出现错误" : report.Title;
        var detail = string.IsNullOrWhiteSpace(report.Detail) ? report.Summary : report.Detail;
        var help = string.IsNullOrWhiteSpace(report.Help)
            ? "如果要寻求帮助，请把错误报告文件发给对方，而不是发送这个窗口的照片或者截图。"
            : report.Help;
        var canRelaunch = !string.IsNullOrWhiteSpace(report.Instance) && !string.IsNullOrWhiteSpace(report.Version);

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

        if (report.Actions is { Count: > 0 })
        {
            box.Children.Add(new TextBlock
            {
                Text = "建议操作",
                FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                Margin = new Thickness(0, 6, 0, 0),
            });
            var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            foreach (var action in report.Actions)
            {
                var act = action;
                var btn = new Button { Content = string.IsNullOrWhiteSpace(act.Label) ? act.Id : act.Label };
                btn.Click += async (_, __) =>
                {
                    btn.IsEnabled = false;
                    try
                    {
                        if (AppServices.Client is null) return;
                        var result = await AppServices.Client.CallAsync<CrashActionResult>(
                            "apply_crash_action",
                            new { action = act, report });
                        if (result?.Ok == true)
                        {
                            AppServices.Toast?.Invoke("已处理", result.Message ?? "完成", InfoBarSeverity.Success);
                            btn.Content = "已执行";
                        }
                        else
                        {
                            btn.IsEnabled = true;
                            AppServices.Toast?.Invoke("操作失败", result?.Message ?? "未知错误", InfoBarSeverity.Error);
                        }
                    }
                    catch (Exception ex)
                    {
                        btn.IsEnabled = true;
                        AppServices.Toast?.Invoke("操作失败", ex.Message, InfoBarSeverity.Error);
                    }
                };
                row.Children.Add(btn);
            }
            box.Children.Add(row);
        }

        var dlg = new ContentDialog
        {
            Title = title,
            Content = new ScrollViewer
            {
                Content = box,
                MaxHeight = 480,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            },
            PrimaryButtonText = canRelaunch ? "重新启动" : "确定",
            SecondaryButtonText = string.IsNullOrWhiteSpace(report.DirectFile) ? "" : "查看输出",
            CloseButtonText = canRelaunch ? "确定" : "导出错误报告",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = host.XamlRoot,
        };
        // 有重新启动时，导出放到 Secondary 旁边不够，改用 Close=确定、另加导出到 Secondary 若无文件则 Close=导出
        if (canRelaunch && !string.IsNullOrWhiteSpace(report.DirectFile))
        {
            dlg.SecondaryButtonText = "查看输出";
            dlg.CloseButtonText = "确定";
        }
        else if (canRelaunch)
        {
            dlg.SecondaryButtonText = "导出错误报告";
            dlg.CloseButtonText = "确定";
        }

        var result = await dlg.ShowAsync();
        if (result == ContentDialogResult.Primary && canRelaunch)
            return true;
        if (result == ContentDialogResult.Secondary)
        {
            if (!string.IsNullOrWhiteSpace(report.DirectFile))
                await OpenAsync(report);
            else
                await ExportAsync(report);
        }
        else if (result == ContentDialogResult.None && !canRelaunch)
            await ExportAsync(report);
        return false;
    }

    public static CrashReport FromLaunchFail(string message, string? instance = null, string? version = null) => new()
    {
        Title = "启动失败",
        Headline = "启动中止",
        Detail = string.IsNullOrWhiteSpace(message) ? "启动失败" : message,
        Help = "这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。",
        Instance = instance ?? "",
        Version = version ?? "",
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
