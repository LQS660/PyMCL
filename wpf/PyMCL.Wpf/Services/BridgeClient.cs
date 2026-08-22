using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PyMCL.Services;

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
    public string PayloadJson { get; set; } = "";
}

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
    public event EventHandler<bool>? EventStreamStateChanged;
    public bool EventStreamConnected { get; private set; }

    public BridgeClient(Uri baseUri, string token)
    {
        if (baseUri.Scheme != Uri.UriSchemeHttp || baseUri.Host != "127.0.0.1" || baseUri.Port is < 1 or > 65535)
            throw new ArgumentException("loopback only", nameof(baseUri));
        if (string.IsNullOrWhiteSpace(token) || token.Length < 32)
            throw new ArgumentException("token", nameof(token));
        BaseUri = baseUri;
        _token = token;
        _http = new HttpClient { BaseAddress = baseUri, Timeout = TimeSpan.FromMinutes(10) };
        _http.DefaultRequestHeaders.TryAddWithoutValidation(TokenHeader, _token);
    }

    public Task ConnectEventsAsync()
    {
        _ = Task.Run(ReadSseLoop);
        return Task.CompletedTask;
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
        return root.TryGetProperty("result", out var result) ? result.Clone() : default;
    }

    public async Task<T?> CallAsync<T>(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        if (el.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null) return default;
        return JsonSerializer.Deserialize<T>(el.GetRawText(), JsonOpt);
    }

    public async Task<string> StartTaskAsync(string method, object? args = null, CancellationToken ct = default)
    {
        var el = await CallAsync(method, args, ct).ConfigureAwait(false);
        return el.ValueKind == JsonValueKind.String ? (el.GetString() ?? "") : el.ToString();
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
            }
            catch (OperationCanceledException) { break; }
            catch { }
            finally { SetEventStreamState(false); }
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
        SetEventStreamState(true);
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
                var evt = new BridgeEvent { Event = ev ?? "message", PayloadJson = data.ToString() };
                try
                {
                    using var doc = JsonDocument.Parse(data.ToString());
                    var r = doc.RootElement;
                    if (r.TryGetProperty("task_id", out var tid)) evt.TaskId = tid.GetString() ?? "";
                    if (r.TryGetProperty("message", out var msg)) evt.Message = msg.GetString() ?? "";
                    if (r.TryGetProperty("text", out var text)) evt.Text = text.GetString() ?? "";
                    if (r.TryGetProperty("title", out var title)) evt.Title = title.GetString() ?? "";
                    if (r.TryGetProperty("current", out var cur) && cur.TryGetInt32(out var ci)) evt.Current = ci;
                    if (r.TryGetProperty("total", out var tot) && tot.TryGetInt32(out var ti)) evt.Total = ti;
                    if (r.TryGetProperty("count", out var c) && c.TryGetInt32(out var n)) evt.Count = n;
                    if (r.TryGetProperty("success", out var ok)) evt.Success = ok.ValueKind == JsonValueKind.True;
                }
                catch { }
                EventReceived?.Invoke(this, evt);
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

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        try { _cts.Cancel(); } catch { }
        _http.Dispose();
        _cts.Dispose();
    }
}
