package com.pymcl.mobile.data

import com.pymcl.mobile.PyMclApp
import org.json.JSONObject
import java.io.File

/** 数据根路径：`filesDir/pymcl/` ≡ 桌面 `PYMCL_HOME`。 */
object Paths {
    const val APP_VERSION = "1.0.1"
    const val UA = "PyMCL/$APP_VERSION (android; +minecraft launcher)"

    const val BMCL = "https://bmclapi2.bangbang93.com"
    const val MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
    const val BMCL_MANIFEST = "$BMCL/mc/game/version_manifest_v2.json"
    const val MCIM = "https://mod.mcimirror.top"

    /** 桌面 auth.py 用的是 login.live.com 那一套设备码口径，安卓照抄。 */
    const val MS_DEVICE_CODE = "https://login.live.com/oauth20_connect.srf"
    const val MS_TOKEN = "https://login.live.com/oauth20_token.srf"
    const val MS_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
    const val XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
    const val XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
    const val MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox"
    const val MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"
    const val MC_ENTITLEMENTS = "https://api.minecraftservices.com/entitlements/mcstore"
    const val MS_CLIENT = "00000000402b5328"

    val root: File
        get() = File(PyMclApp.instance.filesDir, "pymcl").also { it.mkdirs() }

    val cache: File get() = File(root, "cache").also { it.mkdirs() }
    val instancesRoot: File get() = File(root, ".minecraft").also { it.mkdirs() }
    val javaRoot: File get() = File(root, "java").also { it.mkdirs() }
    val skinsRoot: File get() = File(root, "skins").also { it.mkdirs() }
    val themesRoot: File get() = File(root, "themes").also { it.mkdirs() }
    val exportsRoot: File get() = File(root, "exports").also { it.mkdirs() }

    val configFile: File get() = File(root, "config.json")
    val accountsFile: File get() = File(root, "accounts.json")
    val manifestCache: File get() = File(cache, "version_manifest.json")
    val feedbackHistoryFile: File get() = File(root, "feedback_history.json")
    val deviceIdFile: File get() = File(root, "device_id")
    val aiChatsFile: File get() = File(root, "ai_chats.json")

    fun instanceDir(name: String): File = File(instancesRoot, name)

    fun themeFile(name: String): File = File(themesRoot, sanitizeFileName(name) + ".json")

    /** 主题包 / 皮肤文件名用的收敛规则，跟桌面 themes.py `_sanitize` 一致。 */
    fun sanitizeFileName(name: String, fallback: String = "untitled"): String {
        val safe = buildString {
            name.forEach { c ->
                append(if (c.isLetterOrDigit() || c == ' ' || c == '_' || c == '-') c else '_')
            }
        }.trim()
        return safe.ifEmpty { fallback }
    }

    fun readJson(file: File, fallback: JSONObject = JSONObject()): JSONObject {
        if (!file.isFile) return fallback
        return runCatching { JSONObject(file.readText(Charsets.UTF_8)) }.getOrDefault(fallback)
    }

    /** 先写 .tmp 再改名：写一半断电不会把配置烧成半截 JSON。 */
    fun writeJson(file: File, obj: JSONObject) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(obj.toString(2), Charsets.UTF_8)
        if (file.exists()) file.delete()
        if (!tmp.renameTo(file)) {
            file.writeText(obj.toString(2), Charsets.UTF_8)
            tmp.delete()
        }
    }
}
