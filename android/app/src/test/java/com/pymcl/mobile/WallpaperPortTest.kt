package com.pymcl.mobile

import com.pymcl.mobile.data.WallpaperCodec
import com.pymcl.mobile.data.WallpaperKind
import com.pymcl.mobile.data.WallpaperPlaylist
import com.pymcl.mobile.data.WallpaperRef
import com.pymcl.mobile.data.WallpaperState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 钉住 d-315 里那句还没验过的担心：**壁纸清单为空时背景不能是白底**。
 *
 * 白底那一幕是这么来的：渲染层为了让壁纸透出来，把 Scaffold 与顶栏底栏的
 * 底色改成了透明，真正兜底的是 `WallpaperBackdrop(baseColor = …)` 这一层。
 * 于是「清单为空」这条路上只要有任何一步吐出一个不该画的东西、或者兜底色
 * 没传进去，用户看到的就是一片白。这里从数据层把那条路的每一步都焊死：
 * 空清单不产生任何可画的 ref，所以屏幕上能剩下的**只可能**是 baseColor。
 */
class WallpaperPortTest {
    @Test
    fun emptyPlaylistNeverYieldsSomethingToDraw() {
        val empty = WallpaperPlaylist()
        assertTrue(empty.isEmpty)
        assertNull("空清单不该给出当前项", empty.current())
        assertNull("空清单不该给出任何可用项", empty.firstAvailable { true })
        assertFalse("空清单不该轮播", empty.rotates)
    }

    @Test
    fun clearingToBaseColorLeavesNothingOnTop() {
        // 用户点「清除壁纸」之后，能看见的必须只有底色
        val withPaper = WallpaperState().let {
            it.copy(playlist = it.playlist.withItems(listOf(WallpaperRef("file:///a.png"))))
        }
        assertFalse(withPaper.playlist.isEmpty)

        val cleared = withPaper.clearedToBaseColor()
        assertTrue("清除后清单必须是空的", cleared.playlist.isEmpty)
        assertNull(cleared.playlist.current())
        assertNull(cleared.playlist.firstAvailable { true })
    }

    @Test
    fun everyImageBeingUnavailableIsTheSameAsEmpty() {
        // 清单里有条目、但文件全被用户删了——这一条最容易漏，它不是「空清单」，
        // 但能画出来的东西同样是零，兜底色照样得顶上
        val playlist = WallpaperPlaylist().withItems(
            listOf(WallpaperRef("file:///gone1.png"), WallpaperRef("file:///gone2.png")),
        )
        assertFalse(playlist.isEmpty)
        assertNull("文件都不在时不该给出任何可用项", playlist.firstAvailable { false })
    }

    @Test
    fun decodingAMissingOrBrokenConfigFallsBackToEmptyNotToGarbage() {
        // 配置坏了 / 还没写过的时候，解码结果必须是「干净的空状态」，
        // 而不是一个半截 playlist——半截 playlist 会让渲染层去画一个不存在的 uri
        val fromNull = WallpaperCodec.fromMap(null)
        assertTrue(fromNull.playlist.isEmpty)
        assertNull(fromNull.playlist.current())

        val fromJunk = WallpaperCodec.fromMap(mapOf("playlist" to "这不是个 map"))
        assertTrue(fromJunk.playlist.isEmpty)
        assertNull(fromJunk.playlist.current())
    }

    @Test
    fun stateSurvivesARoundTripThroughTheCodec() {
        val state = WallpaperState().let {
            it.copy(
                playlist = it.playlist.withItems(
                    listOf(
                        WallpaperRef("file:///a.png"),
                        WallpaperRef("file:///b.mp4", WallpaperKind.VIDEO),
                    ),
                ),
            )
        }
        val back = WallpaperCodec.fromMap(WallpaperCodec.toMap(state))
        assertEquals(2, back.playlist.items.size)
        assertEquals("file:///a.png", back.playlist.items[0].uri)
        assertEquals(WallpaperKind.VIDEO, back.playlist.items[1].kind)
    }

    @Test
    fun panelStaysOpaqueWhenNothingIsBehindIt() {
        // panelAlpha 是「让壁纸透出来」用的。清单为空时底下什么都没有，
        // 出厂值必须是 100（全不透明），否则顶栏底栏会透到一片白上去
        assertEquals(100, com.pymcl.mobile.data.WallpaperLook.DEFAULT.panelAlpha)
        assertEquals(0, com.pymcl.mobile.data.WallpaperLook.DEFAULT.blur)
        assertEquals(0, com.pymcl.mobile.data.WallpaperLook.DEFAULT.scrim)
    }
}
