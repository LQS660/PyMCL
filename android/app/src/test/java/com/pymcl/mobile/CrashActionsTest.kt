package com.pymcl.mobile

import com.pymcl.mobile.data.CrashAction
import com.pymcl.mobile.data.CrashActions
import com.pymcl.mobile.data.CrashReason
import com.pymcl.mobile.data.CrashRules
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.VersionSettings
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 崩溃页那排「一键修复」按钮：排哪几个、点下去做了什么。
 *
 * 归因本身在 CrashRulesTest 里钉过，这里只管从归因到动作、以及动作真落到盘上的那一段。
 */
class CrashActionsTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-crash-action").toFile()
        Settings.loadFromForTest(File(inst, "config.json"))
    }

    @After
    fun tearDown() {
        // 配置是全局单例，别把这一条写进去的东西留给下一条
        Settings.loadFromForTest(File(inst, "no-such-config.json"))
        inst.deleteRecursively()
    }

    private fun modsDir(): File = File(inst, "mods").also { it.mkdirs() }

    private fun mod(name: String): File = File(modsDir(), name).also { it.writeText("jar") }

    private fun reason(code: String, vararg extras: String) = CrashReason(code, extras.toList())

    // ------------------------------------------------------------ 排按钮

    @Test
    fun outOfMemorySuggestsRaisingMemoryAndStopsAtTheCeiling() {
        val one = CrashActions.build(listOf(reason("oom")), memoryMb = 2048).single()
        assertEquals(CrashActions.BUMP_MEMORY, one.id)
        assertEquals(3072, one.memoryMb)

        val capped = CrashActions.build(listOf(reason("oom")), memoryMb = 32768).single()
        assertEquals(CrashActions.MAX_MEMORY_MB, capped.memoryMb)
    }

    /**
     * 虚拟机压根没起来（安卓上最常见的原因就是内存要得比手机能给的还多）要的是**调小**。
     * 和 oom 共用一个 id 的话按钮就会说反话，所以这里是安卓独有的一条。
     */
    @Test
    fun aJvmThatNeverStartedSuggestsLoweringMemoryInstead() {
        val one = CrashActions.build(listOf(reason("jvm_start")), memoryMb = 4096).single()
        assertEquals(CrashActions.TRIM_MEMORY, one.id)
        assertEquals(3072, one.memoryMb)

        val floored = CrashActions.build(listOf(reason("jvm_start")), memoryMb = 1024).single()
        assertEquals(CrashActions.MIN_MEMORY_MB, floored.memoryMb)
    }

    @Test
    fun suspectedModsBecomeRealFileNamesFromTheModsFolder() {
        mod("sodium-fabric-0.5.8+mc1.20.1.jar")
        mod("lithium-fabric-0.11.2.jar")
        val actions = CrashActions.build(
            listOf(reason("mod_certain", "sodium", "lithium-fabric-0.11.2")),
            modsDir = modsDir(),
        )
        val disable = actions.single { it.id == CrashActions.DISABLE_MODS }
        assertEquals(
            listOf("sodium-fabric-0.5.8+mc1.20.1.jar", "lithium-fabric-0.11.2.jar"),
            disable.mods,
        )
    }

    @Test
    fun aSuspicionWithNothingToPointAtJustOpensTheModsPage() {
        modsDir()
        val actions = CrashActions.build(listOf(reason("mixin")), modsDir = modsDir())
        assertEquals(listOf(CrashActions.OPEN_MODS), actions.map { it.id })
    }

    @Test
    fun javaReasonsPickTheMajorTheDesktopWouldPick() {
        fun majorOf(code: String) =
            CrashActions.build(listOf(reason(code))).single { it.id == CrashActions.NEED_JAVA }.major

        assertEquals(11, majorOf("need_java11"))
        assertEquals(8, majorOf("jdk"))
        assertEquals(8, majorOf("old_forge_new_java"))
        assertEquals(17, majorOf("java_too_new"))
        assertEquals(17, majorOf("openj9"))
    }

    /** 原生库没加载起来不是缺某个大版本，是随包那份解坏了——只跳 Java 页，不写版本号。 */
    @Test
    fun aBrokenNativeLibraryAlsoGoesToTheJavaPageButWithoutAMajor() {
        val one = CrashActions.build(listOf(reason("native_lib", "libawt_xawt.so"))).single()
        assertEquals(CrashActions.NEED_JAVA, one.id)
        assertEquals(0, one.major)
    }

    @Test
    fun repairIsOfferedOnlyWhenWeKnowWhichVersionCrashed() {
        assertEquals(
            emptyList<CrashAction>(),
            CrashActions.build(listOf(reason("libs_missing")), hasVersion = false),
        )
        assertEquals(
            listOf(CrashActions.REPAIR_VERSION),
            CrashActions.build(listOf(reason("libs_missing")), hasVersion = true).map { it.id },
        )
    }

    @Test
    fun duplicateModsKeepTheFirstCopyAndDisableTheRest() {
        mod("jei-1.20.1-15.2.0.jar")
        mod("jei-1.20.1-15.3.0.jar")
        val actions = CrashActions.build(
            listOf(reason("mod_dup", "jei-1.20.1-15.2.0.jar", "jei-1.20.1-15.3.0.jar")),
            modsDir = modsDir(),
        )
        assertEquals(
            listOf(CrashActions.OPEN_MODS, CrashActions.DISABLE_MODS),
            actions.map { it.id },
        )
        assertEquals(listOf("jei-1.20.1-15.3.0.jar"), actions.last().mods)
    }

    @Test
    fun rendererAndDriverReasonsAllLandOnTheSameHint() {
        listOf("pixel_format", "opengl_1282", "gles_renderer", "native_crash").forEach { code ->
            assertEquals(
                "$code 应该给渲染器提示",
                listOf(CrashActions.OPEN_GPU_HINT),
                CrashActions.build(listOf(reason(code))).map { it.id },
            )
        }
    }

    @Test
    fun theSameReasonTwiceStillOnlyProducesOneButton() {
        val actions = CrashActions.build(listOf(reason("oom"), reason("oom")), memoryMb = 2048)
        assertEquals(1, actions.size)
    }

    @Test
    fun aCrashReportOnDiskAlwaysGetsItsOwnButtonAtTheEnd() {
        val actions = CrashActions.build(listOf(reason("oom")), hasCrashFile = true)
        assertEquals(CrashActions.OPEN_CRASH_FILE, actions.last().id)
    }

    /** 端到端一趟：真实形状的日志 → 归因 → 按钮。 */
    @Test
    fun aRealOutOfMemoryLogEndsUpWithARaiseMemoryButton() {
        val reasons = CrashRules.analyze("[Render thread/ERROR]: java.lang.OutOfMemoryError: Java heap space")
        val actions = CrashActions.build(reasons, memoryMb = 2048)
        assertEquals(listOf(CrashActions.BUMP_MEMORY), actions.map { it.id })
    }

    // ------------------------------------------------------------ 点下去

    @Test
    fun disablingModsRenamesThemOnDiskAndCountsWhatWorked() {
        mod("sodium.jar")
        mod("lithium.jar")
        val result = CrashActions.apply(
            CrashAction(CrashActions.DISABLE_MODS, mods = listOf("sodium.jar", "lithium.jar")),
            inst,
        )
        assertTrue(result.ok)
        assertEquals(CrashActions.R_DISABLED, result.code)
        assertEquals(2, result.count)
        assertTrue(File(modsDir(), "sodium.jar.disabled").isFile)
        assertFalse(File(modsDir(), "sodium.jar").isFile)
    }

    @Test
    fun oneMissingModDoesNotSinkTheWholeAction() {
        mod("sodium.jar")
        val result = CrashActions.apply(
            CrashAction(CrashActions.DISABLE_MODS, mods = listOf("sodium.jar", "ghost.jar")),
            inst,
        )
        assertTrue(result.ok)
        assertEquals(1, result.count)
        assertTrue("失败的那个要说出来", "ghost.jar" in result.detail)
    }

    @Test
    fun nothingDisabledAtAllIsAFailure() {
        modsDir()
        val result = CrashActions.apply(
            CrashAction(CrashActions.DISABLE_MODS, mods = listOf("ghost.jar")),
            inst,
        )
        assertFalse(result.ok)
        assertEquals(CrashActions.R_DISABLE_FAILED, result.code)
    }

    /** 全局默认和这个版本自己的都得清；只清一处，下次启动还会被另一处顶回同一个坑。 */
    @Test
    fun clearingJvmArgsWipesBothTheGlobalDefaultAndTheVersionsOwn() {
        Settings.set(SettingsKeys.DEFAULT_JVM_ARGS, "-XX:+UseFancyGC")
        File(inst, "versions/1.20.1").mkdirs()
        VersionSettings.save(
            inst,
            "1.20.1",
            VersionSettings.load(inst, "1.20.1").copy(jvmArgs = "-XX:+UseFancyGC", gc = "g1"),
        )

        val result = CrashActions.apply(CrashAction(CrashActions.RESET_JVM_ARGS), inst, "1.20.1")

        assertTrue(result.ok)
        assertEquals(CrashActions.R_JVM_CLEARED, result.code)
        assertEquals("", Settings.str(SettingsKeys.DEFAULT_JVM_ARGS))
        assertEquals("", VersionSettings.load(inst, "1.20.1").jvmArgs)
        assertEquals("", VersionSettings.load(inst, "1.20.1").gc)
    }

    @Test
    fun theActionsThatNeedAnotherPageComeBackAsARoute() {
        fun route(action: CrashAction) = CrashActions.apply(action, inst).route

        assertEquals(CrashActions.ROUTE_REPAIR, route(CrashAction(CrashActions.REPAIR_VERSION)))
        assertEquals(CrashActions.ROUTE_JAVA, route(CrashAction(CrashActions.NEED_JAVA, major = 17)))
        assertEquals(CrashActions.ROUTE_MODS, route(CrashAction(CrashActions.OPEN_MODS)))
        assertEquals(CrashActions.ROUTE_CRASH, route(CrashAction(CrashActions.OPEN_CRASH_FILE)))
        assertEquals(CrashActions.ROUTE_MEMORY, route(CrashAction(CrashActions.BUMP_MEMORY, memoryMb = 6144)))
    }

    @Test
    fun theMemoryRouteCarriesAValueThatIsAlreadyClamped() {
        val low = CrashActions.apply(CrashAction(CrashActions.TRIM_MEMORY, memoryMb = 64), inst)
        assertEquals(CrashActions.MIN_MEMORY_MB, low.count)

        val high = CrashActions.apply(CrashAction(CrashActions.BUMP_MEMORY, memoryMb = 99999), inst)
        assertEquals(CrashActions.MAX_MEMORY_MB, high.count)
    }

    @Test
    fun theGpuHintIsJustText() {
        val result = CrashActions.apply(CrashAction(CrashActions.OPEN_GPU_HINT), inst)
        assertTrue(result.ok)
        assertEquals(CrashActions.R_GPU_HINT, result.code)
        assertEquals("", result.route)
    }

    @Test
    fun anUnknownActionSaysSoInsteadOfPretendingItWorked() {
        val result = CrashActions.apply(CrashAction("teleport_me_home"), inst)
        assertFalse(result.ok)
        assertEquals(CrashActions.R_UNKNOWN, result.code)
        assertEquals("teleport_me_home", result.detail)
    }
}
