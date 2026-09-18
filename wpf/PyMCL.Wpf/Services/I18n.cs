using System.Globalization;
using System.IO;
using System.Text.Json;

namespace PyMCL.Services;

/// <summary>
/// 界面多语言。词表与 Qt 端同源：<c>mclauncher/locales/&lt;lang&gt;.json</c>，key 就是中文原文，
/// 语义照 <c>mclauncher/i18n.py</c> 的 <c>_()</c>——zh_CN 与 en 互不回退，缺词返回中文原文；
/// 第三方语言先回退 en 再回退原文。
///
/// 用法：<c>L("启动游戏")</c>；带参数 <c>L("已安装 {0} 个", n)</c>（占位符是 string.Format 口径）。
/// 全项目通过 GlobalUsings.cs 的 <c>global using static</c> 直接写 <c>L(...)</c>。
///
/// 语言只在启动时定一次（照 Qt：切语言后提示重启）。来源优先级：
/// 命令行 <c>--lang xx</c> &gt; 环境变量 PYMCL_LANG &gt; config.json 的 language &gt; zh_CN。
/// </summary>
public static class I18n
{
    public const string DefaultLang = "zh_CN";

    private static readonly Dictionary<string, Dictionary<string, string>> _tables = new(StringComparer.Ordinal);
    private static Dictionary<string, string> _current = new(StringComparer.Ordinal);
    private static Dictionary<string, string> _en = new(StringComparer.Ordinal);
    private static readonly HashSet<string> _missing = new(StringComparer.Ordinal);
    private static readonly object _gate = new();

    /// <summary>当前语言代码（zh_CN / en …）。没 Init 之前就是 zh_CN，L() 原样返回。</summary>
    public static string Current { get; private set; } = DefaultLang;

    /// <summary>已加载的词表目录；找不到仓库根时为空串，L() 全部回落中文。</summary>
    public static string LocalesDir { get; private set; } = "";

    /// <summary>非中文界面下 L() 没查到词、回落成中文的 key。冒烟拿它当「界面残留中文」的判据。</summary>
    public static IReadOnlyCollection<string> Missing
    {
        get { lock (_gate) return _missing.ToArray(); }
    }

    /// <summary>词表里登记过的全部中文 key（zh_CN 那份）。给冒烟判断屏幕上的中文是不是界面词。</summary>
    public static IReadOnlyCollection<string> KnownKeys
    {
        get { lock (_gate) return _tables.TryGetValue(DefaultLang, out var zh) ? zh.Keys.ToArray() : Array.Empty<string>(); }
    }

    public static void Init(string[]? args = null)
    {
        var lang = ArgValue(args, "--lang")
                   ?? Environment.GetEnvironmentVariable("PYMCL_LANG")
                   ?? ReadConfigLanguage();
        Load(lang);
    }

    /// <summary>切到某个语言。名字照 Python 那边归一化：短横线换下划线，没有这份词表就回 zh_CN。</summary>
    public static void Load(string? lang)
    {
        EnsureTables();
        lang = (lang ?? "").Trim().Replace('-', '_');
        if (lang.Length == 0) lang = DefaultLang;
        lock (_gate)
        {
            if (!_tables.ContainsKey(lang)) lang = DefaultLang;
            Current = lang;
            _current = _tables[lang];
            _en = _tables.TryGetValue("en", out var en) ? en : new Dictionary<string, string>(StringComparer.Ordinal);
            _missing.Clear();
        }
        CultureInfo.CurrentUICulture = lang switch
        {
            "en" => CultureInfo.GetCultureInfo("en-US"),
            _ => CultureInfo.GetCultureInfo("zh-CN"),
        };
    }

    /// <summary>取当前语言的文案；查不到返回中文原文（跟 Python 的 _() 一样）。</summary>
    public static string L(string zh)
    {
        if (string.IsNullOrEmpty(zh)) return zh;
        var table = _current;
        if (table.TryGetValue(zh, out var v) && v.Length > 0) return v;
        if (Current != DefaultLang)
        {
            // key 本身就是中文原文，所以 zh_CN 与 en 都不能回退到对方；第三方语言先看 en
            if (Current != "en" && _en.TryGetValue(zh, out var e) && e.Length > 0) return e;
            // 只记真的回落成中文的。像「16x」这种本来就不是中文的分类名，原样返回不是残留，
            // 记进去会让 en 冒烟把它当缺词判红。
            if (I18nCheck.HasCjk(zh)) lock (_gate) _missing.Add(zh);
        }
        return zh;
    }

    /// <summary>
    /// 只查不记：给冒烟 / 探针拿词表译文去比对界面文案用。查不到返回 null，**不会**被算进 <see cref="Missing"/>——
    /// 否则白名单里一个没有译文的词（它根本不是界面上的字），就会把整轮 en 冒烟判成「界面残留中文」。
    /// 界面文案照旧走 <see cref="L(string)"/>。
    /// </summary>
    public static string? Peek(string zh)
    {
        if (string.IsNullOrEmpty(zh)) return null;
        if (_current.TryGetValue(zh, out var v) && v.Length > 0) return v;
        if (Current != DefaultLang && Current != "en" && _en.TryGetValue(zh, out var e) && e.Length > 0) return e;
        return null;
    }

    /// <summary>带参数的文案。占位符按 string.Format（{0} {1:N1} …），译文格式坏了就退回原文拼接。</summary>
    public static string L(string zh, params object?[] args)
    {
        var fmt = L(zh);
        if (args.Length == 0) return fmt;
        try { return string.Format(CultureInfo.CurrentCulture, fmt, args); }
        catch (FormatException)
        {
            try { return string.Format(CultureInfo.CurrentCulture, zh, args); }
            catch (FormatException) { return fmt; }
        }
    }

    /// <summary>某个 key 在某种语言里有没有译文（--i18n-check 用）。</summary>
    public static bool Has(string lang, string key)
    {
        EnsureTables();
        lock (_gate) return _tables.TryGetValue(lang, out var t) && t.TryGetValue(key, out var v) && v.Length > 0;
    }

    /// <summary>已加载的语言代码列表。</summary>
    public static IReadOnlyList<string> Languages
    {
        get { EnsureTables(); lock (_gate) return _tables.Keys.OrderBy(k => k, StringComparer.Ordinal).ToArray(); }
    }

    private static bool _loaded;

    private static void EnsureTables()
    {
        lock (_gate)
        {
            if (_loaded) return;
            _loaded = true;
            _tables[DefaultLang] = new Dictionary<string, string>(StringComparer.Ordinal);
            _tables["en"] = new Dictionary<string, string>(StringComparer.Ordinal);
            string dir;
            try { dir = Path.Combine(BridgeHost.FindRoot(), "mclauncher", "locales"); }
            catch { return; }
            if (!Directory.Exists(dir)) return;
            LocalesDir = dir;
            foreach (var file in Directory.EnumerateFiles(dir, "*.json").OrderBy(f => f, StringComparer.Ordinal))
            {
                try
                {
                    using var doc = JsonDocument.Parse(File.ReadAllText(file));
                    if (doc.RootElement.ValueKind != JsonValueKind.Object) continue;
                    var table = new Dictionary<string, string>(StringComparer.Ordinal);
                    foreach (var p in doc.RootElement.EnumerateObject())
                        if (p.Value.ValueKind == JsonValueKind.String) table[p.Name] = p.Value.GetString() ?? "";
                    _tables[Path.GetFileNameWithoutExtension(file)] = table;
                }
                catch (Exception ex) when (ex is JsonException or IOException) { }
            }
        }
    }

    /// <summary>config.json 里的 language 键——跟 Qt 与桥共用同一份配置，切语言两边一起变。</summary>
    private static string ReadConfigLanguage()
    {
        try
        {
            var path = Path.Combine(BridgeHost.FindRoot(), "config.json");
            if (!File.Exists(path)) return DefaultLang;
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            return doc.RootElement.TryGetProperty("language", out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? DefaultLang
                : DefaultLang;
        }
        catch { return DefaultLang; }
    }

    private static string? ArgValue(string[]? args, string name)
    {
        if (args is null) return null;
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
