package com.pymcl.mobile

import com.pymcl.mobile.data.CleanEntry
import com.pymcl.mobile.data.CleanPlan
import com.pymcl.mobile.data.Cleaner
import com.pymcl.mobile.data.DownloadDock
import com.pymcl.mobile.data.TaskCenter
import com.pymcl.mobile.model.TaskInfo
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * 任务角标、悬浮下载坞、清理 / 维护工具三件套的纯逻辑。
 * 全程不碰 Android：实例目录在临时目录里现搭，词表与 Compose 都不参与。
 */
class CleanerDockTest {

    private fun tempRoot(): File = kotlin.io.path.createTempDirectory("pymcl-cleaner").toFile()

    /** 搭一个能被 InstanceStore 认出来的实例：`.instance.json` + `versions/<id>/<id>.json`。 */
    private fun instance(root: File, name: String): File {
        val dir = File(root, name).also { it.mkdirs() }
        File(dir, ".instance.json").writeText(JSONObject().put("name", name).toString())
        return dir
    }

    private fun version(instDir: File, id: String, json: String) {
        val dir = File(instDir, "versions/$id").also { it.mkdirs() }
        File(dir, "$id.json").writeText(json)
    }

    private fun library(instDir: File, relative: String, bytes: Int = 8): File {
        val file = File(instDir, "libraries/$relative")
        file.parentFile?.mkdirs()
        file.writeBytes(ByteArray(bytes))
        return file
    }

    private fun names(rows: List<CleanEntry>): List<String> = rows.map { File(it.path).name }.sorted()

    // ---- 角标计数 --------------------------------------------------------

    @Test
    fun badgeCountsOnlyUnfinishedDownloads() {
        val tasks = listOf(
            TaskInfo("1", "安装游戏 1.20.1"),
            TaskInfo("2", "安装整合包 ATM9"),
            TaskInfo("3", "安装模组 sodium", done = true),
            TaskInfo("4", "启动游戏 1.20.1"),
            TaskInfo("5", "微软登录"),
        )
        assertEquals(2, TaskCenter.activeCount(tasks))
        assertEquals("2", TaskCenter.badgeText(TaskCenter.activeCount(tasks)))
    }

    @Test
    fun exportingAModpackCountsAsADownload() {
        // 桌面把「导出整合包」也算进下载坞（is_download_title 只排掉启动 / 登录三类），
        // 安卓的白名单先前漏了它：导出跑着的时候角标不动、坞也不出来
        assertTrue(TaskCenter.isDownloadTitle("导出整合包 default"))
        assertEquals(1, TaskCenter.activeCount(listOf(TaskInfo("1", "导出整合包 default"))))
    }

    @Test
    fun badgeIsBlankWhenNothingIsRunning() {
        assertEquals("", TaskCenter.badgeText(0))
        assertEquals("", TaskCenter.badgeText(-1))
        assertEquals("", TaskCenter.badgeText(TaskCenter.activeCount(emptyList())))
    }

    @Test
    fun badgeCapsAtNinetyNinePlus() {
        assertEquals("1", TaskCenter.badgeText(1))
        assertEquals("99", TaskCenter.badgeText(99))
        assertEquals("99+", TaskCenter.badgeText(100))
        assertEquals("99+", TaskCenter.badgeText(4321))
    }

    // ---- 下载坞隐藏页集合 -------------------------------------------------

    @Test
    fun hiddenPagesMatchTheDesktopSet() {
        assertEquals(setOf("settings", "instance", "tasks", "feedback"), DownloadDock.HIDDEN_PAGES)
    }

    @Test
    fun dockHidesOnExactlyThoseFourPages() {
        val hidden = listOf(
            DownloadDock.PAGE_SETTINGS,
            DownloadDock.PAGE_INSTANCE,
            DownloadDock.PAGE_TASKS,
            DownloadDock.PAGE_FEEDBACK,
        )
        val shown = listOf(
            DownloadDock.PAGE_LAUNCH,
            DownloadDock.PAGE_MULTIPLAYER,
            DownloadDock.PAGE_DOWNLOAD,
            DownloadDock.PAGE_AI,
            DownloadDock.PAGE_MINE,
            DownloadDock.PAGE_THEME,
            DownloadDock.PAGE_LAYOUT,
            DownloadDock.PAGE_ACCOUNT,
            DownloadDock.PAGE_JAVA,
            DownloadDock.PAGE_MODS,
        )
        hidden.forEach { assertTrue(it, DownloadDock.hidesDock(it)) }
        shown.forEach { assertFalse(it, DownloadDock.hidesDock(it)) }
        assertEquals(hidden.toSet(), DownloadDock.HIDDEN_PAGES)
    }

    @Test
    fun dockNeedsBothARunningDownloadAndAnAllowedPage() {
        assertTrue(DownloadDock.visible(1, DownloadDock.PAGE_LAUNCH))
        assertFalse(DownloadDock.visible(0, DownloadDock.PAGE_LAUNCH))
        assertFalse(DownloadDock.visible(3, DownloadDock.PAGE_SETTINGS))
        // 认不出的页当作不隐藏：新加一页忘了登记，最多多露一条坞，不会把它藏没
        assertTrue(DownloadDock.visible(1, "brand-new-page"))
    }

    @Test
    fun dockFollowsTheNewestRunningDownload() {
        val tasks = listOf(
            TaskInfo("3", "启动游戏 1.20.1"),
            TaskInfo("2", "安装整合包 ATM9"),
            TaskInfo("1", "安装游戏 1.20.1", done = true),
        )
        assertEquals("2", DownloadDock.current(tasks)?.id)
        assertNull(DownloadDock.current(listOf(TaskInfo("1", "安装游戏", done = true))))
        assertNull(DownloadDock.current(emptyList()))
    }

    // ---- 清理目标路径集合 -------------------------------------------------

    @Test
    fun previewKeepsReferencedLibrariesAndListsTheRest() {
        val root = tempRoot()
        try {
            val inst = instance(root, "default")
            version(
                inst, "1.20.1",
                """{"id":"1.20.1","libraries":[
                    {"name":"com.foo:bar:1.0","downloads":{"artifact":{"path":"com/foo/bar/1.0/bar-1.0.jar"}}},
                    {"name":"net.fabricmc:tiny:2.0"}
                ]}""",
            )
            library(inst, "com/foo/bar/1.0/bar-1.0.jar")
            library(inst, "net/fabricmc/tiny/2.0/tiny-2.0.jar")
            val stray = library(inst, "org/old/dead/9.9/dead-9.9.jar")

            val plan = Cleaner.preview(root, File(root, "no-cache"))
            assertEquals(listOf(stray.name), names(plan.unusedLibraries))
            assertEquals(emptyList<String>(), names(plan.parts))
            assertEquals(emptyList<String>(), names(plan.cache))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun previewSortsPartsAndUpdateCacheIntoTheirOwnKinds() {
        val root = tempRoot()
        try {
            val inst = instance(root, "default")
            library(inst, "com/foo/bar/1.0/bar-1.0.jar.part")
            val cache = File(root, "cache").also { it.mkdirs() }
            File(cache, "PyMCL-1.0.2.bin").writeBytes(ByteArray(16))
            File(cache, "nested").mkdirs()
            File(cache, "nested/half.part").writeBytes(ByteArray(4))
            // 缓存里的普通文件不归清理管：版本清单就躺在这儿
            File(cache, "version_manifest.json").writeText("{}")

            val plan = Cleaner.preview(root, cache)
            assertEquals(listOf("bar-1.0.jar.part", "half.part"), names(plan.parts))
            assertEquals(listOf("PyMCL-1.0.2.bin"), names(plan.cache))
            assertEquals(emptyList<String>(), names(plan.unusedLibraries))
            assertEquals(3, plan.count)
            assertEquals(8L + 16L + 4L, plan.bytes)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun inheritedAndClassifierLibrariesCountAsReferenced() {
        val root = tempRoot()
        try {
            val inst = instance(root, "default")
            version(
                inst, "1.20.1",
                """{"id":"1.20.1","libraries":[
                    {"name":"org.lwjgl:lwjgl:3.3.1","downloads":{
                        "artifact":{"path":"org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1.jar"},
                        "classifiers":{"natives-linux":{"path":"org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-linux.jar"}}}}
                ]}""",
            )
            version(
                inst, "fabric-1.20.1",
                """{"id":"fabric-1.20.1","inheritsFrom":"1.20.1","libraries":[
                    {"name":"net.fabricmc:loader:0.15"}
                ]}""",
            )
            library(inst, "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1.jar")
            library(inst, "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-linux.jar")
            library(inst, "net/fabricmc/loader/0.15/loader-0.15.jar")

            assertEquals(emptyList<String>(), names(Cleaner.preview(root, File(root, "cache")).unusedLibraries))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun sharedLibrariesAcrossInstancesAreScannedOnce() {
        val root = tempRoot()
        try {
            instance(root, "alpha")
            instance(root, "beta")
            library(File(root, "alpha"), "org/dead/x/1/x-1.jar")
            library(File(root, "beta"), "org/dead/y/1/y-1.jar")

            val plan = Cleaner.preview(root, File(root, "cache"))
            assertEquals(listOf("x-1.jar", "y-1.jar"), names(plan.unusedLibraries))
            // 各扫各的目录，同一个文件不会被数两遍
            assertEquals(plan.unusedLibraries.size, plan.unusedLibraries.map { it.path }.distinct().size)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun applyOnlyTouchesTheTickedKinds() {
        val root = tempRoot()
        try {
            val inst = instance(root, "default")
            val stray = library(inst, "org/dead/x/1/x-1.jar")
            val half = library(inst, "org/dead/x/1/x-1.jar.part", bytes = 4)

            val plan = Cleaner.preview(root, File(root, "cache"))
            val result = Cleaner.apply(plan, listOf(Cleaner.KIND_PARTS))
            assertEquals(1, result.removed)
            assertEquals(4L, result.bytes)
            assertFalse(half.exists())
            assertTrue(stray.exists())

            assertEquals(1, Cleaner.apply(plan, Cleaner.ALL_KINDS).removed)
            assertFalse(stray.exists())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun applyIgnoresFilesThatVanishedSinceTheScan() {
        val plan = CleanPlan(parts = listOf(CleanEntry(File("no/such/file.part").absolutePath, 99)))
        val result = Cleaner.apply(plan)
        assertEquals(0, result.removed)
        assertEquals(0L, result.bytes)
    }

    @Test
    fun planSlicesAndTotalsFollowTheTickedKinds() {
        val plan = CleanPlan(
            unusedLibraries = listOf(CleanEntry("a", 10)),
            parts = listOf(CleanEntry("b", 20), CleanEntry("c", 30)),
            cache = listOf(CleanEntry("d", 40)),
        )
        assertEquals(4, plan.count)
        assertEquals(100L, plan.bytes)
        assertEquals(2, plan.of(Cleaner.KIND_PARTS).size)
        assertEquals(emptyList<CleanEntry>(), plan.of("nope"))
        assertEquals(50L, plan.bytesOf(listOf(Cleaner.KIND_UNUSED, Cleaner.KIND_CACHE)))
        // 同一类勾两次不该算两遍
        assertEquals(50L, plan.bytesOf(listOf(Cleaner.KIND_PARTS, Cleaner.KIND_PARTS)))
        assertEquals(0L, plan.bytesOf(emptyList()))
    }



    @Test
    fun libraryPathsPreferTheDeclaredArtifactPath() {
        assertEquals(
            listOf("a/b/1/b-1.jar"),
            Cleaner.libraryPaths(JSONObject("""{"name":"x:y:2","downloads":{"artifact":{"path":"a/b/1/b-1.jar"}}}""")),
        )
        assertEquals(
            listOf("a/b/b/1/b-1.jar"),
            Cleaner.libraryPaths(JSONObject("""{"name":"a.b:b:1"}""")),
        )
        // natives 声明的坐标指的不是同一个文件，别照着它推路径
        assertEquals(
            emptyList<String>(),
            Cleaner.libraryPaths(JSONObject("""{"name":"a.b:b:1","natives":{"linux":"natives-linux"}}""")),
        )
        assertEquals(emptyList<String>(), Cleaner.libraryPaths(JSONObject("""{"name":"broken"}""")))
    }
}
