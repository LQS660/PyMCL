package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket

/** 一次 ping 的结果。[online] 为 false 时只有 [error] 有意义。 */
data class ServerStatus(
    val online: Boolean = false,
    val motd: String = "",
    val version: String = "",
    val protocol: Int = 0,
    val players: Int = 0,
    val maxPlayers: Int = 0,
    val latencyMs: Long = -1,
    val favicon: String = "",
    val error: String = "",
)

/**
 * Minecraft 的 Server List Ping（SLP）。
 *
 * 协议本身很紧凑：所有包都是「VarInt 长度 + VarInt 包 id + 负载」，字符串是
 * 「VarInt 长度 + UTF-8」。握手说明要去 status 状态，然后一问一答拿 JSON，
 * 最后一个 ping/pong 量延迟。
 *
 * **编解码那一层是纯的**（[writeVarInt] / [readVarInt] / [parseStatus]），
 * 所以能在单测里拿一个本地 ServerSocket 假装成服务器，把整套握手真跑一遍，
 * 而不是照着协议文档再写一遍然后互相印证。
 */
object ServerPing {
    /** 握手里写 -1 表示「我还不知道用哪个协议版本」，任何服务端都接受。 */
    const val PROTOCOL_UNKNOWN = -1

    const val HANDSHAKE_PACKET = 0x00
    const val STATUS_PACKET = 0x00
    const val PING_PACKET = 0x01

    const val DEFAULT_TIMEOUT_MS = 4000

    // ------------------------------------------------------------ 编解码（纯）

    fun writeVarInt(out: OutputStream, value: Int) {
        var v = value
        while (true) {
            if (v and 0x7F.inv() == 0) {
                out.write(v)
                return
            }
            out.write((v and 0x7F) or 0x80)
            v = v ushr 7
        }
    }

    fun readVarInt(input: InputStream): Int {
        var result = 0
        var shift = 0
        while (true) {
            val b = input.read()
            if (b < 0) throw EOFException("读 VarInt 时连接断了")
            result = result or ((b and 0x7F) shl shift)
            if (b and 0x80 == 0) return result
            shift += 7
            // 5 字节是 VarInt 的上限，再长就是对端在乱发，别在这儿转到天荒地老
            if (shift >= 35) throw IllegalStateException("VarInt 过长")
        }
    }

    fun varIntBytes(value: Int): ByteArray {
        val buffer = java.io.ByteArrayOutputStream()
        writeVarInt(buffer, value)
        return buffer.toByteArray()
    }

    fun writeString(out: OutputStream, text: String) {
        val bytes = text.toByteArray(Charsets.UTF_8)
        writeVarInt(out, bytes.size)
        out.write(bytes)
    }

    fun readString(input: InputStream): String {
        val length = readVarInt(input)
        if (length < 0 || length > 1 shl 21) throw IllegalStateException("字符串长度不合理: $length")
        val bytes = ByteArray(length)
        DataInputStream(input).readFully(bytes)
        return String(bytes, Charsets.UTF_8)
    }

    /** 把一个包体套上「长度 + id」的壳。 */
    fun framePacket(packetId: Int, payload: ByteArray): ByteArray {
        val body = varIntBytes(packetId) + payload
        return varIntBytes(body.size) + body
    }

    fun handshakePayload(host: String, port: Int, protocol: Int = PROTOCOL_UNKNOWN): ByteArray {
        val buffer = java.io.ByteArrayOutputStream()
        writeVarInt(buffer, protocol)
        writeString(buffer, host)
        buffer.write((port ushr 8) and 0xFF)
        buffer.write(port and 0xFF)
        writeVarInt(buffer, 1) // next state = status
        return buffer.toByteArray()
    }

    /**
     * 解析 status 响应的 JSON。
     *
     * `description` 有三种写法，历史包袱：纯字符串、`{"text": "..."}`、
     * 以及带 `extra` 数组的富文本。三种都得认，只认一种会让一半服务器显示成空白。
     */
    fun parseStatus(json: String, latencyMs: Long = -1): ServerStatus {
        val root = runCatching { JSONObject(json) }.getOrNull()
            ?: return ServerStatus(error = "服务器返回的不是合法 JSON")
        val players = root.optJSONObject("players")
        val version = root.optJSONObject("version")
        return ServerStatus(
            online = true,
            motd = stripFormatting(describeMotd(root.opt("description"))),
            version = version?.optString("name").orEmpty(),
            protocol = version?.optInt("protocol") ?: 0,
            players = players?.optInt("online") ?: 0,
            maxPlayers = players?.optInt("max") ?: 0,
            latencyMs = latencyMs,
            favicon = root.optString("favicon"),
        )
    }

    internal fun describeMotd(node: Any?): String = when (node) {
        null -> ""
        is String -> node
        is JSONObject -> buildString {
            append(node.optString("text"))
            node.optJSONArray("extra")?.let { extra ->
                for (i in 0 until extra.length()) append(describeMotd(extra.opt(i)))
            }
        }
        else -> node.toString()
    }

    /** 去掉 §a 之类的颜色码，列表里显示不需要它们。 */
    fun stripFormatting(text: String): String = Regex("\u00a7.").replace(text, "").trim()

    // ------------------------------------------------------------ 真连

    /**
     * 连上去问一次。任何失败都转成 `online=false` 的 [ServerStatus]，**不抛**——
     * 服务器列表一次要 ping 十几个，一个连不上不该让整页崩掉。
     */
    fun ping(host: String, port: Int = 25565, timeoutMs: Int = DEFAULT_TIMEOUT_MS): ServerStatus {
        if (host.isBlank()) return ServerStatus(error = "地址是空的")
        val socket = Socket()
        return try {
            val startedAt = System.nanoTime()
            socket.soTimeout = timeoutMs
            socket.connect(InetSocketAddress(host, port), timeoutMs)
            val out = DataOutputStream(socket.getOutputStream().buffered())
            val input = DataInputStream(socket.getInputStream().buffered())

            out.write(framePacket(HANDSHAKE_PACKET, handshakePayload(host, port)))
            out.write(framePacket(STATUS_PACKET, ByteArray(0)))
            out.flush()

            readVarInt(input) // 包长，读完就丢：后面按字段读，不靠它定位
            val id = readVarInt(input)
            if (id != STATUS_PACKET) return ServerStatus(error = "服务器回了意料之外的包 $id")
            val json = readString(input)
            val latency = (System.nanoTime() - startedAt) / 1_000_000

            parseStatus(json, latency)
        } catch (e: Exception) {
            ServerStatus(error = friendly(e))
        } finally {
            runCatching { socket.close() }
        }
    }

    internal fun friendly(e: Exception): String = when (e) {
        is java.net.SocketTimeoutException -> "连接超时，服务器可能没开或者被墙"
        is java.net.UnknownHostException -> "域名解析不了"
        is java.net.ConnectException -> "连不上，端口没开"
        is EOFException -> "刚连上就被断开了，多半不是 Minecraft 服务器"
        else -> e.message ?: e.toString()
    }

    fun describe(status: ServerStatus): String = when {
        !status.online -> status.error.ifBlank { "离线" }
        else -> "${status.players}/${status.maxPlayers} 人 · ${status.latencyMs}ms · ${status.version}"
    }
}
