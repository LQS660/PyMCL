using System.IO;
using System.Windows;
using System.Windows.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class FeedbackPage : PageBase
{
    public override string Title => L("反馈与帮助");

    private static readonly string[] Categories = { L("问题反馈"), L("功能建议"), L("崩溃报告"), L("其它") };

    private readonly ComboBox _cat = Ui.Combo(Categories);
    private readonly TextBox _title = Ui.Input(L("一句话说清问题"));
    private readonly TextBox _body = Ui.Multi(L("详细描述：怎么触发的、期望是什么"), height: 130);
    private readonly TextBox _contact = Ui.Input(L("联系方式（可空）"));
    private readonly CheckBox _sys = Ui.Check(L("附带系统信息（显卡 / 内存 / Java）"), true);
    private readonly SPanel _history = Ui.V(6);
    private readonly SPanel _articles = Ui.V(6);
    private readonly SPanel _attachList = Ui.V(4);
    private readonly TextBox _search = Ui.Input(L("搜索帮助文章"));
    private readonly List<string> _attachments = new();

    public FeedbackPage()
    {
        var send = Ui.Btn(L("提交反馈"), BtnKind.Primary, (_, _) => Run(SubmitAsync), Ico.Send);
        var sysBtn = Ui.Btn(L("查看系统信息"), BtnKind.Chip, (_, _) => Run(SysInfoAsync), Ico.Info);
        var attachBtn = Ui.Btn(L("添加附件"), BtnKind.Chip, (_, _) => Run(AttachAsync, L("附件没能上传")), Ico.Import);

        var form = Ui.Card(Ui.V(10,
            Ui.Section(L("提交反馈"), L("会发到开发者的反馈服务，不含账号密码")),
            Ui.Field(L("类型"), _cat, labelWidth: 74),
            Ui.Field(L("标题"), _title, labelWidth: 74),
            _body,
            Ui.Field(L("联系方式"), _contact, labelWidth: 74),
            _sys,
            _attachList,
            Ui.H(8, send, attachBtn, sysBtn)), 16);

        var hist = Ui.Card(Ui.V(10, Ui.Section(L("我提交过的")), _history), 16);

        _search.TextChanged += (_, _) => Run(() => LoadArticlesAsync(_search.Text));
        // 对齐 Qt feedback_page 的「常见问题」卡：同一句说明；文章走桥上 help_articles / help_article
        var help = Ui.Card(Ui.V(10, Ui.Section(L("常见问题"), L("启动、Java、模组、账号、联机的快速说明（点击标题展开）")), _search, _articles), 16);

        var cols = Ui.G(null, "*,360");
        cols.Add(Ui.V(14, form, hist), 0, 0);
        cols.Add(help.M(14, 0, 0, 0).VTop(), 0, 1);
        Content = ScrollBody(Ui.Section(L("反馈与帮助"), L("遇到问题先看帮助，解决不了再提反馈")), cols);
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
            _history.Children.Add(Ui.Muted(L("还没有提交记录")));
            return;
        }
        foreach (var r in rows.Take(20))
        {
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.V(2, Ui.Txt(r.Title, 12.5).Trim(), Ui.Small($"{r.Category} · {r.Time}")).VCenter(), 0, 0);
            g.Add(Ui.Tag(string.IsNullOrWhiteSpace(r.Status) ? L("已提交") : r.Status).VCenter(), 0, 1);
            _history.Children.Add(g);
        }
    }

    private async Task LoadArticlesAsync(string query)
    {
        var rows = await Api.TryCallAsync<List<HelpArticle>>("help_articles", new { query = query ?? "" }, new()) ?? new();
        _articles.Children.Clear();
        if (rows.Count == 0)
        {
            _articles.Children.Add(Ui.Muted(L("没有匹配的文章")));
            return;
        }
        foreach (var a in rows.Take(30))
        {
            var article = a;
            var body = Ui.Muted("").Wrap().M(8, 0, 8, 4);
            body.Visibility = Visibility.Collapsed;
            var btn = Ui.Btn(a.Title, BtnKind.Ghost, (_, _) => Run(() => ToggleArticleAsync(article, body)));
            btn.HorizontalContentAlignment = HorizontalAlignment.Left;
            btn.Padding = new Thickness(8, 6, 8, 7);
            _articles.Children.Add(Ui.V(2, btn.Stretch(), body));
        }
        Motion.Stagger(_articles, 14, 180, 6);
    }

    /// <summary>
    /// 点标题原地展开 / 收起正文（Qt 是弹 MessageBox；这里少一次跳转，搜索结果还留在眼前）。
    /// help_articles 一般已把正文带回来；没带（以后瘦身成只给标题也行）就照 Qt _show_help 再按 id 问一次 help_article。
    /// </summary>
    private async Task ToggleArticleAsync(HelpArticle a, TextBlock body)
    {
        if (body.Visibility == Visibility.Visible)
        {
            body.Visibility = Visibility.Collapsed;
            return;
        }
        if (string.IsNullOrEmpty(a.Body))
        {
            var full = await Api.TryCallAsync<HelpArticle>("help_article", new { article_id = a.Id });
            if (full is not null) a.Body = full.Body;
        }
        body.Text = string.IsNullOrEmpty(a.Body) ? L("暂无内容") : a.Body;
        body.Visibility = Visibility.Visible;
    }

    private async Task SysInfoAsync()
    {
        using (Dlg.Busy(L("正在收集系统信息…")))
        {
            var info = await Api.TryCallAsync<object>("collect_sysinfo", new { force = true, scan_system_java = true });
            var text = await Api.TryCallAsync<string>("sysinfo_text", new { info }, "") ?? "";
            await Dlg.Alert(L("系统信息"), text, 640);
        }
    }

    /// <summary>
    /// 把截图 / 日志交给 stash_upload 落进 ROOT/uploads，拿回一条后端自己认得的真实路径，
    /// 再把路径附进正文——反馈服务事后要取文件，靠用户桌面上那个随时会被删的路径是靠不住的。
    /// 读文件和 base64 都在线程池上做，几 MB 的日志不至于卡住界面。
    /// </summary>
    private async Task AttachAsync()
    {
        var files = Dlg.PickFiles(L("截图 / 日志 (*.png;*.jpg;*.log;*.txt)|*.png;*.jpg;*.log;*.txt|全部文件|*.*"), L("添加附件"));
        if (files is null || files.Length == 0) return;
        using (Dlg.Busy(L("正在上传附件…")))
            foreach (var f in files)
            {
                var name = Path.GetFileName(f);
                string data;
                try { data = await Task.Run(() => Convert.ToBase64String(File.ReadAllBytes(f))); }
                catch (Exception ex)
                {
                    Toast(L("读不了这个文件"), L("{0}：{1}", name, ex.Message), ToastKind.Warning);
                    continue;
                }
                if (data.Length == 0)
                {
                    Toast(L("跳过空文件"), name, ToastKind.Warning);
                    continue;
                }
                var stashed = await Api.CallAsync<string>("stash_upload", new { name, data });
                if (string.IsNullOrEmpty(stashed)) continue;
                _attachments.Add(stashed);
            }
        RenderAttachments();
    }

    private void RenderAttachments()
    {
        _attachList.Children.Clear();
        if (_attachments.Count == 0) return;
        _attachList.Children.Add(Ui.Small(L("已附 {0} 个文件", _attachments.Count)));
        foreach (var p in _attachments)
        {
            var path = p;
            var g = Ui.G(null, "*,Auto");
            g.Add(Ui.Small(Path.GetFileName(path)).Trim().VCenter(), 0, 0);
            g.Add(Ui.Btn(L("移除"), BtnKind.Ghost, (_, _) =>
            {
                _attachments.Remove(path);
                RenderAttachments();
            }).VCenter(), 0, 1);
            _attachList.Children.Add(g);
        }
    }

    private async Task SubmitAsync()
    {
        if (string.IsNullOrWhiteSpace(_title.Text))
        {
            Toast(L("标题不能为空"), "", ToastKind.Warning);
            Motion.Shake(_title);
            return;
        }
        var body = _body.Text ?? "";
        if (_attachments.Count > 0)
            body = body.TrimEnd() + L("\n\n附件：\n") + string.Join("\n", _attachments);
        using (Dlg.Busy(L("正在提交…")))
        {
            var r = await Api.TryCallAsync<OpResult>("submit_feedback", new
            {
                category = _cat.Str(),
                title = _title.Text.Trim(),
                body,
                contact = _contact.Text?.Trim() ?? "",
                include_sysinfo = _sys.IsChecked == true,
            });
            Toast(r?.Ok == true ? L("已提交") : L("提交失败"), r?.Message ?? "", r?.Ok == true ? ToastKind.Success : ToastKind.Error);
            if (r?.Ok == true)
            {
                _title.Clear();
                _body.Clear();
                _attachments.Clear();
                RenderAttachments();
                await LoadHistoryAsync();
            }
        }
    }
}
