package com.pymcl.mobile

import com.pymcl.mobile.data.TerracottaCore
import com.pymcl.mobile.data.TerracottaRepo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * d-157 的取证。
 *
 * 跟 [TerracottaRoomTest] 里那三个不一样：那边测的是 `Terracotta.extraNodes()` 这个
 * 工厂函数，这边测的是 **`setScanning` / `setGuesting` 真正收到的那一份**——
 * `TerracottaRepo.sendableNodes` 就是那两个调用点里传进去的表达式，它算完顺手记进
 * `lastSentNodes()`，所以断言它等于断言递给内核的参数。
 */
class TerracottaWiringTest {
    private val remoteNodes = """
        [{"url":"https://etnode.example.com/cn1","region":"cn"},
         {"url":"https://etnode.example.com/us1","region":"us"},
         {"url":"https://etnode.example.com/any"},
         {"url":"not a url","region":"cn"},
         "garbage"]
    """.trimIndent()

    @Test
    fun theListHandedToTheKernelLeadsWithTheHmclNode() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, emptyList())
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, sent.first())
    }

    @Test
    fun itStillLeadsWhenTheRemoteListIsUnavailable() {
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, TerracottaRepo.sendableNodes(null, true, emptyList()).first())
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, TerracottaRepo.sendableNodes("", true, emptyList()).first())
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, TerracottaRepo.sendableNodes("<html>502</html>", true, emptyList()).first())
    }

    @Test
    fun itStillLeadsWhenTheUserConfiguredTheirOwnNodes() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, listOf("tcp://mine.example.com:11010"))
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, sent.first())
        assertTrue(sent.contains("tcp://mine.example.com:11010"))
    }

    @Test
    fun itStillLeadsOutsideMainland() {
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, TerracottaRepo.sendableNodes(remoteNodes, false, emptyList()).first())
    }

    @Test
    fun theUserCannotPushItOutOfFirstPlaceByRepeatingIt() {
        val sent = TerracottaRepo.sendableNodes(null, true, listOf(TerracottaCore.HMCL_CUSTOM_NODE))
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, sent.first())
        assertEquals(1, sent.count { it == TerracottaCore.HMCL_CUSTOM_NODE })
    }

    @Test
    fun theKernelBuiltInsAreCarriedAlongToo() {
        val sent = TerracottaRepo.sendableNodes(null, true, emptyList())
        TerracottaCore.KERNEL_DEFAULT_NODES.forEach { assertTrue(it, sent.contains(it)) }
    }

    @Test
    fun theKernelBuiltInsAloneWouldNotContainIt() {
        // 这就是必须显式传 extraNodes 的理由：内核自带的 4 条里没有会合节点
        assertFalse(TerracottaCore.KERNEL_DEFAULT_NODES.contains(TerracottaCore.HMCL_CUSTOM_NODE))
    }

    @Test
    fun mainlandFilteringKeepsCnAndRegionlessOnly() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, emptyList())
        assertTrue(sent.contains("https://etnode.example.com/cn1"))
        assertTrue(sent.contains("https://etnode.example.com/any"))
        assertFalse(sent.contains("https://etnode.example.com/us1"))
    }

    @Test
    fun outsideMainlandFlipsTheRegionFilter() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, false, emptyList())
        assertTrue(sent.contains("https://etnode.example.com/us1"))
        assertFalse(sent.contains("https://etnode.example.com/cn1"))
    }

    @Test
    fun malformedRowsAreDroppedRatherThanSentOn() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, emptyList())
        assertFalse(sent.contains("not a url"))
        assertFalse(sent.contains("garbage"))
    }

    @Test
    fun everyEntryIsAUsableUrl() {
        TerracottaRepo.sendableNodes(remoteNodes, true, listOf(" ", "://bad")).forEach {
            assertTrue(it, TerracottaCore.validNodeUrl(it))
        }
    }

    @Test
    fun thereAreNoDuplicates() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, TerracottaCore.KERNEL_DEFAULT_NODES)
        assertEquals(sent.size, sent.toSet().size)
    }

    @Test
    fun whatWeRecordIsWhatWeReturn() {
        val sent = TerracottaRepo.sendableNodes(remoteNodes, true, listOf("tcp://mine:1"))
        assertEquals(sent, TerracottaRepo.lastSentNodes())
    }

    @Test
    fun theRecordedListSurvivesForTheUiToShow() {
        TerracottaRepo.sendableNodes(null, true, emptyList())
        assertEquals(TerracottaCore.HMCL_CUSTOM_NODE, TerracottaRepo.lastSentNodes().first())
    }

    // ---- 状态机与文案：Qt multiplayer_page 的每一档都得有落处 ----------------

    @Test
    fun everyStateFromTheKernelHasALabel() {
        listOf(
            "missing", "unsupported", "installing", "launching", "unknown", "waiting",
            "host-scanning", "host-starting", "host-ok",
            "guest-connecting", "guest-starting", "guest-ok",
            "exception", "fatal",
        ).forEach { assertTrue(it, TerracottaCore.STATE_LABEL.containsKey(it)) }
    }

    @Test
    fun parseStateSurvivesGarbage() {
        // 坏响应降级成 unknown 而不是抛：轮询每 1.2s 一次，抛一次就会把整个轮询打断
        listOf("not json", null, "", "{}").forEach { body ->
            val snap = TerracottaCore.parseState(body)
            assertEquals("unknown", snap.state)
            assertEquals(TerracottaCore.STATE_LABEL.getValue("unknown"), snap.label)
        }
    }

    @Test
    fun parseStateReadsRoomAndProfiles() {
        val snap = TerracottaCore.parseState(
            """{"state":"host-ok","room":"U/0000-0000-0000-0000","difficulty":"EASIEST",
                "profiles":[{"name":"Steve","vendor":"HMCL","kind":"guest"}]}""",
        )
        assertEquals("host-ok", snap.state)
        assertEquals("U/0000-0000-0000-0000", snap.room)
        assertEquals(1, snap.profiles.size)
        assertEquals("Steve", snap.profiles.first().name)
        assertTrue(snap.difficultyHint.contains("极好"))
    }

    @Test
    fun theLobbyNameMatchesTheFakeServerMotd() {
        assertEquals(TerracottaCore.LOBBY_NAME, com.pymcl.mobile.data.Terracotta.LOBBY_NAME)
    }
}
