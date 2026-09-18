package com.pymcl.mobile

import com.pymcl.mobile.data.TerracottaCore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 陶瓦纯逻辑层的单测。
 *
 * 这里不碰 net.burningtnt.terracotta，也不联网——节点表那几条是把响应正文直接喂进去的，
 * 所以 :Terracotta 还没进构建时这组用例本身是自洽的。
 *
 * 房间号那几个 fixture 是拿桌面 mclauncher/terracotta.py 的 _room_from_value / parse_room
 * 现算出来的，不是手编的。
 */
class TerracottaLogicTest {

    // ------------------------------------------------------------ 节点表（共识 d-157）

    @Test
    fun nodesAlwaysCarryHmclCustomNode() {
        val remoteOk = """[{"url":"tcp://node-cn.example:11010","region":"cn"}]"""
        listOf(
            TerracottaCore.publicNodes(remoteOk, mainland = true),
            TerracottaCore.publicNodes(null),
            TerracottaCore.publicNodes(""),
            TerracottaCore.publicNodes("   "),
            TerracottaCore.publicNodes("这不是 JSON"),
            TerracottaCore.publicNodes("{}"),
            TerracottaCore.publicNodes("[]"),
            TerracottaCore.publicNodes("[1,2,3]"),
            TerracottaCore.publicNodes(remoteOk, mainland = false),
            TerracottaCore.publicNodes(null, mainland = false, extra = listOf("tcp://my.node:1234")),
        ).forEachIndexed { i, nodes ->
            assertTrue("第 $i 组少了 HMCL_CUSTOM_NODE", nodes.contains(TerracottaCore.HMCL_CUSTOM_NODE))
        }
    }

    @Test
    fun hmclCustomNodeComesFirst() {
        val nodes = TerracottaCore.publicNodes("""[{"url":"tcp://a.example:1","region":""}]""")
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, nodes.first())
    }

    @Test
    fun remoteFailureDegradesInsteadOfThrowing() {
        // 远端拉不到时调用方传 null；解析不了的正文也走同一条降级路径
        val degraded = TerracottaCore.publicNodes(null)
        assertTrue(degraded.contains(TerracottaCore.HMCL_CUSTOM_NODE))
        assertTrue(degraded.containsAll(TerracottaCore.KERNEL_DEFAULT_NODES))
        assertEquals(emptyList<String>(), TerracottaCore.parseNodeList("<html>502</html>", true))
        assertEquals(emptyList<String>(), TerracottaCore.parseNodeList(null, true))
    }

    @Test
    fun remoteRowsAreFilteredByRegionAndValidity() {
        val body = """
            [
              {"url":"tcp://cn.example:11010","region":"cn"},
              {"url":"tcp://global.example:11010","region":"us"},
              {"url":"tcp://anywhere.example:11010","region":""},
              {"url":"   ","region":"cn"},
              {"url":"not a url","region":"cn"},
              "垃圾行"
            ]
        """.trimIndent()

        val cn = TerracottaCore.parseNodeList(body, mainland = true)
        assertEquals(listOf("tcp://cn.example:11010", "tcp://anywhere.example:11010"), cn)

        val abroad = TerracottaCore.parseNodeList(body, mainland = false)
        assertEquals(listOf("tcp://global.example:11010", "tcp://anywhere.example:11010"), abroad)
    }

    @Test
    fun nodesAreDeduplicated() {
        val dup = TerracottaCore.publicNodes(
            """[{"url":"${TerracottaCore.KERNEL_DEFAULT_NODES[0]}","region":""}]""",
            extra = listOf(TerracottaCore.HMCL_CUSTOM_NODE),
        )
        assertEquals(dup.size, dup.distinct().size)
    }

    @Test
    fun nodeUrlValidation() {
        assertTrue(TerracottaCore.validNodeUrl("tcp://public.easytier.top:11010"))
        assertTrue(TerracottaCore.validNodeUrl("https://etnode.zkitefly.eu.org/node1"))
        assertFalse(TerracottaCore.validNodeUrl(""))
        assertFalse(TerracottaCore.validNodeUrl("   "))
        assertFalse(TerracottaCore.validNodeUrl(null))
        assertFalse(TerracottaCore.validNodeUrl("public.easytier.top:11010"))
    }

    // ------------------------------------------------------------ 房间号

    /** 下面这几个都是桌面 _room_from_value 生成、parse_room 回环验证过的真码。 */
    private val validRooms = listOf(
        "U/QUC4-7UMK-QDT7-L078",
        "U/KA23-YY7H-B2Y7-X8L5",
        "U/U11N-THCW-JUL9-0VEC",
        "U/5E5Z-D4QJ-M4G9-A3EW",
        "U/S0FE-2ULU-YTTS-8HJV",
    )

    @Test
    fun validRoomCodeRoundTrips() {
        validRooms.forEach { code ->
            assertEquals("$code 应原样通过", code, TerracottaCore.parseRoom(code))
        }
        // 小写、前后有字、夹在一句话里都得能捞出来（上游是滑动窗口）
        assertEquals(validRooms[0], TerracottaCore.parseRoom(validRooms[0].lowercase()))
        assertEquals(validRooms[0], TerracottaCore.parseRoom("房间号 ${validRooms[0]} 快进"))
        // I/O 按上游规则回退成 1/0
        assertEquals("U/QUC4-7UMK-QDT7-L078", TerracottaCore.parseRoom("U/QUC4-7UMK-QDT7-LO78"))
    }

    @Test
    fun invalidRoomCodeIsRejected() {
        // 种子不能被 7 整除
        assertNull(TerracottaCore.parseRoom("U/Z0A5-YSBB-RHVL-RMKT"))
        assertNull(TerracottaCore.parseRoom("U/0000-0000-0000-000I"))
        // 形状不对
        assertNull(TerracottaCore.parseRoom("hello"))
        assertNull(TerracottaCore.parseRoom("U/QUC4-7UMK-QDT7"))
        assertNull(TerracottaCore.parseRoom("X/QUC4-7UMK-QDT7-L078"))
        assertNull(TerracottaCore.parseRoom("U/QUC4_7UMK_QDT7_L078"))

        val err = TerracottaCore.roomError("hello")
        assertTrue(err.contains("U/XXXX-XXXX-XXXX-XXXX"))
    }

    @Test
    fun emptyRoomCodeIsRejected() {
        assertNull(TerracottaCore.parseRoom(null))
        assertNull(TerracottaCore.parseRoom(""))
        assertNull(TerracottaCore.parseRoom("    "))
        assertEquals("请输入房间号。", TerracottaCore.roomError(""))
        assertEquals("请输入房间号。", TerracottaCore.roomError("   "))
        assertEquals("请输入房间号。", TerracottaCore.roomError(null))
    }

    @Test
    fun roomErrorNamesTheRetiredFormats() {
        // 0.4.2 移除的两种旧格式要单独说清楚，不然用户只看到「校验失败」。
        // 这两个样本是按上游 v0.3.14 的校验规则现造的，桌面 looks_like_* 判定为真。
        val legacy = "UVUYC-BYWB6-UK952-RUA0Z-432CR"
        assertTrue(TerracottaCore.looksLikeLegacyRoom(legacy))
        assertNull(TerracottaCore.parseRoom(legacy))
        assertTrue(TerracottaCore.roomError(legacy).contains("TerracottaLegacy"))

        val pcl2ce = "36Y6MNA66W"
        assertTrue(TerracottaCore.looksLikePcl2ceRoom(pcl2ce))
        assertNull(TerracottaCore.parseRoom(pcl2ce))
        assertTrue(TerracottaCore.roomError(pcl2ce).contains("PCL2CE"))

        // 真码不该被误判成旧格式
        validRooms.forEach {
            assertFalse(TerracottaCore.looksLikeLegacyRoom(it))
            assertFalse(TerracottaCore.looksLikePcl2ceRoom(it))
        }
    }

    @Test
    fun roomAlphabetMatchesUpstream() {
        assertEquals("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ", TerracottaCore.ROOM_CHARS)
        assertEquals(34, TerracottaCore.ROOM_CHARS.length)
        assertFalse(TerracottaCore.ROOM_CHARS.contains('I'))
        assertFalse(TerracottaCore.ROOM_CHARS.contains('O'))
    }

    // ------------------------------------------------------------ 状态与异常文案

    @Test
    fun stateLabelCoversAllFourteenDesktopStates() {
        val expected = listOf(
            "missing", "unsupported", "installing", "launching", "unknown", "waiting",
            "host-scanning", "host-starting", "host-ok",
            "guest-connecting", "guest-starting", "guest-ok",
            "exception", "fatal",
        )
        assertEquals(14, expected.size)
        assertEquals(14, TerracottaCore.STATE_LABEL.size)
        expected.forEach { key ->
            assertNotNull("缺状态 $key", TerracottaCore.STATE_LABEL[key])
            assertTrue("状态 $key 的文案是空的", TerracottaCore.STATE_LABEL.getValue(key).isNotBlank())
        }
    }

    @Test
    fun exceptionTableHasSixEntriesInKernelOrder() {
        assertEquals(6, TerracottaCore.EXCEPTIONS.size)
        assertEquals(6, TerracottaCore.EXCEPTION_KINDS.size)
        assertEquals(
            listOf(
                "PingHostFail", "PingHostRst", "GuestEasytierCrash",
                "HostEasytierCrash", "PingServerRst", "ScaffoldingInvalidResponse",
            ),
            TerracottaCore.EXCEPTION_KINDS,
        )
    }

    @Test
    fun exceptionTextAcceptsIndexOrName() {
        assertEquals(TerracottaCore.EXCEPTIONS[0], TerracottaCore.exceptionText(0))
        assertEquals(TerracottaCore.EXCEPTIONS[5], TerracottaCore.exceptionText(5))
        assertEquals(TerracottaCore.EXCEPTIONS[3], TerracottaCore.exceptionText("3"))
        assertEquals(TerracottaCore.EXCEPTIONS[2], TerracottaCore.exceptionText("GuestEasytierCrash"))
        assertEquals(TerracottaCore.EXCEPTIONS[4], TerracottaCore.exceptionText("pingserverrst"))
        // 认不出来就回落，不能抛
        assertEquals("联机出错", TerracottaCore.exceptionText(null))
        assertEquals("联机出错", TerracottaCore.exceptionText(99))
        assertEquals("联机出错", TerracottaCore.exceptionText("NoSuchKind"))
    }

    @Test
    fun difficultyTableHasFourEntries() {
        assertEquals(4, TerracottaCore.DIFFICULTY.size)
        listOf("EASIEST", "SIMPLE", "MEDIUM", "TOUGH").forEach {
            assertTrue("缺难度 $it", TerracottaCore.DIFFICULTY.containsKey(it))
        }
    }

    // ------------------------------------------------------------ 状态 JSON

    @Test
    fun parseStateReadsRoomProfilesAndDifficulty() {
        val snap = TerracottaCore.parseState(
            """
            {"index":7,"state":"host-ok","room":"${validRooms[0]}","difficulty":"simple",
             "profiles":[{"name":"小明","vendor":"PyMCL","kind":"HOST"},{"vendor":"HMCL","kind":"GUEST"}]}
            """.trimIndent(),
        )
        assertEquals("host-ok", snap.state)
        assertEquals("已启动房间", snap.label)
        assertEquals(7L, snap.index)
        assertEquals(validRooms[0], snap.room)
        assertEquals("SIMPLE", snap.difficulty)
        assertEquals(TerracottaCore.DIFFICULTY.getValue("SIMPLE"), snap.difficultyHint)
        assertEquals(2, snap.profiles.size)
        assertEquals("小明", snap.profiles[0].name)
        assertEquals("玩家", snap.profiles[1].name)
    }

    @Test
    fun parseStateTranslatesExceptionAndAddsNodeHint() {
        val pingHostFail = TerracottaCore.parseState("""{"state":"exception","type":0}""")
        assertEquals(TerracottaCore.EXCEPTIONS[0], pingHostFail.error)
        assertEquals(pingHostFail.error, pingHostFail.label)
        // PingHostFail 十有八九是会合节点没对齐，要把这句提示带出去
        assertEquals(TerracottaCore.PING_HOST_HINT, pingHostFail.errorHint)

        val crash = TerracottaCore.parseState("""{"state":"exception","kind":"HostEasytierCrash"}""")
        assertEquals(TerracottaCore.EXCEPTIONS[3], crash.error)
        assertEquals("", crash.errorHint)
    }

    @Test
    fun parseStateSurvivesGarbage() {
        listOf(null, "", "   ", "not json", "[]").forEach { body ->
            val snap = TerracottaCore.parseState(body)
            assertEquals("unknown", snap.state)
            assertTrue(snap.label.isNotBlank())
        }
        // 键缺光了也得给个能显示的东西
        val empty = TerracottaCore.parseState("{}")
        assertEquals("unknown", empty.state)
        assertEquals("", empty.room)
        assertEquals(emptyList<TerracottaCore.Profile>(), empty.profiles)
    }
}
