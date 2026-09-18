package com.pymcl.mobile

import com.pymcl.mobile.data.InstanceStore
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.ModpackInstall
import com.pymcl.mobile.data.PackFormat
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 实例仓储，外加「整合包导入」这条链在本仓的接线。
 *
 * 清单解析与安装编排本身归 [ModpackInstallTest]（随 `ModpackIndex`/`ModpackInstall`
 * 一起从基线树搬过来的），这里只钉住我这一侧真正依赖的那几个出口。
 */
class ModpackDomainTest {
    private lateinit var dir: File

    @Before
    fun setUp() {
        dir = kotlin.io.path.createTempDirectory("pymcl-instances").toFile()
    }

    @After
    fun tearDown() {
        dir.deleteRecursively()
    }

    private fun zip(name: String, entries: Map<String, String>): File {
        val f = File(dir, name)
        ZipOutputStream(f.outputStream()).use { out ->
            entries.forEach { (path, body) ->
                out.putNextEntry(ZipEntry(path))
                out.write(body.toByteArray())
                out.closeEntry()
            }
        }
        return f
    }

    private val mrpackIndex = """
        {"name":"All The Mods 9","versionId":"1.0.3",
         "dependencies":{"minecraft":"1.20.1","fabric-loader":"0.16.0"},
         "files":[{"path":"mods/sodium.jar","downloads":["https://cdn/sodium.jar"],
                   "hashes":{"sha1":"abc"},"fileSize":100}]}
    """.trimIndent()

    // ---- 整合包入口 ------------------------------------------------------

    @Test
    fun probeRecognisesMrpack() {
        val info = ModpackIndex.probe(zip("a.mrpack", mapOf("modrinth.index.json" to mrpackIndex)))
        assertNotNull(info)
        assertEquals(PackFormat.MRPACK, info!!.format)
        assertEquals("1.20.1", info.mcVersion)
        assertEquals(1, info.files.size)
    }

    @Test
    fun probeReturnsNullForAnUnknownArchive() {
        assertNull(ModpackIndex.probe(zip("b.zip", mapOf("readme.txt" to "x"))))
    }

    @Test
    fun probeReturnsNullForACorruptFile() {
        val bad = File(dir, "c.mrpack").also { it.writeText("not a zip") }
        assertNull(ModpackIndex.probe(bad))
    }

    @Test
    fun planTurnsTheManifestIntoDownloadSteps() {
        val info = ModpackIndex.probe(zip("d.mrpack", mapOf("modrinth.index.json" to mrpackIndex)))!!
        val plan = ModpackInstall.plan(info)
        assertEquals(1, plan.downloads.size)
        assertEquals("mods/sodium.jar", plan.downloads.single().relPath)
        assertEquals("abc", plan.downloads.single().sha1)
    }

    @Test
    fun planPicksUpOverridesFromTheArchive() {
        val pack = zip(
            "e.mrpack",
            mapOf(
                "modrinth.index.json" to mrpackIndex,
                "overrides/config/a.toml" to "a",
                "other/skip.txt" to "s",
            ),
        )
        val info = ModpackIndex.probe(pack)!!
        val names = com.pymcl.mobile.data.FileKinds.entryNames(pack).orEmpty()
        val plan = ModpackInstall.plan(info, names)
        assertEquals(listOf("config/a.toml"), plan.extracts.map { it.relPath })
    }

    @Test
    fun safeRelPathRejectsEscapes() {
        assertNull(ModpackInstall.safeRelPath("../evil.jar"))
        assertNull(ModpackInstall.safeRelPath("   "))
        assertEquals("mods/a.jar", ModpackInstall.safeRelPath("mods\\a.jar"))
    }

    // ---- 实例仓储 --------------------------------------------------------

    @Test
    fun instanceStoreCreatesStandardLayout() {
        val root = File(dir, "instances")
        val info = InstanceStore.createIn(root, "我的实例")
        assertEquals("我的实例", info.name)
        listOf("mods", "saves", "versions", "libraries", "backups").forEach {
            assertTrue(it, File(root, "我的实例/$it").isDirectory)
        }
    }

    @Test
    fun instanceStoreDeduplicatesNames() {
        val root = File(dir, "instances2")
        assertEquals("游戏", InstanceStore.createIn(root, "游戏").name)
        assertEquals("游戏-2", InstanceStore.createIn(root, "游戏").name)
        assertEquals("游戏-3", InstanceStore.createIn(root, "游戏").name)
    }

    @Test
    fun instanceStoreListsOnlyMarkedFolders() {
        val root = File(dir, "instances3")
        InstanceStore.createIn(root, "真的")
        File(root, "假的").mkdirs()
        assertEquals(listOf("真的"), InstanceStore.listIn(root).map { it.name })
    }

    @Test
    fun installedVersionsNeedsMatchingJson() {
        val inst = File(dir, "inst").also { it.mkdirs() }
        File(inst, "versions/1.20.1").mkdirs()
        File(inst, "versions/1.20.1/1.20.1.json").writeText("{}")
        File(inst, "versions/半个").mkdirs()
        assertEquals(listOf("1.20.1"), InstanceStore.installedVersionsIn(inst))
    }

    @Test
    fun configDefaultsAreFilledIn() {
        val cfg = InstanceStore.withDefaults(JSONObject())
        assertEquals(2048, cfg.getInt("memory_mb"))
        assertEquals("Player", cfg.getString("username"))
        assertEquals("bmclapi", cfg.getString("download_source"))
        assertFalse(cfg.getBoolean("show_hidden_versions"))
    }

    @Test
    fun configDefaultsDoNotClobberStoredValues() {
        val cfg = InstanceStore.withDefaults(JSONObject().put("memory_mb", 8192))
        assertEquals(8192, cfg.getInt("memory_mb"))
    }
}
