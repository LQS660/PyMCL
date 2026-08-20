using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class AccountPage : UserControl
{
    public AccountPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ReloadAsync();
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        var rows = await AppServices.Client.CallAsync<List<AccountRow>>("get_account_rows") ?? new();
        ListHost.Children.Clear();
        if (rows.Count == 0)
            ListHost.Children.Add(new TextBlock { Text = "还没有正版或皮肤站账号", Opacity = 0.7 });
        foreach (var row in rows)
        {
            var bar = new Grid { ColumnSpacing = 8 };
            bar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var title = row.Name + (row.Active ? "  · 当前" : "") + "  ·  " + row.Type;
            bar.Children.Add(new TextBlock { Text = title, VerticalAlignment = VerticalAlignment.Center });
            var use = new Button { Content = "使用" };
            use.Click += async (_, _) =>
            {
                try { await AppServices.Client.CallAsync("set_active_account", new { name = row.Name }); await ReloadAsync(); }
                catch (Exception ex) { AppServices.Toast?.Invoke("切换失败", ex.Message, InfoBarSeverity.Error); }
            };
            var del = new Button { Content = "删除" };
            del.Click += async (_, _) =>
            {
                try { await AppServices.Client.CallAsync("remove_account", new { name = row.Name }); await ReloadAsync(); }
                catch (Exception ex) { AppServices.Toast?.Invoke("删除失败", ex.Message, InfoBarSeverity.Error); }
            };
            Grid.SetColumn(use, 2);
            Grid.SetColumn(del, 3);
            bar.Children.Add(use);
            bar.Children.Add(del);
            ListHost.Children.Add(bar);
        }
        try
        {
            var presets = await AppServices.Client.CallAsync<List<AuthlibPreset>>("authlib_presets") ?? new();
            var first = presets.FirstOrDefault(p => !string.IsNullOrEmpty(p.Api));
            if (first != null && string.IsNullOrWhiteSpace(ApiBox.Text)) ApiBox.Text = first.Api;
        }
        catch { }
    }

    private async void Ms_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try { await AppServices.Client.StartTaskAsync("start_microsoft_login"); }
        catch (Exception ex) { AppServices.Toast?.Invoke("登录失败", ex.Message, InfoBarSeverity.Error); }
    }

    private async void Authlib_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            await AppServices.Client.StartTaskAsync("start_authlib_login", new
            {
                api = ApiBox.Text?.Trim() ?? "",
                username = UserBox.Text?.Trim() ?? "",
                password = PwBox.Password ?? "",
            });
        }
        catch (Exception ex) { AppServices.Toast?.Invoke("登录失败", ex.Message, InfoBarSeverity.Error); }
    }

    private async void Offline_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var name = OfflineBox.Text?.Trim() ?? "";
        if (string.IsNullOrEmpty(name))
        {
            AppServices.Toast?.Invoke("缺少名字", "请填写离线角色名", InfoBarSeverity.Warning);
            return;
        }
        try { await AppServices.Client.CallAsync("add_offline_account", new { username = name }); await ReloadAsync(); }
        catch (Exception ex) { AppServices.Toast?.Invoke("保存失败", ex.Message, InfoBarSeverity.Error); }
    }
}
