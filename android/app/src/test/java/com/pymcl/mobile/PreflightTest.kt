package com.pymcl.mobile

import com.pymcl.mobile.data.Preflight
import com.pymcl.mobile.data.PreflightItem
import com.pymcl.mobile.data.PreflightResult
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 启动前体检。
 *
 * 全部走真实目录：体检的结论几乎全来自「盘上到底有没有这个文件」，
 * 拿 mock 测等于把被测的那件事本身假掉了。
 */
class PreflightTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-preflight").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    /** 装一个「文件齐全」的版本：json + jar，且 json 里不引任何库。 */
    private fun installVersion(id: String, json: String = """{"id":"$id","libraries":[]}""") {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText(json)
        File(inst, "versions/$id/$id.jar").writeText("jar")
    }

    /** 体检默认把设备探测那两项关掉，用例只盯自己那一条。 */
    private fun check(
        version: String,
        memoryMb: Int = 2048,
        availableMemoryMb: Long = 8192,
        freeDiskMb: Long = 20480,
        runtimeReady: (Int) -> Boolean = { true },
    ): PreflightResult = Preflight.check(
        inst, version, memoryMb,
        availableMemoryMb = availableMemoryMb,
        freeDiskMb = freeDiskMb,
        runtimeReady = runtimeReady,
    )

    private fun PreflightResult.find(code: String): PreflightItem? = items.firstOrNull { it.code == code }

    // ------------------------------------------------------------ 整体

    @Test
    fun everythingInPlaceReportsReadyAndNothingElse() {
        installVersion("1.20.1")
        val result = check("1.20.1")
        assertTrue(result.ok)
        assertEquals(listOf("ready"), result.items.map { it.code })
        assertEquals(Preflight.OK, result.items.single().level)
    }

    @Test
    fun missingInstanceDirIsTheOnlyThingReported() {
        val gone = File(inst, "nope")
        val result = Preflight.check(gone, "1.20.1", 2048, 8192, 20480) { true }
        assertFalse(result.ok)
        assertEquals(listOf("no_instance"), result.items.map { it.code })
        assertEquals(gone.absolutePath, result.items.single().detail)
    }

    // ------------------------------------------------------------ 版本

    @Test
    fun noVersionSelectedStopsTheRestOfTheChecks() {
        val result = check("")
        assertFalse(result.ok)
        assertEquals(listOf("no_version"), result.items.map { it.code })
        assertEquals(Preflight.FIX_DOWNLOAD, result.items.single().fix)
    }

    @Test
    fun versionWithoutJsonIsAnErrorThatPointsAtTheDownloadPage() {
        val result = check("1.20.1")
        assertFalse(result.ok)
        val item = result.find("no_version_json")!!
        assertEquals(Preflight.ERROR, item.level)
        assertEquals("1.20.1", item.detail)
        assertEquals(Preflight.FIX_DOWNLOAD, item.fix)
    }

    /**
     * 缺文件在安卓上只算 warn。点启动会自己把缺的补下来（launchGame 里那段 installVanilla），
     * 报成 error 就把这条能自愈的路挡死了——这是与桌面 preflight 有意的一处不同。
     */
    @Test
    fun missingFilesAreOnlyAWarningBecauseLaunchRepairsThem() {
        installVersion(
            "1.20.1",
            """{"id":"1.20.1","libraries":[{"name":"com.example:lib:1.0",
               "downloads":{"artifact":{"path":"com/example/lib/1.0/lib-1.0.jar"}}}]}""",
        )
        val result = check("1.20.1")
        assertTrue("缺文件不该挡住启动", result.ok)
        val item = result.find("files_missing")!!
        assertEquals(Preflight.WARN, item.level)
        assertEquals(1, item.amount)
        assertEquals("lib-1.0.jar", item.detail)
        assertEquals(Preflight.FIX_REPAIR, item.fix)
    }

    // ------------------------------------------------------------ 模组

    @Test
    fun modsExtractedIntoFoldersBlockTheLaunch() {
        installVersion("1.20.1-fabric")
        File(inst, "mods/sodium-0.5.8").mkdirs()
        File(inst, "mods/lithium-0.11").mkdirs()
        val result = check("1.20.1-fabric")
        assertFalse(result.ok)
        val item = result.find("mod_unzipped")!!
        assertEquals(Preflight.ERROR, item.level)
        assertEquals(2, item.amount)
        assertEquals(Preflight.FIX_MODS, item.fix)
        assertTrue("sodium-0.5.8" in item.detail)
    }

    @Test
    fun jarsUnderAVanillaVersionAreWarnedAboutButLoaderNamesAreNot() {
        installVersion("1.20.1")
        File(inst, "mods").mkdirs()
        File(inst, "mods/sodium.jar").writeText("jar")
        assertEquals(1, check("1.20.1").find("vanilla_mods")?.amount)

        installVersion("1.20.1-fabric")
        File(inst, "mods/extra.jar").writeText("jar")
        assertNull("版本名带 fabric 就不该再提醒", check("1.20.1-fabric").find("vanilla_mods"))
    }

    // ------------------------------------------------------------ Java

    @Test
    fun aVersionNeedingJava8IsBlockedBecauseThisBuildOnlyShipsJre17And21() {
        installVersion("1.12.2", """{"id":"1.12.2","libraries":[]}""")
        val result = check("1.12.2")
        assertFalse(result.ok)
        val item = result.find("java_unavailable")!!
        assertEquals("jre8", item.detail)
        assertEquals(8, item.amount)
        assertEquals(Preflight.FIX_JAVA, item.fix)
    }

    @Test
    fun aBundledRuntimeThatIsNotUnpackedYetIsOnlyAWarning() {
        installVersion("1.20.1")
        val result = check("1.20.1", runtimeReady = { false })
        assertTrue(result.ok)
        val item = result.find("java_not_ready")!!
        assertEquals(Preflight.WARN, item.level)
        assertEquals("jre17", item.detail)
    }

    @Test
    fun javaVersionComesFromTheDeclaredMajorNotJustTheVersionName() {
        installVersion("weird-name", """{"id":"weird-name","javaVersion":{"majorVersion":21},"libraries":[]}""")
        val result = check("weird-name")
        assertTrue(result.ok)
        assertNull(result.find("java_unavailable"))
    }

    // ------------------------------------------------------------ 磁盘与内存

    @Test
    fun diskSpaceHasTwoTiers() {
        installVersion("1.20.1")
        assertEquals(Preflight.ERROR, check("1.20.1", freeDiskMb = 200).find("disk_low")?.level)
        assertEquals(Preflight.WARN, check("1.20.1", freeDiskMb = 1024).find("disk_warn")?.level)
        assertNull(check("1.20.1", freeDiskMb = 4096).find("disk_warn"))
    }

    @Test
    fun memoryIsFlaggedOnlyWhenItLeavesNoHeadroomAndComesWithASuggestion() {
        installVersion("1.20.1")
        assertNull(check("1.20.1", memoryMb = 2048, availableMemoryMb = 6000).find("memory_high"))

        val tight = check("1.20.1", memoryMb = 4096, availableMemoryMb = 4608).find("memory_high")!!
        assertEquals(Preflight.WARN, tight.level)
        assertEquals("4608", tight.detail)
        assertEquals(3584, tight.amount)
        assertEquals(Preflight.FIX_MEMORY, tight.fix)
    }

    @Test
    fun theSuggestedMemoryNeverDropsBelowTheFloor() {
        assertEquals(512, Preflight.suggestMemoryMb(600))
        assertEquals(512, Preflight.suggestMemoryMb(0))
        assertEquals(3072, Preflight.suggestMemoryMb(4096))
    }

    @Test
    fun deviceMemoryIsReadFromMemAvailableAndMissingFilesAreNotAnError() {
        val meminfo = File(inst, "meminfo")
        meminfo.writeText("MemTotal:       8000000 kB\nMemFree:         120000 kB\nMemAvailable:   3145728 kB\n")
        assertEquals(3072, Preflight.availableMemoryMb(meminfo))
        assertEquals(-1L, Preflight.availableMemoryMb(File(inst, "no-such-file")))
    }
}
