package com.pymcl.mobile.data

/**
 * 陶瓦公网直连里那几段不依赖界面、也不依赖内核的小逻辑，对齐桌面 `backend.terracotta_direct_connect`。
 *
 * 地址解析本身在 [TerracottaCore.parseDirect]，大厅那一行在 [TerracottaCore.withLobby]；
 * 这里只补一样：把 host/port 拼回启动计划认得的一串。
 */
object DirectConnect {
    /**
     * `host` + `port` → 递给 [LaunchPlanner.plan] 的 `server` 参数。
     * IPv6 要套方括号，否则 `fe80::1:25570` 会被当成一串没有端口的地址。
     */
    fun address(host: String, port: Int): String {
        val h = host.trim()
        val wrapped = if (h.contains(':') && !h.startsWith("[")) "[$h]" else h
        return if (port in 1..65535) "$wrapped:$port" else wrapped
    }

    /** 拼回去再解一遍应当原样回来，界面据此在按钮旁边预览「将连接到 …」。 */
    fun roundTrips(host: String, port: Int): Boolean {
        val parsed = TerracottaCore.parseDirect(address(host, port))
        return parsed.error.isEmpty() && parsed.host == host.trim() && parsed.port == port
    }
}
