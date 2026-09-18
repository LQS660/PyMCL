package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.Lan
import com.pymcl.mobile.data.ManifestRepo
import com.pymcl.mobile.data.TaskCenter
import com.pymcl.mobile.model.TaskInfo
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TaskAndLanTest {
    // ---- TaskCenter -----------------------------------------------------

    @Test
    fun downloadTitlesAreRecognised() {
        assertTrue(TaskCenter.isDownloadTitle("安装游戏 1.20.1"))
        assertTrue(TaskCenter.isDownloadTitle("安装整合包 ATM9"))
        assertTrue(TaskCenter.isDownloadTitle("下载 Java 21"))
        assertTrue(TaskCenter.isDownloadTitle("皮肤站登录"))
        assertTrue(TaskCenter.isDownloadTitle("备份存档 我的世界"))
    }

    @Test
    fun interactiveTitlesStayOutOfTheDownloadDock() {
        assertFalse(TaskCenter.isDownloadTitle("启动游戏 1.20.1"))
        assertFalse(TaskCenter.isDownloadTitle("微软登录"))
    }

    @Test
    fun blankTitleIsNotADownload() {
        assertFalse(TaskCenter.isDownloadTitle(""))
        assertFalse(TaskCenter.isDownloadTitle("   "))
    }

    @Test
    fun unrelatedTitleIsNotADownload() {
        assertFalse(TaskCenter.isDownloadTitle("清理缓存"))
    }

    @Test
    fun splitProgressMessageSeparatesSpeed() {
        assertEquals("解压 libraries" to "3.2 MB/s", TaskCenter.splitProgressMessage("解压 libraries  |  3.2 MB/s"))
    }

    @Test
    fun splitProgressMessageWithoutSeparator() {
        assertEquals("排队中…" to "", TaskCenter.splitProgressMessage("排队中…"))
        assertEquals("" to "", TaskCenter.splitProgressMessage(""))
    }

    @Test
    fun percentClampsAndGuardsDivision() {
        assertEquals(0, TaskCenter.percent(5, 0))
        assertEquals(50, TaskCenter.percent(5, 10))
        assertEquals(100, TaskCenter.percent(20, 10))
        assertEquals(0, TaskCenter.percent(-5, 10))
    }

    @Test
    fun activeCountOnlyCountsUnfinishedDownloads() {
        val tasks = listOf(
            TaskInfo("1", "安装游戏 1.20.1"),
            TaskInfo("2", "安装模组 sodium", done = true),
            TaskInfo("3", "启动游戏 1.20.1"),
            TaskInfo("4", "下载 Java 17"),
        )
        assertEquals(2, TaskCenter.activeCount(tasks))
    }

    @Test
    fun clearFinishedKeepsRunningOnes() {
        val tasks = listOf(TaskInfo("1", "安装游戏"), TaskInfo("2", "安装模组", done = true))
        assertEquals(listOf("1"), TaskCenter.clearFinished(tasks).map { it.id })
        assertEquals(listOf("2"), TaskCenter.finished(tasks).map { it.id })
    }

    @Test
    fun modpackInstallAutoExpandsItsLog() {
        assertTrue(TaskCenter.autoExpandLog("安装整合包 ATM9"))
        assertFalse(TaskCenter.autoExpandLog("安装游戏 1.20.1"))
    }

    @Test
    fun summaryMarksSuccessAndFailure() {
        assertEquals("✔ 完成", TaskCenter.summary(TaskInfo("1", "安装游戏", done = true, message = "完成")))
        assertEquals(
            "✘ 网络超时",
            TaskCenter.summary(TaskInfo("1", "安装游戏", done = true, success = false, message = "网络超时")),
        )
    }

    @Test
    fun summaryJoinsStatusAndSpeedWhileRunning() {
        assertEquals("解压 · 3.2 MB/s", TaskCenter.summary(TaskInfo("1", "安装游戏", message = "解压  |  3.2 MB/s")))
    }

    @Test
    fun summaryFallsBackWhenMessageIsBlank() {
        assertEquals("处理中…", TaskCenter.summary(TaskInfo("1", "安装游戏")))
    }

    @Test
    fun humanSpeedCoversEveryUnit() {
        assertEquals("", TaskCenter.humanSpeed(0))
        assertEquals("512 B/s", TaskCenter.humanSpeed(512))
        assertEquals("2 KB/s", TaskCenter.humanSpeed(2048))
        assertEquals("1.0 MB/s", TaskCenter.humanSpeed(1L shl 20))
    }

    @Test
    fun appendLogKeepsOnlyTheTail() {
        var task = TaskInfo("1", "安装游戏")
        repeat(50) { task = TaskCenter.appendLog(task, "line $it") }
        assertEquals(40, task.log.size)
        assertEquals("line 49", task.log.last())
    }

    @Test
    fun appendLogHonoursCustomLimit() {
        var task = TaskInfo("1", "安装游戏")
        repeat(10) { task = TaskCenter.appendLog(task, "l$it", limit = 3) }
        assertEquals(listOf("l7", "l8", "l9"), task.log)
    }

    // ---- CatalogRepo ----------------------------------------------------

    @Test
    fun downloadKindsMatchDesktopOrder() {
        assertEquals("原版游戏", CatalogRepo.KINDS.first())
        assertEquals("下载任务", CatalogRepo.KINDS.last())
        assertEquals(8, CatalogRepo.KINDS.size)
    }

    @Test
    fun projectTypeMapsEveryKind() {
        assertEquals("modpack", CatalogRepo.projectType("整合包"))
        assertEquals("resourcepack", CatalogRepo.projectType("资源包"))
        assertEquals("shader", CatalogRepo.projectType("光影包"))
        assertEquals("datapack", CatalogRepo.projectType("数据包"))
        assertEquals("mod", CatalogRepo.projectType("Mod"))
        assertEquals("", CatalogRepo.projectType("世界"))
    }

    @Test
    fun localKindsNeverHitTheNetwork() {
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("原版游戏", "sodium"))
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("下载任务", "sodium"))
    }

    @Test
    fun blankQueryNeverHitsTheNetwork() {
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("Mod", ""))
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("整合包", "   "))
    }

    @Test
    fun searchUrlsPutMirrorFirst() {
        val urls = CatalogRepo.searchUrls("mod", "sodium")
        assertEquals(2, urls.size)
        assertTrue(urls[0].contains("mcimirror.top"))
        assertTrue(urls[1].startsWith("https://api.modrinth.com/"))
        assertTrue(urls[0].contains("query=sodium"))
    }

    @Test
    fun searchUrlsEncodeChineseQuery() {
        assertTrue(CatalogRepo.searchUrls("mod", "工业").all { it.contains("%E5%B7%A5%E4%B8%9A") })
    }

    @Test
    fun curseForgeUrlsCarryWorldClassId() {
        assertTrue(CatalogRepo.curseForgeUrls("skyblock").all { it.contains("classId=17") })
    }

    @Test
    fun parseModrinthMapsEveryField() {
        val hits = CatalogRepo.parseModrinth(
            """{"hits":[{"title":"Sodium","slug":"sodium","description":"fast","downloads":42,"author":"jelly","project_id":"AA"}]}""",
        )
        assertEquals(1, hits.size)
        assertEquals("Sodium", hits[0].name)
        assertEquals(42L, hits[0].downloads)
        assertEquals("Modrinth", hits[0].source)
        assertEquals("AA", hits[0].projectId)
    }

    @Test
    fun parseModrinthToleratesMissingHits() {
        assertTrue(CatalogRepo.parseModrinth("{}").isEmpty())
    }

    @Test
    fun parseCurseForgeMapsSummaryAndAuthor() {
        val hits = CatalogRepo.parseCurseForge(
            """{"data":[{"name":"SkyBlock","slug":"skyblock","summary":"island","downloadCount":7,"id":"99","authors":[{"name":"bob"}]}]}""",
        )
        assertEquals("SkyBlock", hits[0].name)
        assertEquals("island", hits[0].description)
        assertEquals("bob", hits[0].author)
        assertEquals("CurseForge", hits[0].source)
    }

    // ---- ManifestRepo ---------------------------------------------------

    @Test
    fun parseReadsEveryColumn() {
        val rows = ManifestRepo.parse(
            JSONObject("""{"versions":[{"id":"1.20.1","type":"release","url":"https://x","sha1":"a","releaseTime":"t"}]}"""),
        )
        assertEquals(1, rows.size)
        assertEquals("1.20.1", rows[0].id)
        assertEquals("a", rows[0].sha1)
        assertEquals("t", rows[0].releaseTime)
    }

    @Test
    fun parseToleratesMissingVersionsArray() {
        assertTrue(ManifestRepo.parse(JSONObject("{}")).isEmpty())
    }

    @Test
    fun latestReadsBothChannels() {
        val (release, snapshot) = ManifestRepo.latest(
            JSONObject("""{"latest":{"release":"1.21.1","snapshot":"24w40a"}}"""),
        )
        assertEquals("1.21.1", release)
        assertEquals("24w40a", snapshot)
    }

    @Test
    fun latestIsBlankWithoutTheBlock() {
        assertEquals("" to "", ManifestRepo.latest(JSONObject("{}")))
    }

    @Test
    fun cacheFreshnessFollowsTtl() {
        val dir = kotlin.io.path.createTempDirectory("pymcl-manifest").toFile()
        try {
            val cache = File(dir, "version_manifest.json")
            assertFalse(ManifestRepo.fresh(cache))
            cache.writeText("{}")
            cache.setLastModified(1_000_000_000_000L)
            assertTrue(ManifestRepo.fresh(cache, now = 1_000_000_000_000L + 3600_000))
            assertFalse(ManifestRepo.fresh(cache, now = 1_000_000_000_000L + 5 * 3600_000))
        } finally {
            dir.deleteRecursively()
        }
    }

    // ---- Lan ------------------------------------------------------------

    @Test
    fun hintListsEveryAddress() {
        val text = Lan.hint(25566, listOf("192.168.1.7", "10.0.0.2"))
        assertTrue(text.contains("192.168.1.7:25566"))
        assertTrue(text.contains("10.0.0.2:25566"))
        assertTrue(text.startsWith("房主在游戏里「对局域网开放」后"))
    }

    @Test
    fun localIpsNeverReturnsEmpty() {
        assertTrue(Lan.localIps().isNotEmpty())
    }

    @Test
    fun parseOpenPortReadsEnglishLog() {
        assertEquals(54321, Lan.parseOpenPort("[Server thread/INFO]: Local game hosted on port 54321"))
    }

    @Test
    fun parseOpenPortReadsChineseLog() {
        assertEquals(54321, Lan.parseOpenPort("本地游戏已在端口 54321 上开放"))
    }

    @Test
    fun parseOpenPortIgnoresUnrelatedLines() {
        assertNull(Lan.parseOpenPort("Loading world"))
        assertNull(Lan.parseOpenPort("port 999999"))
    }

    @Test
    fun splitAddressDelegatesToServers() {
        assertEquals("192.168.1.7" to 25566, Lan.splitAddress("192.168.1.7:25566"))
        assertEquals("192.168.1.7" to 25565, Lan.splitAddress("192.168.1.7"))
    }
}
