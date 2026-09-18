package com.pymcl.mobile

import com.pymcl.mobile.data.DEFAULT_SETTINGS
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.SettingsLogic
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsDomainTest {
    @Test
    fun mergeKeepsUnknownKeysFromDesktop() {
        // 桌面写进来的键不在安卓的表里，但一次保存不能把它们抹掉
        val stored = JSONObject()
            .put(SettingsKeys.MEMORY_MB, 6144)
            .put("ui_window_aspect", "16:9")
            .put("ui_nav_pinned", "[]")
        val merged = SettingsLogic.merge(stored)

        assertEquals(6144, merged.optInt(SettingsKeys.MEMORY_MB))
        assertEquals("16:9", merged.optString("ui_window_aspect"))
        assertEquals("[]", merged.optString("ui_nav_pinned"))
        // 没给的键要补上出厂值
        assertEquals("auto", merged.optString(SettingsKeys.DOWNLOAD_SOURCE))
        assertEquals("all", merged.optString(SettingsKeys.DEFAULT_ISOLATION))
    }

    @Test
    fun defaultsCoverEveryKeyTheUiWrites() {
        // UI 读哪个键，出厂表里就得有它，否则「改了、重启没了」
        val required = listOf(
            SettingsKeys.THEME_COLOR, SettingsKeys.UI_DARK, SettingsKeys.UI_SIDEBAR_OPACITY,
            SettingsKeys.UI_BACKGROUND_BLUR, SettingsKeys.UI_BACKGROUND_DIM,
            SettingsKeys.AI_MODE, SettingsKeys.AI_MODEL, SettingsKeys.AI_CONFIRM_WRITES,
            SettingsKeys.FEEDBACK_CONSENT, SettingsKeys.FEEDBACK_HEARTBEAT,
            SettingsKeys.DEFAULT_ISOLATION, SettingsKeys.DOWNLOAD_SOURCE,
            SettingsKeys.DOWNLOAD_THREADS, SettingsKeys.MEMORY_MB, SettingsKeys.DEFAULT_JAVA,
            SettingsKeys.FIRST_RUN, SettingsKeys.UI_LAYOUT_PROFILE,
        )
        required.forEach { assertTrue("缺出厂值：$it", DEFAULT_SETTINGS.containsKey(it)) }
    }

    @Test
    fun manifestUrlOrderFollowsDownloadSource() {
        assertEquals(listOf(Paths.MOJANG_MANIFEST), SettingsLogic.manifestUrls("official"))
        assertEquals(listOf(Paths.BMCL_MANIFEST), SettingsLogic.manifestUrls("bmclapi"))
        // auto 是镜像优先、官方垫底
        assertEquals(
            listOf(Paths.BMCL_MANIFEST, Paths.MOJANG_MANIFEST),
            SettingsLogic.manifestUrls("auto"),
        )
    }

    @Test
    fun clampsStayInsideTheUiRanges() {
        assertEquals(512, SettingsLogic.clampMemory(0))
        assertEquals(32768, SettingsLogic.clampMemory(99999))
        assertEquals(4096, SettingsLogic.clampMemory(4096))
        assertEquals(0, SettingsLogic.clampPercent(-5))
        assertEquals(100, SettingsLogic.clampPercent(300))
        assertEquals(60, SettingsLogic.clampBlur(120))
        assertEquals(1, SettingsLogic.clampThreads(0))
        assertEquals(64, SettingsLogic.clampThreads(1000))
    }

    @Test
    fun parseColorAcceptsEveryFormDesktopWrites() {
        assertEquals(0xFF2E9B6BL, SettingsLogic.parseColor("#2E9B6B"))
        assertEquals(0xFF2E9B6BL, SettingsLogic.parseColor("2e9b6b"))
        assertEquals(0xFFAABBCCL, SettingsLogic.parseColor("#ABC"))
        assertEquals(0x802E9B6BL, SettingsLogic.parseColor("#802E9B6B"))
        // 认不出来退回出厂绿，不是抛异常——配置坏了也不能开不了机
        assertEquals(0xFF2E9B6BL, SettingsLogic.parseColor("绿色"))
        assertEquals(0xFF2E9B6BL, SettingsLogic.parseColor(""))
    }

    @Test
    fun lightColorDecidesTextContrast() {
        assertTrue(SettingsLogic.isLightColor(0xFFFFFFFFL))
        assertTrue(SettingsLogic.isLightColor(0xFFE8862EL))
        assertFalse(SettingsLogic.isLightColor(0xFF2E9B6BL))
        assertFalse(SettingsLogic.isLightColor(0xFF000000L))
    }

    @Test
    fun backgroundHistoryPushesBothStacksTogether() {
        var images = emptyList<String>()
        var folders = emptyList<String>()

        val first = SettingsLogic.pushBackgroundHistory(images, folders, "a.png", "")
        images = first.first
        folders = first.second
        assertEquals(listOf("a.png"), images)
        assertEquals(listOf(""), folders)

        val second = SettingsLogic.pushBackgroundHistory(images, folders, "b.png", "/wall")
        images = second.first
        folders = second.second
        assertEquals(listOf("a.png", "b.png"), images)
        assertEquals(listOf("", "/wall"), folders)
        assertEquals(images.size, folders.size)

        // 同一组连推两次不该堆两遍
        val again = SettingsLogic.pushBackgroundHistory(images, folders, "b.png", "/wall")
        assertEquals(images, again.first)
        assertEquals(folders, again.second)
    }

    @Test
    fun historyStacksGetPairedWhenOnlyImagesWereStored() {
        // 老配置只写过单图栈，这里要补齐文件夹栈，否则撤销时下标对不上
        val (images, folders) = SettingsLogic.pairHistory(listOf("a", "b", "c"), emptyList())
        assertEquals(3, images.size)
        assertEquals(3, folders.size)
        assertTrue(folders.all { it.isEmpty() })
    }

    @Test
    fun historyIsCappedSoConfigDoesNotGrowForever() {
        var images = emptyList<String>()
        var folders = emptyList<String>()
        repeat(40) { i ->
            val next = SettingsLogic.pushBackgroundHistory(images, folders, "w$i.png", "")
            images = next.first
            folders = next.second
        }
        assertEquals(20, images.size)
        assertEquals(20, folders.size)
        assertEquals("w39.png", images.last())
        assertNotEquals("w0.png", images.first())
    }

    @Test
    fun sanitizeFileNameKeepsThemePacksOnDisk() {
        assertEquals("my_theme", Paths.sanitizeFileName("my/theme"))
        assertEquals("dark 01", Paths.sanitizeFileName("  dark 01  "))
        // 非法字符换成下划线而不是删掉，跟桌面 themes._sanitize 一致：
        // 「///」还是三个字符，不会掉进 fallback
        assertEquals("___", Paths.sanitizeFileName("///"))
        assertEquals("untitled", Paths.sanitizeFileName("   "))
        assertEquals("fallback", Paths.sanitizeFileName("", "fallback"))
    }
}
