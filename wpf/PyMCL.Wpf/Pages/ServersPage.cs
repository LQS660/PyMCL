using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class ServersPage : PageBase
{
    public override string Title => L("服务器");

    private readonly ComboBox _inst = Ui.Combo();
    private readonly SPanel _list = Ui.V(9);
    private readonly TextBlock _count = Ui.Muted("");
    private readonly TextBlock _lan = Ui.Small("");

    public ServersPage()
    {
        var add = Ui.Btn(L("添加服务器"), BtnKind.Primary, (_, _) => Run(() => EditAsync(null, -1)), Ico.Add);
        var imp = Ui.Btn(L("导入"), BtnKind.Chip, (_, _) => Run(ImportAsync), Ico.Import);
        var exp = Ui.Btn(L("导出"), BtnKind.Chip, (_, _) => Run(ExportAsync), Ico.Export);
        var head = Ui.Section(L("服务器"), L("直接写进实例的 servers.dat，进游戏就能看到"),
            Ui.H(8, _count.VCenter(), imp, exp, add));
        _inst.SelectionChanged += (_, _) => Run(ReloadAsync);
        var bar = Ui.Card(Ui.H(10,
            Ui.Txt(L("实例"), 12, fg: "B.InkMuted").VCenter(), _inst.W(200), _lan.VCenter()), 12);
        Content = ScrollBody(head, bar, _list);
    }

    protected override async Task LoadAsync()
    {
        var insts = await Api.TryCallAsync<List<InstanceInfo>>("get_instances", null, new()) ?? new();
        _inst.Fill(insts.Select(i => i.Name));
        _lan.Text = await Api.TryCallAsync<string>("lan_hint", new { port = 25565 }, "") ?? "";
        await ReloadAsync();
    }

    private async Task ReloadAsync()
    {
        var inst = _inst.Str();
        if (string.IsNullOrEmpty(inst)) return;
        var rows = await Api.TryCallAsync<List<ServerRow>>("list_servers", new { instance = inst }, new()) ?? new();
        _list.Children.Clear();
        _count.Text = L("{0} 个", rows.Count);
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Server, L("还没有服务器"), L("点右上角添加，或从 servers.txt 导入")));
            return;
        }
        for (var i = 0; i < rows.Count; i++)
        {
            var idx = i;
            var r = rows[i];
            var g = Ui.G(null, "Auto,*,Auto");
            g.Add(Ui.Glyph(Ico.Server, 16, "B.Accent").M(0, 0, 12, 0).VCenter(), 0, 0);
            g.Add(Ui.V(3,
                Ui.Txt(string.IsNullOrWhiteSpace(r.Name) ? r.Ip : r.Name, 13.5, true).Trim(),
                Ui.Small($"{r.Ip}:{r.Port}" + (string.IsNullOrWhiteSpace(r.Description) ? "" : "  ·  " + r.Description))).VCenter(), 0, 1);
            g.Add(Ui.H(6,
                Ui.Btn(L("进入"), BtnKind.Soft, (_, _) => Run(() => JoinAsync(r)), Ico.Play),
                Ui.Btn(L("编辑"), BtnKind.Chip, (_, _) => Run(() => EditAsync(r, idx))),
                Ui.Btn(L("删除"), BtnKind.Ghost, (_, _) => Run(async () =>
                {
                    if (!await Dlg.Confirm(L("删除服务器"), r.Name, L("删除"), L("取消"), true)) return;
                    await Api.CallAsync("delete_server", new { instance = inst, index = idx });
                    await ReloadAsync();
                }))).VCenter(), 0, 2);
            var card = Ui.Card(g, 13);
            Motion.HoverLift(card, 1.005, 1, 16);
            _list.Children.Add(card);
        }
        Motion.Stagger(_list, 24);
    }

    private async Task JoinAsync(ServerRow row)
    {
        var inst = _inst.Str();
        var versions = await Api.TryCallAsync<List<string>>("get_installed_versions", new { instance = inst }, new()) ?? new();
        if (versions.Count == 0)
        {
            Toast(L("这个实例没有版本"), L("先去下载页装一个"), ToastKind.Warning);
            return;
        }
        var pick = Ui.Combo(versions);
        if (!await Dlg.Ask(L("进入 {0}", row.Name), Ui.V(8, Ui.Muted($"{row.Ip}:{row.Port}"), pick), L("启动并直连"))) return;
        var accounts = await Api.TryCallAsync<List<string>>("get_accounts", null, new()) ?? new();
        await Api.StartTaskAsync("launch_game", new
        {
            instance = inst,
            version = pick.Str(),
            account = accounts.FirstOrDefault() ?? L("离线模式"),
            username = Win?.Prefs.LastUser is { Length: > 0 } u ? u : "Player",
            memory_mb = 4096,
            width = 854,
            height = 480,
            java = "自动选择", // i18n:ignore 桥的协议值（原文比对），不是界面词
            extra_game_args = new[] { "--server", row.Ip, "--port", row.Port.ToString() },
        });
        Win?.Navigate("launch");
    }

    private async Task EditAsync(ServerRow? row, int index)
    {
        var inst = _inst.Str();
        var name = Ui.Input(L("显示名"), row?.Name ?? "");
        var ip = Ui.Input("mc.example.com", row?.Ip ?? "");
        var port = Ui.Input("25565", (row?.Port ?? 25565).ToString());
        var desc = Ui.Input(L("备注（可空）"), row?.Description ?? "");
        var body = Ui.V(8, name, ip, port, desc);
        if (!await Dlg.Ask(row is null ? L("添加服务器") : L("编辑服务器"), body, L("保存"))) return;
        var p = int.TryParse(port.Text?.Trim(), out var n) ? n : 25565;
        if (row is null)
            await Api.CallAsync("add_server", new
            {
                instance = inst, name = name.Text?.Trim() ?? "", ip = ip.Text?.Trim() ?? "",
                port = p, description = desc.Text?.Trim() ?? "",
            });
        else
            await Api.CallAsync("update_server", new
            {
                instance = inst, index, name = name.Text?.Trim() ?? "", ip = ip.Text?.Trim() ?? "",
                port = p, description = desc.Text?.Trim() ?? "",
            });
        await ReloadAsync();
    }

    private async Task ImportAsync()
    {
        var file = Dlg.PickFile(L("服务器列表 (*.txt)|*.txt|全部文件|*.*"), L("导入服务器"));
        if (file is null) return;
        var text = await System.IO.File.ReadAllTextAsync(file);
        var n = await Api.CallAsync<int>("import_servers", new { instance = _inst.Str(), text });
        Toast(L("已导入"), L("{0} 个服务器", n), ToastKind.Success);
        await ReloadAsync();
    }

    private async Task ExportAsync()
    {
        var text = await Api.CallAsync<string>("export_servers", new { instance = _inst.Str() }) ?? "";
        var dest = Dlg.SaveFile(L("服务器列表 (*.txt)|*.txt"), "servers.txt", L("导出服务器"));
        if (dest is null) return;
        await System.IO.File.WriteAllTextAsync(dest, text);
        Toast(L("已导出"), dest, ToastKind.Success);
    }

    public override async Task RefreshAsync() => await ReloadAsync();
}
