using System.Text.Json;

namespace PyMCL;

/// <summary>
/// 侧栏编排：数据模型 + 纯逻辑（不碰控件，可在 --nav-dump 里直接跑）。
///
/// 与 Qt 侧 app/main_window.py 和网页版 eziapp/src/nav_model.ts 逐条对齐：
/// NavStyle / SectionMembersFromConfig / PinnedFromConfig / GroupedNavItems /
/// NavItemsFromConfig / UnpinNavConfig / PinNavConfig / ReorderNavConfig。
/// 三端读写的是同一份 config.json 的 ui_nav_* 键，算法不一致就会出现
/// 「在 Qt 里排好的侧栏，WPF 打开是另一套」这类只有用户能发现的偏差。
///
/// 键名用 Qt 那一套（account / instance / resource…），到页面路由那一步再
/// 映射成 WPF 的页面 id，见 <see cref="NavModel.PageForNavKey"/>。
/// </summary>
public sealed class NavGroup
{
    public string Title { get; set; } = "";
    public List<string> Keys { get; set; } = new();

    public NavGroup Clone() => new() { Title = Title, Keys = new List<string>(Keys) };
}

public enum NavEntryKind { Header, Stretch, Item }

public sealed record NavEntry(
    NavEntryKind Kind,
    string Key = "",
    string Label = "",
    bool Top = false,
    bool Draggable = false)
{
    public static NavEntry Header(string label) => new(NavEntryKind.Header, Label: label);
    public static readonly NavEntry Stretch = new(NavEntryKind.Stretch);
}

/// <summary>get_settings 回来的那一份里侧栏用得上的键。缺省 / 类型不对一律按「没设」处理。</summary>
public sealed class NavConfig
{
    public string? Style { get; set; }
    public List<string> Order { get; set; } = new();
    public List<string> Pinned { get; set; } = new();
    public List<string> Hidden { get; set; } = new();
    /// <summary>null = 配置里不是列表（当没设过）。</summary>
    public List<NavGroup>? Groups { get; set; }
    /// <summary>null = 配置里不是对象（当没设过）。</summary>
    public Dictionary<string, List<string>>? SectionMembers { get; set; }
    public int SidebarWidth { get; set; }

    public static NavConfig FromJson(JsonElement settings)
    {
        var cfg = new NavConfig();
        if (settings.ValueKind != JsonValueKind.Object) return cfg;
        if (settings.TryGetProperty("ui_nav_style", out var style) && style.ValueKind == JsonValueKind.String)
            cfg.Style = style.GetString();
        cfg.Order = StrList(Prop(settings, "ui_nav_order"));
        cfg.Pinned = StrList(Prop(settings, "ui_nav_pinned"));
        cfg.Hidden = StrList(Prop(settings, "ui_nav_hidden"));
        if (settings.TryGetProperty("ui_nav_groups", out var groups) && groups.ValueKind == JsonValueKind.Array)
        {
            cfg.Groups = new List<NavGroup>();
            foreach (var grp in groups.EnumerateArray())
            {
                if (grp.ValueKind != JsonValueKind.Object) continue;
                var title = grp.TryGetProperty("title", out var t) && t.ValueKind == JsonValueKind.String
                    ? (t.GetString() ?? "").Trim() : "";
                if (title.Length == 0) continue;
                cfg.Groups.Add(new NavGroup { Title = title, Keys = StrList(Prop(grp, "keys")) });
            }
        }
        if (settings.TryGetProperty("ui_section_members", out var members) && members.ValueKind == JsonValueKind.Object)
        {
            cfg.SectionMembers = new Dictionary<string, List<string>>();
            foreach (var sec in NavModel.SectionIds)
                cfg.SectionMembers[sec] = StrList(Prop(members, sec));
        }
        if (settings.TryGetProperty("ui_sidebar_width", out var w))
        {
            if (w.ValueKind == JsonValueKind.Number && w.TryGetInt32(out var n)) cfg.SidebarWidth = n;
            else if (w.ValueKind == JsonValueKind.String && int.TryParse(w.GetString(), out var m)) cfg.SidebarWidth = m;
        }
        return cfg;
    }

    private static JsonElement? Prop(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) ? v : null;

    /// <summary>对齐 TS strList：只认数组里的非空字符串，其它一律当空。</summary>
    public static List<string> StrList(JsonElement? raw)
    {
        var list = new List<string>();
        if (raw is not { ValueKind: JsonValueKind.Array } arr) return list;
        foreach (var v in arr.EnumerateArray())
            if (v.ValueKind == JsonValueKind.String && v.GetString() is { Length: > 0 } s) list.Add(s);
        return list;
    }

    public NavConfig Clone() => new()
    {
        Style = Style,
        Order = new List<string>(Order),
        Pinned = new List<string>(Pinned),
        Hidden = new List<string>(Hidden),
        Groups = Groups?.Select(g => g.Clone()).ToList(),
        SectionMembers = SectionMembers?.ToDictionary(kv => kv.Key, kv => new List<string>(kv.Value)),
        SidebarWidth = SidebarWidth,
    };

    /// <summary>把一份 patch（update_settings 要发的那一份）叠到副本上，对齐 TS 的 {...cfg, ...patch}。</summary>
    public NavConfig With(IReadOnlyDictionary<string, object?> patch)
    {
        var next = Clone();
        foreach (var (key, value) in patch)
        {
            switch (key)
            {
                case "ui_nav_style": next.Style = value as string; break;
                case "ui_nav_order": next.Order = AsList(value); break;
                case "ui_nav_pinned": next.Pinned = AsList(value); break;
                case "ui_nav_hidden": next.Hidden = AsList(value); break;
                case "ui_nav_groups":
                    next.Groups = value is IEnumerable<NavGroup> gs ? gs.Select(g => g.Clone()).ToList() : null;
                    break;
                case "ui_section_members":
                    next.SectionMembers = value is IReadOnlyDictionary<string, List<string>> sm
                        ? sm.ToDictionary(kv => kv.Key, kv => new List<string>(kv.Value))
                        : null;
                    break;
                case "ui_sidebar_width": next.SidebarWidth = value is int n ? n : 0; break;
            }
        }
        return next;
    }

    private static List<string> AsList(object? value) =>
        value is IEnumerable<string> seq ? seq.Where(s => !string.IsNullOrEmpty(s)).ToList() : new List<string>();
}

public static class NavModel
{
    public const string StyleCompact = "compact";
    public const string StyleGrouped = "grouped";
    public const string DefaultStyle = StyleGrouped;

    public static readonly IReadOnlyDictionary<string, string> StyleLabels = new Dictionary<string, string>
    {
        [StyleCompact] = L("精简（启动 / 游戏 / 版本管理）"),
        [StyleGrouped] = L("分组（账户 / 游戏 / 通用）"),
    };

    public static readonly string[] SectionIds = { "download", "more" };

    /// <summary>分区默认成员（子页归属可由 ui_section_members 自定义：哪栏、栏内顺序）。</summary>
    public static readonly IReadOnlyDictionary<string, string[]> SubDefaultMembers = new Dictionary<string, string[]>
    {
        ["download"] = new[] { "version", "mod", "modpack", "datapack", "resource", "shader", "world", "java" },
        ["more"] = new[] { "instance", "mods", "account", "multiplayer", "servers", "playtime", "feedback", "settings" },
    };

    public static readonly HashSet<string> AllSubKeys =
        new(SectionIds.SelectMany(sec => SubDefaultMembers[sec]));

    public static readonly string[] TopKeys = { "launch", "download", "ai", "more", "tasks" };

    /// <summary>子页标题。instance 这个键只剩历史含义，打开的是版本管理。</summary>
    public static readonly IReadOnlyDictionary<string, string> SubTitles = new Dictionary<string, string>
    {
        ["version"] = L("原版游戏"), ["mod"] = "Mod", ["modpack"] = L("整合包"), ["datapack"] = L("数据包"),
        ["resource"] = L("资源包"), ["shader"] = L("光影包"), ["world"] = L("世界"), ["java"] = "Java",
        ["instance"] = L("版本管理"), ["mods"] = L("模组"), ["account"] = L("账号"), ["multiplayer"] = L("联机"),
        ["servers"] = L("服务器"), ["playtime"] = L("时长"), ["feedback"] = L("反馈"), ["settings"] = L("设置"),
    };

    /// <summary>一级项标题。</summary>
    public static readonly IReadOnlyDictionary<string, string> NavSpecs = new Dictionary<string, string>
    {
        ["launch"] = L("启动"), ["download"] = L("游戏"), ["ai"] = L("AI 助手"), ["more"] = L("更多"), ["tasks"] = L("下载任务"),
    };

    public const string NavDefaultsVersion = "2026.09-ai-visible";
    public static readonly string[] DefaultNavOrder = { "launch", "download", "instance", "ai", "more", "settings", "tasks" };
    public static readonly string[] DefaultNavPinned = { "instance", "settings" };
    public static readonly string[] DefaultNavHidden = Array.Empty<string>();

    /// <summary>历史上的出厂三件套：老用户还照着上一版出厂样子用时也算「没动过」。</summary>
    private static readonly Dictionary<string, string[]>[] LegacyNavFactories =
    {
        new()
        {
            ["ui_nav_order"] = new[] { "launch", "download", "instance", "more", "settings", "tasks" },
            ["ui_nav_pinned"] = new[] { "instance", "settings" },
            ["ui_nav_hidden"] = new[] { "ai" },
        },
    };

    /// <summary>这些键排在分隔线以下，靠侧栏底部。</summary>
    public static readonly string[] BottomKeys = { "ai", "more", "settings", "tasks" };

    public static readonly (string Title, string[] Keys)[] GroupedNav =
    {
        (L("账户"), new[] { "account" }),
        (L("游戏"), new[] { "launch", "instance", "download" }),
        (L("通用"), new[] { "settings", "multiplayer", "ai", "more", "tasks" }),
    };

    /// <summary>组里另用的名字：「游戏」组底下再写一项「游戏」会读成套娃。</summary>
    public static readonly IReadOnlyDictionary<string, string> GroupedLabels = new Dictionary<string, string>
    {
        ["download"] = L("下载"), ["multiplayer"] = L("多人联机"),
    };

    /// <summary>侧栏键 → WPF 页面 id。download / more 是分区，没有页面。</summary>
    public static readonly IReadOnlyDictionary<string, string> PageForNavKey = new Dictionary<string, string>
    {
        ["launch"] = "launch", ["ai"] = "ai", ["tasks"] = "tasks",
        ["version"] = "version", ["mod"] = "mod", ["modpack"] = "modpack", ["datapack"] = "datapack",
        ["resource"] = "resourcepack", ["shader"] = "shader", ["world"] = "world", ["java"] = "java",
        ["instance"] = "instance", ["mods"] = "mods", ["account"] = "account", ["multiplayer"] = "multiplayer",
        ["servers"] = "servers", ["playtime"] = "playtime", ["feedback"] = "feedback", ["settings"] = "settings",
    };

    public static bool IsTop(string key) => Array.IndexOf(TopKeys, key) >= 0;
    public static bool IsSection(string key) => Array.IndexOf(SectionIds, key) >= 0;

    public static string NavStyle(NavConfig? cfg)
    {
        var style = cfg?.Style ?? "";
        return StyleLabels.ContainsKey(style) ? style : DefaultStyle;
    }

    public static string NavLabel(string key) =>
        NavSpecs.TryGetValue(key, out var l) ? l : SubTitles.TryGetValue(key, out var s) ? s : key;

    /// <summary>
    /// 读 ui_section_members：{download: [key…], more: [key…]}。
    /// 非法键剔除、重复去重、漏掉的子页按默认归属补齐，顺序保留用户排列。
    /// </summary>
    public static Dictionary<string, List<string>> SectionMembersFromConfig(NavConfig? cfg)
    {
        var pinned = new HashSet<string>(PinnedFromConfig(cfg));
        var result = SectionIds.ToDictionary(s => s, _ => new List<string>());
        var seen = new HashSet<string>();
        foreach (var sec in SectionIds)
        {
            var keys = cfg?.SectionMembers != null && cfg.SectionMembers.TryGetValue(sec, out var l) ? l : null;
            foreach (var k in keys ?? new List<string>())
            {
                // 固定到侧栏的子页不属于任何分区（拖出去 = 移动），配置里残留的成员记录也一并忽略
                if (AllSubKeys.Contains(k) && !seen.Contains(k) && !pinned.Contains(k))
                {
                    seen.Add(k);
                    result[sec].Add(k);
                }
            }
        }
        foreach (var sec in SectionIds)
        {
            foreach (var k in SubDefaultMembers[sec])
            {
                if (!seen.Contains(k) && !pinned.Contains(k))
                {
                    seen.Add(k);
                    result[sec].Add(k);
                }
            }
        }
        return result;
    }

    public static string DefaultSectionFor(string key)
    {
        foreach (var sec in SectionIds)
            if (SubDefaultMembers[sec].Contains(key)) return sec;
        return "more";
    }

    /// <summary>
    /// 分组排法的分组与成员：用户拖过就以 ui_nav_groups 为准，没动过用出厂的。
    /// 一级键缺席要补回来——漏掉它就等于这一页在界面上彻底没了入口。
    /// </summary>
    public static List<NavGroup> GroupedLayout(NavConfig? cfg)
    {
        var groups = new List<NavGroup>();
        var seen = new HashSet<string>();
        if (cfg?.Groups != null)
        {
            foreach (var grp in cfg.Groups)
            {
                var title = (grp.Title ?? "").Trim();
                if (title.Length == 0) continue;
                var keys = new List<string>();
                foreach (var k in grp.Keys)
                {
                    if (string.IsNullOrEmpty(k)) continue;
                    if (!IsTop(k) && !AllSubKeys.Contains(k)) continue;
                    if (!seen.Add(k)) continue;
                    keys.Add(k);
                }
                groups.Add(new NavGroup { Title = title, Keys = keys });
            }
        }
        if (!groups.Any(g => g.Keys.Count > 0))
            return GroupedNav.Select(g => new NavGroup { Title = g.Title, Keys = new List<string>(g.Keys) }).ToList();
        var missing = TopKeys.Where(k => !seen.Contains(k)).ToList();
        if (missing.Count > 0) groups[groups.Count - 1].Keys.AddRange(missing);
        return groups;
    }

    /// <summary>分组表写回配置用的那一份。</summary>
    public static Dictionary<string, object?> GroupedLayoutPatch(List<NavGroup> groups) => new()
    {
        ["ui_nav_groups"] = groups.Select(g => g.Clone()).ToList(),
    };

    /// <summary>把 key 挪到 target 的前/后（可跨组）。目标不在表里就原样不动。</summary>
    public static bool MoveWithinGroups(List<NavGroup> groups, string key, string target, bool before)
    {
        // 先确认目标存在再摘 key：反过来写的话，一次失败的拖拽就能让这一项消失
        if (key == target || !groups.Any(g => g.Keys.Contains(target))) return false;
        foreach (var group in groups) group.Keys.Remove(key);
        foreach (var group in groups)
        {
            var at = group.Keys.IndexOf(target);
            if (at >= 0)
            {
                group.Keys.Insert(at + (before ? 0 : 1), key);
                return true;
            }
        }
        return false;
    }

    /// <summary>固定到顶级侧栏的分区子页 key（拖拽固定，非法键过滤）。</summary>
    public static List<string> PinnedFromConfig(NavConfig? cfg)
    {
        var hidden = new HashSet<string>(cfg?.Hidden ?? new List<string>());
        if (NavStyle(cfg) == StyleGrouped)
        {
            // 分组排法的固定项就是各组里的子页成员，ui_nav_pinned 在这一档不参与
            return GroupedLayout(cfg).SelectMany(g => g.Keys)
                .Where(k => AllSubKeys.Contains(k) && !hidden.Contains(k)).ToList();
        }
        var picked = new List<string>();
        var seen = new HashSet<string>();
        foreach (var k in cfg?.Pinned ?? new List<string>())
            if (AllSubKeys.Contains(k) && seen.Add(k)) picked.Add(k);
        return picked;
    }

    private static NavEntry ItemEntry(string key, string label, bool draggable) =>
        new(NavEntryKind.Item, key, label, IsTop(key), draggable);

    /// <summary>HMCL 式分组侧栏。隐藏项照 ui_nav_hidden 走，整组空了连标题一起不出。</summary>
    public static List<NavEntry> GroupedNavItems(NavConfig? cfg)
    {
        var hidden = new HashSet<string>(cfg?.Hidden ?? new List<string>());
        var items = new List<NavEntry>();
        foreach (var group in GroupedLayout(cfg))
        {
            var visible = group.Keys.Where(k => !hidden.Contains(k)).ToList();
            if (visible.Count == 0) continue;
            items.Add(NavEntry.Header(group.Title));
            foreach (var key in visible)
                items.Add(ItemEntry(key, GroupedLabels.TryGetValue(key, out var gl) ? gl : NavLabel(key), false));
        }
        return items;
    }

    /// <summary>
    /// 生成侧栏条目：一级项与固定的分区子页按 ui_nav_order 混排。
    /// ui_nav_order 是完整序列（可同时含一级键和固定子页键）；没进序列的固定
    /// 子页插在「更多」前（都不在则插在「下载任务」前 / 末尾），一级键缺失自动补到末尾。
    /// </summary>
    public static List<NavEntry> NavItemsFromConfig(NavConfig? cfg)
    {
        if (NavStyle(cfg) == StyleGrouped) return GroupedNavItems(cfg);
        var raw = cfg?.Order ?? new List<string>();
        var pinned = PinnedFromConfig(cfg);
        var hidden = new HashSet<string>(cfg?.Hidden ?? new List<string>());
        var order = new List<string>();
        foreach (var k in raw)
        {
            if (IsTop(k) && !order.Contains(k)) order.Add(k);
            else if (pinned.Contains(k) && !order.Contains(k)) order.Add(k);
        }
        foreach (var k in TopKeys) if (!order.Contains(k)) order.Add(k);
        // 缺席的固定子页：插到锚点前
        var late = pinned.Where(k => !order.Contains(k)).ToList();
        if (late.Count > 0)
        {
            var anchor = new[] { "more", "tasks" }.FirstOrDefault(a => order.Contains(a));
            if (anchor != null) order.InsertRange(order.IndexOf(anchor), late);
            else order.AddRange(late);
        }
        var visible = order.Where(k => !(IsTop(k) && hidden.Contains(k))).ToList();
        // 分隔线插在第一个「底部键」之前，它和它后面的都被推到侧栏最下方
        var splitAt = visible.FindIndex(k => BottomKeys.Contains(k));
        if (splitAt <= 0) splitAt = -1;
        var items = new List<NavEntry>();
        for (var i = 0; i < visible.Count; i++)
        {
            if (i == splitAt) items.Add(NavEntry.Stretch);
            items.Add(ItemEntry(visible[i], NavLabel(visible[i]), true));
        }
        return items;
    }

    private static Dictionary<string, string[]> NavFactory() => new()
    {
        ["ui_nav_order"] = DefaultNavOrder,
        ["ui_nav_pinned"] = DefaultNavPinned,
        ["ui_nav_hidden"] = DefaultNavHidden,
    };

    /// <summary>侧栏还是某一版出厂那一套（没排过、没藏过、没另外固定过）。</summary>
    public static bool NavUntouched(NavConfig? cfg)
    {
        var stored = new Dictionary<string, List<string>>
        {
            ["ui_nav_order"] = cfg?.Order ?? new List<string>(),
            ["ui_nav_pinned"] = cfg?.Pinned ?? new List<string>(),
            ["ui_nav_hidden"] = cfg?.Hidden ?? new List<string>(),
        };
        return new[] { NavFactory() }.Concat(LegacyNavFactories).Any(factory =>
            factory.All(kv =>
            {
                var seq = stored[kv.Key];
                return seq.Count == 0 || seq.SequenceEqual(kv.Value);
            }));
    }

    /// <summary>出厂侧栏（「恢复默认侧栏」与首次写入都用它）。</summary>
    public static Dictionary<string, object?> DefaultNavPatch() => new()
    {
        ["ui_nav_order"] = DefaultNavOrder.ToList(),
        ["ui_nav_pinned"] = DefaultNavPinned.ToList(),
        ["ui_nav_hidden"] = DefaultNavHidden.ToList(),
        ["ui_nav_style"] = DefaultStyle,
        ["ui_nav_defaults"] = NavDefaultsVersion,
        ["ui_nav_groups"] = null,
        ["ui_section_members"] = null,
    };

    /// <summary>侧栏上真点得进去的分区。被隐藏的分区等于不存在。</summary>
    public static List<string> VisibleSections(NavConfig? cfg)
    {
        var keys = new HashSet<string>(NavItemsFromConfig(cfg)
            .Where(it => it.Kind == NavEntryKind.Item).Select(it => it.Key));
        return SectionIds.Where(keys.Contains).ToList();
    }

    /// <summary>
    /// 取消固定并把子页写回某个分区，返回它真正落到的分区（null = 没做）。
    /// 落点只能是侧栏上点得进去的分区——放回一个被隐藏的分区，这一页在界面上
    /// 就彻底消失了；两个分区都藏着时把落点那个放出来，否则它落地即失踪。
    /// </summary>
    public static (Dictionary<string, object?> Patch, string Section)? UnpinNavConfig(
        NavConfig? cfg, string key, string? backSection = null, int index = -1)
    {
        var pinned = PinnedFromConfig(cfg);
        if (!pinned.Contains(key)) return null;
        var nextPinned = pinned.Where(k => k != key).ToList();
        var patch = new Dictionary<string, object?>();
        NavConfig probe;
        var baseCfg = cfg ?? new NavConfig();
        if (NavStyle(cfg) == StyleGrouped)
        {
            // 分组档的固定项就是组成员，从组里摘掉才算取消固定
            var groups = GroupedLayout(cfg);
            foreach (var group in groups) group.Keys.Remove(key);
            foreach (var (k, v) in GroupedLayoutPatch(groups)) patch[k] = v;
            probe = baseCfg.With(patch);
        }
        else
        {
            patch["ui_nav_pinned"] = nextPinned;
            probe = baseCfg.With(new Dictionary<string, object?> { ["ui_nav_pinned"] = nextPinned });
        }
        // 固定项不属于任何分区，成员表必须在改完 pinned 之后再读
        var members = SectionMembersFromConfig(probe);
        var dest = backSection != null && IsSection(backSection)
            ? backSection
            // 没指定就回它现在的归属（用户在「自定义分区」里挪过的以那份为准）
            : SectionIds.FirstOrDefault(sec => members[sec].Contains(key)) ?? DefaultSectionFor(key);
        var at = index;
        var visible = VisibleSections(probe);
        if (!visible.Contains(dest))
        {
            if (visible.Count > 0)
            {
                dest = visible[0];
                at = -1; // 换了个家，原来那个落点位序没有意义
            }
            else
            {
                patch["ui_nav_hidden"] = (cfg?.Hidden ?? new List<string>()).Where(k => k != dest).ToList();
            }
        }
        var nextMembers = SectionIds.ToDictionary(
            sec => sec, sec => members[sec].Where(k => k != key).ToList());
        var bucket = nextMembers[dest];
        bucket.Insert(at >= 0 && at <= bucket.Count ? at : bucket.Count, key);
        patch["ui_section_members"] = nextMembers;
        return (patch, dest);
    }

    /// <summary>当前侧栏的可见序列（一级项 + 固定子页，按显示顺序）。</summary>
    public static List<string> SidebarSequence(NavConfig? cfg) =>
        NavItemsFromConfig(cfg).Where(it => it.Kind == NavEntryKind.Item).Select(it => it.Key).ToList();

    /// <summary>
    /// 把一整条侧栏序列写回配置（对齐 Qt _write_sidebar_sequence）。
    /// ui_nav_order 存位置（一级键 + 固定子页的真实序列），ui_nav_pinned 只记哪些子页被固定。
    /// </summary>
    public static Dictionary<string, object?> WriteSidebarSequence(IEnumerable<string> seq)
    {
        var seen = new HashSet<string>();
        var clean = seq.Where(k => (IsTop(k) || AllSubKeys.Contains(k)) && seen.Add(k)).ToList();
        foreach (var k in TopKeys) if (!clean.Contains(k)) clean.Add(k);
        return new Dictionary<string, object?>
        {
            ["ui_nav_order"] = clean,
            ["ui_nav_pinned"] = clean.Where(AllSubKeys.Contains).ToList(),
        };
    }

    /// <summary>
    /// 侧栏内拖动排序：把 key 挪到 target 之前 / 之后（对齐 Qt _on_sidebar_reorder）。
    /// 分组档挪的是 ui_nav_groups 里的成员（可跨组），精简档挪的是混合序列。
    /// </summary>
    public static Dictionary<string, object?>? ReorderNavConfig(NavConfig? cfg, string key, string target, bool before)
    {
        if (NavStyle(cfg) == StyleGrouped)
        {
            var groups = GroupedLayout(cfg);
            return MoveWithinGroups(groups, key, target, before) ? GroupedLayoutPatch(groups) : null;
        }
        var seq = SidebarSequence(cfg);
        if (key == target || !seq.Contains(key) || !seq.Contains(target)) return null;
        seq.Remove(key);
        seq.Insert(seq.IndexOf(target) + (before ? 0 : 1), key);
        return WriteSidebarSequence(seq);
    }

    public sealed record PinResult(Dictionary<string, object?>? Patch, string? Error);

    /// <summary>
    /// 固定一个分区子页到侧栏（移动语义：原分区里不再显示）。
    /// 对齐 Qt _pin_nav_at / _take_from_section：分区只剩这一个子页时拒绝，移走会变空栏。
    /// 返回 null = 没做（不是子页 / 已固定）。
    /// </summary>
    public static PinResult? PinNavConfig(NavConfig? cfg, string key, string? target = null, bool before = true)
    {
        if (!AllSubKeys.Contains(key)) return null;
        if (PinnedFromConfig(cfg).Contains(key)) return null;
        var members = SectionMembersFromConfig(cfg);
        var from = SectionIds.FirstOrDefault(sec => members[sec].Contains(key));
        if (from != null && members[from].Count <= 1)
            return new PinResult(null, L("该分区只剩这一个子页，移走会变空栏；先在「自定义分区」里补充其它子页"));
        var patch = new Dictionary<string, object?>();
        if (NavStyle(cfg) == StyleGrouped)
        {
            // 分组档没有独立的固定项列表：进侧栏 = 进某个组
            var groups = GroupedLayout(cfg);
            var anchor = target != null && groups.Any(g => g.Keys.Contains(target)) ? target : "more";
            var landed = MoveWithinGroups(groups, key, anchor, anchor == target ? before : true);
            if (!landed) groups[groups.Count - 1].Keys.Add(key);
            foreach (var (k, v) in GroupedLayoutPatch(groups)) patch[k] = v;
        }
        else
        {
            var seq = SidebarSequence(cfg);
            var anchor = target != null && seq.Contains(target)
                ? target : seq.Contains("more") ? "more" : null;
            if (anchor != null) seq.Insert(seq.IndexOf(anchor) + (anchor == target && !before ? 1 : 0), key);
            else seq.Add(key);
            foreach (var (k, v) in WriteSidebarSequence(seq)) patch[k] = v;
        }
        if (from != null)
        {
            patch["ui_section_members"] = SectionIds.ToDictionary(
                sec => sec, sec => members[sec].Where(k => k != key).ToList());
        }
        return new PinResult(patch, null);
    }

    /// <summary>
    /// 侧栏编辑器按「确定」时要写回的那一份（对齐 Qt SidebarEditorDialog.accept）：
    /// 一级键换成对话框里的新顺序，固定子页保持它们当前在侧栏里的相对位置。
    /// </summary>
    public static List<string> MergeNavOrder(NavConfig? cfg, IEnumerable<string> topOrder, IReadOnlyCollection<string> pinned)
    {
        var current = SidebarSequence(cfg);
        var rest = new Queue<string>(topOrder);
        var merged = new List<string>();
        foreach (var k in current)
        {
            if (AllSubKeys.Contains(k))
            {
                if (pinned.Contains(k)) merged.Add(k);
            }
            else if (rest.Count > 0) merged.Add(rest.Dequeue());
        }
        merged.AddRange(rest);
        foreach (var k in pinned) if (!merged.Contains(k)) merged.Add(k);
        return merged;
    }

    /// <summary>把 patch 转成 update_settings 能收的形状（NavGroup → {title, keys}）。</summary>
    public static Dictionary<string, object?> ToRpcArgs(IReadOnlyDictionary<string, object?> patch)
    {
        var out_ = new Dictionary<string, object?>();
        foreach (var (key, value) in patch)
        {
            out_[key] = value switch
            {
                IEnumerable<NavGroup> groups => groups
                    .Select(g => new Dictionary<string, object?> { ["title"] = g.Title, ["keys"] = new List<string>(g.Keys) })
                    .ToList(),
                _ => value,
            };
        }
        return out_;
    }
}
