package com.pymcl.mobile.data

import java.io.File
import kotlin.math.max
import kotlin.math.roundToLong

/**
 * 一次硬件采样。**采集与判断分开**：判断那一半收这个对象，单测直接喂数，
 * 不用去碰 /proc 也不用 Android Context。拿不到的项留 0，判断那边会退回默认值。
 */
data class HardwareProbe(
    val totalRamBytes: Long = 0L,
    val cpuCount: Int = 0,
)

/**
 * 推荐结果。字段名与桌面 `sysinfo.get_smart_recommendation` 返回的那七个键一一对应
 * （memory_mb / java_major / window_width / window_height / gc_preset / cpu_count / total_ram_gb）。
 */
data class Recommendation(
    val memoryMb: Int,
    val javaMajor: Int,
    val windowWidth: Int,
    val windowHeight: Int,
    val gcPreset: String,
    val cpuCount: Int,
    val totalRamGb: Double,
)

/**
 * 按硬件给内存 / 参数推荐，对齐桌面 `mclauncher/sysinfo.py:get_smart_recommendation`。
 *
 * 分档与那边逐字一致（≥32G→12288 / ≥16G→8192 / ≥8G→4096 / 其余 2048），再压一道
 * 「不超过物理内存的 75%、下限 1024」的保险；采不到硬件就整份退回默认值，跟桌面那个
 * 兜底 `except: pass` 一个效果——推荐算不出来不该把设置页拖崩。
 */
object SmartRecommendation {
    const val DEFAULT_MEMORY_MB = 4096
    const val DEFAULT_JAVA_MAJOR = 17
    const val DEFAULT_WINDOW_WIDTH = 854
    const val DEFAULT_WINDOW_HEIGHT = 480
    const val DEFAULT_GC_PRESET = "auto"
    const val DEFAULT_CPU_COUNT = 4
    const val DEFAULT_TOTAL_RAM_GB = 8.0

    /** 保险档：最多给物理内存的这个比例，且不低于 [MIN_MEMORY_MB]。 */
    const val SAFE_RATIO = 0.75
    const val MIN_MEMORY_MB = 1024

    private const val BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0

    /** 采不到任何硬件信息时的那一份，与桌面的初值字典同值。 */
    val FALLBACK = Recommendation(
        memoryMb = DEFAULT_MEMORY_MB,
        javaMajor = DEFAULT_JAVA_MAJOR,
        windowWidth = DEFAULT_WINDOW_WIDTH,
        windowHeight = DEFAULT_WINDOW_HEIGHT,
        gcPreset = DEFAULT_GC_PRESET,
        cpuCount = DEFAULT_CPU_COUNT,
        totalRamGb = DEFAULT_TOTAL_RAM_GB,
    )

    /** 内存分档。桌面那四档原样搬过来。 */
    fun tierMemoryMb(totalGb: Double): Int = when {
        totalGb >= 32 -> 12288
        totalGb >= 16 -> 8192
        totalGb >= 8 -> 4096
        else -> 2048
    }

    /** 分档值再过一遍 75% 保险。整机 3G 的手机不该被推荐 2G 堆。 */
    fun capToSafe(memoryMb: Int, totalGb: Double): Int {
        val safe = (totalGb * SAFE_RATIO * 1024).toInt()
        return if (memoryMb > safe) max(MIN_MEMORY_MB, safe) else memoryMb
    }

    fun of(probe: HardwareProbe): Recommendation {
        val cpu = if (probe.cpuCount > 0) probe.cpuCount else DEFAULT_CPU_COUNT
        if (probe.totalRamBytes <= 0L) return FALLBACK.copy(cpuCount = cpu)
        val totalGb = probe.totalRamBytes / BYTES_PER_GB
        return FALLBACK.copy(
            memoryMb = capToSafe(tierMemoryMb(totalGb), totalGb),
            cpuCount = cpu,
            totalRamGb = round1(totalGb),
        )
    }

    /**
     * 真机上的那一份采样。
     *
     * 物理内存读 `/proc/meminfo`（而不是 ActivityManager）是为了这条路不依赖 Context：
     * 同一个函数单测里换一份假的 meminfo 就能跑。读不到当作 0，调用方拿到的是默认档。
     */
    fun probe(
        meminfo: File = File("/proc/meminfo"),
        cpuCount: Int = Runtime.getRuntime().availableProcessors(),
    ): HardwareProbe = HardwareProbe(
        totalRamBytes = runCatching { parseMemTotalBytes(meminfo.readText(Charsets.UTF_8)) }.getOrDefault(0L),
        cpuCount = cpuCount,
    )

    /** `MemTotal:  8123456 kB` → 字节。认不出来给 0。 */
    internal fun parseMemTotalBytes(text: String): Long {
        val line = text.lineSequence().firstOrNull { it.startsWith("MemTotal:") } ?: return 0L
        val kb = line.removePrefix("MemTotal:").trim().substringBefore(' ').toLongOrNull() ?: return 0L
        return if (kb > 0) kb * 1024L else 0L
    }

    /**
     * 推荐值落到界面上那根滑杆里。
     *
     * 桌面的内存框能到 32G，手机这根滑杆只到 8G（[maxMb]）——在 32G 的设备上桌面会推 12288，
     * 直接塞进去就是个滑杆拉不到的数。这里夹一道，界面另给一句说明。
     */
    fun applicableMemoryMb(memoryMb: Int, maxMb: Int, minMb: Int = 512): Int =
        memoryMb.coerceIn(minMb, maxMb)

    private fun round1(value: Double): Double = (value * 10).roundToLong() / 10.0
}
