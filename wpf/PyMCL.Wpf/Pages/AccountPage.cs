using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>账号管理：离线 / 微软 / 皮肤站（authlib）。</summary>
public sealed class AccountPage : PageBase
{
    public override string Title => "账号";

    private readonly SPanel _list = Ui.V(10);
    private readonly TextBlock _count = Ui.Muted("");
    private string? _loginTask;
    private string? _authlibTask;
    private Dlg.Layer? _loginLayer;
    private TextBlock? _loginHint, _loginCode;
    private string _loginUri = "";

    public AccountPage()
    {
        var offline = Ui.Btn("添加离线账号", BtnKind.Primary, (_, _) => Run(AddOfflineAsync, "添加失败"), Ico.Add);
        var ms = Ui.Btn("微软登录", BtnKind.Soft, (_, _) => Run(MicrosoftLoginAsync, "微软登录失败"), Ico.User);
        var authlib = Ui.Btn("皮肤站登录", BtnKind.Chip, (_, _) => Run(AuthlibLoginAsync, "皮肤站登录失败"), Ico.Shield);
        var refresh = Ui.IconBtn(Ico.Refresh, "刷新", (_, _) => Run(LoadAsync));
        var head = Ui.Section("账号", "启动游戏时使用标记为「当前」的账号",
            Ui.H(8, _count.VCenter(), refresh, authlib, ms, offline));
        Content = ScrollBody(head, _list);
    }

    protected override async Task LoadAsync()
    {
        var rows = await Api.TryCallAsync<List<AccountRow>>("get_account_rows", null, new()) ?? new();
        _list.Children.Clear();
        _count.Text = $"共 {rows.Count} 个";
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.User, "还没有账号", "添加离线账号，或用微软 / 皮肤站登录"));
            return;
        }
        foreach (var r in rows) _list.Children.Add(Row(r));
        Motion.Stagger(_list, 22, 200, 10);
    }

    private UIElement Row(AccountRow acc)
    {
        var avatar = new Border
        {
            Width = 40,
            Height = 40,
            CornerRadius = new CornerRadius(20),
            Child = Ui.Txt(string.IsNullOrEmpty(acc.Name) ? "?" : acc.Name[..1].ToUpper(), 15, true,
                acc.Active ? "B.OnAccent" : "B.AccentDeep").Center(),
        };
        avatar.SetResourceReference(Border.BackgroundProperty, acc.Active ? "B.Accent" : "B.AccentSoft");

        var typeText = acc.Type switch
        {
            "microsoft" => "微软",
            "offline" => "离线",
            "authlib" => "皮肤站",
            _ => string.IsNullOrEmpty(acc.Api)
                ? (string.IsNullOrEmpty(acc.Type) ? "其他" : acc.Type)
                : "皮肤站",
        };
        var nameRow = Ui.H(7,
            Ui.Txt(acc.Name, 13.5, true).Trim().VCenter(),
            acc.Active ? Ui.Tag("当前", "B.OnAccent", "B.Accent") : null,
            Ui.Tag(typeText));
        var sub = string.IsNullOrEmpty(acc.Uuid) ? typeText + "账号" : "UUID " + acc.Uuid;
        if (sub.Length > 40) sub = sub[..40] + "…";

        var actions = Ui.H(6);
        if (!acc.Active)
            actions.Children.Add(Ui.Btn("设为当前", BtnKind.Soft,
                (_, _) => Run(() => SetActiveAsync(acc.Name), "切换失败"), Ico.Check));
        actions.Children.Add(Ui.Btn("删除", BtnKind.Ghost,
            (_, _) => Run(() => DeleteAsync(acc), "删除失败")));
        actions.VCenter();

        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(avatar.M(0, 0, 12, 0), 0, 0);
        g.Add(Ui.V(3, nameRow, Ui.Small(sub)).VCenter(), 0, 1);
        g.Add(actions, 0, 2);
        var card = Ui.RowCard(g, padding: 12);
        Motion.HoverLift(card, 1.004, 1, 16);
        return card;
    }

    private async Task SetActiveAsync(string name)
    {
        await Api.CallAsync<object>("set_active_account", new { name });
        Toast("已切换", $"当前账号：{name}", ToastKind.Success);
        await LoadAsync();
    }

    private async Task DeleteAsync(AccountRow acc)
    {
        if (!await Dlg.Confirm("删除账号", $"将删除「{acc.Name}」的登录信息。", "删除", "取消", true)) return;
        try
        {
            await Api.CallAsync<object>("remove_account", new { name = acc.Name });
        }
        catch (BridgeCallException)
        {
            await Api.CallAsync<object>("delete_account", new { name = acc.Name });
        }
        Toast("已删除", acc.Name, ToastKind.Success);
        await LoadAsync();
    }

    private async Task AddOfflineAsync()
    {
        var name = await Dlg.Prompt("添加离线账号", "用户名（离线模式，无正版验证）", "", "例如 Steve");
        if (string.IsNullOrWhiteSpace(name)) return;
        await Api.CallAsync<object>("add_offline_account", new { username = name.Trim(), skin = "" });
        Toast("已添加", name.Trim(), ToastKind.Success);
        await LoadAsync();
    }

    // ==================== 微软登录 ====================
    private async Task MicrosoftLoginAsync()
    {
        if (_loginLayer != null) return;
        var hint = Ui.Muted("正在获取登录代码…");
        hint.TextWrapping = TextWrapping.Wrap;
        var code = new TextBlock { FontSize = 26, FontWeight = FontWeights.Bold, Text = "------" };
        code.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        _loginHint = hint;
        _loginCode = code;
        _loginUri = "";
        var copy = Ui.Btn("复制代码", BtnKind.Chip, (_, _) =>
        {
            try
            {
                if (_loginCode is { } c) Clipboard.SetText(c.Text);
                Toast("已复制", "代码已放进剪贴板", ToastKind.Success);
            }
            catch { }
        }, Ico.Copy);
        var open = Ui.Btn("打开浏览器", BtnKind.Primary, (_, _) =>
        {
            if (!string.IsNullOrEmpty(_loginUri)) Ui.OpenUrl(_loginUri);
        }, Ico.Link);
        var body = Ui.V(10, hint, code, Ui.H(8, copy, open));
        _loginLayer = Dlg.Panel("微软账号登录", body, 460, () =>
        {
            _loginLayer = null;
            if (_loginTask != null) _ = Api.TryCallAsync<object>("cancel_task", new { task_id = _loginTask });
        });
        _loginTask = await Api.StartTaskAsync("start_microsoft_login");
    }

    // ==================== 皮肤站登录 ====================
    private async Task AuthlibLoginAsync()
    {
        var presets = await Api.TryCallAsync<List<AuthlibPreset>>("authlib_presets", null, new()) ?? new();
        var api = Ui.Input("https://littleskin.cn/api/yggdrasil", presets.FirstOrDefault()?.Api ?? "");
        var user = Ui.Input("邮箱 / 用户名");
        var pw = Ui.Pw();
        var pick = Ui.Combo(presets.Select(p => p.Name));
        pick.SelectionChanged += (_, _) =>
        {
            var hit = presets.FirstOrDefault(p => p.Name == pick.Str());
            if (hit != null) api.Text = hit.Api;
        };
        var body = Ui.V(8, Ui.Muted("选择皮肤站，或直接填 Yggdrasil API 地址"), pick, api, user, pw);
        if (!await Dlg.Ask("皮肤站登录", body, "登录")) return;
        if (string.IsNullOrWhiteSpace(api.Text) || string.IsNullOrWhiteSpace(user.Text))
        {
            Toast("填写不完整", "API 地址和用户名都不能为空", ToastKind.Warning);
            return;
        }
        _authlibTask = await Api.StartTaskAsync("start_authlib_login", new
        {
            api = api.Text.Trim(),
            username = user.Text.Trim(),
            password = pw.Password ?? "",
        });
        Toast("正在登录", "皮肤站验证中，结果看下载任务", ToastKind.Info);
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "login_code" when _loginLayer != null:
                _loginUri = ev.Uri;
                if (_loginCode != null) _loginCode.Text = ev.Code;
                if (_loginHint != null) _loginHint.Text = "在浏览器打开下面的地址并输入代码：\n" + ev.Uri;
                break;
            case "login_status" when _loginHint != null:
                _loginHint.Text = ev.Text;
                break;
            case "finished" when ev.TaskId == _loginTask:
                _loginTask = null;
                if (ev.Success)
                {
                    _loginLayer?.Close();
                    _loginLayer = null;
                    Toast("登录成功", "微软账号已加入列表", ToastKind.Success);
                    Run(LoadAsync);
                }
                else if (_loginHint != null) _loginHint.Text = ev.Message;
                break;
            case "finished" when ev.TaskId == _authlibTask:
                _authlibTask = null;
                if (ev.Success)
                {
                    Toast("登录成功", "皮肤站账号已加入列表", ToastKind.Success);
                    Run(LoadAsync);
                }
                break;
        }
    }
}
