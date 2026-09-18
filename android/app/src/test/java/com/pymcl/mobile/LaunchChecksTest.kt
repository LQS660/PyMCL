package com.pymcl.mobile

import com.pymcl.mobile.data.CrashAction
import com.pymcl.mobile.data.CrashActionResult
import com.pymcl.mobile.data.CrashActions
import com.pymcl.mobile.data.DirectConnect
import com.pymcl.mobile.data.I18n
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.Preflight
import com.pymcl.mobile.data.PreflightItem
import com.pymcl.mobile.ui.crashActionLabel
import com.pymcl.mobile.ui.crashResultText
import com.pymcl.mobile.ui.preflightDetail
import com.pymcl.mobile.ui.preflightFixLabel
import com.pymcl.mobile.ui.preflightLevelLabel
import com.pymcl.mobile.ui.preflightTitle
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 启动页「先查再启」那一层的纯逻辑：直连地址怎么拼回启动计划、体检码 / 修复动作怎么取词。
 * data 层的 Preflight / CrashActions / parseDirect 各有各的用例，这里只盯界面接过来的那一段。
 */
class LaunchChecksTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        I18n.reset()
        inst = kotlin.io.path.createTempDirectory("pymcl-launch-checks").toFile()
    }

    @After
    fun tearDown() {
        I18n.reset()
        inst.deleteRecursively()
    }

    private fun localesDir(): File = listOf(
        "src/main/assets/locales", "app/src/main/assets/locales", "android/app/src/main/assets/locales",
    ).map { File(it) }.first { it.isDirectory }

    // ------------------------------------------------------------ 直连地址

    @Test
    fun directAddressWrapsIpv6AndRoundTrips() {
        assertEquals("1.2.3.4:25565", DirectConnect.address("1.2.3.4", 25565))
        assertEquals("mc.example.com:25570", DirectConnect.address(" mc.example.com ", 25570))
        // IPv6 不套方括号的话 fe80::1:25570 会被当成没有端口的一整串
        assertEquals("[fe80::1]:25570", DirectConnect.address("fe80::1", 25570))
        assertEquals("[fe80::1]:25570", DirectConnect.address("[fe80::1]", 25570))
        // 端口不合法就只给主机，让 parseDirect 按默认端口处理
        assertEquals("mc.example.com", DirectConnect.address("mc.example.com", 0))

        assertTrue(DirectConnect.roundTrips("1.2.3.4", 25565))
        assertTrue(DirectConnect.roundTrips("fe80::1", 25570))
        assertTrue(DirectConnect.roundTrips("mc.example.com", 25566))
        // 本机地址拼回去也过不了 parseDirect
        assertFalse(DirectConnect.roundTrips("localhost", 25565))
        assertFalse(DirectConnect.roundTrips("", 25565))
    }

    @Test
    fun directAddressFeedsServerAndPortIntoTheLaunchPlan() {
        File(inst, "versions/1.20.1").mkdirs()
        File(inst, "versions/1.20.1/1.20.1.json").writeText("""{"id":"1.20.1","libraries":[]}""")
        File(inst, "versions/1.20.1/1.20.1.jar").writeText("jar")
        val v6 = LaunchPlanner.plan("default", "1.20.1", "Player", 2048, inst, DirectConnect.address("fe80::1", 25570))
        assertEquals(listOf("--server", "fe80::1", "--port", "25570"), v6.serverArgs)
        val v4 = LaunchPlanner.plan("default", "1.20.1", "Player", 2048, inst, DirectConnect.address("1.2.3.4", 25565))
        assertEquals(listOf("--server", "1.2.3.4", "--port", "25565"), v4.serverArgs)
    }

    // ------------------------------------------------------------ 体检文案

    private val preflightCodes = listOf(
        "no_instance", "not_writable", "no_version", "no_version_json", "files_missing",
        "disk_low", "disk_warn", "mod_unzipped", "vanilla_mods", "java_unavailable",
        "java_not_ready", "memory_high", "ready", "check_failed",
    )

    @Test
    fun everyPreflightCodeHasAHumanTitle() {
        for (code in preflightCodes) {
            val title = preflightTitle(code)
            assertTrue(code, title.isNotBlank())
            assertNotEquals("$code 只回了码本身", code, title)
        }
        // 不认识的码原样回，别把新码吞成空白
        assertEquals("brand_new", preflightTitle("brand_new"))
    }

    @Test
    fun preflightDetailCarriesTheVariablesIn() {
        val missing = preflightDetail(PreflightItem(Preflight.WARN, "files_missing", "a.jar\nb.jar", 3, Preflight.FIX_REPAIR))
        assertTrue(missing.contains("3"))
        assertTrue(missing.contains("a.jar") && missing.contains("b.jar"))

        val memory = preflightDetail(PreflightItem(Preflight.WARN, "memory_high", "3072", 2048, Preflight.FIX_MEMORY))
        assertTrue(memory.contains("3072") && memory.contains("2048"))

        val disk = preflightDetail(PreflightItem(Preflight.ERROR, "disk_low", amount = 200))
        assertTrue(disk.contains("200"))

        val java = preflightDetail(PreflightItem(Preflight.ERROR, "java_unavailable", "jre8", 8, Preflight.FIX_JAVA))
        assertTrue(java.contains("jre8") && java.contains("8"))

        // 系统原话直接透传的那几条
        assertEquals("EACCES", preflightDetail(PreflightItem(Preflight.ERROR, "not_writable", "EACCES")))
        assertEquals("boom", preflightDetail(PreflightItem(Preflight.ERROR, "check_failed", "boom")))
        assertTrue(preflightDetail(PreflightItem(Preflight.OK, "ready")).isNotBlank())
    }

    @Test
    fun everyFixTargetHasAButtonLabelAndNoneHasNone() {
        for (fix in listOf(Preflight.FIX_DOWNLOAD, Preflight.FIX_REPAIR, Preflight.FIX_JAVA, Preflight.FIX_MEMORY, Preflight.FIX_MODS)) {
            assertTrue(fix, preflightFixLabel(fix).isNotBlank())
        }
        assertEquals("", preflightFixLabel(Preflight.FIX_NONE))
        assertEquals("", preflightFixLabel("nowhere"))
        assertNotEquals(preflightLevelLabel(Preflight.ERROR), preflightLevelLabel(Preflight.WARN))
        assertNotEquals(preflightLevelLabel(Preflight.WARN), preflightLevelLabel(Preflight.OK))
    }

    // ------------------------------------------------------------ 修复文案

    private val actionIds = listOf(
        CrashActions.DISABLE_MODS, CrashActions.OPEN_MODS, CrashActions.BUMP_MEMORY, CrashActions.TRIM_MEMORY,
        CrashActions.NEED_JAVA, CrashActions.REPAIR_VERSION, CrashActions.OPEN_CRASH_FILE,
        CrashActions.OPEN_GPU_HINT, CrashActions.RESET_JVM_ARGS,
    )

    @Test
    fun everyCrashActionHasAButtonLabel() {
        for (id in actionIds) {
            val label = crashActionLabel(CrashAction(id, major = 17, memoryMb = 4096))
            assertTrue(id, label.isNotBlank())
            assertNotEquals(id, label)
        }
        // 重复 Mod 与嫌疑 Mod 是两句不同的话；下载 Java 要带大版本
        assertNotEquals(
            crashActionLabel(CrashAction(CrashActions.DISABLE_MODS, codes = listOf("mod_dup"))),
            crashActionLabel(CrashAction(CrashActions.DISABLE_MODS, codes = listOf("mixin"))),
        )
        assertTrue(crashActionLabel(CrashAction(CrashActions.NEED_JAVA, major = 11)).contains("11"))
        assertFalse(crashActionLabel(CrashAction(CrashActions.NEED_JAVA)).contains("0"))
        assertEquals("teleport", crashActionLabel(CrashAction("teleport")))
    }

    @Test
    fun resultTextsFollowTheDesktopWording() {
        val disabled = crashResultText(CrashActionResult(true, CrashActions.R_DISABLED, count = 2))
        assertTrue(disabled.contains("2"))
        val partly = crashResultText(CrashActionResult(true, CrashActions.R_DISABLED, count = 1, detail = "ghost.jar: 模组不存在"))
        assertTrue(partly.contains("ghost.jar"))
        assertTrue(crashResultText(CrashActionResult(false, CrashActions.R_DISABLE_FAILED, detail = "x")).contains("x"))
        assertTrue(crashResultText(CrashActionResult(true, CrashActions.R_JVM_CLEARED)).isNotBlank())
        assertTrue(crashResultText(CrashActionResult(true, CrashActions.R_GPU_HINT)).isNotBlank())
        assertTrue(crashResultText(CrashActionResult(true, CrashActions.R_GOTO, count = 6144, route = CrashActions.ROUTE_MEMORY)).contains("6144"))
        for (route in listOf(CrashActions.ROUTE_REPAIR, CrashActions.ROUTE_JAVA, CrashActions.ROUTE_MODS)) {
            assertTrue(route, crashResultText(CrashActionResult(true, CrashActions.R_GOTO, route = route)).isNotBlank())
        }
        assertTrue(crashResultText(CrashActionResult(false, CrashActions.R_UNKNOWN, detail = "teleport")).contains("teleport"))
    }

    // ------------------------------------------------------------ 英文

    @Test
    fun everyLabelHasAnEnglishVersion() {
        I18n.loadFromDir(localesDir())
        I18n.setLanguage("en")
        val cjk = Regex("[\\u3400-\\u9fff\\u3000-\\u303f\\uff00-\\uffef]")
        for (code in preflightCodes) {
            assertFalse("preflightTitle($code) 英文界面漏中文", cjk.containsMatchIn(preflightTitle(code)))
            val detail = preflightDetail(PreflightItem(Preflight.WARN, code, "x", 1))
            assertFalse("preflightDetail($code) 英文界面漏中文: $detail", cjk.containsMatchIn(detail))
        }
        for (id in actionIds) {
            val label = crashActionLabel(CrashAction(id, major = 17, memoryMb = 4096, codes = listOf("mod_dup")))
            assertFalse("crashActionLabel($id) 英文界面漏中文: $label", cjk.containsMatchIn(label))
        }
        for (fix in listOf(Preflight.FIX_DOWNLOAD, Preflight.FIX_REPAIR, Preflight.FIX_JAVA, Preflight.FIX_MEMORY, Preflight.FIX_MODS)) {
            assertFalse(fix, cjk.containsMatchIn(preflightFixLabel(fix)))
        }
        for (code in listOf(CrashActions.R_DISABLED, CrashActions.R_DISABLE_FAILED, CrashActions.R_JVM_CLEARED, CrashActions.R_GPU_HINT, CrashActions.R_UNKNOWN)) {
            val text = crashResultText(CrashActionResult(true, code, count = 1, detail = "d"))
            assertFalse("crashResultText($code) 英文界面漏中文: $text", cjk.containsMatchIn(text))
        }
        for (route in listOf(CrashActions.ROUTE_MEMORY, CrashActions.ROUTE_REPAIR, CrashActions.ROUTE_JAVA, CrashActions.ROUTE_MODS)) {
            val text = crashResultText(CrashActionResult(true, CrashActions.R_GOTO, count = 1, route = route))
            assertFalse("crashResultText(goto/$route) 英文界面漏中文: $text", cjk.containsMatchIn(text))
        }
    }
}
