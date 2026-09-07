using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public partial class LaunchPage : UserControl
{
    public LaunchPage()
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
            var names = new List<string>();
            if (el.ValueKind == JsonValueKind.Array)
            {
                foreach (var x in el.EnumerateArray())
                {
                    if (x.ValueKind == JsonValueKind.String) names.Add(x.GetString() ?? "");
                    else if (x.TryGetProperty("name", out var n)) names.Add(n.GetString() ?? "");
                }
            }
            InstanceBox.ItemsSource = names;
            if (InstanceBox.Items.Count > 0 && InstanceBox.SelectedIndex < 0)
                InstanceBox.SelectedIndex = 0;
            var acc = await AppServices.Client.CallAsync<List<string>>("get_accounts") ?? new();
            AccountBox.ItemsSource = acc;
            if (AccountBox.Items.Count > 0) AccountBox.SelectedIndex = 0;
            await LoadVersionsAsync();
            InstanceBox.SelectionChanged -= InstanceChanged;
            InstanceBox.SelectionChanged += InstanceChanged;
        }
        catch (Exception ex)
        {
            Hint.Text = "加载失败: " + ex.Message;
        }
    }

    private async void InstanceChanged(object sender, SelectionChangedEventArgs e) => await LoadVersionsAsync();

    private async Task LoadVersionsAsync()
    {
        var inst = InstanceBox.SelectedItem as string ?? "default";
        var vers = await AppServices.Client.CallAsync<List<string>>("get_installed_versions", new { instance = inst }) ?? new();
        VersionBox.ItemsSource = vers;
        if (VersionBox.Items.Count > 0) VersionBox.SelectedIndex = 0;
    }

    private async void Launch_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var inst = InstanceBox.SelectedItem as string ?? "default";
            var ver = VersionBox.SelectedItem as string ?? "";
            var acc = AccountBox.SelectedItem as string ?? "离线模式";
            if (string.IsNullOrWhiteSpace(ver))
            {
                MessageBox.Show("请先安装并选择版本", "PyMCL");
                return;
            }
            _ = int.TryParse(MemoryBox.Text, out var mem);
            if (mem < 512) mem = 4096;
            var tid = await AppServices.Client.StartTaskAsync("launch_game", new
            {
                instance = inst,
                version = ver,
                account = acc,
                username = UserNameBox.Text?.Trim() ?? "Player",
                memory_mb = mem,
                width = 854,
                height = 480,
                java = "自动选择",
            });
            Hint.Text = "已开始启动，任务 " + tid;
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "启动失败");
        }
    }

}
