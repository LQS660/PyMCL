package com.pymcl.mobile

import com.pymcl.mobile.data.ServerPing
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * SLP 握手。
 *
 * 编解码那一层是纯的，直接测；**整套握手则在一个本地 ServerSocket 上真跑一遍**——
 * 照着协议文档再写一遍假服务端然后互相印证，只能证明我两次理解一致，证不了对。
 *
 * 纪律：只绑 127.0.0.1、端口交给系统分配、accept 带超时、每个用例结束时在
 * [tearDown] 里关掉。跑完不留任何还在监听的东西。
 */
class ServerPingTest {
    private var server: ServerSocket? = null
    private var worker: Thread? = null

    @After
    fun tearDown() {
        runCatching { server?.close() }
        worker?.join(2000)
        server = null
        worker = null
    }

    /** 起一个只回一次的假服务端。[respond] 收到握手后决定怎么答。 */
    private fun startFakeServer(respond: (DataInputStream, DataOutputStream) -> Unit): Int {
        val socket = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        socket.soTimeout = 5000
        server = socket
        val ready = CountDownLatch(1)
        worker = Thread {
            ready.countDown()
            runCatching {
                socket.accept().use { client: Socket ->
                    client.soTimeout = 5000
                    respond(DataInputStream(client.getInputStream()), DataOutputStream(client.getOutputStream()))
                }
            }
        }.also { it.isDaemon = true; it.start() }
        ready.await(2, TimeUnit.SECONDS)
        return socket.localPort
    }

    /** 读掉客户端发来的握手与 status 请求，然后回一段 JSON。 */
    private fun replyWith(json: String): (DataInputStream, DataOutputStream) -> Unit = { input, out ->
        ServerPing.readVarInt(input)
        ServerPing.readVarInt(input)
        ServerPing.readVarInt(input)
        ServerPing.readString(input)
        input.readUnsignedShort()
        ServerPing.readVarInt(input)
        ServerPing.readVarInt(input)
        ServerPing.readVarInt(input)

        val payload = ByteArrayOutputStream()
        ServerPing.writeString(payload, json)
        out.write(ServerPing.framePacket(ServerPing.STATUS_PACKET, payload.toByteArray()))
        out.flush()
    }

    private val sampleJson = """
        {"version":{"name":"1.20.1","protocol":763},
         "players":{"max":20,"online":3},
         "description":{"text":"§aHello ","extra":[{"text":"World"}]},
         "favicon":"data:image/png;base64,AAA"}
    """.trimIndent()

    // ---- VarInt 与字符串（纯） -------------------------------------------

    @Test
    fun varIntRoundTripsAcrossTheInterestingBoundaries() {
        listOf(0, 1, 127, 128, 255, 2097151, 2097152, Int.MAX_VALUE).forEach { value ->
            val bytes = ServerPing.varIntBytes(value)
            assertEquals(value.toString(), value, ServerPing.readVarInt(ByteArrayInputStream(bytes)))
        }
    }

    @Test
    fun varIntUsesTheExpectedByteCount() {
        assertEquals(1, ServerPing.varIntBytes(0).size)
        assertEquals(1, ServerPing.varIntBytes(127).size)
        assertEquals(2, ServerPing.varIntBytes(128).size)
        // 每字节装 7 位，所以 3 字节封顶 2^21-1；2^21 本身要第 4 个字节
        assertEquals(3, ServerPing.varIntBytes(2097151).size)
        assertEquals(4, ServerPing.varIntBytes(2097152).size)
    }

    @Test
    fun negativeVarIntTakesFiveBytes() {
        // 握手里写 -1 表示「协议版本未知」，必须能编出来也能读回去
        val bytes = ServerPing.varIntBytes(-1)
        assertEquals(5, bytes.size)
        assertEquals(-1, ServerPing.readVarInt(ByteArrayInputStream(bytes)))
    }

    @Test(expected = IllegalStateException::class)
    fun anOverlongVarIntIsRejectedRatherThanLoopingForever() {
        ServerPing.readVarInt(ByteArrayInputStream(ByteArray(10) { 0x80.toByte() }))
    }

    @Test(expected = java.io.EOFException::class)
    fun aTruncatedVarIntReportsEof() {
        ServerPing.readVarInt(ByteArrayInputStream(byteArrayOf(0x80.toByte())))
    }

    @Test
    fun stringsRoundTripIncludingNonAscii() {
        val buffer = ByteArrayOutputStream()
        ServerPing.writeString(buffer, "生存服 ⛏")
        assertEquals("生存服 ⛏", ServerPing.readString(ByteArrayInputStream(buffer.toByteArray())))
    }

    @Test
    fun framingPutsLengthThenIdThenPayload() {
        val framed = ServerPing.framePacket(0x00, byteArrayOf(1, 2, 3))
        val input = ByteArrayInputStream(framed)
        assertEquals(4, ServerPing.readVarInt(input))
        assertEquals(0, ServerPing.readVarInt(input))
        assertEquals(3, input.available())
    }

    @Test
    fun handshakeCarriesHostAndPort() {
        val payload = ServerPing.handshakePayload("mc.example.com", 25566)
        val input = ByteArrayInputStream(payload)
        assertEquals(ServerPing.PROTOCOL_UNKNOWN, ServerPing.readVarInt(input))
        assertEquals("mc.example.com", ServerPing.readString(input))
        assertEquals(25566, DataInputStream(input).readUnsignedShort())
        assertEquals(1, ServerPing.readVarInt(input))
    }

    // ---- 状态 JSON（纯） -------------------------------------------------

    @Test
    fun statusJsonIsFullyParsed() {
        val s = ServerPing.parseStatus(sampleJson, 42)
        assertTrue(s.online)
        assertEquals("1.20.1", s.version)
        assertEquals(763, s.protocol)
        assertEquals(3, s.players)
        assertEquals(20, s.maxPlayers)
        assertEquals(42L, s.latencyMs)
        assertTrue(s.favicon.startsWith("data:image/png"))
    }

    @Test
    fun motdHandlesAllThreeHistoricalShapes() {
        assertEquals("plain", ServerPing.parseStatus("""{"description":"plain"}""").motd)
        assertEquals("texty", ServerPing.parseStatus("""{"description":{"text":"texty"}}""").motd)
        assertEquals(
            "Hello World",
            ServerPing.parseStatus("""{"description":{"text":"Hello ","extra":[{"text":"World"}]}}""").motd,
        )
    }

    @Test
    fun colourCodesAreStrippedFromTheMotd() {
        assertEquals("Hello World", ServerPing.parseStatus(sampleJson).motd)
        assertEquals("abc", ServerPing.stripFormatting("§aa§lb§rc"))
    }

    @Test
    fun badJsonIsOfflineWithAReason() {
        val s = ServerPing.parseStatus("not json")
        assertFalse(s.online)
        assertTrue(s.error.contains("JSON"))
    }

    @Test
    fun missingSectionsDefaultToZeroRatherThanCrashing() {
        val s = ServerPing.parseStatus("{}")
        assertTrue(s.online)
        assertEquals(0, s.players)
        assertEquals("", s.version)
    }

    // ---- 真握手：本地 ServerSocket ---------------------------------------

    @Test
    fun aRealHandshakeAgainstALocalSocketSucceeds() {
        val port = startFakeServer(replyWith(sampleJson))
        val status = ServerPing.ping("127.0.0.1", port, timeoutMs = 3000)
        assertTrue(status.error, status.online)
        assertEquals(3, status.players)
        assertEquals(20, status.maxPlayers)
        assertEquals("1.20.1", status.version)
        assertEquals("Hello World", status.motd)
        assertTrue(status.latencyMs >= 0)
    }

    @Test
    fun theServerReallyReceivesAWellFormedHandshake() {
        var seenHost = ""
        var seenPort = 0
        var seenNextState = -1
        val port = startFakeServer { input, out ->
            ServerPing.readVarInt(input)
            ServerPing.readVarInt(input)
            ServerPing.readVarInt(input)
            seenHost = ServerPing.readString(input)
            seenPort = input.readUnsignedShort()
            seenNextState = ServerPing.readVarInt(input)
            ServerPing.readVarInt(input)
            ServerPing.readVarInt(input)
            val payload = ByteArrayOutputStream()
            ServerPing.writeString(payload, "{}")
            out.write(ServerPing.framePacket(ServerPing.STATUS_PACKET, payload.toByteArray()))
            out.flush()
        }
        ServerPing.ping("127.0.0.1", port, timeoutMs = 3000)
        assertEquals("127.0.0.1", seenHost)
        assertEquals(port, seenPort)
        assertEquals(1, seenNextState)
    }

    @Test
    fun aServerThatHangsUpImmediatelyIsReportedNotThrown() {
        val port = startFakeServer { _, _ -> /* 收到就闭嘴走人 */ }
        val status = ServerPing.ping("127.0.0.1", port, timeoutMs = 1500)
        assertFalse(status.online)
        assertTrue(status.error.isNotBlank())
    }

    @Test
    fun aServerThatAnswersWithTheWrongPacketIsReported() {
        val port = startFakeServer { input, out ->
            repeat(3) { ServerPing.readVarInt(input) }
            ServerPing.readString(input)
            input.readUnsignedShort()
            repeat(3) { ServerPing.readVarInt(input) }
            out.write(ServerPing.framePacket(0x7F, ByteArray(0)))
            out.flush()
        }
        val status = ServerPing.ping("127.0.0.1", port, timeoutMs = 1500)
        assertFalse(status.online)
        assertTrue(status.error.contains("意料之外"))
    }

    @Test
    fun aServerThatSendsGarbageJsonIsReported() {
        val port = startFakeServer(replyWith("<html>nope</html>"))
        val status = ServerPing.ping("127.0.0.1", port, timeoutMs = 1500)
        assertFalse(status.online)
        assertTrue(status.error.contains("JSON"))
    }

    @Test
    fun nothingListeningIsAClearMessage() {
        // 先占一个端口再放掉，拿到一个几乎肯定没人听的号
        val free = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { it.localPort }
        val status = ServerPing.ping("127.0.0.1", free, timeoutMs = 1000)
        assertFalse(status.online)
        assertTrue(status.error.isNotBlank())
    }

    @Test
    fun aBlankAddressNeverOpensASocket() {
        val status = ServerPing.ping("   ", 25565)
        assertFalse(status.online)
        assertTrue(status.error.contains("空"))
    }

    @Test
    fun describeReadsWellBothWays() {
        val port = startFakeServer(replyWith(sampleJson))
        val ok = ServerPing.ping("127.0.0.1", port, timeoutMs = 3000)
        assertTrue(ServerPing.describe(ok).contains("3/20 人"))
        assertEquals("离线", ServerPing.describe(com.pymcl.mobile.data.ServerStatus()))
    }
}
