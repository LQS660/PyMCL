using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace PyMCL.Services;

/// <summary>拉起并守护本机桥进程（优先 C 桥，回退 Python 桥）。</summary>
public sealed class BridgeHost : IDisposable
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
        var python = await Task.Run(FindPython, ct).ConfigureAwait(false);
        var token = NewToken();
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
            backend = L("C 桥");
            psi.FileName = native;
            psi.Arguments = "--root " + QuoteArg(root);
            var bridgeDir = Path.GetDirectoryName(native) ?? "";
            var path = Environment.GetEnvironmentVariable("PATH") ?? "";
            if (!string.IsNullOrEmpty(bridgeDir))
                psi.EnvironmentVariables["PATH"] = bridgeDir + Path.PathSeparator + path;
            if (File.Exists(python))
                psi.EnvironmentVariables["PYMCL_PYTHON"] = python;
        }
        else if (File.Exists(server))
        {
            backend = L("Python 桥");
            psi.FileName = python;
            psi.Arguments = "-u " + QuoteArg(server) + " --root " + QuoteArg(root);
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
        }
        else
            throw new FileNotFoundException(L("找不到 pymcl-bridge.exe 或 bridge/server.py"));

        psi.EnvironmentVariables["PYMCL_HOME"] = root;
        psi.EnvironmentVariables["PYMCL_BRIDGE_TOKEN"] = token;

        var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        var err = new System.Text.StringBuilder();
        if (!proc.Start()) throw new InvalidOperationException(L("无法启动桥进程"));
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
            if (line != null && line.IndexOf("PYMCL_BRIDGE", StringComparison.Ordinal) >= 0) break;
            if (line is null) break;
            readTask = proc.StandardOutput.ReadLineAsync();
        }
        if (line is null || line.IndexOf("PYMCL_BRIDGE", StringComparison.Ordinal) < 0)
        {
            KillTree(proc);
            var tail = err.ToString().Trim();
            throw new InvalidOperationException(L("桥进程未输出端口") + (tail.Length > 0 ? L("：\n") + Tail(tail, 600) : ""));
        }
        var m = PortRegex.Match(line);
        if (!m.Success) throw new InvalidOperationException(L("无法解析桥端口: ") + line);
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
        KillTree(proc);
        throw new InvalidOperationException(L("桥已启动但 /health 无响应"));
    }

    private static string Tail(string text, int max) =>
        text.Length <= max ? text : "…" + text.Substring(text.Length - max);

    public static string FindRoot()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_HOME");
        if (!string.IsNullOrWhiteSpace(env)) return Path.GetFullPath(env);
        foreach (var start in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory, Path.GetDirectoryName(typeof(BridgeHost).Assembly.Location) ?? "" })
        {
            var hit = WalkUp(start);
            if (hit != null) return hit;
        }
        throw new DirectoryNotFoundException(L("找不到启动器根目录（需要包含 mclauncher/ 与 bridge/server.py）"));
    }

    private static string? _python;

    /// <summary>
    /// 桥要用的 Python：手动设的 PYMCL_PYTHON 优先；否则在 PATH 和注册表登记的解释器里挑，
    /// 装了 requests 和 keyring 的优先（C 桥回落 Python 时缺了它们就报错），只装 requests 的次之。结果缓存。
    /// </summary>
    public static string FindPython()
    {
        var env = Environment.GetEnvironmentVariable("PYMCL_PYTHON");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env)) return env;
        if (_python != null) return _python;
        string? first = null, best = null;
        var bestScore = 0;
        foreach (var p in PythonCandidates())
        {
            var score = ProbePython(p);
            if (score < 0) continue;
            first ??= p;
            if (score > bestScore) { best = p; bestScore = score; }
            if (score == 3) break;
        }
        return _python = best ?? first ?? "python";
    }

    private static IEnumerable<string> PythonCandidates()
    {
        var paths = new List<string>
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".workbuddy", "binaries", "python", "envs", "pymcl5", "Scripts", "python.exe"),
        };
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            if (string.IsNullOrWhiteSpace(dir)) continue;
            try { paths.Add(Path.Combine(dir.Trim().Trim('"'), "python.exe")); }
            catch { }
        }
        paths.AddRange(RegisteredPythons());
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var p in paths)
        {
            string full;
            try { full = Path.GetFullPath(p); }
            catch { continue; }
            // WindowsApps 根目录下的 python.exe 是商店别名，没装商店版 Python 时一运行就弹商店
            if ((Path.GetDirectoryName(full) ?? "").EndsWith(@"\Microsoft\WindowsApps", StringComparison.OrdinalIgnoreCase))
                continue;
            if (File.Exists(full) && seen.Add(full)) yield return full;
        }
    }

    /// <summary>PEP 514 登记的解释器（官方安装包、商店版都会登记）。</summary>
    private static List<string> RegisteredPythons()
    {
        var found = new List<string>();
        foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            try
            {
                using var root = RegistryKey.OpenBaseKey(hive, view);
                using var core = root.OpenSubKey(@"Software\Python\PythonCore");
                if (core == null) continue;
                foreach (var tag in core.GetSubKeyNames())
                {
                    using var install = core.OpenSubKey(tag + @"\InstallPath");
                    if (install?.GetValue("ExecutablePath") is string exe && exe.Length > 0)
                        found.Add(exe);
                    else if (install?.GetValue(null) is string dir && dir.Length > 0)
                        found.Add(Path.Combine(dir, "python.exe"));
                }
            }
            catch { }
        }
        return found;
    }

    /// <summary>2 = 装了 requests，+1 = 装了 keyring；跑不起来返回 -1。只查不导入，每个解释器几十毫秒。</summary>
    private static int ProbePython(string python)
    {
        try
        {
            using var proc = Process.Start(new ProcessStartInfo
            {
                FileName = python,
                Arguments = "-c \"import importlib.util as u; print(2 * bool(u.find_spec('requests')) + bool(u.find_spec('keyring')))\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
            });
            if (proc == null) return -1;
            var output = proc.StandardOutput.ReadToEndAsync();
            if (!proc.WaitForExit(8000))
            {
                try { proc.Kill(); } catch { }
                return -1;
            }
            return proc.ExitCode == 0 && int.TryParse(output.Result.Trim(), out var score) ? score : -1;
        }
        catch { return -1; }
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
            KillTree(_proc);
        }
        _proc?.Dispose();
        _proc = null;
    }

    /// <summary>net48 没有 Kill(bool)：用 taskkill 结束整棵进程树，失败再退回 Kill()。</summary>
    private static void KillTree(Process proc)
    {
        try
        {
            using var killer = Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill",
                Arguments = "/PID " + proc.Id + " /T /F",
                UseShellExecute = false,
                CreateNoWindow = true,
            });
            killer?.WaitForExit(5000);
        }
        catch { }
        try { if (!proc.HasExited) proc.Kill(); } catch { }
    }

    private static string QuoteArg(string arg) => "\"" + arg + "\"";

    private static string NewToken()
    {
        var buf = new byte[32];
        using (var rng = RandomNumberGenerator.Create())
            rng.GetBytes(buf);
        return BitConverter.ToString(buf).Replace("-", "");
    }

    private static readonly Regex PortRegex = new(@"port=(\d+)", RegexOptions.Compiled);
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
