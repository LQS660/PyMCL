using System.Text.Json;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class AiPage : UserControl
{
    private string _activeId = "";
    private string _runChatId = "";
    private string _stream = "";
    private TextBlock? _assistant;
    private string _lastUser = "";
    private bool _busy;
    private bool _picking;
    private DispatcherQueueTimer? _flushTimer;

    public AiPage()
    {
        InitializeComponent();
        _flushTimer = DispatcherQueue.CreateTimer();
        _flushTimer.IsRepeating = false;
        _flushTimer.Interval = TimeSpan.FromMilliseconds(33);
        _flushTimer.Tick += (_, _) =>
        {
            SetAssistant(string.IsNullOrEmpty(_stream) ? "…" : _stream);
            ScrollBottom();
        };
    }

    public async Task ReloadAsync()
    {
        if (AppServices.Client is null) return;
        try
        {
            var s = await AppServices.Client.CallAsync<SettingsDto>("get_settings");
            var model = string.IsNullOrWhiteSpace(s?.AiModel) ? "deepseek-v4-flash" : s!.AiModel;
            StatusLabel.Text = (s?.AiMode == "custom" ? "自定义 · " : "公益接口 · ") + model;
        }
        catch { }
        await LoadStoreAsync();
    }

    /// <summary>
    /// 事件属于的那一回合，是不是正显示着的对话在跑的。分不清（两边都没 id）按「是」处理。
    /// 不比对 chat_id 的话，切走对话后旧回合的流式文本会逐字写进新对话的助手气泡里。
    /// </summary>
    private bool RunIsDisplayed(BridgeEvent ev)
    {
        var cid = ev.ChatId;
        if (string.IsNullOrEmpty(cid)) cid = _runChatId;
        return cid.Length == 0 || cid == _activeId;
    }

    public void HandleEvent(BridgeEvent ev)
    {
        if (ev.Event == "ai.delta")
        {
            if (!RunIsDisplayed(ev)) return;
            _stream += ev.Text ?? "";
            if (_flushTimer is { IsRunning: false })
                _flushTimer.Start();
        }
        else if (ev.Event == "ai.status")
        {
            if (!RunIsDisplayed(ev)) return;
            var kind = ev.Kind;
            if (kind == "tool" || kind == "tool_run" || kind == "tool_done" || kind == "tool_skip")
            {
                var prefix = kind switch
                {
                    "tool_run" => "执行中：",
                    "tool_done" => "完成：",
                    "tool_skip" => "已跳过：",
                    _ => "准备：",
                };
                AddCaption(prefix + (string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label));
            }
        }
        else if (ev.Event == "ai.confirm")
        {
            if (!RunIsDisplayed(ev)) return;
            ShowConfirmCard(ev);
        }
        else if (ev.Event == "ai.ask")
        {
            if (!RunIsDisplayed(ev)) return;
            ShowAskCard(ev);
        }
        else if (ev.Event == "ai.done")
        {
            if (!RunIsDisplayed(ev)) return;
            StopFlush();
            SetAssistant(string.IsNullOrWhiteSpace(ev.Text) ? _stream : ev.Text);
            ScrollBottom();
            _runChatId = "";
            SetBusy(false);
        }
        else if (ev.Event == "ai.fail")
        {
            if (!RunIsDisplayed(ev)) return;
            StopFlush();
            SetAssistant(string.IsNullOrWhiteSpace(ev.Text) ? "出错了" : ev.Text);
            _runChatId = "";
            SetBusy(false);
            AppServices.Toast?.Invoke(ev.Stopped ? "已停止" : "助手出错", ev.Text, ev.Stopped ? InfoBarSeverity.Informational : InfoBarSeverity.Error);
        }
    }

    private async Task LoadStoreAsync()
    {
        if (AppServices.Client is null) return;
        var store = await AppServices.Client.CallAsync<AiStoreDto>("ai_list_chats");
        FillList(store);
    }

    private void FillList(AiStoreDto? store)
    {
        _picking = true;
        ChatList.ItemsSource = store?.Chats ?? new();
        _activeId = store?.ActiveId ?? "";
        AiChatDto? cur = null;
        foreach (var c in store?.Chats ?? new())
        {
            if (c.Id == _activeId) { cur = c; break; }
        }
        ChatList.SelectedItem = cur;
        RenderMessages(cur);
        _picking = false;
    }

    private void RenderMessages(AiChatDto? chat)
    {
        MsgHost.Children.Clear();
        _assistant = null;
        _stream = "";
        var msgs = chat?.Messages ?? new();
        if (msgs.Count == 0)
        {
            AddBubble("助手", "我是启动器助手。可以帮你下游戏、装模组和整合包、看启动报错、查模组冲突、改常用配置。", false);
            return;
        }
        foreach (var m in msgs)
            AddBubble(m.Role == "user" ? "我" : "助手", m.Content, m.Role == "user");
        ScrollBottom();
    }

    private void AddBubble(string who, string text, bool mine)
    {
        var card = new Border
        {
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(12, 8, 12, 8),
            MaxWidth = 640,
            HorizontalAlignment = mine ? HorizontalAlignment.Right : HorizontalAlignment.Left,
            Background = mine
                ? new Microsoft.UI.Xaml.Media.SolidColorBrush(Windows.UI.Color.FromArgb(255, 232, 246, 239))
                : (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
        };
        var stack = new StackPanel { Spacing = 2 };
        stack.Children.Add(new TextBlock { Text = who, FontSize = 11, Opacity = 0.6 });
        var body = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
        stack.Children.Add(body);
        card.Child = stack;
        MsgHost.Children.Add(card);
        if (!mine) _assistant = body;
    }

    private void AddCaption(string text)
    {
        MsgHost.Children.Add(new TextBlock
        {
            Text = text,
            FontSize = 12,
            Opacity = 0.75,
            TextWrapping = TextWrapping.Wrap,
        });
        ScrollBottom();
    }

    private void SetAssistant(string text)
    {
        if (_assistant is null)
            AddBubble("助手", text, false);
        else
            _assistant.Text = text;
    }

    private void StopFlush()
    {
        if (_flushTimer is { IsRunning: true })
            _flushTimer.Stop();
    }

    private void ScrollBottom()
    {
        MsgScroll.ChangeView(null, MsgScroll.ScrollableHeight, null, true);
    }

    private void SetBusy(bool on)
    {
        _busy = on;
        StopBtn.IsEnabled = on;
        RetryBtn.IsEnabled = !on;
    }

    private async void Send_Click(object sender, RoutedEventArgs e) => await SendAsync(InputBox.Text);

    private async void Chip_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is string t)
            await SendAsync(t);
    }

    private async Task SendAsync(string? raw)
    {
        var text = (raw ?? "").Trim();
        if (string.IsNullOrEmpty(text) || AppServices.Client is null || _busy) return;
        InputBox.Text = "";
        _lastUser = text;
        AddBubble("我", text, true);
        _stream = "";
        _assistant = null;
        AddBubble("助手", "正在想…", false);
        _runChatId = _activeId;
        SetBusy(true);
        try
        {
            await AppServices.Client.CallAsync("ai_send", new { text, chat_id = _activeId });
        }
        catch (Exception ex)
        {
            SetAssistant(ex.Message);
            SetBusy(false);
        }
    }

    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        try { await AppServices.Client.CallAsync("ai_stop"); } catch { }
    }

    private async void Retry_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_lastUser))
            await SendAsync(_lastUser);
    }

    private async void NewChat_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null) return;
        var data = await AppServices.Client.CallAsync<AiStoreDto>("ai_new_chat");
        FillList(data);
    }

    private async void DeleteChat_Click(object sender, RoutedEventArgs e)
    {
        if (AppServices.Client is null || string.IsNullOrEmpty(_activeId)) return;
        if (!await Dialogs.ConfirmAsync(XamlRoot, "删除会话", "确定删除当前 AI 会话吗？该会话的全部对话记录都会丢失。"))
            return;
        try
        {
            var data = await AppServices.Client.CallAsync<AiStoreDto>("ai_delete_chat", new { chat_id = _activeId });
            FillList(data);
        }
        catch (Exception ex) { AppServices.Toast?.Invoke("删除失败", ex.Message, InfoBarSeverity.Error); }
    }

    private async void ChatList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_picking || ChatList.SelectedItem is not AiChatDto chat || AppServices.Client is null) return;
        if (chat.Id == _activeId) return;
        try
        {
            // 切走时若还有回合在跑，先掐掉：它属于旧对话（后端按 chat_id 把结果写回旧对话），
            // 新对话这边必须从「发送」可点的干净状态开始，不然按钮停在上一回合的「忙」上。
            if (_busy) await AbandonRunAsync();
            var data = await AppServices.Client.CallAsync<AiStoreDto>("ai_set_active", new { chat_id = chat.Id });
            FillList(data);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("切换对话失败", ex.Message, InfoBarSeverity.Error);
            // 切失败就把列表拉回后端认定的当前对话，别让高亮停在没切过去的那个上
            await LoadStoreAsync();
        }
    }

    /// <summary>掐掉在跑的回合并等后端把 busy 放开（最多 3 秒），随后复位本地状态。</summary>
    private async Task AbandonRunAsync()
    {
        if (!_busy || AppServices.Client is null) return;
        _runChatId = "";
        _stream = "";
        _assistant = null;
        StopFlush();
        try
        {
            await AppServices.Client.CallAsync("ai_stop");
            var deadline = DateTime.UtcNow.AddSeconds(3);
            while (DateTime.UtcNow < deadline)
            {
                // AiStoreDto 没带 busy 位，直接读原始 JSON 判后端是否真的收尾了
                var raw = await AppServices.Client.CallAsync("ai_list_chats");
                if (raw.ValueKind != JsonValueKind.Object
                    || !raw.TryGetProperty("busy", out var b)
                    || b.ValueKind != JsonValueKind.True)
                    break;
                await Task.Delay(150);
            }
        }
        catch { }
        SetBusy(false);
    }

    // ==================== 内联确认卡 / 提问卡 ====================
    // 以前这两张卡用模态 ContentDialog 弹。两个问题：
    //   1) 事件来自后端而非「当前页」——用户切到别的页时本页 XamlRoot 变 null，
    //      对话框根本弹不出来，异常还没人观察，后端 wait_card 无超时死等，AI 永久挂起；
    //   2) ContentDialog 丢字段：confirm 不传 always/scope（「始终允许」永不可达），
    //      ask 丢掉后端下发的 options（恒定回一个伪造的 q1/other）。
    // 改成 WPF 那样内联渲染进对话流：跟着消息走，切页也在，字段一个不少。

    private static string Str(JsonElement obj, string key) =>
        obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(key, out var v)
            ? v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : v.ToString()
            : "";

    /// <summary>卡片外壳：和消息气泡同一列，但用强调色边框标出「要你操作」。</summary>
    private Border CardShell(StackPanel body)
    {
        var card = new Border
        {
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(12, 10, 12, 11),
            BorderThickness = new Thickness(1),
            MaxWidth = 760,
            HorizontalAlignment = HorizontalAlignment.Left,
            BorderBrush = ThemeBrushes.Accent,
            Background = ThemeBrushes.Get("CardBackgroundFillColorDefaultBrush"),
            Child = body,
        };
        MsgHost.Children.Add(card);
        ScrollBottom();
        return card;
    }

    private void ShowConfirmCard(BridgeEvent ev)
    {
        if (AppServices.Client is null) return;
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        var body = new StackPanel { Spacing = 8 };
        body.Children.Add(new TextBlock { Text = "需要你点一下确认：", FontSize = 12.5, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        body.Children.Add(new TextBlock { Text = label ?? "执行写操作", TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true });
        // 变更预览（桥端与 Qt 共用 preview.lines），有就逐行展示，信息量与 WPF 一致
        var detail = PreviewText(ev.PayloadJson, "reason");
        if (detail.Length > 0)
            body.Children.Add(new TextBlock { Text = detail, TextWrapping = TextWrapping.Wrap, FontSize = 12, Opacity = 0.8, IsTextSelectionEnabled = true });

        var allowAlways = AllowAlways(ev);
        var yes = new Button { Content = "允许" };
        var always = new Button { Content = "始终允许" };
        var no = new Button { Content = "拒绝" };
        var scope = new ComboBox { Width = 130 };
        scope.Items.Add("仅当前实例");
        scope.Items.Add("所有实例");
        scope.SelectedIndex = 0;
        always.IsEnabled = scope.IsEnabled = allowAlways;
        always.Visibility = scope.Visibility = allowAlways ? Visibility.Visible : Visibility.Collapsed;
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        row.Children.Add(yes);
        row.Children.Add(always);
        row.Children.Add(scope);
        row.Children.Add(no);
        body.Children.Add(row);
        var note = new TextBlock { FontSize = 12, Opacity = 0.75 };
        note.Visibility = Visibility.Collapsed;
        body.Children.Add(note);
        CardShell(body);

        async Task AnswerAsync(bool ok, bool remember)
        {
            yes.IsEnabled = always.IsEnabled = no.IsEnabled = false;
            scope.IsEnabled = false;
            note.Text = ok ? (remember ? "已记住并允许" : "已允许") : "已拒绝";
            note.Visibility = Visibility.Visible;
            try
            {
                await AppServices.Client!.CallAsync("ai_confirm", new
                {
                    ok,
                    always = remember,
                    scope = scope.SelectedIndex == 1 ? "global" : "instance",
                });
            }
            catch (Exception ex) { AppServices.Toast?.Invoke("确认失败", ex.Message, InfoBarSeverity.Error); }
        }
        yes.Click += (_, _) => _ = AnswerAsync(true, false);
        always.Click += (_, _) => _ = AnswerAsync(true, true);
        no.Click += (_, _) => _ = AnswerAsync(false, false);
        SetBusy(true);
    }

    /// <summary>给不给「始终允许」：桥按 TOOL_META 判好放在 allow_always（删除类、计划审批都不给）；
    /// 旧版桥没这一位就按名字兜底，与 WPF ConfirmCard.AllowAlways 同一判据。</summary>
    private static bool AllowAlways(BridgeEvent ev)
    {
        try
        {
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(ev.PayloadJson) ? "{}" : ev.PayloadJson);
            var r = doc.RootElement;
            if (r.TryGetProperty("allow_always", out var aa)
                && aa.ValueKind is JsonValueKind.True or JsonValueKind.False)
                return aa.ValueKind == JsonValueKind.True;
        }
        catch { }
        return ev.Name is not ("delete_instance" or "delete_mod" or "plan_approval");
    }

    private static string PreviewText(string? json, string reasonKey)
    {
        try
        {
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(json) ? "{}" : json);
            var r = doc.RootElement;
            var reason = Str(r, reasonKey);
            if (r.TryGetProperty("preview", out var pv) && pv.ValueKind == JsonValueKind.Object
                && pv.TryGetProperty("lines", out var lines) && lines.ValueKind == JsonValueKind.Array)
            {
                var parts = new List<string>();
                var head = Str(pv, "head");
                if (head.Length > 0) parts.Add(head);
                foreach (var l in lines.EnumerateArray())
                    if (l.ValueKind == JsonValueKind.String) parts.Add(l.GetString() ?? "");
                var preview = string.Join("\n", parts.Where(s => s.Length > 0));
                if (preview.Length > 0)
                    return reason.Length > 0 ? preview + "\n" + reason : preview;
            }
            return reason;
        }
        catch { return ""; }
    }

    private void ShowAskCard(BridgeEvent ev)
    {
        if (AppServices.Client is null) return;
        JsonDocument? doc = null;
        try
        {
            doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(ev.PayloadJson) ? "{}" : ev.PayloadJson);
            var root = doc.RootElement;
            if (!root.TryGetProperty("questions", out var qs) || qs.ValueKind != JsonValueKind.Array)
            {
                // 没有题目可答：直接回 null（与 WPF 一致），别让后端空等
                _ = AppServices.Client.CallAsync("ai_answer", new { result = (object?)null });
                return;
            }
            var title = Str(root, "title");
            var body = new StackPanel { Spacing = 10 };
            if (title.Length > 0)
                body.Children.Add(new TextBlock { Text = title, FontSize = 13, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap });

            // 每道题一块：单选用 RadioButton、多选用 CheckBox，选项 id/label 全部照后端下发的渲染
            var blocks = new List<(string Id, string Prompt, List<(RadioButton? Radio, CheckBox? Check, string Oid, string Label)> Opts, TextBox Other)>();
            foreach (var q in qs.EnumerateArray())
            {
                var qid = Str(q, "id");
                if (qid.Length == 0) qid = "q1";
                var prompt = Str(q, "prompt");
                if (prompt.Length == 0) prompt = "请选择";
                var multi = q.TryGetProperty("allow_multiple", out var m) && m.ValueKind == JsonValueKind.True;
                var block = new StackPanel { Spacing = 5 };
                block.Children.Add(new TextBlock { Text = prompt + (multi ? "（可多选）" : ""), FontSize = 12.5, TextWrapping = TextWrapping.Wrap });
                var opts = new List<(RadioButton?, CheckBox?, string, string)>();
                var other = new TextBox { PlaceholderText = "选「其它」时在这里填", Visibility = Visibility.Collapsed };
                var group = Guid.NewGuid().ToString("N");
                if (q.TryGetProperty("options", out var olist) && olist.ValueKind == JsonValueKind.Array)
                {
                    foreach (var o in olist.EnumerateArray())
                    {
                        var oid = Str(o, "id");
                        var olabel = Str(o, "label");
                        if (olabel.Length == 0) olabel = oid;
                        if (multi)
                        {
                            var cb = new CheckBox { Content = olabel };
                            if (oid == "other")
                            {
                                cb.Checked += (_, _) => other.Visibility = Visibility.Visible;
                                cb.Unchecked += (_, _) => other.Visibility = Visibility.Collapsed;
                            }
                            opts.Add((null, cb, oid, olabel));
                            block.Children.Add(cb);
                        }
                        else
                        {
                            var rb = new RadioButton { Content = olabel, GroupName = group };
                            if (oid == "other") { cbOther(rb, other); }
                            opts.Add((rb, null, oid, olabel));
                            block.Children.Add(rb);
                        }
                    }
                }
                block.Children.Add(other);
                blocks.Add((qid, prompt, opts, other));
                body.Children.Add(block);
            }

            var ok = new Button { Content = "确定" };
            var skip = new Button { Content = "跳过" };
            var btnRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            btnRow.Children.Add(ok);
            btnRow.Children.Add(skip);
            body.Children.Add(btnRow);
            var note = new TextBlock { FontSize = 12, Opacity = 0.75, Visibility = Visibility.Collapsed };
            body.Children.Add(note);
            CardShell(body);

            void Freeze(string text)
            {
                ok.IsEnabled = skip.IsEnabled = false;
                note.Text = text;
                note.Visibility = Visibility.Visible;
            }

            ok.Click += (_, _) =>
            {
                var answers = new Dictionary<string, object?>();
                foreach (var b in blocks)
                {
                    var picked = new List<Dictionary<string, string>>();
                    foreach (var (rb, cb, oid, olabel) in b.Opts)
                    {
                        var on = rb?.IsChecked == true || cb?.IsChecked == true;
                        if (on) picked.Add(new Dictionary<string, string> { ["id"] = oid, ["label"] = olabel });
                    }
                    var extra = b.Other.Text?.Trim() ?? "";
                    if (picked.Count == 0 && extra.Length == 0)
                    {
                        AppServices.Toast?.Invoke("还没选", b.Prompt, InfoBarSeverity.Warning);
                        return;
                    }
                    answers[b.Id] = new Dictionary<string, object?> { ["picked"] = picked, ["other"] = extra };
                }
                Freeze("已提交");
                _ = AnswerAsync(answers);
            };
            skip.Click += (_, _) => { Freeze("已跳过"); _ = AnswerAsync(null); };
            SetBusy(true);
        }
        catch (Exception ex)
        {
            AppServices.Toast?.Invoke("提问卡解析失败", ex.Message, InfoBarSeverity.Error);
            // 解析不了也要给后端一个答复，否则内核在 wait_card 里空等
            _ = AppServices.Client.CallAsync("ai_answer", new { result = (object?)null });
        }
        finally { doc?.Dispose(); }
    }

    /// <summary>单选模式下「其它」也要能露出自由文本框。</summary>
    private static void cbOther(RadioButton rb, TextBox other)
    {
        rb.Checked += (_, _) => other.Visibility = Visibility.Visible;
        rb.Unchecked += (_, _) => other.Visibility = Visibility.Collapsed;
    }

    private async Task AnswerAsync(object? answers)
    {
        if (AppServices.Client is null) return;
        try { await AppServices.Client.CallAsync("ai_answer", new { result = answers }); }
        catch (Exception ex) { AppServices.Toast?.Invoke("回答失败", ex.Message, InfoBarSeverity.Error); }
    }
}
