using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>陶瓦联机（Terracotta）。房主开房 / 访客用邀请码进。</summary>
public sealed class MultiplayerPage : PageBase
{
    public override string Title => "联机";

    private readonly TextBlock _state = new() { FontSize = 18, FontWeight = FontWeights.SemiBold };
    private readonly TextBlock _detail = Ui.Muted("");
    private readonly TextBox _room = Ui.Input("粘贴好友给的邀请码");
    private readonly TextBox _mine = Ui.Input("开房后这里会出现邀请码");
    private readonly Button _prepare, _host, _join, _idle, _copy, _fw, _stop;
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private readonly Border _dot = new() { Width = 10, Height = 10, CornerRadius = new CornerRadius(5) };

    public MultiplayerPage()
    {
        _mine.IsReadOnly = true;
        _prepare = Ui.Btn("下载并启动联机内核", BtnKind.Primary, (_, _) => Run(PrepareAsync), Ico.Download);
        _host = Ui.Btn("创建房间", BtnKind.Soft, (_, _) => Run(HostAsync), Ico.Wifi);
        _join = Ui.Btn("加入房间", BtnKind.Soft, (_, _) => Run(JoinAsync), Ico.Link);
        _idle = Ui.Btn("回到空闲", BtnKind.Chip, (_, _) => Run(async () => await Api.CallAsync("terracotta_idle")));
        _copy = Ui.Btn("复制邀请码", BtnKind.Chip, (_, _) =>
        {
            try { Clipboard.SetText(_mine.Text); Toast("已复制", "把邀请码发给朋友", ToastKind.Success); } catch { }
        }, Ico.Copy);
        _fw = Ui.Btn("放行防火墙", BtnKind.Chip, (_, _) => Run(async () =>
        {
            var msg = await Api.CallAsync<string>("terracotta_allow_firewall");
            Toast("防火墙", msg ?? "已提交规则", ToastKind.Success);
        }), Ico.Shield);
        _stop = Ui.Btn("关闭内核", BtnKind.Ghost, (_, _) => Run(async () =>
        {
            await Api.CallAsync("terracotta_shutdown");
            await ReloadAsync();
        }));

        var status = Ui.Card(Ui.V(10,
            Ui.H(10, _dot.VCenter(), _state),
            _detail,
            Ui.H(8, _prepare, _fw, _stop)), 18);

        var hostCard = Ui.Card(Ui.V(10,
            Ui.Section("我来开房", "把邀请码发给朋友，他们填进「加入房间」"),
            Ui.H(8, _host, _copy),
            _mine), 16);

        var joinCard = Ui.Card(Ui.V(10,
            Ui.Section("加入朋友的房间", "进游戏后在多人游戏里连 127.0.0.1 显示的端口"),
            _room,
            Ui.H(8, _join, _idle)), 16);

        var cols = Ui.G(null, "*,*");
        cols.Add(hostCard.M(0, 0, 7, 0), 0, 0);
        cols.Add(joinCard.M(7, 0, 0, 0), 0, 1);

        Content = ScrollBody(
            Ui.Section("联机", "基于陶瓦（Terracotta）内核的联机中转，免公网 IP"),
            status, cols,
            Ui.Muted("提示：房主需要先在游戏里「对局域网开放」，访客再用邀请码加入。"));

        _timer.Tick += (_, _) => Run(ReloadAsync);
    }

    protected override async Task LoadAsync() => await ReloadAsync();

    public override void OnShown() => _timer.Start();
    public override void OnHidden() => _timer.Stop();

    private async Task ReloadAsync()
    {
        var s = await Api.TryCallAsync<TerracottaSnap>("terracotta_snapshot");
        if (s is null) return;
        _state.Text = string.IsNullOrWhiteSpace(s.Label) ? s.State : s.Label;
        var bits = new List<string>();
        if (!s.Supported) bits.Add("当前系统架构不支持");
        bits.Add(s.Installed ? "内核已安装" : "内核未安装");
        bits.Add(s.Running ? "内核运行中" : "内核未运行");
        if (!string.IsNullOrWhiteSpace(s.Url)) bits.Add(s.Url);
        if (!string.IsNullOrWhiteSpace(s.Error)) bits.Add("错误：" + s.Error);
        _detail.Text = string.Join(" · ", bits);
        _dot.SetResourceReference(Border.BackgroundProperty, s.Running ? "B.Ok" : s.Installed ? "B.Warn" : "B.InkFaint");
        if (!string.IsNullOrWhiteSpace(s.Room)) _mine.Text = s.Room;
        _prepare.IsEnabled = s.Supported && !s.Running;
        _host.IsEnabled = _join.IsEnabled = _idle.IsEnabled = s.Running;
        _stop.IsEnabled = s.Running;
    }

    private async Task PrepareAsync()
    {
        await Api.StartTaskAsync("terracotta_prepare");
        Toast("正在准备联机内核", "进度看下载任务");
    }

    private async Task HostAsync()
    {
        await Api.CallAsync("terracotta_host");
        await ReloadAsync();
        Toast("已开房", "等邀请码出现后发给朋友", ToastKind.Success);
    }

    private async Task JoinAsync()
    {
        var room = _room.Text?.Trim() ?? "";
        if (string.IsNullOrEmpty(room))
        {
            Toast("先填邀请码", "", ToastKind.Warning);
            Motion.Shake(_room);
            return;
        }
        await Api.CallAsync("terracotta_join", new { room });
        await ReloadAsync();
    }
}
