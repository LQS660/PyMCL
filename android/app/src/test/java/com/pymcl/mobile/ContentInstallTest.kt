package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogKeys
import com.pymcl.mobile.data.CatalogSource
import com.pymcl.mobile.data.ContentError
import com.pymcl.mobile.data.ContentInstall
import com.pymcl.mobile.data.FileKind
import com.pymcl.mobile.data.PackDownloader
import com.pymcl.mobile.data.PackFile
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.data.VersionSettings
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class ContentInstallTest {
    private lateinit var inst: File

    private val fakeDownloader = PackDownloader { urls, dest, _, _ ->
        dest.parentFile?.mkdirs()
        dest.writeText(urls.firstOrNull().orEmpty())
    }

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-content").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    private fun version(id: String, isolation: String) {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText("""{"id":"$id"}""")
        VersionSettings.save(inst, id, VersionSettings.load(inst, id).copy(isolation = isolation))
    }

    private fun worldZip(name: String): File {
        val f = File(inst, "$name.zip")
        ZipOutputStream(f.outputStream()).use { zip ->
            zip.putNextEntry(ZipEntry("$name/level.dat"))
            zip.write("lvl".toByteArray())
            zip.closeEntry()
        }
        return f
    }

    // ---- 分区到类型 ------------------------------------------------------

    @Test
    fun everyDownloadTabMapsToAKind() {
        assertEquals(FileKind.MOD, ContentInstall.kindOf("Mod"))
        assertEquals(FileKind.RESOURCEPACK, ContentInstall.kindOf("资源包"))
        assertEquals(FileKind.SHADERPACK, ContentInstall.kindOf("光影包"))
        assertEquals(FileKind.DATAPACK, ContentInstall.kindOf("数据包"))
        assertEquals(FileKind.WORLD, ContentInstall.kindOf("世界"))
        assertEquals(FileKind.MODPACK, ContentInstall.kindOf("整合包"))
    }

    @Test
    fun localTabsHaveNoKind() {
        assertNull(ContentInstall.kindOf("原版游戏"))
        assertNull(ContentInstall.kindOf("下载任务"))
    }

    @Test
    fun folderMappingMatchesTheGameLayout() {
        assertEquals("mods", ContentInstall.folderOf(FileKind.MOD))
        assertEquals("resourcepacks", ContentInstall.folderOf(FileKind.RESOURCEPACK))
        assertEquals("shaderpacks", ContentInstall.folderOf(FileKind.SHADERPACK))
        assertEquals("datapacks", ContentInstall.folderOf(FileKind.DATAPACK))
        assertEquals("saves", ContentInstall.folderOf(FileKind.WORLD))
    }

    // ---- 落点 ------------------------------------------------------------

    @Test
    fun withoutAVersionEverythingLandsInTheInstanceRoot() {
        assertEquals(File(inst, "mods"), ContentInstall.targetDir(inst, "", FileKind.MOD))
        assertEquals(File(inst, "saves"), ContentInstall.targetDir(inst, "", FileKind.WORLD))
    }

    @Test
    fun sharedPoolVersionStillLandsInTheInstanceRoot() {
        version("1.20.1", VersionSettings.NONE)
        assertEquals(File(inst, "mods"), ContentInstall.targetDir(inst, "1.20.1", FileKind.MOD))
        assertEquals(File(inst, "saves"), ContentInstall.targetDir(inst, "1.20.1", FileKind.WORLD))
    }

    @Test
    fun modIsolationMovesModsButNotSaves() {
        version("1.20.1", VersionSettings.MODS)
        assertEquals(File(inst, "versions/1.20.1/mods"), ContentInstall.targetDir(inst, "1.20.1", FileKind.MOD))
        assertEquals(File(inst, "saves"), ContentInstall.targetDir(inst, "1.20.1", FileKind.WORLD))
    }

    @Test
    fun saveIsolationMovesSavesButNotMods() {
        version("1.20.1", VersionSettings.SAVES)
        assertEquals(File(inst, "mods"), ContentInstall.targetDir(inst, "1.20.1", FileKind.MOD))
        assertEquals(File(inst, "versions/1.20.1/saves"), ContentInstall.targetDir(inst, "1.20.1", FileKind.WORLD))
    }

    @Test
    fun fullIsolationMovesEverything() {
        version("1.20.1", VersionSettings.ALL)
        assertEquals(File(inst, "versions/1.20.1/mods"), ContentInstall.targetDir(inst, "1.20.1", FileKind.MOD))
        assertEquals(File(inst, "versions/1.20.1/saves"), ContentInstall.targetDir(inst, "1.20.1", FileKind.WORLD))
        assertEquals(File(inst, "versions/1.20.1/shaderpacks"), ContentInstall.targetDir(inst, "1.20.1", FileKind.SHADERPACK))
    }

    // ---- 路径穿越 --------------------------------------------------------

    @Test
    fun resolveUnderAcceptsAPlainFileName() {
        val dir = File(inst, "mods").also { it.mkdirs() }
        assertEquals(File(dir, "sodium.jar").canonicalPath, ContentInstall.resolveUnder(dir, " sodium.jar ").canonicalPath)
    }

    @Test(expected = ContentError::class)
    fun resolveUnderRejectsAnyDirectoryPart() {
        ContentInstall.resolveUnder(File(inst, "mods").also { it.mkdirs() }, "a/b/sodium.jar")
    }

    @Test(expected = ContentError::class)
    fun resolveUnderRejectsBackslashPaths() {
        ContentInstall.resolveUnder(File(inst, "mods").also { it.mkdirs() }, "a\\b.jar")
    }

    @Test(expected = ContentError::class)
    fun resolveUnderRejectsParentEscape() {
        ContentInstall.resolveUnder(File(inst, "mods").also { it.mkdirs() }, "../evil.jar")
    }

    @Test(expected = ContentError::class)
    fun resolveUnderRejectsBlankName() {
        ContentInstall.resolveUnder(File(inst, "mods").also { it.mkdirs() }, "   ")
    }

    @Test(expected = ContentError::class)
    fun resolveUnderRejectsBareDotDot() {
        ContentInstall.resolveUnder(File(inst, "mods").also { it.mkdirs() }, "..")
    }

    @Test
    fun uniqueUnderDoesNotOverwrite() {
        val dir = File(inst, "mods").also { it.mkdirs() }
        File(dir, "sodium.jar").writeText("old")
        assertEquals("sodium-2.jar", ContentInstall.uniqueUnder(dir, "sodium.jar").name)
        File(dir, "sodium-2.jar").writeText("old2")
        assertEquals("sodium-3.jar", ContentInstall.uniqueUnder(dir, "sodium.jar").name)
        assertEquals("old", File(dir, "sodium.jar").readText())
    }

    // ---- 装 --------------------------------------------------------------

    @Test
    fun installModLandsInMods() {
        val out = ContentInstall.install(
            inst, "", FileKind.MOD,
            PackFile("sodium.jar", listOf("https://cdn/sodium.jar")),
            fakeDownloader,
        )
        assertEquals("sodium.jar", out.name)
        assertTrue(File(inst, "mods/sodium.jar").isFile)
    }

    @Test
    fun installShaderLandsInShaderpacks() {
        ContentInstall.install(inst, "", FileKind.SHADERPACK, PackFile("bsl.zip", listOf("https://cdn/bsl.zip")), fakeDownloader)
        assertTrue(File(inst, "shaderpacks/bsl.zip").isFile)
    }

    @Test
    fun installDatapackLandsInDatapacks() {
        ContentInstall.install(inst, "", FileKind.DATAPACK, PackFile("dp.zip", listOf("https://cdn/dp.zip")), fakeDownloader)
        assertTrue(File(inst, "datapacks/dp.zip").isFile)
    }

    @Test
    fun installResourcePackLandsInResourcepacks() {
        ContentInstall.install(inst, "", FileKind.RESOURCEPACK, PackFile("rp.zip", listOf("https://cdn/rp.zip")), fakeDownloader)
        assertTrue(File(inst, "resourcepacks/rp.zip").isFile)
    }

    @Test
    fun installIntoIsolatedVersionUsesTheVersionFolder() {
        version("1.20.1", VersionSettings.ALL)
        ContentInstall.install(inst, "1.20.1", FileKind.MOD, PackFile("a.jar", listOf("https://cdn/a.jar")), fakeDownloader)
        assertTrue(File(inst, "versions/1.20.1/mods/a.jar").isFile)
        assertTrue(!File(inst, "mods/a.jar").exists())
    }

    @Test
    fun installKeepsTheWarningFromVersionPick() {
        val out = ContentInstall.install(
            inst, "", FileKind.MOD, PackFile("a.jar", listOf("https://cdn/a.jar")), fakeDownloader,
            warning = "这个版本没声明支持 fabric",
        )
        assertTrue(out.warning.contains("fabric"))
    }

    @Test
    fun installAWorldUnzipsIntoSaves() {
        val zip = worldZip("SkyBlock")
        val local = PackDownloader { _, dest, _, _ -> zip.copyTo(dest, overwrite = true) }
        val out = ContentInstall.install(inst, "", FileKind.WORLD, PackFile("SkyBlock.zip", listOf("file://x")), local)
        assertEquals("skyblock", out.name.lowercase())
        assertTrue(File(inst, "saves/SkyBlock/level.dat").isFile)
    }

    @Test
    fun installAWorldLeavesNoStagingFileBehind() {
        val zip = worldZip("W")
        val local = PackDownloader { _, dest, _, _ -> zip.copyTo(dest, overwrite = true) }
        ContentInstall.install(inst, "", FileKind.WORLD, PackFile("W.zip", listOf("file://x")), local)
        val leftovers = File(inst, "saves").listFiles()?.filter { it.name.endsWith(".zip") }.orEmpty()
        assertTrue(leftovers.isEmpty())
    }

    @Test
    fun installRejectsAMaliciousFileName() {
        try {
            ContentInstall.install(inst, "", FileKind.MOD, PackFile("../../evil.jar", listOf("https://cdn/x")), fakeDownloader)
            throw AssertionError("应当拒绝")
        } catch (e: ContentError) {
            assertTrue(e.message!!.contains("非法文件名"))
        }
    }

    // ---- 从搜索结果到落盘 ------------------------------------------------

    private val modrinthVersions = """
        [{"id":"v1","name":"Sodium 0.5.8","version_number":"0.5.8","version_type":"release",
          "game_versions":["1.20.1"],"loaders":["fabric"],"date_published":"2024-01-01",
          "files":[{"url":"https://cdn/sodium.jar","filename":"sodium-0.5.8.jar","primary":true,
                    "hashes":{"sha1":""},"size":100}]}]
    """.trimIndent()

    @Test
    fun catalogInstallGoesAllTheWayToDisk() {
        val out = ContentInstall.installFromCatalog(
            inst, "", "Mod", "sodium", "", CatalogSource.MODRINTH, "1.20.1", "fabric",
            CatalogKeys(), TextFetcher { _, _ -> modrinthVersions }, fakeDownloader,
        )
        assertEquals("sodium-0.5.8.jar", out.name)
        assertTrue(File(inst, "mods/sodium-0.5.8.jar").isFile)
    }

    @Test
    fun catalogInstallSurfacesThePickerReason() {
        try {
            ContentInstall.installFromCatalog(
                inst, "", "Mod", "sodium", "", CatalogSource.MODRINTH, "1.21.4", "fabric",
                CatalogKeys(), TextFetcher { _, _ -> modrinthVersions }, fakeDownloader,
            )
            throw AssertionError("应当拒绝")
        } catch (e: ContentError) {
            assertTrue(e.message!!.contains("1.20.1"))
        }
    }

    @Test
    fun catalogInstallSaysWhenCurseForgeNeedsAKey() {
        try {
            ContentInstall.installFromCatalog(
                inst, "", "Mod", "x", "1234", CatalogSource.CURSEFORGE, "1.20.1", "fabric",
                CatalogKeys(), TextFetcher { _, _ -> "" }, fakeDownloader,
            )
            throw AssertionError("应当拒绝")
        } catch (e: ContentError) {
            assertTrue(e.message!!.contains("API key"))
        }
    }

    @Test(expected = ContentError::class)
    fun catalogInstallRejectsNonNumericCurseForgeId() {
        ContentInstall.installFromCatalog(
            inst, "", "Mod", "x", "not-a-number", CatalogSource.CURSEFORGE, "1.20.1", "fabric",
            CatalogKeys("key"), TextFetcher { _, _ -> "" }, fakeDownloader,
        )
    }

    @Test(expected = ContentError::class)
    fun catalogInstallRejectsUnsupportedTab() {
        ContentInstall.installFromCatalog(
            inst, "", "原版游戏", "x", "", CatalogSource.MODRINTH, "1.20.1", "fabric",
            CatalogKeys(), TextFetcher { _, _ -> "[]" }, fakeDownloader,
        )
    }
}
