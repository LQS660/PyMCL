using System.Text.Json;
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
        if (IsoBox != null)
        {
            IsoBox.SelectedIndex = s.DefaultIsolation == "all" ? 3 : s.DefaultIsolation == "mods" ? 2 : s.DefaultIsolation == "saves" ? 1 : 0;
        }
        if (JvmEdit != null) JvmEdit.Text = s.DefaultJvmArgs ?? "";
        if (VisBox != null)
            VisBox.SelectedIndex = s.LauncherVisibility switch { "minimize" => 1, "hide" => 2, "hide_reopen" => 3, "close" => 4, _ => 0 };
        if (GcBox != null)
            GcBox.SelectedIndex = s.GcPreset switch { "g1" => 1, "g1_tuned" => 2, "zgc" => 3, "none" => 4, _ => 0 };
        if (SourceBox != null)
            SourceBox.SelectedIndex = s.DownloadSource switch { "official" => 1, "bmclapi" => 2, _ => 0 };
        if (LimitSpin != null) LimitSpin.Value = s.DownloadLimitKbps;
        if (HomeBox != null)
            HomeBox.SelectedIndex = s.HomepageMode == "custom" ? 1 : s.HomepageMode == "blank" ? 2 : 0;
        if (HomePath != null) HomePath.Text = s.CustomHomepage ?? "";
        if (AutoUpd != null) AutoUpd.IsOn = s.AutoCheckUpdate;
        if (FlyAnimSw != null) FlyAnimSw.IsOn = s.UiFlyAnimation;
        if (FlyDurSpin != null) FlyDurSpin.Value = s.UiFlyDurationMs > 0 ? s.UiFlyDurationMs : 620;
        RootLabel.Text = "启动器主目录: " + s.Root;
    }

    /// <summary>
    /// 清空 NumberBox 会让 Value 变成 double.NaN，直接 (int) 强转得到 0。
    /// 线程数/内存那两个键后端有 <c>or 8</c> 之类的兜底，但分辨率是裸 <c>int(res[0])</c>——
    /// 用户把宽度框一清再保存，config.json 里就真躺着 width=0，游戏拿到 --width 0。
    /// </summary>
    private static int SpinValue(NumberBox box, int fallback)
    {
        var v = box?.Value ?? double.NaN;
        if (double.IsNaN(v) || double.IsInfinity(v)) return fallback;
        return (int)Math.Round(v);
    }

    private static string TagOf(ComboBox box, string fallback) =>
        (box?.SelectedItem as ComboBoxItem)?.Tag as string ?? fallback;

    /// <summary>AI 相关的键单独打包：测试连接只需要这一组，不该把整页设置一并落盘。</summary>
    private object BuildAiPatch() => new
    {
        ai_mode = TagOf(AiModeBox, "public"),
        ai_gateway_url = AiGateway.Text?.Trim() ?? "",
        ai_base_url = AiBase.Text?.Trim() ?? "",
        ai_api_key = AiKey.Password?.Trim() ?? "",
        ai_model = string.IsNullOrWhiteSpace(AiModel.Text) ? "deepseek-v4-flash" : AiModel.Text.Trim(),
    };

    /// <summary>
    /// 提交空串时后端按「沿用旧值 / 回落到默认」处理，本来就不该等于空串的键。
    /// 对这些键不回读对账，免得把「清空 = 用默认」误报成「没写进去」。
    /// （bridge/api.py 与 native/src/settings.c 两侧都是这个语义。）
    /// </summary>
    private static readonly HashSet<string> EmptyMeansFallback = new(StringComparer.Ordinal)
    {
        "ms_client_id", "ai_gateway_url", "ai_model",
    };

    /// <summary>
    /// 保存后回读校验。桥（尤其 C 桥）对白名单外的键是「静默忽略 + 返回成功」，
    /// 前端只看返回值就会弹绿色「已保存」而用户改的东西其实没落盘。这里拿刚提交的值
    /// 跟 get_settings 回读的结果逐键比，把对不上的键名报给用户，不再假装成功。
    /// </summary>
    private async Task<List<string>> VerifyAsync(object sent)
    {
        var missed = new List<string>();
        if (AppServices.Client is null) return missed;
        var after = await AppServices.Client.CallAsync<Dictionary<string, JsonElement>>("get_settings");
        if (after is null) return missed;
        var sentJson = JsonSerializer.SerializeToElement(sent, BridgeClient.JsonOpt);
        if (sentJson.ValueKind != JsonValueKind.Object) return missed;
        foreach (var kv in sentJson.EnumerateObject())
        {
            if (!after.TryGetValue(kv.Name, out var got)) continue;   // 桥不返回的键无从对账，跳过
            var want = kv.Value;
            if (want.ValueKind == JsonValueKind.String
                && string.IsNullOrEmpty(want.GetString())
                && EmptyMeansFallback.Contains(kv.Name))
                continue;
            var same = want.ValueKind switch
            {
                JsonValueKind.Array => ArrayEquals(want, got),
                JsonValueKind.True or JsonValueKind.False => IsTrue(got) == (want.ValueKind == JsonValueKind.True),
                JsonValueKind.Number => got.ValueKind == JsonValueKind.Number
                    ? Math.Abs(got.GetDouble() - want.GetDouble()) < 0.001
                    : false,
                JsonValueKind.String => got.ValueKind == JsonValueKind.String
                    && string.Equals(got.GetString(), want.GetString(), StringComparison.Ordinal),
                _ => true,
            };
            if (!same) missed.Add(kv.Name);
        }
        return missed;
    }

    private static bool ArrayEquals(JsonElement want, JsonElement got)
    {
        if (got.ValueKind != JsonValueKind.Array || got.GetArrayLength() != want.GetArrayLength())
            return false;
        var a = want.EnumerateArray().ToList();
        var b = got.EnumerateArray().ToList();
        for (var i = 0; i < a.Count; i++)
        {
            if (a[i].ValueKind == JsonValueKind.Number && b[i].ValueKind == JsonValueKind.Number)
            {
                if (Math.Abs(a[i].GetDouble() - b[i].GetDouble()) > 0.001) return false;
            }
            else if (a[i].ToString() != b[i].ToString()) return false;
        }
        return true;
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            // 键名与 bridge/api.py 的 save_settings 白名单逐键对齐（Python 是权威）；
            // 桥写不进去的键由下面的回读校验抓出来，不再无条件报「已保存」。
            var payload = new
            {
                share_libraries = ShareLibs.IsOn,
                share_assets = ShareAssets.IsOn,
                download_threads = SpinValue(ThreadsSpin, 8),
                default_memory_mb = SpinValue(MemorySpin, 4096),
                default_resolution = new[] { SpinValue(WidthSpin, 854), SpinValue(HeightSpin, 480) },
                ms_client_id = MsClient.Text?.Trim() ?? "",
                curseforge_api_key = CurseKey.Password?.Trim() ?? "",
                ai_mode = TagOf(AiModeBox, "public"),
                ai_gateway_url = AiGateway.Text?.Trim() ?? "",
                ai_base_url = AiBase.Text?.Trim() ?? "",
                ai_api_key = AiKey.Password?.Trim() ?? "",
                ai_model = string.IsNullOrWhiteSpace(AiModel.Text) ? "deepseek-v4-flash" : AiModel.Text.Trim(),
                default_isolation = TagOf(IsoBox, "none"),
                default_jvm_args = JvmEdit?.Text?.Trim() ?? "",
                launcher_visibility = TagOf(VisBox, "keep"),
                gc_preset = TagOf(GcBox, "auto"),
                download_source = TagOf(SourceBox, "auto"),
                download_limit_kbps = SpinValue(LimitSpin, 0),
                homepage_mode = TagOf(HomeBox, "news"),
                custom_homepage = HomePath?.Text?.Trim() ?? "",
                auto_check_update = AutoUpd.IsOn,
                ui_fly_animation = FlyAnimSw?.IsOn ?? true,
                ui_fly_duration_ms = SpinValue(FlyDurSpin, 620),
            };
            await AppServices.Client.CallAsync("save_settings", new { data = payload });
            var missed = await VerifyAsync(payload);
            if (missed.Count == 0)
                AppServices.Toast?.Invoke("已保存", "设置已写入 config.json", InfoBarSeverity.Success);
            else
                AppServices.Toast?.Invoke("部分设置未生效",
                    "后端没有写入这些键：" + string.Join("、", missed)
                    + "。当前桥可能尚未支持，设置会在重启后回退。",
                    InfoBarSeverity.Warning);
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
            // 只写 AI 那几个键。以前这里连 share_libraries / 线程数 / 内存 / 分辨率 /
            // 微软 ClientID / CurseForge 密钥一起落盘——用户只是想点一下「测试连接」，
            // 结果页面上还没想好的改动被永久写进 config.json，想反悔都没得反悔。
            await AppServices.Client.CallAsync("save_settings", new { data = BuildAiPatch() });
            var msg = await AppServices.Client.CallAsync<string>("test_ai_connection");
            AppServices.Toast?.Invoke("AI 连接成功", msg ?? "已连通", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("AI 连接失败", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void Update_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            var info = await AppServices.Client.CallAsync<Dictionary<string, object>>("check_update") ?? new();
            // CallAsync<Dictionary<string, object>> 反序列化出来的值是 JsonElement，不是 bool，
            // `h is bool b` 恒 false → 这里以前永远报「已是最新」、start_self_update 永不触发。
            var has = info.TryGetValue("has_update", out var h) && IsTrue(h);
            var msg = info.TryGetValue("message", out var m) ? m?.ToString() ?? "" : "";
            if (has)
            {
                await AppServices.Client.StartTaskAsync("start_self_update");
                AppServices.Toast?.Invoke("发现更新", msg, InfoBarSeverity.Success);
            }
            else AppServices.Toast?.Invoke("检查更新", string.IsNullOrEmpty(msg) ? "已是最新" : msg, InfoBarSeverity.Informational);
        }
        catch (Exception ex) { AppServices.Toast?.Invoke("检查失败", ex.Message, InfoBarSeverity.Error); }
    }

    /// <summary>JSON 布尔判定：JsonElement（反序列化到 object 的常态）与字符串都认。</summary>
    private static bool IsTrue(object? v) => v switch
    {
        bool b => b,
        JsonElement je => je.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.String => je.GetString() is { } s && s.Equals("true", StringComparison.OrdinalIgnoreCase),
            _ => false,
        },
        string s => s.Equals("true", StringComparison.OrdinalIgnoreCase),
        _ => false,
    };

    private async void Clean_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try
        {
            var preview = await AppServices.Client.CallAsync<Dictionary<string, object>>("cleaner_preview") ?? new();
            var n = preview.TryGetValue("count", out var c) ? c?.ToString() : "0";
            var dlg = new ContentDialog
            {
                Title = "清理文件",
                Content = "将删除未引用库 / .part / 更新缓存，共 " + n + " 个",
                PrimaryButtonText = "清理",
                CloseButtonText = "取消",
                XamlRoot = XamlRoot,
            };
            if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;
            var result = await AppServices.Client.CallAsync<Dictionary<string, object>>("cleaner_apply") ?? new();
            AppServices.Toast?.Invoke("清理完成", "删除 " + (result.TryGetValue("removed", out var r) ? r : 0) + " 个文件", InfoBarSeverity.Success);
        }
        catch (Exception ex) { AppServices.Toast?.Invoke("清理失败", ex.Message, InfoBarSeverity.Error); }
    }

    private async void GlobalMods_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try { await AppServices.Client.CallAsync("open_global_mods"); }
        catch (Exception ex) { AppServices.Toast?.Invoke("打开失败", ex.Message, InfoBarSeverity.Error); }
    }
}
