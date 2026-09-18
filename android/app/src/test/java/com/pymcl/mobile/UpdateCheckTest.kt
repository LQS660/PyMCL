package com.pymcl.mobile

import com.pymcl.mobile.data.UpdateCheck
import com.pymcl.mobile.data.UpdateInfo
import com.pymcl.mobile.data.UpdateKind
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.util.concurrent.atomic.AtomicInteger

/**
 * 启动器自更新检查（对齐 `check_update` → `mclauncher/updater.py`）。
 * 版本比较的边界照 `_parse` / `newer` 的口径逐条钉死；网络这一层用假的 fetch 喂，
 * 另有一条真连本机一个没人听的端口，证明默认那条 OkHttp 路径失败也不抛。
 */
class UpdateCheckTest {

    private val sha = "a".repeat(64)

    @Before
    fun fresh() {
        UpdateCheck.reset()
    }

    @After
    fun clean() {
        UpdateCheck.reset()
    }

    // ---------------------------------------------------------------- 版本比较

    @Test
    fun parseVersionMatchesDesktopParse() {
        assertEquals(listOf(3, 2, 0, 1), UpdateCheck.parseVersion("3.2.0-beta1"))
        assertEquals(listOf(2, 0, 0), UpdateCheck.parseVersion("v2"))
        assertEquals(listOf(0, 0, 0), UpdateCheck.parseVersion(""))
        assertEquals(listOf(0, 0, 0), UpdateCheck.parseVersion(null))
        // 最多比 4 段
        assertEquals(listOf(1, 2, 3, 4), UpdateCheck.parseVersion("1.2.3.4.5"))
        // 空段 / 纯字母段按 0
        assertEquals(listOf(1, 0, 2), UpdateCheck.parseVersion("1..2"))
        assertEquals(listOf(1, 0, 0), UpdateCheck.parseVersion("1.beta"))
        // 只取数字：rc2 → 2
        assertEquals(listOf(1, 0, 1, 2), UpdateCheck.parseVersion("1.0.1-rc2"))
    }

    @Test
    fun compareVersionsUsesPythonTupleSemantics() {
        assertEquals(0, UpdateCheck.compareVersions("3.2.0", "3.2.0"))
        assertEquals(0, UpdateCheck.compareVersions("3.2", "3.2.0"))
        // 数值比较，不是字典序
        assertTrue(UpdateCheck.compareVersions("3.10.0", "3.9.9") > 0)
        // 前缀相同则更长的更大——桌面元组比较的口径，所以 3.2.0-beta1 算比 3.2.0 新
        assertTrue(UpdateCheck.compareVersions("3.2.0.1", "3.2.0") > 0)
        assertTrue(UpdateCheck.compareVersions("3.2.0-beta1", "3.2.0") > 0)
        assertTrue(UpdateCheck.compareVersions("1.0.0", "1.0.1") < 0)
    }

    @Test
    fun newerIsStrictlyGreater() {
        assertTrue(UpdateCheck.newer("1.0.2", "1.0.1"))
        assertTrue(UpdateCheck.newer("2", "1.9.9"))
        assertFalse(UpdateCheck.newer("1.0.1", "1.0.1"))
        assertFalse(UpdateCheck.newer("0.9", "1.0.1"))
        assertFalse(UpdateCheck.newer("", "1.0.1"))
        assertFalse(UpdateCheck.newer(null, "1.0.1"))
    }

    @Test
    fun validSha256IsExactly64Hex() {
        assertTrue(UpdateCheck.validSha256(sha))
        assertTrue(UpdateCheck.validSha256("  ${"A".repeat(64)}  "))
        assertFalse(UpdateCheck.validSha256("a".repeat(63)))
        assertFalse(UpdateCheck.validSha256("a".repeat(65)))
        assertFalse(UpdateCheck.validSha256("g".repeat(64)))
        assertFalse(UpdateCheck.validSha256(""))
        assertFalse(UpdateCheck.validSha256(null))
    }

    // ---------------------------------------------------------------- 清单判定

    @Test
    fun sameOrOlderRemoteIsUpToDate() {
        val same = UpdateCheck.evaluate(JSONObject("""{"version":"1.0.1"}"""), "1.0.1")
        assertTrue(same.ok)
        assertFalse(same.hasUpdate)
        assertEquals(UpdateKind.UP_TO_DATE, same.kind)
        assertEquals("已是最新版本", same.message)
        assertEquals("1.0.1", same.latest)
        assertEquals("1.0.1", same.current)

        val older = UpdateCheck.evaluate(JSONObject("""{"version":"0.9.0","sha256":"$sha"}"""), "1.0.1")
        assertEquals(UpdateKind.UP_TO_DATE, older.kind)
        assertFalse(older.hasUpdate)
        assertEquals("0.9.0", older.latest)
    }

    @Test
    fun signedNewerManifestIsAnUpdate() {
        val json = JSONObject()
            .put("version", "1.2.0")
            .put("sha256", "B".repeat(64))
            .put("url", "https://pymcl.dev/PyMCL-1.2.0.apk")
            .put("notes", "fixes")
        val info = UpdateCheck.evaluate(json, "1.0.1")
        assertTrue(info.ok)
        assertTrue(info.hasUpdate)
        assertEquals(UpdateKind.UPDATE, info.kind)
        assertEquals("发现 1.2.0", info.message)
        assertEquals("1.2.0", info.latest)
        assertEquals("b".repeat(64), info.sha256)
        assertEquals("https://pymcl.dev/PyMCL-1.2.0.apk", info.url)
        assertEquals("fixes", info.notes)
        assertEquals("", info.error)
    }

    @Test
    fun newerManifestWithoutValidSha256IsRefused() {
        for (manifest in listOf(
            """{"version":"1.2.0"}""",
            """{"version":"1.2.0","sha256":"deadbeef"}""",
            """{"version":"1.2.0","sha256":""}""",
        )) {
            val info = UpdateCheck.evaluate(JSONObject(manifest), "1.0.1")
            assertFalse(manifest, info.ok)
            assertFalse(manifest, info.hasUpdate)
            assertEquals(manifest, UpdateKind.UNSIGNED, info.kind)
            assertEquals("更新清单缺少有效 SHA-256，已拒绝自动更新", info.message)
            assertEquals("1.2.0", info.latest)
        }
    }

    @Test
    fun evaluateAcceptsAlternateManifestKeys() {
        val json = JSONObject()
            .put("latest", "1.2.0")
            .put("sha256", sha)
            .put("download", "https://x/y.apk")
            .put("changelog", "log")
        val info = UpdateCheck.evaluate(json, "1.0.1")
        assertEquals(UpdateKind.UPDATE, info.kind)
        assertEquals("1.2.0", info.latest)
        assertEquals("https://x/y.apk", info.url)
        assertEquals("log", info.notes)
        // `version` 优先于 `latest`
        val both = UpdateCheck.evaluate(JSONObject("""{"version":"1.3.0","latest":"1.2.0","sha256":"$sha"}"""), "1.0.1")
        assertEquals("1.3.0", both.latest)
    }

    @Test
    fun emptyOrMissingManifestCountsAsUpToDate() {
        for (info in listOf(UpdateCheck.evaluate(JSONObject(), "1.0.1"), UpdateCheck.evaluate(null, "1.0.1"))) {
            assertTrue(info.ok)
            assertFalse(info.hasUpdate)
            assertEquals(UpdateKind.UP_TO_DATE, info.kind)
            assertEquals("1.0.1", info.latest)
        }
    }

    // ---------------------------------------------------------------- 网络失败不崩

    @Test
    fun fetchFailureBecomesFailedInfoInsteadOfThrowing() {
        val info = UpdateCheck.check("https://example.invalid/update.json", "1.0.1") { throw IOException("boom") }
        assertFalse(info.ok)
        assertFalse(info.hasUpdate)
        assertEquals(UpdateKind.FAILED, info.kind)
        assertEquals("boom", info.error)
        assertEquals("检查更新失败: boom", info.message)
        assertEquals("1.0.1", info.latest)
        assertSame(info, UpdateCheck.last)
        assertTrue(UpdateCheck.lastCheckedAt > 0L)
    }

    @Test
    fun malformedBodyBecomesFailedInfo() {
        val info = UpdateCheck.check("https://example.invalid/update.json", "1.0.1") { "not json at all" }
        assertEquals(UpdateKind.FAILED, info.kind)
        assertTrue(info.error.isNotBlank())
        // 异常没带文案时退回异常类名，不让界面上出现「检查更新失败: null」
        val blank = UpdateCheck.check("https://example.invalid/update.json", "1.0.1") { throw IllegalStateException() }
        assertEquals("IllegalStateException", blank.error)
        assertEquals("检查更新失败: IllegalStateException", blank.message)
    }

    /** 默认的 OkHttp 路径：连本机一个没人听的端口，拒绝连接也只是一条 FAILED。 */
    @Test
    fun realHttpFailureIsSwallowedToo() {
        val info = UpdateCheck.check("http://127.0.0.1:9/update.json", "1.0.1")
        assertEquals(UpdateKind.FAILED, info.kind)
        assertTrue(info.error.isNotBlank())
        assertFalse(info.hasUpdate)
    }

    // ---------------------------------------------------------------- 监听与启动那一次

    @Test
    fun listenersGetEveryResultUntilRemoved() {
        val seen = ArrayList<UpdateInfo>()
        val listener: (UpdateInfo) -> Unit = { seen.add(it) }
        UpdateCheck.addListener(listener)
        // 一个会炸的监听者不能拖死别人
        UpdateCheck.addListener { throw IllegalStateException("listener bug") }
        val first = UpdateCheck.check("u", "1.0.1") { """{"version":"1.2.0","sha256":"$sha"}""" }
        assertEquals(listOf(first), seen)
        UpdateCheck.removeListener(listener)
        UpdateCheck.check("u", "1.0.1") { throw IOException("x") }
        assertEquals(1, seen.size)
    }

    @Test
    fun startupCheckRespectsSwitchAndRunsOnlyOnce() {
        val calls = AtomicInteger()
        val fetch: (String) -> String = { calls.incrementAndGet(); """{"version":"1.2.0","sha256":"$sha"}""" }

        assertNull(UpdateCheck.checkOnStartup(enabled = false, url = "u", current = "1.0.1", fetch = fetch))
        assertEquals(0, calls.get())
        assertNull(UpdateCheck.last)

        val first = UpdateCheck.checkOnStartup(enabled = true, url = "u", current = "1.0.1", fetch = fetch)
        assertNotNull(first)
        assertEquals(UpdateKind.UPDATE, first!!.kind)
        assertEquals(1, calls.get())

        // 同一进程再叫一次：直接给上次结果，不再联网
        val again = UpdateCheck.checkOnStartup(enabled = true, url = "u", current = "1.0.1", fetch = fetch)
        assertSame(first, again)
        assertEquals(1, calls.get())

        // 手动检查不受「只查一次」限制
        UpdateCheck.check("u", "1.0.1", fetch)
        assertEquals(2, calls.get())

        UpdateCheck.reset()
        assertNull(UpdateCheck.last)
        UpdateCheck.checkOnStartup(enabled = true, url = "u", current = "1.0.1", fetch = fetch)
        assertEquals(3, calls.get())
    }

    @Test
    fun kindIsDerivedFromFieldsInPriorityOrder() {
        assertEquals(UpdateKind.FAILED, UpdateInfo(false, "1", "1", false, "m", error = "e").kind)
        assertEquals(UpdateKind.UPDATE, UpdateInfo(true, "1", "2", true, "m").kind)
        assertEquals(UpdateKind.UNSIGNED, UpdateInfo(false, "1", "2", false, "m").kind)
        assertEquals(UpdateKind.UP_TO_DATE, UpdateInfo(true, "1", "1", false, "m").kind)
    }
}
