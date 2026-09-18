package com.pymcl.mobile.data

import java.io.File

/**
 * 一条体检结论。
 *
 * 刻意只出**码**、不出文案：标题和说明由界面按 [code] 取词，英文界面上才不会漏出中文。
 * [detail] 与 [amount] 是文案里要填的变量部分——路径、文件名、份数、建议值。
 *
 * [fix] 是「去修」的落点，空串表示这条只能看、跳过去也没用。
 */
data class PreflightItem(
    val level: String,
    val code: String,
    val detail: String = "",
    val amount: Int = 0,
    val fix: String = "",
)

/** 一次体检的结果。[ok] = 没有 error 级项，与桌面 `preflight.check_launch` 的 ok 同义。 */
data class PreflightResult(val items: List<PreflightItem>) {
    val ok: Boolean get() = items.none { it.level == Preflight.ERROR }

    val errors: List<PreflightItem> get() = items.filter { it.level == Preflight.ERROR }

    val warns: List<PreflightItem> get() = items.filter { it.level == Preflight.WARN }
}

/**
 * 启动前体检，移植自桌面 `mclauncher/preflight.py`（它自己对齐 PCL 的「先查再启」）。
 *
 * 三处刻意与桌面不同，都是安卓这边的事实决定的：
 * 1. **缺文件只报 warn**。桌面缺三个以上库就 error 挡住；安卓点启动会自己把缺的补下来
 *    （`AppViewModel.launchGame` 里那段 installVanilla），报成 error 反而挡掉了能自愈的路。
 * 2. **Java 不查 exe，查大版本**。本包只带 JRE 17/21，`McLaunch.prepare` 遇到 jre8/jre25
 *    直接抛；体检提前把这一条报出来，而不是让用户点了启动才看见。
 * 3. **可用内存读 /proc/meminfo**。桌面走 GlobalMemoryStatusEx，安卓这边同样的信息在
 *    MemAvailable 那一行，顺带让这个函数在纯 JVM 单测里也能跑（读不到就跳过这一条）。
 */
object Preflight {
    const val ERROR = "error"
    const val WARN = "warn"
    const val OK = "ok"

    /** [PreflightItem.fix] 的落点。 */
    const val FIX_NONE = ""
    const val FIX_DOWNLOAD = "download"
    const val FIX_REPAIR = "repair"
    const val FIX_JAVA = "java"
    const val FIX_MEMORY = "memory"
    const val FIX_MODS = "mods"

    /** 本包随包带的 JRE，只有这两档；其余大版本体检直接报错。 */
    private val BUNDLED_JRE = setOf("jre17", "jre21")

    /** 低于这个数就起不来，对齐桌面的 512 MB。 */
    const val DISK_ERROR_MB = 512L

    /** 低于这个数还能启动，但装大整合包会炸，对齐桌面的 2048 MB。 */
    const val DISK_WARN_MB = 2048L

    /** 游戏内存加这一截仍超过可用物理内存就报警，对齐桌面的 1024 MB 余量。 */
    const val MEMORY_HEADROOM_MB = 1024L

    /** 缺文件、解压成文件夹这类清单在 detail 里最多列这么多条，再多用户也看不完。 */
    private const val MAX_SAMPLE = 8

    /**
     * 跑一遍体检。
     *
     * @param availableMemoryMb 设备可用物理内存；传 -1 让它自己读 /proc/meminfo，读不到就跳过内存这条
     * @param freeDiskMb        实例所在盘剩余空间；传 -1 用 [File.getUsableSpace]
     * @param runtimeReady      某个 Java 大版本的运行时解开了没。默认问 [RuntimeInstaller]，单测传桩
     */
    fun check(
        instDir: File,
        version: String,
        memoryMb: Int,
        availableMemoryMb: Long = -1L,
        freeDiskMb: Long = -1L,
        runtimeReady: (Int) -> Boolean = { RuntimeInstaller.ready(it) },
    ): PreflightResult {
        val items = mutableListOf<PreflightItem>()
        if (!instDir.isDirectory) {
            return PreflightResult(listOf(item(ERROR, "no_instance", instDir.absolutePath)))
        }
        probeWritable(instDir)?.let { items += item(ERROR, "not_writable", it) }

        checkDisk(instDir, freeDiskMb)?.let { items += it }

        val id = version.trim()
        if (id.isEmpty()) {
            items += item(ERROR, "no_version", fix = FIX_DOWNLOAD)
            return PreflightResult(items)
        }

        val jsonFile = VersionOps.jsonFile(instDir, id)
        if (!jsonFile.isFile) {
            items += item(ERROR, "no_version_json", id, fix = FIX_DOWNLOAD)
            return PreflightResult(items)
        }

        val json = runCatching { LaunchPlanner.resolveJson(instDir, id) }.getOrNull()
        val missing = runCatching { VersionOps.missingFiles(instDir, id) }.getOrDefault(emptyList())
        if (missing.isNotEmpty()) {
            items += item(
                WARN,
                "files_missing",
                missing.take(MAX_SAMPLE).joinToString("\n") { File(it).name },
                missing.size,
                FIX_REPAIR,
            )
        }

        checkMods(instDir, id).forEach { items += it }

        if (json != null) {
            val major = JavaRuntime.javaMajor(json, id)
            val jre = JavaRuntime.jreDirName(major)
            if (jre !in BUNDLED_JRE) {
                items += item(ERROR, "java_unavailable", jre, major, FIX_JAVA)
            } else if (!runCatching { runtimeReady(major) }.getOrDefault(true)) {
                items += item(WARN, "java_not_ready", jre, major)
            }
        }

        checkMemory(memoryMb, availableMemoryMb)?.let { items += it }

        if (items.isEmpty()) items += item(OK, "ready")
        return PreflightResult(items)
    }

    /** 实例目录写不进去时返回系统给的原因，写得进去返回 null。 */
    private fun probeWritable(instDir: File): String? {
        val probe = File(instDir, ".pymcl_write_probe")
        return try {
            probe.writeText("ok", Charsets.UTF_8)
            probe.delete()
            null
        } catch (e: Exception) {
            e.message ?: e.toString()
        }
    }

    private fun checkDisk(instDir: File, freeDiskMb: Long): PreflightItem? {
        val free = if (freeDiskMb >= 0) {
            freeDiskMb
        } else {
            runCatching { instDir.usableSpace / (1024 * 1024) }.getOrDefault(-1L)
        }
        if (free < 0) return null
        return when {
            free < DISK_ERROR_MB -> item(ERROR, "disk_low", amount = free.toInt())
            free < DISK_WARN_MB -> item(WARN, "disk_warn", amount = free.toInt())
            else -> null
        }
    }

    /**
     * mods 目录的两条：解压成文件夹的、以及原版版本下面躺着 jar 的。
     * 判定与桌面 `preflight._check_*` 同口径，加载器名单也照抄那一份。
     */
    private fun checkMods(instDir: File, version: String): List<PreflightItem> {
        val dir = Mods.dirFor(instDir, version)
        if (!dir.isDirectory) return emptyList()
        val children = dir.listFiles() ?: return emptyList()
        val out = mutableListOf<PreflightItem>()

        val unzipped = children.filter { it.isDirectory && !it.name.startsWith(".") }.map { it.name }
        if (unzipped.isNotEmpty()) {
            out += item(
                ERROR,
                "mod_unzipped",
                unzipped.take(MAX_SAMPLE).joinToString("\n"),
                unzipped.size,
                FIX_MODS,
            )
        }

        val jars = children.count { it.isFile && it.name.endsWith(".jar", true) }
        val looksLoader = LOADER_TOKENS.any { it in version.lowercase() }
        if (jars > 0 && !looksLoader) {
            out += item(WARN, "vanilla_mods", amount = jars, fix = FIX_MODS)
        }
        return out
    }

    private fun checkMemory(memoryMb: Int, availableMemoryMb: Long): PreflightItem? {
        val want = memoryMb.toLong()
        if (want <= 0) return null
        val avail = if (availableMemoryMb >= 0) availableMemoryMb else availableMemoryMb()
        if (avail < 0) return null
        if (want + MEMORY_HEADROOM_MB <= avail) return null
        return item(WARN, "memory_high", avail.toString(), suggestMemoryMb(avail), FIX_MEMORY)
    }

    /** 报警时建议调到多少：留出 [MEMORY_HEADROOM_MB] 余量，再往下不低于 512。 */
    fun suggestMemoryMb(availableMemoryMb: Long): Int =
        (availableMemoryMb - MEMORY_HEADROOM_MB).coerceAtLeast(512L).toInt()

    /**
     * 设备当前可用物理内存（MB）。读不到返回 -1——体检拿不准就不报，别吓唬用户。
     *
     * 用 MemAvailable 而不是 MemFree：后者不算可回收的页缓存，在安卓上常年只有几百 MB，
     * 按它判断的话每次启动都会误报「内存不够」。
     */
    fun availableMemoryMb(meminfo: File = File("/proc/meminfo")): Long {
        if (!meminfo.isFile) return -1L
        val line = runCatching {
            meminfo.useLines { lines -> lines.firstOrNull { it.startsWith("MemAvailable:") } }
        }.getOrNull() ?: return -1L
        val kb = Regex("""(\d+)""").find(line)?.groupValues?.get(1)?.toLongOrNull() ?: return -1L
        return kb / 1024
    }

    private fun item(
        level: String,
        code: String,
        detail: String = "",
        amount: Int = 0,
        fix: String = FIX_NONE,
    ) = PreflightItem(level, code, detail, amount, fix)

    /** 版本名里出现这些就当装了加载器，mods 目录里有 jar 是正常的。 */
    private val LOADER_TOKENS = listOf(
        "forge", "fabric", "quilt", "neoforge", "optifine", "liteloader",
    )
}
