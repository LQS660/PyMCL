package com.pymcl.mobile

import com.pymcl.mobile.data.Terracotta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TerracottaRoomTest {
    /** 造一个种子能被 7 整除的房间号，和内核生成出来的形状一致。 */
    private fun room(seed: Long) = Terracotta.roomFromValue(seed - seed % 7)

    @Test
    fun alphabetMatchesKernel() {
        assertEquals("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ", Terracotta.ROOM_CHARS)
        assertEquals(34, Terracotta.ROOM_CHARS.length)
        assertFalse(Terracotta.ROOM_CHARS.contains('I'))
        assertFalse(Terracotta.ROOM_CHARS.contains('O'))
    }

    @Test
    fun customNodeIsTheHmclOne() {
        assertEquals(
            "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0",
            Terracotta.HMCL_CUSTOM_NODE,
        )
    }

    @Test
    fun extraNodesAlwaysLeadWithTheCustomNode() {
        assertEquals(listOf(Terracotta.HMCL_CUSTOM_NODE), Terracotta.extraNodes())
        assertEquals(Terracotta.HMCL_CUSTOM_NODE, Terracotta.extraNodes(listOf("tcp://x:1")).first())
    }

    @Test
    fun extraNodesAppendUserNodesAndTrim() {
        val nodes = Terracotta.extraNodes(listOf("  tcp://x:1  ", "", "   "))
        assertEquals(listOf(Terracotta.HMCL_CUSTOM_NODE, "tcp://x:1"), nodes)
    }

    @Test
    fun extraNodesDropDuplicateOfCustomNode() {
        assertEquals(1, Terracotta.extraNodes(listOf(Terracotta.HMCL_CUSTOM_NODE)).size)
    }

    @Test
    fun kernelDefaultsDoNotContainTheRendezvousNode() {
        // 这正是必须显式传 extraNodes 的原因，见 d-157
        assertEquals(4, Terracotta.KERNEL_DEFAULT_NODES.size)
        assertFalse(Terracotta.KERNEL_DEFAULT_NODES.contains(Terracotta.HMCL_CUSTOM_NODE))
    }

    @Test
    fun stateLabelsCoverTheWholeMachine() {
        assertEquals("已启动房间", Terracotta.stateLabel("host-ok"))
        assertEquals("正在加入房间", Terracotta.stateLabel("guest-connecting"))
        assertEquals("联机内核已停止", Terracotta.stateLabel("fatal"))
    }

    @Test
    fun unknownStateFallsBackInsteadOfCrashing() {
        assertEquals("正在初始化联机核心", Terracotta.stateLabel("something-new"))
    }

    @Test
    fun exceptionTextsFollowKernelOrder() {
        assertTrue(Terracotta.exceptionText(0).contains("找不到房主"))
        assertTrue(Terracotta.exceptionText(4).contains("已退出游戏世界"))
        assertTrue(Terracotta.exceptionText(99).contains("未知错误 99"))
    }

    @Test
    fun difficultyTextsExistForEveryGrade() {
        assertEquals(4, Terracotta.DIFFICULTY.size)
        assertTrue(Terracotta.DIFFICULTY.getValue("EASIEST").contains("极好"))
    }

    @Test
    fun lookupCharMapsLookAlikes() {
        assertEquals(Terracotta.lookupChar('1'), Terracotta.lookupChar('I'))
        assertEquals(Terracotta.lookupChar('0'), Terracotta.lookupChar('O'))
        assertNull(Terracotta.lookupChar('-'))
    }

    @Test
    fun generatedRoomHasTheCanonicalShape() {
        val code = room(123_456_789L)
        assertEquals(Terracotta.ROOM_WIDTH, code.length)
        assertTrue(code.startsWith("U/"))
        assertEquals(listOf(6, 11, 16), code.mapIndexedNotNull { i, c -> i.takeIf { c == '-' } })
    }

    @Test
    fun parseRoomAcceptsWhatWeGenerate() {
        val code = room(987_654_321L)
        assertEquals(code, Terracotta.parseRoom(code))
    }

    @Test
    fun parseRoomIsCaseInsensitive() {
        val code = room(55_555L)
        assertEquals(code, Terracotta.parseRoom(code.lowercase()))
    }

    @Test
    fun parseRoomFindsCodeInsideChatText() {
        val code = room(4_242_424L)
        assertEquals(code, Terracotta.parseRoom("快进来：$code 等你"))
    }

    @Test
    fun parseRoomRejectsWrongChecksum() {
        val good = room(700L)
        // 最低位挪一格：种子恰好差 1 或 33，两个都不是 7 的倍数
        val bumped = Terracotta.ROOM_CHARS[(Terracotta.ROOM_CHARS.indexOf(good[2]) + 1) % 34]
        val broken = good.substring(0, 2) + bumped + good.substring(3)
        assertNull(Terracotta.parseRoom(broken))
    }

    @Test
    fun parseRoomRejectsMissingDashes() {
        val code = room(700L).replace("-", "X")
        assertNull(Terracotta.parseRoom(code))
    }

    @Test
    fun parseRoomRejectsShortText() {
        assertNull(Terracotta.parseRoom("U/1234"))
        assertNull(Terracotta.parseRoom(""))
    }

    @Test
    fun parseRoomRejectsMissingPrefix() {
        val code = room(700L).removePrefix("U/")
        assertNull(Terracotta.parseRoom("XX$code"))
    }

    @Test
    fun looksLikeRoomMatchesParse() {
        val code = room(31_337L)
        assertTrue(Terracotta.looksLikeRoom("房间 $code"))
        assertFalse(Terracotta.looksLikeRoom("房间 不是房间号"))
        assertNotNull(Terracotta.parseRoom(code))
    }

    @Test
    fun lobbyNameMatchesFakeServerMotd() {
        assertEquals("陶瓦联机大厅", Terracotta.LOBBY_NAME)
    }

    @Test
    fun pingHostHintNamesTheRealCause() {
        assertTrue(Terracotta.PING_HOST_HINT.contains("会合节点"))
        assertTrue(Terracotta.PING_HOST_HINT.contains("terracotta.glavo.site"))
    }
}
