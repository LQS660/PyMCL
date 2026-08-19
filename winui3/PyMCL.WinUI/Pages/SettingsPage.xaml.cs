using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class SettingsPage : UserControl
{
    public SettingsPage()
    {
        InitializeComponent();
        Loaded += OnFirstLoaded;
    }

    private void Page_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (PageRoot is null) return;
        var pad = e.NewSize.Width < 640 ? new Thickness(12, 10, 12, 10) : new Thickness(28, 20, 28, 20);
        if (PageRoot.Padding != pad) PageRoot.Padding = pad;
    }

    private void OnFirstLoaded(object sender, RoutedEventArgs e)
    {
        Loaded -= OnFirstLoaded;
        Motion.EnableHoverLift(CardStorage, 1.02);
        Motion.EnableHoverLift(CardPerf, 1.02);
        Motion.EnableHoverLift(CardAccount, 1.02);
        Motion.EnableHoverLift(CardAi, 1.02);
        AiModeBox.SelectionChanged += (_, _) => SyncAiMode();
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        var s = await AppServices.Client.CallAsync<SettingsDto>("get_settings");
        if (s is null) return;
        ShareLibs.IsOn = s.ShareLibraries;
        ShareAssets.IsOn = s.ShareAssets;
        ThreadsSpin.Value = s.DownloadThreads;
        MemorySpin.Value = s.DefaultMemoryMb;
        if (s.DefaultResolution is { Count: >= 2 })
        {
            WidthSpin.Value = s.DefaultResolution[0];
            HeightSpin.Value = s.DefaultResolution[1];
        }
        MsClient.Text = s.MsClientId;
        CurseKey.Password = s.CurseforgeApiKey;
        AiGateway.Text = s.AiGatewayUrl;
        AiBase.Text = s.AiBaseUrl;
        AiKey.Password = s.AiApiKey;
        AiModel.Text = s.AiModel;
        AiModeBox.SelectedIndex = s.AiMode == "custom" ? 1 : 0;
        SyncAiMode();
        RootLabel.Text = "启动器主目录: " + s.Root;
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            await AppServices.Client.CallAsync("save_settings", new
            {
                data = new
                {
                    share_libraries = ShareLibs.IsOn,
                    share_assets = ShareAssets.IsOn,
                    download_threads = (int)ThreadsSpin.Value,
                    default_memory_mb = (int)MemorySpin.Value,
                    default_resolution = new[] { (int)WidthSpin.Value, (int)HeightSpin.Value },
                    ms_client_id = MsClient.Text?.Trim() ?? "",
                    curseforge_api_key = CurseKey.Password?.Trim() ?? "",
                    ai_mode = (AiModeBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "public",
                    ai_gateway_url = AiGateway.Text?.Trim() ?? "",
                    ai_base_url = AiBase.Text?.Trim() ?? "",
                    ai_api_key = AiKey.Password?.Trim() ?? "",
                    ai_model = string.IsNullOrWhiteSpace(AiModel.Text) ? "deepseek-v4-flash" : AiModel.Text.Trim(),
                },
            });
            AppServices.Toast?.Invoke("已保存", "设置已写入 config.json", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("保存失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private void SyncAiMode()
    {
        var custom = (AiModeBox.SelectedItem as ComboBoxItem)?.Tag as string == "custom";
        AiPublicPanel.Visibility = custom ? Visibility.Collapsed : Visibility.Visible;
        AiCustomPanel.Visibility = custom ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void TestAi_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            await AppServices.Client.CallAsync("save_settings", new
            {
                data = new
                {
                    share_libraries = ShareLibs.IsOn,
                    share_assets = ShareAssets.IsOn,
                    download_threads = (int)ThreadsSpin.Value,
                    default_memory_mb = (int)MemorySpin.Value,
                    default_resolution = new[] { (int)WidthSpin.Value, (int)HeightSpin.Value },
                    ms_client_id = MsClient.Text?.Trim() ?? "",
                    curseforge_api_key = CurseKey.Password?.Trim() ?? "",
                    ai_mode = (AiModeBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "public",
                    ai_gateway_url = AiGateway.Text?.Trim() ?? "",
                    ai_base_url = AiBase.Text?.Trim() ?? "",
                    ai_api_key = AiKey.Password?.Trim() ?? "",
                    ai_model = string.IsNullOrWhiteSpace(AiModel.Text) ? "deepseek-v4-flash" : AiModel.Text.Trim(),
                },
            });
            var msg = await AppServices.Client.CallAsync<string>("test_ai_connection");
            AppServices.Toast?.Invoke("AI 连接成功", msg ?? "已连通", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("AI 连接失败", ex.Message, InfoBarSeverity.Error);
        }
    }
}
