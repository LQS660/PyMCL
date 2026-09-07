using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PyMCL.Models;

namespace PyMCL.Services;

public sealed class BridgeClient : IDisposable
{
    public const string TokenHeader = "X-PyMCL-Bridge-Token";
    private static readonly JsonSerializerOptions JsonOpt = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;
    private readonly CancellationTokenSource _cts = new();
    private readonly string _token;
    private int _id;
    private int _disposed;

    public Uri BaseUri { get; }
    public event EventHandler<BridgeEvent>? EventReceived;

    /// <summary>SSE 连接状态变化（true=已连上事件流）。断线期间进度/完成/角标全部收不到，界面需要据此提示。</summary>
    public event EventHandler<bool>? EventStreamStateChanged;

    public bool EventStreamConnected { get; private set; }

    public BridgeClient(Uri baseUri, string token)
    {
        if (baseUri.Scheme != Uri.UriSchemeHttp || baseUri.Host != "127.0.0.1" || baseUri.Port is < 1 or > 65535)
            throw new ArgumentException("Bridge URI must use the local loopback HTTP endpoint.", nameof(baseUri));
        if (string.IsNullOrWhiteSpace(token) || token.Length < 32)
            throw new ArgumentException("Bridge token is missing or too short.", nameof(token));
        BaseUri = baseUri;
        _token = token;
        _http = new HttpClient { BaseAddress = baseUri, Timeout = TimeSpan.FromMinutes(10) };
        _http.DefaultRequestHeaders.TryAddWithoutValidation(TokenHeader, _token);
    }

    public async Task ConnectEventsAsync()
    {
        _ = Task.Run(ReadSseLoop);
        await Task.CompletedTask;
    }

    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
    {
        using var resp = await _http.GetAsync("/health", ct).ConfigureAwait(false);
        return resp.IsSuccessStatusCode;
    }

    public async Task<JsonElement> CallAsync(string method, object? args = null, CancellationToken ct = default)
    {
        var id = Interlocked.Increment(ref _id);
        var payload = new Dictionary<string, object?>
        {
            ["jsonrpc"] = "2.0",
            ["id"] = id,
            ["method"] = method,
            ["params"] = args ?? new Dictionary<string, object?>(),
        };
        using var content = new StringContent(JsonSerializer.Serialize(payload, JsonOpt), Encoding.UTF8, "application/json");
        using var resp = await _http.PostAsync("/rpc", content, ct).ConfigureAwait(false);
        var text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text);
        var root = doc.RootElement.Clone();
        if (root.TryGetProperty("error", out var err) && err.ValueKind != JsonValueKind.Null)
        {
            var msg = err.TryGetProperty("message", out var m) ? m.GetString() : err.ToString();
            throw new InvalidOperationException(msg);
        }
        if (root.TryGetProperty("result", out var result))
            return result.Clone();
        return default;
    }

    public async Task<T?> CallAsync<T>(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        if (el.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
            return default;
        return JsonSerializer.Deserialize<T>(el.GetRawText(), JsonOpt);
    }

    public async Task<string> StartTaskAsync(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        if (el.ValueKind == JsonValueKind.String)
            return el.GetString() ?? "";
        return el.ToString();
    }

    /// <summary>
    /// 事件流读取 + 自动重连。以前读到流结束或抛异常就直接退出方法，此后进度、完成、
    /// 角标、AI 流式全部静默失效，而界面上没有任何迹象——只能重开整个应用。
    /// 现在按 1s→2s→…→15s 退避无限重连，与 Web 端行为一致。
    /// </summary>
    private async Task ReadSseLoop()
    {
        var attempt = 0;
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                await ReadSseOnceAsync().ConfigureAwait(false);
                attempt = 0;
            }
            catch (OperationCanceledException) { break; }
            catch { /* 掉线，走下面的退避重连 */ }
            finally
            {
                SetEventStreamState(false);
            }

            if (_cts.IsCancellationRequested) break;
            attempt = Math.Min(attempt + 1, 5);
            var delay = TimeSpan.FromSeconds(Math.Min(1 << (attempt - 1), 15));
            try { await Task.Delay(delay, _cts.Token).ConfigureAwait(false); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task ReadSseOnceAsync()
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, "/events");
        req.Headers.TryAddWithoutValidation(TokenHeader, _token);
        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, _cts.Token).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();
        await using var stream = await resp.Content.ReadAsStreamAsync(_cts.Token).ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        SetEventStreamState(true);
        string? ev = null;
        var data = new StringBuilder();
        while (!_cts.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(_cts.Token).ConfigureAwait(false);
            if (line is null) break;
            if (line.StartsWith("event:", StringComparison.Ordinal))
                ev = line[6..].Trim();
            else if (line.StartsWith("data:", StringComparison.Ordinal))
                data.Append(line[5..].Trim());
            else if (line.Length == 0 && data.Length > 0)
            {
                Raise(ev ?? "message", data.ToString());
                ev = null;
                data.Clear();
            }
        }
    }

    private void SetEventStreamState(bool connected)
    {
        if (EventStreamConnected == connected) return;
        EventStreamConnected = connected;
        try { EventStreamStateChanged?.Invoke(this, connected); } catch { }
    }

    private void Raise(string ev, string json)
    {
        var evt = new BridgeEvent { Event = ev };
        try
        {
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(json) ? "{}" : json);
            var r = doc.RootElement;
            if (r.TryGetProperty("task_id", out var tid)) evt.TaskId = tid.GetString() ?? "";
            if (r.TryGetProperty("title", out var title)) evt.Title = title.GetString() ?? "";
            if (r.TryGetProperty("current", out var cur) && cur.TryGetInt32(out var ci)) evt.Current = ci;
            if (r.TryGetProperty("total", out var tot) && tot.TryGetInt32(out var ti)) evt.Total = ti;
            if (r.TryGetProperty("message", out var msg)) evt.Message = msg.GetString() ?? "";
            if (r.TryGetProperty("text", out var text)) evt.Text = text.GetString() ?? "";
            if (r.TryGetProperty("success", out var ok)) evt.Success = ok.ValueKind == JsonValueKind.True;
            if (r.TryGetProperty("count", out var c) && c.TryGetInt32(out var ci2)) evt.Count = ci2;
            if (r.TryGetProperty("code", out var code)) evt.Code = code.GetString() ?? "";
            if (r.TryGetProperty("uri", out var uri)) evt.Uri = uri.GetString() ?? "";
            if (r.TryGetProperty("detail", out var detail)) evt.Detail = detail.GetString() ?? "";
            if (r.TryGetProperty("kind", out var kind)) evt.Kind = kind.GetString() ?? "";
            if (r.TryGetProperty("label", out var label)) evt.Label = label.GetString() ?? "";
            if (r.TryGetProperty("name", out var name)) evt.Name = name.GetString() ?? "";
            if (r.TryGetProperty("stopped", out var stopped)) evt.Stopped = stopped.ValueKind == JsonValueKind.True;
            evt.PayloadJson = r.GetRawText();
            if (ev == "crash" || r.TryGetProperty("direct_file", out _) || r.TryGetProperty("headline", out _))
            {
                try { evt.Crash = JsonSerializer.Deserialize<CrashReport>(r.GetRawText(), JsonOpt); }
                catch { evt.Crash = null; }
                if (evt.Crash != null)
                {
                    if (string.IsNullOrEmpty(evt.Crash.TaskId)) evt.Crash.TaskId = evt.TaskId;
                    if (string.IsNullOrEmpty(evt.Detail)) evt.Detail = evt.Crash.Detail;
                    if (string.IsNullOrEmpty(evt.Title)) evt.Title = evt.Crash.Title;
                }
            }
        }
        catch { }
        EventReceived?.Invoke(this, evt);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        try { _cts.Cancel(); } catch (ObjectDisposedException) { }
        _http.Dispose();
        _cts.Dispose();
    }
}
