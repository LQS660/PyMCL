using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>全局设置。后端认识的键一次性走 save_settings；ui_motion / 主题色 / 背景 / 飞入动画
/// 另存一份 wpf-theme.json 以便立即应用，桥接补齐这些键后两边会一致。</summary>
public sealed class SettingsPage : PageBase
{
    public override string Title => L("设置");

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
        { ("none", L("关闭（共用实例目录）")), ("saves", L("隔离存档")), ("mods", L("隔离 Mod 与配置")), ("all", L("隔离全部")) };
    private static readonly (string Key, string Label)[] GcOpts =
        { ("auto", L("G1（推荐）")), ("g1", "G1"), ("g1_tuned", L("调优 G1")), ("zgc", "ZGC"), ("none", L("不指定")) };
    private static readonly (string Key, string Label)[] VisOpts =
        { ("keep", L("保持显示")), ("minimize", L("最小化")), ("hide", L("隐藏")), ("hide_reopen", L("隐藏，退出后重开")), ("close", L("关闭启动器")) };
    private static readonly (string Key, string Label)[] HomeOpts =
        { ("news", L("Minecraft 新闻")), ("custom", L("本地 HTML")), ("blank", L("空白")) };
    private static readonly (string Key, string Label)[] WinOpts =
        { ("window", L("窗口")), ("maximize", L("全屏")) };
    private static readonly (string Key, string Label)[] SrcOpts =
        { ("auto", L("自动（官方慢则走 BMCLAPI）")), ("official", L("仅官方")), ("bmclapi", L("仅 BMCLAPI")) };
    private static readonly (string Key, string Label)[] CommOpts =
        { ("auto", L("自动")), ("official", L("仅官方")), ("mcim", L("仅 MCIM")) };
    private static readonly (string Key, string Label)[] BgOpts =
        { ("default", L("默认")), ("eye", L("护眼绿")), ("warm", L("暖米")), ("mist", L("雾蓝")) };
    private static readonly (string Key, string Label)[] AiModeOpts =
        { ("public", L("公共网关（免配置）")), ("custom", L("自定义 OpenAI 兼容端点")) };
    // 词表必须是 mclauncher/ai/permission.py 枚举的合法值（W-5）：旧值 trusted/strict
    // 后端认不出，会静默折回 default——「信任（少打扰）」实际变成「每一步都问」。
    private static readonly (string Key, string Label)[] AiPermOpts =
        { ("default", L("标准（写操作先问）")), ("acceptEdits", L("少打扰（写操作直接执行）")), ("plan", L("只看不动（禁止写操作）")), ("yolo", L("全自动")) };
    private static readonly (string Name, string Hex)[] Palette =
        { (L("松绿"), "#2E9B6B"), (L("湛蓝"), "#2F72C4"), (L("紫罗兰"), "#7C5CFC"), (L("暖橙"), "#D68A17"), (L("绯红"), "#D64545"), (L("青碧"), "#149B9B") };

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
    private readonly TextBox _jvm = Ui.Input(L("例如 -XX:+UseG1GC（可空）"));
    private readonly CheckBox _shareLib = Ui.Switch();
    private readonly CheckBox _shareAssets = Ui.Switch();
    private readonly CheckBox _multi = Ui.Switch();
    private readonly ComboBox _vis = KeyCombo(VisOpts);
    private readonly ComboBox _home = KeyCombo(HomeOpts);
    private readonly TextBox _homePath = Ui.Input(L("本地 .html 文件路径（主页选「本地 HTML」时生效）"));
    private readonly CheckBox _autoUpdate = Ui.Switch(true);
    private readonly TextBox _updateUrl = Ui.Input(L("留空用默认更新源"));
    private readonly ComboBox _lang = KeyCombo(Array.Empty<(string, string)>());
    private readonly TextBlock _langPreview = Ui.Small("");
    private readonly TextBox _gameDir = Ui.Input(L("游戏目录（.minecraft 的落脚处）"));
    private readonly TextBlock _cleanInfo = Ui.Small(L("还没扫描"));
    private readonly ComboBox _themePack = Ui.Combo(width: 200);
    private readonly TextBlock _themeInfo = Ui.Small("");
    private readonly ComboBox _aiMode = KeyCombo(AiModeOpts);
    private readonly ComboBox _aiPerm = KeyCombo(AiPermOpts);
    private readonly TextBox _aiGateway = Ui.Input(L("https://…（公共网关地址）"));
    private readonly TextBox _aiBase = Ui.Input("https://api.openai.com/v1");
    private readonly TextBox _aiKey = Ui.Input("sk-…");
    private readonly TextBox _aiModel = Ui.Input(L("模型名"));
    private readonly TextBox _aiCtx = Ui.Input("131072");
    private readonly TextBox _aiFallback = Ui.Input(L("留空不启用"));
    private readonly CheckBox _aiConfirm = Ui.Switch(true);
    private readonly TextBox _msClient = Ui.Input(L("微软登录 Client ID（留空用内置）"));
    private readonly TextBox _cfKey = Ui.Input(L("CurseForge API Key（留空用内置）"));
    private readonly TextBox _bgPath = Ui.Input(L("图片或视频路径，留空则不用壁纸"));
    private readonly TextBox _bgFolder = Ui.Input(L("壁纸文件夹（设了就轮播，优先于上面那张）"));
    private readonly CheckBox _bgShuffle = Ui.Switch();
    private readonly Slider _bgInterval = Ui.Sld(1, 120, 10, 1);
    private readonly TextBlock _bgIntervalLbl = Ui.Txt(L("10 分钟"), 12, true);
    private readonly Slider _bgBlur = Ui.Sld(0, 40, 0, 1);
    private readonly TextBlock _bgBlurLbl = Ui.Txt("0 px", 12, true);
    private readonly Slider _bgDim = Ui.Sld(0, 80, 0, 1);
    private readonly TextBlock _bgDimLbl = Ui.Txt("0 %", 12, true);
    private readonly TextBlock _bgInfo = Ui.Small("");
    private readonly Button _bgUndo;
    private readonly Button _clean, _testAi, _rec;
    private string _lang0 = "";
    private string _gameDir0 = "";
    private string _color = DefaultColor;
    private bool _sync;
    private CleanerPreview? _cleanPreview;

    public SettingsPage()
    {
        _dark.Checked += (_, _) => { if (!_sync) ApplyDark(_dark.IsChecked == true); };
        _dark.Unchecked += (_, _) => { if (!_sync) ApplyDark(false); };
        _bg.SelectionChanged += (_, _) => { if (!_sync) ApplyVisuals(_color, KeyOf(_bg)); };
        _flyDur.ValueChanged += (_, e) => _flyDurLbl.Text = $"{(int)e.NewValue} ms";
        _threads.ValueChanged += (_, e) => _threadsLbl.Text = ((int)e.NewValue).ToString();
        _mem.ValueChanged += (_, e) => _memLbl.Text = $"{(int)e.NewValue} MB";
        _lang.SelectionChanged += (_, _) => { if (!_sync) Run(PreviewLanguageAsync); };
        _aiMode.SelectionChanged += (_, _) => SyncAiRows();
        _aiKey.Tag = "sk-…";

        BuildSwatches();

        var browseHome = Ui.Btn(L("浏览…"), BtnKind.Chip, (_, _) =>
        {
            var p = Dlg.PickFile(L("网页 (*.html;*.htm)|*.html;*.htm|全部文件|*.*"), L("选择自定义主页"));
            if (p != null) _homePath.Text = p;
        });
        var homeRow = Ui.G(null, "*,Auto");
        homeRow.Add(_homePath, 0, 0);
        homeRow.Add(browseHome.M(8, 0, 0, 0).VCenter(), 0, 1);

        var browseDir = Ui.Btn(L("浏览…"), BtnKind.Chip, (_, _) => Run(BrowseGameDirAsync, L("切换失败")), Ico.Folder);
        var dirRow = Ui.G(null, "*,Auto");
        dirRow.Add(_gameDir, 0, 0);
        dirRow.Add(browseDir.M(8, 0, 0, 0).VCenter(), 0, 1);

        var checkUpdate = Ui.Btn(L("检查更新"), BtnKind.Chip, (_, _) => Run(CheckUpdateAsync, L("检查更新失败")), Ico.Refresh);
        var save = Ui.Btn(L("保存设置"), BtnKind.Primary, (_, _) => Run(SaveAsync, L("保存失败")), Ico.Save);
        save.Padding = new Thickness(24, 9, 24, 10);

        _clean = Ui.Btn(L("扫描并清理"), BtnKind.Chip, (_, _) => Run(CleanAsync, L("清理失败")), Ico.Broom);
        _testAi = Ui.Btn(L("测试 AI 连接"), BtnKind.Chip, (_, _) => Run(TestAiAsync, L("AI 连接失败")), Ico.Robot);
        _rec = Ui.Btn(L("查看推荐"), BtnKind.Chip, (_, _) => Run(RecommendAsync, L("检测失败")), Ico.Lightning);

        var appearance = Ui.Card(Ui.V(2,
            Ui.Field(L("深色模式"), _dark, L("立即生效")),
            Ui.Field(L("主题色"), _swatches, L("点击圆圈即时预览，保存后记住")),
            Ui.Field(L("界面背景"), _bg, L("预设色调，立即预览")),
            Ui.Field(L("界面动画"), _motion, L("换页过渡、进度条、悬浮等动效；关闭则全部瞬时")),
            Ui.Field(L("下载飞入动画"), _fly, L("点安装时图标抛物线飞入侧栏「下载任务」")),
            Ui.Field(L("飞入动画时长"), SliderRow(_flyDur, _flyDurLbl), L("毫秒，建议 400–800；越小越快"))), 16);

        _bgInterval.ValueChanged += (_, e) => _bgIntervalLbl.Text = L("{0} 分钟", (int)e.NewValue);
        _bgBlur.ValueChanged += (_, e) =>
        {
            _bgBlurLbl.Text = $"{(int)e.NewValue} px";
            if (!_sync) Wallpaper.SetEffects((int)_bgBlur.Value, (int)_bgDim.Value);
        };
        _bgDim.ValueChanged += (_, e) =>
        {
            _bgDimLbl.Text = $"{(int)e.NewValue} %";
            if (!_sync) Wallpaper.SetEffects((int)_bgBlur.Value, (int)_bgDim.Value);
        };
        var pickBg = Ui.Btn(L("选图片 / 视频…"), BtnKind.Chip, (_, _) =>
        {
            var p = Dlg.PickFile(
                L("壁纸 (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif;*.mp4;*.mkv;*.webm;*.mov)")
                + L("|*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif;*.mp4;*.mkv;*.webm;*.mov|全部文件|*.*"),
                L("选择壁纸"));
            if (p is null) return;
            _bgPath.Text = p;
            _bgFolder.Clear();
            Run(ApplyWallpaperAsync, L("壁纸没能应用"));
        }, Ico.Image);
        var pickBgDir = Ui.Btn(L("选文件夹…"), BtnKind.Chip, (_, _) =>
        {
            var p = Dlg.PickFolder(L("选择壁纸文件夹"));
            if (p is null) return;
            _bgFolder.Text = p;
            Run(ApplyWallpaperAsync, L("壁纸没能应用"));
        }, Ico.Folder);
        var clearBg = Ui.Btn(L("关闭壁纸"), BtnKind.Ghost, (_, _) =>
        {
            _bgPath.Clear();
            _bgFolder.Clear();
            Run(ApplyWallpaperAsync, L("壁纸没能关闭"));
        }, Ico.Close);
        // 换错了能退回去：后端记着一摞换下来的旧壁纸（单图与轮播文件夹成对入栈）
        _bgUndo = Ui.Btn(L("撤销上一次"), BtnKind.Chip, (_, _) => Run(UndoWallpaperAsync, L("撤销失败")), Ico.Refresh);
        var resetBg = Ui.Btn(L("恢复出厂"), BtnKind.Chip, (_, _) => Run(ResetWallpaperAsync, L("恢复失败")), Ico.Broom);

        var bgRow = Ui.G(null, "*,Auto");
        bgRow.Add(_bgPath, 0, 0);
        bgRow.Add(pickBg.M(8, 0, 0, 0).VCenter(), 0, 1);
        var bgDirRow = Ui.G(null, "*,Auto");
        bgDirRow.Add(_bgFolder, 0, 0);
        bgDirRow.Add(pickBgDir.M(8, 0, 0, 0).VCenter(), 0, 1);

        var wallpaper = Ui.Card(Ui.V(2,
            Ui.Section(L("壁纸"), L("图片或 mp4 动态壁纸；也可以直接把文件拖进窗口")),
            Ui.Field(L("壁纸文件"), bgRow, L("留空就不用壁纸。视频会静音循环播放")),
            Ui.Field(L("轮播文件夹"), bgDirRow, L("设了文件夹就按间隔换图，优先于上面那张单图")),
            Ui.Field(L("随机顺序"), _bgShuffle, L("关掉则按文件名顺序轮")),
            Ui.Field(L("轮播间隔"), SliderRow(_bgInterval, _bgIntervalLbl), L("分钟")),
            Ui.Field(L("模糊"), SliderRow(_bgBlur, _bgBlurLbl), L("把壁纸推远一点，文字更好读；随拖随看")),
            Ui.Field(L("遮罩浓度"), SliderRow(_bgDim, _bgDimLbl), L("按当前主题压淡 / 压暗壁纸；随拖随看")),
            Ui.Field("", Ui.H(8, clearBg, _bgUndo, resetBg, _bgInfo.VCenter()))), 16);

        var themes = Ui.Card(Ui.V(2,
            Ui.Section(L("主题包"), L("把当前配色、背景、窗口与主页设置整包存下来，随时切回")),
            Ui.Field(L("已保存"), _themePack, L("从这里挑一个加载或删除")),
            Ui.Field("", Ui.H(7,
                Ui.Btn(L("保存为主题包"), BtnKind.Soft, (_, _) => Run(SaveThemeAsync, L("保存失败")), Ico.Save),
                Ui.Btn(L("加载"), BtnKind.Chip, (_, _) => Run(LoadThemeAsync, L("加载失败")), Ico.Palette),
                Ui.Btn(L("删除"), BtnKind.Ghost, (_, _) => Run(DeleteThemeAsync, L("删除失败")), Ico.Trash),
                Ui.Btn(L("导入"), BtnKind.Chip, (_, _) => Run(ImportThemeAsync, L("导入失败")), Ico.Import),
                Ui.Btn(L("导出"), BtnKind.Chip, (_, _) => Run(ExportThemeAsync, L("导出失败")), Ico.Export))),
            _themeInfo), 16);

        var download = Ui.Card(Ui.V(2,
            Ui.Field(L("下载并发线程数"), SliderRow(_threads, _threadsLbl), L("同时下载的文件数量")),
            Ui.Field(L("文件下载源"), _src, L("自动测速，官方慢于 4 秒改走 BMCLAPI")),
            Ui.Field(L("社区资源源"), _comm, L("模组 / 整合包：MCIM 国内镜像，挂了可改官方")),
            Ui.Field(L("跟随系统代理"), _proxy, L("默认开。关掉才强制直连")),
            Ui.Field(L("下载限速 (KB/s)"), _limit.Left(), L("0 表示不限制")),
            Ui.Field("CurseForge Key", _cfKey, L("留空用内置 Key"))), 16);

        var game = Ui.Card(Ui.V(2,
            Ui.Field(L("游戏目录"), dirRow, L("所有实例的落脚处；切换会校验可写性")),
            Ui.Field(L("默认内存"), SliderRow(_mem, _memLbl), L("新实例的默认 JVM 内存")),
            Ui.Field("", Ui.H(8, _rec, Ui.Small(L("按本机内存 / CPU 给一组推荐值")).VCenter())),
            Ui.Field(L("默认分辨率"), Ui.H(6, _w, Ui.Txt("×", 13).VCenter(), _h), L("游戏窗口的默认宽高")),
            Ui.Field(L("默认实例"), _inst, L("安装与启动缺省使用的实例")),
            Ui.Field(L("新版本默认隔离"), _iso, L("安装新版本时写入，可在版本设置里改")),
            Ui.Field(L("内存回收器"), _gc, L("启动时写入 JVM，版本设置可覆盖")),
            Ui.Field(L("默认游戏窗口"), _win, L("可被版本设置覆盖")),
            Ui.Field(L("默认 JVM 参数"), _jvm, L("所有版本都会带上，版本设置可再追加")),
            Ui.Field(L("允许多开"), _multi, L("关掉则游戏已在运行时不再启动第二个"))), 16);

        var share = Ui.Card(Ui.V(2,
            Ui.Field(L("共享 libraries"), _shareLib, L("所有实例共享依赖库（节省空间，降低隔离性）")),
            Ui.Field(L("共享 assets 资源"), _shareAssets, L("所有实例共享资源文件（节省空间，降低隔离性）")),
            Ui.Field(L("空间清理"), Ui.H(8, _clean, _cleanInfo.VCenter()),
                L("扫描未引用的依赖库、残留 .part 与更新缓存，确认后再删"))), 16);

        var ai = Ui.Card(Ui.V(2,
            Ui.Section(L("AI 助手"), L("对话里下游戏、装模组、读崩溃日志")),
            Ui.Field(L("接入方式"), _aiMode),
            Ui.Field(L("网关地址"), _aiGateway, L("公共网关模式下生效")),
            Ui.Field(L("端点地址"), _aiBase, L("自定义模式下的 OpenAI 兼容 base_url")),
            Ui.Field("API Key", _aiKey),
            Ui.Field(L("模型"), _aiModel),
            Ui.Field(L("上下文窗口（token）"), _aiCtx, L("模型真实窗口未知时按 128k 保守压缩；实测后可改大")),
            Ui.Field(L("备用模型（可选）"), _aiFallback, L("主模型连续 429/5xx 时本回合自动切到它；留空不启用")),
            Ui.Field(L("写操作确认"), _aiConfirm, L("AI 要改文件 / 装东西前先弹窗问你")),
            Ui.Field(L("权限档位"), _aiPerm),
            Ui.Field("", _testAi.Left())), 16);

        var launcher = Ui.Card(Ui.V(2,
            Ui.Field(L("启动器可见性"), _vis, L("游戏启动后启动器窗口怎么处理")),
            Ui.Field(L("启动页主页"), _home, L("新闻、自定义 HTML 或留空")),
            Ui.Field(L("自定义主页"), homeRow, L("本地 .html 文件路径")),
            Ui.Field(L("自动检查更新"), _autoUpdate, L("启动时检查启动器更新")),
            Ui.Field(L("更新地址"), _updateUrl, L("留空用默认更新源")),
            Ui.Field(L("微软 Client ID"), _msClient, L("自建 Azure 应用时填")),
            Ui.Field(L("语言"), _lang, L("切换界面语言，重启后完全生效")),
            Ui.Field("", _langPreview),
            Ui.Field(L("启动向导"), Ui.Btn(L("重新运行"), BtnKind.Chip,
                (_, _) => Run(FirstRunWizard.ShowAsync, L("向导没能打开")), Ico.Rocket).Left(),
                L("目录、下载源、内存、隔离会再问一遍，最后一步还会指一遍容易错过的功能"))), 16);

        var foot = Ui.H(10, checkUpdate, save).Right();
        Content = ScrollBody(
            Ui.Section(L("设置"), L("改动在点「保存设置」后一次性写入后端；外观项随点随看")),
            appearance, wallpaper, themes, download, game, share, ai, launcher, foot);
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

    private void SyncAiRows()
    {
        var custom = KeyOf(_aiMode) == "custom";
        _aiBase.IsEnabled = _aiKey.IsEnabled = custom;
        _aiGateway.IsEnabled = !custom;
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
                _threads.Value = Clamp.Of(GetInt(s, "download_threads", 8), 1, 64);
                _mem.Value = Clamp.Of(GetInt(s, "default_memory_mb", 4096), 512, 32768);
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
                _msClient.Text = GetStr(s, "ms_client_id");
                _cfKey.Text = GetStr(s, "curseforge_api_key");
                SelectKey(_aiMode, GetStr(s, "ai_mode", "public"));
                SelectKey(_aiPerm, GetStr(s, "ai_permission_mode", "default"));
                _aiGateway.Text = GetStr(s, "ai_gateway_url");
                _aiBase.Text = GetStr(s, "ai_base_url");
                _aiKey.Text = GetStr(s, "ai_api_key");
                _aiModel.Text = GetStr(s, "ai_model");
                _aiCtx.Text = GetStr(s, "ai_context_window", "131072");
                _aiFallback.Text = GetStr(s, "ai_fallback_model");
                _aiConfirm.IsChecked = GetBool(s, "ai_confirm_writes", true);
                _gameDir0 = GetStr(s, "game_dir");
                if (string.IsNullOrEmpty(_gameDir0)) _gameDir0 = GetStr(s, "root");
                _gameDir.Text = _gameDir0;
                // ui_background 在后端是壁纸路径。WPF 的预设色调是本地项，另存 wpf-theme.json，
                // 不能往这个键上写，否则一保存设置就把用户的壁纸顶掉。
                _bgPath.Text = GetStr(s, "ui_background");
                _bgFolder.Text = GetStr(s, "ui_background_folder");
                _bgShuffle.IsChecked = GetBool(s, "ui_background_shuffle");
                _bgInterval.Value = Clamp.Of(GetInt(s, "ui_background_interval", 10), 1, 120);
                _bgBlur.Value = Clamp.Of(GetInt(s, "ui_background_blur", 0), 0, 40);
                _bgDim.Value = Clamp.Of(GetInt(s, "ui_background_dim", 0), 0, 80);
                _bgIntervalLbl.Text = L("{0} 分钟", (int)_bgInterval.Value);
                _bgBlurLbl.Text = $"{(int)_bgBlur.Value} px";
                _bgDimLbl.Text = $"{(int)_bgDim.Value} %";
            }
            SyncWallpaperInfo();
            SyncAiRows();

            var insts = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
            _inst.Fill(insts.Select(i => i.Name));
            var defInst = await Api.TryCallAsync<string>("get_setting",
                new Dictionary<string, object?> { ["key"] = "default_instance", ["default"] = "" }, "");
            if (!string.IsNullOrEmpty(defInst) && _inst.Items.Contains(defInst)) _inst.SelectedItem = defInst;

            // 多开开关不在 get_settings 里，有自己的一对读写 RPC。
            _multi.IsChecked = await Api.TryCallAsync<bool>("allow_multi_instance", null, false);

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
            _flyDur.Value = Clamp.Of(Extras.FlyDurationMs, 200, 1200);
            _flyDurLbl.Text = $"{(int)_flyDur.Value} ms";
            _color = Extras.ThemeColor;
            BuildSwatches();
            SelectKey(_bg, Extras.Background);
            ApplyVisuals();
        }
        finally { _sync = false; }

        await ReloadThemesAsync();
    }

    // ==================== 保存 ====================
    private async Task SaveAsync()
    {
        // 游戏目录不能当普通配置项写：切目录要经 set_game_dir 校验可写性。
        var typed = _gameDir.Text?.Trim() ?? "";
        if (typed.Length > 0 && typed != _gameDir0)
        {
            try
            {
                _gameDir0 = await Api.CallAsync<string>("set_game_dir", new { path = typed }) ?? typed;
                _gameDir.Text = _gameDir0;
            }
            catch (Exception ex)
            {
                _gameDir.Text = _gameDir0;
                Toast(L("游戏目录无效"), ex.Message, ToastKind.Error);
                Motion.Shake(_gameDir);
                return;
            }
        }

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
            ["ms_client_id"] = _msClient.Text?.Trim() ?? "",
            ["curseforge_api_key"] = _cfKey.Text?.Trim() ?? "",
            ["ai_mode"] = KeyOf(_aiMode),
            ["ai_gateway_url"] = _aiGateway.Text?.Trim() ?? "",
            ["ai_base_url"] = _aiBase.Text?.Trim() ?? "",
            ["ai_api_key"] = _aiKey.Text?.Trim() ?? "",
            ["ai_model"] = _aiModel.Text?.Trim() ?? "",
            ["ai_context_window"] = int.TryParse(_aiCtx.Text?.Trim(), out var ctxWin)
                ? Clamp.Of(ctxWin, 8192, 2_000_000) : 131072,
            ["ai_fallback_model"] = _aiFallback.Text?.Trim() ?? "",
            ["ai_confirm_writes"] = _aiConfirm.IsChecked == true,
            ["ai_permission_mode"] = KeyOf(_aiPerm),
            ["ui_background"] = _bgPath.Text?.Trim() ?? "",
            ["ui_background_folder"] = _bgFolder.Text?.Trim() ?? "",
            ["ui_background_shuffle"] = _bgShuffle.IsChecked == true,
            ["ui_background_interval"] = (int)_bgInterval.Value,
            ["ui_background_blur"] = (int)_bgBlur.Value,
            ["ui_background_dim"] = (int)_bgDim.Value,
            // 桥接 save_settings 目前会丢弃的键：app 后端认识，一并提交，桥接补齐后即生效。
            ["theme_color"] = _color,
            ["ui_motion"] = _motion.IsChecked == true,
            ["ui_fly_animation"] = _fly.IsChecked == true,
            ["ui_fly_duration_ms"] = (int)_flyDur.Value,
        };
        // 整页一次落盘：save_settings 只写带过来的键，没提交的原样保留。
        await Api.CallAsync<object>("save_settings", new { data = settings });
        await Api.CallAsync<object>("set_multi_instance", new { allow = _multi.IsChecked == true });

        var lang = KeyOf(_lang);
        var langChanged = !string.IsNullOrEmpty(lang) && lang != _lang0;
        if (langChanged)
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
        await Wallpaper.ReloadAsync();
        SyncWallpaperInfo();
        Win?.SaveUiPrefs();
        AppServices.Window?.Toast(L("设置已保存"), L("外观与动效已立即生效"), ToastKind.Success);
        if (langChanged) await OfferLanguageRestartAsync();
    }

    /// <summary>
    /// 界面文案在各页构造时就取好了，切语言不会自动重排——照 Qt 设置页 _offer_language_restart 的做法：
    /// 问一句要不要现在重启（PCL 同款），不重启就提示下次启动生效。
    /// </summary>
    private async Task OfferLanguageRestartAsync()
    {
        var now = await Dlg.Confirm(L("语言已切换"), L("界面文字要重启启动器才会全部变成新语言。是否现在重启？"),
            L("立即重启"), L("稍后"));
        if (!now)
        {
            Toast(L("语言已切换"), L("下次启动启动器后界面才会变成新语言"));
            return;
        }
        try
        {
            var exe = System.Reflection.Assembly.GetEntryAssembly()?.Location;
            if (string.IsNullOrEmpty(exe))
                exe = System.Diagnostics.Process.GetCurrentProcess().MainModule?.FileName ?? "";
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe)
            {
                UseShellExecute = true,
                WorkingDirectory = Environment.CurrentDirectory,
            });
            Application.Current.Shutdown();
        }
        catch (Exception ex)
        {
            Toast(L("重启失败"), L("无法拉起新进程，请手动关闭后重新打开") + "\n" + ex.Message, ToastKind.Error);
        }
    }

    // ==================== 壁纸 ====================
    /// <summary>壁纸这几项随点随看：先落盘再让背景层重读，不用等「保存设置」。</summary>
    private async Task ApplyWallpaperAsync()
    {
        await Api.CallAsync<object>("save_settings", new
        {
            data = new Dictionary<string, object?>
            {
                ["ui_background"] = _bgPath.Text?.Trim() ?? "",
                ["ui_background_folder"] = _bgFolder.Text?.Trim() ?? "",
                ["ui_background_shuffle"] = _bgShuffle.IsChecked == true,
                ["ui_background_interval"] = (int)_bgInterval.Value,
                ["ui_background_blur"] = (int)_bgBlur.Value,
                ["ui_background_dim"] = (int)_bgDim.Value,
            },
        });
        await Wallpaper.ReloadAsync();
        SyncWallpaperInfo();
    }

    private void SyncWallpaperInfo()
    {
        Run(SyncWallpaperInfoAsync);
    }

    private async Task SyncWallpaperInfoAsync()
    {
        var history = await Api.TryCallAsync<List<string>>("background_history", null, new()) ?? new();
        var canUndo = await Api.TryCallAsync<bool>("can_undo_background", null, false);
        _bgUndo.IsEnabled = canUndo;
        _bgUndo.ToolTip = history.Count == 0 ? null : L("上一张：{0}", history[history.Count - 1]);

        if (!string.IsNullOrEmpty(Wallpaper.Error))
        {
            _bgInfo.Text = Wallpaper.Error;
            return;
        }
        var folder = _bgFolder.Text?.Trim() ?? "";
        var path = _bgPath.Text?.Trim() ?? "";
        var now = folder.Length > 0
            ? L("正在轮播文件夹里的图片")
            : path.Length == 0
                ? L("当前没有壁纸，界面走主题底色")
                : (FileKinds.IsVideo(path) ? L("当前是动态壁纸（静音循环）") : L("当前是静态背景图"));
        _bgInfo.Text = history.Count == 0 ? now : L("{0} · 历史 {1} 张可退", now, history.Count);
    }

    /// <summary>退回上一组壁纸（单图与轮播文件夹一起退，否则文件夹还挂着、界面什么都不会变）。</summary>
    private async Task UndoWallpaperAsync()
    {
        var prev = await Api.CallAsync<BackgroundState>("undo_background");
        if (prev is null) return;
        _sync = true;
        _bgPath.Text = prev.Image;
        _bgFolder.Text = prev.Folder;
        _sync = false;
        await Wallpaper.ReloadAsync();
        await SyncWallpaperInfoAsync();
        Toast(L("已撤销"), string.IsNullOrEmpty(prev.Image) && string.IsNullOrEmpty(prev.Folder)
            ? L("退回到没有壁纸") : prev.Image.Length > 0 ? prev.Image : prev.Folder, ToastKind.Success);
    }

    private async Task ResetWallpaperAsync()
    {
        if (!await Dlg.Confirm(L("恢复出厂壁纸"), L("会清掉当前壁纸与轮播文件夹；这一组仍会进历史，可以撤销回来。"),
                L("恢复"), L("取消"))) return;
        var def = await Api.CallAsync<BackgroundState>("reset_background");
        _sync = true;
        _bgPath.Text = def?.Image ?? "";
        _bgFolder.Text = def?.Folder ?? "";
        _sync = false;
        await Wallpaper.ReloadAsync();
        await SyncWallpaperInfoAsync();
        Toast(L("已恢复出厂壁纸"), L("想退回去点「撤销上一次」"), ToastKind.Success);
    }

    private void ApplyDark(bool dark)
    {
        if (dark == App.IsDark) return;
        App.ApplyTheme(dark);
        ApplyVisuals();
        Win?.SaveUiPrefs();
    }

    // ==================== 游戏目录 ====================
    private async Task BrowseGameDirAsync()
    {
        var path = Dlg.PickFolder(L("选择游戏目录"));
        if (path is null) return;
        _gameDir0 = await Api.CallAsync<string>("set_game_dir", new { path }) ?? path;
        _gameDir.Text = _gameDir0;
        Toast(L("已切换目录"), _gameDir0, ToastKind.Success);
        await LoadAsync();
    }

    // ==================== 更新 ====================
    private async Task CheckUpdateAsync()
    {
        UpdateInfo? info;
        using (Dlg.Busy(L("正在检查更新…")))
            info = await Api.TryCallAsync<UpdateInfo>("check_update");
        if (info == null)
        {
            Toast(L("检查失败"), L("更新源没有响应"), ToastKind.Warning);
            return;
        }
        if (!info.HasUpdate)
        {
            Toast(L("已是最新"), string.IsNullOrEmpty(info.Message) ? L("当前就是最新版本") : info.Message, ToastKind.Success);
            return;
        }
        var body = $"{info.Version}\n{info.Message}\n{info.Url}".Trim();
        if (!await Dlg.Confirm(L("发现新版本"), body + L("\n\n现在下载更新包？"), L("下载更新"), L("以后再说"))) return;
        await Api.StartTaskAsync("start_self_update");
        Toast(L("正在下载更新"), L("进度看下载任务，下完关掉启动器运行更新包即可"), ToastKind.Success);
        Win?.Navigate("tasks");
    }

    // ==================== 空间清理 ====================
    /// <summary>先 cleaner_preview 报个数，用户确认后才 cleaner_apply 真删。两步都在后台线程上跑完再回 UI。</summary>
    private async Task CleanAsync()
    {
        _clean.IsEnabled = false;
        _clean.Content = L("扫描中…");
        try
        {
            _cleanPreview = await Api.CallAsync<CleanerPreview>("cleaner_preview");
        }
        finally
        {
            _clean.IsEnabled = true;
            _clean.Content = Ui.H(6, Ui.Glyph(Ico.Broom, 12.5), Ui.Txt(L("扫描并清理"), 13));
        }
        var info = _cleanPreview;
        if (info is null || info.Count == 0)
        {
            _cleanInfo.Text = L("没有可清理的文件");
            Toast(L("很干净"), L("没有找到可清理的文件"), ToastKind.Success);
            return;
        }
        _cleanInfo.Text = L("可清理 {0} 个文件 · {1}", info.Count, Fmt.Size(info.Bytes));

        var libs = Ui.Check(L("未引用依赖库（{0} 个 · {1}）", info.UnusedLibraries.Count, Fmt.Size(info.UnusedLibraries.Sum(x => x.Bytes))), true);
        var parts = Ui.Check(L("残留 .part（{0} 个 · {1}）", info.Parts.Count, Fmt.Size(info.Parts.Sum(x => x.Bytes))), true);
        var cache = Ui.Check(L("更新缓存（{0} 个 · {1}）", info.Cache.Count, Fmt.Size(info.Cache.Sum(x => x.Bytes))), true);
        var body = Ui.V(8,
            Ui.Muted(L("共 {0} 个文件，约 {1}。删掉的文件下次用到会自动重新下载。", info.Count, Fmt.Size(info.Bytes))),
            libs, parts, cache);
        if (!await Dlg.Ask(L("清理文件"), body, L("开始清理"), L("取消"), true)) return;

        var kinds = new List<string>();
        if (libs.IsChecked == true) kinds.Add("unused_libraries");
        if (parts.IsChecked == true) kinds.Add("parts");
        if (cache.IsChecked == true) kinds.Add("cache");
        if (kinds.Count == 0) return;

        CleanerResult? result;
        using (Dlg.Busy(L("正在清理…")))
            result = await Api.CallAsync<CleanerResult>("cleaner_apply", new { kinds });
        _cleanInfo.Text = L("已清理 {0} 个文件 · {1}", result?.Removed ?? 0, Fmt.Size(result?.Bytes ?? 0));
        Toast(L("清理完成"), _cleanInfo.Text, ToastKind.Success);
    }

    // ==================== 智能推荐 ====================
    private async Task RecommendAsync()
    {
        _rec.IsEnabled = false;
        SmartRecommendation? rec;
        try
        {
            using (Dlg.Busy(L("正在读取硬件信息…")))
                rec = await Api.CallAsync<SmartRecommendation>("get_smart_recommendation");
        }
        finally { _rec.IsEnabled = true; }
        if (rec is null) return;
        var body = Ui.V(6,
            Ui.Muted(L("本机：{0} GB 内存 / {1} 核 CPU", rec.TotalRamGb, rec.CpuCount)),
            Ui.Txt(L("推荐内存 {0} MB", rec.MemoryMb), 14, true),
            Ui.Small(L("推荐 Java {0} · 窗口 {1}×{2} · 回收器 {3}", rec.JavaMajor, rec.WindowWidth, rec.WindowHeight, rec.GcPreset)));
        if (!await Dlg.Ask(L("智能推荐"), body, L("应用推荐"))) return;
        _mem.Value = Clamp.Of(rec.MemoryMb, 512, 32768);
        if (rec.WindowWidth > 0) _w.Text = rec.WindowWidth.ToString();
        if (rec.WindowHeight > 0) _h.Text = rec.WindowHeight.ToString();
        SelectKey(_gc, string.IsNullOrEmpty(rec.GcPreset) ? "auto" : rec.GcPreset);
        Toast(L("已应用"), L("内存已设为 {0} MB，保存设置后生效", rec.MemoryMb), ToastKind.Success);
    }

    // ==================== AI 试连 ====================
    /// <summary>只拿页面上当前填的值去试连，不落盘——用户只是想测一下，不该顺手把整页设置写进去。</summary>
    private async Task TestAiAsync()
    {
        _testAi.IsEnabled = false;
        _testAi.Content = L("测试中…");
        try
        {
            var probe = await Api.TryCallAsync<Dictionary<string, JsonElement>>("get_settings", null, new()) ?? new();
            var settings = probe.ToDictionary(kv => kv.Key, kv => (object?)kv.Value);
            settings["ai_mode"] = KeyOf(_aiMode);
            settings["ai_gateway_url"] = _aiGateway.Text?.Trim() ?? "";
            settings["ai_base_url"] = _aiBase.Text?.Trim() ?? "";
            settings["ai_api_key"] = _aiKey.Text?.Trim() ?? "";
            settings["ai_model"] = _aiModel.Text?.Trim() ?? "";
            var msg = await Api.CallAsync<string>("test_ai_connection", new { settings });
            Toast(L("AI 连接成功"), msg ?? "", ToastKind.Success);
        }
        finally
        {
            _testAi.IsEnabled = true;
            _testAi.Content = Ui.H(6, Ui.Glyph(Ico.Robot, 12.5), Ui.Txt(L("测试 AI 连接"), 13));
        }
    }

    // ==================== 语言预览 ====================
    /// <summary>切语言要重启才全量生效，先用 translate 取几条目标语言的文案让用户确认挑对了。</summary>
    private async Task PreviewLanguageAsync()
    {
        var lang = KeyOf(_lang);
        if (string.IsNullOrEmpty(lang))
        {
            _langPreview.Text = "";
            return;
        }
        // translate 的 key 是词表里的中文原文，不能先 L() 再发
        var keys = new[] { "设置", "启动游戏", "下载任务" }; // i18n:ignore 桥 translate 的 key 就是中文原文
        var texts = await Task.WhenAll(keys.Select(k =>
            Api.TryCallAsync<string>("translate", new { key = k, lang }, L(k))));
        _langPreview.Text = lang == _lang0
            ? L("预览：") + string.Join(" · ", texts)
            : L("切换后界面会变成：") + string.Join(" · ", texts) + L("（重启后全量生效）");
    }

    // ==================== 主题包 ====================
    private async Task ReloadThemesAsync()
    {
        var rows = await Api.TryCallAsync<List<ThemeRow>>("list_themes", null, new()) ?? new();
        var keep = _themePack.Str();
        _themePack.Fill(rows.Select(t => t.Name), keep);
        _themeInfo.Text = rows.Count == 0
            ? L("还没有主题包。调好配色后点「保存为主题包」。")
            : L("共 {0} 个：", rows.Count) + string.Join(L("、"), rows.Take(6).Select(t => L("{0}（{1} {2}）", t.Name, (t.UiDark ? L("深色") : L("浅色")), t.ThemeColor)));
    }

    private async Task SaveThemeAsync()
    {
        var name = await Dlg.Prompt(L("保存主题包"), L("主题包名称"), L("我的主题"));
        if (string.IsNullOrWhiteSpace(name)) return;
        await Api.CallAsync<object>("save_theme", new { name = name.Trim() });
        Toast(L("已保存"), L("主题包「{0}」已保存", name.Trim()), ToastKind.Success);
        await ReloadThemesAsync();
    }

    private async Task LoadThemeAsync()
    {
        var name = _themePack.Str();
        if (string.IsNullOrEmpty(name))
        {
            Toast(L("没有主题包"), L("先保存一个再来加载"), ToastKind.Warning);
            return;
        }
        await Api.CallAsync<object>("load_theme", new { name });
        Toast(L("已加载"), L("主题包「{0}」已应用", name), ToastKind.Success);
        await LoadAsync();
    }

    private async Task DeleteThemeAsync()
    {
        var name = _themePack.Str();
        if (string.IsNullOrEmpty(name)) return;
        if (!await Dlg.Confirm(L("删除主题包"), L("删除「{0}」？", name), L("删除"), L("取消"), true)) return;
        await Api.CallAsync<object>("delete_theme", new { name });
        Toast(L("已删除"), name, ToastKind.Success);
        await ReloadThemesAsync();
    }

    private async Task ImportThemeAsync()
    {
        var path = Dlg.PickFile(L("主题包 (*.json)|*.json|全部文件|*.*"), L("导入主题包"));
        if (path is null) return;
        var name = await Api.CallAsync<string>("import_theme", new { path });
        Toast(L("已导入"), string.IsNullOrEmpty(name) ? path : L("主题包「{0}」", name), ToastKind.Success);
        await ReloadThemesAsync();
    }

    private async Task ExportThemeAsync()
    {
        var name = _themePack.Str();
        if (string.IsNullOrEmpty(name))
        {
            Toast(L("没有主题包"), L("先保存一个再来导出"), ToastKind.Warning);
            return;
        }
        var dest = Dlg.SaveFile(L("主题包 (*.json)|*.json"), name + ".json", L("导出主题包"));
        if (dest is null) return;
        var written = await Api.CallAsync<string>("export_theme", new { name, dest });
        Toast(L("已导出"), written ?? dest, ToastKind.Success);
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
