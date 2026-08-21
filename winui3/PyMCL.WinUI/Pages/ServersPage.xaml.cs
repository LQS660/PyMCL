using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class ServersPage : UserControl
{
    private readonly List<ServerRow> _rows = new();
    private bool _loading;

    public ServersPage()
    {
        InitializeComponent();
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        _loading = true;
        try
        {
            var insts = await AppServices.Client.CallAsync<List<InstanceInfo>>("get_instances") ?? new();
            var names = insts.Select(i => i.Name).Where(n => !string.IsNullOrWhiteSpace(n)).ToList();
            var cur = InstanceBox.SelectedItem as string;
            InstanceBox.ItemsSource = names;
            if (!string.IsNullOrWhiteSpace(cur) && names.Contains(cur))
                InstanceBox.SelectedItem = cur;
            else if (names.Count > 0)
                InstanceBox.SelectedIndex = 0;
            await LoadServersAsync();
        }
        finally
        {
            _loading = false;
        }
    }

    private async void InstanceBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        await LoadServersAsync();
    }

    private async Task LoadServersAsync()
    {
        if (AppServices.Client is null) return;
        var inst = InstanceBox.SelectedItem as string ?? "";
        var raw = await AppServices.Client.CallAsync<List<ServerRow>>("list_servers",
            new { instance = inst }) ?? new();
        _rows.Clear();
        _rows.AddRange(raw);
        ServerList.ItemsSource = null;
        ServerList.ItemsSource = _rows;
        Empty.Visibility = _rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void Add_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var inst = InstanceBox.SelectedItem as string ?? "";
        if (string.IsNullOrWhiteSpace(inst))
        {
            AppServices.Toast?.Invoke("缺少实例", "请先创建或选择一个实例", InfoBarSeverity.Warning);
            return;
        }
        var nameBox = new TextBox { PlaceholderText = "服务器名称（可选）" };
        var ipBox = new TextBox { PlaceholderText = "example.com 或 IP" };
        var portBox = new TextBox { PlaceholderText = "25565", Text = "25565" };
        var panel = new StackPanel { Spacing = 8 };
        panel.Children.Add(nameBox);
        panel.Children.Add(ipBox);
        panel.Children.Add(portBox);
        var dlg = new ContentDialog
        {
            Title = "添加服务器",
            Content = panel,
            PrimaryButtonText = "添加",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
        var ip = ipBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(ip))
        {
            AppServices.Toast?.Invoke("缺少地址", "请填写服务器地址", InfoBarSeverity.Error);
            return;
        }
        if (!int.TryParse(portBox.Text.Trim(), out var port) || port < 1 || port > 65535)
            port = 25565;
        try
        {
            await AppServices.Client.CallAsync("add_server", new
            {
                instance = inst,
                name = nameBox.Text.Trim(),
                ip,
                port,
            });
            await LoadServersAsync();
            AppServices.Toast?.Invoke("已添加", "服务器已加入列表", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("添加失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var idx = ServerList.SelectedIndex;
        if (idx < 0 || idx >= _rows.Count)
        {
            AppServices.Toast?.Invoke("未选择", "请先选中要删除的服务器", InfoBarSeverity.Warning);
            return;
        }
        var row = _rows[idx];
        var inst = InstanceBox.SelectedItem as string ?? "";
        if (!await Dialogs.ConfirmAsync(XamlRoot, "确认删除", $"删除服务器 {(!string.IsNullOrWhiteSpace(row.Name) ? row.Name : row.Ip)}？"))
            return;
        try
        {
            await AppServices.Client.CallAsync("delete_server", new { instance = inst, index = idx });
            await LoadServersAsync();
            AppServices.Toast?.Invoke("已删除", "", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("删除失败", ex.Message, InfoBarSeverity.Error);
        }
    }
}
