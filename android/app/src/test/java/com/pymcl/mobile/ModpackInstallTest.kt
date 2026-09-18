package com.pymcl.mobile

import com.pymcl.mobile.data.InstallCancelled
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.ModpackInstall
import com.pymcl.mobile.data.PackDownloader
import com.pymcl.mobile.data.PackFile
import com.pymcl.mobile.data.PackFormat
import org.junit.Assert.assertEquals
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
 * 清单解析与安装编排的单测。
 *
 * 一次网都不联：下载那一步走注入进来的替身 [PackDownloader]，它只是在目标位置
 * 写一个文件。真实网络实现在 HttpPackDownloader.kt，那一条要上设备才验得了。
 */
class ModpackInstallTest {

    @get:Rule
    val tmp = TemporaryFolder()

    /** 替身下载器：记下要过谁、往目标写点内容，永不联网。 */
    private class FakeDownloader(
        val failOn: Set<String> = emptySet(),
    ) : PackDownloader {
        val calls = mutableListOf<Pair<String, List<String>>>()

        override fun fetch(urls: List<String>, dest: File, sha1: String?, onProgress: (Long, Long) -> Unit) {
            calls.add(dest.name to urls)
            if (dest.name in failOn) throw RuntimeException("假装 404")
            dest.parentFile?.mkdirs()
            dest.writeText(urls.first())
            onProgress(1, 1)
        }
    }

    private fun zip(name: String, vararg entries: Pair<String, String>): File {
        val f = tmp.newFile(name)
        ZipOutputStream(f.outputStream()).use { out ->
            entries.forEach { (path, body) ->
                out.putNextEntry(ZipEntry(path))
                out.write(body.toByteArray())
                out.closeEntry()
            }
        }
        return f
    }

    // ---------- .mrpack 解析 ----------

    private val mrpackJson = """
    {
      "formatVersion": 1,
      "game": "minecraft",
      "versionId": "1.4.2",
      "name": "Demo Pack",
      "dependencies": { "minecraft": "1.20.1", "fabric-loader": "0.15.7" },
      "files": [
        { "path": "mods/sodium.jar",
          "hashes": { "sha1": "aaa", "sha512": "bbb" },
          "downloads": ["https://cdn.modrinth.com/sodium.jar"],
          "fileSize": 1234 },
        { "path": "mods/server-only.jar",
          "env": { "client": "unsupported", "server": "required" },
          "downloads": ["https://cdn.modrinth.com/server.jar"] },
        { "path": "../../evil.sh",
          "downloads": ["https://evil.example/evil.sh"] },
        { "path": "mods/nourl.jar", "downloads": [] }
      ]
    }
    """.trimIndent()

    @Test
    fun mrpackManifestIsParsed() {
        val info = ModpackIndex.parseMrpack(mrpackJson)
        assertNotNull(info)
        info!!
        assertEquals(PackFormat.MRPACK, info.format)
        assertEquals("Demo Pack", info.name)
        assertEquals("1.4.2", info.version)
        assertEquals("1.20.1", info.mcVersion)
        assertEquals("fabric-loader", info.loader)
        assertEquals("0.15.7", info.loaderVersion)
        assertEquals("Fabric 0.15.7", info.loaderLabel)
        assertEquals(4, info.files.size)

        val sodium = info.files.first()
        assertEquals("mods/sodium.jar", sodium.path)
        assertEquals("aaa", sodium.sha1)
        assertEquals("bbb", sodium.sha512)
        assertEquals(1234L, sodium.size)
        assertTrue(sodium.clientSupported)
        assertTrue(!info.files[1].clientSupported)
    }

    @Test
    fun mrpackWithoutLoaderIsVanilla() {
        val info = ModpackIndex.parseMrpack(
            """{"formatVersion":1,"dependencies":{"minecraft":"1.21"},"files":[]}""",
        )
        assertNotNull(info)
        assertEquals("", info!!.loader)
        assertEquals("原版（未声明加载器）", info.loaderLabel)
    }

    // ---------- CurseForge 解析 ----------

    private val cfJson = """
    {
      "minecraft": {
        "version": "1.19.2",
        "modLoaders": [
          { "id": "fabric-0.14.9", "primary": false },
          { "id": "forge-43.2.0", "primary": true }
        ]
      },
      "manifestType": "minecraftModpack",
      "name": "CF Demo",
      "version": "2.0",
      "overrides": "client-overrides",
      "files": [
        { "projectID": 238222, "fileID": 4022267, "required": true },
        { "projectID": 0, "fileID": 5, "required": true },
        { "projectID": 306612, "fileID": 4065507, "required": false }
      ]
    }
    """.trimIndent()

    @Test
    fun curseForgeManifestIsParsed() {
        val info = ModpackIndex.parseCurseForge(cfJson)
        assertNotNull(info)
        info!!
        assertEquals(PackFormat.CURSEFORGE, info.format)
        assertEquals("CF Demo", info.name)
        assertEquals("2.0", info.version)
        assertEquals("1.19.2", info.mcVersion)
        assertEquals("forge", info.loader) // primary=true 的那个说了算
        assertEquals("43.2.0", info.loaderVersion)
        assertEquals(listOf("client-overrides"), info.overridesDirs)
        assertEquals(2, info.refs.size) // projectID=0 那条是坏数据，丢掉
        assertEquals(238222L, info.refs[0].projectId)
        assertEquals(4022267L, info.refs[0].fileId)
        assertTrue(!info.refs[1].required)
    }

    @Test
    fun plainModJarManifestIsNotAModpack() {
        // 模组自己也可能带 manifest.json，但不会有 minecraft 这一段；
        // 少了这个判断，随便一个 jar 都会被当成整合包。
        assertNull(ModpackIndex.parseCurseForge("""{"name":"some mod","version":"1.0"}"""))
    }

    @Test
    fun garbageJsonIsNullNotThrown() {
        assertNull(ModpackIndex.parseMrpack("这不是 JSON"))
        assertNull(ModpackIndex.parseCurseForge("{{{"))
        assertNull(ModpackIndex.parseMrpack(""))
    }

    @Test
    fun probeFindsTheShallowestIndex() {
        val f = zip(
            "pack.mrpack",
            "modrinth.index.json" to mrpackJson,
            "overrides/config/a.txt" to "a",
        )
        val info = ModpackIndex.probe(f)
        assertNotNull(info)
        assertEquals(PackFormat.MRPACK, info!!.format)

        assertEquals("a/modrinth.index.json", ModpackIndex.memberOf(listOf("a/b/modrinth.index.json", "a/modrinth.index.json"), "modrinth.index.json"))
        assertNull(ModpackIndex.memberOf(listOf("a/b/c/d/modrinth.index.json"), "modrinth.index.json"))
    }

    @Test
    fun probeOnCorruptZipIsNullNotThrown() {
        val f = tmp.newFile("bad.mrpack")
        f.writeBytes(ByteArray(64) { 7 })
        assertNull(ModpackIndex.probe(f))
    }

    // ---------- 路径穿越 ----------

    @Test
    fun pathTraversalIsRejected() {
        assertNull(ModpackInstall.safeRelPath("../evil"))
        assertNull(ModpackInstall.safeRelPath("mods/../../evil"))
        assertNull(ModpackInstall.safeRelPath("/etc/passwd"))
        assertNull(ModpackInstall.safeRelPath("C:/Windows/x"))
        assertNull(ModpackInstall.safeRelPath("   "))
        assertEquals("mods/a.jar", ModpackInstall.safeRelPath("mods/a.jar"))
        assertEquals("mods/a.jar", ModpackInstall.safeRelPath("mods\\a.jar"))
        assertEquals("mods/a.jar", ModpackInstall.safeRelPath("./mods//a.jar"))
    }

    // ---------- 编排 ----------

    @Test
    fun planSkipsServerOnlyIllegalAndUrllessFiles() {
        val info = ModpackIndex.parseMrpack(mrpackJson)!!
        val plan = ModpackInstall.plan(info)

        assertEquals(1, plan.downloads.size)
        assertEquals("mods/sodium.jar", plan.downloads[0].relPath)
        assertEquals(3, plan.skipped.size)
        val reasons = plan.skipped.associate { it.path to it.reason }
        assertTrue(reasons["mods/server-only.jar"]!!.contains("服务端"))
        assertTrue(reasons["../../evil.sh"]!!.contains("路径非法"))
        assertTrue(reasons["mods/nourl.jar"]!!.contains("没给下载地址"))
    }

    @Test
    fun overridesAreMappedOntoTheContentRoot() {
        val info = ModpackIndex.parseMrpack(mrpackJson)!!
        val names = listOf(
            "modrinth.index.json",
            "overrides/",
            "overrides/config/sodium.json",
            "overrides/resourcepacks/x.zip",
            "client-overrides/config/ignored.json",
        )
        val plan = ModpackInstall.plan(info, names)
        assertEquals(
            listOf("config/sodium.json", "resourcepacks/x.zip"),
            plan.extracts.map { it.relPath },
        )
        // overridesDirs 按顺序只取第一个存在的，不会两份都解
        assertTrue(plan.extracts.none { it.entry.startsWith("client-overrides/") })
    }

    @Test
    fun curseForgeRefsComeOutAsUnresolved() {
        val info = ModpackIndex.parseCurseForge(cfJson)!!
        val plan = ModpackInstall.plan(info)
        assertEquals(0, plan.downloads.size)
        assertEquals(2, plan.unresolved.size)

        // 外面把地址换出来之后并回去
        val merged = ModpackInstall.withResolved(
            plan,
            listOf(PackFile("mods/jei.jar", listOf("https://edge.forgecdn.net/jei.jar"), sha1 = "ccc")),
        )
        assertEquals(1, merged.downloads.size)
        assertEquals("mods/jei.jar", merged.downloads[0].relPath)
        assertTrue(merged.unresolved.isEmpty())
    }

    // ---------- 执行 ----------

    @Test
    fun executeDownloadsExtractsAndReportsProgress() {
        val info = ModpackIndex.parseMrpack(mrpackJson)!!
        val pack = zip(
            "demo.mrpack",
            "modrinth.index.json" to mrpackJson,
            "overrides/config/sodium.json" to "{\"quality\":\"fast\"}",
        )
        val names = listOf("modrinth.index.json", "overrides/config/sodium.json")
        val plan = ModpackInstall.plan(info, names)
        val root = tmp.newFolder("content")
        val dl = FakeDownloader()
        val seen = mutableListOf<Triple<Int, Int, String>>()

        val report = ModpackInstall.execute(
            plan = plan,
            contentRoot = root,
            packZip = pack,
            downloader = dl,
            onProgress = { done, total, msg -> seen.add(Triple(done, total, msg)) },
        )

        assertEquals(1, report.downloaded)
        assertEquals(1, report.extracted)
        assertTrue(report.failed.isEmpty())
        assertEquals(3, report.skipped.size)

        assertTrue(File(root, "mods/sodium.jar").isFile)
        assertEquals("{\"quality\":\"fast\"}", File(root, "config/sodium.json").readText())
        assertTrue(File(root, "../../evil.sh").canonicalFile.let { !it.isFile })

        // 进度从 0 走到 2/2
        assertEquals(0, seen.first().first)
        assertEquals(2 to 2, seen.last().first to seen.last().second)
        assertEquals("完成", seen.last().third)
    }

    @Test
    fun oneBadFileDoesNotSinkTheWholeInstall() {
        val info = ModpackIndex.parseMrpack(
            """
            {"formatVersion":1,"dependencies":{"minecraft":"1.20.1"},"files":[
              {"path":"mods/ok.jar","downloads":["https://x/ok.jar"]},
              {"path":"mods/bad.jar","downloads":["https://x/bad.jar"]}
            ]}
            """.trimIndent(),
        )!!
        val plan = ModpackInstall.plan(info)
        val root = tmp.newFolder("content2")
        val report = ModpackInstall.execute(
            plan = plan,
            contentRoot = root,
            downloader = FakeDownloader(failOn = setOf("bad.jar")),
        )
        assertEquals(1, report.downloaded)
        assertEquals(1, report.failed.size)
        assertEquals("mods/bad.jar", report.failed[0].path)
        assertTrue(File(root, "mods/ok.jar").isFile)
    }

    @Test
    fun continueOnErrorFalseStopsAtTheFirstFailure() {
        val info = ModpackIndex.parseMrpack(
            """
            {"formatVersion":1,"dependencies":{"minecraft":"1.20.1"},"files":[
              {"path":"mods/bad.jar","downloads":["https://x/bad.jar"]},
              {"path":"mods/ok.jar","downloads":["https://x/ok.jar"]}
            ]}
            """.trimIndent(),
        )!!
        val root = tmp.newFolder("content3")
        val dl = FakeDownloader(failOn = setOf("bad.jar"))
        try {
            ModpackInstall.execute(
                plan = ModpackInstall.plan(info),
                contentRoot = root,
                downloader = dl,
                continueOnError = false,
            )
            throw AssertionError("应该抛出来才对")
        } catch (e: RuntimeException) {
            assertEquals("假装 404", e.message)
        }
        assertEquals(1, dl.calls.size) // 第二个没再试
    }

    @Test
    fun cancellationStopsBeforeTheNextStep() {
        val info = ModpackIndex.parseMrpack(
            """
            {"formatVersion":1,"dependencies":{"minecraft":"1.20.1"},"files":[
              {"path":"mods/a.jar","downloads":["https://x/a.jar"]},
              {"path":"mods/b.jar","downloads":["https://x/b.jar"]},
              {"path":"mods/c.jar","downloads":["https://x/c.jar"]}
            ]}
            """.trimIndent(),
        )!!
        val root = tmp.newFolder("content4")
        val dl = FakeDownloader()

        try {
            ModpackInstall.execute(
                plan = ModpackInstall.plan(info),
                contentRoot = root,
                downloader = dl,
                // 第一个下完就按下取消：取消是在每一步开头问的，所以第二个不该再发起
                cancelled = { dl.calls.isNotEmpty() },
            )
            throw AssertionError("取消之后应该抛 InstallCancelled")
        } catch (e: InstallCancelled) {
            assertEquals(1, dl.calls.size)
        }
        assertTrue(File(root, "mods/a.jar").isFile)
        assertTrue(!File(root, "mods/b.jar").exists())
    }

    @Test
    fun extractsAreSkippedWhenThePackItselfIsMissing() {
        val info = ModpackIndex.parseMrpack(mrpackJson)!!
        val plan = ModpackInstall.plan(info, listOf("overrides/config/a.json"))
        val root = tmp.newFolder("content5")
        val logs = mutableListOf<String>()
        val report = ModpackInstall.execute(
            plan = plan,
            contentRoot = root,
            packZip = null,
            downloader = FakeDownloader(),
            onLog = { logs.add(it) },
        )
        assertEquals(0, report.extracted)
        assertTrue(logs.any { it.contains("没给整合包本体") })
    }
}
