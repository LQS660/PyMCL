package com.pymcl.mobile

import com.pymcl.mobile.data.HardwareProbe
import com.pymcl.mobile.data.SmartRecommendation
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 按硬件推荐内存 / 参数。逐档对着桌面 `sysinfo.get_smart_recommendation` 核：
 * 四道分档、75% 保险、1024 下限、采不到硬件时的整份默认值。
 */
class SmartRecommendationTest {
    private lateinit var tmp: File

    @Before
    fun setUp() {
        tmp = kotlin.io.path.createTempDirectory("pymcl-rec").toFile()
    }

    @After
    fun tearDown() {
        tmp.deleteRecursively()
    }

    private fun gb(value: Double) = (value * 1024 * 1024 * 1024).toLong()

    private fun recFor(ramGb: Double, cpu: Int = 8) =
        SmartRecommendation.of(HardwareProbe(gb(ramGb), cpu))

    private fun meminfo(body: String): File =
        File(tmp, "meminfo").also { it.writeText(body, Charsets.UTF_8) }

    // ---------------------------------------------------------------- 分档

    @Test
    fun everyTierMatchesDesktop() {
        assertEquals(12288, SmartRecommendation.tierMemoryMb(64.0))
        assertEquals(12288, SmartRecommendation.tierMemoryMb(32.0))
        assertEquals(8192, SmartRecommendation.tierMemoryMb(31.9))
        assertEquals(8192, SmartRecommendation.tierMemoryMb(16.0))
        assertEquals(4096, SmartRecommendation.tierMemoryMb(15.9))
        assertEquals(4096, SmartRecommendation.tierMemoryMb(8.0))
        assertEquals(2048, SmartRecommendation.tierMemoryMb(7.9))
        assertEquals(2048, SmartRecommendation.tierMemoryMb(0.5))
    }

    @Test
    fun tierBoundariesAreInclusiveOnTheLowSide() {
        // 32 / 16 / 8 这三个整点归上面那一档，跟桌面的 >= 一致
        assertEquals(12288, recFor(32.0).memoryMb)
        assertEquals(8192, recFor(16.0).memoryMb)
        assertEquals(4096, recFor(8.0).memoryMb)
    }

    // ---------------------------------------------------------------- 保险档

    @Test
    fun safeCapKeepsThreeQuartersOfPhysicalRam() {
        // 4G 机器：分档给 2048，75% 是 3072，不触顶
        assertEquals(2048, recFor(4.0).memoryMb)
        // 2G 机器：分档给 2048，75% 只有 1536，压到 1536
        assertEquals(1536, recFor(2.0).memoryMb)
    }

    @Test
    fun safeCapNeverGoesBelowOneGig() {
        // 1G 机器：75% 是 768，低于下限，抬回 1024——桌面那句 max(1024, safe)
        assertEquals(SmartRecommendation.MIN_MEMORY_MB, recFor(1.0).memoryMb)
        assertEquals(SmartRecommendation.MIN_MEMORY_MB, recFor(0.25).memoryMb)
    }

    @Test
    fun hugeRamStopsAtTheTopTier() {
        // 128G 也就推 12288：分档封顶，75% 保险这时不起作用
        assertEquals(12288, recFor(128.0).memoryMb)
    }

    // ---------------------------------------------------------------- 其余字段

    @Test
    fun theOtherFieldsAreTheDesktopConstants() {
        val rec = recFor(16.0)
        assertEquals(17, rec.javaMajor)
        assertEquals(854, rec.windowWidth)
        assertEquals(480, rec.windowHeight)
        assertEquals("auto", rec.gcPreset)
    }

    @Test
    fun ramIsReportedRoundedToOneDecimal() {
        assertEquals(7.7, recFor(7.68).totalRamGb, 0.001)
        assertEquals(16.0, recFor(16.0).totalRamGb, 0.001)
    }

    @Test
    fun cpuCountFallsBackToFourWhenUnknown() {
        assertEquals(12, SmartRecommendation.of(HardwareProbe(gb(16.0), 12)).cpuCount)
        assertEquals(SmartRecommendation.DEFAULT_CPU_COUNT, SmartRecommendation.of(HardwareProbe(gb(16.0), 0)).cpuCount)
    }

    // ---------------------------------------------------------------- 采不到

    @Test
    fun noHardwareInfoGivesTheWholeDefaultSet() {
        val rec = SmartRecommendation.of(HardwareProbe())
        assertEquals(SmartRecommendation.FALLBACK, rec)
        assertEquals(4096, rec.memoryMb)
        assertEquals(8.0, rec.totalRamGb, 0.001)
        assertEquals(4, rec.cpuCount)
    }

    @Test
    fun negativeOrZeroRamIsTreatedAsUnknown() {
        // 内存读成 0 时不能顺着算出「0.75 * 0 = 0」再抬到 1024，那是在瞎猜
        assertEquals(4096, SmartRecommendation.of(HardwareProbe(0L, 8)).memoryMb)
        assertEquals(4096, SmartRecommendation.of(HardwareProbe(-1L, 8)).memoryMb)
        // CPU 仍然按采到的报
        assertEquals(8, SmartRecommendation.of(HardwareProbe(0L, 8)).cpuCount)
    }

    // ---------------------------------------------------------------- 采样

    @Test
    fun memTotalIsReadFromProcMeminfo() {
        val probe = SmartRecommendation.probe(
            meminfo("MemTotal:        8123456 kB\nMemFree:          123456 kB\n"),
            cpuCount = 8,
        )
        assertEquals(8123456L * 1024, probe.totalRamBytes)
        assertEquals(8, probe.cpuCount)
    }

    @Test
    fun brokenOrMissingMeminfoIsZeroNotACrash() {
        assertEquals(0L, SmartRecommendation.parseMemTotalBytes(""))
        assertEquals(0L, SmartRecommendation.parseMemTotalBytes("MemFree: 100 kB"))
        assertEquals(0L, SmartRecommendation.parseMemTotalBytes("MemTotal:  这不是数字 kB"))
        assertEquals(0L, SmartRecommendation.parseMemTotalBytes("MemTotal:  0 kB"))
        // 文件根本不存在时也只是 0，上层拿到的是默认档
        assertEquals(0L, SmartRecommendation.probe(File(tmp, "nope"), cpuCount = 4).totalRamBytes)
    }

    @Test
    fun aRealPhoneProbeLandsOnAReasonableTier() {
        val probe = SmartRecommendation.probe(meminfo("MemTotal:        7912345 kB"), cpuCount = 8)
        val rec = SmartRecommendation.of(probe)
        // 7.5G 的机器：分档 2048，75% 是 5793，不触顶
        assertEquals(2048, rec.memoryMb)
        assertTrue(rec.totalRamGb in 7.0..8.0)
    }

    // ---------------------------------------------------------------- 落到滑杆

    @Test
    fun recommendationIsClampedIntoTheSliderRange() {
        // 手机这根滑杆只到 8192，32G 设备上桌面档位给的 12288 得夹回去
        assertEquals(8192, SmartRecommendation.applicableMemoryMb(12288, 8192))
        assertEquals(4096, SmartRecommendation.applicableMemoryMb(4096, 8192))
        assertEquals(512, SmartRecommendation.applicableMemoryMb(128, 8192))
    }
}
