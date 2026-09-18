// i18n:ignore-file —— 冒烟报告里的备注是开发者看的日志，不进词表；按钮白名单是 L() 的 key，比对时再取词。
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using PyMCL.Pages;
using PyMCL.Services;

namespace PyMCL;

/// <summary>
/// 运行期冒烟：真起应用、逐页导航一遍、每页截一张图，把编译期看不出来的东西抬出来
/// （XAML 资源键拼错、绑定路径写错、构造顺序、空引用、桥没连上时的降级路径）。
///
///   PyMCL.Wpf.exe --smoke [--smoke-timeout 90] [--no-bridge]
///
/// **这条命令必须自己结束。** 三道保险：
///   1. 看门狗线程到点 Environment.Exit，不管主线程卡在哪；
///   2. 每页单独限时，一页卡住不拖垮整轮；
///   3. 冒烟模式下所有会等人点的路径都被短路（连桥失败不弹框、首启向导不弹）。
/// 留一个等人点的窗口就等于把调用方挂死，这在无人值守里是不可接受的。
/// </summary>
public static class Smoke
{
    /// <summary>冒烟模式。生产路径上一律 false，只有 --smoke 会把它打开。</summary>
    public static bool Active { get; private set; }

    // ---- 异步操作登记：PageBase.Run 每起一个处理器就登记一笔，收场再销掉 ----
    // 记的是「哪一笔、什么时候起的」，不是一个总计数：点击之后只等**这一下点出来**的活，
    // 上一页某个慢网络请求（比如拉版本清单）不该让后面每一页的点击都白等到预算用光。
    private static long _opSeq;
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<long, long> _inflight = new();   // 序号 → 开始时刻
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<long, long> _finishedAt = new(); // 序号 → 收场时刻

    /// <summary>登记一个异步操作开始，返回序号；不在冒烟里返回 0（不登记、零开销）。</summary>
    public static long OperationStarted()
    {
        if (!Active) return 0;
        var id = Interlocked.Increment(ref _opSeq);
        _inflight[id] = Stopwatch.GetTimestamp();
        return id;
    }

    public static void OperationFinished(long id)
    {
        if (id == 0) return;
        if (_inflight.TryRemove(id, out _)) _finishedAt[id] = Stopwatch.GetTimestamp();
    }

    /// <summary>自 since 时刻起开始、此刻还没收场的操作序号。</summary>
    private static long[] PendingSince(long since) =>
        _inflight.Where(kv => kv.Value >= since).Select(kv => kv.Key).ToArray();

    private static long MsSince(long from, long to) => (to - from) * 1000 / Stopwatch.Frequency;

    /// <summary>点完预算内没收场的那些点击：整轮结束再回头看它们到底收了没收（收了记时长，没收判红）。</summary>
    private static readonly List<(string Page, string Label, long ClickedAt, long[] Ops, Dictionary<string, object?> Record)> _late = new();
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hwnd, int index);
    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hwnd, int index, int value);

    private const int DefaultPageBudgetMs = 9000;
    private const int DefaultClickBudgetMs = 15000;
    private const int MaxClicksPerPage = 4;
    private const int MinClicks = 20;
    private const int MinDialogs = 10;

    private static readonly List<Dictionary<string, object?>> _pages = new();
    private static readonly List<string> _issues = new();
    private static string _dir = "";
    private static int _pageBudgetMs = DefaultPageBudgetMs;
    private static int _clickBudgetMs = DefaultClickBudgetMs;
    private static string _runLabel = "";

    private static readonly List<Dictionary<string, object?>> _dialogs = new();
    private static readonly List<Dictionary<string, object?>> _clicks = new();

    /// <summary>
    /// 只点这些按钮。**白名单制，不是黑名单**——冒烟跑在用户真实的游戏目录上，
    /// 「删除实例」「清空统计」「卸载版本」这类按钮点一下就没法撤销了。
    /// 这里挑的都是「只读、或只会弹一个框」的：弹出来的框由 AutoAnswerDialog 一律按取消收掉，
    /// 什么都不会被提交。宁可少覆盖几个，也不能让冒烟把人家的存档删了。
    /// </summary>
    private static readonly string[] SafeButtons =
    {
        "刷新", "刷新清单", "刷新新闻", "查看", "查看推荐", "查看系统信息", "检查更新",
        "版本设置", "存档管理", "模组管理", "全局模组", "选择 Java", "隔离细分",
        // 正版（微软）登录需要真实账号与浏览器授权，按无人值守约定明确跳过。
        "皮肤", "添加离线账号", "皮肤站登录", "统一通行证",
        "保存为主题包", "加载", "导入", "导入本地文件", "选择版本", "链接安装", "挑着更新模组",
        "新建实例", "导入官方启动器", "新对话", "选择入口", "重新运行", "重置条件",
        "智能推荐", "扫描并清理", "扫描系统 Java", "测试 AI 连接", "复制启动命令",
    };

    /// <summary>
    /// 任何情况下都不碰的词。白名单之外再加一道：万一将来有人往白名单里加了个
    /// 「删除主题包」这样前缀撞上的，这一道能拦住。
    /// </summary>
    private static readonly string[] NeverClick =
    {
        "删除", "卸载", "清空", "清除", "移除", "永久", "恢复出厂", "重置",
        "启动游戏", "安装", "导出", "提交", "发送", "撤销", "关闭壁纸", "保存设置",
    };

    /// <summary>页面加载里被吞掉的异常也要记一笔——它们不会冒到 UI 线程的未处理钩子上。</summary>
    public static void Note(string where, string message)
    {
        if (!Active) return;
        lock (_issues) _issues.Add($"{where}: {message}");
    }

    /// <summary>
    /// 替用户把弹窗点掉。**一律走「取消 / 关闭」那一路，从不点主按钮**——
    /// 主按钮是「确定删除」「开始清理」这类真会落地的动作，冒烟只该验证框能开能关，
    /// 不该替用户做决定。
    /// </summary>
    public static void AutoAnswerDialog(UIElement card, Action dismiss)
    {
        if (card is not FrameworkElement fe) return;
        var title = FirstText(fe);
        var record = new Dictionary<string, object?> { ["title"] = title, ["type"] = "in-app" };
        lock (_dialogs) _dialogs.Add(record);

        fe.Dispatcher.BeginInvoke(DispatcherPriority.Background, () =>
        {
            try
            {
                record["shot"] = ShootDialog(title);
                var buttons = Descendants<ButtonBase>(fe).Where(b => b.IsEnabled).ToList();
                // 只按明确的取消按钮，绝不回退到第一个按钮。按钮文案是当前语言的，所以拿译文再比。
                string[] cancels = { "取消", "算了", "关闭", "跳过", "知道了", "以后再说", "留空" };
                var cancelLabels = cancels.Select(T).ToArray();
                var pick = buttons.FirstOrDefault(b => cancelLabels.Contains(TextOf(b).Trim(), StringComparer.Ordinal));
                if (pick is null)
                {
                    lock (_dialogs) record["answered_with"] = "取消（对话层关闭）";
                    dismiss();
                    return;
                }
                lock (_dialogs) record["answered_with"] = TextOf(pick);
                pick.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
            }
            catch (Exception ex) { Note("dialog", $"「{title}」自动应答失败：{ex.Message}"); }
        });
    }

    /// <summary>
    /// Win32 文件选择器不属于 WPF 视觉树，不能靠 Dlg 的按钮钩子关闭。冒烟里不把它真弹出来，
    /// 而是把「请求过这个系统对话框并按取消返回」记进报告；生产路径仍走真实选择器。
    /// </summary>
    public static void AutoCancelSystemDialog(string title)
    {
        if (!Active) return;
        lock (_dialogs)
            _dialogs.Add(new Dictionary<string, object?>
            {
                ["title"] = title,
                ["type"] = "system-file-dialog",
                ["answered_with"] = "取消（冒烟）",
            });
    }

    private static string FirstText(DependencyObject root) =>
        Descendants<TextBlock>(root).Where(t => !IsGlyph(t)).Select(t => t.Text)
            .FirstOrDefault(s => !string.IsNullOrWhiteSpace(s)) ?? "(无标题)";

    /// <summary>
    /// 图标字是 Segoe MDL2 Assets 的私有区码位，不是人看的字。带图标的按钮
    /// （Ui.Btn 传了 glyph）内容是「图标 TextBlock + 文字 TextBlock」，
    /// 不排掉图标就只会读到一个方块字符，白名单永远匹配不上。
    /// </summary>
    private static bool IsGlyph(TextBlock t) =>
        t.FontFamily?.Source?.Contains("MDL2", StringComparison.OrdinalIgnoreCase) == true;

    private static string TextOf(DependencyObject el)
    {
        if (el is ContentControl cc)
        {
            if (cc.Content is string s && !string.IsNullOrWhiteSpace(s)) return s;
            if (cc.Content is DependencyObject d)
            {
                var inner = FirstText(d);
                if (inner != "(无标题)") return inner;
            }
        }
        var vis = FirstText(el);
        // 纯图标按钮（IconBtn）没有文字，只有 ToolTip，拿它当名字
        if (vis == "(无标题)" && el is FrameworkElement { ToolTip: string tip } && !string.IsNullOrWhiteSpace(tip))
            return tip;
        return vis;
    }

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        var n = VisualTreeHelper.GetChildrenCount(root);
        for (var i = 0; i < n; i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T hit) yield return hit;
            foreach (var deep in Descendants<T>(child)) yield return deep;
        }
    }

    public static int Run(string[] args)
    {
        Active = true;
        // 逐页点按钮之后单轮就不可能再是 90s 的量级了：19 个页面，每页最多 4 次点击，
        // 每次点击都可能弹一个要读盘 / 问桥的框。默认给足，真卡住有看门狗兜着。
        var timeout = ArgInt(args, "--smoke-timeout", 420);
        _pageBudgetMs = ArgInt(args, "--smoke-page-budget", DefaultPageBudgetMs);
        // --smoke-click-budget 0 = 退回到只导航不点的老口径
        _clickBudgetMs = ArgInt(args, "--smoke-click-budget", DefaultClickBudgetMs);
        // --smoke-search-timeout 1 = 把目录页在线搜索的超时压到 1ms：所有搜索必超时，
        // 用来证明「搜不到 / 断网时页面显示错误态与重试，而不是卡住」。这也是负向对照，目录名要带出身。
        var searchTimeoutMs = ArgInt(args, "--smoke-search-timeout", CatalogPage.SearchTimeoutMs);
        var searchStarved = searchTimeoutMs != CatalogPage.SearchTimeoutMs;
        CatalogPage.SearchTimeoutMs = searchTimeoutMs;
        VersionPage.FetchTimeoutMs = searchTimeoutMs; // 版本清单的在线拉取与目录页搜索同一口径
        // 每一轮单独一个目录，目录名自带这一轮的口径。
        // 以前所有轮都往同一个目录里写：跑完正常轮再跑一次「把预算压到 1ms」的负向对照，
        // 后者会把前者的 19 张截图original 悄悄盖掉——事后看图的人只会看到一屋子没加载完的空页面，
        // 并且**看不出这是故意饿着跑的那一轮**，很容易当成 UI 坏了。产物必须自带出身。
        var negative = _pageBudgetMs != DefaultPageBudgetMs || _clickBudgetMs != DefaultClickBudgetMs || searchStarved;
        // 非中文那一轮把语言写进目录名，跟中文轮的截图分开放
        var langTag = I18n.Current == I18n.DefaultLang ? "" : I18n.Current + "-";
        _runLabel = !negative
            ? $"run-{langTag}{DateTime.Now:yyyyMMdd-HHmmss}"
            : $"negative-{langTag}p{_pageBudgetMs}-c{_clickBudgetMs}{(searchStarved ? $"-s{searchTimeoutMs}" : "")}-{DateTime.Now:yyyyMMdd-HHmmss}";
        _dir = Path.Combine(BridgeRootOrHere(), "_wpf_smoke", _runLabel);
        Directory.CreateDirectory(_dir);

        Watchdog(timeout);

        var app = Application.Current;
        var win = new MainWindow();
        // 无人值守默认离屏渲染，既不抢焦点，也不占任务栏。
        Motion.Enabled = false;
        win.ShowActivated = false;
        win.ShowInTaskbar = false;
        win.WindowStartupLocation = WindowStartupLocation.Manual;
        win.Left = SystemParameters.VirtualScreenLeft - win.Width - 100;
        win.Top = SystemParameters.VirtualScreenTop - win.Height - 100;
        win.SourceInitialized += (_, _) =>
        {
            var hwnd = new System.Windows.Interop.WindowInteropHelper(win).Handle;
            SetWindowLong(hwnd, -20, GetWindowLong(hwnd, -20) | 0x08000000); // WS_EX_NOACTIVATE
        };
        win.Show();
        app.Dispatcher.InvokeAsync(async () => await DriveAsync(win), DispatcherPriority.ApplicationIdle);
        return 0;   // 真正的退出码由 DriveAsync 末尾的 Shutdown 决定
    }

    /// <summary>到点就地掐掉。主线程卡在任何地方都拦不住它——这是最后一道保险。</summary>
    private static void Watchdog(int seconds)
    {
        var t = new Thread(() =>
        {
            Thread.Sleep(TimeSpan.FromSeconds(seconds));
            try
            {
                Note("watchdog", $"超过 {seconds}s 仍未结束，强制退出");
                Dump(99, "watchdog-timeout");
            }
            catch { }
            try { AppServices.Host?.Dispose(); } catch { }
            Environment.Exit(99);
        })
        { IsBackground = true, Name = "smoke-watchdog" };
        t.Start();
    }

    private static async Task DriveAsync(MainWindow win)
    {
        var sw = Stopwatch.StartNew();
        var bridge = "未知";
        try
        {
            // 连桥是 Loaded 里起的异步活，等它落定再逐页走——否则每页都在"桥还没好"的状态下加载
            var settled = await Task.WhenAny(win.BridgeSettled, Task.Delay(40_000));
            bridge = settled == win.BridgeSettled
                ? (AppServices.Ready ? "已连上" : "未连上（已降级）")
                : "连接超时";
        }
        catch (Exception ex) { bridge = "连接异常：" + ex.Message; }

        foreach (var def in MainWindow.NavDefs)
        {
            var page = new Dictionary<string, object?> { ["id"] = def.Id, ["title"] = def.Title };
            var t0 = Stopwatch.StartNew();
            var navigatedAt = Stopwatch.GetTimestamp();
            var before = IssueCount();
            try
            {
                win.Navigate(def.Id, instant: true);
                // 让布局跑完再判定：构造抛的异常在这一拍才浮出来
                await win.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                var p = win.GetPage(def.Id);
                if (p is null) throw new InvalidOperationException("GetPage 返回 null");
                var load = p.EnsureLoadedAsync();
                if (await Task.WhenAny(load, Task.Delay(_pageBudgetMs)) != load)
                {
                    page["ok"] = false;
                    page["error"] = $"加载超过 {_pageBudgetMs}ms 未返回";
                    Note(def.Id, "加载超时");
                }
                else
                {
                    await load;
                    await win.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                    page["ok"] = IssueCount() == before;
                }
            }
            catch (Exception ex)
            {
                page["ok"] = false;
                page["error"] = ex.GetType().Name + ": " + ex.Message;
                Note(def.Id, ex.ToString());
            }
            page["ms"] = t0.ElapsedMilliseconds;
            // 首载起的异步活（目录页的在线搜索走 PageBase.Run，计数在飞）落地之后再截图与扫字：
            // 截的才是页面的稳定态（结果 / 空态 / 错误态 + 重试），不是一屏骨架。等多久有上限——
            // 搜索自己带 SearchTimeoutMs 的超时，到点必然收场成错误态，再给两秒让继续体跑完。
            page["settle_ms"] = await SettleAsync(win, CatalogPage.SearchTimeoutMs + 2000, navigatedAt);
            page["shot"] = Shoot(win, def.Id);
            var cjk = CjkOnScreen(win);
            page["cjk_texts"] = cjk;
            // 非中文界面下，屏幕上还出现词表 key 原文 = 界面残留；数据带来的中文不算（桥不翻译）
            if (I18n.Current != I18n.DefaultLang)
                page["cjk_ui_residue"] = cjk.Count(x => Equals(x["is_ui_key"], true));
            page["clicked"] = await ClickSafeButtonsAsync(win, win.GetPage(def.Id), def.Id);
            lock (_pages) _pages.Add(page);
        }

        // 深冒烟的门槛也是测试本身的负向对照支点：把 --smoke-click-budget 设成 0，
        // 页面导航仍会全绿，但这里必须把整轮判红，证明「按钮/弹窗覆盖」不是漂亮的空数字。
        if (_clicks.Count < MinClicks)
            Note("coverage", $"只点击了 {_clicks.Count} 个按钮，要求至少 {MinClicks} 个");
        var renderedDialogs = _dialogs.Count(d => Equals(d.GetValueOrDefault("type"), "in-app"));
        if (renderedDialogs < MinDialogs)
            Note("coverage", $"只打开了 {renderedDialogs} 个真实 WPF 弹窗，要求至少 {MinDialogs} 个；系统文件框模拟取消不计入");

        // 非中文轮：L() 回落成中文的 key 是确凿的界面残留，算这一轮红。
        // 屏幕上出现词表原文（cjk_ui_residue）只记不判：桥不翻译，它返回的标签（如 Java 下拉的「自动选择」）
        // 跟词表 key 撞车时会被算进去，得由人看 cjk_texts 分辨是界面还是数据。
        if (I18n.Current != I18n.DefaultLang)
        {
            var missing = I18n.Missing;
            if (missing.Count > 0) Note("i18n", $"{I18n.Current} 下 L() 缺词回落中文 {missing.Count} 条：{string.Join(" | ", missing.Take(20))}");
        }

        // 点过之后预算内没收场的异步活：整轮跑完还在飞 = 挂住了，判红；收场了就把真实时长写回那一下点击。
        List<(string Page, string Label, long ClickedAt, long[] Ops, Dictionary<string, object?> Record)> late;
        lock (_late) late = new(_late);
        foreach (var l in late)
        {
            var hung = l.Ops.Count(id => _inflight.ContainsKey(id));
            lock (_clicks)
            {
                if (hung > 0)
                {
                    l.Record["ok"] = false;
                    l.Record["hung"] = hung;
                    Note(l.Page, $"点「{l.Label}」起的 {hung} 个异步操作到整轮结束仍未收场");
                    continue;
                }
                var finished = l.Ops.Select(id => _finishedAt.TryGetValue(id, out var t) ? t : 0L).Max();
                l.Record["late_ms"] = MsSince(l.ClickedAt, finished);
            }
        }

        var code = _pages.Any(p => p.TryGetValue("ok", out var v) && v is false) || IssueCount() > 0 ? 1 : 0;
        Dump(code, "finished", sw.ElapsedMilliseconds, bridge);

        try { AppServices.Host?.Dispose(); } catch { }
        Application.Current.Shutdown(code);
        // Shutdown 走的是消息循环，万一被什么挡住，给它半秒后硬退
        _ = Task.Run(async () =>
        {
            await Task.Delay(1500);
            Environment.Exit(code);
        });
    }

    /// <summary>等 since 之后起的异步操作与对话层都收场，返回实际等了多久（毫秒）；到 budgetMs 就不等了。</summary>
    private static async Task<long> SettleAsync(MainWindow win, int budgetMs, long since)
    {
        var sw = Stopwatch.StartNew();
        while ((Dlg.AnyOpen || PendingSince(since).Length > 0) && sw.ElapsedMilliseconds < budgetMs)
        {
            await Task.Delay(80);
            await win.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
        }
        return sw.ElapsedMilliseconds;
    }

    /// <summary>
    /// 点这一页上白名单里的按钮。每点一下等一拍让弹窗 / 异步活动起来；
    /// 弹窗由 AutoAnswerDialog 按取消收掉，所以这一圈下来什么都不会被真正提交。
    /// </summary>
    private static async Task<int> ClickSafeButtonsAsync(MainWindow win, DependencyObject? page, string pageId)
    {
        if (page is null || _clickBudgetMs <= 0) return 0;
        var clicked = 0;
        List<ButtonBase> targets;
        try
        {
            // 只在**当前页的子树**里找。整窗扫会连侧栏导航一起点到，那会让测试自己跳走页。
            // 按文案去重：版本页上每张卡都有一个「版本设置」，点三遍走的是同一条代码路径，
            // 只是把预算烧光——同样的时间不如留给别的页。
            var seen = new HashSet<string>(StringComparer.Ordinal);
            targets = Descendants<ButtonBase>(page)
                .Where(b => b.IsEnabled && b.IsVisible)
                .Where(b => Safe(TextOf(b)))
                .Where(b => seen.Add(TextOf(b)))
                .Take(MaxClicksPerPage)
                .ToList();
        }
        catch { return 0; }

        var budget = Stopwatch.StartNew();
        foreach (var b in targets)
        {
            if (budget.ElapsedMilliseconds > _clickBudgetMs)
            {
                break;
            }
            var label = TextOf(b);
            var before = IssueCount();
            var clickedAt = Stopwatch.GetTimestamp();
            try
            {
                b.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
                await win.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                // 事件处理器都走 PageBase.Run，起了几笔活这里看得见。等这一下点出来的活收场、弹窗被钩子关闭、动画收尾；
                // 固定睡 120ms 会在 RPC 稍慢时导航到下一页，报告却抢先写成「点击成功」。
                var settle = Stopwatch.StartNew();
                do
                {
                    await Task.Delay(80);
                    await win.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                } while ((Dlg.AnyOpen || PendingSince(clickedAt).Length > 0 || settle.ElapsedMilliseconds < 350) && settle.ElapsedMilliseconds < _clickBudgetMs);
                // 对话层还开着 = 自动应答没收掉它，这是真挂住，当场判红。
                if (Dlg.AnyOpen) Note(pageId, $"点「{label}」之后对话层未在预算内关闭");
                clicked++;
                var record = new Dictionary<string, object?>
                {
                    ["page"] = pageId, ["label"] = label, ["ok"] = IssueCount() == before,
                    ["ms"] = MsSince(clickedAt, Stopwatch.GetTimestamp()),
                };
                // 预算内没收场的异步活先记「慢」，不当场判红：慢（网络）和挂住（永远不回来）是两回事，
                // 整轮结束再回头看——收场了把真实时长写回这一下，没收场才判红。
                var pending = PendingSince(clickedAt);
                if (pending.Length > 0)
                {
                    record["slow"] = true;
                    lock (_late) _late.Add((pageId, label, clickedAt, pending, record));
                }
                lock (_clicks) _clicks.Add(record);
            }
            catch (Exception ex)
            {
                Note(pageId, $"点「{label}」抛了：{ex}");
                lock (_clicks)
                    _clicks.Add(new Dictionary<string, object?>
                    {
                        ["page"] = pageId, ["label"] = label, ["ok"] = false, ["error"] = ex.Message,
                    });
            }
        }
        return clicked;
    }

    /// <summary>
    /// 白名单 / 禁词 / 取消键都存 L() 的 key（中文原文），界面上是当前语言的译文——拿译文比，没译文就拿原文。
    /// **只查不记**（I18n.Peek）：这些词不是界面上的字，走 L() 会把白名单里没译文的那几个算进 I18n.Missing，
    /// 整轮 en 冒烟就被自己的比对判红了。
    /// </summary>
    private static string T(string key) => I18n.Peek(key) ?? key;

    /// <summary>
    /// 白名单命中、且不含任何禁词，才算安全。两道门都要过。
    /// 两张表存的都是 L() 的 key（中文原文），界面上的按钮文案是当前语言的译文，所以每一项先取译文再比——
    /// 否则 --lang en 那一轮一个按钮都对不上，深冒烟就退化成只导航。
    /// </summary>
    private static bool Safe(string label)
    {
        if (string.IsNullOrWhiteSpace(label)) return false;
        var trimmed = label.Trim();
        if (trimmed == T("链接安装")) return true; // 仅打开输入框，由取消钩子关闭
        // 禁词译文与原文都拦：en 下桥带回来的中文标签（桥不翻译）照样是中文，只比译文会放过它
        if (NeverClick.Any(bad => label.Contains(T(bad), StringComparison.Ordinal) || label.Contains(bad, StringComparison.Ordinal))) return false;
        return SafeButtons.Any(ok => T(ok) == trimmed);
    }

    /// <summary>
    /// 这一页此刻画在屏幕上的中文文本。非中文界面下它就是「残留」的直接证据：
    /// is_ui_key = 这段文字本身是词表里的一个 key（多半是没走 L() 或译文缺失），
    /// 否则是数据带进来的（实例名、桥返回的任务标题 / 状态这类，桥本身不翻译）。
    /// </summary>
    private static List<Dictionary<string, object?>> CjkOnScreen(MainWindow win)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var known = new HashSet<string>(I18n.KnownKeys, StringComparer.Ordinal);
        var out_ = new List<Dictionary<string, object?>>();
        void Add(string? text)
        {
            if (string.IsNullOrWhiteSpace(text) || !I18nCheck.HasCjk(text)) return;
            var t = text.Trim();
            if (!seen.Add(t) || out_.Count >= 60) return;
            out_.Add(new Dictionary<string, object?> { ["text"] = t.Length > 80 ? t[..80] + "…" : t, ["is_ui_key"] = known.Contains(t) });
        }
        try
        {
            Add(win.Title);
            foreach (var el in Descendants<FrameworkElement>(win))
            {
                if (!el.IsVisible) continue;
                switch (el)
                {
                    case TextBlock tb when !IsGlyph(tb): Add(tb.Text); break;
                    case TextBox: break; // 输入框里是用户自己的东西
                    case ContentControl { Content: string s }: Add(s); break;
                }
                if (el.ToolTip is string tip) Add(tip);
            }
        }
        catch (Exception ex) { Note("cjk-scan", ex.Message); }
        return out_;
    }

    private static int IssueCount()
    {
        lock (_issues) return _issues.Count;
    }

    /// <summary>截一张当前窗口。渲染失败不算页面失败——截图是取证，不是判据。</summary>
    private static string Shoot(MainWindow win, string id)
    {
        try
        {
            var w = (int)Math.Max(1, win.ActualWidth);
            var h = (int)Math.Max(1, win.ActualHeight);
            var bmp = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
            bmp.Render(win);
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(bmp));
            var path = Path.Combine(_dir, $"{id}.png");
            using var fs = File.Create(path);
            enc.Save(fs);
            return path;
        }
        catch (Exception ex) { return "截图失败：" + ex.Message; }
    }

    private static string ShootDialog(string title)
    {
        try
        {
            if (Application.Current.MainWindow is not MainWindow win) return "主窗口不可用";
            var seq = _dialogs.Count;
            var safe = string.Concat(title.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
            if (safe.Length > 32) safe = safe[..32];
            return Shoot(win, $"dialog-{seq:00}-{safe}");
        }
        catch (Exception ex) { return "截图失败：" + ex.Message; }
    }

    private static void Dump(int code, string state, long ms = 0, string bridge = "")
    {
        var report = new Dictionary<string, object?>
        {
            ["state"] = state,
            ["exit_code"] = code,
            // 这一轮是什么口径，跟产物放在一起。预算不是默认值就说明是负向对照那种故意饿着跑的，
            // 别让后来看图的人把它当成真实运行结果。
            ["run"] = _runLabel,
            ["page_budget_ms"] = _pageBudgetMs,
            ["click_budget_ms"] = _clickBudgetMs,
            ["search_timeout_ms"] = CatalogPage.SearchTimeoutMs,
            ["is_negative_control"] = _runLabel.StartsWith("negative-", StringComparison.Ordinal),
            ["required_clicks"] = MinClicks,
            ["required_dialogs"] = MinDialogs,
            ["dialog_threshold_kind"] = "in-app-only",
            ["display_mode"] = "offscreen-no-activate",
            ["lang"] = I18n.Current,
            ["i18n_missing"] = I18n.Missing.OrderBy(k => k, StringComparer.Ordinal).ToList(),
            ["skipped"] = new[] { "微软正版登录（无账号，按要求跳过）" },
            ["click_evidence_scope"] = "event-dispatched; every async handler goes through PageBase.Run (pending counter awaited, exceptions recorded as issues); dialog layer settled",
            ["dir"] = _dir,
            ["elapsed_ms"] = ms,
            ["bridge"] = bridge,
            ["pages"] = Snapshot(_pages),
            ["dialogs"] = Snapshot(_dialogs),
            ["clicks"] = Snapshot(_clicks),
            ["issues"] = IssuesSnapshot(),
        };

        // 报告是这套东西唯一的产出，丢了就等于整轮白跑。序列化**必须**兜住：
        // 看门狗是在另一根线程上调过来的，主线程这会儿可能正在往集合里写。
        string json;
        try
        {
            json = JsonSerializer.Serialize(report, new JsonSerializerOptions
            {
                WriteIndented = true,
                Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            });
        }
        catch (Exception ex)
        {
            json = "{\"state\":\"" + state + "\",\"exit_code\":" + code +
                   ",\"run\":\"" + _runLabel + "\",\"serialize_error\":\"" +
                   ex.Message.Replace("\"", "'") + "\"}";
        }
        try { File.WriteAllText(Path.Combine(_dir, "report.json"), json); } catch { }
        try { Console.Out.Write(json); Console.Out.Flush(); } catch { }
    }

    /// <summary>
    /// 连里面的字典一起复制。只复制外层列表不够：AutoAnswerDialog 会回头往
    /// 已经在列表里的那个字典补 answered_with，序列化撞上就抛。
    /// </summary>
    private static List<Dictionary<string, object?>> Snapshot(List<Dictionary<string, object?>> src)
    {
        lock (src)
        {
            var copy = new List<Dictionary<string, object?>>(src.Count);
            foreach (var d in src) copy.Add(new Dictionary<string, object?>(d));
            return copy;
        }
    }

    private static List<string> IssuesSnapshot()
    {
        lock (_issues) return new List<string>(_issues);
    }


    private static int ArgInt(string[] args, string name, int fallback)
    {
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length && int.TryParse(args[i + 1], out var v) ? v : fallback;
    }

    private static string BridgeRootOrHere()
    {
        try { return BridgeHost.FindRoot(); }
        catch { return AppContext.BaseDirectory; }
    }
}
