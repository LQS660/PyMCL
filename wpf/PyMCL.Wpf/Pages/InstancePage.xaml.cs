using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public partial class InstancePage : UserControl
{
    public InstancePage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ReloadAsync();
    }

    private async void Reload_Click(object sender, RoutedEventArgs e) => await ReloadAsync();

    private async Task ReloadAsync()
    {
        try
        {
            var el = await AppServices.Client.CallAsync("get_instances");
            var items = new List<string>();
            if (el.ValueKind == JsonValueKind.Array)
            {
                foreach (var x in el.EnumerateArray())
                {
                    if (x.ValueKind == JsonValueKind.String) items.Add(x.GetString() ?? "");
                    else if (x.TryGetProperty("name", out var n)) items.Add(n.GetString() ?? "");
                    else items.Add(x.ToString());
                }
            }
            List.ItemsSource = items;
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message);
        }
    }
}
