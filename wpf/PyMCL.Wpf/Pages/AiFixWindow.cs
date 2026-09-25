using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Shell;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// 崩溃弹窗的「交给 AI 修复」小窗：打开即把崩溃报告喂给 AI 助手诊断，对话流
/// （流式回复 / 工具行 / 确认卡 / 提问卡）就地展示，与 Qt 端
/// app/pages/ai_fix_dialog.py 同一套行为。
/// 为什么是独立小窗而不是 Dlg 遮罩层：崩溃弹窗本身还开在主窗遮罩上，用户要能
/// 同时看两边；气泡 / 工具行 / 确认卡直接复用 AiPage.cs 里的 internal 组件。
/// 走桥的同一条 ai_send 单回合通道，用独立 chat_id（fix-时间戳）：桥照常落盘，
/// 主 AI 页按 chat_id 分流不会把这里的流式字画进它正看着的对话。
/// </summary>
internal sealed class AiFixWindow : Window
{
    private readonly CrashReport _report;
    private readonly SPanel _messages = Ui.V(12);
    private readonly SmoothScroll _scroll;
    private readonly ChatInput _input = new();
    private readonly Button _send;    private readonly TextBlock _status = Ui.Small("");
    private readonly StringBuilder _stream = new();   // 整回合累积
    private readonly StringBuilder _round = new();    // 当前轮次已说的话
    private readonly Dictionary<string, ToolLine> _toolLines = new();
    private readonly Dictionary<string, ToolLine> _taskLines = new();
    private Bubble? _roundBubble;   // 当前轮次的气泡：工具回合开始就封口换新
    private PlanCard? _planCard;
    private bool _busy;
    private bool _kicked;
    private readonly string _chatId;

    public AiFixWindow(CrashReport report)
    {
        _report = report;
        _chatId = $"fix-{DateTime.Now:yyyyMMddHHmmss}";
        Title = L("AI 修复");
        Width = 520;
        Height = 660;
        MinWidth = 430;
        MinHeight = 480;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.CanResize;
        UseLayoutRounding = true;
        SetResourceReference(BackgroundProperty, "B.Canvas");
        SetResourceReference(BorderBrushProperty, "B.Line");
        BorderThickness = new Thickness(1);

        var chrome = new WindowChrome
        {
            CaptionHeight = 40,
            ResizeBorderThickness = new Thickness(6),
            GlassFrameThickness = new Thickness(0),
            CornerRadius = new CornerRadius(0),
            UseAeroCaptionButtons = false,
        };
        WindowChrome.SetWindowChrome(this, chrome);

        // 标题栏：同 MainWindow 的做法（WindowChrome 拖拽 + 关闭钮单独命中）
        var close = new Button { Style = Ui.S("Btn.CaptionClose"), Content = "\uE8BB" };
        close.Click += (_, _) => Close();
        WindowChrome.SetIsHitTestVisibleInChrome(close, true);
        var bar = Ui.G(null, "*,Auto")
            .Add(Ui.Txt(Title, 13.5, true, "B.Ink").M(14, 0, 0, 0).VCenter(), 0, 0)
            .Add(close, 0, 1);
        var titleBar = new Border
        {
            Height = 40,
            Child = bar,
        };
        titleBar.SetResourceReference(BackgroundProperty, "B.Chrome");
        titleBar.SetResourceReference(BorderBrushProperty, "B.LineSoft");
        titleBar.BorderThickness = new Thickness(0, 0, 0, 1);

        _send = Ui.Btn(L("发送"), BtnKind.Primary, OnMainButtonClick, Ico.Send);
        _input.Tag = L("补充崩溃前做了什么、装了什么…  Enter 发送，Shift+Enter 换行");
        _input.Submitted += text => PageBase.Run(() => SendTextAsync(text));
        // 停止入口合并进发送键（跑动中变形为「停止」），头部不再单设按钮
        _input.TextChanged += (_, _) => SyncMainButton();
        _scroll = Ui.Scroll(_messages.M(4, 4, 10, 4));

        var inputCard = Ui.Card(Ui.V(6, _status, Ui.H(8, _input, _send)), 12);
        var root = Ui.G("Auto,*,Auto")
            .Add(titleBar, 0, 0)
            .Add(Ui.Card(_scroll, 10).M(12, 10, 12, 4), 1, 0)
            .Add(inputCard.M(12, 0, 12, 12), 2, 0);
        Content = root;
        SyncMainButton();

        Loaded += (_, _) => PageBase.Run(KickOffAsync);
        AppServices.Client.EventReceived += OnBridgeEvent;
    }

    /// <summary>开窗即跑：用户气泡只放这句短问话，崩溃报告走隐藏 context 注入。</summary>
    private Task KickOffAsync()
    {
        if (_kicked) return Task.CompletedTask;
        _kicked = true;
        return SendTextAsync(L("帮我看看游戏为什么闪退"));
    }

    /// <summary>当前接口的人话描述（公益 / 自定义 + 模型名），从桥设置取。</summary>
    private async Task<string> InterfaceLabelAsync()
    {
        var settings = await AppServices.Client.TryCallAsync<Dictionary<string, JsonElement>>(
            "get_settings", null, new Dictionary<string, JsonElement>()) ?? new();
        var mode = settings.TryGetValue("ai_mode", out var mraw) && mraw.ValueKind == JsonValueKind.String
            ? mraw.GetString() ?? "public" : "public";
        if (mode != "custom") return L("公益接口（免费网关）");
        var model = settings.TryGetValue("ai_model", out var mod) && mod.ValueKind == JsonValueKind.String
            ? mod.GetString() ?? "" : "";
        return string.Format(L("自定义接口（{0}）"), model.Length > 0 ? model : L("未命名模型"));
    }

    /// <summary>把崩溃报告压成一段隐藏的系统提示注入文本（与 Qt build_crash_context 同一段话术）。</summary>
    internal static string BuildCrashContext(CrashReport r, string iface)
    {
        static string Clip(string? s, int n)
        {
            var t = (s ?? "").Trim();
            return t.Length <= n ? t : t.Substring(0, n) + L("…（已截断）");
        }
        var rows = new List<string> { L("【启动器注入 · 对用户不可见】本次对话的崩溃上下文：") };
        var ctx = new List<string>();
        if (!string.IsNullOrWhiteSpace(r.Instance)) ctx.Add(string.Format(L("实例：{0}"), r.Instance));
        if (!string.IsNullOrWhiteSpace(r.Version)) ctx.Add(string.Format(L("版本：{0}"), r.Version));
        if (r.ExitCode is { } code)
        {
            var hint = string.IsNullOrWhiteSpace(r.ExitHint) ? "" : string.Format(L("（{0}）"), r.ExitHint);
            ctx.Add(string.Format(L("退出码：{0}{1}"), code, hint));
        }
        if (ctx.Count > 0) rows.Add(string.Join("\n", ctx));
        foreach (var (value, label, clip) in new[]
                 {
                     (r.Headline, L("现象"), 400),
                     (r.Summary, L("摘要"), 600),
                     (r.Detail, L("详细信息"), 4000),
                 })
        {
            var text = Clip(value, clip);
            if (text.Length > 0) rows.Add(label + L("：") + "\n" + text);
        }
        if (!string.IsNullOrWhiteSpace(r.DirectFile))
            rows.Add(string.Format(L("完整日志文件：{0}"), r.DirectFile));
        rows.Add(L("日志自查提醒：上面的日志只是截断摘录。你带有读取日志和检查实例的工具（get_latest_log、get_crash_report、read_artifact、inspect_mod、list_mods 等），请主动调用工具读取完整日志核实原因，不要以「没有日志」「无法访问日志」为由拒绝分析。"));
        rows.Add(string.Format(L("接口状态：当前对话通过启动器内置的{0}接入，接口正常可用。不要声称「没有配置接口 / 接口不可用」。"), iface));
        rows.Add(L("如果问题能通过改配置、禁用模组等方式修复，请直接动手（写操作会先征求我同意）；需要更多上下文就自己读日志文件。边查边说：有阶段性发现或换步骤时，先用一两句话告诉我，再继续调用工具。最后用一句话给我结论和下一步建议。"));
        return string.Join("\n\n", rows);
    }

    // ==================== 发送 / 停止（单按钮变形） ====================

    /// <summary>输入框有字 = 发送（跑动中点了进 steering 队列）；空且在跑 = 停止。</summary>
    private void OnMainButtonClick(object sender, RoutedEventArgs e)
    {
        var text = _input.Text?.Trim() ?? "";
        if (text.Length > 0)
        {
            PageBase.Run(() => SendTextAsync(text));
            return;
        }
        if (_busy) PageBase.Run(StopAsync);
    }

    /// <summary>按钮在「发送 / 停止」之间变形，状态统一由 SyncMainButton 计算。</summary>
    private void SyncMainButton()
    {
        var hasText = !string.IsNullOrWhiteSpace(_input.Text);
        var stopMode = _busy && !hasText;
        _send.Content = Ui.H(6, Ui.Glyph(stopMode ? Ico.Stop : Ico.Send, 13),
            Ui.Txt(stopMode ? L("停止") : L("发送"), 13));
        _send.IsEnabled = hasText || _busy;
    }

    private void RetryFrom(string text) => PageBase.Run(() => SendTextAsync(text));

    private async Task SendTextAsync(string raw)
    {
        var text = (raw ?? "").Trim();
        if (text.Length == 0) return;
        if (_busy)
        {
            // 跑动中的插话走 steering：下一轮模型请求前被采纳（对齐 Qt 的排队）。
            // 桥回 ok=false 说明刚好收尾了：落回普通 ai_send。
            var sr = await AppServices.Client.TryCallAsync<JsonElement>("ai_steer", new { text });
            var queued = sr.ValueKind == JsonValueKind.Object
                         && sr.TryGetProperty("ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
            if (queued)
            {
                _input.Clear();
                Add(new Bubble("user", text, RetryFrom));
                _status.Text = L("已插队") + " · " + L("这句话会立刻交给正在运行的助手");
                SyncMainButton();
                return;
            }
        }
        _input.Clear();
        SetBusy(true);
        _status.Text = L("思考中…");

        Add(new Bubble("user", text, RetryFrom));
        _stream.Clear();
        _roundBubble = OpenRound();

        var launch = new Dictionary<string, object?>
        {
            ["instance"] = _report.Instance ?? "",
            ["username"] = AppServices.Window?.Prefs.LastUser ?? "",
        };
        // 崩溃报告从隐藏 context 注入（桥端转成 ai_extra_context 系统提示），每次
        // 发送都带上：后续追问时上下文仍然在场；不入库、用户气泡里看不到
        var context = BuildCrashContext(_report, await InterfaceLabelAsync());
        var r = await AppServices.Client.TryCallAsync<OpResult>("ai_send",
            new { text, chat_id = _chatId, launch, context });
        if (r is null || !r.Ok)
        {
            // 调用没到后端（r 为空）或被拒（例如主 AI 页还有一回合在跑）：这一回合
            // 根本没开始，不会再有 ai.done / ai.fail 来复位，这里必须把按钮放回去
            var msg = r?.Message is { Length: > 0 } m ? m : L("后端没有响应，请稍后再试");
            if (_roundBubble != null) _messages.Children.Remove(_roundBubble);
            Add(new Bubble("error", msg, RetryFrom));
            ResetRunState();
            _status.Text = msg;
        }
    }

    private async Task StopAsync()
    {
        var r = await AppServices.Client.TryCallAsync<JsonElement>("ai_stop");
        // 后端根本没有回合在跑（或压根没应答）：不会再有 ai.fail 来复位，当场收
        if (r.ValueKind != JsonValueKind.Object
            || !r.TryGetProperty("busy", out var b) || b.ValueKind != JsonValueKind.True)
            ResetRunState();
        _status.Text = L("已停止");
    }

    private void SetBusy(bool on)
    {
        _busy = on;
        SyncMainButton();
    }

    private void ResetRunState()
    {
        _roundBubble = null;
        _planCard = null;
        _round.Clear();
        _stream.Clear();
        _status.Text = "";
        SetBusy(false);
    }

    /// <summary>开一个新的轮次气泡：模型每次「开口」都有自己的一段（对齐 AiPage）。</summary>
    private Bubble OpenRound(string? thinking = null)
    {
        _round.Clear();
        var b = new Bubble("assistant", "…", RetryFrom);
        b.SetThinking(thinking ?? L("正在想…"));
        Add(b);
        return b;
    }

    /// <summary>把当前轮次已说的话定稿在它自己的气泡里（工具行从此插在下面）。</summary>
    private void CloseRound()
    {
        if (_roundBubble is null) return;
        _roundBubble.SetText(_round.ToString());
        _roundBubble = null;
        _round.Clear();
    }

    // ==================== 事件 ====================
    private void OnBridgeEvent(object? sender, BridgeEvent ev)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(() => OnBridgeEvent(sender, ev));
            return;
        }
        switch (ev.Event)
        {
            case "ai.delta":
                if (!Mine(ev)) return;
                // 整回合累积 + 轮内分段：模型在工具之间开口时自动开新气泡
                _stream.Append(ev.Text);
                _round.Append(ev.Text);
                _roundBubble ??= OpenRound();
                _roundBubble.SetText(_round.ToString(), live: true);
                ScrollDown();
                break;

            case "ai.status":
                if (Mine(ev)) OnStatus(ev);
                break;

            case "ai.confirm":
                if (Mine(ev)) ShowConfirm(ev);
                break;

            case "ai.ask":
                if (Mine(ev)) ShowAsk(ev);
                break;

            case "ai.done":
            {
                if (!Mine(ev)) return;
                var note = StopNote(ev);
                // 最后一轮先封口，再把「为什么停」的增量补在末尾（无话时单开一条）
                if (_round.Length == 0 && note.Length > 0) OpenRound();
                if (_round.Length > 0 || _roundBubble != null)
                {
                    var finalText = _round.ToString();
                    if (note.Length > 0 && !finalText.Contains(note))
                        finalText = finalText.Length > 0 ? finalText + "\n\n" + note : note;
                    _roundBubble!.SetText(finalText);
                }
                ResetRunState();
                break;
            }

            case "ai.fail":
            {
                if (!Mine(ev)) return;
                // 主动停止不算错：不该看到红色 error 气泡（对齐 AiPage）
                if (_round.Length > 0) _roundBubble?.SetText(_round.ToString());
                else if (ev.Stopped) _roundBubble?.SetText(L("已停止"));
                else if (_roundBubble != null) _roundBubble.SetText(ev.Text);
                else Add(new Bubble("error", ev.Text, RetryFrom));
                ResetRunState();
                break;
            }

            // AI 起的下载：进度直接画在对话流那一行上
            case "progress" when _taskLines.TryGetValue(ev.TaskId, out var pl):
                pl.SetProgress(ev.Current, ev.Total, ev.Message);
                break;
            case "finished" when _taskLines.TryGetValue(ev.TaskId, out var fl):
                fl.Finish(ev.Success, ev.Message);
                break;
        }
    }

    /// <summary>事件是不是这个窗口那一回合的：有 chat_id 就比对，没有（旧版桥）按
    /// 「本窗正忙就是我的」处理——桥同时只有一个回合，本窗不忙时一律别抢。</summary>
    private bool Mine(BridgeEvent ev)
    {
        var cid = ChatIdOf(ev);
        return cid.Length > 0 ? cid == _chatId : _busy;
    }

    private static string ChatIdOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("chat_id", out var c) && c.ValueKind == JsonValueKind.String
            ? c.GetString() ?? "" : "";

    private void Add(UIElement el)
    {
        _messages.Children.Add(el);
        Motion.FadeIn(el, 200, 8);
        ScrollDown();
    }

    private void ScrollDown() => Dispatcher.BeginInvoke(() => _scroll.ScrollToEnd());

    // ==================== 状态 / 工具行（照 AiPage 同名逻辑裁剪） ====================
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

    private void OnStatus(BridgeEvent ev)
    {
        var name = string.IsNullOrEmpty(ev.Name) ? ev.Kind : ev.Name;
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        switch (ev.Kind)
        {
            case "plan":
                ShowPlan(ev);
                return;
            case "checkpoint_warn":
            {
                var wmsg = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("message", out var w)
                    && w.ValueKind == JsonValueKind.String ? w.GetString() ?? "" : "";
                _status.Text = wmsg.Length > 0 ? wmsg : L("检查点不可用，本轮改动无法自动撤回");
                return;
            }
            case "model_fallback":
            {
                var model = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("model", out var mo)
                    && mo.ValueKind == JsonValueKind.String ? mo.GetString() ?? "" : "";
                _status.Text = L("已切换备用模型") + (model.Length > 0 ? " · " + model : "");
                return;
            }
            case "thinking":
                _status.Text = L("思考中…");
                if (_round.Length == 0) OpenRound();
                return;
            case "think":
            {
                var afterTools = ev.Payload.ValueKind == JsonValueKind.Object
                    && ev.Payload.TryGetProperty("after_tools", out var at)
                    && at.ValueKind == JsonValueKind.True;
                _status.Text = afterTools ? L("搜完了，正在整理…") : L("思考中…");
                if (_round.Length == 0) OpenRound(afterTools ? L("搜完了，正在整理…") : L("正在想…"));
                return;
            }
            case "tool":
                if (ev.Name == "ask_user")
                {
                    if (_round.Length == 0) OpenRound(L("请在下面选一下"));
                    return;
                }
                // 工具要开工了：这一轮说的话就地定稿，工具行插在它下面
                CloseRound();
                Line(name, L("准备：") + label, ToolState.Prepare);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_start":
            case "tool_run":
                CloseRound();
                Line(name, L("执行中：") + label, ToolState.Running);
                _status.Text = L("正在执行操作…");
                return;
            case "tool_done":
            {
                CloseRound();
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
                CloseRound();
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

    private static string StopReasonOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("stop_reason", out var r) && r.ValueKind == JsonValueKind.String
            ? r.GetString() ?? "" : "";

    private static string DetailOf(BridgeEvent ev) =>
        ev.Payload.ValueKind == JsonValueKind.Object
        && ev.Payload.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String
            ? d.GetString() ?? "" : "";

    /// <summary>与 AiPage / Qt `_stop_note` 同一张词表：completed 等不打扰，其余挂气泡末尾。</summary>
    private static string StopNote(BridgeEvent ev)
    {
        var note = StopReasonOf(ev) switch
        {
            "no_tool_call" => L("它没有真的开始执行：模型只回了文字，没有调用任何工具。"),
            "max_rounds" => L("步骤太多，先停在这里。你可以让我继续。"),
            "pending_task" => L("下载/安装还在后台跑，完成后助手会回来汇报。"),
            "stream_failed" => L("接口这轮没有返回内容，已停止。"),
            "empty_response" => L("接口返回了空回复。"),
            _ => "",
        };
        if (note.Length == 0) return "";
        var detail = DetailOf(ev);
        if (detail.Length > 0 && !note.Contains(detail)) note += L("（") + detail + L("）");
        return L("（提示：") + note + L("）");
    }

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

    // ==================== 内联确认卡 / 提问卡 ====================
    private void ShowConfirm(BridgeEvent ev)
    {
        // 确认卡落在最后一段话下面：先把手头这段话封口
        CloseRound();
        var label = string.IsNullOrWhiteSpace(ev.Label) ? ev.Name : ev.Label;
        var name = ev.Name ?? "";
        var reason = ev.Payload.ValueKind == JsonValueKind.Object
                     && ev.Payload.TryGetProperty("reason", out var rr)
                     && rr.ValueKind == JsonValueKind.String
            ? rr.GetString() ?? "" : "";
        // 变更预览：桥端与 Qt 用同一函数生成 preview.lines，逐行展示
        var detail = reason;
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
        var card = new ConfirmCard(label, detail, allowAlways,
            (ok, always, scope) => PageBase.Run(async () =>
                await AppServices.Client.TryCallAsync<object>("ai_confirm", new { ok, always, scope })));
        Add(card);
        _status.Text = L("等你确认");
    }

    private void ShowAsk(BridgeEvent ev)
    {
        // 提问卡落在最后一段话下面：先把手头这段话封口
        CloseRound();
        if (ev.Payload.ValueKind != JsonValueKind.Object ||
            !ev.Payload.TryGetProperty("questions", out var qs) || qs.ValueKind != JsonValueKind.Array)
        {
            PageBase.Run(async () =>
                await AppServices.Client.TryCallAsync<object>("ai_answer", new { result = (object?)null }));
            return;
        }
        var title = ev.Payload.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";
        var card = new AskCard(title, qs, result =>
            PageBase.Run(async () =>
                await AppServices.Client.TryCallAsync<object>("ai_answer", new { result })));
        Add(card);
        _status.Text = L("等你回答");
    }

    protected override void OnClosed(EventArgs e)
    {
        AppServices.Client.EventReceived -= OnBridgeEvent;
        if (_busy)
        {
            // 窗关了回合别留在后台空转：代答停止（发完就算，不等回执）
            _ = AppServices.Client.TryCallAsync<JsonElement>("ai_stop");
        }
        base.OnClosed(e);
    }
}
