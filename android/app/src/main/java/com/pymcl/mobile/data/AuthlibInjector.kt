package com.pymcl.mobile.data

import java.io.File

/**
 * authlib-injector：把客户端对 Mojang 会话服务的请求劫持到本地皮肤服务。
 *
 * 对齐桌面 mclauncher/authlib.py 的 ensure_injector / javaagent_arg，但有一处
 * **故意的不同**，见 [LaunchArgs.withAuthlibAgent] 上面那段注释——桌面会把所有
 * `-javaagent:` 都清掉，安卓这边不能那么干。
 */
data class AuthlibAgent(val jar: File, val apiRoot: String) {
    val usable: Boolean
        get() = apiRoot.isNotBlank() && jar.isFile && jar.length() > AuthlibInjector.MIN_JAR_BYTES

    /** `-javaagent:<jar>=<api 根地址>`，authlib-injector 认的就是这个形状。 */
    fun javaagentArg(): String = "-javaagent:${jar.absolutePath}=${apiRoot.trimEnd('/')}"
}

object AuthlibInjector {
    const val JAR_NAME = "authlib-injector.jar"

    /** 真身有几百 KB；比这还小的多半是半截下载或一张错误页。 */
    const val MIN_JAR_BYTES = 10_000L

    val LATEST_META = listOf(
        "https://bmclapi2.bangbang93.com/mirrors/authlib-injector/artifact/latest.json",
        "https://authlib-injector.yushi.moe/artifact/latest.json",
    )

    fun jarIn(root: File): File = File(root, JAR_NAME)

    /** 从 latest.json 里挑下载地址。两个字段名都见过，都认。 */
    fun downloadUrlOf(metaJson: String): String? = runCatching {
        val o = org.json.JSONObject(metaJson)
        val url = o.optString("download_url").ifBlank { o.optString("url") }
        url.ifBlank { null }
    }.getOrNull()

    /**
     * 确保 jar 在本地。已经在了就是空转。
     *
     * [fetchText] 与 [downloader] 都是注进来的，所以这一段能不联网地测。
     * 任何一步失败都返回 null——**皮肤是锦上添花，不该连游戏都起不来**。
     */
    fun ensureJar(
        root: File,
        fetchText: (List<String>) -> String?,
        downloader: PackDownloader,
    ): File? {
        val dest = jarIn(root)
        if (dest.isFile && dest.length() > MIN_JAR_BYTES) return dest
        return runCatching {
            val meta = fetchText(LATEST_META) ?: return null
            val url = downloadUrlOf(meta) ?: return null
            downloader.fetch(listOf(url), dest, null) { _, _ -> }
            dest.takeIf { it.isFile && it.length() > MIN_JAR_BYTES }
        }.getOrNull()
    }

    /**
     * 离线账号设了自定义皮肤时，备好 jar、起本地服务、返回可注入的 agent。
     *
     * 照搬桌面 launcher._offline_skin_api 的行为：**全程吞异常**。皮肤文件坏了、
     * injector 下不到、服务起不来——任何一步出问题都只是没皮肤，返回 null，
     * 启动链照常走。
     */
    fun prepare(
        root: File,
        skinPng: File?,
        uuid: String,
        playerName: String,
        model: String,
        server: SkinServer,
        fetchText: (List<String>) -> String?,
        downloader: PackDownloader,
    ): AuthlibAgent? = runCatching {
        val png = skinPng ?: return null
        if (!SkinFile.validate(png).ok) return null
        val jar = ensureJar(root, fetchText, downloader) ?: return null

        server.registry.register(
            SkinProfile(
                uuid = uuid.replace("-", "").lowercase().ifBlank { "0".repeat(32) },
                name = playerName.ifBlank { "Player" },
                png = png.readBytes(),
                model = SkinFile.modelOf(model),
            ),
        )
        val api = server.ensureRunning()
        if (api.isBlank()) return null
        AuthlibAgent(jar, api).takeIf { it.usable }
    }.getOrNull()
}
