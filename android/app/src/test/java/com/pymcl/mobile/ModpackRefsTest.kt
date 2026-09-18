package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogKeys
import com.pymcl.mobile.data.CursePackRef
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.ModpackInstall
import com.pymcl.mobile.data.ModpackRefs
import com.pymcl.mobile.data.TextFetcher
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * CurseForge 整合包的 `refs` 那一批。
 *
 * 修之前：`ModpackInstall.withResolved` 在生产代码里一处调用都没有，所以导一个
 * CF 整合包会把 overrides 铺开、报成功，**但 refs 里的 mod 一个都不装**——而
 * CF 整合包的 mod 几乎全在 refs 里。这组测就是钉住这件事不再发生。
 */
class ModpackRefsTest {
    private lateinit var dir: File

    private val keys = CatalogKeys("test-key")

    @Before
    fun setUp() {
        dir = kotlin.io.path.createTempDirectory("pymcl-refs").toFile()
    }

    @After
    fun tearDown() {
        dir.deleteRecursively()
    }

    private fun fileResponse(id: Long, name: String) = """
        {"data":{"id":$id,"fileName":"$name","displayName":"$name",
                 "downloadUrl":"https://cdn/$name","fileLength":1234,"releaseType":1,
                 "gameVersions":["1.20.1","Forge"],
                 "hashes":[{"value":"abc123","algo":1}]}}
    """.trimIndent()

    private val blockedResponse = """
        {"data":{"id":9,"fileName":"secret.jar","downloadUrl":null,"releaseType":1,"gameVersions":[]}}
    """.trimIndent()

    /** CurseForge 整合包：只有 manifest 与 overrides，mod 全在 refs 里。 */
    private fun cursePack(): File {
        val manifest = """
            {"name":"RLCraft","version":"2.9.3","overrides":"overrides",
             "minecraft":{"version":"1.12.2","modLoaders":[{"id":"forge-14.23.5.2860","primary":true}]},
             "files":[{"projectID":238222,"fileID":3222222,"required":true},
                      {"projectID":238223,"fileID":3222223,"required":true}]}
        """.trimIndent()
        val f = File(dir, "pack.zip")
        ZipOutputStream(f.outputStream()).use { zip ->
            mapOf("manifest.json" to manifest, "overrides/config/a.toml" to "a").forEach { (name, body) ->
                zip.putNextEntry(ZipEntry(name))
                zip.write(body.toByteArray())
                zip.closeEntry()
            }
        }
        return f
    }

    private fun fetcherFor(vararg bodies: Pair<Long, String>): TextFetcher {
        val byFile = bodies.toMap()
        return TextFetcher { urls, _ ->
            val fileId = urls.first().substringAfterLast('/').toLongOrNull()
            byFile[fileId]
        }
    }

    // ---- 修前的形状：证明这个 bug 真的存在过 ------------------------------

    @Test
    fun withoutResolvingRefsThePlanInstallsNothing() {
        val info = ModpackIndex.probe(cursePack())!!
        assertEquals(2, info.refs.size)
        assertTrue(info.files.isEmpty())
        val plan = ModpackInstall.plan(info)
        // 这正是修之前的样子：零个下载步骤，却什么都不报
        assertEquals(0, plan.downloads.size)
    }

    // ---- 修后 ------------------------------------------------------------

    @Test
    fun resolvingRefsTurnsThemIntoRealDownloads() {
        val info = ModpackIndex.probe(cursePack())!!
        val report = ModpackRefs.resolve(
            info.refs, keys,
            fetcherFor(3222222L to fileResponse(3222222, "a.jar"), 3222223L to fileResponse(3222223, "b.jar")),
        )
        assertEquals(2, report.resolved.size)
        assertTrue(report.failures.isEmpty())
        val plan = ModpackRefs.merge(ModpackInstall.plan(info), report)
        assertEquals(2, plan.downloads.size)
        assertEquals(setOf("mods/a.jar", "mods/b.jar"), plan.downloads.map { it.relPath }.toSet())
    }

    @Test
    fun resolvedFilesKeepTheirHashAndSize() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 3222222)), keys,
            fetcherFor(3222222L to fileResponse(3222222, "a.jar")),
        )
        assertEquals("abc123", report.resolved.single().sha1)
        assertEquals(1234L, report.resolved.single().size)
        assertEquals("https://cdn/a.jar", report.resolved.single().urls.single())
    }

    @Test
    fun refsAlwaysLandUnderMods() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 3222222)), keys,
            fetcherFor(3222222L to fileResponse(3222222, "deep/name.jar")),
        )
        assertEquals("mods/name.jar", report.resolved.single().path)
    }

    // ---- 不能静默 --------------------------------------------------------

    @Test
    fun allFailedIsFlaggedSoTheInstallCanRefuseToClaimSuccess() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 1), CursePackRef(2, 2)), keys,
            TextFetcher { _, _ -> null },
        )
        assertTrue(report.allFailed)
        assertEquals(2, report.failures.size)
        assertEquals(2, report.total)
    }

    @Test
    fun partialSuccessIsNotFlaggedAsTotalFailure() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 3222222), CursePackRef(2, 999)), keys,
            fetcherFor(3222222L to fileResponse(3222222, "a.jar")),
        )
        assertFalse(report.allFailed)
        assertEquals(1, report.resolved.size)
        assertEquals(1, report.failures.size)
    }

    @Test
    fun aBlockedDownloadSaysSoInsteadOfLookingLikeANetworkError() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 9)), keys,
            TextFetcher { _, _ -> blockedResponse },
        )
        assertEquals(ModpackRefs.BLOCKED_MESSAGE, report.failures.single().reason)
    }

    @Test
    fun withoutAnApiKeyTheWholeBatchFailsWithOneClearReason() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 1), CursePackRef(2, 2)), CatalogKeys(),
            TextFetcher { _, _ -> throw AssertionError("不该发请求") },
        )
        assertTrue(report.allFailed)
        assertTrue(report.failures.all { it.reason.contains("API key") })
    }

    @Test
    fun garbageResponseIsAFailureNotACrash() {
        val report = ModpackRefs.resolve(
            listOf(CursePackRef(1, 1)), keys,
            TextFetcher { _, _ -> "<html>502</html>" },
        )
        assertEquals(1, report.failures.size)
    }

    @Test
    fun failuresEndUpOnTheInstallReceipt() {
        val info = ModpackIndex.probe(cursePack())!!
        val report = ModpackRefs.resolve(
            info.refs, keys,
            fetcherFor(3222222L to fileResponse(3222222, "a.jar")),
        )
        val plan = ModpackRefs.merge(ModpackInstall.plan(info), report)
        assertEquals(1, plan.skipped.size)
        assertTrue(plan.skipped.single().path.contains("238223"))
    }

    @Test
    fun anEmptyRefListIsNotAnError() {
        val report = ModpackRefs.resolve(emptyList(), CatalogKeys(), TextFetcher { _, _ -> null })
        assertEquals(0, report.total)
        assertFalse(report.allFailed)
        assertTrue(ModpackRefs.describe(report).contains("没有 CurseForge 引用"))
    }

    // ---- 细节 ------------------------------------------------------------

    @Test
    fun theMirrorIsTriedBeforeTheOfficialApi() {
        val urls = ModpackRefs.fileUrls(238222, 3222222)
        assertEquals(2, urls.size)
        assertTrue(urls[0].contains("mcimirror.top"))
        assertTrue(urls[1].startsWith("https://api.curseforge.com/"))
        assertTrue(urls.all { it.endsWith("/mods/238222/files/3222222") })
    }

    @Test
    fun parseSingleReadsTheWrappedObject() {
        val file = ModpackRefs.parseSingle(fileResponse(1, "x.jar"))
        assertEquals("x.jar", file!!.path)
    }

    @Test
    fun parseSingleReturnsNullOnJunk() {
        assertNull(ModpackRefs.parseSingle("not json"))
        assertNull(ModpackRefs.parseSingle("{}"))
    }

    @Test
    fun blockedDetectionOnlyFiresOnAnExplicitNull() {
        assertTrue(ModpackRefs.isBlocked(blockedResponse))
        assertFalse(ModpackRefs.isBlocked(fileResponse(1, "a.jar")))
        assertFalse(ModpackRefs.isBlocked("{}"))
    }

    @Test
    fun describeTellsTheUserWhatHappened() {
        val ok = ModpackRefs.resolve(
            listOf(CursePackRef(1, 3222222)), keys,
            fetcherFor(3222222L to fileResponse(3222222, "a.jar")),
        )
        assertTrue(ModpackRefs.describe(ok).contains("全部解到地址"))
        val bad = ModpackRefs.resolve(listOf(CursePackRef(1, 1)), keys, TextFetcher { _, _ -> null })
        assertTrue(ModpackRefs.describe(bad).contains("失败 1 个"))
    }
}
