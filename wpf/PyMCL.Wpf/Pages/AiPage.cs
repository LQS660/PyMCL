using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// AI 助手。对话流里除了气泡，还内联工具行 / 任务进度 / 确认卡 / 提问卡——
/// 与 Qt 端 app/pages/ai_page.py 一致：AI 自己起的下载不该逼用户跳到任务页，
/// 连着问几轮也不该连弹几个模态框。
/// </summary>
public sealed class AiPage : PageBase
{
    public override string Title => L("AI 助手");

    private readonly SPanel _chatList = Ui.V(4);
    private readonly SPanel _messages = Ui.V(12);
    private readonly SmoothScroll _scroll;
    private readonly ChatInput _input = new();
    private readonly Button _send, _stop, _retry;
    private readonly TextBlock _status = Ui.Small("");
    private readonly StringBuilder _stream = new();
    private readonly Dictionary<string, ToolLine> _toolLines = new();
    private readonly Dictionary<string, ToolLine> _taskLines = new();
    private Bubble? _streamBubble;
    private AiStoreDto _store = new();
    private bool _busy;

    public AiPage()
    {
        _send = Ui.Btn(L("发送"), BtnKind.Primary, (_, _) => Run(SendAsync), Ico.Send);
        _stop = Ui.Btn(L("停止"), BtnKind.Danger, (_, _) => Run(StopAsync), Ico.Stop);
        _retry = Ui.Btn(L("重试"), BtnKind.Chip, (_, _) => Run(RetryAsync), Ico.Refresh);
        _stop.IsEnabled = false;
        _retry.IsEnabled = false;

        _scroll = Ui.Scroll(_messages.M(4, 4, 10, 4));
        _input.Submitted += text => Run(() => SendTextAsync(text));

        var newChat = Ui.Btn(L("新对话"), BtnKind.Soft, (_, _) => Run(NewChatAsync), Ico.Add);
        var side = Ui.V(10, newChat.Stretch(), Ui.Sep(), Ui.Scroll(_chatList));
        var sideCard = Ui.Card(side, 12);
        sideCard.Width = 208;

        var quick = new WrapPanel();
        foreach (var (text, prompt) in new[]
                 {
                     (L("下个最新版"), L("帮我下载最新正式版 Minecraft")),
                     (L("装 Fabric + 钠"), L("给我装 1.20.1 Fabric，再装钠和 Iris 光影")),
                     (L("崩溃分析"), L("刚才启动失败了，读一下日志告诉我原因")),
                     (L("扫模组冲突"), L("扫一下当前实例的模组冲突")),
                 })
        {
            var p = prompt;
            var b = Ui.Btn(text, BtnKind.Chip, (_, _) => Run(() => SendTextAsync(p)));
            b.Margin = new Thickness(0, 0, 6, 6);
            quick.Children.Add(b);
        }

        var inputCard = Ui.Card(Ui.V(8,
            quick,
            _input,
            Ui.G(null, "*,Auto")
                .Add(_status.VCenter(), 0, 0)
                .Add(Ui.H(8, _retry, _stop, _send), 0, 1)), 14);

        var main = Ui.G("*,Auto");
        main.Add(Ui.Card(_scroll, 10), 0, 0);
        main.Add(inputCard.M(0, 12, 0, 0), 1, 0);

        var cols = Ui.G(null, "Auto,*");
        cols.Add(sideCard.M(0, 0, 12, 0), 0, 0);
        cols.Add(main, 0, 1);

        var root = Ui.G("Auto,*");
        root.Add(Ui.Section(L("AI 助手"), L("对话里下游戏、装模组、读崩溃日志；写操作会先问你")).M(0, 0, 0, 12), 0, 0);
        root.Add(cols, 1, 0);
        root.Margin = new Thickness(26, 20, 26, 20);
        Content = root;
    }

    protected override async Task LoadAsync()
    {
        _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, new()) ?? new();
        RenderChats();
        RenderMessages();
    }

    private void RenderChats()
    {
        _chatList.Children.Clear();
        foreach (var c in _store.Chats)
        {
            var id = c.Id;
            var active = id == _store.ActiveId;
            var title = string.IsNullOrWhiteSpace(c.Title) ? L("新对话") : c.Title;
            var btn = Ui.Btn(title, active ? BtnKind.Soft : BtnKind.Ghost, (_, _) => Run(async () =>
            {
                _store = await Api.TryCallAsync<AiStoreDto>("ai_set_active", new { chat_id = id }, _store) ?? _store;
                RenderChats();
                RenderMessages();
            }));
            btn.HorizontalContentAlignment = HorizontalAlignment.Left;
            btn.Padding = new Thickness(9, 6, 9, 7);
            btn.ContextMenu = DelMenu(id);
            _chatList.Children.Add(btn.Stretch());
        }
        if (_store.Chats.Count == 0) _chatList.Children.Add(Ui.Muted(L("还没有对话")));
    }

    private ContextMenu DelMenu(string id)
    {
        var m = new ContextMenu();
        var del = new MenuItem { Header = L("删除这个对话") };
        del.Click += (_, _) => Run(async () =>
        {
            _store = await Api.TryCallAsync<AiStoreDto>("ai_delete_chat", new { chat_id = id }, _store) ?? _store;
            RenderChats();
            RenderMessages();
        });
        m.Items.Add(del);
        return m;
    }

    private async Task NewChatAsync()
    {
        _store = await Api.TryCallAsync<AiStoreDto>("ai_new_chat", null, _store) ?? _store;
        RenderChats();
        RenderMessages();
    }

    private AiChatDto? ActiveChat =>
        _store.Chats.FirstOrDefault(c => c.Id == _store.ActiveId) ?? _store.Chats.FirstOrDefault();

    private void RenderMessages()
    {
        _messages.Children.Clear();
        _toolLines.Clear();
        _taskLines.Clear();
        _streamBubble = null;
        _stream.Clear();
        var chat = ActiveChat;
        if (chat is null || chat.Messages.Count == 0)
        {
            _messages.Children.Add(Ui.Empty(Ico.Robot, L("问点什么吧"),
                L("「下一款 1.20.1 Fabric」「装钠和光影」「启动闪退了帮我看看」——写操作前会先弹确认。")));
            _retry.IsEnabled = false;
            return;
        }
        foreach (var m in chat.Messages)
        {
            if (m.Role is not ("user" or "assistant" or "error")) continue;
            _messages.Children.Add(new Bubble(m.Role, m.Content, RetryFrom));
        }
        Motion.Stagger(_messages, 18, 200, 8);
        _retry.IsEnabled = !_busy && LastUserText().Length > 0;
        ScrollDown();
    }

    private void ScrollDown() => Dispatcher.BeginInvoke(() => _scroll.ScrollToEnd());

    private void Add(UIElement el)
    {
        if (_messages.Children.Count == 1 && _messages.Children[0] is SPanel) _messages.Children.Clear();
        _messages.Children.Add(el);
        Motion.FadeIn(el, 200, 8);
        ScrollDown();
    }

    private string LastUserText() =>
        ActiveChat?.Messages.LastOrDefault(m => m.Role == "user" && !string.IsNullOrWhiteSpace(m.Content))?.Content ?? "";

    // ==================== 发送 ====================
    private Task SendAsync() => SendTextAsync(_input.Text);

    private void RetryFrom(string text) => Run(() => SendTextAsync(text));

    /// <summary>「重试」= 把最后一条用户消息原样再发一遍，与 Qt `_retry` 同义。</summary>
    private Task RetryAsync()
    {
        var last = LastUserText();
        return last.Length == 0 ? Task.CompletedTask : SendTextAsync(last);
    }

    private async Task SendTextAsync(string raw)
    {
        var text = (raw ?? "").Trim();
        if (text.Length == 0 || _busy) return;
        _input.Clear();
        SetBusy(true);
        _status.Text = L("思考中…");

        Add(new Bubble("user", text, RetryFrom));
        _stream.Clear();
        _streamBubble = new Bubble("assistant", "…", RetryFrom);
        Add(_streamBubble);

        var launch = new Dictionary<string, object?>
        {
            ["instance"] = Win?.Prefs.CatalogInstance ?? "",
            ["username"] = Win?.Prefs.LastUser ?? "",
        };
        var r = await Api.TryCallAsync<OpResult>("ai_send", new { text, chat_id = _store.ActiveId, launch });
        if (r is { Ok: false })
        {
            _status.Text = r.Message;
            Add(new Bubble("error", r.Message, RetryFrom));
            SetBusy(false);
        }
    }

    private async Task StopAsync()
    {
        await Api.TryCallAsync<object>("ai_stop");
        _status.Text = L("已停止");
    }

    private void SetBusy(bool on)
    {
        _busy = on;
        _send.IsEnabled = !on;
        _stop.IsEnabled = on;
        _retry.IsEnabled = !on && LastUserText().Length > 0;
    }

    // ==================== 工具行 ====================
    private ToolLine Line(string name, string text)
    {
        if (_toolLines.TryGetValue(name, out var line))
        {
            line.SetText(text);
            return line;
        }
        line = new ToolLine(text);
        _toolLines[name] = line;
        Add(line);
        return line;
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "ai.delta":
                if (_streamBubble is null) return;
                _stream.Append(ev.Text);
                _streamBubble.SetText(_stream.ToString());
                ScrollDown();
                break;

            case "ai.status":
                OnStatus(ev);
                break;

            case "ai.done":
            {
                _status.Text = "";
                NotifyStop(ev);
                // 流式气泡先就地补上「为什么停」；随后重拉的会话里已带同一条提示
                // （bridge 端照 Qt 入了库），重建后不丢。
                var note = StopNote(ev);
                if (note.Length > 0 && _streamBubble != null)
                    _streamBubble.SetText(_stream.ToString() + note);
                SetBusy(false);
                Run(async () =>
                {
                    _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, _store) ?? _store;
                    RenderChats();
                    RenderMessages();
                });
                break;
            }

            case "ai.fail":
                // 主动停止不算错：用户点「停止」不该看到红色 error 气泡（对齐 winui3/eziapp/Qt）
                _status.Text = ev.Stopped ? "" : ev.Text;
                if (ev.Stopped)
                {
                    if (_streamBubble != null && _stream.Length == 0) _streamBubble.SetText(L("已停止"));
                    Toast(L("已停止"), L("可以继续说下一句"));
                }
                else
                {
                    if (_streamBubble != null && _stream.Length == 0) _streamBubble.SetText(ev.Text);
                    else Add(new Bubble("error", ev.Text, RetryFrom));
                }
                SetBusy(false);
                break;

            case "ai.confirm":
                ShowConfirm(ev);
                break;

            case "ai.ask":
                ShowAsk(ev);
                break;

            // AI 起的下载：进度直接画在对话流那一行上，不用跳任务页
            case "progress" when _taskLines.TryGetValue(ev.TaskId, out var pl):
                pl.SetProgress(ev.Current, ev.Total, ev.Message);
                break;
            case "finished" when _taskLines.TryGetValue(ev.TaskId, out var fl):
                fl.Finish(ev.Success, ev.Message);
                break;
        }
    }

    // ==================== 停止原因（对齐 Qt 批次 0） ====================
    /// <summary>stop_reason 只从 payload 里掏——BridgeEvent.Payload 本来就是整包原始 JSON，别给它加属性。</summary>
    private static string StopReasonOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("stop_reason", out var r) && r.ValueKind == JsonValueKind.String
            ? r.GetString() ?? "" : "";

    private static string DetailOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String
            ? d.GetString() ?? "" : "";

    /// <summary>
    /// 与 Qt `_stop_note` 同一张词表：completed / truncated 等不打扰，
    /// 其余拼成「（提示：…）」挂在气泡末尾。
    /// </summary>
    private static string StopNote(BridgeEvent ev)
    {
        var note = StopReasonOf(ev) switch
        {
            "no_tool_call" => L("它没有真的开始执行：模型只回了文字，没有调用任何工具。"),
            "max_rounds" => L("步骤太多，先停在这里。你可以让我继续。"),
            "pending_task" => L("下载/安装还在后台跑，可以在「下载任务」里看进度。"),
            "stream_failed" => L("接口这轮没有返回内容，已停止。"),
            "empty_response" => L("接口返回了空回复。"),
            _ => "",
        };
        if (note.Length == 0) return "";
        var detail = DetailOf(ev);
        if (detail.Length > 0 && !note.Contains(detail)) note += L("（") + detail + L("）");
        return L("（提示：") + note + L("）");
    }

    /// <summary>两类原因值得弹一下：没动手（催它重试）与后台还在跑（别干等）。</summary>
    private void NotifyStop(BridgeEvent ev)
    {
        switch (StopReasonOf(ev))
        {
            case "no_tool_call":
                Toast(L("它没有真的开始执行"), L("模型只回了文字，没有调用任何工具。"), ToastKind.Warning);
                break;
            case "pending_task":
                Toast(L("任务还在后台跑"), L("可以在「下载任务」里查进度。"));
                break;
        }
    }

    private void OnStatus(BridgeEvent ev)
    {
        var name = string.IsNullOrEmpty(ev.Name) ? ev.Kind : ev.Name;
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        switch (ev.Kind)
        {
            case "thinking":
            case "think":
                _status.Text = L("思考中…");
                if (_stream.Length == 0) _streamBubble?.SetText(L("正在想…"));
                return;
            case "tool":
                if (ev.Name == "ask_user")
                {
                    if (_stream.Length == 0) _streamBubble?.SetText(L("请在下面选一下"));
                    return;
                }
                Line(name, L("准备：") + label);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_start":
            case "tool_run":
                Line(name, L("执行中：") + label);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_done":
            {
                var line = Line(name, L("完成：") + label);
                var tid = TaskIdOf(ev);
                if (tid.Length > 0)
                {
                    line.BindTask();
                    _taskLines[tid] = line;
                }
                _status.Text = L("操作完成");
                return;
            }
            case "tool_skip":
                Line(name, L("已跳过：") + label);
                return;
            default:
                if (!string.IsNullOrWhiteSpace(ev.Label)) _status.Text = ev.Label;
                return;
        }
    }

    /// <summary>task_id 可能直接在事件上，也可能裹在工具返回的 JSON 结果里。</summary>
    private static string TaskIdOf(BridgeEvent ev)
    {
        if (!string.IsNullOrEmpty(ev.TaskId)) return ev.TaskId;
        if (ev.Payload.ValueKind != JsonValueKind.Object) return "";
        if (ev.Payload.TryGetProperty("task_id", out var t) && t.ValueKind == JsonValueKind.String)
            return t.GetString() ?? "";
        if (!ev.Payload.TryGetProperty("result", out var r) || r.ValueKind != JsonValueKind.String) return "";
        var raw = r.GetString() ?? "";
        if (!raw.StartsWith("{", StringComparison.Ordinal)) return "";
        try
        {
            using var doc = JsonDocument.Parse(raw);
            return doc.RootElement.TryGetProperty("task_id", out var inner) && inner.ValueKind == JsonValueKind.String
                ? inner.GetString() ?? "" : "";
        }
        catch { return ""; }
    }

    // ==================== 内联确认卡 ====================
    private void ShowConfirm(BridgeEvent ev)
    {
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        // 判权给的「为什么要问」（如「规则要求先询问」）对人友好，优先于裸 args JSON
        var reason = ev.Payload.ValueKind == JsonValueKind.Object
                     && ev.Payload.TryGetProperty("reason", out var rr)
                     && rr.ValueKind == JsonValueKind.String
            ? rr.GetString() ?? "" : "";
        var args = "";
        if (ev.Payload.ValueKind == JsonValueKind.Object && ev.Payload.TryGetProperty("args", out var a))
            args = a.ToString();
        var card = new ConfirmCard(label,
            string.IsNullOrWhiteSpace(reason) ? args : reason,
            ok =>
            Run(async () => await Api.TryCallAsync<object>("ai_confirm", new { ok })));
        Add(card);
        _status.Text = L("等你确认");
    }

    // ==================== 内联提问卡 ====================
    private void ShowAsk(BridgeEvent ev)
    {
        if (ev.Payload.ValueKind != JsonValueKind.Object ||
            !ev.Payload.TryGetProperty("questions", out var qs) || qs.ValueKind != JsonValueKind.Array)
        {
            Run(async () => await Api.TryCallAsync<object>("ai_answer", new { result = (object?)null }));
            return;
        }
        var title = ev.Payload.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";
        var card = new AskCard(title, qs, result =>
            Run(async () => await Api.TryCallAsync<object>("ai_answer", new { result })));
        Add(card);
        _status.Text = L("等你回答");
    }

    public override void OnShown() => _input.Focus();
}

// ======================================================================
/// <summary>一条消息。助手 / 出错的消息带「复制」，用户的消息带「重发」。</summary>
internal sealed class Bubble : Border
{
    private readonly TextBox _body;
    private string _plain;

    public Bubble(string role, string text, Action<string> resend)
    {
        _plain = text ?? "";
        var mine = role == "user";
        var err = role == "error";

        _body = new TextBox
        {
            Text = _plain,
            IsReadOnly = true,
            BorderThickness = new Thickness(0),
            Background = Brushes.Transparent,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13,
            Padding = new Thickness(0),
        };
        _body.SetResourceReference(Control.ForegroundProperty, mine ? "B.OnAccent" : "B.Ink");

        var who = Ui.Small(mine ? L("我") : err ? L("出错") : L("助手"));
        if (mine) who.SetResourceReference(TextBlock.ForegroundProperty, "B.OnAccent");
        var head = Ui.G(null, "*,Auto");
        head.Add(who.VCenter(), 0, 0);

        var tools = Ui.H(4);
        // 复制：助手那段答案经常要贴进 issue 或搜索框
        if (!mine) tools.Children.Add(Ui.IconBtn(Ico.Copy, L("复制这条"), (_, _) => Copy(), 12));
        // 重发：用户那条改一改再问一遍是常态
        if (mine) tools.Children.Add(Ui.IconBtn(Ico.Refresh, L("重新发这条"), (_, _) => resend(_plain), 12));
        head.Add(tools.VCenter(), 0, 1);

        CornerRadius = new CornerRadius(12, 12, mine ? 4 : 12, mine ? 12 : 4);
        Padding = new Thickness(13, 8, 13, 11);
        MaxWidth = 760;
        HorizontalAlignment = mine ? HorizontalAlignment.Right : HorizontalAlignment.Left;
        Child = Ui.V(4, head, _body);
        SetResourceReference(BackgroundProperty, mine ? "B.Accent" : err ? "B.DangerSoft" : "B.Paper2");
        if (err)
        {
            BorderThickness = new Thickness(1);
            SetResourceReference(BorderBrushProperty, "B.Danger");
        }
    }

    public void SetText(string text)
    {
        _plain = text ?? "";
        _body.Text = _plain;
    }

    private void Copy()
    {
        try
        {
            Clipboard.SetText(_plain);
            AppServices.Toast(L("已复制"), "", ToastKind.Success);
        }
        catch { }
    }
}

/// <summary>对话流里的一行工具执行状态；绑上任务后带进度条。</summary>
internal sealed class ToolLine : Border
{
    private readonly TextBlock _label;
    private readonly ProgressBar _bar;

    public ToolLine(string text)
    {
        _label = Ui.Small(text).Wrap();
        _label.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        _bar = Ui.Prog();
        _bar.Height = 4;
        _bar.Visibility = Visibility.Collapsed;
        CornerRadius = new CornerRadius(8);
        Padding = new Thickness(10, 6, 10, 7);
        HorizontalAlignment = HorizontalAlignment.Left;
        MaxWidth = 760;
        SetResourceReference(BackgroundProperty, "B.AccentSoft");
        Child = Ui.V(4, _label, _bar);
    }

    public void SetText(string text) => _label.Text = text;

    /// <summary>这一行背后挂了一条后台任务：亮出进度条。</summary>
    public void BindTask()
    {
        _bar.Visibility = Visibility.Visible;
        _bar.IsIndeterminate = true;
    }

    public void SetProgress(int current, int total, string? message)
    {
        _bar.Visibility = Visibility.Visible;
        _bar.IsIndeterminate = total <= 0;
        if (total > 0) Motion.Progress(_bar, Math.Clamp(current * 100.0 / total, 0, 100));
        Fmt.SplitMsg(message, out var status, out _);
        if (!string.IsNullOrEmpty(status)) _label.Text = status;
    }

    public void Finish(bool success, string? message)
    {
        _bar.IsIndeterminate = false;
        if (success) Motion.Progress(_bar, 100);
        _label.Text = (success ? L("完成：") : L("失败：")) + (message ?? "");
        _label.SetResourceReference(TextBlock.ForegroundProperty, success ? "B.AccentDeep" : "B.Danger");
    }
}

/// <summary>内联确认卡，替掉原来的模态框：连着问几轮也只是往下长几张卡。</summary>
internal sealed class ConfirmCard : Border
{
    public ConfirmCard(string label, string detail, Action<bool> answer)
    {
        var body = Ui.V(8,
            Ui.Txt(L("需要你点一下确认："), 12.5, true),
            Ui.Txt(label, 13).Wrap());
        if (!string.IsNullOrWhiteSpace(detail))
        {
            var box = new TextBox
            {
                Style = Ui.S("Input.Log"),
                Text = detail,
                MaxHeight = 160,
                TextWrapping = TextWrapping.Wrap,
            };
            body.Children.Add(box);
        }
        var yes = Ui.Btn(L("确认执行"), BtnKind.Primary, null, Ico.Check);
        var no = Ui.Btn(L("取消"));
        body.Children.Add(Ui.H(8, yes, no));

        void Done(bool ok)
        {
            yes.IsEnabled = no.IsEnabled = false;
            body.Children.Add(Ui.Small(ok ? L("已确认") : L("已取消")));
            answer(ok);
        }
        yes.Click += (_, _) => Done(true);
        no.Click += (_, _) => Done(false);

        CornerRadius = new CornerRadius(10);
        Padding = new Thickness(12, 10, 12, 11);
        BorderThickness = new Thickness(1);
        MaxWidth = 760;
        HorizontalAlignment = HorizontalAlignment.Left;
        Child = body;
        SetResourceReference(BackgroundProperty, "B.WarnSoft");
        SetResourceReference(BorderBrushProperty, "B.Warn");
    }
}

/// <summary>内联提问卡。每个问题一块，支持单选 / 多选，选中「其它」时露出自由文本框。</summary>
internal sealed class AskCard : Border
{
    private readonly List<AskBlock> _blocks = new();

    public AskCard(string title, JsonElement questions, Action<object?> submit)
    {
        var body = Ui.V(10);
        if (!string.IsNullOrWhiteSpace(title)) body.Children.Add(Ui.Txt(title, 13, true).Wrap());
        foreach (var q in questions.EnumerateArray())
        {
            var block = new AskBlock(q);
            _blocks.Add(block);
            body.Children.Add(block.Root);
        }

        var ok = Ui.Btn(L("确定"), BtnKind.Primary, null, Ico.Check);
        var skip = Ui.Btn(L("跳过"));
        body.Children.Add(Ui.H(8, ok, skip));

        void Freeze(string note)
        {
            ok.IsEnabled = skip.IsEnabled = false;
            foreach (var b in _blocks) b.Root.IsEnabled = false;
            body.Children.Add(Ui.Small(note));
        }
        ok.Click += (_, _) =>
        {
            var answers = new Dictionary<string, object?>();
            foreach (var b in _blocks)
            {
                var picked = b.Collect();
                if (picked is null)
                {
                    AppServices.Toast(L("还没选"), b.Prompt, ToastKind.Warning);
                    return;
                }
                answers[b.Id] = picked;
            }
            Freeze(L("已提交"));
            submit(answers);
        };
        skip.Click += (_, _) =>
        {
            Freeze(L("已跳过"));
            submit(null);
        };

        CornerRadius = new CornerRadius(10);
        Padding = new Thickness(12, 10, 12, 11);
        BorderThickness = new Thickness(1);
        MaxWidth = 760;
        HorizontalAlignment = HorizontalAlignment.Left;
        Child = body;
        SetResourceReference(BackgroundProperty, "B.AccentSoft");
        SetResourceReference(BorderBrushProperty, "B.Accent");
    }
}

/// <summary>提问卡里的一个问题。</summary>
internal sealed class AskBlock
{
    private readonly List<(ToggleButton Btn, string Id, string Label)> _opts = new();
    private readonly TextBox _other = Ui.Input(L("选「其它」时在这里填"));
    private readonly bool _multi;
    private readonly ToggleButton? _otherBtn;

    public string Id { get; }
    public string Prompt { get; }
    public SPanel Root { get; }

    public AskBlock(JsonElement q)
    {
        Id = Str(q, "id") is { Length: > 0 } id ? id : "q1";
        Prompt = Str(q, "prompt") is { Length: > 0 } p ? p : L("请选择");
        _multi = q.TryGetProperty("allow_multiple", out var m) && m.ValueKind == JsonValueKind.True;

        Root = Ui.V(5, Ui.Txt(Prompt + (_multi ? L("（可多选）") : ""), 12.5).Wrap());
        var group = Guid.NewGuid().ToString("N");
        if (q.TryGetProperty("options", out var opts) && opts.ValueKind == JsonValueKind.Array)
            foreach (var o in opts.EnumerateArray())
            {
                var oid = Str(o, "id");
                var label = Str(o, "label") is { Length: > 0 } l ? l : oid;
                ToggleButton btn = _multi
                    ? new CheckBox { Content = label }
                    : new RadioButton { Content = label, GroupName = group };
                btn.Margin = new Thickness(0, 1, 0, 1);
                btn.Checked += (_, _) => SyncOther();
                btn.Unchecked += (_, _) => SyncOther();
                if (oid == "other") _otherBtn = btn;
                _opts.Add((btn, oid, label));
                Root.Children.Add(btn);
            }
        _other.Visibility = Visibility.Collapsed;
        Root.Children.Add(_other);
    }

    /// <summary>只有勾了「其它」才露出自由文本框，与 Qt `_sync_other` 同义。</summary>
    private void SyncOther() =>
        _other.Visibility = _otherBtn?.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>收答案。一个都没选返回 null，让调用方提示用户。</summary>
    public object? Collect()
    {
        var picked = _opts.Where(o => o.Btn.IsChecked == true)
            .Select(o => new Dictionary<string, object?> { ["id"] = o.Id, ["label"] = o.Label })
            .ToList();
        var extra = _other.Text?.Trim() ?? "";
        if (picked.Count == 0 && extra.Length == 0) return null;
        return new Dictionary<string, object?>
        {
            ["picked"] = picked,
            ["other"] = extra,
        };
    }

    private static string Str(JsonElement el, string key) =>
        el.ValueKind == JsonValueKind.Object && el.TryGetProperty(key, out var v)
            ? v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : v.ToString()
            : "";
}

/// <summary>
/// 聊天输入框：跟着内容长高，Enter 发送、Shift+Enter 换行，
/// 输入法组合串没上屏时那一下回车归输入法（判定见 <see cref="ImeGuard"/>）。
/// </summary>
internal sealed class ChatInput : TextBox
{
    private const double MinH = 48;
    private const double MaxH = 140;

    private string _composition = "";

    public event Action<string>? Submitted;

    public ChatInput()
    {
        Style = Ui.S("Input.Multi");
        Tag = L("问我要下什么、哪报错、模组怎么配…  Enter 发送，Shift+Enter 换行");
        AcceptsReturn = true;
        TextWrapping = TextWrapping.Wrap;
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
        Height = MinH;

        TextChanged += (_, _) => Grow();
        // 组合串的开始 / 更新 / 结束：拼音上屏前 CompositionText 一直非空
        TextCompositionManager.AddTextInputStartHandler(this, OnComposition);
        TextCompositionManager.AddTextInputUpdateHandler(this, OnComposition);
        TextCompositionManager.AddTextInputHandler(this, OnCompositionEnd);
        LostFocus += (_, _) => _composition = "";
    }

    private void OnComposition(object sender, TextCompositionEventArgs e) =>
        _composition = e.TextComposition?.CompositionText ?? "";

    private void OnCompositionEnd(object sender, TextCompositionEventArgs e) => _composition = "";

    /// <summary>跟着文字长高，到 140px 封顶后改用滚动条——对齐 Qt `_grow`。</summary>
    private void Grow()
    {
        var want = (LineCount <= 0 ? 1 : LineCount) * FontSize * 1.6 + 22;
        Height = Math.Clamp(want, MinH, MaxH);
    }

    protected override void OnPreviewKeyDown(KeyEventArgs e)
    {
        var shift = (Keyboard.Modifiers & ModifierKeys.Shift) != 0;
        if (ImeGuard.ShouldSend(e.Key, e.ImeProcessedKey, shift, _composition))
        {
            var text = Text?.Trim() ?? "";
            if (text.Length > 0) Submitted?.Invoke(text);
            e.Handled = true;
            return;
        }
        base.OnPreviewKeyDown(e);
    }
}
