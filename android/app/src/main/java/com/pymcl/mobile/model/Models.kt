package com.pymcl.mobile.model

data class VersionRow(
    val id: String,
    val type: String,
    val url: String,
    val sha1: String = "",
    val releaseTime: String = "",
)

data class InstanceInfo(
    val name: String,
    val versions: List<String>,
    val path: String,
)

data class CatalogHit(
    val name: String,
    val slug: String,
    val description: String,
    val downloads: Long,
    val source: String,
    val author: String = "",
    val projectId: String = "",
    /** 搜索结果的图标地址，空 = 没有；下载页用 Thumbnails 缓存后显示。 */
    val iconUrl: String = "",
)

data class TaskInfo(
    val id: String,
    val title: String,
    val current: Long = 0,
    val total: Long = 0,
    val message: String = "",
    val done: Boolean = false,
    val success: Boolean = true,
    val log: List<String> = emptyList(),
)

data class LaunchPlan(
    val instance: String,
    val version: String,
    val mainClass: String,
    val classpath: List<String>,
    val gameArgs: List<String>,
    val jvmArgs: List<String>,
    val missing: List<String>,
    val nativesMissing: Boolean,
    val gameDir: String = "",
    /** 直连要追加的 `--server/--port`。单列一格，见 LaunchArgs.addGameArgs 里的说明。 */
    val serverArgs: List<String> = emptyList(),
)

/** 服务器列表一行。`index` 是它在 servers.json 里的下标，删改都按它定位。 */
data class ServerEntry(
    val name: String,
    val ip: String,
    val port: Int = 25565,
    val description: String = "",
    val icon: String = "",
    val hidden: Boolean = false,
    val index: Int = 0,
)

/** 存档目录一条。`bytes` 是抽样统计出来的，不保证等于实际占用，见 Saves.dirSize。 */
data class SaveEntry(
    val name: String,
    val path: String,
    val icon: String = "",
    val bytes: Long = 0,
    val mtime: Long = 0,
)

data class BackupEntry(
    val name: String,
    val path: String,
    val save: String,
    val bytes: Long = 0,
    val mtime: Long = 0,
)

/** 截图 / 崩溃报告 / 日志 共用一种行。 */
data class MediaEntry(
    val name: String,
    val path: String,
    val bytes: Long = 0,
    val mtime: Long = 0,
)

/** 已安装的模组文件。禁用态在磁盘上是 `.jar.disabled`，`filename` 一律是去掉后缀的原名。 */
data class ModEntry(
    val filename: String,
    val path: String,
    val bytes: Long = 0,
    val enabled: Boolean = true,
    val mtime: Long = 0,
)

/** 模组安装目标：大锅饭（value 为空）或某个开了独立模组的版本。 */
data class ModTarget(
    val label: String,
    val value: String,
)

data class PlaytimeSession(
    val start: Long,
    val duration: Long,
    val version: String,
)

data class PlaytimeStat(
    val total: Long = 0,
    val versions: Map<String, Long> = emptyMap(),
    val sessions: List<PlaytimeSession> = emptyList(),
)

/** 版本管理页一张卡的全部内容。 */
data class VersionCard(
    val id: String,
    val mc: String,
    val loader: String,
    val mods: Int,
    val isolated: Boolean,
    val hidden: Boolean,
)
