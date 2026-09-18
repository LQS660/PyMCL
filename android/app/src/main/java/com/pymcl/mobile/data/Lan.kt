package com.pymcl.mobile.data

import java.net.Inet4Address
import java.net.NetworkInterface

/** 本机局域网地址，给「把 IP 发给好友」用；语义对齐桌面 `mclauncher/lan.py`。 */
object Lan {
    const val DEFAULT_PORT = 25565

    fun localIps(): List<String> {
        val found = mutableListOf<String>()
        runCatching {
            NetworkInterface.getNetworkInterfaces()?.toList().orEmpty().forEach { nif ->
                if (!nif.isUp || nif.isLoopback) return@forEach
                nif.inetAddresses.toList().forEach { addr ->
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        val ip = addr.hostAddress ?: return@forEach
                        if (ip !in found) found += ip
                    }
                }
            }
        }
        return found.ifEmpty { listOf("127.0.0.1") }
    }

    fun hint(port: Int = DEFAULT_PORT, ips: List<String> = localIps()): String {
        val lines = ips.joinToString("\n") { "$it:$port" }
        return "房主在游戏里「对局域网开放」后，把下面地址发给好友：\n$lines"
    }

    /**
     * 从游戏日志里抠出「对局域网开放」的端口。
     * 中英文两种 MOTD 都认：`Local game hosted on port 54321` / `本地游戏已在端口 54321 上开放`。
     */
    fun parseOpenPort(logLine: String): Int? {
        val m = Regex("""(?:port|端口)\D{0,4}(\d{2,5})""", RegexOption.IGNORE_CASE).find(logLine)
        val port = m?.groupValues?.get(1)?.toIntOrNull() ?: return null
        return if (port in 1..65535) port else null
    }

    /** `192.168.1.7:25565` → (host, port)；没写端口就补默认端口。 */
    fun splitAddress(text: String): Pair<String, Int> = Servers.splitAddress(text)
}
