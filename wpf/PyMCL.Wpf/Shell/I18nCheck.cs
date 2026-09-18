// i18n:ignore-file —— 自检本身的控制台输出是开发者看的，不进词表。
using System.IO;
using System.Text;
using System.Text.Json;
using PyMCL.Services;

namespace PyMCL;

/// <summary>
/// 多语言自检：扫 wpf/PyMCL.Wpf 下的 .cs 源码，找出还没包进 L(...) 的中文字面量，
/// 并把 L() 用到的 key 逐个对到 mclauncher/locales 的 zh_CN / en 词表上。
///
///   PyMCL.Wpf.exe --i18n-check          人读的摘要 + 逐条位置
///   PyMCL.Wpf.exe --i18n-check --json   只输出 JSON（tests/test_wpf_i18n.py 用）
///
/// 退出码：0 = 没有未包裹、en 也不缺词；1 = 有问题；2 = 找不到源码树。
///
/// 规则（tests/test_wpf_i18n.py 里那份 Python 实现与这里逐条一致，改一处要改两处）：
///   · 只看字符串字面量：普通 / 逐字 @"" / 插值 $"" / 原始 """ """；注释与字符字面量不算。
///   · 「中文」= 含 CJK 统一表意文字（U+4E00–9FFF、U+3400–4DBF）或 CJK 标点 / 全角字符
///     （U+3000–303F、U+FF00–FFEF）。
///   · 「已包裹」= 字面量往前跳过空白恰好是 `L(`（L 前面不是标识符字符，或是 `.`）。
///   · 文件前 10 行出现 `i18n:ignore-file` 整文件不看（冒烟 / 自检这类开发探针的日志文案）；
///     某一行出现 `i18n:ignore` 该行不看（跟桥返回的原文比对、协议值这类不该翻的）。
/// </summary>
public static class I18nCheck
{
    public sealed record Literal(string File, int Line, string Value, bool Wrapped, bool Ignored);

    public static int Run(string[] args)
    {
        var utf8 = new UTF8Encoding(false);
        using var output = new StreamWriter(Console.OpenStandardOutput(), utf8);
        var json = args.Contains("--json");
        string srcDir;
        try { srcDir = Path.Combine(BridgeHost.FindRoot(), "wpf", "PyMCL.Wpf"); }
        catch (Exception ex)
        {
            output.WriteLine(json ? JsonSerializer.Serialize(new { error = ex.Message }) : "找不到仓库根目录：" + ex.Message);
            output.Flush();
            return 2;
        }
        if (!Directory.Exists(srcDir))
        {
            output.WriteLine(json ? JsonSerializer.Serialize(new { error = "no sources", dir = srcDir }) : "没有源码树：" + srcDir);
            output.Flush();
            return 2;
        }

        var literals = new List<Literal>();
        var files = 0;
        var ignoredFiles = new List<string>();
        foreach (var file in Directory.EnumerateFiles(srcDir, "*.cs", SearchOption.AllDirectories).OrderBy(f => f, StringComparer.Ordinal))
        {
            var rel = Path.GetRelativePath(srcDir, file).Replace('\\', '/');
            if (rel.StartsWith("obj/", StringComparison.Ordinal) || rel.StartsWith("bin/", StringComparison.Ordinal)) continue;
            files++;
            var text = File.ReadAllText(file);
            if (IsFileIgnored(text)) { ignoredFiles.Add(rel); continue; }
            literals.AddRange(Scan(text).Select(l => l with { File = rel }));
        }

        var unwrapped = literals.Where(l => !l.Wrapped && !l.Ignored).ToList();
        var keys = literals.Where(l => l.Wrapped).Select(l => l.Value).Distinct(StringComparer.Ordinal).OrderBy(k => k, StringComparer.Ordinal).ToList();
        var missingEn = keys.Where(k => !I18n.Has("en", k)).ToList();
        var missingZh = keys.Where(k => !I18n.Has(I18n.DefaultLang, k)).ToList();

        var report = new Dictionary<string, object?>
        {
            ["src_dir"] = srcDir,
            ["locales_dir"] = I18n.LocalesDir,
            ["files"] = files,
            ["ignored_files"] = ignoredFiles,
            ["ignored_lines"] = literals.Count(l => l.Ignored && !l.Wrapped),
            ["wrapped"] = literals.Count(l => l.Wrapped),
            ["keys"] = keys.Count,
            ["unwrapped_count"] = unwrapped.Count,
            ["unwrapped"] = unwrapped.Select(l => new { file = l.File, line = l.Line, text = l.Value }).ToList(),
            ["missing_en_count"] = missingEn.Count,
            ["missing_en"] = missingEn,
            ["missing_zh_count"] = missingZh.Count,
            ["missing_zh"] = missingZh,
        };
        var code = unwrapped.Count == 0 && missingEn.Count == 0 ? 0 : 1;
        report["exit_code"] = code;

        if (json)
        {
            output.WriteLine(JsonSerializer.Serialize(report, new JsonSerializerOptions
            {
                WriteIndented = true,
                Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            }));
        }
        else
        {
            output.WriteLine($"源码：{srcDir}（{files} 个 .cs，整文件忽略 {ignoredFiles.Count} 个：{string.Join(", ", ignoredFiles)}）");
            output.WriteLine($"词表：{(I18n.LocalesDir.Length > 0 ? I18n.LocalesDir : "（没找到）")}");
            output.WriteLine($"已包裹 L() {report["wrapped"]} 处，去重 {keys.Count} 个 key；按行忽略 {report["ignored_lines"]} 处");
            output.WriteLine($"未包裹的中文字面量：{unwrapped.Count}");
            foreach (var l in unwrapped) output.WriteLine($"  {l.File}:{l.Line}  {Shorten(l.Value)}");
            output.WriteLine($"L() 用到、en 词表缺的 key：{missingEn.Count}");
            foreach (var k in missingEn) output.WriteLine($"  {Shorten(k)}");
            output.WriteLine($"L() 用到、zh_CN 词表缺的 key：{missingZh.Count}");
            foreach (var k in missingZh) output.WriteLine($"  {Shorten(k)}");
            output.WriteLine(code == 0 ? "OK" : "FAIL");
        }
        output.Flush();
        return code;
    }

    private static string Shorten(string s)
    {
        s = s.Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t");
        return s.Length > 80 ? s[..80] + "…" : s;
    }

    public static bool HasCjk(string s)
    {
        foreach (var c in s)
        {
            if ((c >= '\u4E00' && c <= '\u9FFF') || (c >= '\u3400' && c <= '\u4DBF') ||
                (c >= '\u3000' && c <= '\u303F') || (c >= '\uFF00' && c <= '\uFFEF'))
                return true;
        }
        return false;
    }

    private static bool IsFileIgnored(string text)
    {
        var n = 0;
        foreach (var line in text.Split('\n'))
        {
            if (line.Contains("i18n:ignore-file", StringComparison.Ordinal)) return true;
            if (++n >= 10) break;
        }
        return false;
    }

    /// <summary>把一份源码里含中文的字符串字面量全部找出来（含插值字符串的文本段与洞里的嵌套字面量）。</summary>
    public static List<Literal> Scan(string text)
    {
        var result = new List<Literal>();
        var lines = text.Split('\n');
        var lineStarts = new int[lines.Length];
        var pos = 0;
        for (var i = 0; i < lines.Length; i++) { lineStarts[i] = pos; pos += lines[i].Length + 1; }

        int LineOf(int offset)
        {
            var lo = 0; var hi = lineStarts.Length - 1;
            while (lo < hi)
            {
                var mid = (lo + hi + 1) / 2;
                if (lineStarts[mid] <= offset) lo = mid; else hi = mid - 1;
            }
            return lo;
        }

        bool LineIgnored(int offset) => lines[LineOf(offset)].Contains("i18n:ignore", StringComparison.Ordinal);

        void Emit(int start, string value)
        {
            if (!HasCjk(value)) return;
            result.Add(new Literal("", LineOf(start) + 1, value, IsWrapped(text, start), LineIgnored(start)));
        }

        ScanCode(text, 0, text.Length, Emit, stopAtBrace: false);
        return result;
    }

    /// <summary>
    /// 从 i 起扫代码；stopAtBrace 时遇到未配对的 `}` 就停（用于插值洞）。返回停下的位置。
    /// </summary>
    private static int ScanCode(string s, int i, int end, Action<int, string> emit, bool stopAtBrace)
    {
        var depth = 0;
        while (i < end)
        {
            var c = s[i];
            if (c == '/' && i + 1 < end && s[i + 1] == '/')
            {
                while (i < end && s[i] != '\n') i++;
                continue;
            }
            if (c == '/' && i + 1 < end && s[i + 1] == '*')
            {
                var close = s.IndexOf("*/", i + 2, StringComparison.Ordinal);
                i = close < 0 ? end : close + 2;
                continue;
            }
            if (c == '\'')
            {
                i++;
                while (i < end && s[i] != '\'') { if (s[i] == '\\') i++; i++; }
                i++;
                continue;
            }
            if (c == '"' || (c == '@' && i + 1 < end && (s[i + 1] == '"' || (s[i + 1] == '$' && i + 2 < end && s[i + 2] == '"')))
                || (c == '$' && i + 1 < end && (s[i + 1] == '"' || (s[i + 1] == '@' && i + 2 < end && s[i + 2] == '"'))))
            {
                i = ScanString(s, i, end, emit);
                continue;
            }
            if (stopAtBrace)
            {
                if (c == '{' || c == '(' || c == '[') depth++;
                else if (c == ')' || c == ']') depth--;
                else if (c == '}')
                {
                    if (depth == 0) return i;
                    depth--;
                }
            }
            i++;
        }
        return i;
    }

    /// <summary>扫一个字符串字面量（起点在前缀 @ / $ 或引号上），返回字面量之后的位置。</summary>
    private static int ScanString(string s, int start, int end, Action<int, string> emit)
    {
        var i = start;
        var verbatim = false; var interpolated = false;
        while (i < end && (s[i] == '@' || s[i] == '$'))
        {
            if (s[i] == '@') verbatim = true; else interpolated = true;
            i++;
        }
        // 原始字符串 """..."""：整段当普通文本
        if (i + 2 < end && s[i] == '"' && s[i + 1] == '"' && s[i + 2] == '"')
        {
            var q = i;
            while (q < end && s[q] == '"') q++;
            var quotes = q - i;
            var closing = new string('"', quotes);
            var close = s.IndexOf(closing, q, StringComparison.Ordinal);
            if (close < 0) close = end;
            var raw = s.Substring(q, close - q);
            if (interpolated) raw = raw.Replace("{{", "{").Replace("}}", "}");
            emit(start, raw.Trim('\r', '\n', ' '));
            return Math.Min(end, close + quotes);
        }
        i++; // 开引号
        var sb = new StringBuilder();
        while (i < end)
        {
            var c = s[i];
            if (c == '"')
            {
                if (verbatim && i + 1 < end && s[i + 1] == '"') { sb.Append('"'); i += 2; continue; }
                i++;
                break;
            }
            if (!verbatim && c == '\\' && i + 1 < end)
            {
                i = Unescape(s, i, sb);
                continue;
            }
            if (interpolated && c == '{')
            {
                if (i + 1 < end && s[i + 1] == '{') { sb.Append('{'); i += 2; continue; }
                // 洞：里面是代码，嵌套的字面量各自单独算
                var stop = ScanCode(s, i + 1, end, emit, stopAtBrace: true);
                sb.Append("{}");
                i = Math.Min(end, stop + 1);
                continue;
            }
            if (interpolated && c == '}' && i + 1 < end && s[i + 1] == '}') { sb.Append('}'); i += 2; continue; }
            sb.Append(c);
            i++;
        }
        emit(start, sb.ToString());
        return i;
    }

    private static int Unescape(string s, int i, StringBuilder sb)
    {
        var e = s[i + 1];
        switch (e)
        {
            case 'n': sb.Append('\n'); return i + 2;
            case 'r': sb.Append('\r'); return i + 2;
            case 't': sb.Append('\t'); return i + 2;
            case '0': sb.Append('\0'); return i + 2;
            case 'a': sb.Append('\a'); return i + 2;
            case 'b': sb.Append('\b'); return i + 2;
            case 'f': sb.Append('\f'); return i + 2;
            case 'v': sb.Append('\v'); return i + 2;
            case 'u':
                if (i + 6 <= s.Length && int.TryParse(s.AsSpan(i + 2, 4), System.Globalization.NumberStyles.HexNumber, null, out var u))
                { sb.Append((char)u); return i + 6; }
                break;
            case 'U':
                if (i + 10 <= s.Length && int.TryParse(s.AsSpan(i + 2, 8), System.Globalization.NumberStyles.HexNumber, null, out var big))
                { sb.Append(char.ConvertFromUtf32(big)); return i + 10; }
                break;
            case 'x':
            {
                var j = i + 2; var n = 0;
                while (j < s.Length && n < 4 && Uri.IsHexDigit(s[j])) { j++; n++; }
                if (n > 0) { sb.Append((char)Convert.ToInt32(s.Substring(i + 2, n), 16)); return j; }
                break;
            }
        }
        sb.Append(e); // \' \" \\ 以及不认识的：照抄那个字符
        return i + 2;
    }

    /// <summary>字面量前面（跳过空白）是不是 `L(`。</summary>
    private static bool IsWrapped(string s, int start)
    {
        var i = start - 1;
        while (i >= 0 && char.IsWhiteSpace(s[i])) i--;
        if (i < 0 || s[i] != '(') return false;
        i--;
        while (i >= 0 && char.IsWhiteSpace(s[i])) i--;
        if (i < 0 || s[i] != 'L') return false;
        if (i == 0) return true;
        var p = s[i - 1];
        return !(char.IsLetterOrDigit(p) || p == '_') || p == '.';
    }
}
