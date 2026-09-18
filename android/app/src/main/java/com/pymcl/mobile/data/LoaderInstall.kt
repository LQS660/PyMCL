package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.jar.JarFile
import java.util.zip.ZipFile

class LoaderError(message: String) : RuntimeException(message)

enum class Loader(val key: String, val label: String) {
    FABRIC("fabric", "Fabric"),
    QUILT("quilt", "Quilt"),
    FORGE("forge", "Forge"),
    NEOFORGE("neoforge", "NeoForge"),
    OPTIFINE("optifine", "OptiFine"),
    ;

    companion object {
        fun of(raw: String): Loader? {
            val key = VersionPick.normalizeLoader(raw)
            return entries.firstOrNull { it.key == key }
        }
    }
}

/** 加载器的一个可选构建号。 */
data class LoaderBuild(val id: String, val label: String, val stable: Boolean = true)

/**
 * 在一个已装好的原版上再装一个加载器，对齐桌面 `mclauncher/loader_meta.py` +
 * `installer.py` 的加载器那一段。
 *
 * 分工与本仓其它仓储一致：**`parse*` / `*Urls` / `mavenPath` 全是纯函数**，
 * 所以构建号解析、版本 json 合成、`inheritsFrom` 链都能不联网地测；真正的
 * 拉取交给注入进来的 [PackDownloader]（设备上就是 [HttpPackDownloader]）。
 */
object LoaderInstall {
    const val FABRIC_META = "https://meta.fabricmc.net/v2"
    const val QUILT_META = "https://meta.quiltmc.org/v3"
    const val FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
    const val NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
    const val MOJANG_LIBRARIES = "https://libraries.minecraft.net"

    /**
     * Forge / NeoForge / OptiFine 要先在本机跑一遍安装器里的 processors（binarypatcher、
     * ForgeAutoRenamingTool 之类）才能补出打过补丁的客户端 jar。这条路现在走
     * [installProcessorLoader]，在手机上真起一个 JVM；这句话只在**没有 JVM 宿主可用**
     * 时还会出现，比如调用方没给 runJvm。
     */
    const val NEEDS_PROCESSOR_MESSAGE =
        "这个版本要先在本机跑一遍安装器里的 processors，得有一个 JVM 宿主才行。" +
            "从「下载」页发起安装会自动带上宿主；直接调 API 请传 runJvm。"

    // ------------------------------------------------------------ 构建号列表

    fun buildListUrls(loader: Loader, mc: String): List<String> = when (loader) {
        Loader.FABRIC -> listOf("$FABRIC_META/versions/loader/$mc")
        Loader.QUILT -> listOf("$QUILT_META/versions/loader/$mc")
        Loader.FORGE -> listOf(
            "${Paths.BMCL}/forge/minecraft/$mc",
            "${Paths.BMCL}/maven/net/minecraftforge/forge/maven-metadata.xml",
            "$FORGE_MAVEN/maven-metadata.xml",
        )
        Loader.NEOFORGE -> listOf("$NEOFORGE_MAVEN/maven-metadata.xml")
        Loader.OPTIFINE -> listOf("${Paths.BMCL}/optifine/$mc")
    }

    /** Fabric / Quilt 的 `versions/loader/{mc}`：两家的形状一样。 */
    fun parseLoaderBuilds(json: String): List<LoaderBuild> {
        val arr = runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val loader = arr.optJSONObject(i)?.optJSONObject("loader") ?: return@mapNotNull null
            val version = loader.optString("version")
            if (version.isBlank()) return@mapNotNull null
            LoaderBuild(version, version, loader.optBoolean("stable", true))
        }
    }

    /** `maven-metadata.xml` 里的 `<version>` 列表。不引 XML 解析器，正则够用。 */
    fun parseMavenVersions(xml: String): List<String> =
        Regex("<version>([^<]+)</version>").findAll(xml)
            .map { it.groupValues[1].trim() }
            .filter { it.isNotEmpty() }
            .toList()

    /** BMCLAPI 的 `/forge/minecraft/{mc}` 返回 JSON 数组，取 `version` 字段。 */
    fun parseBmclForge(json: String, mc: String): List<String> {
        val arr = runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val build = o.optString("version").trim()
            if (build.isEmpty()) null else "$mc-$build"
        }
    }

    /** Forge 的 maven 版本号是 `<mc>-<build>`，先按 MC 版本筛掉别的号段。 */
    fun filterForgeVersions(all: List<String>, mc: String): List<String> =
        all.filter { it == mc || it.startsWith("$mc-") }
            .sortedWith(compareByDescending { forgeSortKey(it, mc) })

    /** `1.20.1-47.2.0` → 47002000；比不出来的给 -1，排到最后。 */
    fun forgeSortKey(version: String, mc: String): Long {
        val tail = version.removePrefix("$mc-").substringBefore('-')
        val parts = tail.split('.').mapNotNull { it.toLongOrNull() }
        if (parts.isEmpty()) return -1
        var key = 0L
        for (i in 0 until 3) key = key * 1000 + (parts.getOrNull(i) ?: 0)
        return key
    }

    /** MC 版本对应的 NeoForge 号段前缀；`1.21.4` → `21.4`。1.20.2 之前没有。 */
    fun neoforgePrefix(mc: String): String {
        val mapped = NEOFORGE_MC_MAP[mc]
        if (mapped != null) return mapped
        val parts = mc.split('.').mapNotNull { it.toIntOrNull() }
        if (parts.size < 2) return ""
        val ge = parts[0] > 1 || (parts[0] == 1 && (parts[1] > 20 || (parts[1] == 20 && (parts.getOrNull(2) ?: 0) >= 2)))
        return if (ge) mc.split('.').drop(1).joinToString(".") else ""
    }

    val NEOFORGE_MC_MAP = mapOf(
        "1.20.1" to "47.1", "1.20.2" to "20.2", "1.20.3" to "20.3", "1.20.4" to "20.4",
        "1.20.5" to "20.5", "1.20.6" to "20.6", "1.21" to "21.0", "1.21.1" to "21.1",
    )

    /**
     * 从 NeoForge 的全量版本表里挑属于这个 MC 版本的。
     * 前缀推不出来时**返回空表**——不过滤的话下拉框里会混进所有 MC 版本的构建，
     * 用户随手选一条就是版本错配（桌面那边已经踩过，见 loader_meta.py 同名函数）。
     */
    fun filterNeoForgeVersions(all: List<String>, mc: String): List<String> {
        val prefix = neoforgePrefix(mc)
        val picked = if (prefix.isEmpty()) emptyList() else all.filter { it.startsWith("$prefix.") }
        if (picked.isNotEmpty()) return picked.takeLast(80).reversed()
        return all.filter { it.startsWith("$mc-") }.takeLast(80).reversed()
    }

    // ------------------------------------------------------------ 版本 json

    /** 装完之后这个版本在 `versions/` 下叫什么。与 HMCL / PCL 的命名一致。 */
    fun versionIdOf(loader: Loader, mc: String, build: String): String = when (loader) {
        Loader.FABRIC -> "$mc-fabric-$build"
        Loader.QUILT -> "$mc-quilt-$build"
        Loader.FORGE -> "$mc-forge-${build.removePrefix("$mc-")}"
        Loader.NEOFORGE -> "$mc-neoforge-$build"
        Loader.OPTIFINE -> "$mc-OptiFine-$build"
    }

    /** Fabric / Quilt 直接给现成的 profile json，不用跑安装器。 */
    fun profileJsonUrls(loader: Loader, mc: String, build: String): List<String> = when (loader) {
        Loader.FABRIC -> listOf("$FABRIC_META/versions/loader/$mc/$build/profile/json")
        Loader.QUILT -> listOf("$QUILT_META/versions/loader/$mc/$build/profile/json")
        else -> emptyList()
    }

    /**
     * 把上游给的 profile json 收拾成能直接落盘的样子：
     * `id` 改成我们自己的版本号、`inheritsFrom` 一定指向原版。
     *
     * 上游给的 `id` 是它自己那一套（`fabric-loader-0.16.0-1.20.1`），照抄的话
     * 目录名和 json 里的 id 对不上，`LaunchPlanner` 走继承链时就会找不到父版本。
     */
    fun normalizeProfile(raw: JSONObject, mc: String, versionId: String): JSONObject {
        val out = JSONObject(raw.toString())
        out.put("id", versionId)
        out.put("inheritsFrom", mc)
        // 继承链上父版本已经有了，子版本重复声明这些只会让合成结果打架
        out.remove("downloads")
        out.remove("assetIndex")
        out.remove("assets")
        if (out.optString("mainClass").isBlank()) {
            throw LoaderError("上游给的 profile 没有 mainClass，装了也起不来")
        }
        return out
    }

    /** profile 里声明的库，换算成可下载的 [PackFile]。 */
    fun librariesOf(profile: JSONObject): List<PackFile> {
        val arr = profile.optJSONArray("libraries") ?: return emptyList()
        val out = ArrayList<PackFile>(arr.length())
        for (i in 0 until arr.length()) {
            val lib = arr.optJSONObject(i) ?: continue
            if (!Installer.allowedByRules(lib)) continue
            val name = lib.optString("name")
            if (name.isBlank()) continue
            val rel = Installer.artifactRelPath(lib) ?: mavenPath(name) ?: continue
            val artifact = lib.optJSONObject("downloads")?.optJSONObject("artifact")
            val direct = artifact?.optString("url").orEmpty()
            val repo = lib.optString("url").trimEnd('/').ifBlank { MOJANG_LIBRARIES }
            val urls = buildList {
                if (direct.isNotBlank()) add(direct)
                add("$repo/$rel")
                add("${Paths.BMCL}/maven/$rel")
            }
            out += PackFile(
                path = rel,
                urls = urls.distinct(),
                sha1 = artifact?.optString("sha1").orEmpty(),
                size = artifact?.optLong("size", 0L) ?: 0L,
            )
        }
        return out
    }

    /** `net.fabricmc:fabric-loader:0.16.0` → `net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar`。 */
    fun mavenPath(name: String): String? {
        val head = name.substringBefore('@')
        val ext = if (name.contains('@')) name.substringAfter('@') else "jar"
        val parts = head.split(':')
        if (parts.size < 3) return null
        val (group, artifact, version) = parts
        if (group.isBlank() || artifact.isBlank() || version.isBlank()) return null
        val classifier = parts.getOrNull(3)?.takeIf { it.isNotBlank() }?.let { "-$it" }.orEmpty()
        return "${group.replace('.', '/')}/$artifact/$version/$artifact-$version$classifier.$ext"
    }

    // ------------------------------------------------------------ 落盘

    /**
     * 把一份收拾好的 profile 装进实例：写版本 json，再把它声明的库补齐。
     * 原版必须已经装好——这条路只加加载器，不碰客户端 jar。
     *
     * @return 新版本的 id
     */
    fun installProfile(
        instDir: File,
        mc: String,
        versionId: String,
        profile: JSONObject,
        downloader: PackDownloader,
        onLog: (String) -> Unit = {},
        onProgress: (Int, Int) -> Unit = { _, _ -> },
    ): String {
        if (!File(instDir, "versions/$mc/$mc.json").isFile) {
            throw LoaderError("先装原版 $mc，再装加载器")
        }
        val dir = File(instDir, "versions/$versionId").also { it.mkdirs() }
        File(dir, "$versionId.json").writeText(profile.toString(2), Charsets.UTF_8)
        onLog("已写入 versions/$versionId/$versionId.json")

        val libs = librariesOf(profile)
        val libRoot = File(instDir, "libraries")
        libs.forEachIndexed { i, lib ->
            if (Installer.cancelled) throw InstallCancelled()
            val dest = File(libRoot, lib.path.replace('/', File.separatorChar))
            onProgress(i + 1, libs.size)
            if (dest.isFile && lib.sha1.isNotBlank() && Http.sha1Of(dest).equals(lib.sha1, true)) return@forEachIndexed
            downloader.fetch(lib.urls, dest, lib.sha1.takeIf { it.isNotBlank() }) { _, _ -> }
        }
        onLog("加载器库 ${libs.size} 个就位")
        return versionId
    }

    /**
     * Fabric / Quilt 的完整一条：拉 profile → 收拾 → 落盘 → 补库。
     * Forge / NeoForge / OptiFine 走不到这里，见 [NEEDS_PROCESSOR_MESSAGE]。
     */
    fun installMetaLoader(
        instDir: File,
        loader: Loader,
        mc: String,
        build: String,
        fetcher: TextFetcher,
        downloader: PackDownloader,
        onLog: (String) -> Unit = {},
        onProgress: (Int, Int) -> Unit = { _, _ -> },
    ): String {
        val urls = profileJsonUrls(loader, mc, build)
        if (urls.isEmpty()) throw LoaderError(NEEDS_PROCESSOR_MESSAGE)
        val body = fetcher.get(urls, CatalogFiles.JSON_HEADERS)
            ?: throw LoaderError("拉不到 ${loader.label} $build 的 profile")
        val raw = runCatching { JSONObject(body) }.getOrNull()
            ?: throw LoaderError("${loader.label} 的 profile 不是合法 JSON")
        val versionId = versionIdOf(loader, mc, build)
        onLog("${loader.label} $build → $versionId")
        return installProfile(instDir, mc, versionId, normalizeProfile(raw, mc, versionId), downloader, onLog, onProgress)
    }

    /** 这个加载器能不能只靠元数据装完。false 的那几个需要跑 processors。 */
    fun isMetaOnly(loader: Loader): Boolean = loader == Loader.FABRIC || loader == Loader.QUILT

    // ------------------------------------------------------------ 要跑 processors 的那一支

    /** 跑一条 processor，返回退出码。0 以外都算失败。 */
    fun interface JvmStepRunner {
        fun run(step: ProcessorStep, index: Int, total: Int): Int
    }

    /** 安装器 jar 的下载地址。OptiFine 不在 maven 上，单独走镜像直链。 */
    fun installerFile(loader: Loader, mc: String, build: String): PackFile? = when (loader) {
        Loader.FORGE -> mavenInstaller(ForgeProcessors.forgeInstallerCoord(mc, build))
        Loader.NEOFORGE -> mavenInstaller(ForgeProcessors.neoForgeInstallerCoord(build))
        Loader.OPTIFINE -> {
            val type = build.substringBefore('_', build).ifBlank { build }
            val patch = build.substringAfter('_', "")
            PackFile("optifine-$mc-$build.jar", listOf(ForgeProcessors.optifineUrl(mc, type, patch)))
        }
        else -> null
    }

    private fun mavenInstaller(coord: String): PackFile? {
        val rel = mavenPath(coord) ?: return null
        val repo = if (coord.startsWith("net.neoforged")) {
            "https://maven.neoforged.net/releases"
        } else {
            "https://maven.minecraftforge.net"
        }
        return PackFile(rel.substringAfterLast('/'), listOf("$repo/$rel", "${Paths.BMCL}/maven/$rel"))
    }

    /**
     * 真装一个要跑 processors 的加载器。
     *
     * 六步：下安装器 jar → 从里面抽 `install_profile.json` 与 `version.json` →
     * 落版本 json → 把两份清单声明的库补齐 → 展开 processors 并逐条交给
     * [runJvm] → 核对每一步的产物。
     *
     * [runJvm] 由调用方注入：设备上是 [JvmHost] + 宿主 Activity，测试里是一个
     * 造产物的替身。这样这条编排本身能离线验，不用等一台真机。
     */
    fun installProcessorLoader(
        instDir: File,
        loader: Loader,
        mc: String,
        build: String,
        downloader: PackDownloader,
        runJvm: JvmStepRunner?,
        onLog: (String) -> Unit = {},
        onProgress: (Int, Int) -> Unit = { _, _ -> },
        cacheDir: File = File(instDir, "cache"),
    ): String {
        if (!File(instDir, "versions/$mc/$mc.json").isFile) throw LoaderError("先装原版 $mc，再装加载器")
        val spec = installerFile(loader, mc, build) ?: throw LoaderError("${loader.label} 没有可下载的安装器")
        val jar = File(cacheDir.also { it.mkdirs() }, spec.path)
        onLog("下载 ${loader.label} 安装器 ${spec.path}")
        downloader.fetch(spec.urls, jar, spec.sha1.takeIf { it.isNotBlank() }) { _, _ -> }

        val versionId = versionIdOf(loader, mc, build)
        val work = File(cacheDir, "installer-$versionId").also { it.deleteRecursively(); it.mkdirs() }
        try {
            ZipFile(jar).use { zip ->
                val profile = readJsonEntry(zip, "install_profile.json")
                    ?: throw LoaderError("安装器里没有 install_profile.json，认不出这个安装器")
                val versionJson = readJsonEntry(zip, ForgeProcessors.versionJsonEntry(profile))
                    ?: profile.optJSONObject("versionInfo")
                    ?: throw LoaderError("安装器里没有 version.json")

                val dir = File(instDir, "versions/$versionId").also { it.mkdirs() }
                File(dir, "$versionId.json")
                    .writeText(normalizeProfile(versionJson, mc, versionId).toString(2), Charsets.UTF_8)
                onLog("已写入 versions/$versionId/$versionId.json")

                val libs = (librariesOf(profile) + librariesOf(versionJson)).distinctBy { it.path }
                val libRoot = File(instDir, "libraries")
                libs.forEachIndexed { i, lib ->
                    if (Installer.cancelled) throw InstallCancelled()
                    onProgress(i + 1, libs.size)
                    val dest = File(libRoot, lib.path.replace('/', File.separatorChar))
                    if (dest.isFile && lib.sha1.isNotBlank() && Http.sha1Of(dest).equals(lib.sha1, true)) {
                        return@forEachIndexed
                    }
                    runCatching { downloader.fetch(lib.urls, dest, lib.sha1.takeIf { it.isNotBlank() }) { _, _ -> } }
                        .onFailure { onLog("库下载失败（继续）${lib.path}: ${it.message}") }
                }
                onLog("库 ${libs.size} 个就位")

                if (!ForgeProcessors.needsProcessors(profile)) {
                    onLog("这个版本不需要跑 processors，装完了")
                    return versionId
                }
                val runner = runJvm ?: throw LoaderError(NEEDS_PROCESSOR_MESSAGE)
                val data = ForgeProcessors.resolveData(profile, libraryDir = libRoot) { entry ->
                    extractEntry(zip, entry, work)
                }
                val extras = ForgeProcessors.extrasOf(
                    instDir,
                    jar,
                    LaunchPlanner.baseJar(instDir, LaunchPlanner.chain(instDir, mc)),
                )
                val steps = ForgeProcessors.plan(profile, libRoot, data, extras, ::mainClassOf)
                onLog("要跑 ${steps.size} 步 processor，手机上会比较慢，别退出这个页面")
                steps.forEachIndexed { i, step ->
                    if (Installer.cancelled) throw InstallCancelled()
                    onProgress(i + 1, steps.size)
                    onLog("[${i + 1}/${steps.size}] ${step.mainClass}")
                    val code = runner.run(step, i + 1, steps.size)
                    if (code != 0) throw LoaderError("第 ${i + 1} 步 processor 失败，退出码 $code")
                    val bad = ForgeProcessors.verifyOutputs(step) { Http.sha1Of(it) }
                    if (bad.isNotEmpty()) throw LoaderError("第 ${i + 1} 步产物不对：${bad.first()}")
                }
            }
        } finally {
            work.deleteRecursively()
        }
        onLog("${loader.label} $build 安装完成 → $versionId")
        return versionId
    }

    internal fun readJsonEntry(zip: ZipFile, name: String): JSONObject? {
        val entry = zip.getEntry(name) ?: return null
        val text = zip.getInputStream(entry).bufferedReader().readText()
        return runCatching { JSONObject(text) }.getOrNull()
    }

    internal fun extractEntry(zip: ZipFile, name: String, dest: File): File {
        val entry = zip.getEntry(name) ?: throw LoaderError("安装器里没有 $name")
        val out = File(dest, name.substringAfterLast('/'))
        out.parentFile?.mkdirs()
        zip.getInputStream(entry).use { input -> out.outputStream().use { input.copyTo(it) } }
        return out
    }

    /** processor jar 的入口类写在它自己的 MANIFEST 里。 */
    internal fun mainClassOf(jar: File): String? {
        if (!jar.isFile) return null
        return runCatching {
            JarFile(jar).use { it.manifest?.mainAttributes?.getValue("Main-Class") }
        }.getOrNull()
    }
}
