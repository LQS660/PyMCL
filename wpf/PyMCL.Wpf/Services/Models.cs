using System.Text.Json;
using System.Text.Json.Serialization;

namespace PyMCL.Models;

public sealed class InstanceInfo
{
    public string Name { get; set; } = "";
    public int Versions { get; set; }
    public string Mc { get; set; } = "";
    public string Pack { get; set; } = "";
    [JsonPropertyName("pack_version")] public string PackVersion { get; set; } = "";
    [JsonPropertyName("mc_version")] public string McVersion { get; set; } = "";
    public string Java { get; set; } = "";
    [JsonPropertyName("java_label")] public string JavaLabel { get; set; } = "";
}

public sealed class VersionRow
{
    public string Version { get; set; } = "";
    public string Type { get; set; } = "";
    public string Date { get; set; } = "";

    [JsonIgnore]
    public string TypeLabel => Type switch
    {
        "release" => "正式版",
        "snapshot" => "快照",
        "old_alpha" => "远古 Alpha",
        "old_beta" => "远古 Beta",
        _ => Type,
    };
}

public sealed class CatalogItem
{
    public string Name { get; set; } = "";
    public string Author { get; set; } = "";
    public long Downloads { get; set; }
    public JsonElement? Id { get; set; }
    public string? Slug { get; set; }
    public string Source { get; set; } = "";
    public string Description { get; set; } = "";
    public List<string>? Tags { get; set; }
    public string Updated { get; set; } = "";
    [JsonPropertyName("game_version")] public string GameVersion { get; set; } = "";

    [JsonIgnore]
    public object? IdValue => Id is { } el
        ? el.ValueKind switch
        {
            JsonValueKind.Number => el.TryGetInt64(out var n) ? n : (object)el.GetDouble(),
            JsonValueKind.String => el.GetString(),
            JsonValueKind.Null or JsonValueKind.Undefined => null,
            _ => el.ToString(),
        }
        : null;

    [JsonIgnore] public string Key => $"{Source}:{Slug ?? IdValue?.ToString() ?? Name}";
}

public sealed class JavaInfo
{
    public string Name { get; set; } = "";
    public string Major { get; set; } = "";
    public string Path { get; set; } = "";
}

public sealed class JavaOption
{
    public string Label { get; set; } = "";
    public string Value { get; set; } = "";
    public override string ToString() => Label;
}

public sealed class VersionSettingsDto
{
    public string Isolation { get; set; } = "none";
    [JsonPropertyName("memory_mb")] public int? MemoryMb { get; set; }
    [JsonPropertyName("jvm_args")] public string JvmArgs { get; set; } = "";
    public string Server { get; set; } = "";
    public string Port { get; set; } = "";
    [JsonPropertyName("pre_launch")] public string PreLaunch { get; set; } = "";
    [JsonPropertyName("post_launch")] public string PostLaunch { get; set; } = "";
    [JsonPropertyName("login_account")] public string LoginAccount { get; set; } = "";
    [JsonPropertyName("nide8_id")] public string Nide8Id { get; set; } = "";
    public string Gc { get; set; } = "";
    [JsonPropertyName("window_title")] public string WindowTitle { get; set; } = "";
    [JsonPropertyName("window_mode")] public string WindowMode { get; set; } = "window";
    [JsonPropertyName("pre_launch_wait")] public bool PreLaunchWait { get; set; } = true;
    public bool Hidden { get; set; }
    [JsonPropertyName("offline_skin")] public string OfflineSkin { get; set; } = "default";
}

public sealed class NewsRow
{
    public string Title { get; set; } = "";
    public string Body { get; set; } = "";
    public string Version { get; set; } = "";
}

public sealed class AuthlibPreset
{
    public string Name { get; set; } = "";
    public string Api { get; set; } = "";
}

public sealed class AccountRow
{
    public string Name { get; set; } = "";
    public string Type { get; set; } = "";
    public string Uuid { get; set; } = "";
    public string Api { get; set; } = "";
    public string Avatar { get; set; } = "";
    public string Body { get; set; } = "";
    public bool Active { get; set; }
}

public sealed class TerracottaSnap
{
    public bool Supported { get; set; }
    public bool Installed { get; set; }
    public bool Running { get; set; }
    public string State { get; set; } = "";
    public string Label { get; set; } = "";
    public string Room { get; set; } = "";
    public string Url { get; set; } = "";
    public string Error { get; set; } = "";
}

public sealed class ModEntry
{
    public string Filename { get; set; } = "";
    public string Name { get; set; } = "";
    public bool Enabled { get; set; } = true;
    public string Version { get; set; } = "";
    public string Size { get; set; } = "";
}

public sealed class GlobalModRow
{
    public string Filename { get; set; } = "";
    public bool Enabled { get; set; }
    public string Size { get; set; } = "";
}

public sealed class SaveRow
{
    public string Name { get; set; } = "";
    public string Folder { get; set; } = "";
    public string Size { get; set; } = "";
    public string Mtime { get; set; } = "";
    [JsonPropertyName("last_played")] public string LastPlayed { get; set; } = "";
    public string Mode { get; set; } = "";
    public string Seed { get; set; } = "";
}

public sealed class BackupRow
{
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    public string Size { get; set; } = "";
    public string Date { get; set; } = "";
}

public sealed class AiStoreDto
{
    [JsonPropertyName("active_id")] public string ActiveId { get; set; } = "";
    public List<AiChatDto> Chats { get; set; } = new();
}

public sealed class AiChatDto
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public List<AiMsgDto> Messages { get; set; } = new();
}

public sealed class AiMsgDto
{
    public string Role { get; set; } = "";
    public string Content { get; set; } = "";
}

public sealed class CrashReport
{
    public string Title { get; set; } = "";
    public string Headline { get; set; } = "";
    public string Summary { get; set; } = "";
    public string Detail { get; set; } = "";
    public string Help { get; set; } = "";
    [JsonPropertyName("direct_file")] public string DirectFile { get; set; } = "";
    [JsonPropertyName("exit_code")] public int? ExitCode { get; set; }
    [JsonPropertyName("exit_hint")] public string ExitHint { get; set; } = "";
    [JsonPropertyName("task_id")] public string TaskId { get; set; } = "";
    public string Instance { get; set; } = "";
    public string Version { get; set; } = "";
    [JsonPropertyName("is_crash")] public bool IsCrash { get; set; }
    public List<CrashAction>? Actions { get; set; }
}

public sealed class CrashAction
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public List<string>? Mods { get; set; }
    public int? Major { get; set; }
    [JsonPropertyName("memory_mb")] public int? MemoryMb { get; set; }
    public string Instance { get; set; } = "";
    public string Version { get; set; } = "";
    public string Path { get; set; } = "";
}

public sealed class PreflightResult
{
    public bool Ok { get; set; } = true;
    public List<PreflightItem> Items { get; set; } = new();
}

public sealed class PreflightItem
{
    public string Level { get; set; } = "";
    public string Code { get; set; } = "";
    public string Title { get; set; } = "";
    public string Detail { get; set; } = "";
}

public sealed class OpResult
{
    public bool Ok { get; set; }
    public string Message { get; set; } = "";
    [JsonPropertyName("task_id")] public string? TaskId { get; set; }
}

public sealed class CatalogFile
{
    public JsonElement? Id { get; set; }
    public string Name { get; set; } = "";
    [JsonPropertyName("version_number")] public string VersionNumber { get; set; } = "";
    public string Filename { get; set; } = "";
    [JsonPropertyName("game_versions")] public List<string>? GameVersions { get; set; }
    public List<string>? Loaders { get; set; }
    public string Date { get; set; } = "";
    public long Downloads { get; set; }
    [JsonPropertyName("release_type")] public string ReleaseType { get; set; } = "";
    public string Source { get; set; } = "";

    [JsonIgnore]
    public object? IdValue => Id is { } el
        ? el.ValueKind switch
        {
            JsonValueKind.Number => el.TryGetInt64(out var n) ? n : (object)el.GetDouble(),
            JsonValueKind.String => el.GetString(),
            _ => null,
        }
        : null;
}

public sealed class LoaderVer
{
    public string Label { get; set; } = "";
    public string Id { get; set; } = "";
    public bool Stable { get; set; }
    public override string ToString() => Label;
}

public sealed class HelpArticle
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string Body { get; set; } = "";
}

public sealed class ServerRow
{
    public string Name { get; set; } = "";
    public string Ip { get; set; } = "";
    public int Port { get; set; } = 25565;
    public string Description { get; set; } = "";
}

public sealed class ThemeRow
{
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    public string Date { get; set; } = "";
}

public sealed class UpdateInfo
{
    [JsonPropertyName("has_update")] public bool HasUpdate { get; set; }
    public string Message { get; set; } = "";
    public string Version { get; set; } = "";
    public string Url { get; set; } = "";
}

public sealed class CleanerPreview
{
    public long Total { get; set; }
    [JsonPropertyName("total_text")] public string TotalText { get; set; } = "";
    public List<CleanerKind> Kinds { get; set; } = new();
}

public sealed class CleanerKind
{
    public string Kind { get; set; } = "";
    public string Label { get; set; } = "";
    public long Size { get; set; }
    [JsonPropertyName("size_text")] public string SizeText { get; set; } = "";
    public int Count { get; set; }
}

public sealed class FeedbackRow
{
    public string Category { get; set; } = "";
    public string Title { get; set; } = "";
    public string Time { get; set; } = "";
    public string Status { get; set; } = "";
    public string Id { get; set; } = "";
}

/// <summary>目录页五种内容 + 世界的差异集中在这里，页面本体只有一份。</summary>
public sealed class CatalogKind
{
    public string Key { get; set; } = "";
    public string Title { get; set; } = "";
    public string SearchMethod { get; set; } = "";
    public string InstallMethod { get; set; } = "";
    public string InstalledMethod { get; set; } = "";
    public string DeleteMethod { get; set; } = "";
    public string Empty { get; set; } = "";
    public string LinkHint { get; set; } = "";
    public string LocalFilter { get; set; } = "";
    public bool IsModpack { get; set; }
    public string[] Types { get; set; } = Array.Empty<string>();
    public string FileKind { get; set; } = "mod";
    public string DefaultSource { get; set; } = "全部";
    public string Icon { get; set; } = "";

    public static readonly CatalogKind Mod = new()
    {
        Key = "mod", Title = "Mod", Icon = "mod",
        SearchMethod = "search_mods", InstallMethod = "install_mod",
        InstalledMethod = "get_installed_mods", DeleteMethod = "delete_mod",
        Empty = "没有找到相关模组", LinkHint = "模组链接 / .jar 直链",
        LocalFilter = "模组 (*.jar)|*.jar|全部文件|*.*",
        Types = new[] { "全部", "优化", "科技", "魔法", "冒险", "建筑", "工具" },
        FileKind = "mod", DefaultSource = "Modrinth",
    };

    public static readonly CatalogKind Modpack = new()
    {
        Key = "modpack", Title = "整合包", Icon = "pack",
        SearchMethod = "search_modpacks", InstallMethod = "install_modpack",
        Empty = "没有找到相关整合包", LinkHint = "整合包链接 / .mrpack / .zip",
        LocalFilter = "整合包 (*.mrpack;*.zip)|*.mrpack;*.zip|全部文件|*.*",
        IsModpack = true,
        Types = new[] { "全部", "生存", "空岛", "科技", "魔法", "冒险" },
        FileKind = "modpack", DefaultSource = "Modrinth",
    };

    public static readonly CatalogKind Datapack = new()
    {
        Key = "datapack", Title = "数据包", Icon = "data",
        SearchMethod = "search_datapacks", InstallMethod = "install_datapack",
        InstalledMethod = "get_installed_datapacks", DeleteMethod = "delete_datapack",
        Empty = "没有找到相关数据包", LinkHint = "数据包下载链接",
        LocalFilter = "数据包 (*.zip)|*.zip|全部文件|*.*",
        Types = new[] { "全部", "生存", "冒险", "装饰", "工具" },
        FileKind = "datapack",
    };

    public static readonly CatalogKind ResourcePack = new()
    {
        Key = "resourcepack", Title = "资源包", Icon = "res",
        SearchMethod = "search_resourcepacks", InstallMethod = "install_resourcepack",
        InstalledMethod = "get_installed_resourcepacks", DeleteMethod = "delete_resourcepack",
        Empty = "没有找到相关资源包", LinkHint = "资源包下载链接",
        LocalFilter = "资源包 (*.zip)|*.zip|全部文件|*.*",
        Types = new[] { "全部", "16x", "32x", "64x", "写实", "现代风", "动态效果" },
        FileKind = "resourcepack",
    };

    public static readonly CatalogKind Shader = new()
    {
        Key = "shader", Title = "光影包", Icon = "shader",
        SearchMethod = "search_shaders", InstallMethod = "install_shader",
        InstalledMethod = "get_installed_shaders", DeleteMethod = "delete_shader",
        Empty = "没有找到相关光影", LinkHint = "光影包下载链接",
        LocalFilter = "光影包 (*.zip)|*.zip|全部文件|*.*",
        Types = new[] { "全部", "写实", "卡通", "高性能", "光追" },
        FileKind = "shader",
    };

    public static readonly CatalogKind World = new()
    {
        Key = "world", Title = "世界", Icon = "world",
        SearchMethod = "search_worlds", InstallMethod = "install_world",
        Empty = "没有找到相关世界地图", LinkHint = "世界地图下载链接",
        LocalFilter = "世界 (*.zip)|*.zip|全部文件|*.*",
        Types = new[] { "全部", "生存", "冒险", "创造", "跑酷" },
        FileKind = "world", DefaultSource = "CurseForge",
    };

    public static readonly CatalogKind[] All = { Mod, Modpack, Datapack, ResourcePack, Shader, World };
}
