package com.pymcl.mobile.data

import java.io.BufferedOutputStream
import java.io.File
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder

/**
 * 本地皮肤服务的**监听层**，故意写得很薄：收字节、拼成 [HttpRequest]、交给
 * [YggdrasilRoutes]、把 [HttpReply] 写回去。所有判断都在路由那一层，那一层有单测。
 *
 * - **只听 127.0.0.1**。这份服务只保证单机和本机自己看得见；联机要让别人也看到，
 *   服务端得挂同一个外置验证站，那不是启动器能代劳的。
 * - 端口取 0 让系统分配，避免跟别的东西撞。
 * - 用手写 socket 而不是 `com.sun.net.httpserver`：后者 Android 上没有。
 * - 不引第三方库。
 */
class SkinServer(
    val registry: SkinRegistry,
    private val keys: YggdrasilKeys,
) {
    @Volatile
    private var socket: ServerSocket? = null

    @Volatile
    private var boundPort: Int = 0

    private val routes = YggdrasilRoutes(registry, keys, port = { boundPort })

    val port: Int get() = boundPort

    val apiRoot: String get() = "http://$YGG_LOOPBACK:$boundPort"

    val isRunning: Boolean get() = socket?.isClosed == false

    /** 幂等：已经在跑就直接返回地址。起不来返回空串——**皮肤起不来不该影响开游戏**。 */
    @Synchronized
    fun ensureRunning(): String {
        if (isRunning) return apiRoot
        return runCatching {
            val server = ServerSocket(0, 50, InetAddress.getByName(YGG_LOOPBACK))
            socket = server
            boundPort = server.localPort
            Thread({ serveLoop(server) }, "pymcl-skinserver").apply { isDaemon = true }.start()
            apiRoot
        }.getOrElse { "" }
    }

    @Synchronized
    fun shutdown() {
        runCatching { socket?.close() }
        socket = null
        boundPort = 0
    }

    private fun serveLoop(server: ServerSocket) {
        while (!server.isClosed) {
            val client = runCatching { server.accept() }.getOrNull() ?: break
            // 客户端一局游戏里会打好几次，各开一条短线程最省事；
            // 单个连接出问题不能把整个服务带下去。
            Thread({ runCatching { serveOne(client) }; runCatching { client.close() } })
                .apply { isDaemon = true }
                .start()
        }
    }

    private fun serveOne(client: Socket) {
        client.soTimeout = 15_000
        val input = client.getInputStream()
        val request = readRequest(input) ?: return
        val reply = runCatching { routes.handle(request) }.getOrElse { HttpReply(500) }
        BufferedOutputStream(client.getOutputStream()).use { out ->
            val head = buildString {
                append("HTTP/1.1 ").append(reply.status).append(" ").append(reasonOf(reply.status)).append("\r\n")
                if (reply.body.isNotEmpty()) append("Content-Type: ").append(reply.contentType).append("\r\n")
                append("Content-Length: ").append(reply.body.size).append("\r\n")
                append("Connection: close\r\n\r\n")
            }
            out.write(head.toByteArray(Charsets.US_ASCII))
            if (reply.body.isNotEmpty() && request.method.uppercase() != "HEAD") out.write(reply.body)
            out.flush()
        }
    }

    companion object {
        /** 请求行 + 头再大也就几 KB；给个上限，免得被一条畸形连接撑爆内存。 */
        private const val MAX_HEAD = 16 * 1024
        private const val MAX_BODY = 1 * 1024 * 1024

        fun defaultKeyFile(root: File): File = File(SkinFile.dirIn(root), "yggdrasil_key.der")

        private fun reasonOf(status: Int): String = when (status) {
            200 -> "OK"
            204 -> "No Content"
            403 -> "Forbidden"
            404 -> "Not Found"
            405 -> "Method Not Allowed"
            else -> "Error"
        }

        /** 把请求行与查询串拆成 [HttpRequest]。解析失败返回 null，由调用方直接断开。 */
        fun parseRequestLine(line: String, body: String = ""): HttpRequest? {
            val parts = line.trim().split(' ')
            if (parts.size < 2) return null
            val target = parts[1]
            val query = target.substringAfter('?', "").split('&')
                .mapNotNull { pair ->
                    if (pair.isBlank()) return@mapNotNull null
                    decode(pair.substringBefore('=')) to decode(pair.substringAfter('=', ""))
                }.toMap()
            return HttpRequest(parts[0], decode(target.substringBefore('?')), query, body)
        }

        private fun decode(raw: String): String = runCatching { URLDecoder.decode(raw, "UTF-8") }.getOrDefault(raw)

        private fun readRequest(input: InputStream): HttpRequest? {
            val head = StringBuilder()
            var prev = -1
            while (head.length < MAX_HEAD) {
                val b = input.read()
                if (b < 0) break
                head.append(Char(b))
                if (prev == '\n'.code && b == '\n'.code) break
                if (b != '\r'.code) prev = b
            }
            val lines = head.toString().split("\r\n", "\n").filter { it.isNotBlank() }
            if (lines.isEmpty()) return null
            val contentLength = lines.drop(1)
                .firstOrNull { it.startsWith("content-length:", ignoreCase = true) }
                ?.substringAfter(':')?.trim()?.toIntOrNull()
            val length = (contentLength ?: 0).coerceIn(0, MAX_BODY)
            val body = if (length > 0) {
                val buf = ByteArray(length)
                var read = 0
                while (read < length) {
                    val n = input.read(buf, read, length - read)
                    if (n <= 0) break
                    read += n
                }
                String(buf, 0, read, Charsets.UTF_8)
            } else {
                ""
            }
            return parseRequestLine(lines[0], body)
        }
    }
}
