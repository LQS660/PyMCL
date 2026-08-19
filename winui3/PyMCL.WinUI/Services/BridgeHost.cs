using System.Diagnostics;
using System.Text.RegularExpressions;

namespace PyMCL.Services;

public sealed class BridgeHost : IDisposable
{
    private Process? _proc;
    private int _disposed;
    public BridgeClient Client { get; }
    public int Port { get; }
    public string Root { get; }
    public string Python { get; }

    private BridgeHost(BridgeClient client, Process proc, int port, string root, string python)
    {
        Client = client;
        _proc = proc;
        Port = port;
        Root = root;
        Python = python;
    }

    public static async Task<BridgeHost> StartAsync(CancellationToken ct = default)
    {
        var root = FindRoot();
        var native = FindNativeBridge(root);
        var server = Path.Combine(root, "bridge", "server.py");
        var forcePython = string.Equals(Environment.GetEnvironmentVariable("PYMCL_BRIDGE"), "python", StringComparison.OrdinalIgnoreCase);
        var python = "";
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
            psi.Arguments = $"--root \"{root}\"";
            var mingw = @"C:\msys64\mingw64\bin";
            var path = Environment.GetEnvironmentVariable("PATH") ?? "";
            if (Directory.Exists(mingw) && path.IndexOf(mingw, StringComparison.OrdinalIgnoreCase) < 0)
                psi.Environment["PATH"] = mingw + Path.PathSeparator + path;
        }
        else if (File.Exists(server))
        {
            python = FindPython();
            psi.FileName = python;
            psi.Arguments = $"-u \"{server}\" --root \"{root}\"";
            psi.Environment["PYTHONIOENCODING"] = "utf-8";
            psi.Environment["PYTHONUNBUFFERED"] = "1";
        }
        else
        {
            throw new FileNotFoundException("找不到 native/build/pymcl-bridge.exe 或 bridge/server.py", server);
        }
        psi.Environment["PYMCL_HOME"] = root;
        psi.Environment["PYTHONFAULTHANDLER"] = "1";

        var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        var stderrPath = Path.Combine(root, "bridge-server.log");
        proc.ErrorDataReceived += (_, e) =>
        {
            if (string.IsNullOrEmpty(e.Data)) return;
            try { File.AppendAllText(stderrPath, e.Data + Environment.NewLine); } catch { }
        };
        if (!proc.Start())
            throw new InvalidOperationException("无法启动桥进程");
        proc.BeginErrorReadLine();

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
            throw new InvalidOperationException("桥进程未输出端口。见 bridge-server.log");
        }
        var m = Regex.Match(line, @"port=(\d+)");
        if (!m.Success)
            throw new InvalidOperationException("无法解析桥端口: " + line);
        var port = int.Parse(m.Groups[1].Value);
        var client = new BridgeClient(new Uri($"http://127.0.0.1:{port}/"));
        await client.ConnectEventsAsync();
        for (var i = 0; i < 25; i++)
        {
            try
            {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
                var r = await http.GetAsync($"http://127.0.0.1:{port}/health", ct);
                if (r.IsSuccessStatusCode) break;
            }
            catch
            {
                if (i == 24) throw new InvalidOperationException("桥进程已启动但 /health 无响应");
                await Task.Delay(200, ct);
            }
        }
        return new BridgeHost(client, proc, port, root, string.IsNullOrEmpty(python) ? native! : python);
    }

    public static string FindRoot()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_HOME");
        if (!string.IsNullOrWhiteSpace(env))
            return Path.GetFullPath(env);

        foreach (var start in new[]
                 {
                     AppContext.BaseDirectory,
                     Environment.CurrentDirectory,
                     Path.GetDirectoryName(Environment.ProcessPath) ?? "",
                 })
        {
            var hit = WalkUp(start);
            if (hit != null) return hit;
        }
        throw new DirectoryNotFoundException("找不到启动器根目录（需含 mclauncher，以及 C 桥或 bridge/server.py）");
    }

    public static string FindPython()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env))
            return env;
        var known = @"C:\Users\Administrator\.workbuddy\binaries\python\envs\pymcl5\Scripts\python.exe";
        if (File.Exists(known)) return known;
        foreach (var name in new[] { "python.exe", "python" })
        {
            var found = FindOnPath(name);
            if (found != null) return found;
        }
        throw new FileNotFoundException("找不到 Python。设置 PYMCL_PYTHON 或安装 pymcl5 环境。");
    }

    private static string? WalkUp(string start)
    {
        if (string.IsNullOrWhiteSpace(start)) return null;
        DirectoryInfo? dir;
        try { dir = new DirectoryInfo(Path.GetFullPath(start)); }
        catch { return null; }
        while (dir != null)
        {
            if (LooksLikeRoot(dir.FullName)) return dir.FullName;
            dir = dir.Parent;
        }
        return null;
    }

    public static string? FindNativeBridge(string root)
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_BRIDGE_EXE");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env))
            return Path.GetFullPath(env);
        foreach (var p in new[]
                 {
                     Path.Combine(AppContext.BaseDirectory, "pymcl-bridge.exe"),
                     Path.Combine(root, "pymcl-bridge.exe"),
                     Path.Combine(root, "native", "build", "pymcl-bridge.exe"),
                     Path.Combine(root, "native", "build", "Release", "pymcl-bridge.exe"),
                     Path.Combine(root, "native", "build", "RelWithDebInfo", "pymcl-bridge.exe"),
                 })
        {
            if (File.Exists(p)) return p;
        }
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

    private static string? FindOnPath(string name)
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var part in path.Split(Path.PathSeparator))
        {
            try
            {
                var full = Path.Combine(part.Trim(), name);
                if (File.Exists(full)) return full;
            }
            catch { }
        }
        return null;
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
    public static Microsoft.UI.Dispatching.DispatcherQueue? Dispatcher { get; set; }
    public static Action<string, string, Microsoft.UI.Xaml.Controls.InfoBarSeverity>? Toast { get; set; }
    public static Action<string>? OpenDownload { get; set; }
    public static nint WindowHandle { get; set; }

    public static void OnUi(Action action)
    {
        var dq = Dispatcher;
        if (dq is null || dq.HasThreadAccess)
        {
            action();
            return;
        }
        dq.TryEnqueue(() => action());
    }
}
