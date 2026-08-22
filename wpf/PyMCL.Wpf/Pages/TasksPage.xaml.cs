using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public partial class TasksPage : UserControl
{
    public TasksPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ReloadAsync();
    }

    private async void Reload_Click(object sender, RoutedEventArgs e) => await ReloadAsync();

    private async Task ReloadAsync()
    {
        try
        {
            var el = await AppServices.Client.CallAsync("list_tasks");
            var rows = new List<string>();
            if (el.ValueKind == JsonValueKind.Array)
            {
                foreach (var x in el.EnumerateArray())
                {
                    var id = x.TryGetProperty("id", out var i) ? i.GetString() : "?";
                    var title = x.TryGetProperty("title", out var t) ? t.GetString() : "";
                    var st = x.TryGetProperty("status", out var s) ? s.GetString() : "";
                    rows.Add($"{id}  {st}  {title}");
                }
            }
            List.ItemsSource = rows.Count == 0 ? new[] { "（无任务）" } : rows;
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message);
        }
    }
}
