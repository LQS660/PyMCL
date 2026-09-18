package com.pymcl.mobile

import com.pymcl.mobile.data.LayoutStore
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.ThemePack
import com.pymcl.mobile.data.ThemeStore
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeLayoutTest {
    // ------------------------------------------------------------------ 主题
    @Test
    fun themePackRoundTripsThroughJson() {
        val pack = ThemePack(
            name = "深绿",
            themeColor = "#1E7A52",
            dark = true,
            background = "/sdcard/a.png",
            backgroundFolder = "/sdcard/walls",
            sidebarOpacity = 70,
            backgroundBlur = 12,
            backgroundDim = 40,
            backgroundShuffle = true,
            backgroundInterval = 5,
        )
        val back = ThemeStore.parse(pack.toJson())
        assertEquals(pack, back)
    }

    @Test
    fun themePackTolerateAPartialFile() {
        // 手写的 / 老版本导出的主题包缺字段，不能整个读失败
        val back = ThemeStore.parse(JSONObject("""{"theme_color":"#4C8BF5"}"""), "手写")
        assertEquals("手写", back.name)
        assertEquals("#4C8BF5", back.themeColor)
        assertFalse(back.dark)
        assertEquals(85, back.sidebarOpacity)
    }

    @Test
    fun applyingAThemeThatChangesWallpaperPushesHistory() {
        val pack = ThemePack("夜", "#000000", true, background = "new.png")
        val updates = ThemeStore.applyUpdates(pack, "old.png", "", emptyList(), emptyList())

        assertEquals("new.png", updates[SettingsKeys.UI_BACKGROUND])
        // 主题包换壁纸也得能撤销——这条路径绕开了设置页的保存按钮
        assertEquals(listOf("old.png"), updates[SettingsKeys.UI_BACKGROUND_HISTORY])
        assertEquals(listOf(""), updates[SettingsKeys.UI_BACKGROUND_FOLDER_HISTORY])
    }

    @Test
    fun applyingAThemeThatKeepsWallpaperDoesNotTouchHistory() {
        val pack = ThemePack("同壁纸", "#2E9B6B", false, background = "same.png")
        val updates = ThemeStore.applyUpdates(pack, "same.png", "", listOf("x.png"), listOf(""))
        assertNull(updates[SettingsKeys.UI_BACKGROUND_HISTORY])
    }

    @Test
    fun outOfRangeLookValuesAreClampedOnApply() {
        val pack = ThemePack("越界", "#2E9B6B", false, sidebarOpacity = 300, backgroundBlur = 999, backgroundDim = -5)
        val updates = ThemeStore.applyUpdates(pack, "", "", emptyList(), emptyList())
        assertEquals(100, updates[SettingsKeys.UI_SIDEBAR_OPACITY])
        assertEquals(60, updates[SettingsKeys.UI_BACKGROUND_BLUR])
        assertEquals(0, updates[SettingsKeys.UI_BACKGROUND_DIM])
    }

    // ------------------------------------------------------------------ 布局
    @Test
    fun defaultLayoutFillsTheCanvasWithoutOverflow() {
        val doc = LayoutStore.defaultDoc()
        assertEquals(LayoutStore.LAYOUT_VERSION, doc.version)
        assertTrue(doc.items.isNotEmpty())
        doc.items.forEach {
            assertTrue("${it.type} 越界", it.x + it.w <= 1.0001f)
            assertTrue("${it.type} 越界", it.y + it.h <= 1.0001f)
            assertTrue(it.type in LayoutStore.KNOWN_CARDS)
        }
    }

    @Test
    fun layoutRoundTripsThroughJson() {
        val doc = LayoutStore.defaultDoc()
        val back = LayoutStore.parseDoc(doc.toJson())
        assertNotNull(back)
        assertEquals(doc.items.size, back!!.items.size)
        assertEquals(doc.items.map { it.type }, back.items.map { it.type })
    }

    @Test
    fun unknownCardTypesFromDesktopAreDropped() {
        val json = JSONObject(
            """{"version":1,"items":[
                 {"type":"banner","x":0,"y":0,"w":1,"h":0.2},
                 {"type":"某个桌面独有的卡","x":0,"y":0.2,"w":1,"h":0.2}]}""",
        )
        val doc = LayoutStore.parseDoc(json)
        assertNotNull(doc)
        assertEquals(1, doc!!.items.size)
        assertEquals("banner", doc.items[0].type)
    }

    @Test
    fun outOfCanvasCardsAreClampedBackIn() {
        val json = JSONObject(
            """{"items":[{"type":"log","x":0.9,"y":0.9,"w":5,"h":5}]}""",
        )
        val card = LayoutStore.parseDoc(json)!!.items[0]
        assertTrue(card.x + card.w <= 1.0001f)
        assertTrue(card.y + card.h <= 1.0001f)
    }

    @Test
    fun emptyOrBrokenLayoutFallsBackInsteadOfCrashing() {
        assertNull(LayoutStore.parseDoc(null))
        assertNull(LayoutStore.parseDoc(JSONObject("{}")))
        assertNull(LayoutStore.parseDoc(JSONObject("""{"items":[]}""")))
        // 全是不认识的卡也算读不出来，调用方会退回出厂布局
        assertNull(LayoutStore.parseDoc(JSONObject("""{"items":[{"type":"zzz"}]}""")))
    }
}
