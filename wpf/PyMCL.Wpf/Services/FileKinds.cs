using System.IO;
using System.IO.Compression;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PyMCL.Services;

/// <summary>
/// 认一认用户拖进来的是什么东西。口径照搬 Qt 端 app/file_kinds.py 与
/// app/pages/modpack_drop.py 的 probe：尽量看内容不看后缀，改过名的 .mrpack、
/// CurseForge 导出的 zip、只换了扩展名的资源包都认得出来。
///
/// 一个文件同时像两样东西时（64x64 的 PNG 既可能是皮肤也可能是壁纸），两种都列出来
/// 交给用户挑——猜错比多问一句烦人得多。
///
/// 这里只做判定，不碰界面也不落盘；怎么分派见 FileDrop。
/// 判定必须在前端做：桥上没有「认一个任意文件」的 RPC，Qt 端同样是在前端认的。
/// </summary>
public static class FileKinds
{
    public const string Modpack = "modpack";
    public const string Mod = "mod";
    public const string ResourcePack = "resourcepack";
    public const string ShaderPack = "shaderpack";
    public const string DataPack = "datapack";
    public const string World = "world";
    public const string Skin = "skin";
    public const string Wallpaper = "wallpaper";

    /// <summary>拿不准时给用户看的选项顺序，也是「全都不像」时的兜底菜单。</summary>
    public static readonly string[] AllKinds =
        { Modpack, Mod, ResourcePack, ShaderPack, DataPack, World, Skin, Wallpaper };

    public static readonly string[] VideoSuffixes = { ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv" };
    public static readonly string[] ImageSuffixes = { ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif" };

    private static readonly Dictionary<string, string> Labels = new()
    {
        [Modpack] = L("整合包"), [Mod] = L("模组"), [ResourcePack] = L("资源包"), [ShaderPack] = L("光影包"),
        [DataPack] = L("数据包"), [World] = L("存档"), [Skin] = L("离线皮肤"), [Wallpaper] = L("启动器壁纸"),
    };

    /// <summary>选项旁边那句「选了会发生什么」。</summary>
    private static readonly Dictionary<string, string> Actions = new()
    {
        [Modpack] = L("装成一个新版本"), [Mod] = L("装进当前版本的 mods"),
        [ResourcePack] = L("装进 resourcepacks"), [ShaderPack] = L("装进 shaderpacks"),
        [DataPack] = L("装进 datapacks"), [World] = L("装进存档列表"),
        [Skin] = L("设为离线账号的皮肤"), [Wallpaper] = L("设为启动器背景"),
    };

    public static string Label(string kind) => Labels.GetValueOrDefault(kind) ?? kind;
    public static string Action(string kind) => Actions.GetValueOrDefault(kind) ?? "";

    /// <summary>皮肤贴图只有这两种尺寸，跟 mclauncher/skin.py 的 VALID_SIZES 同一套。</summary>
    private static readonly (int W, int H)[] SkinSizes = { (64, 64), (64, 32) };

    // 目录当包看时只扫这么深、这么多条：拖进来的可能是一整个 .minecraft
    private const int ScanDepth = 3;
    private const int ScanLimit = 4000;
    private const int MaxNest = 3;

    public static bool IsVideo(string path) =>
        VideoSuffixes.Contains(Path.GetExtension(path ?? "").ToLowerInvariant());

    public static bool IsImage(string path) =>
        ImageSuffixes.Contains(Path.GetExtension(path ?? "").ToLowerInvariant());

    public static bool IsWallpaper(string path) => IsVideo(path) || IsImage(path);

    /// <summary>认一下这是什么。Kinds 里最像的在前；Sure=true 表示可以直接照办。</summary>
    public sealed class Verdict
    {
        public string Path { get; init; } = "";
        public string Name { get; init; } = "";
        public List<string> Kinds { get; init; } = new();
        public bool Sure { get; init; }
        public string Detail { get; init; } = "";

        /// <summary>候选完全相同的一批可以合并成一次提问。</summary>
        public string KindSig => string.Join(",", Kinds);
    }

    public static Verdict Identify(string path)
    {
        var name = Path.GetFileName(path);
        if (string.IsNullOrEmpty(name)) name = path;
        Verdict Make(IEnumerable<string>? kinds = null, bool sure = false, string detail = "") => new()
        {
            Path = path, Name = name, Kinds = kinds?.ToList() ?? new List<string>(), Sure = sure, Detail = detail,
        };

        var isDir = Directory.Exists(path);
        if (!isDir && !File.Exists(path)) return Make(detail: L("这个路径不存在"));
        var suffix = Path.GetExtension(path).ToLowerInvariant();

        if (!isDir)
        {
            if (VideoSuffixes.Contains(suffix))
                return Make(new[] { Wallpaper }, true, L("视频 · 可以当动态壁纸"));
            if (ImageSuffixes.Contains(suffix))
            {
                var size = suffix == ".png" ? PngSize(path) : null;
                if (size is { } s && SkinSizes.Contains(s))
                    // 皮肤贴图也是一张能当壁纸的 PNG，光看文件分不出来
                    return Make(new[] { Skin, Wallpaper }, false, L("{0}x{1} 的 PNG，尺寸正好是皮肤贴图", s.W, s.H));
                return Make(new[] { Wallpaper }, true, L("图片"));
            }
            // jar 先判：它也是个 zip，交给整合包那套探针只是白读一遍
            if (suffix == ".jar") return IdentifyJar(path, Make);
        }

        var pack = ModpackProbe.Probe(path);
        if (pack != null)
            return Make(new[] { Modpack }, true,
                $"{pack.Format} · Minecraft {(string.IsNullOrEmpty(pack.McVersion) ? L("未知版本") : pack.McVersion)}");

        var names = EntryNames(path);
        if (names is null) return Make(detail: L("打不开，也认不出是什么"));
        return IdentifyArchive(names, Make);
    }

    private static Verdict IdentifyJar(string path, Func<IEnumerable<string>?, bool, string, Verdict> make)
    {
        var names = EntryNames(path) ?? new List<string>();
        var flat = names.ToHashSet(StringComparer.Ordinal);
        if (flat.Contains("install_profile.json"))
            // Forge / NeoForge 的安装器：装加载器要走「原版游戏」页，丢进 mods 只会启动失败
            return make(null, false, L("这是加载器安装器，不是模组；装加载器请到「原版游戏」页"));
        string[] marks =
        {
            "fabric.mod.json", "quilt.mod.json", "meta-inf/mods.toml",
            "meta-inf/neoforge.mods.toml", "mcmod.info",
        };
        return marks.Any(flat.Contains)
            ? make(new[] { Mod }, true, L("Minecraft 模组"))
            : make(new[] { Mod }, false, L("jar 包，但里面没有模组描述文件"));
    }

    /// <summary>压缩包 / 目录：按里面有什么认。</summary>
    private static Verdict IdentifyArchive(List<string> names, Func<IEnumerable<string>?, bool, string, Verdict> make)
    {
        if (HasEntry(names, "level.dat")) return make(new[] { World }, true, L("带 level.dat，是一个存档"));
        if (HasDir(names, "shaders")) return make(new[] { ShaderPack }, true, L("带 shaders 目录"));
        if (HasEntry(names, "pack.mcmeta"))
        {
            bool assets = HasDir(names, "assets"), data = HasDir(names, "data");
            if (assets && !data) return make(new[] { ResourcePack }, true, L("带 pack.mcmeta 与 assets"));
            if (data && !assets) return make(new[] { DataPack }, true, L("带 pack.mcmeta 与 data"));
            return make(new[] { ResourcePack, DataPack }, false, L("有 pack.mcmeta，但资源包和数据包的目录都在"));
        }
        return make(null, false, L("压缩包里没有认得出来的标志文件"));
    }

    // ---------------------------------------------------------------- 读取工具
    /// <summary>只读 PNG 头拿宽高。不是 PNG、读不动都返回 null。</summary>
    private static (int W, int H)? PngSize(string path)
    {
        try
        {
            using var fs = File.OpenRead(path);
            Span<byte> head = stackalloc byte[24];
            if (fs.Read(head) < 24) return null;
            ReadOnlySpan<byte> magic = new byte[] { 0x89, (byte)'P', (byte)'N', (byte)'G', 0x0D, 0x0A, 0x1A, 0x0A };
            if (!head[..8].SequenceEqual(magic)) return null;
            if (head[12] != 'I' || head[13] != 'H' || head[14] != 'D' || head[15] != 'R') return null;
            var w = (head[16] << 24) | (head[17] << 16) | (head[18] << 8) | head[19];
            var h = (head[20] << 24) | (head[21] << 16) | (head[22] << 8) | head[23];
            return (w, h);
        }
        catch { return null; }
    }

    /// <summary>包里（或目录里）的相对路径，统一成小写正斜杠。读不了返回 null。</summary>
    internal static List<string>? EntryNames(string path)
    {
        if (Directory.Exists(path)) return WalkNames(path);
        try
        {
            using var zip = ZipFile.OpenRead(path);
            return zip.Entries.Take(ScanLimit)
                .Select(e => e.FullName.Replace('\\', '/').ToLowerInvariant())
                .ToList();
        }
        catch { return null; }
    }

    private static List<string> WalkNames(string root)
    {
        var outp = new List<string>();
        void Walk(string dir, int depth, string prefix)
        {
            if (outp.Count >= ScanLimit) return;
            IEnumerable<string> entries;
            try { entries = Directory.EnumerateFileSystemEntries(dir); }
            catch { return; }
            foreach (var e in entries)
            {
                if (outp.Count >= ScanLimit) return;
                var name = Path.GetFileName(e);
                outp.Add(prefix + name.ToLowerInvariant());
                // 再深就不看了，标志文件都在前两层
                if (depth + 1 < ScanDepth && Directory.Exists(e))
                    Walk(e, depth + 1, prefix + name.ToLowerInvariant() + "/");
            }
        }
        Walk(root, 0, "");
        return outp;
    }

    /// <summary>
    /// 根目录、或恰好裹了一层目录的位置上有这个文件。只认前两层：
    /// 资源包里 assets/minecraft/… 底下也可能躺着同名文件，按「任意深度」判会把一堆包认错。
    /// </summary>
    private static bool HasEntry(List<string> names, string target) =>
        names.Any(n => n.Split('/').Last() == target && n.Count(c => c == '/') <= 1);

    private static bool HasDir(List<string> names, string target) =>
        names.Any(n => n.Split('/').Take(2).Contains(target));

    // ================================================================
    /// <summary>整合包判定：mrpack / CurseForge / 直接压缩的 .minecraft 目录。</summary>
    public static class ModpackProbe
    {
        // 直接压缩的 .minecraft 目录：靠这几个标志性子目录认
        private static readonly HashSet<string> PlainMarkers = new()
            { "mods", "config", "versions", "saves", "resourcepacks", "shaderpacks" };

        private static readonly Dictionary<string, string> LoaderLabels = new()
        {
            ["forge"] = "Forge", ["neoforge"] = "NeoForge", ["fabric"] = "Fabric",
            ["fabric-loader"] = "Fabric", ["quilt"] = "Quilt", ["quilt-loader"] = "Quilt",
            ["liteloader"] = "LiteLoader",
        };

        public sealed class Info
        {
            public string Kind = "";
            public string Format = "";
            public string Name = "";
            public string Version = "";
            public string McVersion = "";
            public string Loader = "";
            public string LoaderVersion = "";
            public int Files;
            public string Path = "";
        }

        public static string LoaderLabel(string? loader, string version = "")
        {
            if (string.IsNullOrEmpty(loader)) return L("原版（未声明加载器）");
            var name = LoaderLabels.GetValueOrDefault(loader.ToLowerInvariant()) ?? loader;
            return string.IsNullOrEmpty(version) ? name : $"{name} {version}";
        }

        /// <summary>认一下这东西是不是整合包，不是就返回 null。只看内容不看后缀。</summary>
        public static Info? Probe(string path)
        {
            var isDir = Directory.Exists(path);
            if (!isDir && !File.Exists(path)) return null;
            var names = EntryNames(path);
            if (names is null) return null;

            Func<string, byte[]?> reader = isDir
                ? rel => TryRead(Path.Combine(path, rel.Replace('/', Path.DirectorySeparatorChar)))
                : rel => TryReadZip(path, rel);

            var info = ProbeMrpack(names, reader) ?? ProbeCurseForge(names, reader) ?? ProbePlain(names);
            if (info is null) return null;
            info.Path = path;
            if (string.IsNullOrEmpty(info.Name))
                info.Name = isDir ? Path.GetFileName(path.TrimEnd(Path.DirectorySeparatorChar))
                                  : Path.GetFileNameWithoutExtension(path);
            if (isDir) info.Format += L(" · 已解开的目录");
            return info;
        }

        private static byte[]? TryRead(string full)
        {
            try { return File.Exists(full) ? File.ReadAllBytes(full) : null; }
            catch { return null; }
        }

        private static byte[]? TryReadZip(string archive, string rel)
        {
            try
            {
                using var zip = ZipFile.OpenRead(archive);
                var entry = zip.Entries.FirstOrDefault(e =>
                    string.Equals(e.FullName.Replace('\\', '/'), rel, StringComparison.OrdinalIgnoreCase));
                if (entry is null) return null;
                using var s = entry.Open();
                using var ms = new MemoryStream();
                s.CopyTo(ms);
                return ms.ToArray();
            }
            catch { return null; }
        }

        /// <summary>在包里找标志文件，返回最浅的那个成员名；找不到给 null。</summary>
        private static string? Member(List<string> names, string marker)
        {
            string? best = null;
            foreach (var n in names)
            {
                var parts = n.Split('/');
                if (parts[^1] != marker || parts.Length > MaxNest + 1) continue;
                if (best is null || parts.Length < best.Split('/').Length) best = n;
            }
            return best;
        }

        private static JsonElement? ReadJson(Func<string, byte[]?> reader, string member)
        {
            var raw = reader(member);
            if (raw is null || raw.Length == 0) return null;
            try
            {
                // utf-8-sig：Windows 上导出的 manifest 常带 BOM
                var span = raw.Length >= 3 && raw[0] == 0xEF && raw[1] == 0xBB && raw[2] == 0xBF
                    ? raw.AsSpan(3) : raw.AsSpan();
                using var doc = JsonDocument.Parse(span.ToArray());
                return doc.RootElement.Clone();
            }
            catch { return null; }
        }

        private static string Str(JsonElement el, string key) =>
            el.ValueKind == JsonValueKind.Object && el.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? "" : "";

        private static Info? ProbeMrpack(List<string> names, Func<string, byte[]?> reader)
        {
            var member = Member(names, "modrinth.index.json");
            if (member is null) return null;
            var idx = ReadJson(reader, member);
            if (idx is not { ValueKind: JsonValueKind.Object } root) return null;
            var deps = root.TryGetProperty("dependencies", out var d) && d.ValueKind == JsonValueKind.Object
                ? d : default;
            string loader = "";
            foreach (var k in new[] { "forge", "neoforge", "fabric-loader", "quilt-loader" })
                if (deps.ValueKind == JsonValueKind.Object && !string.IsNullOrEmpty(Str(deps, k))) { loader = k; break; }
            return new Info
            {
                Kind = "mrpack",
                Format = "Modrinth .mrpack",
                Name = Str(root, "name"),
                Version = Str(root, "versionId"),
                McVersion = deps.ValueKind == JsonValueKind.Object ? Str(deps, "minecraft") : "",
                Loader = loader,
                LoaderVersion = loader.Length > 0 ? Str(deps, loader) : "",
                Files = root.TryGetProperty("files", out var f) && f.ValueKind == JsonValueKind.Array ? f.GetArrayLength() : 0,
            };
        }

        private static Info? ProbeCurseForge(List<string> names, Func<string, byte[]?> reader)
        {
            var member = Member(names, "manifest.json");
            if (member is null) return null;
            var mf = ReadJson(reader, member);
            if (mf is not { ValueKind: JsonValueKind.Object } root) return null;
            // 模组自己也可能带 manifest.json，但不会有 minecraft 这一段
            if (!root.TryGetProperty("minecraft", out var mc) || mc.ValueKind != JsonValueKind.Object) return null;

            var loader = "";
            var loaderVersion = "";
            if (mc.TryGetProperty("modLoaders", out var ml) && ml.ValueKind == JsonValueKind.Array)
            {
                var rows = ml.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.Object).ToList();
                var primary = rows.FirstOrDefault(x =>
                    x.TryGetProperty("primary", out var p) && p.ValueKind == JsonValueKind.True);
                if (primary.ValueKind != JsonValueKind.Object && rows.Count > 0) primary = rows[0];
                var id = primary.ValueKind == JsonValueKind.Object ? Str(primary, "id") : "";
                var dash = id.IndexOf('-');
                loader = dash < 0 ? id : id[..dash];
                loaderVersion = dash < 0 ? "" : id[(dash + 1)..];
            }
            return new Info
            {
                Kind = "curseforge",
                Format = "CurseForge .zip",
                Name = Str(root, "name"),
                Version = Str(root, "version"),
                McVersion = Str(mc, "version"),
                Loader = loader,
                LoaderVersion = loaderVersion,
                Files = root.TryGetProperty("files", out var f) && f.ValueKind == JsonValueKind.Array ? f.GetArrayLength() : 0,
            };
        }

        /// <summary>直接压缩的 .minecraft 目录（可能还套了一层文件夹）。</summary>
        private static Info? ProbePlain(List<string> names)
        {
            var children = new Dictionary<string, HashSet<string>>();
            foreach (var n in names)
            {
                var parts = n.Split('/', StringSplitOptions.RemoveEmptyEntries);
                for (var depth = 0; depth < Math.Min(parts.Length, MaxNest); depth++)
                {
                    var key = string.Join("/", parts.Take(depth));
                    if (!children.TryGetValue(key, out var set)) children[key] = set = new HashSet<string>();
                    set.Add(parts[depth].ToLowerInvariant());
                }
            }
            foreach (var root in children.Keys.OrderBy(k => k.Length))
            {
                var hit = children[root].Intersect(PlainMarkers).ToList();
                // 一个资源包 / 模组 jar 顶多蹭到一个同名目录，两个以上才算数
                if (hit.Count < 2 && !hit.Contains("versions")) continue;
                var prefix = root.Length == 0 ? "" : root + "/";
                var (mcVersion, loader) = PlainVersion(names, prefix);
                return new Info
                {
                    Kind = "plain",
                    Format = L("直接压缩的 .minecraft 目录"),
                    McVersion = mcVersion,
                    Loader = loader,
                };
            }
            return null;
        }

        /// <summary>从 versions/&lt;名&gt;/&lt;名&gt;.json 的目录名推 MC 版本与加载器。</summary>
        private static (string McVersion, string Loader) PlainVersion(List<string> names, string prefix)
        {
            var head = prefix + "versions/";
            foreach (var n in names)
            {
                if (!n.StartsWith(head, StringComparison.Ordinal)) continue;
                var parts = n[head.Length..].Split('/');
                if (parts.Length != 2 || parts[1] != parts[0] + ".json") continue;
                var vid = parts[0];
                foreach (var (key, loader) in new[]
                         {
                             ("neoforge", "neoforge"), ("-forge-", "forge"),
                             ("fabric-loader-", "fabric-loader"), ("quilt-loader-", "quilt-loader"),
                         })
                {
                    if (!vid.Contains(key, StringComparison.Ordinal)) continue;
                    var m = Regex.Match(vid, @"(\d+\.\d+(?:\.\d+)?)");
                    return (m.Success ? m.Groups[1].Value : "", loader);
                }
                return (vid, "");
            }
            return ("", "");
        }
    }
}
