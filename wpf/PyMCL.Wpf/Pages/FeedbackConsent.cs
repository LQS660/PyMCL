using System.IO;
using System.Text.Json;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// 启动后的「是否上传诊断数据」提示，对齐 Qt 端 app/widgets.py prompt_feedback_consent 与
/// app/main_window.py _ask_feedback_consent：主窗口起来约 400 ms 后弹一次，选过就不再弹，
/// 状态存 config.json 的 feedback_consent（null = 还没问过；true / false = 选过；关掉弹窗按「暂不同意」算）。
///
/// 桥上 get_settings 把 feedback_consent 收成了 bool（None 也算 false），从桥上分不出「没问过」和
/// 「暂不同意」。所以「问过没有」直接读 config.json 里那个键的原始值——跟 Qt 的 fb.consent_asked()
/// 同一个键、同一个判法，三端共用一份状态。读不到文件时（桥都连上了却读不到，基本不会发生）
/// 只剩桥上那个 bool 可依：它说已同意就不问，否则问。
///
/// 判定本身是纯函数，不碰控件，好让 <c>--consent-check</c> 把真值表整张跑一遍（见 <see cref="SelfTest()"/>）。
/// </summary>
public static class FeedbackConsent
{
    /// <summary>与 Qt 的 QTimer.singleShot(400, _boot_extras) 同一个数。</summary>
    public const int DelayMs = 400;

    public const string Key = "feedback_consent";

    /// <summary>
    /// config.json 里 feedback_consent 的原始值。
    /// <see cref="Readable"/> 为 false = 文件读不到 / 不是 JSON；否则 <see cref="Value"/> 为 null 表示键缺失或为 null（没问过），
    /// true / false 表示选过。非 bool 的其它值按 Python 的口径算「问过但没同意」（is not None / is True）。
    /// </summary>
    public readonly record struct Raw(bool Readable, bool? Value);

    /// <summary>读 config.json；文件不存在 = 从没保存过配置 = 没问过。</summary>
    public static Raw ReadRaw(string? configPath)
    {
        if (string.IsNullOrWhiteSpace(configPath)) return new Raw(false, null);
        try
        {
            if (!File.Exists(configPath)) return new Raw(true, null);
            return ParseRaw(File.ReadAllText(configPath));
        }
        catch
        {
            return new Raw(false, null);
        }
    }

    /// <summary>只管解析，给自检和用例喂字符串用。</summary>
    public static Raw ParseRaw(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return new Raw(false, null);
            if (!doc.RootElement.TryGetProperty(Key, out var v)) return new Raw(true, null);
            return v.ValueKind switch
            {
                JsonValueKind.Null or JsonValueKind.Undefined => new Raw(true, null),
                JsonValueKind.True => new Raw(true, true),
                _ => new Raw(true, false),
            };
        }
        catch (JsonException)
        {
            return new Raw(false, null);
        }
    }

    /// <summary>
    /// 这次启动要不要弹。
    /// config.json 读得到：键为 null 就问（= Qt 的 not consent_asked()）；有 bool 就不问。
    /// 读不到：桥说已同意 → 肯定问过，不问；否则问。
    /// </summary>
    public static bool ShouldAsk(Raw raw, bool bridgeConsent)
    {
        if (raw.Readable) return raw.Value is null;
        return !bridgeConsent;
    }

    /// <summary>
    /// 启动时（首次运行向导之后）看一眼要不要弹。弹了就把选择写回 config.json——三端共用，
    /// Qt / 网页版下次启动也不会再问。
    /// </summary>
    public static async Task MaybeAskAsync()
    {
        var api = AppServices.Client;
        var settings = await api.TryCallAsync<Dictionary<string, JsonElement>>("get_settings", null, new()) ?? new();
        var root = settings.TryGetValue("root", out var r) && r.ValueKind == JsonValueKind.String ? r.GetString() ?? "" : "";
        var bridgeConsent = settings.TryGetValue(Key, out var c) && c.ValueKind == JsonValueKind.True;
        var raw = ReadRaw(root.Length > 0 ? Path.Combine(root, "config.json") : null);
        if (!ShouldAsk(raw, bridgeConsent)) return;

        await Task.Delay(DelayMs);
        var ok = await Dlg.Confirm(
            L("是否上传诊断数据"),
            L("第一次打开需要你亲自选择。\n\n同意后才会向开发者上传：\n· 你提交的反馈内容\n· 本机配置（CPU / 内存 / 显卡 / Java / 已装版本）\n\n暂不同意则不会上传，以后可在设置里更改。"),
            L("同意"), L("暂不同意"));
        // 关掉弹窗 = false，跟 Qt 的 bool(box.exec()) 一样：不同意也要落盘，否则下次还问
        await api.TryCallAsync<object>("save_settings", new { data = new { feedback_consent = ok } });
    }

    /// <summary>真值表自检。`PyMCL.Wpf.exe --consent-check` 走这条；全过返回 0。用例名是开发者看的自检输出，全 ASCII。</summary>
    public static int SelfTest(TextWriter output)
    {
        var parse = new (string Name, string Json, Raw Want)[]
        {
            ("empty object -> never asked", "{}", new Raw(true, null)),
            ("explicit null -> never asked", "{\"feedback_consent\": null}", new Raw(true, null)),
            ("true -> asked, consented", "{\"feedback_consent\": true, \"first_run\": false}", new Raw(true, true)),
            ("false -> asked, declined", "{\"feedback_consent\": false}", new Raw(true, false)),
            ("non-bool value counts as asked (python: is not None)", "{\"feedback_consent\": \"yes\"}", new Raw(true, false)),
            ("broken json -> unreadable", "{not json", new Raw(false, null)),
            ("json array -> unreadable", "[1,2]", new Raw(false, null)),
        };
        var decide = new (string Name, Raw Raw, bool Bridge, bool Want)[]
        {
            ("config readable, key null -> ask", new Raw(true, null), false, true),
            ("config readable, key null even if bridge says true (file wins) -> ask", new Raw(true, null), true, true),
            ("config readable, true -> no", new Raw(true, true), true, false),
            ("config readable, false (declined earlier, maybe in Qt) -> no", new Raw(true, false), false, false),
            ("config unreadable, bridge consented -> no", new Raw(false, null), true, false),
            ("config unreadable, bridge false -> ask", new Raw(false, null), false, true),
        };
        var transitions = new (string Name, bool Choice, bool Want)[]
        {
            ("after agreeing, next launch does not ask", true, false),
            ("after declining, next launch does not ask", false, false),
        };

        var rows = new List<Dictionary<string, object?>>();
        var bad = 0;
        foreach (var c in parse)
        {
            var got = ParseRaw(c.Json);
            var ok = got == c.Want;
            if (!ok) bad++;
            rows.Add(new Dictionary<string, object?>
            {
                ["case"] = c.Name, ["kind"] = "parse", ["json"] = c.Json,
                ["want"] = $"{c.Want.Readable}/{c.Want.Value?.ToString() ?? "null"}",
                ["got"] = $"{got.Readable}/{got.Value?.ToString() ?? "null"}", ["ok"] = ok,
            });
        }
        foreach (var c in decide)
        {
            var got = ShouldAsk(c.Raw, c.Bridge);
            var ok = got == c.Want;
            if (!ok) bad++;
            rows.Add(new Dictionary<string, object?>
            {
                ["case"] = c.Name, ["kind"] = "decide",
                ["readable"] = c.Raw.Readable, ["raw"] = c.Raw.Value, ["bridge_consent"] = c.Bridge,
                ["want"] = c.Want, ["got"] = got, ["ok"] = ok,
            });
        }
        foreach (var c in transitions)
        {
            // 第一次：config.json 里还是 null → 问；用户选完，save_settings 落成 bool → 再启动读到 bool → 不问
            var first = ShouldAsk(ParseRaw("{\"feedback_consent\": null}"), false);
            var saved = JsonSerializer.Serialize(new Dictionary<string, object?> { [Key] = c.Choice });
            var second = ShouldAsk(ParseRaw(saved), c.Choice);
            var ok = first && second == c.Want;
            if (!ok) bad++;
            rows.Add(new Dictionary<string, object?>
            {
                ["case"] = c.Name, ["kind"] = "transition", ["choice"] = c.Choice,
                ["first_launch_asks"] = first, ["second_launch_asks"] = second, ["want_second"] = c.Want, ["ok"] = ok,
            });
        }

        output.Write(JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["total"] = parse.Length + decide.Length + transitions.Length,
            ["failed"] = bad,
            ["delay_ms"] = DelayMs,
            ["cases"] = rows,
        }, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        }));
        output.Flush();
        return bad == 0 ? 0 : 1;
    }

    public static int SelfTest()
    {
        var utf8 = new System.Text.UTF8Encoding(false);
        using var output = new StreamWriter(Console.OpenStandardOutput(), utf8);
        return SelfTest(output);
    }
}
