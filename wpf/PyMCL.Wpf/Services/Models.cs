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
        "release" => L("正式版"),
        "snapshot" => L("快照"),
        "old_alpha" => L("远古 Alpha"),
        "old_beta" => L("远古 Beta"),
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
    [JsonPropertyName("icon_url")] public string IconUrl { get; set; } = "";

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
    [JsonPropertyName("skin_file")] public string SkinFile { get; set; } = "";
    [JsonPropertyName("skin_model")] public string SkinModel { get; set; } = "classic";
}

/// <summary>get_account_skin：账号当前绑的那张皮肤，data_url 是可直接解码的 base64 PNG。</summary>
public sealed class AccountSkin
{
    public string Name { get; set; } = "";
    [JsonPropertyName("skin_file")] public string SkinFile { get; set; } = "";
    [JsonPropertyName("skin_model")] public string SkinModel { get; set; } = "classic";
    [JsonPropertyName("data_url")] public string DataUrl { get; set; } = "";

    [JsonIgnore] public bool Slim => string.Equals(SkinModel, "slim", StringComparison.OrdinalIgnoreCase);
}

/// <summary>skin_urls：头像与全身像的在线地址。</summary>
public sealed class SkinUrls
{
    public string Avatar { get; set; } = "";
    public string Body { get; set; } = "";
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
    public int Port { get; set; }
    public string Player { get; set; } = "";
    [JsonPropertyName("game_running")] public bool GameRunning { get; set; }
    [JsonPropertyName("error_hint")] public string ErrorHint { get; set; } = "";
    [JsonPropertyName("difficulty_hint")] public string DifficultyHint { get; set; } = "";
    public List<TerracottaProfile> Profiles { get; set; } = new();
    public List<string> Nodes { get; set; } = new();
    public string Copyright { get; set; } = "";
    public string Home { get; set; } = "";
}

/// <summary>房间成员。kind = HOST / GUEST。</summary>
public sealed class TerracottaProfile
{
    public string Name { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Vendor { get; set; } = "";
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
    /// <summary>后端此刻是否有一回合在跑（ai_list_chats 带回），前端按钮状态以它为准。</summary>
    public bool Busy { get; set; }
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
    public string Note { get; set; } = "";
}

public sealed class AiPermissionRuleDto
{
    public string Key { get; set; } = "";
    [JsonPropertyName("toolName")] public string ToolName { get; set; } = "";
    [JsonPropertyName("ruleContent")] public string RuleContent { get; set; } = "";
    public string Behavior { get; set; } = "";
    [JsonPropertyName("behavior_label")] public string BehaviorLabel { get; set; } = "";
    public string Instance { get; set; } = "";
    public string Scope { get; set; } = "";
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

/// <summary>list_themes 的一行：主题包名 + 落盘文件名 + 包里记着的主色 / 深色。</summary>
public sealed class ThemeRow
{
    public string Name { get; set; } = "";
    public string File { get; set; } = "";
    [JsonPropertyName("theme_color")] public string ThemeColor { get; set; } = "";
    [JsonPropertyName("ui_dark")] public bool UiDark { get; set; }
}

public sealed class UpdateInfo
{
    [JsonPropertyName("has_update")] public bool HasUpdate { get; set; }
    public string Message { get; set; } = "";
    public string Version { get; set; } = "";
    public string Url { get; set; } = "";
}

/// <summary>cleaner_preview：未引用依赖库 / 残留 .part / 更新缓存三类的明细与总量。</summary>
public sealed class CleanerPreview
{
    [JsonPropertyName("unused_libraries")] public List<CleanerEntry> UnusedLibraries { get; set; } = new();
    public List<CleanerEntry> Parts { get; set; } = new();
    public List<CleanerEntry> Cache { get; set; } = new();
    public long Bytes { get; set; }
    public int Count { get; set; }
}

public sealed class CleanerEntry
{
    public string Path { get; set; } = "";
    public long Bytes { get; set; }
}

/// <summary>cleaner_apply 的回执。</summary>
public sealed class CleanerResult
{
    public int Removed { get; set; }
    public long Bytes { get; set; }
}

/// <summary>get_smart_recommendation：按本机硬件给出的推荐值。</summary>
public sealed class SmartRecommendation
{
    [JsonPropertyName("memory_mb")] public int MemoryMb { get; set; } = 4096;
    [JsonPropertyName("java_major")] public int JavaMajor { get; set; } = 17;
    [JsonPropertyName("window_width")] public int WindowWidth { get; set; } = 854;
    [JsonPropertyName("window_height")] public int WindowHeight { get; set; } = 480;
    [JsonPropertyName("gc_preset")] public string GcPreset { get; set; } = "auto";
    [JsonPropertyName("cpu_count")] public int CpuCount { get; set; }
    [JsonPropertyName("total_ram_gb")] public double TotalRamGb { get; set; }
}

/// <summary>get_mods_targets 的一行：mods 目录的去处（实例共享 / 某个隔离版本）。</summary>
public sealed class ModsTarget
{
    public string Label { get; set; } = "";
    public string Value { get; set; } = "";
    public override string ToString() => Label;
}

/// <summary>
/// check_mod_updates 的一行。apply_mod_update 收的是原样这一行，
/// 未知键靠 Extra 兜住，避免序列化回去时把 file_id / sha1 这类字段丢掉。
/// </summary>
public sealed class ModUpdateRow
{
    public string Filename { get; set; } = "";
    public string Name { get; set; } = "";
    public string Current { get; set; } = "";
    public string Latest { get; set; } = "";
    public string Project { get; set; } = "";
    public string Url { get; set; } = "";
    public string Sha1 { get; set; } = "";
    public long Size { get; set; }
    [JsonPropertyName("filename_new")] public string FilenameNew { get; set; } = "";
    public string Source { get; set; } = "";
    [JsonPropertyName("mc_version")] public string McVersion { get; set; } = "";
    [JsonPropertyName("game_versions")] public List<string> GameVersions { get; set; } = new();

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }
}

/// <summary>
/// get_version_rows 的一行：版本管理页的数据源。隔离状态、模组数、加载器标签与配色
/// 都由后端一次算好，前端不再逐个版本去问两次 RPC，也不用自己猜加载器。
/// </summary>
public sealed class VersionRowDto
{
    public string Id { get; set; } = "";
    public string Loader { get; set; } = "";
    [JsonPropertyName("loader_color")] public string LoaderColor { get; set; } = "";
    public string Mc { get; set; } = "";
    public string Isolation { get; set; } = "none";
    [JsonPropertyName("isolation_label")] public string IsolationLabel { get; set; } = "";
    public bool Isolated { get; set; }
    public int Mods { get; set; }
    [JsonPropertyName("mods_dir")] public string ModsDir { get; set; } = "";
    public bool Hidden { get; set; }
    public string Java { get; set; } = "";
    [JsonPropertyName("memory_mb")] public int MemoryMb { get; set; }
}

/// <summary>undo_background / reset_background 的回执。</summary>
public sealed class BackgroundState
{
    public string Image { get; set; } = "";
    public string Folder { get; set; } = "";
}

/// <summary>export_contents 的回执。</summary>
public sealed class ExportResult
{
    public List<string> Ok { get; set; } = new();
    public List<string> Failed { get; set; } = new();
    public string Dest { get; set; } = "";
}

/// <summary>list_media 的一行：截图 / 崩溃报告 / 日志。</summary>
public sealed class MediaRow
{
    public string Name { get; set; } = "";
    public string Path { get; set; } = "";
    public long Bytes { get; set; }
    public long Mtime { get; set; }
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
    public string DefaultSource { get; set; } = L("全部");
    public string Icon { get; set; } = "";

    public static readonly CatalogKind Mod = new()
    {
        Key = "mod", Title = "Mod", Icon = "mod",
        SearchMethod = "search_mods", InstallMethod = "install_mod",
        InstalledMethod = "get_installed_mods", DeleteMethod = "delete_mod",
        Empty = L("没有找到相关模组"), LinkHint = L("模组链接 / .jar 直链"),
        LocalFilter = L("模组 (*.jar)|*.jar|全部文件|*.*"),
        Types = new[] { "全部", "优化", "科技", "魔法", "冒险", "建筑", "工具" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "mod", DefaultSource = "Modrinth",
    };

    public static readonly CatalogKind Modpack = new()
    {
        Key = "modpack", Title = L("整合包"), Icon = "pack",
        SearchMethod = "search_modpacks", InstallMethod = "install_modpack",
        InstalledMethod = "get_installed_modpacks", DeleteMethod = "delete_modpack",
        Empty = L("没有找到相关整合包"), LinkHint = L("整合包链接 / .mrpack / .zip"),
        LocalFilter = L("整合包 (*.mrpack;*.zip)|*.mrpack;*.zip|全部文件|*.*"),
        IsModpack = true,
        Types = new[] { "全部", "生存", "空岛", "科技", "魔法", "冒险" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "modpack", DefaultSource = "Modrinth",
    };

    public static readonly CatalogKind Datapack = new()
    {
        Key = "datapack", Title = L("数据包"), Icon = "data",
        SearchMethod = "search_datapacks", InstallMethod = "install_datapack",
        InstalledMethod = "get_installed_datapacks", DeleteMethod = "delete_datapack",
        Empty = L("没有找到相关数据包"), LinkHint = L("数据包下载链接"),
        LocalFilter = L("数据包 (*.zip)|*.zip|全部文件|*.*"),
        Types = new[] { "全部", "生存", "冒险", "装饰", "工具" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "datapack",
    };

    public static readonly CatalogKind ResourcePack = new()
    {
        Key = "resourcepack", Title = L("资源包"), Icon = "res",
        SearchMethod = "search_resourcepacks", InstallMethod = "install_resourcepack",
        InstalledMethod = "get_installed_resourcepacks", DeleteMethod = "delete_resourcepack",
        Empty = L("没有找到相关资源包"), LinkHint = L("资源包下载链接"),
        LocalFilter = L("资源包 (*.zip)|*.zip|全部文件|*.*"),
        Types = new[] { "全部", "16x", "32x", "64x", "写实", "现代风", "动态效果" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "resourcepack",
    };

    public static readonly CatalogKind Shader = new()
    {
        Key = "shader", Title = L("光影包"), Icon = "shader",
        SearchMethod = "search_shaders", InstallMethod = "install_shader",
        InstalledMethod = "get_installed_shaders", DeleteMethod = "delete_shader",
        Empty = L("没有找到相关光影"), LinkHint = L("光影包下载链接"),
        LocalFilter = L("光影包 (*.zip)|*.zip|全部文件|*.*"),
        Types = new[] { "全部", "写实", "卡通", "高性能", "光追" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "shader",
    };

    public static readonly CatalogKind World = new()
    {
        Key = "world", Title = L("世界"), Icon = "world",
        SearchMethod = "search_worlds", InstallMethod = "install_world",
        Empty = L("没有找到相关世界地图"), LinkHint = L("世界地图下载链接"),
        LocalFilter = L("世界 (*.zip)|*.zip|全部文件|*.*"),
        Types = new[] { "全部", "生存", "冒险", "创造", "跑酷" }, // i18n:ignore 分类名是后端的映射键（mclauncher/catalog_files.py），显示时再 L()
        FileKind = "world", DefaultSource = "CurseForge",
    };

    public static readonly CatalogKind[] All = { Mod, Modpack, Datapack, ResourcePack, Shader, World };
}
