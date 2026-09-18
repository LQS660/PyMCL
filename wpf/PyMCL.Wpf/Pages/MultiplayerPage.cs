using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// 陶瓦联机（Terracotta）。动作区按后端状态机渲染，与 Qt 端 multiplayer_page 逐档对齐。
///
/// 会合节点的硬约束（extraNodes 必须含 HMCL_CUSTOM_NODE）由后端 terracotta.public_nodes()
/// 统一兜住：开房 / 加入一律经 terracotta_host / terracotta_join 走那一条路，
/// 前端不自带节点表、也不绕过它们直连内核 HTTP 口，漏传节点的 PingHostFail 就不会出现。
/// </summary>
public sealed class MultiplayerPage : PageBase
{
    public override string Title => L("联机");

    private const string ProjectHome = "https://github.com/burningtnt/Terracotta";

    private readonly TextBlock _state = new() { FontSize = 18, FontWeight = FontWeights.SemiBold };
    private readonly TextBlock _detail = Ui.Muted("");
    private readonly TextBlock _lan = Ui.Small("");
    private readonly TextBlock _nodes = Ui.Small("");
    private readonly TextBlock _room = new() { FontSize = 21, FontWeight = FontWeights.Bold };
    private readonly TextBlock _roomHint = Ui.Small("");
    private readonly Border _roomCard;
    private readonly SPanel _actions = Ui.V(10);
    private readonly SPanel _players = Ui.V(8);
    private readonly TextBlock _playersTitle = Ui.Txt(L("房间成员"), 13, true);
    private readonly Border _dot = new() { Width = 10, Height = 10, CornerRadius = new CornerRadius(5) };
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMilliseconds(1200) };

    private bool _busy;
    private bool _polling;
    private bool _autoStarted;
    private string _uiState = "";
    private string _playerSig = "";
    private string _lastState = "";
    private string _prepareTask = "";

    public MultiplayerPage()
    {
        var fw = Ui.Btn(L("允许访问"), BtnKind.Primary, (_, _) => Run(AllowFirewallAsync), Ico.Shield);
        var fwOpen = Ui.Btn(L("打开设置"), BtnKind.Chip, (_, _) => Run(OpenFirewallAsync));
        var stop = Ui.Btn(L("关闭内核"), BtnKind.Ghost, (_, _) => Run(async () =>
        {
            await Api.CallAsync("terracotta_shutdown");
            await ReloadAsync();
        }));

        var status = Ui.Card(Ui.V(10,
            Ui.H(10, _dot.VCenter(), _state),
            _detail.Wrap(),
            Ui.H(8, fw, fwOpen, stop)), 18);

        var copy = Ui.Btn(L("复制邀请码"), BtnKind.Chip, (_, _) => Copy(_room.Text), Ico.Copy);
        _room.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        _roomCard = Ui.Card(Ui.V(6,
            Ui.Small(L("邀请码")),
            Ui.H(10, _room.VCenter(), copy.VCenter()),
            _roomHint.Wrap()), 16);
        _roomCard.Visibility = Visibility.Collapsed;

        _playersTitle.Visibility = Visibility.Collapsed;

        var foot = Ui.H(10,
            Ui.Btn(L("Terracotta 项目主页"), BtnKind.Ghost, (_, _) => Ui.OpenUrl(ProjectHome), Ico.Link),
            Ui.Small(L("Terracotta | 陶瓦联机  © burningtnt  ·  基于 EasyTier")).VCenter());

        Content = ScrollBody(
            Ui.Section(L("陶瓦联机"), L("输入邀请码即可加入。陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道；")
                                   + L("会与 HMCL 一样带上自定义会合节点。PCL 房间号不互通，局域网请用下面的地址。")),
            _lan.Wrap(),
            status,
            _roomCard,
            _actions,
            _playersTitle,
            _players,
            _nodes.Wrap(),
            foot);

        _timer.Tick += (_, _) => Run(ReloadAsync);
    }

    protected override async Task LoadAsync()
    {
        await LoadLanAsync();
        await ReloadAsync();
    }

    public override void OnShown()
    {
        _timer.Start();
        Run(MaybePrepareAsync);
    }

    public override void OnHidden() => _timer.Stop();

    /// <summary>局域网直连地址。lan_hint 给成句的提示，local_ips 给可单独复制的网卡地址。</summary>
    private async Task LoadLanAsync()
    {
        var hint = await Api.TryCallAsync<string>("lan_hint", new { port = 25565 }, "") ?? "";
        var ips = await Api.TryCallAsync<List<string>>("local_ips", null, new()) ?? new();
        _lan.Text = ips.Count > 0
            ? L("本机局域网地址：{0}", string.Join(L("、"), ips.Select(ip => ip + ":25565")))
            : hint;
        _lan.ToolTip = string.IsNullOrWhiteSpace(hint) ? null : hint;
    }

    // ==================== 轮询 ====================
    private async Task ReloadAsync()
    {
        if (_polling) return;
        _polling = true;
        try
        {
            var snap = await Api.TryCallAsync<TerracottaSnap>("terracotta_snapshot");
            if (snap != null) Render(snap);
        }
        finally { _polling = false; }
    }

    private async Task MaybePrepareAsync()
    {
        if (_autoStarted || _busy) return;
        var snap = await Api.TryCallAsync<TerracottaSnap>("terracotta_snapshot");
        if (snap is { Supported: true, Installed: true, Running: false })
        {
            _autoStarted = true;
            await PrepareAsync(null);
        }
    }

    private void Render(TerracottaSnap s)
    {
        var state = string.IsNullOrEmpty(s.State) ? "missing" : s.State;
        if (_busy && state is "missing" or "idle") state = "installing";
        else if (state is "waiting" or "host-ok" or "guest-ok" || state == "idle") _busy = false;

        _state.Text = state is "exception" or "fatal" ? L("加入失败")
            : string.IsNullOrWhiteSpace(s.Label) ? state : s.Label;
        _dot.SetResourceReference(Border.BackgroundProperty, DotBrush(state));

        var text = !string.IsNullOrWhiteSpace(s.Error) ? s.Error : s.Label;
        if (!string.IsNullOrWhiteSpace(s.ErrorHint)) text = (s.Error + "\n" + s.ErrorHint).Trim();
        else if (!string.IsNullOrWhiteSpace(s.DifficultyHint)) text = (s.Label + "\n" + s.DifficultyHint).Trim();
        var bits = new List<string>();
        if (!s.Supported) bits.Add(L("当前系统架构不支持"));
        bits.Add(s.Installed ? L("内核已安装") : L("内核未安装"));
        bits.Add(s.Running ? L("内核运行中") : L("内核未运行"));
        if (!string.IsNullOrWhiteSpace(s.Player)) bits.Add(L("玩家 ") + s.Player);
        if (s.GameRunning) bits.Add(L("游戏运行中"));
        _detail.Text = string.Join(" · ", bits) + (string.IsNullOrWhiteSpace(text) ? "" : "\n" + text);

        var hasRoom = !string.IsNullOrWhiteSpace(s.Room) || !string.IsNullOrWhiteSpace(s.Url);
        _roomCard.Show(hasRoom);
        if (hasRoom)
        {
            _room.Text = string.IsNullOrWhiteSpace(s.Room) ? L("陶瓦联机大厅") : s.Room;
            _roomHint.Text = string.IsNullOrWhiteSpace(s.Url)
                ? L("让好友在联机页选「我想当房客」，填这串邀请码。")
                : L("启动游戏 → 多人游戏 → 双击「陶瓦联机大厅」。");
        }

        _nodes.Text = s.Nodes.Count == 0 ? "" : L("会合节点 {0} 个：{1}", s.Nodes.Count, string.Join("  ", s.Nodes.Take(3)));

        if (state != _uiState)
        {
            _uiState = state;
            FillActions(state, s);
        }
        RenderPlayers(s.Profiles);

        if (!string.IsNullOrWhiteSpace(s.Room) && state == "host-ok" && _lastState != "host-ok")
            Copy(s.Room, L("已把邀请码复制到剪贴板"));
        _lastState = state;
    }

    private static string DotBrush(string state) => state switch
    {
        "host-ok" or "guest-ok" or "waiting" => "B.Ok",
        "idle" => "B.Accent",
        "exception" or "fatal" or "unsupported" => "B.Danger",
        "missing" => "B.Warn",
        _ => "B.InkFaint",
    };

    private void RenderPlayers(List<TerracottaProfile> profiles)
    {
        var sig = string.Join("|", profiles.Select(p => $"{p.Name}/{p.Kind}/{p.Vendor}"));
        if (sig == _playerSig) return;
        _playerSig = sig;
        _players.Children.Clear();
        _playersTitle.Show(profiles.Count > 0);
        foreach (var p in profiles)
        {
            var host = string.Equals(p.Kind, "HOST", StringComparison.OrdinalIgnoreCase);
            var g = Ui.G(null, "Auto,*,Auto");
            g.Add(new ThumbTile(p.Name, 36, 18).M(0, 0, 12, 0), 0, 0);
            g.Add(Ui.V(1,
                Ui.Txt(string.IsNullOrWhiteSpace(p.Name) ? L("玩家") : p.Name, 13, true).Trim(),
                Ui.Small(string.IsNullOrWhiteSpace(p.Vendor) ? (host ? L("房主") : L("成员")) : p.Vendor)).VCenter(), 0, 1);
            g.Add(Ui.Tag(host ? L("房主") : L("成员"), "B.OnAccent", "B.Accent").VCenter(), 0, 2);
            _players.Children.Add(Ui.Card(g, 12));
        }
        Motion.Stagger(_players, 18, 190, 8);
    }

    // ==================== 动作区 ====================
    private void FillActions(string state, TerracottaSnap s)
    {
        _actions.Children.Clear();
        switch (state)
        {
            case "unsupported":
                Action("!", L("当前系统不支持"), L("陶瓦联机暂未提供此架构的官方内核。"), L("了解"),
                    () => { Ui.OpenUrl(ProjectHome); return Task.CompletedTask; });
                break;
            case "missing":
                Action(L("瓦"), L("下载陶瓦联机内核"), L("首次使用需要下载约 8 MB 的官方内核，之后可直接开房。"),
                    L("下载"), () => PrepareAsync(_actions), true);
                break;
            case "idle":
                Action("▶", L("启动联机内核"), L("内核已安装，点一下即可开始联机。"),
                    L("启动"), () => PrepareAsync(_actions), true);
                break;
            case "launching":
            case "unknown":
            case "installing":
                Action("…", L("请稍候"), string.IsNullOrWhiteSpace(s.Label) ? L("正在准备联机内核。") : s.Label,
                    L("刷新"), ReloadAsync);
                break;
            case "waiting":
                Action(L("房"), L("我想当房主"), L("创建房间并生成邀请码，与好友一起畅玩。"), L("创建"), HostAsync, true);
                Action(L("客"), L("我想当房客"), L("输入房主提供的邀请码加入游戏世界。"), L("加入"), JoinAsync);
                break;
            case "host-scanning":
            case "host-starting":
                Action(L("扫"), L("正在扫描局域网世界"), L("请启动游戏，进入单人世界，按 ESC，选择对局域网开放。"),
                    L("退出"), BackAsync);
                break;
            case "host-ok":
                Action(L("复"), L("复制邀请码"), L("好友在联机页选「我想当房客」并填这串邀请码即可加入。"),
                    L("复制"), () => { Copy(_room.Text, L("已把邀请码复制到剪贴板")); return Task.CompletedTask; }, true);
                Action(L("返"), L("退出"), L("这会彻底关闭房间，其他房客将一并退出。"), L("退出"), BackAsync);
                break;
            case "guest-connecting":
            case "guest-starting":
                Action(L("连"), L("正在加入房间"),
                    string.IsNullOrWhiteSpace(s.DifficultyHint) ? L("正在与房主建立连接。") : s.DifficultyHint,
                    L("退出"), BackAsync);
                break;
            case "guest-ok":
                Action(L("进"), L("进入世界"), L("启动游戏后到多人游戏双击「陶瓦联机大厅」，或点这里直接进入。"),
                    L("进入"), EnterWorldAsync, true);
                Action(L("返"), L("退出"), L("这不影响其他房客加入当前房间。"), L("退出"), BackAsync);
                break;
            case "exception":
            case "fatal":
                Action("!", L("联机失败"),
                    string.IsNullOrWhiteSpace(s.ErrorHint) ? (string.IsNullOrWhiteSpace(s.Error) ? L("请返回后重试，或检查网络。") : s.Error) : s.ErrorHint,
                    L("返回"), BackAsync);
                Action(L("直"), L("朋友是公网就直连"),
                    L("让他把单人世界对局域网开放，并在路由映射该端口，然后填他的公网 IP:端口。"),
                    L("直连"), DirectConnectAsync);
                Action(L("启"), L("重新启动内核"), L("若内核已退出，点此重新拉起。"), L("重启"), () => PrepareAsync(_actions));
                break;
        }
    }

    private void Action(string letter, string title, string desc, string btnText, Func<Task> act, bool primary = false)
    {
        var btn = Ui.Btn(btnText, primary ? BtnKind.Primary : BtnKind.Normal, (_, _) => Run(act));
        btn.MinWidth = 96;
        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(new ThumbTile(letter, 46, 12).M(0, 0, 14, 0), 0, 0);
        g.Add(Ui.V(2, Ui.Txt(title, 13.5, true), Ui.Small(desc).Wrap()).VCenter(), 0, 1);
        g.Add(btn.VCenter().M(14, 0, 0, 0), 0, 2);
        var card = Ui.Card(g, 14);
        Motion.HoverLift(card, 1.004, 1, 16);
        _actions.Children.Add(card);
    }

    // ==================== 具体操作 ====================
    private async Task PrepareAsync(FrameworkElement? anchor)
    {
        if (_busy) return;
        _busy = true;
        _prepareTask = await Api.StartTaskAsync("terracotta_prepare");
        if (anchor != null && SettingsPage.FlyEnabled) Win?.FlyToTasks(anchor, L("联"));
        Toast(L("正在准备联机内核"), L("进度看下载任务"));
        await ReloadAsync();
    }

    private async Task HostAsync()
    {
        // 房间是挂在当前账号名下的，开之前当场问一次而不是用轮询快照里那份——
        // 用户可能刚在账号页换了人，快照最长会慢 1.2 秒。
        var player = await Api.TryCallAsync<string>("terracotta_player", null, "Player");
        var snap = await Api.TryCallAsync<TerracottaSnap>("terracotta_snapshot");
        if (snap is { GameRunning: false })
        {
            if (!await Dlg.Confirm(L("您似乎忘记启动游戏了"),
                    L("将以「{0}」的身份开房。\n请先启动游戏，进入单人世界，按 ESC，选择「对局域网开放」。", player),
                    L("游戏已启动"), L("取消"))) return;
        }
        else Toast(L("正在开房"), L("以「{0}」的身份创建房间", player));
        await Api.CallAsync("terracotta_host");
        await ReloadAsync();
    }

    private async Task JoinAsync()
    {
        var room = await Dlg.Prompt(L("我想当房客"), L("请输入房主提供的邀请码"), "", "U/XXXX-XXXX-XXXX-XXXX");
        if (string.IsNullOrWhiteSpace(room)) return;
        await Api.CallAsync("terracotta_join", new { room = room.Trim() });
        await ReloadAsync();
    }

    /// <summary>公网直连：朋友有公网 IP 时不经会合节点，后端会直接拉起游戏连过去。</summary>
    private async Task DirectConnectAsync()
    {
        var addr = await Dlg.Prompt(L("公网直连"),
            L("朋友需先对局域网开放世界，并在路由器映射该端口，然后填他的公网地址。"), "", L("例如 1.2.3.4:25565"));
        if (string.IsNullOrWhiteSpace(addr)) return;
        var result = await Api.CallAsync<string>("terracotta_direct_connect", new { address = addr.Trim() });
        Toast(L("正在直连"), string.IsNullOrWhiteSpace(result) ? L("启动后会进入该服务器。") : result, ToastKind.Success);
        await ReloadAsync();
    }

    /// <summary>已连上房间时直接拉起游戏进大厅；游戏已经开着就只给一句提示。</summary>
    private async Task EnterWorldAsync()
    {
        var result = await Api.CallAsync<string>("terracotta_enter_world") ?? "";
        if (result.StartsWith("task-", StringComparison.Ordinal))
        {
            if (SettingsPage.FlyEnabled) Win?.FlyToTasks(_actions, L("进"));
            Toast(L("正在启动游戏"), L("启动后会直接进入陶瓦联机大厅"), ToastKind.Success);
        }
        else Toast(L("已加入房间"), string.IsNullOrWhiteSpace(result) ? L("请到多人游戏双击「陶瓦联机大厅」。") : result, ToastKind.Success);
        await ReloadAsync();
    }

    private async Task BackAsync()
    {
        await Api.CallAsync("terracotta_idle");
        await ReloadAsync();
    }

    private async Task AllowFirewallAsync()
    {
        var msg = await Api.CallAsync<string>("terracotta_allow_firewall");
        Toast(L("防火墙"), string.IsNullOrWhiteSpace(msg) ? L("已提交规则") : msg, ToastKind.Success);
    }

    /// <summary>打开系统防火墙设置。桥上没接就退回 ms-settings 协议。</summary>
    private async Task OpenFirewallAsync()
    {
        try { await Api.CallAsync("terracotta_open_firewall_settings"); }
        catch (BridgeCallException) { Ui.OpenUrl("ms-settings:windowsdefender"); }
    }

    private void Copy(string text, string? title = null)
    {
        title ??= L("已复制");
        text = (text ?? "").Trim();
        if (text.Length == 0) return;
        try
        {
            Clipboard.SetText(text);
            Toast(title, text, ToastKind.Success);
        }
        catch { }
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        if (ev.Event != "finished") return;
        Run(async () =>
        {
            // 任务标题可能不在本端 TaskStore 里（页面没开时起的），问桥要一次。
            var title = TaskStore.Get(ev.TaskId)?.Title
                        ?? await Api.TryCallAsync<string>("task_title", new { task_id = ev.TaskId }, "") ?? "";
            if (ev.TaskId != _prepareTask && !title.Contains("陶瓦", StringComparison.Ordinal)) return; // i18n:ignore 桥起的任务标题原文
            _busy = false;
            if (ev.TaskId == _prepareTask) _prepareTask = "";
            if (!ev.Success) Toast(string.IsNullOrWhiteSpace(title) ? L("联机内核") : title, ev.Message, ToastKind.Error);
            await ReloadAsync();
        });
    }
}
