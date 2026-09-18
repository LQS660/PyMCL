using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PyMCL.Models;

namespace PyMCL.Services;

/// <summary>桥接推送的一条事件。字段是各类事件的并集，取用方按 Event 分流。</summary>
public sealed class BridgeEvent
{
    public string Event { get; set; } = "";
    public string TaskId { get; set; } = "";
    public string Title { get; set; } = "";
    public string Message { get; set; } = "";
    public string Text { get; set; } = "";
    public int Current { get; set; }
    public int Total { get; set; }
    public int Count { get; set; }
    public bool Success { get; set; }
    public bool Stopped { get; set; }
    public string Code { get; set; } = "";
    public string Uri { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Label { get; set; } = "";
    public string Name { get; set; } = "";
    public JsonElement Payload { get; set; }
    public CrashReport? Crash { get; set; }
}

public sealed class BridgeClient : IDisposable
{
    public const string TokenHeader = "X-PyMCL-Bridge-Token";

    public static readonly JsonSerializerOptions JsonOpt = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    private readonly HttpClient _http;
    private readonly CancellationTokenSource _cts = new();
    private readonly string _token;
    private int _id;
    private int _disposed;

    public Uri BaseUri { get; }
    public event EventHandler<BridgeEvent>? EventReceived;
    public event EventHandler<bool>? StreamStateChanged;
    public bool StreamConnected { get; private set; }
    public string LastStreamError { get; private set; } = "";

    public BridgeClient(Uri baseUri, string token)
    {
        if (baseUri.Scheme != Uri.UriSchemeHttp || baseUri.Host != "127.0.0.1" || baseUri.Port is < 1 or > 65535)
            throw new ArgumentException(L("仅允许回环地址"), nameof(baseUri));
        if (string.IsNullOrWhiteSpace(token) || token.Length < 32)
            throw new ArgumentException(L("令牌无效"), nameof(token));
        BaseUri = baseUri;
        _token = token;
        _http = new HttpClient { BaseAddress = baseUri, Timeout = TimeSpan.FromMinutes(20) };
        _http.DefaultRequestHeaders.TryAddWithoutValidation(TokenHeader, _token);
    }

    public void ConnectEvents() => _ = Task.Run(ReadSseLoop);

    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
    {
        using var resp = await _http.GetAsync("/health", ct).ConfigureAwait(false);
        return resp.IsSuccessStatusCode;
    }

    public async Task<JsonElement> CallAsync(string method, object? args = null, CancellationToken ct = default)
    {
        var payload = new Dictionary<string, object?>
        {
            ["jsonrpc"] = "2.0",
            ["id"] = Interlocked.Increment(ref _id),
            ["method"] = method,
            ["params"] = args ?? new Dictionary<string, object?>(),
        };
        using var content = new StringContent(JsonSerializer.Serialize(payload, JsonOpt), Encoding.UTF8, "application/json");
        using var resp = await _http.PostAsync("/rpc", content, ct).ConfigureAwait(false);
        var text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text);
        var root = doc.RootElement;
        if (root.TryGetProperty("error", out var err) && err.ValueKind != JsonValueKind.Null)
        {
            var msg = err.TryGetProperty("message", out var m) ? m.GetString() : err.ToString();
            throw new BridgeCallException(method, msg ?? L("调用失败"));
        }
        return root.TryGetProperty("result", out var result) ? result.Clone() : default;
    }

    public async Task<T?> CallAsync<T>(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        if (el.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null) return default;
        if (typeof(T) == typeof(string) && el.ValueKind == JsonValueKind.String)
            return (T)(object)(el.GetString() ?? "");
        try { return JsonSerializer.Deserialize<T>(el.GetRawText(), JsonOpt); }
        catch (JsonException) { return default; }
    }

    /// <summary>调用失败时不抛异常，返回兜底值。用于「刷新一下顺便试试」的非关键读取。</summary>
    public async Task<T?> TryCallAsync<T>(string method, object? args = null, T? fallback = default)
    {
        try { return await CallAsync<T>(method, args).ConfigureAwait(false) ?? fallback; }
        catch { return fallback; }
    }

    public async Task<string> StartTaskAsync(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        return el.ValueKind == JsonValueKind.String ? el.GetString() ?? "" : el.ToString();
    }

    private async Task ReadSseLoop()
    {
        var attempt = 0;
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                await ReadSseOnceAsync().ConfigureAwait(false);
                attempt = 0;
                LastStreamError = L("事件流被服务端关闭");
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex) { LastStreamError = ex.GetType().Name + ": " + ex.Message; }
            finally
            {
                SetStreamState(false);
                if (Environment.GetEnvironmentVariable("PYMCL_WPF_DEBUG") == "1")
                {
                    try
                    {
                        File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "pymcl-wpf-sse.log"),
                            $"[{DateTime.Now:HH:mm:ss}] attempt={attempt} {LastStreamError}\n");
                    }
                    catch { }
                }
            }
            if (_cts.IsCancellationRequested) break;
            attempt = Math.Min(attempt + 1, 5);
            try { await Task.Delay(TimeSpan.FromSeconds(Math.Min(1 << (attempt - 1), 15)), _cts.Token).ConfigureAwait(false); }
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
        SetStreamState(true);
        string? ev = null;
        var data = new StringBuilder();
        while (!_cts.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(_cts.Token).ConfigureAwait(false);
            if (line is null) break;
            if (line.StartsWith("event:", StringComparison.Ordinal)) ev = line[6..].Trim();
            else if (line.StartsWith("data:", StringComparison.Ordinal)) data.Append(line[5..].Trim());
            else if (line.Length == 0 && data.Length > 0)
            {
                Dispatch(ev ?? "message", data.ToString());
                ev = null;
                data.Clear();
            }
        }
    }

    private void Dispatch(string name, string json)
    {
        var evt = new BridgeEvent { Event = name };
        try
        {
            using var doc = JsonDocument.Parse(json);
            var r = doc.RootElement;
            evt.Payload = r.Clone();
            evt.TaskId = Str(r, "task_id");
            evt.Message = Str(r, "message");
            evt.Text = Str(r, "text");
            evt.Title = Str(r, "title");
            evt.Code = Str(r, "code");
            evt.Uri = Str(r, "uri");
            evt.Kind = Str(r, "kind");
            evt.Label = Str(r, "label");
            evt.Name = Str(r, "name");
            evt.Current = Num(r, "current");
            evt.Total = Num(r, "total");
            evt.Count = Num(r, "count");
            evt.Success = Bool(r, "success");
            evt.Stopped = Bool(r, "stopped");
            if (name == "crash")
            {
                try { evt.Crash = JsonSerializer.Deserialize<CrashReport>(json, JsonOpt); }
                catch { }
            }
        }
        catch { }
        EventReceived?.Invoke(this, evt);
    }

    private static string Str(JsonElement e, string k) =>
        e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    private static int Num(JsonElement e, string k) =>
        e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n) ? n : 0;

    private static bool Bool(JsonElement e, string k) =>
        e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.True;

    private void SetStreamState(bool connected)
    {
        if (StreamConnected == connected) return;
        StreamConnected = connected;
        try { StreamStateChanged?.Invoke(this, connected); } catch { }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        try { _cts.Cancel(); } catch { }
        _http.Dispose();
        _cts.Dispose();
    }
}

public sealed class BridgeCallException : Exception
{
    public string Method { get; }
    public BridgeCallException(string method, string message) : base(message) => Method = method;
}
