using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class FeedbackPage : PageBase
{
    public override string Title => "反馈与帮助";

    private static readonly string[] Categories = { "问题反馈", "功能建议", "崩溃报告", "其它" };

    private readonly ComboBox _cat = Ui.Combo(Categories);
    private readonly TextBox _title = Ui.Input("一句话说清问题");
    private readonly TextBox _body = Ui.Multi("详细描述：怎么触发的、期望是什么", height: 130);
    private readonly TextBox _contact = Ui.Input("联系方式（可空）");
    private readonly CheckBox _sys = Ui.Check("附带系统信息（显卡 / 内存 / Java）", true);
    private readonly SPanel _history = Ui.V(6);
    private readonly SPanel _articles = Ui.V(6);
    private readonly TextBox _search = Ui.Input("搜索帮助文章");

    public FeedbackPage()
    {
        var send = Ui.Btn("提交反馈", BtnKind.Primary, (_, _) => Run(SubmitAsync), Ico.Send);
        var sysBtn = Ui.Btn("查看系统信息", BtnKind.Chip, (_, _) => Run(SysInfoAsync), Ico.Info);

        var form = Ui.Card(Ui.V(10,
            Ui.Section("提交反馈", "会发到开发者的反馈服务，不含账号密码"),
            Ui.Field("类型", _cat, labelWidth: 74),
            Ui.Field("标题", _title, labelWidth: 74),
            _body,
            Ui.Field("联系方式", _contact, labelWidth: 74),
            _sys,
            Ui.H(8, send, sysBtn)), 16);

        var hist = Ui.Card(Ui.V(10, Ui.Section("我提交过的"), _history), 16);

        _search.TextChanged += (_, _) => Run(() => LoadArticlesAsync(_search.Text));
        var help = Ui.Card(Ui.V(10, Ui.Section("帮助中心", "常见问题速查"), _search, _articles), 16);

        var cols = Ui.G(null, "*,360");
        cols.Add(Ui.V(14, form, hist), 0, 0);
        cols.Add(help.M(14, 0, 0, 0).VTop(), 0, 1);
        Content = ScrollBody(Ui.Section("反馈与帮助", "遇到问题先看帮助，解决不了再提反馈"), cols);
    }

    protected override async Task LoadAsync()
    {
        await LoadHistoryAsync();
        await LoadArticlesAsync("");
    }

    private async Task LoadHistoryAsync()
    {
        var rows = await Api.TryCallAsync<List<FeedbackRow>>("feedback_history", null, new()) ?? new();
        _history.Children.Clear();
        if (rows.Count == 0)
        {
            _history.Children.Add(Ui.Muted("还没有提交记录"));
            return;
        }
        foreach (var r in rows.Take(20))
        {
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.V(2, Ui.Txt(r.Title, 12.5).Trim(), Ui.Small($"{r.Category} · {r.Time}")).VCenter(), 0, 0);
            g.Add(Ui.Tag(string.IsNullOrWhiteSpace(r.Status) ? "已提交" : r.Status).VCenter(), 0, 1);
            _history.Children.Add(g);
        }
    }

    private async Task LoadArticlesAsync(string query)
    {
        var rows = await Api.TryCallAsync<List<HelpArticle>>("help_articles", new { query = query ?? "" }, new()) ?? new();
        _articles.Children.Clear();
        if (rows.Count == 0)
        {
            _articles.Children.Add(Ui.Muted("没有匹配的文章"));
            return;
        }
        foreach (var a in rows.Take(30))
        {
            var id = a.Id;
            var btn = Ui.Btn(a.Title, BtnKind.Ghost, (_, _) => Run(() => OpenArticleAsync(id)));
            btn.HorizontalContentAlignment = HorizontalAlignment.Left;
            btn.Padding = new Thickness(8, 6, 8, 7);
            _articles.Children.Add(btn.Stretch());
        }
        Motion.Stagger(_articles, 14, 180, 6);
    }

    private async Task OpenArticleAsync(string id)
    {
        var a = await Api.TryCallAsync<HelpArticle>("help_article", new { article_id = id });
        if (a is null) return;
        await Dlg.Alert(a.Title, a.Body, 640);
    }

    private async Task SysInfoAsync()
    {
        using (Dlg.Busy("正在收集系统信息…"))
        {
            var info = await Api.TryCallAsync<object>("collect_sysinfo", new { force = true, scan_system_java = true });
            var text = await Api.TryCallAsync<string>("sysinfo_text", new { info }, "") ?? "";
            await Dlg.Alert("系统信息", text, 640);
        }
    }

    private async Task SubmitAsync()
    {
        if (string.IsNullOrWhiteSpace(_title.Text))
        {
            Toast("标题不能为空", "", ToastKind.Warning);
            Motion.Shake(_title);
            return;
        }
        using (Dlg.Busy("正在提交…"))
        {
            var r = await Api.TryCallAsync<OpResult>("submit_feedback", new
            {
                category = _cat.Str(),
                title = _title.Text.Trim(),
                body = _body.Text ?? "",
                contact = _contact.Text?.Trim() ?? "",
                include_sysinfo = _sys.IsChecked == true,
            });
            Toast(r?.Ok == true ? "已提交" : "提交失败", r?.Message ?? "", r?.Ok == true ? ToastKind.Success : ToastKind.Error);
            if (r?.Ok == true)
            {
                _title.Clear();
                _body.Clear();
                await LoadHistoryAsync();
            }
        }
    }
}
