using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class AiPage : PageBase
{
    public override string Title => "AI 助手";

    private readonly SPanel _chatList = Ui.V(4);
    private readonly SPanel _messages = Ui.V(12);
    private readonly SmoothScroll _scroll;
    private readonly TextBox _input = Ui.Multi("说人话就行：下个 1.20.1 Fabric，再装钠和光影", height: 76);
    private readonly Button _send, _stop;
    private readonly TextBlock _status = Ui.Small("");
    private readonly StringBuilder _stream = new();
    private TextBlock? _streamBlock;
    private Border? _streamCard;
    private AiStoreDto _store = new();
    private bool _busy;

    public AiPage()
    {
        _send = Ui.Btn("发送", BtnKind.Primary, (_, _) => Run(SendAsync), Ico.Send);
        _stop = Ui.Btn("停止", BtnKind.Danger, (_, _) => Run(StopAsync), Ico.Stop);
        _stop.IsEnabled = false;

        _scroll = Ui.Scroll(_messages.M(4, 4, 10, 4));
        _input.AcceptsReturn = true;
        _input.PreviewKeyDown += (_, e) =>
        {
            if (e.Key != Key.Enter || Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)) return;
            e.Handled = true;
            Run(SendAsync);
        };

        var newChat = Ui.Btn("新对话", BtnKind.Soft, (_, _) => Run(NewChatAsync), Ico.Add);
        var side = Ui.V(10,
            newChat.Stretch(),
            Ui.Sep(),
            Ui.Scroll(_chatList));
        var sideCard = Ui.Card(side, 12);
        sideCard.Width = 208;

        var quick = new WrapPanel();
        foreach (var (text, prompt) in new[]
                 {
                     ("下个最新版", "帮我下载最新正式版 Minecraft"),
                     ("装 Fabric + 钠", "给我装 1.20.1 Fabric，再装钠和 Iris 光影"),
                     ("崩溃分析", "刚才启动失败了，读一下日志告诉我原因"),
                     ("扫模组冲突", "扫一下当前实例的模组冲突"),
                 })
        {
            var p = prompt;
            var b = Ui.Btn(text, BtnKind.Chip, (_, _) =>
            {
                _input.Text = p;
                _input.Focus();
                _input.CaretIndex = p.Length;
            });
            b.Margin = new Thickness(0, 0, 6, 6);
            quick.Children.Add(b);
        }

        var inputCard = Ui.Card(Ui.V(8,
            quick,
            _input,
            Ui.G(null, "*,Auto")
                .Add(_status.VCenter(), 0, 0)
                .Add(Ui.H(8, _stop, _send), 0, 1)), 14);

        var main = Ui.G("*,Auto");
        main.Add(Ui.Card(_scroll, 10), 0, 0);
        main.Add(inputCard.M(0, 12, 0, 0), 1, 0);

        var cols = Ui.G(null, "Auto,*");
        cols.Add(sideCard.M(0, 0, 12, 0), 0, 0);
        cols.Add(main, 0, 1);

        var root = Ui.G("Auto,*");
        root.Add(Ui.Section("AI 助手", "对话里下游戏、装模组、读崩溃日志；写操作会先问你").M(0, 0, 0, 12), 0, 0);
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
            var title = string.IsNullOrWhiteSpace(c.Title) ? "新对话" : c.Title;
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
        if (_store.Chats.Count == 0) _chatList.Children.Add(Ui.Muted("还没有对话"));
    }

    private ContextMenu DelMenu(string id)
    {
        var m = new ContextMenu();
        var del = new MenuItem { Header = "删除这个对话" };
        del.Click += (_, _) => Run(async () =>
        {
            _store = await Api.TryCallAsync<AiStoreDto>("ai_delete_chat", new { chat_id = id }, _store) ?? _store;
            RenderChats();
            RenderMessages();
        });
        m.Items.Add(del);
        return m;
    }

    private void RenderMessages()
    {
        _messages.Children.Clear();
        var chat = _store.Chats.FirstOrDefault(c => c.Id == _store.ActiveId) ?? _store.Chats.FirstOrDefault();
        if (chat is null || chat.Messages.Count == 0)
        {
            _messages.Children.Add(Ui.Empty(Ico.Robot, "问点什么吧",
                "「下一款 1.20.1 Fabric」「装钠和光影」「启动闪退了帮我看看」——写操作前会先弹确认。"));
            return;
        }
        foreach (var m in chat.Messages)
        {
            if (m.Role is not ("user" or "assistant")) continue;
            _messages.Children.Add(Bubble(m.Role == "user", m.Content));
        }
        Motion.Stagger(_messages, 18, 200, 8);
        Dispatcher.BeginInvoke(() => _scroll.ScrollToEnd());
    }

    private UIElement Bubble(bool mine, string text)
    {
        var tb = new TextBox
        {
            Text = text,
            IsReadOnly = true,
            BorderThickness = new Thickness(0),
            Background = Brushes.Transparent,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13,
            Padding = new Thickness(0),
        };
        tb.SetResourceReference(Control.ForegroundProperty, mine ? "B.OnAccent" : "B.Ink");
        var card = new Border
        {
            CornerRadius = new CornerRadius(mine ? 12 : 12, mine ? 12 : 12, mine ? 4 : 12, mine ? 12 : 4),
            Padding = new Thickness(13, 10, 13, 11),
            MaxWidth = 760,
            HorizontalAlignment = mine ? HorizontalAlignment.Right : HorizontalAlignment.Left,
            Child = tb,
        };
        card.SetResourceReference(Border.BackgroundProperty, mine ? "B.Accent" : "B.Paper2");
        return card;
    }

    private async Task NewChatAsync()
    {
        _store = await Api.TryCallAsync<AiStoreDto>("ai_new_chat", null, _store) ?? _store;
        RenderChats();
        RenderMessages();
    }

    private async Task SendAsync()
    {
        var text = _input.Text?.Trim() ?? "";
        if (text.Length == 0 || _busy) return;
        _input.Clear();
        _busy = true;
        _send.IsEnabled = false;
        _stop.IsEnabled = true;
        _status.Text = "思考中…";

        if (_messages.Children.Count == 1 && _messages.Children[0] is SPanel) _messages.Children.Clear();
        _messages.Children.Add(Bubble(true, text));
        _stream.Clear();
        _streamBlock = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 13 };
        _streamBlock.SetResourceReference(TextBlock.ForegroundProperty, "B.Ink");
        _streamCard = new Border
        {
            CornerRadius = new CornerRadius(12, 12, 12, 4),
            Padding = new Thickness(13, 10, 13, 11),
            MaxWidth = 760,
            HorizontalAlignment = HorizontalAlignment.Left,
            Child = _streamBlock,
        };
        _streamCard.SetResourceReference(Border.BackgroundProperty, "B.Paper2");
        _messages.Children.Add(_streamCard);
        Motion.FadeIn(_streamCard, 200, 8);
        _scroll.ScrollToEnd();

        var launch = new Dictionary<string, object?>
        {
            ["instance"] = Win?.Prefs.CatalogInstance ?? "",
            ["username"] = Win?.Prefs.LastUser ?? "",
        };
        var r = await Api.TryCallAsync<OpResult>("ai_send", new { text, chat_id = _store.ActiveId, launch });
        if (r is { Ok: false })
        {
            _status.Text = r.Message;
            Finish();
        }
    }

    private async Task StopAsync()
    {
        await Api.TryCallAsync<object>("ai_stop");
        _status.Text = "已停止";
    }

    private void Finish()
    {
        _busy = false;
        _send.IsEnabled = true;
        _stop.IsEnabled = false;
    }

    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "ai.delta":
                if (_streamBlock is null) return;
                _stream.Append(ev.Text);
                _streamBlock.Text = _stream.ToString();
                _scroll.ScrollToEnd();
                break;

            case "ai.status":
                _status.Text = string.IsNullOrWhiteSpace(ev.Label)
                    ? ev.Kind switch
                    {
                        "tool_start" => "正在执行操作…",
                        "tool_done" => "操作完成",
                        "thinking" => "思考中…",
                        _ => _status.Text,
                    }
                    : ev.Label;
                break;

            case "ai.done":
                _status.Text = "";
                Finish();
                Run(async () =>
                {
                    _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, _store) ?? _store;
                    RenderChats();
                    RenderMessages();
                });
                break;

            case "ai.fail":
                _status.Text = ev.Text;
                if (_streamBlock != null && _stream.Length == 0) _streamBlock.Text = ev.Text;
                Finish();
                break;

            case "ai.confirm":
                Run(() => ConfirmAsync(ev));
                break;

            case "ai.ask":
                Run(() => AskAsync(ev));
                break;
        }
    }

    private async Task ConfirmAsync(BridgeEvent ev)
    {
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        var args = "";
        if (ev.Payload.ValueKind == JsonValueKind.Object && ev.Payload.TryGetProperty("args", out var a))
            args = a.ToString();
        var body = Ui.V(8,
            Ui.Txt(label, 13.5, true).Wrap(),
            string.IsNullOrWhiteSpace(args) ? null : Ui.Mono(args).Wrap());
        var ok = await Dlg.Ask("AI 想执行一个操作", body, "允许", "拒绝");
        await Api.TryCallAsync<object>("ai_confirm", new { ok });
    }

    private async Task AskAsync(BridgeEvent ev)
    {
        if (ev.Payload.ValueKind != JsonValueKind.Object || !ev.Payload.TryGetProperty("questions", out var qs)
            || qs.ValueKind != JsonValueKind.Array)
        {
            await Api.TryCallAsync<object>("ai_answer", new { result = (object?)null });
            return;
        }
        var title = ev.Payload.TryGetProperty("title", out var t) ? t.GetString() ?? "AI 有几个问题" : "AI 有几个问题";
        var body = Ui.V(12);
        var pickers = new List<(string Id, ComboBox Box, List<string> Values)>();
        foreach (var q in qs.EnumerateArray())
        {
            var id = q.TryGetProperty("id", out var qi) ? qi.GetString() ?? "" : "";
            var prompt = q.TryGetProperty("prompt", out var qp) ? qp.GetString() ?? "" : "";
            var labels = new List<string>();
            var values = new List<string>();
            if (q.TryGetProperty("options", out var opts) && opts.ValueKind == JsonValueKind.Array)
                foreach (var o in opts.EnumerateArray())
                {
                    labels.Add(o.TryGetProperty("label", out var ol) ? ol.GetString() ?? "" : o.ToString());
                    values.Add(o.TryGetProperty("id", out var oi) ? oi.GetString() ?? "" : o.ToString());
                }
            var box = Ui.Combo(labels);
            pickers.Add((id, box, values));
            body.Children.Add(Ui.V(5, Ui.Txt(prompt, 13).Wrap(), box));
        }
        var ok = await Dlg.Ask(title, body, "提交");
        if (!ok)
        {
            await Api.TryCallAsync<object>("ai_answer", new { result = (object?)null });
            return;
        }
        var result = new Dictionary<string, object?>();
        foreach (var (id, box, values) in pickers)
        {
            var idx = Math.Max(0, box.SelectedIndex);
            result[id] = idx < values.Count ? values[idx] : box.Str();
        }
        await Api.TryCallAsync<object>("ai_answer", new { result });
    }
}
