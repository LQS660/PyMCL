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
    private readonly ComboBox _perm = Ui.Combo(new[]
    {
        L("每次确认"), L("写直接执行"), L("只看不动"), L("全自动"), L("自定义")
    }, width: 112);
    private readonly Button _send, _stop, _retry, _rewind;
    private readonly TextBlock _status = Ui.Small("");
    private readonly TextBlock _usageLabel = Ui.Small("");
    private bool _syncPerm;
    private readonly StringBuilder _stream = new();
    private readonly Dictionary<string, ToolLine> _toolLines = new();
    private readonly Dictionary<string, ToolLine> _taskLines = new();
    private Bubble? _streamBubble;
    private AiStoreDto _store = new();
    private bool _busy;
    // 在跑的这一回合属于哪条对话：用户中途切走后，流式 / 状态 / 收尾事件都靠它分流，
    // 别把旧对话的气泡、工具行、报错贴进正看着的新对话里。
    private string _runChatId = "";
    // 这一回合是我们因切换对话主动掐掉的：收尾那帖 ai.fail 别再弹一次「已停止」
    private bool _abandoned;
    // 切换对话时等在跑的回合真正收尾（后端 busy 放开）再放行，避免新对话第一句被「上一条还在处理」顶回
    private TaskCompletionSource? _runEnded;

    public AiPage()
    {
        _send = Ui.Btn(L("发送"), BtnKind.Primary, (_, _) => Run(SendAsync), Ico.Send);
        _stop = Ui.Btn(L("停止"), BtnKind.Danger, (_, _) => Run(StopAsync), Ico.Stop);
        _retry = Ui.Btn(L("重试"), BtnKind.Chip, (_, _) => Run(RetryAsync), Ico.Refresh);
        // 撤回最近一轮（对齐 Qt _rewind）：对话截回上一轮之前，该轮写/删改动一并还原
        _rewind = Ui.Btn(L("撤回"), BtnKind.Chip, (_, _) => Run(RewindAsync), Ico.Back);
        _stop.IsEnabled = false;
        _retry.IsEnabled = false;
        _perm.ToolTip = L("AI 权限等级");
        _perm.SelectionChanged += (_, _) =>
        {
            if (!_syncPerm) Run(SavePermissionModeAsync, L("权限设置保存失败"));
        };

        _scroll = Ui.Scroll(_messages.M(4, 4, 10, 4));
        _input.Submitted += text => Run(() => SendTextAsync(text));

        var newChat = Ui.Btn(L("新对话"), BtnKind.Soft, (_, _) => Run(NewChatAsync), Ico.Add);
        var permission = Ui.IconBtn(Ico.Gear, L("管理 AI 权限"), (_, _) => Run(OpenPermissionPanelAsync));
        var side = Ui.V(10, Ui.G(null, "*,Auto").Add(newChat, 0, 0).Add(permission, 0, 1), Ui.Sep(), Ui.Scroll(_chatList));
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

        // 6.1 会话累计用量行（右对齐小字；ai.done 时刷新）
        var usageRow = Ui.G(null, "*,Auto")
            .Add(_status.VCenter(), 0, 0)
            .Add(_usageLabel, 0, 1);
        var inputCard = Ui.Card(Ui.V(8,
            quick,
            _input,
            usageRow), 14);

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

    private static readonly string[] PermissionModes = { "default", "acceptEdits", "plan", "yolo", "custom" };

    private async Task SyncPermissionAsync()
    {
        var settings = await Api.TryCallAsync<Dictionary<string, JsonElement>>("get_settings", null, new()) ?? new();
        var mode = "default";
        if (settings.TryGetValue("ai_permission_mode", out var raw) && raw.ValueKind == JsonValueKind.String)
            mode = raw.GetString() ?? mode;
        var index = Array.IndexOf(PermissionModes, mode);
        if (index < 0) index = 0;
        _syncPerm = true;
        try { _perm.SelectedIndex = index; }
        finally { _syncPerm = false; }
    }

    private async Task SavePermissionModeAsync()
    {
        var mode = _perm.SelectedIndex >= 0 && _perm.SelectedIndex < PermissionModes.Length
            ? PermissionModes[_perm.SelectedIndex] : "default";
        await AppServices.Client.CallAsync<object>("save_settings", new
        {
            data = new Dictionary<string, object?>
            {
                ["ai_permission_mode"] = mode,
                ["ai_confirm_writes"] = mode != "yolo",
            }
        });
    }

    private async Task OpenPermissionPanelAsync()
    {
        var instance = await Api.TryCallAsync<string>("get_setting",
            new { key = "default_instance", @default = "default" }, "default") ?? "default";
        var panel = new AiPermissionPanel(instance);
        await panel.RefreshAsync();
        var layer = Dlg.Panel(L("权限管理"), panel, 860);
        panel.CloseRequested = layer.Close;
    }

    protected override async Task LoadAsync()
    {
        _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, new()) ?? new();
        await SyncPermissionAsync();
        // 「发送 / 停止」按钮对回后端的真实状态：桥重启、漏掉一帖 ai.done，
        // 前端自己那份 busy 就永远停在上一回合的「忙」上，F5 / 重进页面都救不回来。
        if (_busy && !_store.Busy) ResetRunState();
        else if (!_busy && _store.Busy) SetBusy(true);
        RenderChats();
        // 回合进行中别整页重画消息区：ui_changed 触发的刷新会把流式气泡 / 工具行 /
        // 等待中的确认卡清掉（落库只在回合结束才发生），重画就等于把这些全丢掉
        if (!(_busy && _runChatId.Length > 0 && _runChatId == _store.ActiveId))
        {
            RenderMessages();
            RestorePendingCard();
        }
    }

    /// <summary>SSE 断线窗口里丢掉的确认 / 提问卡：用 ai_list_chats 带回的
    /// pending_card 补画——内核在等回答，页面上没卡就只能干等。</summary>
    private void RestorePendingCard()
    {
        var pc = _store.PendingCard;
        if (pc is not { ValueKind: JsonValueKind.Object } || !_store.Busy) return;
        string GetStr(string prop) =>
            pc.Value.TryGetProperty(prop, out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? "" : "";
        var kind = GetStr("kind");
        if (kind.Length == 0) return;
        var chatId = GetStr("chat_id");
        if (chatId.Length > 0 && chatId != _store.ActiveId) return;
        var ev = new BridgeEvent { Name = GetStr("name"), Label = GetStr("label"), Payload = pc.Value };
        SetBusy(true);
        if (_runChatId.Length == 0) _runChatId = chatId.Length > 0 ? chatId : _store.ActiveId;
        if (kind == "confirm") ShowConfirm(ev);
        else if (kind == "ask") ShowAsk(ev);
    }

    private void RenderChats()
    {
        _chatList.Children.Clear();
        foreach (var c in _store.Chats)
        {
            var id = c.Id;
            var active = id == _store.ActiveId;
            var title = string.IsNullOrWhiteSpace(c.Title) ? L("新对话") : c.Title;
            var btn = Ui.Btn(title, active ? BtnKind.Soft : BtnKind.Ghost, (_, _) =>
            {
                // 点的就是当前对话：不切，也别把正在跑的回合掐了
                if (id == _store.ActiveId) return;
                Run(() => SwitchChatAsync(() =>
                    Api.TryCallAsync<AiStoreDto>("ai_set_active", new { chat_id = id }, _store)));
            });
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
        del.Click += (_, _) => Run(() => SwitchChatAsync(() =>
            Api.TryCallAsync<AiStoreDto>("ai_delete_chat", new { chat_id = id }, _store)));
        m.Items.Add(del);
        return m;
    }

    private Task NewChatAsync() =>
        SwitchChatAsync(() => Api.TryCallAsync<AiStoreDto>("ai_new_chat", null, _store));

    /// <summary>
    /// 切换 / 新建 / 删除对话共用的一条路：换 store、重画、把底栏复位。
    /// 换走时若还有回合在跑，先把它掐掉——它属于旧对话（bridge 按 chat_id 把结果写回旧对话），
    /// 新对话这边必须从「发送」可点的干净状态开始；不然按钮就停在上一回合的「忙」上，
    /// 状态栏也还挂着旧对话的「已停止 / 操作完成」。只删一条非当前对话不算切走，在跑的回合不动。
    /// </summary>
    private async Task SwitchChatAsync(Func<Task<AiStoreDto?>> op)
    {
        var before = _store.ActiveId;
        _store = await op() ?? _store;
        if (_store.ActiveId != before || (_busy && ActiveChat is null))
            await AbandonRunAsync();
        if (!_busy) _status.Text = "";
        RenderChats();
        RenderMessages();
    }

    /// <summary>掐掉在跑的回合并等它真正收尾（后端 busy 放开），最多等 3 秒。</summary>
    private async Task AbandonRunAsync()
    {
        if (!_busy) return;
        _abandoned = true;
        var ended = _runEnded = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var r = await Api.TryCallAsync<JsonElement>("ai_stop");
        if (!BackendBusy(r))
        {
            // 回合刚好自己收尾了（ai_stop 回 busy=false）：静默复位就行，别弹
            // 「已中断」吓人；_abandoned 保持 true，让还压在 Dispatcher 队列里的
            // ai.done 安静地走完（那条事件的复位是幂等的）
            _streamBubble = null;
            _stream.Clear();
            _runChatId = "";
            _status.Text = "";
            SetBusy(false);
            _runEnded?.TrySetResult();
            _runEnded = null;
            return;
        }
        await Task.WhenAny(ended.Task, Task.Delay(3000));
        ResetRunState();
        Toast(L("已停止上一个对话的回合"), L("切换对话时正在运行的那一轮已中断"));
    }

    private static bool BackendBusy(JsonElement r) =>
        r.ValueKind == JsonValueKind.Object
        && r.TryGetProperty("busy", out var b) && b.ValueKind == JsonValueKind.True;

    /// <summary>这一回合彻底完了：按钮复位、流式上下文清空、叫醒等着它结束的切换流程。</summary>
    private void ResetRunState()
    {
        _streamBubble = null;
        _stream.Clear();
        _runChatId = "";
        _abandoned = false;
        _status.Text = "";
        SetBusy(false);
        _runEnded?.TrySetResult();
        _runEnded = null;
    }

    /// <summary>事件属于的那回合，是不是正显示着的对话在跑的。分不清（两边都没 id）按「是」处理。</summary>
    private bool RunIsDisplayed(BridgeEvent ev)
    {
        var cid = ChatIdOf(ev);
        if (cid.Length == 0) cid = _runChatId;
        return cid.Length == 0 || cid == _store.ActiveId;
    }

    private static string ChatIdOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("chat_id", out var c) && c.ValueKind == JsonValueKind.String
            ? c.GetString() ?? "" : "";

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
            _rewind.IsEnabled = false;
            return;
        }
        foreach (var m in chat.Messages)
        {
            if (m.Role is not ("user" or "assistant" or "error")) continue;
            var text = m.Content;
            if (!string.IsNullOrWhiteSpace(m.Note) && !text.Contains(m.Note, StringComparison.Ordinal))
                text = (text + "\n\n" + m.Note).Trim();
            _messages.Children.Add(new Bubble(m.Role, text, RetryFrom));
        }
        // 3.4 计划卡持久化恢复：store 里存着本对话最新待办，重开程序 / 切页回来仍在
        if (chat.Plan is { Items.Count: > 0 })
        {
            _planCard = new PlanCard(chat.Plan.Items
                .Where(i => !string.IsNullOrWhiteSpace(i.Title))
                .Select(i => (i.Title, i.Status)).ToList());
            _messages.Children.Add(_planCard);
        }
        Motion.Stagger(_messages, 18, 200, 8);
        _retry.IsEnabled = !_busy && LastUserText().Length > 0;
        _rewind.IsEnabled = _retry.IsEnabled;
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
        if (text.Length == 0) return;
        if (_busy)
        {
            // 别静默吞掉：用户只看到「点了没反应」，会以为按钮坏了
            Toast(L("上一条还在处理"), L("等它说完，或点「停止」再发"), ToastKind.Warning);
            return;
        }
        _input.Clear();
        _runChatId = _store.ActiveId;
        SetBusy(true);
        _status.Text = L("思考中…");

        Add(new Bubble("user", text, RetryFrom));
        _stream.Clear();
        _streamBubble = new Bubble("assistant", "…", RetryFrom);
        _streamBubble.SetThinking(L("正在想…"));
        Add(_streamBubble);

        var launch = new Dictionary<string, object?>
        {
            ["instance"] = Win?.Prefs.CatalogInstance ?? "",
            ["username"] = Win?.Prefs.LastUser ?? "",
        };
        var r = await Api.TryCallAsync<OpResult>("ai_send", new { text, chat_id = _store.ActiveId, launch });
        if (r is null || !r.Ok)
        {
            // 调用没到后端（r 为空）或被拒：这一回合根本没开始，不会再有 ai.done / ai.fail
            // 来复位，这里就得把按钮放回去——否则「停止」亮着、「发送」灰着，永远回不来。
            var msg = r?.Message is { Length: > 0 } m ? m : L("后端没有响应，请稍后再试");
            if (_streamBubble != null) _messages.Children.Remove(_streamBubble);
            Add(new Bubble("error", msg, RetryFrom));
            ResetRunState();
            _status.Text = msg;
        }
    }

    private async Task StopAsync()
    {
        var r = await Api.TryCallAsync<JsonElement>("ai_stop");
        _status.Text = L("已停止");
        // 后端根本没有回合在跑（或压根没应答）：不会再有 ai.fail 来复位，当场把按钮放回去
        if (!BackendBusy(r))
        {
            ResetRunState();
            _status.Text = L("已停止");
        }
    }

    /// <summary>撤回最近一轮（对齐 Qt _rewind）：对话截回上一轮之前，该轮写/删改动一并还原。</summary>
    private async Task RewindAsync()
    {
        var r = await Api.TryCallAsync<JsonElement>("ai_rewind",
            new { chat_id = _store.ActiveId ?? "" });
        _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, _store) ?? _store;
        RenderMessages();
        var ok = r.ValueKind == JsonValueKind.Object && r.TryGetProperty("ok", out var okEl) && okEl.GetBoolean();
        var diskChanged = r.ValueKind == JsonValueKind.Object
                          && r.TryGetProperty("disk_changed", out var dcEl) && dcEl.GetBoolean();
        if (!ok && diskChanged)
        {
            // 部分还原：磁盘动了但没全部还原，必须如实说
            _status.Text = L("对话已回退，但磁盘改动没能全部还原，请手动检查相关文件");
            return;
        }
        if (!ok)
        {
            // 后端忙 / 其他失败：明确报出来，绝不假装「已撤回」
            var msg = r.ValueKind == JsonValueKind.Object
                && r.TryGetProperty("message", out var mEl)
                && mEl.ValueKind == JsonValueKind.String
                ? mEl.GetString() ?? "" : "";
            _status.Text = msg.Length > 0 ? msg : L("撤回失败");
            return;
        }
        var restored = 0;
        if (r.ValueKind == JsonValueKind.Object && r.TryGetProperty("restored_files", out var rfEl)
            && rfEl.TryGetInt32(out var n)) restored = n;
        if (diskChanged)
            _status.Text = string.Format(L("已撤回：{0} 个文件的改动已还原"), restored);
        else if (r.ValueKind == JsonValueKind.Object
                 && r.TryGetProperty("rollbackable", out var rbEl) && rbEl.ValueKind == JsonValueKind.False)
            _status.Text = L("已撤回：只回退了对话，这一轮的磁盘改动无法自动还原");
        else
            _status.Text = L("已撤回：只回退了对话，这一轮没有可还原的磁盘改动");
    }

    private void SetBusy(bool on)
    {
        _busy = on;
        _send.IsEnabled = !on;
        _stop.IsEnabled = on;
        _rewind.IsEnabled = !on && LastUserText().Length > 0;
        _retry.IsEnabled = !on && LastUserText().Length > 0;
    }

    // ==================== 工具行 ====================
    private ToolLine Line(string name, string text, ToolState state)
    {
        if (_toolLines.TryGetValue(name, out var line))
        {
            line.SetText(text);
            line.SetState(state);
            return line;
        }
        line = new ToolLine(text, name);
        line.SetState(state);
        _toolLines[name] = line;
        Add(line);
        return line;
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            // 流式 / 状态 / 确认 / 提问都是「这一回合」的东西：用户已经切到别的对话时，
            // 别把旧对话的字和工具行贴进新对话里（确认 / 提问由 ai_stop 那头代答 False / None）
            case "ai.delta":
                if (_streamBubble is null || !RunIsDisplayed(ev)) return;
                _stream.Append(ev.Text);
                // live：<think> 没闭合时思考块自动展开走流光，闭合了就收起、正文接着长
                _streamBubble.SetText(_stream.ToString(), live: true);
                ScrollDown();
                break;

            case "ai.status":
                if (!RunIsDisplayed(ev)) return;
                OnStatus(ev);
                break;

            case "ai.done":
            {
                // 迟到的旧回合收尾（切换后 ai_stop 超时 / 事件积压时才到）：绝不能
                // 拿它复位新回合的运行态、覆盖新回合的用量——比对 chat_id 后丢弃
                var staleCid = ChatIdOf(ev);
                if (_busy && _runChatId.Length > 0 && staleCid.Length > 0 && staleCid != _runChatId)
                    return;
                var quiet = _abandoned;
                var mine = RunIsDisplayed(ev);
                _status.Text = "";
                if (!quiet && mine) NotifyStop(ev);
                // 6.1 会话累计用量（与 Qt 同一数据源：bridge 在 ai.done 里转发）；
                // 只在事件属于正显示的对话时更新，别拿旧对话的数盖这边
                if (mine) ShowUsage(ev);
                // 流式气泡先就地补上「为什么停」；随后重拉的会话里已带同一条提示
                // （bridge 端照 Qt 入了库），重建后不丢。
                var note = StopNote(ev);
                // 这一发同时把流式态收掉（live=false）：思考块该折的折起来、流光停下
                if (_streamBubble != null && mine && (_stream.Length > 0 || note.Length > 0))
                    _streamBubble.SetText(_stream.ToString() + note);
                ResetRunState();
                Run(async () =>
                {
                    _store = await Api.TryCallAsync<AiStoreDto>("ai_list_chats", null, _store) ?? _store;
                    RenderChats();
                    RenderMessages();
                });
                break;
            }

            case "ai.fail":
            {
                // 同 ai.done：迟到的旧回合收尾不动新回合的状态
                var staleCid = ChatIdOf(ev);
                if (_busy && _runChatId.Length > 0 && staleCid.Length > 0 && staleCid != _runChatId)
                    return;
                // 主动停止不算错：用户点「停止」不该看到红色 error 气泡（对齐 winui3/eziapp/Qt）
                var mine = RunIsDisplayed(ev);
                var quiet = _abandoned;
                _status.Text = ev.Stopped ? "" : ev.Text;
                // 半路断掉的流式气泡也要收成终态：思考块别一直亮着「思考中…」
                if (mine && _streamBubble != null && _stream.Length > 0) _streamBubble.SetText(_stream.ToString());
                if (ev.Stopped)
                {
                    if (mine && _streamBubble != null && _stream.Length == 0) _streamBubble.SetText(L("已停止"));
                    if (!quiet) Toast(L("已停止"), L("可以继续说下一句"));
                }
                else if (mine)
                {
                    if (_streamBubble != null && _stream.Length == 0) _streamBubble.SetText(ev.Text);
                    else Add(new Bubble("error", ev.Text, RetryFrom));
                }
                else
                {
                    // 出错的是已经切走的那条对话：气泡别贴到这边，提示一声就够
                    Toast(L("助手出错"), ev.Text, ToastKind.Error);
                }
                var status = _status.Text;
                ResetRunState();
                _status.Text = status;
                break;
            }

            case "ai.confirm":
                if (!RunIsDisplayed(ev)) return;
                ShowConfirm(ev);
                break;

            case "ai.ask":
                if (!RunIsDisplayed(ev)) return;
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
            case "plan":
                // 3.4 计划卡：模型出的结构化待办直接进对话流
                ShowPlan(ev);
                return;
            case "checkpoint_warn":
            {
                // 快照失败：本轮改动不可回滚，用户必须知道（对齐 Qt 的 InfoBar 告警）
                var wmsg = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("message", out var w)
                    && w.ValueKind == JsonValueKind.String ? w.GetString() ?? "" : "";
                Toast(L("无法一键撤回"),
                    wmsg.Length > 0 ? wmsg : L("检查点不可用，本轮改动无法自动撤回"), ToastKind.Warning);
                return;
            }
            case "model_fallback":
            {
                // 主模型连续 429/5xx 已切备用模型：可见提示，不静默
                var model = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("model", out var mo)
                    && mo.ValueKind == JsonValueKind.String ? mo.GetString() ?? "" : "";
                Toast(L("已切换备用模型"), model, ToastKind.Warning);
                return;
            }
            case "thinking":
                _status.Text = L("思考中…");
                if (_stream.Length == 0) _streamBubble?.SetThinking(L("正在想…"));
                return;
            case "think":
            {
                // 跑完工具继续想：占位提示与 Qt 一致，别一直说「正在想…」
                var afterTools = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("after_tools", out var at)
                    && at.ValueKind == JsonValueKind.True;
                var hint = afterTools ? L("搜完了，正在整理…") : L("正在想…");
                _status.Text = afterTools ? L("搜完了，正在整理…") : L("思考中…");
                if (_stream.Length == 0) _streamBubble?.SetThinking(hint);
                return;
            }
            case "tool":
                if (ev.Name == "ask_user")
                {
                    if (_stream.Length == 0) _streamBubble?.SetText(L("请在下面选一下"));
                    return;
                }
                Line(name, L("准备：") + label, ToolState.Prepare);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_start":
            case "tool_run":
                Line(name, L("执行中：") + label, ToolState.Running);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_done":
            {
                var line = Line(name, L("完成：") + label, ToolState.Done);
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
                Line(name, L("已跳过：") + label, ToolState.Skipped);
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

    /// <summary>6.1 会话累计用量：输入/输出分开；拿不到真实 usage 时标「估算」。</summary>
    private void ShowUsage(BridgeEvent ev)
    {
        if (ev.Payload.ValueKind != JsonValueKind.Object
            || !ev.Payload.TryGetProperty("usage", out var u)
            || u.ValueKind != JsonValueKind.Object)
            return;
        long GetNum(string prop) =>
            u.TryGetProperty(prop, out var n) && n.TryGetInt64(out var v) ? v : 0;
        var est = GetNum("input_estimated");
        var input = GetNum("input") + est;
        var output = GetNum("output");
        if (input == 0 && output == 0) return;
        // 混合来源（有真实回执但本次也含估算）必须标「估算」，不把估算冒充实测
        var real = u.TryGetProperty("real_requests", out var rr) && rr.TryGetInt64(out var r) && r > 0;
        string Fmt(long n) => n >= 1000 ? $"{n / 1000.0:0.0}k" : n.ToString();
        var source = real && est == 0 ? "" : L("（估算）");
        _usageLabel.Text = string.Format(L("本会话：输入 {0} / 输出 {1} tokens{2}"),
            Fmt(input), Fmt(output), source);
    }

    // ==================== 内联计划卡 ====================
    private PlanCard? _planCard;

    private void ShowPlan(BridgeEvent ev)
    {
        var items = new List<(string Title, string Status)>();
        if (ev.Payload.ValueKind == JsonValueKind.Object
            && ev.Payload.TryGetProperty("items", out var arr)
            && arr.ValueKind == JsonValueKind.Array)
        {
            foreach (var it in arr.EnumerateArray())
            {
                if (it.ValueKind != JsonValueKind.Object) continue;
                var title = it.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";
                var status = it.TryGetProperty("status", out var s) ? s.GetString() ?? "pending" : "pending";
                if (!string.IsNullOrWhiteSpace(title)) items.Add((title, status));
            }
        }
        if (items.Count == 0) return;
        if (_planCard != null)
        {
            _messages.Children.Remove(_planCard);
            _planCard = null;
        }
        _planCard = new PlanCard(items);
        Add(_planCard);
    }

    // ==================== 内联确认卡 ====================
    private void ShowConfirm(BridgeEvent ev)
    {
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        var name = ev.Name ?? "";
        var reason = ev.Payload.ValueKind == JsonValueKind.Object
                     && ev.Payload.TryGetProperty("reason", out var rr)
                     && rr.ValueKind == JsonValueKind.String
            ? rr.GetString() ?? "" : "";
        // 变更预览：桥端与 Qt 用同一函数生成 preview.lines，这里逐行展示，两端信息量一致
        var detail = reason ?? "";
        if (ev.Payload.ValueKind == JsonValueKind.Object
            && ev.Payload.TryGetProperty("preview", out var pv)
            && pv.ValueKind == JsonValueKind.Object
            && pv.TryGetProperty("lines", out var pvLines)
            && pvLines.ValueKind == JsonValueKind.Array)
        {
            var lines = new List<string>();
            if (pv.TryGetProperty("head", out var pvHead) && pvHead.ValueKind == JsonValueKind.String)
                lines.Add(pvHead.GetString() ?? "");
            foreach (var line in pvLines.EnumerateArray())
                if (line.ValueKind == JsonValueKind.String) lines.Add(line.GetString() ?? "");
            var preview = string.Join("\n", lines.Where(l => l.Length > 0));
            if (preview.Length > 0)
                detail = string.IsNullOrWhiteSpace(detail) ? preview : preview + "\n" + detail;
        }
        var allowAlways = !string.Equals(name, "delete_instance", StringComparison.Ordinal)
                          && !string.Equals(name, "delete_mod", StringComparison.Ordinal);
        var card = new ConfirmCard(label,
            detail,
            allowAlways,
            (ok, always, scope) =>
                Run(async () => await Api.TryCallAsync<object>("ai_confirm",
                    new { ok, always, scope })));
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

internal sealed class AiPermissionPanel : Border
{
    private static readonly string[] Modes = { "default", "acceptEdits", "plan", "yolo", "custom" };
    private static readonly string[] ModeLabels =
    {
        L("每次确认"), L("写直接执行"), L("只看不动"), L("全自动"), L("自定义")
    };
    private static readonly string[] Tools =
    {
        "ask_user", "create_instance", "delete_instance", "delete_mod", "diagnose_launch",
        "disable_mod", "download_java", "enable_mod", "get_crash_report", "get_java_list",
        "get_latest_log", "get_launcher_state", "inspect_mod", "install_datapack", "install_game",
        "install_mod", "install_modpack", "install_resourcepack", "install_shader", "install_world",
        "launch_game", "list_installed_versions", "list_instances", "list_mod_configs", "list_mods",
        "read_artifact", "read_mod_config", "scan_mod_conflicts", "search_content", "search_modpacks",
        "search_mods", "search_versions", "search_worlds", "write_mod_config"
    };
    private readonly string _instance;
    private readonly ComboBox _mode = Ui.Combo(ModeLabels, width: 170);
    private readonly ComboBox _tool = Ui.Combo(Tools, width: 190);
    private readonly ComboBox _behavior = Ui.Combo(new[] { L("允许"), L("禁止"), L("每次问") }, width: 100);
    private readonly ComboBox _scope = Ui.Combo(new[] { L("所有实例"), L("仅当前实例") }, width: 125);
    private readonly TextBox _content = Ui.Input(L("限定参数（留空 = 整个工具）"));
    private readonly SPanel _rules = Ui.V(6);
    private readonly TextBlock _status = Ui.Small("");
    private readonly TextBlock _usageLabel = Ui.Small("");
    public Action? CloseRequested { get; set; }

    public AiPermissionPanel(string instance)
    {
        _instance = instance;
        var cards = Ui.V(8,
            Ui.Section(L("权限档位"), L("与 Qt 版共用五档权限；自定义规则会覆盖默认判定")),
            Ui.Field(L("当前档位"), _mode, L("点保存后立即对下一轮生效")));
        var saveMode = Ui.Btn(L("保存档位"), BtnKind.Primary, (_, _) => PageBase.Run(SaveModeAsync), Ico.Save);
        var modeRow = Ui.H(8, _mode, saveMode);
        cards.Children.Clear();
        cards.Children.Add(Ui.Section(L("权限档位"), L("与 Qt 版共用五档权限；自定义规则会覆盖默认判定")));
        cards.Children.Add(Ui.Field(L("当前档位"), modeRow, L("点保存后立即对下一轮生效")));

        var add = Ui.Btn(L("添加规则"), BtnKind.Soft, (_, _) => PageBase.Run(AddRuleAsync), Ico.Add);
        var addRow = Ui.G(null, "*,Auto,Auto,Auto,Auto")
            .Add(_tool, 0, 0).Add(_behavior, 0, 1).Add(_content.M(8, 0, 8, 0), 0, 2)
            .Add(_scope, 0, 3).Add(add, 0, 4);
        cards.Children.Add(Ui.Section(L("规则"), L("规则可记到全局或当前实例；删除工具不提供始终允许")));
        cards.Children.Add(addRow);
        cards.Children.Add(_status);
        cards.Children.Add(Ui.Scroll(_rules).Hh(290));
        Child = cards;
        Padding = new Thickness(2);
    }

    public async Task RefreshAsync()
    {
        var settings = await AppServices.Client.TryCallAsync<Dictionary<string, JsonElement>>("get_settings", null, new()) ?? new();
        var mode = settings.TryGetValue("ai_permission_mode", out var raw) && raw.ValueKind == JsonValueKind.String
            ? raw.GetString() ?? "default" : "default";
        var idx = Array.IndexOf(Modes, mode);
        _mode.SelectedIndex = idx >= 0 ? idx : 0;
        await ReloadRulesAsync();
    }

    private async Task SaveModeAsync()
    {
        var idx = Math.Clamp(_mode.SelectedIndex, 0, Modes.Length - 1);
        await AppServices.Client.CallAsync<object>("save_settings", new
        {
            data = new Dictionary<string, object?>
            {
                ["ai_permission_mode"] = Modes[idx],
                ["ai_confirm_writes"] = Modes[idx] != "yolo",
            }
        });
        _status.Text = L("已保存");
    }

    private async Task AddRuleAsync()
    {
        var behavior = new[] { "allow", "deny", "ask" }[Math.Clamp(_behavior.SelectedIndex, 0, 2)];
        var instance = _scope.SelectedIndex == 1 ? _instance : "";
        await AppServices.Client.CallAsync<List<AiPermissionRuleDto>>("ai_permission_rule_add", new
        {
            tool = _tool.Str(), behavior, content = _content.Text.Trim(), instance
        });
        _content.Clear();
        await ReloadRulesAsync();
    }

    private async Task ReloadRulesAsync()
    {
        var rows = await AppServices.Client.TryCallAsync<List<AiPermissionRuleDto>>("ai_permission_rules", null, new()) ?? new();
        _rules.Children.Clear();
        foreach (var row in rows)
        {
            var key = row.Key;
            var scope = string.IsNullOrWhiteSpace(row.Scope) ? L("全局") : row.Scope;
            var detail = $"{scope} · {row.ToolName}"
                         + (string.IsNullOrWhiteSpace(row.RuleContent) ? "" : $" · {row.RuleContent}")
                         + $" · {row.BehaviorLabel}";
            var del = Ui.IconBtn(Ico.Trash, L("删除规则"), (_, _) => PageBase.Run(async () =>
            {
                await AppServices.Client.CallAsync<object>("ai_permission_rule_remove", new { key, instance = row.Instance ?? "" });
                await ReloadRulesAsync();
            }));
            _rules.Children.Add(Ui.G(null, "*,Auto").Add(Ui.Muted(detail).Wrap(), 0, 0).Add(del, 0, 1));
        }
        if (rows.Count == 0) _rules.Children.Add(Ui.Muted(L("还没有自定义规则")));
    }
}

// ======================================================================
/// <summary>
/// 可折叠的思考过程块，与 Qt 端 app/pages/ai_page.py 的 ThinkFold 同款：平时一行收起，点开看全文；
/// 流式期间模型还在想（&lt;think&gt; 没闭合）时自动展开、文字走流光，闭合后自动收起。
/// 标题行照 ZCode 的 Reasoning 行：左 brain 图标，中间文字，右侧 chevron 展开时转 90°。
/// 不折叠的话思考原文会直接铺满气泡，正文被顶到看不见。
/// </summary>
internal sealed class ThinkFold : Border
{
    private readonly TextBlock _label;
    private readonly System.Windows.Shapes.Path _chevron;
    private readonly TextBox _body;
    private bool _open;
    private bool _thinking;

    /// <summary>当前是否展开（默认收起）。</summary>
    public bool IsOpen => _open;
    /// <summary>思考原文（只给面板显示，复制正文时不带）。</summary>
    public string Text => _body.Text;
    /// <summary>标题行此刻的文字（「思考中…」/「思考过程（N）」）；--think-check 用。</summary>
    internal string Header => _label.Text;
    /// <summary>思考原文那块此刻是否展开着；--think-check 用。</summary>
    internal bool BodyShown => _body.Visibility == Visibility.Visible;

    public ThinkFold()
    {
        _label = Ui.Txt("", 12, true, "B.Ink");
        _chevron = Lucide.Icon(Lucide.ChevronRight, 16, "B.InkMuted");
        var head = Ui.G(null, "Auto,*,Auto");
        head.Add(Lucide.Icon(Lucide.Brain, 16, "B.InkMuted").VCenter(), 0, 0);
        head.Add(_label.M(8, 0, 8, 0).VCenter(), 0, 1);
        head.Add(_chevron.VCenter(), 0, 2);
        // 整行可点：Grid 没底色时空白处不吃鼠标，得铺一层透明底
        head.Background = Brushes.Transparent;
        head.Cursor = Cursors.Hand;
        head.MinHeight = 22;
        head.MouseLeftButtonUp += (_, e) => { Toggle(); e.Handled = true; };

        _body = new TextBox
        {
            IsReadOnly = true,
            BorderThickness = new Thickness(0),
            Background = Brushes.Transparent,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 12,
            Padding = new Thickness(0),
            Margin = new Thickness(0, 4, 0, 0),
            Visibility = Visibility.Collapsed,
        };
        _body.SetResourceReference(Control.ForegroundProperty, "B.InkMuted");

        CornerRadius = new CornerRadius(8);
        Padding = new Thickness(10, 5, 10, 6);
        BorderThickness = new Thickness(1);
        SetResourceReference(BackgroundProperty, "B.Hover");
        SetResourceReference(BorderBrushProperty, "B.Line");
        Child = Ui.V(0, head, _body);
        SyncHead();
    }

    public void Toggle() => SetOpen(!_open);

    public void SetOpen(bool on)
    {
        if (_open == on)
        {
            SyncHead();
            return;
        }
        _open = on;
        _body.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
        SyncHead();
    }

    /// <summary>live = 整条消息还在流式；open = 思考块还没闭合（模型仍在想）。</summary>
    public void SetThink(string text, bool live, bool open)
    {
        _thinking = live && open;
        _body.Text = text ?? "";
        SetOpen(open);
    }

    private void SyncHead()
    {
        var n = _body.Text.Length;
        _label.Text = _thinking
            ? L("思考中…")
            : L("思考过程") + (n > 0 ? L("（") + n + L("）") : "");
        Lucide.Shimmer(_label, _thinking, "B.Ink");
        Lucide.Rotate(_chevron, _open);
    }
}

// ======================================================================
/// <summary>一条消息。助手 / 出错的消息带「复制」，用户的消息带「重发」。</summary>
internal sealed class Bubble : Border
{
    private readonly TextBox _body;
    private readonly SPanel _thinking;
    private readonly TextBlock _thinkingLabel;
    private readonly ThinkFold? _think;
    private readonly bool _mine;
    private string _plain;
    // 去掉 <think> 块之后的正文：复制拿的是它，不把推理原文一起贴进 issue
    private string _answer;

    // ---- 只给 --think-check（Shell/ThinkCheck.cs）量状态用，界面代码别拿 ----
    internal ThinkFold? Think => _think;
    internal string Answer => _answer;
    internal string BodyText => _body.Text;
    internal bool BodyShown => _body.Visibility == Visibility.Visible;

    /// <summary>
    /// 把 &lt;think&gt;…&lt;/think&gt; 块从回复里摘出来（与 Qt 端 _split_think 同一套规则）。
    /// 流式期间可能只有开头没有收尾（模型还在想），这种情况把未闭合块整体算作思考内容、
    /// 答案为空；收尾出现后答案从 &lt;/think&gt; 之后起算。标签大小写不敏感。
    /// </summary>
    internal static (List<string> Parts, string Answer) SplitThink(string? text)
    {
        var parts = new List<string>();
        var answer = new System.Text.StringBuilder();
        var rest = text ?? "";
        while (true)
        {
            var i = rest.IndexOf("<think>", StringComparison.OrdinalIgnoreCase);
            if (i < 0) break;
            answer.Append(rest, 0, i);
            var j = rest.IndexOf("</think>", i + 7, StringComparison.OrdinalIgnoreCase);
            if (j < 0)
            {
                parts.Add(rest[(i + 7)..]);
                rest = "";
                break;
            }
            parts.Add(rest[(i + 7)..j]);
            rest = rest[(j + 8)..];
        }
        answer.Append(rest);
        return (parts, answer.ToString().Trim());
    }

    /// <summary>思考块还没闭合：开头比收尾多。</summary>
    private static bool ThinkOpen(string text)
    {
        static int Count(string s, string tag)
        {
            int n = 0, at = 0;
            while ((at = s.IndexOf(tag, at, StringComparison.OrdinalIgnoreCase)) >= 0) { n++; at += tag.Length; }
            return n;
        }
        return Count(text, "<think>") > Count(text, "</think>");
    }

    public Bubble(string role, string text, Action<string> resend)
    {
        _plain = text ?? "";
        _answer = _plain;
        var mine = _mine = role == "user";
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

        // 「正在想…」占位行：brain 图标 + 流光文字（ZCode 的思考行），一有正文就换回 _body
        _thinkingLabel = Ui.Txt("", 13, true, "B.Ink");
        _thinking = Ui.H(8, Lucide.Icon(Lucide.Brain, 16, "B.InkMuted").VCenter(), _thinkingLabel.VCenter());
        _thinking.Visibility = Visibility.Collapsed;
        // 思考折叠只有助手 / 出错的消息才会有；用户自己的话原样显示
        if (!mine) _think = new ThinkFold { Visibility = Visibility.Collapsed };

        var who = Ui.Small(mine ? L("我") : err ? L("出错") : L("助手"));
        if (mine) who.SetResourceReference(TextBlock.ForegroundProperty, "B.OnAccent");
        var head = Ui.G(null, "*,Auto");
        head.Add(err ? Ui.H(5, Lucide.Icon(Lucide.CircleX, 13, "B.Danger").VCenter(), who.VCenter()) : who.VCenter(), 0, 0);

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
        Child = Ui.V(4, head, _thinking, _think, _body);
        SetResourceReference(BackgroundProperty, mine ? "B.Accent" : err ? "B.DangerSoft" : "B.Paper2");
        if (err)
        {
            BorderThickness = new Thickness(1);
            SetResourceReference(BorderBrushProperty, "B.Danger");
        }
        // 历史重载也走同一条路：存过的回复里带 <think> 一样折起来
        Render(live: false);
    }

    /// <summary>live = 还在流式：思考块没闭合时展开并走流光，正文就地追加。</summary>
    public void SetText(string text, bool live = false)
    {
        _plain = text ?? "";
        if (_thinking.Visibility == Visibility.Visible)
        {
            Lucide.Shimmer(_thinkingLabel, false, "B.Ink");
            _thinking.Visibility = Visibility.Collapsed;
            _body.Visibility = Visibility.Visible;
        }
        Render(live);
    }

    /// <summary>把 _plain 拆成思考块 + 正文铺到界面上；用户的消息不拆。</summary>
    private void Render(bool live)
    {
        if (_mine || _think is null)
        {
            _answer = _plain;
            _body.Text = _plain;
            return;
        }
        var (parts, answer) = SplitThink(_plain);
        _answer = answer;
        if (parts.Count > 0)
        {
            var open = ThinkOpen(_plain);
            _think.SetThink(string.Join("\n\n", parts.Select(p => p.Trim()).Where(p => p.Length > 0)),
                            live, live && open);
            _think.Visibility = Visibility.Visible;
            // 模型还在想、正文一个字没有：别让空文本框在思考块下面撑出一行空白
            _body.Visibility = live && answer.Length == 0 ? Visibility.Collapsed : Visibility.Visible;
            _body.Text = !live && answer.Length == 0 ? "…" : answer;
            return;
        }
        _think.Visibility = Visibility.Collapsed;
        if (_thinking.Visibility != Visibility.Visible) _body.Visibility = Visibility.Visible;
        _body.Text = answer;
    }

    /// <summary>还没有正文时的「正在想…」：整条气泡只剩 brain + 流光一行。</summary>
    public void SetThinking(string text)
    {
        _plain = "";
        _answer = "";
        _body.Text = "";
        _thinkingLabel.Text = text ?? "";
        _thinking.Visibility = Visibility.Visible;
        _body.Visibility = Visibility.Collapsed;
        if (_think != null) _think.Visibility = Visibility.Collapsed;
        Lucide.Shimmer(_thinkingLabel, true, "B.Ink");
    }

    private void Copy()
    {
        try
        {
            // 只拷正文：思考原文留在折叠块里
            Clipboard.SetText(string.IsNullOrEmpty(_answer) ? _plain : _answer);
            AppServices.Toast(L("已复制"), "", ToastKind.Success);
        }
        catch { }
    }
}

internal enum ToolState { Prepare, Running, Done, Skipped, Failed }

/// <summary>
/// 对话流里的一行工具执行状态；绑上任务后带进度条。
/// 左侧图标照 ZCode 的工具行：搜索 / 读文件 / 改文件三类工具在准备、执行时显示类型图标，
/// 其余工具显示旋转的 loader；结束后统一换成 circle-check / circle-slash-2 / circle-x。执行中文字走流光。
/// </summary>
internal sealed class ToolLine : Border
{
    private readonly TextBlock _label;
    private readonly ProgressBar _bar;
    private readonly ContentControl _icon = new() { Width = 16, Height = 16, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 1, 0, 0) };
    private readonly string? _typeIcon;
    private ToolState _state = ToolState.Prepare;

    public ToolLine(string text, string? tool = null)
    {
        _typeIcon = Lucide.ToolIcon(tool);
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
        var row = Ui.G(null, "Auto,*");
        row.Add(_icon, 0, 0);
        row.Add(_label.M(8, 0, 0, 0), 0, 1);
        Child = Ui.V(4, row, _bar);
        SyncIcon();
    }

    public void SetText(string text) => _label.Text = text;

    public void SetState(ToolState state)
    {
        if (_state == state) return;
        _state = state;
        SyncIcon();
    }

    private void SyncIcon()
    {
        var running = _state is ToolState.Prepare or ToolState.Running;
        Lucide.Shimmer(_label, running, "B.AccentDeep");
        _icon.Content = _state switch
        {
            ToolState.Prepare or ToolState.Running when _typeIcon != null => Lucide.Icon(_typeIcon, 16, "B.AccentDeep"),
            ToolState.Prepare or ToolState.Running => Lucide.Spinner(16, "B.AccentDeep"),
            ToolState.Done => Lucide.Icon(Lucide.CircleCheck, 16, "B.AccentDeep"),
            ToolState.Skipped => Lucide.Icon(Lucide.CircleSlash2, 16, "B.InkMuted"),
            _ => Lucide.Icon(Lucide.CircleX, 16, "B.Danger"),
        };
    }

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
        SetState(success ? ToolState.Done : ToolState.Failed);
        _label.SetResourceReference(TextBlock.ForegroundProperty, success ? "B.AccentDeep" : "B.Danger");
    }
}

/// <summary>内联确认卡，替掉原来的模态框：连着问几轮也只是往下长几张卡。</summary>
/// <summary>
/// 计划卡（批次 3.4）：模型出的结构化待办清单，每项带 待办 / 进行中 / 完成 状态。
/// </summary>
internal sealed class PlanCard : Border
{
    public PlanCard(List<(string Title, string Status)> items)
    {
        var mark = new Dictionary<string, string>
        {
            ["pending"] = L("待办"),
            ["in_progress"] = L("进行中"),
            ["completed"] = L("完成"),
        };
        var body = Ui.V(4, Ui.Txt(L("计划"), 12, true, "B.InkMuted"));
        foreach (var (title, status) in items)
        {
            var tag = mark.TryGetValue(status, out var m) ? m : L("待办");
            body.Children.Add(Ui.Txt($"[{tag}] {title}", 12.5).Wrap());
        }
        Child = body;
        Padding = new Thickness(12, 8, 12, 9);
        BorderThickness = new Thickness(1);
        CornerRadius = new CornerRadius(10);
        MaxWidth = 760;
        HorizontalAlignment = HorizontalAlignment.Stretch;
    }
}

internal sealed class ConfirmCard : Border
{    public ConfirmCard(string label, string detail, bool allowAlways,
        Action<bool, bool, string> answer)
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
        var yes = Ui.Btn(L("允许"), BtnKind.Primary, null, Ico.Check);
        var always = Ui.Btn(L("始终允许"), BtnKind.Chip, null, Ico.Check);
        var no = Ui.Btn(L("拒绝"));
        var scope = Ui.Combo(new[] { L("仅当前实例"), L("所有实例") }, width: 120);
        always.Visibility = allowAlways ? Visibility.Visible : Visibility.Collapsed;
        scope.Visibility = allowAlways ? Visibility.Visible : Visibility.Collapsed;
        body.Children.Add(Ui.H(8, yes, always, scope, no));

        void Done(bool ok, bool remember)
        {
            yes.IsEnabled = always.IsEnabled = no.IsEnabled = false;
            scope.IsEnabled = false;
            body.Children.Add(Ui.Small(ok ? (remember ? L("已记住并允许") : L("已允许")) : L("已拒绝")));
            answer(ok, remember, scope.SelectedIndex == 1 ? "global" : "instance");
        }
        yes.Click += (_, _) => Done(true, false);
        always.Click += (_, _) => Done(true, true);
        no.Click += (_, _) => Done(false, false);

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
