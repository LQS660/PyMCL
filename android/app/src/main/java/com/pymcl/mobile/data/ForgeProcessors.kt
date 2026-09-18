package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class ProcessorError(message: String) : RuntimeException(message)

/** `install_profile.json` 里的一步 processor，展开成一条能直接交给 JVM 的命令行。 */
data class ProcessorStep(
    val jar: String,
    val mainClass: String,
    val classpath: List<String>,
    val args: List<String>,
    /** 产物路径 → 期望 sha1；为空表示这一步不声明产物。 */
    val outputs: Map<String, String> = emptyMap(),
) {
    /** 完整 java 命令行参数：`-cp <...> <mainClass> <args...>`。 */
    fun commandLine(separator: String = File.pathSeparator): List<String> =
        listOf("-cp", classpath.joinToString(separator)) + mainClass + args
}

/**
 * Forge / NeoForge 从 1.13 起不再直接发客户端 jar，而是发一个 `install_profile.json`，
 * 里面写着要依次跑哪几个 processor（binarypatcher、ForgeAutoRenamingTool 之类）
 * 把原版 jar 打成补丁版。这个文件把那份清单翻译成命令行。
 *
 * **全是纯函数**：收 JSON 文本与一张「这些名字对应哪个本地文件」的表，给出命令行。
 * 真正起 JVM 的是 [JvmHost]，下载是 [PackDownloader]，都在外面。
 * 这样最容易出错的那一段（占位符替换）能离线测，不用等一台真机。
 */
object ForgeProcessors {
    const val SIDE_CLIENT = "client"

    /** 安装器自己在 maven 里的坐标后缀。 */
    const val INSTALLER_CLASSIFIER = "installer"

    fun forgeInstallerCoord(mc: String, build: String): String {
        val version = if (build.startsWith("$mc-")) build else "$mc-$build"
        return "net.minecraftforge:forge:$version:$INSTALLER_CLASSIFIER"
    }

    fun neoForgeInstallerCoord(build: String): String =
        "net.neoforged:neoforge:$build:$INSTALLER_CLASSIFIER"

    /** OptiFine 的安装器不在 maven 上，走 BMCLAPI 的直链。 */
    fun optifineUrl(mc: String, type: String, patch: String): String =
        "${Paths.BMCL}/optifine/$mc/$type/$patch"

    // ------------------------------------------------------------ 解析

    /** `install_profile.json` 里那份 `version.json` 的位置；1.13+ 一般是 `version.json`。 */
    fun versionJsonEntry(profile: JSONObject): String =
        profile.optString("json").trim().removePrefix("/").ifBlank { "version.json" }

    /** 这个 profile 需不需要跑 processor。1.12 及以前没有这一段，直接落 json 就能玩。 */
    fun needsProcessors(profile: JSONObject): Boolean =
        (profile.optJSONArray("processors")?.length() ?: 0) > 0

    /**
     * 展开 `data` 段。每个键在 client / server 下各有一个值，我们只要 client。
     *
     * 值有三种写法，必须分开处理，混了就会把字面量当路径去找：
     * - `[maven:coord]` → 本地 maven 仓库里的那个文件
     * - `'literal'`     → 原样的字符串
     * - 其它            → 安装器 jar 内部的一个条目，得先解出来
     */
    fun resolveData(
        profile: JSONObject,
        side: String = SIDE_CLIENT,
        libraryDir: File,
        extractEntry: (String) -> File,
    ): Map<String, String> {
        val data = profile.optJSONObject("data") ?: return emptyMap()
        val out = LinkedHashMap<String, String>()
        for (key in data.keys()) {
            val raw = data.optJSONObject(key)?.optString(side).orEmpty()
            if (raw.isEmpty()) continue
            out[key] = resolveValue(raw, libraryDir, extractEntry)
        }
        return out
    }

    internal fun resolveValue(raw: String, libraryDir: File, extractEntry: (String) -> File): String {
        val text = raw.trim()
        return when {
            text.startsWith("[") && text.endsWith("]") ->
                File(libraryDir, mavenPathOrThrow(text.substring(1, text.length - 1))).absolutePath
            text.startsWith("'") && text.endsWith("'") && text.length >= 2 ->
                text.substring(1, text.length - 1)
            else -> extractEntry(text.removePrefix("/")).absolutePath
        }
    }

    internal fun mavenPathOrThrow(coord: String): String =
        LoaderInstall.mavenPath(coord) ?: throw ProcessorError("认不出的 maven 坐标: $coord")

    /**
     * 把一条 processor 展开成命令行。
     *
     * @param mainClassOf 从 jar 的 MANIFEST 里读 Main-Class；读不到就没法跑，直接报错。
     */
    fun buildStep(
        node: JSONObject,
        libraryDir: File,
        data: Map<String, String>,
        extras: Map<String, String>,
        mainClassOf: (File) -> String?,
        side: String = SIDE_CLIENT,
    ): ProcessorStep? {
        val sides = node.optJSONArray("sides")
        if (sides != null && side !in strings(sides)) return null
        val jarCoord = node.optString("jar")
        if (jarCoord.isBlank()) throw ProcessorError("processor 没写 jar")
        val jarFile = File(libraryDir, mavenPathOrThrow(jarCoord))
        val mainClass = mainClassOf(jarFile)
            ?: throw ProcessorError("${jarFile.name} 的 MANIFEST 里没有 Main-Class，跑不了")
        val classpath = (listOf(jarCoord) + strings(node.optJSONArray("classpath")))
            .map { File(libraryDir, mavenPathOrThrow(it)).absolutePath }
            .distinct()
        val args = strings(node.optJSONArray("args")).map { substitute(it, libraryDir, data, extras) }
        val outputs = LinkedHashMap<String, String>()
        node.optJSONObject("outputs")?.let { o ->
            for (key in o.keys()) {
                outputs[substitute(key, libraryDir, data, extras)] =
                    substitute(o.optString(key), libraryDir, data, extras)
            }
        }
        return ProcessorStep(jarFile.absolutePath, mainClass, classpath, args, outputs)
    }

    /**
     * 占位符替换。`{KEY}` 查 data 与 extras，`[maven:coord]` 换成本地路径，
     * 其余原样。查不到的 `{KEY}` **报错而不是留在命令行里**——留着的话
     * processor 会把 `{MAPPINGS}` 当成一个真实文件名去找，报的错完全指不到根因。
     */
    fun substitute(
        raw: String,
        libraryDir: File,
        data: Map<String, String>,
        extras: Map<String, String> = emptyMap(),
    ): String {
        val text = raw.trim()
        if (text.startsWith("[") && text.endsWith("]")) {
            return File(libraryDir, mavenPathOrThrow(text.substring(1, text.length - 1))).absolutePath
        }
        // `'literal'` 在这里就脱引号，下游（参数、产物校验和）拿到的一律是干净值
        if (text.length >= 2 && text.startsWith("'") && text.endsWith("'")) {
            return text.substring(1, text.length - 1)
        }
        if (!text.startsWith("{") || !text.endsWith("}")) return text
        val key = text.substring(1, text.length - 1)
        return extras[key] ?: data[key] ?: throw ProcessorError("install_profile 里没有占位符 $text 的值")
    }

    /** profile 里声明的库，交给 [LoaderInstall.librariesOf] 补齐，形状与版本 json 一致。 */
    fun libraries(profile: JSONObject): List<PackFile> = LoaderInstall.librariesOf(profile)

    /**
     * 一整套：把 processors 逐条展开。
     * [extras] 至少要给 `SIDE` / `MINECRAFT_JAR` / `ROOT` / `INSTALLER` / `LIBRARY_DIR`。
     */
    fun plan(
        profile: JSONObject,
        libraryDir: File,
        data: Map<String, String>,
        extras: Map<String, String>,
        mainClassOf: (File) -> String?,
        side: String = SIDE_CLIENT,
    ): List<ProcessorStep> {
        val arr = profile.optJSONArray("processors") ?: return emptyList()
        val out = ArrayList<ProcessorStep>(arr.length())
        for (i in 0 until arr.length()) {
            val node = arr.optJSONObject(i) ?: continue
            buildStep(node, libraryDir, data, extras, mainClassOf, side)?.let { out += it }
        }
        return out
    }

    /** 跑完之后核对一遍产物。返回对不上的那些，空表示都对。 */
    fun verifyOutputs(step: ProcessorStep, sha1Of: (File) -> String): List<String> =
        step.outputs.mapNotNull { (path, want) ->
            val file = File(path)
            when {
                !file.isFile -> "$path 没有生成"
                want.isBlank() -> null
                !sha1Of(file).equals(want, true) -> "$path 校验不过"
                else -> null
            }
        }

    /** 默认的 extras，调用方通常只需要补 `MINECRAFT_JAR`。 */
    fun extrasOf(instDir: File, installerJar: File, minecraftJar: File, side: String = SIDE_CLIENT): Map<String, String> =
        linkedMapOf(
            "SIDE" to side,
            "ROOT" to instDir.absolutePath,
            "INSTALLER" to installerJar.absolutePath,
            "LIBRARY_DIR" to File(instDir, "libraries").absolutePath,
            "MINECRAFT_JAR" to minecraftJar.absolutePath,
        )

    private fun strings(arr: JSONArray?): List<String> {
        if (arr == null) return emptyList()
        return (0 until arr.length()).mapNotNull { arr.optString(it).takeIf { s -> s.isNotBlank() } }
    }
}
