package com.pymcl.mobile.data

import java.net.Inet4Address
import java.net.NetworkInterface

object Lan {
    fun localIps(): List<String> {
        val found = mutableListOf<String>()
        runCatching {
            NetworkInterface.getNetworkInterfaces()?.toList().orEmpty().forEach { nif ->
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

    fun hint(port: Int = 25565): String {
        val lines = localIps().joinToString("\n") { "$it:$port" }
        return "房主在游戏里对局域网开放后，把下面地址发给好友：\n$lines"
    }
}
