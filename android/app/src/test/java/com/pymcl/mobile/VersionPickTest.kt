package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogFiles
import com.pymcl.mobile.data.CatalogKeys
import com.pymcl.mobile.data.CatalogSource
import com.pymcl.mobile.data.CatalogVersion
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.PackDownloader
import com.pymcl.mobile.data.PackFile
import com.pymcl.mobile.data.PickFailure
import com.pymcl.mobile.data.PickResult
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.data.VersionPick
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 「搜到一个项目 → 挑出具体文件 → 拿到下载地址」这一段的单测。
 *
 * 一次网都不联：解析收的是 JSON 文本，拉取走注入的 [TextFetcher]，
 * 下载走注入的 [PackDownloader]。
 */
class VersionPickTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun ver(
        id: String,
        channel: String = "release",
        games: List<String> = listOf("1.20.1"),
        loaders: List<String> = listOf("fabric"),
        published: String = "2024-01-01T00:00:00Z",
        withFile: Boolean = true,
    ) = CatalogVersion(
        id = id,
        versionNumber = id,
        channel = channel,
        gameVersions = games,
        loaders = loaders,
        files = if (withFile) listOf(PackFile("$id.jar", listOf("https://cdn/$id.jar"), sha1 = "h$id")) else emptyList(),
        published = published,
    )

    private fun picked(r: PickResult): PickResult.Picked {
        assertTrue("期望挑中，实际是 $r", r is PickResult.Picked)
        return r as PickResult.Picked
    }

    private fun failed(r: PickResult): PickResult.Failed {
        assertTrue("期望挑不中，实际是 $r", r is PickResult.Failed)
        return r as PickResult.Failed
    }

    // ---------- 规则 1：版本匹配 ----------

    @Test
    fun picksTheVersionThatMatchesTheGameVersion() {
        val out = picked(
            VersionPick.pick(
                listOf(ver("old", games = listOf("1.19.4")), ver("right", games = listOf("1.20.1"))),
                mcVersion = "1.20.1",
                loader = "fabric",
            ),
        )
        assertEquals("right", out.version.id)
        assertEquals("https://cdn/right.jar", out.file.urls.first())
        assertEquals("hright", out.file.sha1)
    }

    // ---------- 规则 2：加载器匹配 ----------

    @Test
    fun picksTheVersionThatMatchesTheLoader() {
        val out = picked(
            VersionPick.pick(
                listOf(ver("forge-one", loaders = listOf("forge")), ver("fabric-one", loaders = listOf("fabric"))),
                mcVersion = "1.20.1",
                loader = "fabric",
            ),
        )
        assertEquals("fabric-one", out.version.id)
    }

    @Test
    fun loaderNamesAreNormalisedBeforeComparing() {
        // 各家叫法不一样：mrpack 写 fabric-loader，CF 写 Fabric
        assertEquals("fabric", VersionPick.normalizeLoader("fabric-loader"))
        assertEquals("fabric", VersionPick.normalizeLoader("Fabric"))
        assertEquals("quilt", VersionPick.normalizeLoader("quilt-loader"))
        assertEquals("neoforge", VersionPick.normalizeLoader("NeoForge"))
        assertEquals("forge", VersionPick.normalizeLoader("Forge"))
        assertEquals("", VersionPick.normalizeLoader("   "))

        val out = picked(VersionPick.pick(listOf(ver("v", loaders = listOf("fabric"))), "1.20.1", "fabric-loader"))
        assertEquals("v", out.version.id)
    }

    // ---------- 规则 3：release 优于 beta ----------

    @Test
    fun releaseBeatsBetaEvenWhenBetaIsNewer() {
        val out = picked(
            VersionPick.pick(
                listOf(
                    ver("beta", channel = "beta", published = "2025-06-01T00:00:00Z"),
                    ver("stable", channel = "release", published = "2024-01-01T00:00:00Z"),
                ),
                mcVersion = "1.20.1",
                loader = "fabric",
            ),
        )
        assertEquals("稳定版应该赢过更新的 beta", "stable", out.version.id)
        assertTrue(VersionPick.channelRank("release") < VersionPick.channelRank("beta"))
        assertTrue(VersionPick.channelRank("beta") < VersionPick.channelRank("alpha"))
    }

    // ---------- 规则 4：同条件取最新 ----------

    @Test
    fun newestWinsAmongEqualChannels() {
        val out = picked(
            VersionPick.pick(
                listOf(
                    ver("older", published = "2024-01-01T00:00:00Z"),
                    ver("newest", published = "2024-09-09T00:00:00Z"),
                    ver("middle", published = "2024-05-05T00:00:00Z"),
                ),
                mcVersion = "1.20.1",
                loader = "fabric",
            ),
        )
        assertEquals("newest", out.version.id)
    }

    // ---------- 挑不中时的原因要能上屏 ----------

    @Test
    fun missingGameVersionSaysWhichOnesExist() {
        val f = failed(
            VersionPick.pick(
                listOf(ver("a", games = listOf("1.19.4")), ver("b", games = listOf("1.20.1"))),
                mcVersion = "1.21.1",
                loader = "fabric",
            ),
        )
        assertEquals(PickFailure.NO_SUCH_GAME_VERSION, f.reason)
        assertTrue(f.message, f.message.contains("1.21.1"))
        assertTrue("要告诉用户它支持哪些，否则他不知道该往哪改", f.message.contains("1.20.1"))
    }

    @Test
    fun missingLoaderSaysWhichLoadersExist() {
        val f = failed(
            VersionPick.pick(
                listOf(ver("a", loaders = listOf("forge"))),
                mcVersion = "1.20.1",
                loader = "fabric",
                strictLoader = true,
            ),
        )
        assertEquals(PickFailure.NO_SUCH_LOADER, f.reason)
        assertTrue(f.message, f.message.contains("fabric"))
        assertTrue(f.message, f.message.contains("forge"))
    }

    @Test
    fun theTwoFailuresAreToldApart() {
        // 同一批候选，只换查询条件，得到的是两个不同的原因——这正是这条要求的意义
        val versions = listOf(ver("a", games = listOf("1.20.1"), loaders = listOf("forge")))
        assertEquals(
            PickFailure.NO_SUCH_GAME_VERSION,
            failed(VersionPick.pick(versions, "1.21.1", "forge", strictLoader = true)).reason,
        )
        assertEquals(
            PickFailure.NO_SUCH_LOADER,
            failed(VersionPick.pick(versions, "1.20.1", "fabric", strictLoader = true)).reason,
        )
    }

    @Test
    fun lenientModeStillPicksButWarns() {
        // 桌面的行为：加载器对不上也给一个，但把话说明白
        val out = picked(VersionPick.pick(listOf(ver("a", loaders = listOf("forge"))), "1.20.1", "fabric"))
        assertEquals("a", out.version.id)
        assertTrue(out.warning, out.warning.contains("fabric"))
        assertTrue(out.warning, out.warning.contains("可能不兼容"))
    }

    @Test
    fun noVersionsAndNoFilesAreDifferentFailures() {
        assertEquals(PickFailure.NO_VERSIONS, failed(VersionPick.pick(emptyList(), "1.20.1", "fabric")).reason)
        assertEquals(
            PickFailure.NO_FILE,
            failed(VersionPick.pick(listOf(ver("a", withFile = false)), "1.20.1", "fabric")).reason,
        )
    }

    // ---------- 坏响应三种 ----------

    @Test
    fun brokenApiResponsesNeverThrow() {
        for (junk in listOf("", "   ", "这不是 JSON", "{{{", "null", "{\"data\":\"oops\"}", "[1,2,3]")) {
            assertTrue("modrinth: $junk", CatalogFiles.parseModrinthVersions(junk).isEmpty())
            assertTrue("curseforge: $junk", CatalogFiles.parseCurseForgeFiles(junk).isEmpty())
        }
    }

    @Test
    fun emptyListsComeBackAsNoVersions() {
        assertTrue(CatalogFiles.parseModrinthVersions("[]").isEmpty())
        assertTrue(CatalogFiles.parseCurseForgeFiles("""{"data":[]}""").isEmpty())
        assertEquals(
            PickFailure.NO_VERSIONS,
            failed(VersionPick.pick(CatalogFiles.parseModrinthVersions("[]"), "1.20.1", "fabric")).reason,
        )
    }

    @Test
    fun missingFieldsFallBackInsteadOfCrashing() {
        // 一条什么都没有，一条只有地址
        val vs = CatalogFiles.parseModrinthVersions("""[{}, {"files":[{"url":"https://cdn/x.jar"}]}]""")
        assertEquals(2, vs.size)
        assertEquals("未声明 version_type 时按 release 算", "release", vs[0].channel)
        assertTrue(vs[0].files.isEmpty())
        assertEquals("x.jar", vs[1].files.first().path) // 没 filename 就从 URL 末段推
        assertEquals("", vs[1].files.first().sha1)

        val cf = CatalogFiles.parseCurseForgeFiles("""{"data":[{"id":1},{"id":2,"fileName":"a.jar"}]}""")
        assertEquals(2, cf.size)
        assertTrue("没有 downloadUrl 就没有可下载文件", cf.all { it.files.isEmpty() })
    }

    // ---------- 真实形状的响应 ----------

    private val modrinthJson = """
    [
      {"id":"v2","name":"Sodium 0.5.8","version_number":"mc1.20.1-0.5.8","version_type":"release",
       "game_versions":["1.20.1"],"loaders":["fabric","quilt"],"date_published":"2024-03-01T10:00:00Z",
       "files":[
         {"url":"https://cdn.modrinth.com/sources.jar","filename":"sources.jar","primary":false,"size":10},
         {"url":"https://cdn.modrinth.com/sodium.jar","filename":"sodium.jar","primary":true,"size":900,
          "hashes":{"sha1":"aa","sha512":"bb"}}
       ]},
      {"id":"v1","version_number":"mc1.19.4-0.4.10","version_type":"beta",
       "game_versions":["1.19.4"],"loaders":["fabric"],"date_published":"2023-05-01T10:00:00Z",
       "files":[{"url":"https://cdn.modrinth.com/old.jar","filename":"old.jar","primary":true}]}
    ]
    """.trimIndent()

    @Test
    fun modrinthResponseIsParsedAndPrimaryFileComesFirst() {
        val vs = CatalogFiles.parseModrinthVersions(modrinthJson)
        assertEquals(2, vs.size)
        val v2 = vs.first { it.id == "v2" }
        assertEquals("release", v2.channel)
        assertEquals(listOf("fabric", "quilt"), v2.loaders)
        assertEquals(CatalogSource.MODRINTH, v2.source)
        assertEquals("标了 primary 的要排最前", "sodium.jar", v2.files.first().path)
        assertEquals("aa", v2.files.first().sha1)
        assertEquals(900L, v2.files.first().size)

        val out = picked(VersionPick.pick(vs, "1.20.1", "fabric"))
        assertEquals("v2", out.version.id)
        assertEquals("sodium.jar", out.file.path)
    }

    private val curseForgeJson = """
    {"data":[
      {"id":4022267,"fileName":"jei.jar","displayName":"JEI 15.2","downloadUrl":"https://edge.forgecdn.net/jei.jar",
       "releaseType":1,"fileDate":"2024-04-01T00:00:00Z","fileLength":4096,
       "gameVersions":["1.20.1","Forge","Java 17"],
       "hashes":[{"value":"md5here","algo":2},{"value":"sha1here","algo":1}]},
      {"id":4022268,"fileName":"jei-beta.jar","downloadUrl":"https://edge.forgecdn.net/jei-beta.jar",
       "releaseType":2,"fileDate":"2024-08-01T00:00:00Z","gameVersions":["1.20.1","Forge"]}
    ]}
    """.trimIndent()

    @Test
    fun curseForgeResponseSplitsLoadersOutOfGameVersions() {
        val vs = CatalogFiles.parseCurseForgeFiles(curseForgeJson)
        assertEquals(2, vs.size)
        val jei = vs.first()
        assertEquals(listOf("1.20.1"), jei.gameVersions)
        assertEquals("Java 17 不该被当成 MC 版本", listOf("forge"), jei.loaders)
        assertEquals("sha1here", jei.files.first().sha1)
        assertEquals(4096L, jei.files.first().size)
        assertEquals(CatalogSource.CURSEFORGE, jei.source)

        assertTrue(CatalogFiles.looksLikeLoader("Forge"))
        assertTrue(CatalogFiles.looksLikeLoader("Java 17"))
        assertFalse(CatalogFiles.looksLikeLoader("1.20.1"))
        assertFalse(CatalogFiles.looksLikeLoader("23w31a"))

        // releaseType 1=release 2=beta，所以稳定版赢
        assertEquals("4022267", picked(VersionPick.pick(vs, "1.20.1", "forge")).version.id)
    }

    // ---------- 编排与 CurseForge 的 key ----------

    /** 按 URL 里的关键字返回预置响应，不联网。 */
    private class FakeFetcher(val answers: Map<String, String>) : TextFetcher {
        val seen = mutableListOf<List<String>>()
        var lastHeaders: Map<String, String> = emptyMap()
        override fun get(urls: List<String>, headers: Map<String, String>): String? {
            seen.add(urls)
            lastHeaders = headers
            val hit = answers.entries.firstOrNull { e -> urls.any { it.contains(e.key) } }
            return hit?.value
        }
    }

    @Test
    fun modrinthResolveFallsBackToLooserQueries() {
        // 带 loaders 的那一问返回空表，只带 game_versions 的那一问才有货
        val fetcher = object : TextFetcher {
            val calls = mutableListOf<String>()
            override fun get(urls: List<String>, headers: Map<String, String>): String? {
                val u = urls.first()
                calls.add(u)
                return if (u.contains("loaders")) "[]" else modrinthJson
            }
        }
        val out = picked(CatalogFiles.resolveModrinth("sodium", "1.20.1", "fabric", fetcher))
        assertEquals("v2", out.version.id)
        assertEquals("应该先严后松问两次", 2, fetcher.calls.size)
        assertTrue(fetcher.calls[0].contains("loaders"))
        assertFalse(fetcher.calls[1].contains("loaders"))
    }

    @Test
    fun modrinthUrlsPutTheMirrorFirst() {
        val urls = CatalogFiles.modrinthVersionUrls("sodium", "1.20.1", "fabric-loader")
        assertEquals(2, urls.size)
        assertTrue(urls[0], urls[0].startsWith(com.pymcl.mobile.data.Paths.MCIM))
        assertTrue(urls[1], urls[1].startsWith(CatalogFiles.MODRINTH_OFFICIAL))
        assertTrue("归一化之后再进 URL", urls[0].contains("fabric") && !urls[0].contains("fabric-loader"))
    }

    @Test
    fun curseForgeWithoutAKeySaysSoInsteadOfFailingQuietly() {
        val fetcher = FakeFetcher(emptyMap())
        val f = failed(CatalogFiles.resolveCurseForge(238222, "1.20.1", "forge", CatalogKeys(), fetcher))
        assertEquals(PickFailure.NEED_API_KEY, f.reason)
        assertTrue(f.message, f.message.contains("设置"))
        assertEquals("没 key 时根本不该发请求", 0, fetcher.seen.size)
    }

    @Test
    fun curseForgeWithAKeySendsItAsAHeaderNotInTheUrl() {
        val fetcher = FakeFetcher(mapOf("/files" to curseForgeJson))
        val out = picked(
            CatalogFiles.resolveCurseForge(238222, "1.20.1", "forge", CatalogKeys("user-supplied-key"), fetcher),
        )
        assertEquals("4022267", out.version.id)
        assertEquals("user-supplied-key", fetcher.lastHeaders["x-api-key"])
        assertFalse("key 不能出现在 URL 里", fetcher.seen.first().any { it.contains("user-supplied-key") })
    }

    // ---------- 先下后解 ----------

    @Test
    fun remoteModpackIsDownloadedThenProbed() {
        val index = """{"formatVersion":1,"name":"Remote","versionId":"9",
            "dependencies":{"minecraft":"1.20.1","fabric-loader":"0.15.7"},"files":[]}"""
        val prepared = tmp.newFile("source.mrpack")
        ZipOutputStream(prepared.outputStream()).use { out ->
            out.putNextEntry(ZipEntry("modrinth.index.json"))
            out.write(index.toByteArray())
            out.closeEntry()
        }
        val downloader = PackDownloader { _, dest, _, _ -> prepared.copyTo(dest, overwrite = true) }

        val dest = File(tmp.newFolder("dl"), "pack.mrpack")
        val got = ModpackIndex.probeRemote(PackFile("pack.mrpack", listOf("https://x/pack.mrpack")), dest, downloader)
        assertNotNull(got)
        assertEquals("Remote", got!!.second.name)
        assertEquals("1.20.1", got.second.mcVersion)
        assertTrue(got.first.isFile)
    }

    @Test
    fun remoteProbeIsNullWhenTheDownloadFailsOrItIsNotAPack() {
        val dest = File(tmp.newFolder("dl2"), "pack.mrpack")
        assertNull(
            "没有地址就不下",
            ModpackIndex.probeRemote(PackFile("p", emptyList()), dest, PackDownloader { _, _, _, _ -> }),
        )
        assertNull(
            "下载抛了也不能崩",
            ModpackIndex.probeRemote(
                PackFile("p", listOf("https://x/p")), dest,
                PackDownloader { _, _, _, _ -> throw RuntimeException("假装断网") },
            ),
        )
        assertNull(
            "下回来的不是整合包",
            ModpackIndex.probeRemote(
                PackFile("p", listOf("https://x/p")), dest,
                PackDownloader { _, d, _, _ -> d.parentFile?.mkdirs(); d.writeText("not a zip") },
            ),
        )
    }
}
