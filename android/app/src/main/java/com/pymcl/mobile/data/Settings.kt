package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 启动器全局配置，键名与桌面 `mclauncher/config.py` 的 `DEFAULT_CONFIG` 一一对应。
 *
 * 两端读写的是同一套键名，所以桌面导出的 config.json 拷到手机上直接能用，
 * 反过来也一样。安卓用不上的键（窗口大小、多开）照样保留，不然一次 [save]
 * 就会把桌面那边的设置抹掉。
 */
object SettingsKeys {
    const val INSTANCES_DIR = "instances_dir"
    const val JAVA_DIR = "java_dir"
    const val SHARED_LIBRARIES = "shared_libraries"
    const val SHARED_ASSETS = "shared_assets"
    const val MEMORY_MB = "memory_mb"
    const val DOWNLOAD_THREADS = "download_threads"
    const val WIDTH = "width"
    const val HEIGHT = "height"
    const val MS_CLIENT_ID = "microsoft_client_id"
    const val CURSEFORGE_API_KEY = "curseforge_api_key"
    const val FORCE_MANIFEST_REFRESH = "force_manifest_refresh"
    const val DOWNLOAD_SOURCE = "download_source"
    const val COMMUNITY_SOURCE = "community_source"
    const val USE_SYSTEM_PROXY = "use_system_proxy"
    const val AI_MODE = "ai_mode"
    const val AI_GATEWAY_URL = "ai_gateway_url"
    const val AI_BASE_URL = "ai_base_url"
    const val AI_API_KEY = "ai_api_key"
    const val AI_MODEL = "ai_model"
    const val AI_CONFIRM_WRITES = "ai_confirm_writes"
    const val AI_PERMISSION_MODE = "ai_permission_mode"
    const val FEEDBACK_URL = "feedback_url"
    const val FEEDBACK_HEARTBEAT = "feedback_heartbeat"
    const val FEEDBACK_CONSENT = "feedback_consent"
    const val DEVICE_ID = "device_id"
    const val DEFAULT_ISOLATION = "default_isolation"
    const val DEFAULT_JVM_ARGS = "default_jvm_args"
    const val UPDATE_URL = "update_url"
    const val AUTO_CHECK_UPDATE = "auto_check_update"
    const val THEME_COLOR = "theme_color"
    const val UI_DARK = "ui_dark"
    const val UI_BACKGROUND = "ui_background"
    const val UI_BACKGROUND_FOLDER = "ui_background_folder"
    const val UI_BACKGROUND_SHUFFLE = "ui_background_shuffle"
    const val UI_BACKGROUND_INTERVAL = "ui_background_interval"
    const val UI_BACKGROUND_HISTORY = "ui_background_history"
    const val UI_BACKGROUND_FOLDER_HISTORY = "ui_background_folder_history"
    const val UI_SIDEBAR_OPACITY = "ui_sidebar_opacity"
    const val UI_BACKGROUND_BLUR = "ui_background_blur"
    const val UI_BACKGROUND_DIM = "ui_background_dim"
    const val UI_MOTION = "ui_motion"
    const val UI_LAYOUT = "ui_layout"
    const val UI_LAYOUTS = "ui_layouts"
    const val UI_LAYOUT_PROFILE = "ui_layout_profile"
    const val UI_NAV_ORDER = "ui_nav_order"
    const val UI_NAV_HIDDEN = "ui_nav_hidden"
    const val CATALOG_FAVORITES = "catalog_favorites"
    const val DEFAULT_JAVA = "default_java"
    const val DOWNLOAD_LIMIT = "download_limit_kbps"
    const val LANGUAGE = "language"
    const val FIRST_RUN = "first_run"
    const val OFFLINE_SKIN = "offline_skin"
    const val EXPORT_DIR = "export_dir"
    const val USERNAME = "username"
    const val ACTIVE_INSTANCE = "active_instance"
}

/** 桌面 `DEFAULT_CONFIG` 的安卓副本。缺一个键就等于「用户改了，重启没了」。 */
val DEFAULT_SETTINGS: Map<String, Any> = mapOf(
    SettingsKeys.INSTANCES_DIR to ".minecraft",
    SettingsKeys.JAVA_DIR to "java",
    SettingsKeys.SHARED_LIBRARIES to false,
    SettingsKeys.SHARED_ASSETS to false,
    SettingsKeys.MEMORY_MB to 2048,
    SettingsKeys.DOWNLOAD_THREADS to 8,
    SettingsKeys.WIDTH to 854,
    SettingsKeys.HEIGHT to 480,
    SettingsKeys.MS_CLIENT_ID to Paths.MS_CLIENT,
    SettingsKeys.CURSEFORGE_API_KEY to "",
    SettingsKeys.FORCE_MANIFEST_REFRESH to false,
    SettingsKeys.DOWNLOAD_SOURCE to "auto",
    SettingsKeys.COMMUNITY_SOURCE to "auto",
    SettingsKeys.USE_SYSTEM_PROXY to true,
    SettingsKeys.AI_MODE to "public",
    SettingsKeys.AI_GATEWAY_URL to "",
    SettingsKeys.AI_BASE_URL to "",
    SettingsKeys.AI_API_KEY to "",
    SettingsKeys.AI_MODEL to "deepseek-v4-flash",
    SettingsKeys.AI_CONFIRM_WRITES to true,
    SettingsKeys.AI_PERMISSION_MODE to "standard",
    SettingsKeys.FEEDBACK_URL to "",
    SettingsKeys.FEEDBACK_HEARTBEAT to true,
    SettingsKeys.FEEDBACK_CONSENT to false,
    SettingsKeys.DEVICE_ID to "",
    SettingsKeys.DEFAULT_ISOLATION to "all",
    SettingsKeys.DEFAULT_JVM_ARGS to "",
    SettingsKeys.UPDATE_URL to "https://pymcl.dev/update.json",
    SettingsKeys.AUTO_CHECK_UPDATE to true,
    SettingsKeys.THEME_COLOR to "#2E9B6B",
    SettingsKeys.UI_DARK to false,
    SettingsKeys.UI_BACKGROUND to "",
    SettingsKeys.UI_BACKGROUND_FOLDER to "",
    SettingsKeys.UI_BACKGROUND_SHUFFLE to false,
    SettingsKeys.UI_BACKGROUND_INTERVAL to 10,
    SettingsKeys.UI_SIDEBAR_OPACITY to 85,
    SettingsKeys.UI_BACKGROUND_BLUR to 0,
    SettingsKeys.UI_BACKGROUND_DIM to 25,
    SettingsKeys.UI_MOTION to true,
    SettingsKeys.UI_LAYOUT_PROFILE to "",
    SettingsKeys.DEFAULT_JAVA to "",
    SettingsKeys.DOWNLOAD_LIMIT to 0,
    SettingsKeys.LANGUAGE to "zh_CN",
    SettingsKeys.FIRST_RUN to true,
    SettingsKeys.OFFLINE_SKIN to "default",
    SettingsKeys.EXPORT_DIR to "",
    SettingsKeys.USERNAME to "Player",
    SettingsKeys.ACTIVE_INSTANCE to "default",
)

/** 壁纸历史栈上限，跟桌面 `config.BG_HISTORY_MAX` 对齐。 */
const val BG_HISTORY_MAX = 20

/**
 * 纯逻辑部分单独摘出来：不碰文件、不碰 Context，单测直接跑。
 */
object SettingsLogic {
    /** 缺键补默认 + 保留表外的键。表外键必须留，否则一次保存就抹掉桌面写进来的设置。 */
    fun merge(stored: JSONObject): JSONObject {
        val out = JSONObject()
        DEFAULT_SETTINGS.forEach { (k, v) -> out.put(k, v) }
        stored.keys().forEach { k -> out.put(k, stored.get(k)) }
        return out
    }

    /** 下载源档位 → 实际要试的清单顺序。auto = 镜像优先、官方垫底。 */
    fun manifestUrls(source: String): List<String> = when (source) {
        "official" -> listOf(Paths.MOJANG_MANIFEST)
        "bmclapi" -> listOf(Paths.BMCL_MANIFEST)
        else -> listOf(Paths.BMCL_MANIFEST, Paths.MOJANG_MANIFEST)
    }

    /** 内存滑杆的合法区间，跟桌面首次引导的 SpinBox 一致。 */
    fun clampMemory(mb: Int): Int = mb.coerceIn(512, 32768)

    fun clampPercent(value: Int): Int = value.coerceIn(0, 100)

    fun clampBlur(value: Int): Int = value.coerceIn(0, 60)

    fun clampThreads(value: Int): Int = value.coerceIn(1, 64)

    /**
     * 主题色文本 → ARGB。认 `#RGB` / `#RRGGBB` / `#AARRGGBB`，认不出来退回出厂绿。
     * 桌面那边 theme_color 就是一个 `#RRGGBB` 字符串，这里要能原样吃下。
     */
    fun parseColor(text: String, fallback: Long = 0xFF2E9B6BL): Long {
        val hex = text.trim().removePrefix("#")
        val normalized = when (hex.length) {
            3 -> hex.map { "$it$it" }.joinToString("")
            6 -> hex
            8 -> hex
            else -> return fallback
        }
        val value = normalized.toLongOrNull(16) ?: return fallback
        return if (normalized.length == 8) value else (0xFF000000L or value)
    }

    /** 亮度加权：决定这个主题色上面该压白字还是黑字。 */
    fun isLightColor(argb: Long): Boolean {
        val r = ((argb shr 16) and 0xFF).toDouble()
        val g = ((argb shr 8) and 0xFF).toDouble()
        val b = (argb and 0xFF).toDouble()
        return (r * 299 + g * 587 + b * 114) / 1000.0 >= 150.0
    }

    /**
     * 壁纸历史入栈，对应桌面 `config.push_background_history`。
     * 单图栈与文件夹栈成对推进，撤销才能把「单图 + 文件夹」整套退回去。
     */
    fun pushBackgroundHistory(
        images: List<String>,
        folders: List<String>,
        oldImage: String,
        oldFolder: String,
    ): Pair<List<String>, List<String>> {
        val paired = pairHistory(images, folders)
        if (paired.first.isNotEmpty() &&
            paired.first.last() == oldImage &&
            paired.second.last() == oldFolder
        ) {
            return paired
        }
        val nextImages = (paired.first + oldImage).takeLast(BG_HISTORY_MAX)
        val nextFolders = (paired.second + oldFolder).takeLast(BG_HISTORY_MAX)
        return nextImages to nextFolders
    }

    /** 历史上只写过单图栈的话，这里给文件夹栈补齐空位，保证两栈等长。 */
    fun pairHistory(images: List<String>, folders: List<String>): Pair<List<String>, List<String>> {
        if (folders.size == images.size) return images to folders
        val fixed = (folders + List(images.size) { "" }).take(images.size)
        return images to fixed
    }
}

/**
 * 磁盘上的那一份。
 *
 * 写入是**合并**的：改十个开关只落一次盘。UI 每点一下就 `commit()` 一次，
 * 由 [flushIfDirty] 在退到后台 / 离开设置页 / 启动游戏前统一写出去。
 */
object Settings {
    @Volatile
    private var cache: JSONObject? = null

    @Volatile
    private var dirty = false

    /** 每改一次 +1，Compose 侧据此判断要不要重组，省掉整份字典的相等比较。 */
    @Volatile
    var revision: Int = 0
        private set

    fun all(): JSONObject {
        cache?.let { return it }
        synchronized(this) {
            cache?.let { return it }
            val merged = SettingsLogic.merge(Paths.readJson(Paths.configFile))
            cache = merged
            return merged
        }
    }

    fun str(key: String, fallback: String = ""): String =
        all().optString(key, DEFAULT_SETTINGS[key] as? String ?: fallback)

    fun int(key: String, fallback: Int = 0): Int =
        all().optInt(key, DEFAULT_SETTINGS[key] as? Int ?: fallback)

    fun bool(key: String, fallback: Boolean = false): Boolean =
        all().optBoolean(key, DEFAULT_SETTINGS[key] as? Boolean ?: fallback)

    fun list(key: String): List<String> {
        val arr = all().optJSONArray(key) ?: return emptyList()
        return (0 until arr.length()).map { arr.optString(it) }
    }

    /** 只改内存，不落盘。 */
    fun set(key: String, value: Any?) {
        val obj = all()
        synchronized(this) {
            if (value == null) obj.remove(key) else obj.put(key, value)
            dirty = true
            revision++
        }
    }

    fun setList(key: String, values: List<String>) {
        set(key, JSONArray().also { arr -> values.forEach { arr.put(it) } })
    }

    fun update(pairs: Map<String, Any?>) {
        val obj = all()
        synchronized(this) {
            pairs.forEach { (k, v) -> if (v == null) obj.remove(k) else obj.put(k, v) }
            dirty = true
            revision++
        }
    }

    /** 真正落盘。没脏就直接返回，别为了一次翻页写一遍 config.json。 */
    fun flushIfDirty(): Boolean {
        if (!dirty) return false
        val snapshot: JSONObject
        synchronized(this) {
            if (!dirty) return false
            snapshot = JSONObject(all().toString())
            dirty = false
        }
        Paths.writeJson(Paths.configFile, snapshot)
        return true
    }

    fun reload() {
        synchronized(this) {
            cache = null
            dirty = false
            revision++
        }
    }

    /** 单测用：把配置指到一个临时文件上，别去碰真机的 filesDir。 */
    fun loadFromForTest(file: File) {
        synchronized(this) {
            cache = SettingsLogic.merge(Paths.readJson(file))
            dirty = false
            revision++
        }
    }
}
