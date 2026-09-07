using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace PyMCL.Services;

/// <summary>拉起并守护本机桥进程（优先 C 桥，回退 Python 桥）。</summary>
public sealed partial class BridgeHost : IDisposable
{
    private Process? _proc;
    private int _disposed;

    public BridgeClient Client { get; }
    public int Port { get; }
    public string Root { get; }
    public string Backend { get; }

    private BridgeHost(BridgeClient client, Process proc, int port, string root, string backend)
    {
        Client = client;
        _proc = proc;
        Port = port;
        Root = root;
        Backend = backend;
    }

    public static async Task<BridgeHost> StartAsync(CancellationToken ct = default)
    {
        var root = FindRoot();
        var native = FindNativeBridge(root);
        var server = Path.Combine(root, "bridge", "server.py");
        var forcePython = string.Equals(Environment.GetEnvironmentVariable("PYMCL_BRIDGE"), "python", StringComparison.OrdinalIgnoreCase);
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
        var psi = new ProcessStartInfo
        {
            WorkingDirectory = root,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        string backend;
        if (native != null && !forcePython)
        {
            backend = "C 桥";
            psi.FileName = native;
            psi.ArgumentList.Add("--root");
            psi.ArgumentList.Add(root);
            var bridgeDir = Path.GetDirectoryName(native) ?? "";
            var path = Environment.GetEnvironmentVariable("PATH") ?? "";
            if (!string.IsNullOrEmpty(bridgeDir))
                psi.Environment["PATH"] = bridgeDir + Path.PathSeparator + path;
        }
        else if (File.Exists(server))
        {
            backend = "Python 桥";
            psi.FileName = FindPython();
            psi.ArgumentList.Add("-u");
            psi.ArgumentList.Add(server);
            psi.ArgumentList.Add("--root");
            psi.ArgumentList.Add(root);
            psi.Environment["PYTHONIOENCODING"] = "utf-8";
            psi.Environment["PYTHONUNBUFFERED"] = "1";
        }
        else
            throw new FileNotFoundException("找不到 pymcl-bridge.exe 或 bridge/server.py");

        psi.Environment["PYMCL_HOME"] = root;
        psi.Environment["PYMCL_BRIDGE_TOKEN"] = token;

        var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        var err = new System.Text.StringBuilder();
        if (!proc.Start()) throw new InvalidOperationException("无法启动桥进程");
        proc.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is { Length: > 0 } && err.Length < 4000) err.AppendLine(e.Data);
        };
        try { proc.BeginErrorReadLine(); } catch { }

        string? line = null;
        var deadline = DateTime.UtcNow.AddSeconds(30);
        var readTask = proc.StandardOutput.ReadLineAsync();
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            var done = await Task.WhenAny(readTask, Task.Delay(200, ct)).ConfigureAwait(false);
            if (done != readTask)
            {
                if (proc.HasExited) break;
                continue;
            }
            line = await readTask.ConfigureAwait(false);
            if (line != null && line.Contains("PYMCL_BRIDGE", StringComparison.Ordinal)) break;
            if (line is null) break;
            readTask = proc.StandardOutput.ReadLineAsync();
        }
        if (line is null || !line.Contains("PYMCL_BRIDGE", StringComparison.Ordinal))
        {
            try { proc.Kill(true); } catch { }
            var tail = err.ToString().Trim();
            throw new InvalidOperationException("桥进程未输出端口" + (tail.Length > 0 ? "：\n" + Tail(tail, 600) : ""));
        }
        var m = PortRegex().Match(line);
        if (!m.Success) throw new InvalidOperationException("无法解析桥端口: " + line);
        var port = int.Parse(m.Groups[1].Value);
        var client = new BridgeClient(new Uri($"http://127.0.0.1:{port}/"), token);
        for (var i = 0; i < 60; i++)
        {
            try
            {
                if (await client.IsHealthyAsync(ct).ConfigureAwait(false))
                {
                    client.ConnectEvents();
                    return new BridgeHost(client, proc, port, root, backend);
                }
            }
            catch { }
            await Task.Delay(100, ct).ConfigureAwait(false);
        }
        client.Dispose();
        try { proc.Kill(true); } catch { }
        throw new InvalidOperationException("桥已启动但 /health 无响应");
    }

    private static string Tail(string text, int max) =>
        text.Length <= max ? text : "…" + text[^max..];

    public static string FindRoot()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_HOME");
        if (!string.IsNullOrWhiteSpace(env)) return Path.GetFullPath(env);
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory, Path.GetDirectoryName(Environment.ProcessPath) ?? "" })
        {
            var hit = WalkUp(start);
            if (hit != null) return hit;
        }
        throw new DirectoryNotFoundException("找不到启动器根目录（需要包含 mclauncher/ 与 bridge/server.py）");
    }

    public static string FindPython()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return env;
        var known = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".workbuddy", "binaries", "python", "envs", "pymcl5", "Scripts", "python.exe"),
        };
        foreach (var p in known)
            if (File.Exists(p)) return p;
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            if (string.IsNullOrWhiteSpace(dir)) continue;
            try
            {
                var p = Path.Combine(dir.Trim(), "python.exe");
                if (File.Exists(p)) return p;
            }
            catch { }
        }
        return "python";
    }

    private static string? WalkUp(string start)
    {
        if (string.IsNullOrWhiteSpace(start)) return null;
        try
        {
            var dir = new DirectoryInfo(Path.GetFullPath(start));
            while (dir != null)
            {
                if (LooksLikeRoot(dir.FullName)) return dir.FullName;
                dir = dir.Parent;
            }
        }
        catch { }
        return null;
    }

    public static string? FindNativeBridge(string root)
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_BRIDGE_EXE");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return Path.GetFullPath(env);
        foreach (var p in new[]
                 {
                     Path.Combine(AppContext.BaseDirectory, "pymcl-bridge.exe"),
                     Path.Combine(root, "pymcl-bridge.exe"),
                     Path.Combine(root, "native", "build", "pymcl-bridge.exe"),
                 })
            if (File.Exists(p)) return p;
        return null;
    }

    private static bool LooksLikeRoot(string path)
    {
        var hasCore = Directory.Exists(Path.Combine(path, "mclauncher"))
                      || File.Exists(Path.Combine(path, "native", "data", "catalog.json"));
        var hasBridge = File.Exists(Path.Combine(path, "bridge", "server.py"))
                        || FindNativeBridge(path) != null;
        return hasCore && hasBridge;
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        Client.Dispose();
        if (_proc is { HasExited: false })
        {
            try { _proc.Kill(true); } catch { }
        }
        _proc?.Dispose();
        _proc = null;
    }

    [GeneratedRegex(@"port=(\d+)")]
    private static partial Regex PortRegex();
}

public static class AppServices
{
    public static BridgeClient Client { get; set; } = null!;
    public static BridgeHost? Host { get; set; }
    public static MainWindow? Window { get; set; }
    public static bool Ready => Client is not null;

    public static void Toast(string title, string body = "", ToastKind kind = ToastKind.Info) =>
        Window?.Toast(title, body, kind);
}
