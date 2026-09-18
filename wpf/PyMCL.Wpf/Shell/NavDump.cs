using System.IO;
using System.Text.Json;

namespace PyMCL;

/// <summary>
/// 把 NavModel 对一组配置算出来的侧栏结构打印成 JSON，供 tests/test_nav_parity.py
/// 跟 Qt 版 app/main_window.py、网页版 eziapp/tests/nav_dump.ts 的结果逐条比。
///
///   echo [{"config":{"ui_nav_style":"compact"}}] | PyMCL.Wpf.exe --nav-dump
///
/// 输出形状与 nav_dump.ts 完全一致：style / items / pinned / members / sequence / unpin。
/// </summary>
public static class NavDump
{
    /// <summary>stdin / stdout 都按 UTF-8 走，不看控制台代码页——对照脚本在中文 Windows 上才读得对。</summary>
    public static int Run()
    {
        var utf8 = new System.Text.UTF8Encoding(false);
        using var input = new StreamReader(Console.OpenStandardInput(), utf8);
        using var output = new StreamWriter(Console.OpenStandardOutput(), utf8);
        return Run(input, output);
    }

    public static int Run(TextReader input, TextWriter output)
    {
        try
        {
            var text = input.ReadToEnd();
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(text) ? "[]" : text);
            var results = new List<Dictionary<string, object?>>();
            foreach (var item in doc.RootElement.EnumerateArray())
                results.Add(Describe(item));
            output.Write(JsonSerializer.Serialize(results, new JsonSerializerOptions
            {
                Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            }));
            output.Flush();
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static Dictionary<string, object?> Describe(JsonElement input)
    {
        var cfgEl = input.TryGetProperty("config", out var c) ? c : default;
        var cfg = NavConfig.FromJson(cfgEl);
        var items = NavModel.NavItemsFromConfig(cfg).Select(entry => entry.Kind switch
        {
            NavEntryKind.Item => new List<string> { "item", entry.Key, entry.Label },
            NavEntryKind.Header => new List<string> { "header", entry.Label },
            _ => new List<string> { "stretch" },
        }).ToList();
        var out_ = new Dictionary<string, object?>
        {
            ["style"] = NavModel.NavStyle(cfg),
            ["items"] = items,
            ["pinned"] = NavModel.PinnedFromConfig(cfg),
            ["members"] = NavModel.SectionMembersFromConfig(cfg),
            ["sequence"] = NavModel.SidebarSequence(cfg),
        };
        if (input.TryGetProperty("unpin", out var unpin) && unpin.ValueKind == JsonValueKind.Object)
        {
            var key = unpin.TryGetProperty("key", out var k) ? k.GetString() ?? "" : "";
            var section = unpin.TryGetProperty("section", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
            var index = unpin.TryGetProperty("index", out var i) && i.ValueKind == JsonValueKind.Number ? i.GetInt32() : -1;
            var landed = NavModel.UnpinNavConfig(cfg, key, section, index);
            out_["unpin"] = landed is null
                ? null
                : new Dictionary<string, object?>
                {
                    ["section"] = landed.Value.Section,
                    ["patch"] = NavModel.ToRpcArgs(landed.Value.Patch),
                };
        }
        return out_;
    }
}
