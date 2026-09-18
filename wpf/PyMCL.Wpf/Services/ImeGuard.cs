// i18n:ignore-file —— --ime-check 真值表的用例名是开发者看的自检输出，不是界面文案。
using System.IO;
using System.Text.Json;
using System.Windows.Input;

namespace PyMCL.Services;

/// <summary>
/// 「这一下回车该不该发送」。
///
/// 中文输入法打字时，拼音串还没上屏就敲回车，那一下是**给输入法用的**（选第一个候选词），
/// 不是要发消息。Qt 端靠 `inputMethodEvent` 的 `preeditString()` 判（app/pages/ai_page.py:494-507）；
/// WPF 这边有两个独立信号，两个都要看：
///
/// 1. `TextCompositionManager.TextInputStart/Update/End` 给出组合串（`CompositionText`），
///    对应 Qt 的 preedit；
/// 2. `KeyEventArgs.Key == Key.ImeProcessed`——按键已经被输入法吃掉了，WPF 把真实键塞在
///    `ImeProcessedKey` 里。只看第 1 条会漏：某些输入法在候选窗开着时不更新组合串。
///
/// 判定本身是纯函数，不碰控件，好让 `--ime-check` 把真值表整张跑一遍（见 <see cref="SelfTest"/>）——
/// 自动化里敲不出真键盘，那就让逻辑自己能被考。
/// </summary>
public static class ImeGuard
{
    /// <summary>按下某个键时，这一下是不是「发送」。</summary>
    /// <param name="key">WPF 报上来的键。输入法吃掉时这里是 <see cref="Key.ImeProcessed"/>。</param>
    /// <param name="imeProcessedKey">被输入法吃掉时的真实键；没被吃就是 <see cref="Key.None"/>。</param>
    /// <param name="shift">按着 Shift = 换行，不发送。</param>
    /// <param name="composition">当前输入法组合串（preedit）。非空表示拼音还没上屏。</param>
    public static bool ShouldSend(Key key, Key imeProcessedKey, bool shift, string? composition)
    {
        if (shift) return false;
        // 输入法已经接管这一下：无论它对应的是不是回车，都不是「发送」
        if (key == Key.ImeProcessed || imeProcessedKey != Key.None) return false;
        if (key is not (Key.Enter or Key.Return)) return false;
        // 组合串还在 = 拼音没上屏，这个回车是去选候选词的
        return string.IsNullOrEmpty(composition);
    }

    /// <summary>真值表自检。`PyMCL.Wpf.exe --ime-check` 走这条；全过返回 0。</summary>
    public static int SelfTest(TextWriter output)
    {
        var cases = new (string Name, Key Key, Key Ime, bool Shift, string? Comp, bool Want)[]
        {
            ("空输入框直接回车 → 发送", Key.Enter, Key.None, false, "", true),
            ("Return 键同样算发送", Key.Return, Key.None, false, null, true),
            ("Shift+Enter → 换行不发", Key.Enter, Key.None, true, "", false),
            ("拼音串未上屏时回车 → 不发", Key.Enter, Key.None, false, "nihao", false),
            ("输入法吃掉这一下 → 不发", Key.ImeProcessed, Key.Enter, false, "", false),
            ("ImeProcessedKey 有值 → 不发", Key.Enter, Key.Enter, false, "", false),
            ("组合串已上屏（清空）后回车 → 发送", Key.Enter, Key.None, false, "", true),
            ("普通字符键 → 不发", Key.A, Key.None, false, "", false),
            ("拼音串 + Shift → 不发", Key.Enter, Key.None, true, "zhongwen", false),
        };

        var rows = new List<Dictionary<string, object?>>();
        var bad = 0;
        foreach (var c in cases)
        {
            var got = ShouldSend(c.Key, c.Ime, c.Shift, c.Comp);
            var ok = got == c.Want;
            if (!ok) bad++;
            rows.Add(new Dictionary<string, object?>
            {
                ["case"] = c.Name,
                ["key"] = c.Key.ToString(),
                ["ime_processed_key"] = c.Ime.ToString(),
                ["shift"] = c.Shift,
                ["composition"] = c.Comp,
                ["want"] = c.Want,
                ["got"] = got,
                ["ok"] = ok,
            });
        }
        output.Write(JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["total"] = cases.Length,
            ["failed"] = bad,
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
