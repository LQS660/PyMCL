using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace PyMCL.Services;

public sealed class BridgeHost : IDisposable
{
    private Process? _proc;
    private int _disposed;
    public BridgeClient Client { get; }
    public int Port { get; }
    public string Root { get; }

    private BridgeHost(BridgeClient client, Process proc, int port, string root)
    {
        Client = client;
        _proc = proc;
        Port = port;
        Root = root;
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
        if (native != null && !forcePython)
        {
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
            var python = FindPython();
            psi.FileName = python;
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
        if (!proc.Start()) throw new InvalidOperationException("无法启动桥进程");

        string? line = null;
        var deadline = DateTime.UtcNow.AddSeconds(20);
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
            if (line != null && line.Contains("PYMCL_BRIDGE", StringComparison.Ordinal))
                break;
            readTask = proc.StandardOutput.ReadLineAsync();
        }
        if (line is null || !line.Contains("PYMCL_BRIDGE", StringComparison.Ordinal))
        {
            try { proc.Kill(true); } catch { }
            throw new InvalidOperationException("桥进程未输出端口");
        }
        var m = Regex.Match(line, @"port=(\d+)");
        if (!m.Success) throw new InvalidOperationException("无法解析桥端口: " + line);
        var port = int.Parse(m.Groups[1].Value);
        var client = new BridgeClient(new Uri($"http://127.0.0.1:{port}/"), token);
        for (var i = 0; i < 40; i++)
        {
            try
            {
                if (await client.IsHealthyAsync(ct).ConfigureAwait(false))
                {
                    await client.ConnectEventsAsync();
                    return new BridgeHost(client, proc, port, root);
                }
            }
            catch { }
            await Task.Delay(100, ct).ConfigureAwait(false);
        }
        client.Dispose();
        try { proc.Kill(true); } catch { }
        throw new InvalidOperationException("桥已启动但 /health 无响应");
    }

    public static string FindRoot()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_HOME");
        if (!string.IsNullOrWhiteSpace(env)) return Path.GetFullPath(env);
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory, Path.GetDirectoryName(Environment.ProcessPath) ?? "" })
        {
            var hit = WalkUp(start);
            if (hit != null) return hit;
        }
        throw new DirectoryNotFoundException("找不到启动器根目录");
    }

    public static string FindPython()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return env;
        var known = @"C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe";
        if (File.Exists(known)) return known;
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
}

public static class AppServices
{
    public static BridgeClient Client { get; set; } = null!;
    public static BridgeHost? Host { get; set; }
}
