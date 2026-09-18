package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File
import java.util.Locale

/** 一条待删文件。[path] 是绝对路径，[bytes] 是扫描那一刻的大小。 */
data class CleanEntry(val path: String, val bytes: Long)

/** 一次扫描的结果。三类分开装，用户可以只勾其中几类再删。 */
data class CleanPlan(
    val unusedLibraries: List<CleanEntry> = emptyList(),
    val parts: List<CleanEntry> = emptyList(),
    val cache: List<CleanEntry> = emptyList(),
) {
    val count: Int get() = unusedLibraries.size + parts.size + cache.size

    val bytes: Long get() = bytesOf(Cleaner.ALL_KINDS)

    fun of(kind: String): List<CleanEntry> = when (kind) {
        Cleaner.KIND_UNUSED -> unusedLibraries
        Cleaner.KIND_PARTS -> parts
        Cleaner.KIND_CACHE -> cache
        else -> emptyList()
    }

    fun entries(kinds: Collection<String>): List<CleanEntry> = kinds.distinct().flatMap { of(it) }

    fun bytesOf(kinds: Collection<String>): Long = entries(kinds).sumOf { it.bytes }
}

/** [Cleaner.apply] 真删完的账：删掉几个、腾出多少。 */
data class CleanResult(val removed: Int, val bytes: Long)

/**
 * 清理 / 维护工具，对齐桌面 `mclauncher/cleaner.py`：没有任何已装版本引用的
 * libraries、下载断在半路的 `.part`、以及更新缓存这三类。
 *
 * [preview] 与 [apply] 是分开的两步：先把要删的东西列出来给人看过，确认了才删——
 * 桌面那边也是 `cleaner_preview` → 确认框 → `cleaner_apply` 这个顺序，没有一步到位的删。
 */
object Cleaner {
    const val KIND_UNUSED = "unused_libraries"
    const val KIND_PARTS = "parts"
    const val KIND_CACHE = "cache"

    /** 默认全勾，与桌面 `cleaner.apply(kinds=None)` 的默认集合一致。 */
    val ALL_KINDS = listOf(KIND_UNUSED, KIND_PARTS, KIND_CACHE)

    const val PART_SUFFIX = ".part"

    /** 更新缓存的文件名形状，桌面是 `cache.glob("PyMCL-*.bin")`——只看一层，不往下钻。 */
    private val CACHE_NAME = Regex("^PyMCL-.*\\.bin$")

    /**
     * 扫一遍，列出可删的文件。不动任何东西。
     *
     * [instanceRoot] 下每个实例各自的 `libraries/` 都过一遍；开了共享库时几个实例
     * 指的是同一个目录，按路径去重只扫一次（桌面 `seen_libs` 同理）。
     */
    fun preview(instanceRoot: File = Paths.instancesRoot, cacheDir: File = Paths.cache): CleanPlan {
        val instances = InstanceStore.listIn(instanceRoot).map { File(it.path) }
        val used = HashSet<String>()
        instances.forEach { used += usedLibraryPaths(it) }

        val unused = ArrayList<CleanEntry>()
        val parts = ArrayList<CleanEntry>()
        val seen = HashSet<String>()
        for (inst in instances) {
            val libs = File(inst, "libraries")
            if (!seen.add(key(libs))) continue
            if (!libs.isDirectory) continue
            libs.walkTopDown().filter { it.isFile }.forEach { file ->
                when {
                    file.name.endsWith(PART_SUFFIX, ignoreCase = true) -> parts += entry(file)
                    key(file) !in used -> unused += entry(file)
                }
            }
        }

        val cached = ArrayList<CleanEntry>()
        if (cacheDir.isDirectory) {
            cacheDir.walkTopDown()
                .filter { it.isFile && it.name.endsWith(PART_SUFFIX, ignoreCase = true) }
                .forEach { parts += entry(it) }
            cacheDir.listFiles()
                ?.filter { it.isFile && CACHE_NAME.matches(it.name) }
                ?.forEach { cached += entry(it) }
        }
        return CleanPlan(unused, parts, cached)
    }

    /**
     * 按 [kinds] 真删。只删 [plan] 里列过的那几条——扫描之后目录又变了也不会误伤；
     * 删不动的（权限、正被占用）跳过不计，不抛。
     */
    fun apply(plan: CleanPlan, kinds: Collection<String> = ALL_KINDS): CleanResult {
        var removed = 0
        var bytes = 0L
        for (row in plan.entries(kinds)) {
            val file = File(row.path)
            if (!file.isFile) continue
            val size = file.length()
            if (!runCatching { file.delete() }.getOrDefault(false)) continue
            removed++
            bytes += size
        }
        return CleanResult(removed, bytes)
    }

    /**
     * 一个实例里所有已装版本真正引用到的库文件，收成 [key] 过的绝对路径。
     *
     * 判定放宽不收紧：少算一条就等于把还在用的 jar 当垃圾删掉，所以 rules 挡掉的、
     * natives 那些也一律算「在用」，宁可留着。
     */
    fun usedLibraryPaths(instDir: File): Set<String> {
        val libs = File(instDir, "libraries")
        val used = HashSet<String>()
        for (version in InstanceStore.installedVersionsIn(instDir)) {
            val json = runCatching { LaunchPlanner.resolveJson(instDir, version) }.getOrNull() ?: continue
            val arr = json.optJSONArray("libraries") ?: continue
            for (i in 0 until arr.length()) {
                val lib = arr.optJSONObject(i) ?: continue
                libraryPaths(lib).forEach { used += key(File(libs, it)) }
            }
        }
        return used
    }

    /**
     * 一条 library 声明对应到 `libraries/` 下的哪几个相对路径。
     *
     * `downloads.artifact.path` 优先；没有就按 maven 坐标推（`natives` 那种除外，
     * 它的坐标指的不是同一个文件）。`downloads.classifiers` 里的全都算上。
     */
    internal fun libraryPaths(lib: JSONObject): List<String> {
        val out = ArrayList<String>(2)
        val downloads = lib.optJSONObject("downloads")
        val artifact = downloads?.optJSONObject("artifact")?.optString("path").orEmpty()
        if (artifact.isNotBlank()) {
            out += artifact
        } else if (!lib.has("natives")) {
            LoaderInstall.mavenPath(lib.optString("name"))?.let { out += it }
        }
        val classifiers = downloads?.optJSONObject("classifiers")
        classifiers?.keys()?.forEach { name ->
            val path = classifiers.optJSONObject(name)?.optString("path").orEmpty()
            if (path.isNotBlank()) out += path
        }
        return out
    }

    private fun entry(file: File): CleanEntry =
        CleanEntry(file.absoluteFile.normalize().path, runCatching { file.length() }.getOrDefault(0L))

    /** 比对用的路径形态：绝对、去掉 `..`、分隔符统一、大小写不敏感（与桌面 `.resolve().lower()` 同口径）。 */
    private fun key(file: File): String =
        file.absoluteFile.normalize().path.replace(File.separatorChar, '/').lowercase(Locale.US)
}
