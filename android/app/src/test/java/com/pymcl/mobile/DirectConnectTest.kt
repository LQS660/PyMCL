package com.pymcl.mobile

import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.TerracottaCore
import com.pymcl.mobile.model.ServerEntry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 陶瓦公网直连：地址怎么解析、大厅那一行怎么落进服务器列表、
 * 以及 `--server/--port` 到底有没有跟着启动计划走出去。
 *
 * 口径来自桌面 `terracotta.split_join_url` + `backend.terracotta_direct_connect`。
 */
class DirectConnectTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-direct").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    // ------------------------------------------------------------ 地址

    @Test
    fun aBareAddressGetsTheDefaultPort() {
        val target = TerracottaCore.parseDirect("1.2.3.4")
        assertEquals("1.2.3.4", target.host)
        assertEquals(25565, target.port)
        assertEquals("", target.error)
    }

    @Test
    fun aPortInTheAddressIsUsedAndASeparatelyTypedOneWins() {
        assertEquals(25570, TerracottaCore.parseDirect("1.2.3.4:25570").port)
        assertEquals(25580, TerracottaCore.parseDirect("1.2.3.4:25570", "25580").port)
        assertEquals("1.2.3.4", TerracottaCore.parseDirect("1.2.3.4:25570", "25580").host)
    }

    @Test
    fun aSchemeInFrontIsStripped() {
        val target = TerracottaCore.parseDirect("tcp://mc.example.com:25566")
        assertEquals("mc.example.com", target.host)
        assertEquals(25566, target.port)
    }

    /** IPv6 要写成方括号形式才认得出端口，规则本身在 Servers.splitAddress 那边钉过。 */
    @Test
    fun bracketedIpv6KeepsItsHostAndPortApart() {
        val target = TerracottaCore.parseDirect("[fe80::1]:25570")
        assertEquals("fe80::1", target.host)
        assertEquals(25570, target.port)
        assertEquals("", target.error)
    }

    @Test
    fun anEmptyAddressIsRejected() {
        assertEquals(TerracottaCore.DIRECT_EMPTY, TerracottaCore.parseDirect("").error)
        assertEquals(TerracottaCore.DIRECT_EMPTY, TerracottaCore.parseDirect("   ").error)
        assertEquals(TerracottaCore.DIRECT_EMPTY, TerracottaCore.parseDirect(null).error)
    }

    /** 直连是连到房主那台机器上，填自己等于连了个寂寞——桌面挡的也是这一批。 */
    @Test
    fun localAddressesAreRejectedWithTheirOwnReason() {
        listOf("127.0.0.1", "localhost", "LocalHost:25565", "0.0.0.0").forEach { raw ->
            assertEquals(raw, TerracottaCore.DIRECT_LOOPBACK, TerracottaCore.parseDirect(raw).error)
        }
    }

    @Test
    fun aPortOutsideTheValidRangeIsItsOwnComplaint() {
        listOf("abc", "0", "70000", "-1").forEach { port ->
            assertEquals(port, TerracottaCore.DIRECT_BAD_PORT, TerracottaCore.parseDirect("1.2.3.4", port).error)
        }
    }

    // ------------------------------------------------------------ 大厅那一行

    @Test
    fun theLobbyRowGoesToTheTopAndOldCopiesAreDropped() {
        val existing = listOf(
            ServerEntry(TerracottaCore.LOBBY_NAME, "9.9.9.9", 25565, index = 0),
            ServerEntry("朋友的服", "1.2.3.4", 25570, index = 1),
            ServerEntry("另一个服", "5.6.7.8", 25565, index = 2),
        )
        val rows = TerracottaCore.withLobby(existing, "1.2.3.4", 25570)

        assertEquals(TerracottaCore.LOBBY_NAME, rows.first().name)
        assertEquals("1.2.3.4", rows.first().ip)
        assertEquals(25570, rows.first().port)
        // 旧的同名行和同地址的那一行都不该再留着
        assertEquals(listOf(TerracottaCore.LOBBY_NAME, "另一个服"), rows.map { it.name })
        assertEquals(listOf(0, 1), rows.map { it.index })
    }

    @Test
    fun aDifferentPortOnTheSameHostIsADifferentServer() {
        val existing = listOf(ServerEntry("朋友的服", "1.2.3.4", 25565, index = 0))
        val rows = TerracottaCore.withLobby(existing, "1.2.3.4", 25570)
        assertEquals(2, rows.size)
        assertEquals("朋友的服", rows[1].name)
    }

    // ------------------------------------------------------------ 启动计划

    private fun installVersion(id: String) {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText("""{"id":"$id","libraries":[]}""")
        File(inst, "versions/$id/$id.jar").writeText("jar")
    }

    @Test
    fun aDirectAddressTurnsIntoServerAndPortArguments() {
        installVersion("1.20.1")
        val plan = LaunchPlanner.plan("default", "1.20.1", "Player", 2048, inst, "1.2.3.4:25570")
        assertEquals(listOf("--server", "1.2.3.4", "--port", "25570"), plan.serverArgs)
    }

    @Test
    fun noAddressMeansNoExtraArguments() {
        installVersion("1.20.1")
        assertEquals(
            emptyList<String>(),
            LaunchPlanner.plan("default", "1.20.1", "Player", 2048, inst).serverArgs,
        )
    }

    /** 地址不合法时宁可当没填，也不要把一串垃圾原样递给游戏。 */
    @Test
    fun aRejectedAddressNeverReachesTheCommandLine() {
        installVersion("1.20.1")
        val plan = LaunchPlanner.plan("default", "1.20.1", "Player", 2048, inst, "localhost")
        assertTrue(plan.serverArgs.isEmpty())
    }
}
