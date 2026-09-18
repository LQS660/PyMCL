package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File

/** 单个版本的设置，落在 `versions/<id>/pymcl.json`，字段与桌面 `version_settings.py` 同名同义。 */
data class VersionSetting(
    val isolation: String = VersionSettings.NONE,
    val memoryMb: Int? = null,
    val java: String = "自动选择",
    val jvmArgs: String = "",
    val gameArgs: String = "",
    val preLaunch: String = "",
    val postLaunch: String = "",
    val preLaunchWait: Boolean = true,
    val server: String = "",
    val port: String = "",
    val icon: String = "",
    val hidden: Boolean = false,
    val windowMode: String = "window",
    val windowTitle: String = "",
    val windowWidth: Int? = null,
    val windowHeight: Int? = null,
    val skipAssets: Boolean = false,
    /** GC 预设键，见 [GcPresets]；空串 = 跟随全局。 */
    val gc: String = "",
    val processPriority: String = "normal",
    /** 绑定到这个版本的账号名；空 = 跟随启动页。 */
    val loginAccount: String = "",
    val authServer: String = "",
    val authServerName: String = "",
    /** 统一通行证（Nide8）服务器 ID。 */
    val nide8Id: String = "",
    val offlineSkin: String = "default",
)

object VersionSettings {
    const val FILE_NAME = "pymcl.json"

    const val NONE = "none"
    const val SAVES = "saves"
    const val MODS = "mods"
    const val ALL = "all"

    /** 版本卡上那个一键开关只在「大锅饭」和这一档之间翻，四档细分留在版本设置里。 */
    const val ISOLATED_DEFAULT = ALL

    val LABELS = linkedMapOf(
        NONE to "大锅饭（与其他版本共用）",
        SAVES to "隔离存档",
        MODS to "隔离 Mod 与配置",
        ALL to "完全独立",
    )

    /** 转独立时从大锅饭里带一份过去的目录。 */
    val SEED_DIRS = listOf("mods", "config", "resourcepacks", "shaderpacks")

    fun file(instDir: File, version: String): File =
        File(instDir, "versions/$version/$FILE_NAME")

    fun load(instDir: File, version: String): VersionSetting {
        val f = file(instDir, version)
        if (!f.isFile) return VersionSetting()
        val obj = runCatching { JSONObject(f.readText()) }.getOrNull() ?: return VersionSetting()
        return fromJson(obj)
    }

    fun fromJson(obj: JSONObject): VersionSetting {
        val iso = obj.optString("isolation", NONE)
        return VersionSetting(
            isolation = if (iso in LABELS) iso else NONE,
            memoryMb = obj.optInt("memory_mb", 0).takeIf { it > 0 },
            java = obj.optString("java", "自动选择"),
            jvmArgs = obj.optString("jvm_args", ""),
            gameArgs = obj.optString("game_args", ""),
            preLaunch = obj.optString("pre_launch", ""),
            postLaunch = obj.optString("post_launch", ""),
            preLaunchWait = obj.optBoolean("pre_launch_wait", true),
            server = obj.optString("server", ""),
            port = obj.optString("port", ""),
            icon = obj.optString("icon", ""),
            hidden = obj.optBoolean("hidden", false),
            windowMode = obj.optString("window_mode", "window"),
            windowTitle = obj.optString("window_title", ""),
            windowWidth = obj.optInt("window_width", 0).takeIf { it > 0 },
            windowHeight = obj.optInt("window_height", 0).takeIf { it > 0 },
            skipAssets = obj.optBoolean("skip_assets", false),
            gc = obj.optString("gc", ""),
            processPriority = obj.optString("process_priority", "normal"),
            loginAccount = obj.optString("login_account", ""),
            authServer = obj.optString("auth_server", ""),
            authServerName = obj.optString("auth_server_name", ""),
            nide8Id = obj.optString("nide8_id", ""),
            offlineSkin = obj.optString("offline_skin", "default"),
        )
    }

    fun toJson(s: VersionSetting): JSONObject = JSONObject()
        .put("isolation", s.isolation)
        .put("memory_mb", s.memoryMb ?: JSONObject.NULL)
        .put("java", s.java)
        .put("jvm_args", s.jvmArgs)
        .put("game_args", s.gameArgs)
        .put("pre_launch", s.preLaunch)
        .put("post_launch", s.postLaunch)
        .put("pre_launch_wait", s.preLaunchWait)
        .put("server", s.server)
        .put("port", s.port)
        .put("icon", s.icon)
        .put("hidden", s.hidden)
        .put("window_mode", s.windowMode)
        .put("window_title", s.windowTitle)
        .put("window_width", s.windowWidth ?: JSONObject.NULL)
        .put("window_height", s.windowHeight ?: JSONObject.NULL)
        .put("skip_assets", s.skipAssets)
        .put("gc", s.gc)
        .put("process_priority", s.processPriority)
        .put("login_account", s.loginAccount)
        .put("auth_server", s.authServer)
        .put("auth_server_name", s.authServerName)
        .put("nide8_id", s.nide8Id)
        .put("offline_skin", s.offlineSkin)

    fun save(instDir: File, version: String, s: VersionSetting): VersionSetting {
        val f = file(instDir, version)
        f.parentFile?.mkdirs()
        f.writeText(toJson(s).toString(2), Charsets.UTF_8)
        return s
    }

    /** 这个版本有没有自己的 mods 目录（而不是吃大锅饭）。 */
    fun isolatedMods(s: VersionSetting): Boolean = s.isolation == MODS || s.isolation == ALL

    fun isolatedSaves(s: VersionSetting): Boolean = s.isolation == SAVES || s.isolation == ALL

    /** 只要不是纯大锅饭，游戏工作目录就落在版本目录里。 */
    fun isolatedAnywhere(s: VersionSetting): Boolean = s.isolation != NONE

    fun gameDir(instDir: File, version: String, s: VersionSetting = load(instDir, version)): File =
        if (isolatedAnywhere(s)) File(instDir, "versions/$version") else instDir

    fun modsDir(instDir: File, version: String, s: VersionSetting = load(instDir, version)): File =
        File(if (isolatedMods(s)) File(instDir, "versions/$version") else instDir, "mods")

    fun savesDir(instDir: File, version: String, s: VersionSetting = load(instDir, version)): File =
        File(if (isolatedSaves(s)) File(instDir, "versions/$version") else instDir, "saves")

    /**
     * 切隔离档位。`seed=true` 时把大锅饭里现有的模组 / 配置复制一份过去——
     * 转独立那一下版本目录是空的，不带种子用户会以为模组丢了。
     */
    fun setIsolation(
        instDir: File,
        version: String,
        mode: String,
        seed: Boolean = false,
    ): VersionSetting {
        require(mode in LABELS) { "未知的隔离模式: $mode" }
        val before = load(instDir, version)
        val after = save(instDir, version, before.copy(isolation = mode))
        if (seed && isolatedMods(after) && !isolatedMods(before)) {
            seedFromShared(instDir, version)
        }
        applyLayout(instDir, version, after)
        return after
    }

    internal fun seedFromShared(instDir: File, version: String) {
        val dest = File(instDir, "versions/$version")
        for (name in SEED_DIRS) {
            val src = File(instDir, name)
            if (!src.isDirectory) continue
            val target = File(dest, name)
            target.mkdirs()
            src.listFiles()?.forEach { child ->
                val out = File(target, child.name)
                if (out.exists()) return@forEach
                runCatching { if (child.isDirectory) child.copyRecursively(out) else child.copyTo(out) }
            }
        }
    }

    /** 按档位把该有的目录建出来。安卓没有 junction，共享靠启动时把路径指回实例根。 */
    fun applyLayout(
        instDir: File,
        version: String,
        s: VersionSetting = load(instDir, version),
    ): File {
        val dir = gameDir(instDir, version, s)
        dir.mkdirs()
        when (s.isolation) {
            SAVES -> File(dir, "saves").mkdirs()
            MODS -> listOf("mods", "config").forEach { File(dir, it).mkdirs() }
            ALL -> listOf("mods", "config", "saves", "resourcepacks", "shaderpacks")
                .forEach { File(dir, it).mkdirs() }
        }
        return dir
    }

    fun addressOf(s: VersionSetting): String {
        val host = s.server.trim()
        if (host.isEmpty()) return ""
        val port = s.port.trim().toIntOrNull()
        if (port == null || port !in 1..65535) return host
        return "$host:$port"
    }

    /**
     * 把用户在设置里敲的一行参数切成 argv。支持成对的单双引号，
     * 不配对的引号按普通字符处理——总比整行被吞掉强。
     */
    fun splitArgs(raw: String): List<String> {
        val out = mutableListOf<String>()
        val buf = StringBuilder()
        var quote = ' '
        var has = false
        for (ch in raw) {
            when {
                quote != ' ' -> {
                    if (ch == quote) quote = ' ' else buf.append(ch)
                }
                ch == '"' || ch == '\'' -> {
                    quote = ch
                    has = true
                }
                ch.isWhitespace() -> {
                    if (has || buf.isNotEmpty()) out += buf.toString()
                    buf.setLength(0)
                    has = false
                }
                else -> buf.append(ch)
            }
        }
        if (has || buf.isNotEmpty()) out += buf.toString()
        return out
    }
}
