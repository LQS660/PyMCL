using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>全局设置。后端认识的键走 update_settings；ui_motion / 主题色 / 背景 / 飞入动画是 WPF 本地项，
/// 存 wpf-theme.json 并立即应用（桥接 save_settings 目前会丢弃这些键，一并提交以便后端补齐后生效）。</summary>
public sealed class SettingsPage : PageBase
{
    public override string Title => "设置";

    private const string DefaultColor = "#2E9B6B";

    // ---------------- 本地外观项（桥接后端暂不持久化的部分） ----------------
    internal sealed class ThemeExtras
    {
        public string ThemeColor { get; set; } = DefaultColor;
        public string Background { get; set; } = "default";
        public bool FlyAnimation { get; set; } = true;
        public int FlyDurationMs { get; set; } = 620;
    }

    internal static ThemeExtras Extras { get; } = LoadExtras();

    /// <summary>目录页「飞入下载任务」是否启用（同时受全局动效开关约束）。</summary>
    internal static bool FlyEnabled => Extras.FlyAnimation && Motion.Enabled;

    private static string ExtrasPath
    {
        get
        {
            string root;
            try { root = BridgeHost.FindRoot(); }
            catch { root = AppContext.BaseDirectory; }
            return Path.Combine(root, "wpf-theme.json");
        }
    }

    private static ThemeExtras LoadExtras()
    {
        try
        {
            if (File.Exists(ExtrasPath))
                return JsonSerializer.Deserialize<ThemeExtras>(File.ReadAllText(ExtrasPath)) ?? new ThemeExtras();
        }
        catch { }
        return new ThemeExtras();
    }

    private static void SaveExtras()
    {
        try { File.WriteAllText(ExtrasPath, JsonSerializer.Serialize(Extras, new JsonSerializerOptions { WriteIndented = true })); }
        catch { }
    }

    // ---------------- 控件 ----------------
    private sealed class Opt
    {
        public required string Key { get; init; }
        public required string Label { get; init; }
        public override string ToString() => Label;
    }

    private static ComboBox KeyCombo(IEnumerable<(string Key, string Label)> items, double width = 200)
    {
        var c = new ComboBox { Style = Ui.S("Combo"), Width = width };
        foreach (var (k, l) in items) c.Items.Add(new Opt { Key = k, Label = l });
        if (c.Items.Count > 0) c.SelectedIndex = 0;
        return c;
    }

    private static void SelectKey(ComboBox c, string key)
    {
        foreach (var item in c.Items)
            if (item is Opt o && o.Key == key)
            {
                c.SelectedItem = item;
                return;
            }
        if (c.Items.Count > 0) c.SelectedIndex = 0;
    }

    private static string KeyOf(ComboBox c) => (c.SelectedItem as Opt)?.Key ?? "";

    private static readonly (string Key, string Label)[] IsoOpts =
        { ("none", "关闭（共用实例目录）"), ("saves", "隔离存档"), ("mods", "隔离 Mod 与配置"), ("all", "隔离全部") };
    private static readonly (string Key, string Label)[] GcOpts =
        { ("auto", "G1（推荐）"), ("g1", "G1"), ("g1_tuned", "调优 G1"), ("zgc", "ZGC"), ("none", "不指定") };
    private static readonly (string Key, string Label)[] VisOpts =
        { ("keep", "保持显示"), ("minimize", "最小化"), ("hide", "隐藏"), ("hide_reopen", "隐藏，退出后重开"), ("close", "关闭启动器") };
    private static readonly (string Key, string Label)[] HomeOpts =
        { ("news", "Minecraft 新闻"), ("custom", "本地 HTML"), ("blank", "空白") };
    private static readonly (string Key, string Label)[] WinOpts =
        { ("window", "窗口"), ("maximize", "全屏") };
    private static readonly (string Key, string Label)[] SrcOpts =
        { ("auto", "自动（官方慢则走 BMCLAPI）"), ("official", "仅官方"), ("bmclapi", "仅 BMCLAPI") };
    private static readonly (string Key, string Label)[] CommOpts =
        { ("auto", "自动"), ("official", "仅官方"), ("mcim", "仅 MCIM") };
    private static readonly (string Key, string Label)[] BgOpts =
        { ("default", "默认"), ("eye", "护眼绿"), ("warm", "暖米"), ("mist", "雾蓝") };
    private static readonly (string Name, string Hex)[] Palette =
        { ("松绿", "#2E9B6B"), ("湛蓝", "#2F72C4"), ("紫罗兰", "#7C5CFC"), ("暖橙", "#D68A17"), ("绯红", "#D64545"), ("青碧", "#149B9B") };

    private readonly CheckBox _dark = Ui.Switch();
    private readonly CheckBox _motion = Ui.Switch(true);
    private readonly CheckBox _fly = Ui.Switch(true);
    private readonly Slider _flyDur = Ui.Sld(200, 1200, 620, 20);
    private readonly TextBlock _flyDurLbl = Ui.Txt("620 ms", 12, true);
    private readonly SPanel _swatches = Ui.H(8);
    private readonly ComboBox _bg = KeyCombo(BgOpts);
    private readonly Slider _threads = Ui.Sld(1, 64, 8, 1);
    private readonly TextBlock _threadsLbl = Ui.Txt("8", 12, true);
    private readonly ComboBox _src = KeyCombo(SrcOpts);
    private readonly ComboBox _comm = KeyCombo(CommOpts);
    private readonly CheckBox _proxy = Ui.Switch(true);
    private readonly TextBox _limit = Ui.Input("0", "0", 110);
    private readonly Slider _mem = Ui.Sld(512, 32768, 4096, 256);
    private readonly TextBlock _memLbl = Ui.Txt("4096 MB", 12, true);
    private readonly TextBox _w = Ui.Input("854", "854", 80);
    private readonly TextBox _h = Ui.Input("480", "480", 80);
    private readonly ComboBox _inst = Ui.Combo(width: 200);
    private readonly ComboBox _iso = KeyCombo(IsoOpts);
    private readonly ComboBox _gc = KeyCombo(GcOpts);
    private readonly ComboBox _win = KeyCombo(WinOpts);
    private readonly TextBox _jvm = Ui.Input("例如 -XX:+UseG1GC（可空）");
    private readonly CheckBox _shareLib = Ui.Switch();
    private readonly CheckBox _shareAssets = Ui.Switch();
    private readonly ComboBox _vis = KeyCombo(VisOpts);
    private readonly ComboBox _home = KeyCombo(HomeOpts);
    private readonly TextBox _homePath = Ui.Input("本地 .html 文件路径（主页选「本地 HTML」时生效）");
    private readonly CheckBox _autoUpdate = Ui.Switch(true);
    private readonly TextBox _updateUrl = Ui.Input("留空用默认更新源");
    private readonly ComboBox _lang = KeyCombo(Array.Empty<(string, string)>());
    private string _lang0 = "";
    private string _color = DefaultColor;
    private bool _sync;

    public SettingsPage()
    {
        _dark.Checked += (_, _) => { if (!_sync) ApplyDark(_dark.IsChecked == true); };
        _dark.Unchecked += (_, _) => { if (!_sync) ApplyDark(false); };
        _bg.SelectionChanged += (_, _) => { if (!_sync) ApplyVisuals(_color, KeyOf(_bg)); };
        _flyDur.ValueChanged += (_, e) => _flyDurLbl.Text = $"{(int)e.NewValue} ms";
        _threads.ValueChanged += (_, e) => _threadsLbl.Text = ((int)e.NewValue).ToString();
        _mem.ValueChanged += (_, e) => _memLbl.Text = $"{(int)e.NewValue} MB";

        BuildSwatches();

        var browseHome = Ui.Btn("浏览…", BtnKind.Chip, (_, _) =>
        {
            var p = Dlg.PickFile("网页 (*.html;*.htm)|*.html;*.htm|全部文件|*.*", "选择自定义主页");
            if (p != null) _homePath.Text = p;
        });
        var homeRow = Ui.G(null, "*,Auto");
        homeRow.Add(_homePath, 0, 0);
        homeRow.Add(browseHome.M(8, 0, 0, 0).VCenter(), 0, 1);
        var checkUpdate = Ui.Btn("检查更新", BtnKind.Chip, (_, _) => Run(CheckUpdateAsync, "检查更新失败"), Ico.Refresh);
        var save = Ui.Btn("保存设置", BtnKind.Primary, (_, _) => Run(SaveAsync, "保存失败"), Ico.Save);
        save.Padding = new Thickness(24, 9, 24, 10);

        var appearance = Ui.Card(Ui.V(2,
            Ui.Field("深色模式", _dark, "立即生效"),
            Ui.Field("主题色", _swatches, "点击圆圈即时预览，保存后记住"),
            Ui.Field("界面背景", _bg, "预设色调，立即预览"),
            Ui.Field("界面动画", _motion, "换页过渡、进度条、悬浮等动效；关闭则全部瞬时"),
            Ui.Field("下载飞入动画", _fly, "点安装时图标抛物线飞入侧栏「下载任务」"),
            Ui.Field("飞入动画时长", SliderRow(_flyDur, _flyDurLbl), "毫秒，建议 400–800；越小越快")), 16);

        var download = Ui.Card(Ui.V(2,
            Ui.Field("下载并发线程数", SliderRow(_threads, _threadsLbl), "同时下载的文件数量"),
            Ui.Field("文件下载源", _src, "自动测速，官方慢于 4 秒改走 BMCLAPI"),
            Ui.Field("社区资源源", _comm, "模组 / 整合包：MCIM 国内镜像，挂了可改官方"),
            Ui.Field("跟随系统代理", _proxy, "默认开。关掉才强制直连"),
            Ui.Field("下载限速 (KB/s)", _limit.Left(), "0 表示不限制")), 16);

        var game = Ui.Card(Ui.V(2,
            Ui.Field("默认内存", SliderRow(_mem, _memLbl), "新实例的默认 JVM 内存"),
            Ui.Field("默认分辨率", Ui.H(6, _w, Ui.Txt("×", 13).VCenter(), _h), "游戏窗口的默认宽高"),
            Ui.Field("默认实例", _inst, "安装与启动缺省使用的实例"),
            Ui.Field("新版本默认隔离", _iso, "安装新版本时写入，可在版本设置里改"),
            Ui.Field("内存回收器", _gc, "启动时写入 JVM，版本设置可覆盖"),
            Ui.Field("默认游戏窗口", _win, "可被版本设置覆盖"),
            Ui.Field("默认 JVM 参数", _jvm, "所有版本都会带上，版本设置可再追加")), 16);

        var share = Ui.Card(Ui.V(2,
            Ui.Field("共享 libraries", _shareLib, "所有实例共享依赖库（节省空间，降低隔离性）"),
            Ui.Field("共享 assets 资源", _shareAssets, "所有实例共享资源文件（节省空间，降低隔离性）")), 16);

        var launcher = Ui.Card(Ui.V(2,
            Ui.Field("启动器可见性", _vis, "游戏启动后启动器窗口怎么处理"),
            Ui.Field("启动页主页", _home, "新闻、自定义 HTML 或留空"),
            Ui.Field("自定义主页", homeRow, "本地 .html 文件路径"),
            Ui.Field("自动检查更新", _autoUpdate, "启动时检查启动器更新"),
            Ui.Field("更新地址", _updateUrl, "留空用默认更新源"),
            Ui.Field("语言", _lang, "切换界面语言，重启后完全生效")), 16);

        var foot = Ui.H(10, checkUpdate, save).Right();
        Content = ScrollBody(
            Ui.Section("设置", "改动在点「保存设置」后写入后端；外观项随点随看"),
            appearance, download, game, share, launcher, foot);
    }

    private static UIElement SliderRow(Slider s, TextBlock label)
    {
        var g = Ui.G(null, "*,Auto");
        g.Add(s.VCenter(), 0, 0);
        g.Add(label.M(10, 0, 0, 0).VCenter(), 0, 1);
        return g;
    }

    private void BuildSwatches()
    {
        _swatches.Children.Clear();
        foreach (var (name, hex) in Palette)
        {
            var sel = string.Equals(_color, hex, StringComparison.OrdinalIgnoreCase);
            var ring = new Border
            {
                Width = 26,
                Height = 26,
                CornerRadius = new CornerRadius(13),
                Padding = new Thickness(3),
                BorderThickness = new Thickness(sel ? 2 : 0),
                Cursor = Cursors.Hand,
                ToolTip = name,
            };
            ring.SetResourceReference(Border.BorderBrushProperty, "B.AccentDeep");
            ring.Child = new Border { CornerRadius = new CornerRadius(10), Background = new SolidColorBrush(Parse(hex)) };
            var pick = hex;
            ring.MouseLeftButtonUp += (_, _) =>
            {
                _color = pick;
                BuildSwatches();
                ApplyVisuals(_color, KeyOf(_bg));
            };
            _swatches.Children.Add(ring);
        }
    }

    // ==================== 读取 ====================
    protected override async Task LoadAsync()
    {
        _sync = true;
        try
        {
            var s = await Api.TryCallAsync<Dictionary<string, JsonElement>>("get_settings");
            if (s != null)
            {
                _dark.IsChecked = GetBool(s, "ui_dark");
                _threads.Value = Math.Clamp(GetInt(s, "download_threads", 8), 1, 64);
                _mem.Value = Math.Clamp(GetInt(s, "default_memory_mb", 4096), 512, 32768);
                if (s.TryGetValue("default_resolution", out var r) &&
                    r.ValueKind == JsonValueKind.Array && r.GetArrayLength() >= 2)
                {
                    _w.Text = r[0].ToString();
                    _h.Text = r[1].ToString();
                }
                _limit.Text = GetInt(s, "download_limit_kbps", 0).ToString();
                SelectKey(_src, GetStr(s, "download_source", "auto"));
                SelectKey(_comm, GetStr(s, "community_source", "auto"));
                _proxy.IsChecked = GetBool(s, "use_system_proxy", true);
                SelectKey(_iso, GetStr(s, "default_isolation", "none"));
                SelectKey(_gc, GetStr(s, "gc_preset", "auto"));
                SelectKey(_vis, GetStr(s, "launcher_visibility", "keep"));
                SelectKey(_home, GetStr(s, "homepage_mode", "news"));
                SelectKey(_win, GetStr(s, "window_mode", "window"));
                _homePath.Text = GetStr(s, "custom_homepage");
                _jvm.Text = GetStr(s, "default_jvm_args");
                _shareLib.IsChecked = GetBool(s, "share_libraries");
                _shareAssets.IsChecked = GetBool(s, "share_assets");
                _autoUpdate.IsChecked = GetBool(s, "auto_check_update", true);
                _updateUrl.Text = GetStr(s, "update_url");
            }

            var insts = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
            _inst.Fill(insts.Select(i => i.Name));
            var defInst = await Api.TryCallAsync<string>("get_setting",
                new Dictionary<string, object?> { ["key"] = "default_instance", ["default"] = "" }, "");
            if (!string.IsNullOrEmpty(defInst) && _inst.Items.Contains(defInst)) _inst.SelectedItem = defInst;

            var langs = await Api.TryCallAsync<Dictionary<string, string>>("available_languages");
            if (langs is { Count: > 0 })
            {
                _lang.Items.Clear();
                foreach (var kv in langs) _lang.Items.Add(new Opt { Key = kv.Key, Label = kv.Value });
            }
            _lang0 = await Api.TryCallAsync<string>("get_language", null, "") ?? "";
            SelectKey(_lang, _lang0);

            _motion.IsChecked = Motion.Enabled;
            _fly.IsChecked = Extras.FlyAnimation;
            _flyDur.Value = Math.Clamp(Extras.FlyDurationMs, 200, 1200);
            _flyDurLbl.Text = $"{(int)_flyDur.Value} ms";
            _color = Extras.ThemeColor;
            BuildSwatches();
            SelectKey(_bg, Extras.Background);
            ApplyVisuals();
        }
        finally { _sync = false; }
    }

    // ==================== 保存 ====================
    private async Task SaveAsync()
    {
        var dark = _dark.IsChecked == true;
        var settings = new Dictionary<string, object?>
        {
            ["ui_dark"] = dark,
            ["download_threads"] = (int)_threads.Value,
            ["default_memory_mb"] = (int)_mem.Value,
            ["default_resolution"] = new[] { Int(_w.Text, 854), Int(_h.Text, 480) },
            ["download_source"] = KeyOf(_src),
            ["community_source"] = KeyOf(_comm),
            ["use_system_proxy"] = _proxy.IsChecked == true,
            ["download_limit_kbps"] = Int(_limit.Text, 0),
            ["default_isolation"] = KeyOf(_iso),
            ["default_jvm_args"] = _jvm.Text?.Trim() ?? "",
            ["gc_preset"] = KeyOf(_gc),
            ["launcher_visibility"] = KeyOf(_vis),
            ["homepage_mode"] = KeyOf(_home),
            ["custom_homepage"] = _homePath.Text?.Trim() ?? "",
            ["window_mode"] = KeyOf(_win),
            ["auto_check_update"] = _autoUpdate.IsChecked == true,
            ["update_url"] = _updateUrl.Text?.Trim() ?? "",
            ["share_libraries"] = _shareLib.IsChecked == true,
            ["share_assets"] = _shareAssets.IsChecked == true,
            ["default_instance"] = _inst.Str(),
            // 桥接 save_settings 目前会丢弃的键：app 后端认识，一并提交，桥接补齐后即生效。
            ["theme_color"] = _color,
            ["ui_background"] = KeyOf(_bg),
            ["ui_motion"] = _motion.IsChecked == true,
            ["ui_fly_animation"] = _fly.IsChecked == true,
            ["ui_fly_duration_ms"] = (int)_flyDur.Value,
        };
        await Api.CallAsync<object>("update_settings", new { settings });

        var lang = KeyOf(_lang);
        if (!string.IsNullOrEmpty(lang) && lang != _lang0)
        {
            await Api.TryCallAsync<object>("set_language", new { lang });
            _lang0 = lang;
        }

        Extras.ThemeColor = _color;
        Extras.Background = KeyOf(_bg);
        Extras.FlyAnimation = _fly.IsChecked == true;
        Extras.FlyDurationMs = (int)_flyDur.Value;
        SaveExtras();

        if (dark != App.IsDark) App.ApplyTheme(dark);
        Motion.Enabled = _motion.IsChecked == true;
        ApplyVisuals();
        Win?.SaveUiPrefs();
        AppServices.Window?.Toast("设置已保存", "外观与动效已立即生效", ToastKind.Success);
    }

    private void ApplyDark(bool dark)
    {
        if (dark == App.IsDark) return;
        App.ApplyTheme(dark);
        ApplyVisuals();
        Win?.SaveUiPrefs();
    }

    private async Task CheckUpdateAsync()
    {
        using (Dlg.Busy("正在检查更新…"))
        {
            var info = await Api.TryCallAsync<UpdateInfo>("check_update");
            if (info == null) Toast("检查失败", "更新源没有响应", ToastKind.Warning);
            else if (info.HasUpdate) await Dlg.Alert("发现新版本", $"{info.Version}\n{info.Message}\n{info.Url}".Trim());
            else Toast("已是最新", string.IsNullOrEmpty(info.Message) ? "当前就是最新版本" : info.Message, ToastKind.Success);
        }
    }

    // ==================== 主题应用 ====================
    internal static void ApplyVisuals() => ApplyVisuals(Extras.ThemeColor, Extras.Background);

    private static void ApplyVisuals(string color, string bg)
    {
        try
        {
            var dicts = Application.Current.Resources.MergedDictionaries;
            if (dicts.Count == 0) return;
            var d = dicts[0];
            var dark = App.IsDark;
            var paper = dark ? Color.FromRgb(0x1B, 0x23, 0x20) : Colors.White;

            if (!string.Equals(color, DefaultColor, StringComparison.OrdinalIgnoreCase))
            {
                var c = Parse(color);
                d["B.Accent"] = new SolidColorBrush(dark ? Mix(c, Colors.White, 0.16) : c);
                d["B.AccentDeep"] = new SolidColorBrush(dark ? c : Mix(c, Colors.Black, 0.22));
                d["B.AccentLite"] = new SolidColorBrush(Mix(c, Colors.White, 0.30));
                d["B.AccentSoft"] = new SolidColorBrush(Mix(c, paper, dark ? 0.24 : 0.10));
                d["B.AccentSoft2"] = new SolidColorBrush(Mix(c, paper, dark ? 0.32 : 0.17));
                d["B.Ok"] = new SolidColorBrush(dark ? Mix(c, Colors.White, 0.16) : c);
                var grad = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 1) };
                grad.GradientStops.Add(new GradientStop(Mix(c, Colors.Black, dark ? 0.28 : 0.10), 0));
                grad.GradientStops.Add(new GradientStop(c, 0.5));
                grad.GradientStops.Add(new GradientStop(Mix(c, Colors.Black, dark ? 0.50 : 0.35), 1));
                d["B.BannerFill"] = grad;
            }

            if (bg != "default")
            {
                var (canvas, wash) = bg switch
                {
                    "eye" => dark ? ("#121A15", new[] { "#141D17", "#16211A", "#121A15" })
                                  : ("#EBF4EC", new[] { "#EFF7F0", "#EAF4EB", "#EDF6EE" }),
                    "warm" => dark ? ("#1B1813", new[] { "#1D1A15", "#201C16", "#1B1813" })
                                   : ("#F7F3EA", new[] { "#F9F5ED", "#F6F2E8", "#F8F4EC" }),
                    _ => dark ? ("#14181D", new[] { "#161B21", "#181E25", "#14181D" })
                              : ("#EDF1F6", new[] { "#F0F4F9", "#EBF0F6", "#EEF2F8" }),
                };
                d["B.Canvas"] = new SolidColorBrush(Parse(canvas));
                var wash2 = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(0.9, 1) };
                wash2.GradientStops.Add(new GradientStop(Parse(wash[0]), 0));
                wash2.GradientStops.Add(new GradientStop(Parse(wash[1]), 0.55));
                wash2.GradientStops.Add(new GradientStop(Parse(wash[2]), 1));
                d["B.PageWash"] = wash2;
            }
        }
        catch { }
    }

    private static Color Parse(string hex) =>
        (Color)(ColorConverter.ConvertFromString(hex) ?? Colors.SeaGreen);

    private static Color Mix(Color a, Color b, double t) => Color.FromRgb(
        (byte)(a.R + (b.R - a.R) * t),
        (byte)(a.G + (b.G - a.G) * t),
        (byte)(a.B + (b.B - a.B) * t));

    // ==================== 读取辅助 ====================
    private static bool GetBool(Dictionary<string, JsonElement> s, string k, bool def = false) =>
        s.TryGetValue(k, out var v) && v.ValueKind is JsonValueKind.True or JsonValueKind.False ? v.GetBoolean() : def;

    private static int GetInt(Dictionary<string, JsonElement> s, string k, int def) =>
        s.TryGetValue(k, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n) ? n : def;

    private static string GetStr(Dictionary<string, JsonElement> s, string k, string def = "") =>
        s.TryGetValue(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? def : def;

    private static int Int(string? s, int fallback) =>
        int.TryParse(s?.Trim(), out var v) && v >= 0 ? v : fallback;
}
