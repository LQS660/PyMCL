package com.pymcl.mobile

import com.pymcl.mobile.data.SaveError
import com.pymcl.mobile.data.Saves
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class SavesDomainTest {
    private lateinit var game: File

    @Before
    fun setUp() {
        game = kotlin.io.path.createTempDirectory("pymcl-saves").toFile()
    }

    @After
    fun tearDown() {
        game.deleteRecursively()
    }

    private fun makeSave(name: String, files: Int = 2): File {
        val dir = File(game, "saves/$name").also { it.mkdirs() }
        File(dir, "level.dat").writeText("level")
        repeat(files) { File(dir, "region/r.0.$it.mca").also { f -> f.parentFile.mkdirs() }.writeText("x$it") }
        return dir
    }

    @Test
    fun listIsEmptyWithoutSavesFolder() {
        assertTrue(Saves.list(game).isEmpty())
    }

    @Test
    fun listSkipsFilesAndDotFolders() {
        makeSave("世界一")
        File(game, "saves/.hidden").mkdirs()
        File(game, "saves/loose.txt").writeText("x")
        assertEquals(listOf("世界一"), Saves.list(game).map { it.name })
    }

    @Test
    fun listSortsCaseInsensitively() {
        makeSave("Beta")
        makeSave("alpha")
        assertEquals(listOf("alpha", "Beta"), Saves.list(game).map { it.name })
    }

    @Test
    fun listReportsIconWhenPresent() {
        val dir = makeSave("有图")
        assertEquals("", Saves.list(game)[0].icon)
        File(dir, "icon.png").writeText("png")
        assertTrue(Saves.list(game)[0].icon.endsWith("icon.png"))
    }

    @Test
    fun listReportsNonZeroSize() {
        makeSave("大小")
        assertTrue(Saves.list(game)[0].bytes > 0)
    }

    @Test
    fun safeChildRejectsTraversal() {
        val root = File(game, "saves").also { it.mkdirs() }
        try {
            Saves.safeChild(root, "../escape")
            throw AssertionError("应当拒绝路径穿越")
        } catch (e: SaveError) {
            assertTrue(e.message!!.contains("非法"))
        }
    }

    @Test
    fun safeChildAcceptsDirectChild() {
        val root = File(game, "saves").also { it.mkdirs() }
        assertEquals("世界", Saves.safeChild(root, "世界").name)
    }

    @Test
    fun deleteRemovesTheWholeTree() {
        makeSave("删我")
        Saves.delete(game, "删我")
        assertTrue(Saves.list(game).isEmpty())
    }

    @Test(expected = SaveError::class)
    fun deleteRejectsMissingSave() {
        Saves.delete(game, "不存在")
    }

    @Test
    fun renameMovesFolder() {
        makeSave("旧名")
        val row = Saves.rename(game, "旧名", "新名")
        assertEquals("新名", row.name)
        assertEquals(listOf("新名"), Saves.list(game).map { it.name })
    }

    @Test(expected = SaveError::class)
    fun renameRejectsExistingTarget() {
        makeSave("a")
        makeSave("b")
        Saves.rename(game, "a", "b")
    }

    @Test
    fun listMediaFiltersByExtensionAndOrder() {
        val shots = File(game, "screenshots").also { it.mkdirs() }
        File(shots, "a.png").writeText("a")
        File(shots, "b.txt").writeText("b")
        val newer = File(shots, "c.jpg")
        newer.writeText("c")
        newer.setLastModified(System.currentTimeMillis() + 60_000)
        val rows = Saves.listMedia(game, "screenshots")
        assertEquals(listOf("c.jpg", "a.png"), rows.map { it.name })
    }

    @Test(expected = SaveError::class)
    fun listMediaRejectsUnknownKind() {
        Saves.listMedia(game, "movies")
    }

    @Test
    fun listMediaIsEmptyWhenFolderMissing() {
        assertTrue(Saves.listMedia(game, "logs").isEmpty())
    }

    @Test
    fun backupProducesZipUnderBackups() {
        makeSave("备份我")
        val row = Saves.backup(game, "备份我")
        assertTrue(row.name.endsWith(".zip"))
        assertEquals("备份我", row.save)
        assertTrue(File(row.path).isFile)
        assertTrue(row.bytes > 0)
    }

    @Test
    fun backupDoesNotLeavePartFile() {
        makeSave("x")
        Saves.backup(game, "x")
        val leftovers = Saves.backupsDir(game).listFiles()?.filter { it.name.endsWith(".part") }
        assertEquals(emptyList<File>(), leftovers)
    }

    @Test
    fun backupTwiceInSameSecondGetsDistinctNames() {
        makeSave("x")
        val now = 1_700_000_000_000L
        val a = Saves.backup(game, "x", now)
        val b = Saves.backup(game, "x", now)
        assertNotEquals(a.name, b.name)
        assertEquals(2, Saves.listBackups(game).size)
    }

    @Test
    fun listBackupsFiltersBySaveName() {
        makeSave("a")
        makeSave("b")
        Saves.backup(game, "a")
        Saves.backup(game, "b")
        assertEquals(2, Saves.listBackups(game).size)
        assertEquals(1, Saves.listBackups(game, "a").size)
    }

    @Test
    fun originOfStripsTimestampAndCounter() {
        assertEquals("我的世界", Saves.originOf("我的世界-20260917-190000"))
        assertEquals("我的世界", Saves.originOf("我的世界-20260917-190000-2"))
        assertEquals("没有戳", Saves.originOf("没有戳"))
    }

    @Test
    fun deleteBackupRemovesArchive() {
        makeSave("x")
        val row = Saves.backup(game, "x")
        Saves.deleteBackup(game, row.name)
        assertTrue(Saves.listBackups(game).isEmpty())
    }

    @Test(expected = SaveError::class)
    fun deleteBackupRejectsMissing() {
        Saves.deleteBackup(game, "没有.zip")
    }

    @Test
    fun restoreKeepsExistingSaveBySuffixing() {
        makeSave("原档")
        val row = Saves.backup(game, "原档")
        val restored = Saves.restore(game, row.name)
        assertEquals("原档-还原", restored.name)
        assertEquals(setOf("原档", "原档-还原"), Saves.list(game).map { it.name }.toSet())
    }

    @Test
    fun restoreOverwritesWhenAsked() {
        makeSave("原档")
        val row = Saves.backup(game, "原档")
        val restored = Saves.restore(game, row.name, overwrite = true)
        assertEquals("原档", restored.name)
        assertEquals(1, Saves.list(game).size)
    }

    @Test
    fun restoreRecreatesDeletedSaveUnderOriginalName() {
        makeSave("原档")
        val row = Saves.backup(game, "原档")
        Saves.delete(game, "原档")
        val restored = Saves.restore(game, row.name)
        assertEquals("原档", restored.name)
        assertTrue(File(restored.path, "level.dat").isFile)
    }

    @Test
    fun restoreHonoursExplicitTargetName() {
        makeSave("原档")
        val row = Saves.backup(game, "原档")
        assertEquals("另一个", Saves.restore(game, row.name, targetName = "另一个").name)
    }

    @Test
    fun restoreRejectsTraversalInsideArchive() {
        val dir = Saves.backupsDir(game).also { it.mkdirs() }
        val bad = File(dir, "坏包.zip")
        ZipOutputStream(bad.outputStream()).use { zip ->
            zip.putNextEntry(ZipEntry("../escaped.txt"))
            zip.write("x".toByteArray())
            zip.closeEntry()
        }
        try {
            Saves.restore(game, "坏包.zip")
            throw AssertionError("应当拒绝非法路径")
        } catch (e: SaveError) {
            assertTrue(e.message!!.contains("非法路径"))
        }
        assertFalse(File(game, "escaped.txt").exists())
    }

    @Test
    fun restoreRejectsEmptyArchive() {
        val dir = Saves.backupsDir(game).also { it.mkdirs() }
        ZipOutputStream(File(dir, "空.zip").outputStream()).use { }
        try {
            Saves.restore(game, "空.zip")
            throw AssertionError("应当拒绝空包")
        } catch (e: SaveError) {
            assertTrue(e.message!!.contains("空"))
        }
    }

    @Test
    fun exportAddsZipSuffixAndKeepsContent() {
        makeSave("导出我")
        val out = Saves.export(game, "导出我", File(game, "out/导出我"))
        assertTrue(out.name.endsWith(".zip"))
        assertTrue(out.isFile)
    }

    @Test
    fun exportIntoDirectoryUsesSaveName() {
        makeSave("导出我")
        val dir = File(game, "out").also { it.mkdirs() }
        assertEquals("导出我.zip", Saves.export(game, "导出我", dir).name)
    }

    @Test
    fun exportReportsProgressToCompletion() {
        makeSave("进度", files = 3)
        var last = 0 to 0
        Saves.export(game, "进度", File(game, "out/进度.zip")) { cur, total -> last = cur to total }
        assertEquals(last.second, last.first)
        assertTrue(last.second >= 4)
    }

    @Test
    fun installDatapackCopiesIntoSave() {
        val inst = File(game, "inst").also { it.mkdirs() }
        File(inst, "datapacks").mkdirs()
        File(inst, "datapacks/pack.zip").writeText("pack")
        makeSave("目标档")
        val dest = Saves.installDatapack(game, inst, "pack.zip", "目标档")
        assertTrue(dest.isFile)
        assertTrue(dest.path.replace('\\', '/').endsWith("saves/目标档/datapacks/pack.zip"))
    }

    @Test(expected = SaveError::class)
    fun installDatapackRejectsMissingPack() {
        makeSave("目标档")
        Saves.installDatapack(game, File(game, "inst"), "没有.zip", "目标档")
    }

    @Test
    fun dirSizeStopsAtLimit() {
        val dir = File(game, "many").also { it.mkdirs() }
        repeat(10) { File(dir, "f$it").writeText("0123456789") }
        assertEquals(30L, Saves.dirSize(dir, limit = 3))
    }

    // ---- 交给崩溃归因的那份 ----------------------------------------------

    @Test
    fun theNewestCrashReportIsTheOneHandedToTheAnalyser() {
        val dir = File(game, "crash-reports").also { it.mkdirs() }
        File(dir, "old.txt").apply { writeText("old one"); setLastModified(1_000_000L) }
        File(dir, "new.txt").apply { writeText("newest one"); setLastModified(System.currentTimeMillis()) }
        assertEquals("newest one", com.pymcl.mobile.data.GameRuntime.latestCrashReport(game))
    }

    @Test
    fun aHugeCrashReportIsTruncatedFromTheTail() {
        val dir = File(game, "crash-reports").also { it.mkdirs() }
        // 真实的 crash-report 常有几百 KB，整份拼进归因没意义
        File(dir, "big.txt").writeText("x".repeat(100_000) + "TAIL-MARKER")
        val text = com.pymcl.mobile.data.GameRuntime.latestCrashReport(game)
        assertTrue(text.endsWith("TAIL-MARKER"))
        assertTrue(text.length <= 64 * 1024)
    }

    @Test
    fun noCrashReportsMeansAnEmptyStringNotAnError() {
        assertEquals("", com.pymcl.mobile.data.GameRuntime.latestCrashReport(game))
        assertEquals("", com.pymcl.mobile.data.GameRuntime.latestCrashReport(null))
    }

    @Test
    fun formatSizeCoversEveryUnit() {
        assertEquals("512 B", Saves.formatSize(512))
        assertEquals("2 KB", Saves.formatSize(2048))
        assertEquals("1.0 MB", Saves.formatSize(1L shl 20))
        assertEquals("1.0 GB", Saves.formatSize(1L shl 30))
    }
}
