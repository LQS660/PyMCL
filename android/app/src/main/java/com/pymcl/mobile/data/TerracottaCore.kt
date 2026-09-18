package com.pymcl.mobile.data

import com.pymcl.mobile.model.ServerEntry
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.net.URI

/**
 * 陶瓦联机的纯逻辑层：节点表、房间号、状态与异常文案。
 *
 * 这里一行都不碰 net.burningtnt.terracotta，也不碰 Android framework，
 * 所以能在 JVM 单测里直接跑（见 TerracottaLogicTest）。
 * 需要真调内核的部分在 TerracottaRepo。
 *
 * 口径来自桌面 PyMCL 的 mclauncher/terracotta.py（陶瓦 0.4.2），
 * 已在 t-136 里逐条与上游 v0.4.2 src/controller/rooms/scaffolding/room.rs 对过。
 */
object TerracottaCore {
    /** 桌面 terracotta.py:31 钉的内核版本；安卓侧内核为 v0.4.2 + 6 个 commit（协议层同源）。 */
    const val VERSION_BASELINE = "0.4.2"

    const val HOME = "https://github.com/burningtnt/Terracotta"
    const val COPYRIGHT = "Terracotta | 陶瓦联机  © burningtnt  ·  基于 EasyTier"

    /** 多人游戏里双击这个名字进房，与官方 FakeServer MOTD 一致。 */
    const val LOBBY_NAME = "陶瓦联机大厅"

    // ---------------------------------------------------------------- 节点表

    const val NODE_LIST_URL = "https://terracotta.glavo.site/nodes"

    /**
     * HMCL 加入房间时额外带的会合节点，官方 /nodes 表里没有。
     *
     * 共识 d-157：两端的会合节点必须对齐，否则房间号再对也打不通洞，
     * 表现为 PingHostFail，看着像协议不兼容。任何情况下都必须出现在节点表里。
     */
    const val HMCL_CUSTOM_NODE = "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0"

    /**
     * 内核 publics.rs 自带的 4 条（安卓 libterracotta.so 里能搜到同样 4 条字符串）。
     *
     * 桌面 public_nodes() 并不重复传这 4 条，因为内核自己会加；这里仍然带上，
     * 一是任务书要求，二是远端表拉不到时保证降级结果不至于只剩一条。重复项内核会自行去重。
     */
    val KERNEL_DEFAULT_NODES: List<String> = listOf(
        "tcp://public.easytier.top:11010",
        "tcp://public2.easytier.cn:54321",
        "https://etnode.zkitefly.eu.org/node1",
        "https://etnode.zkitefly.eu.org/node2",
    )

    /** HMCL TerracottaNode.validate：能解析成带 scheme 与 authority 的 URI 才算数。 */
    fun validNodeUrl(url: String?): Boolean {
        val text = url?.trim().orEmpty()
        if (text.isEmpty()) return false
        return try {
            val uri = URI(text)
            !uri.scheme.isNullOrBlank() && !uri.authority.isNullOrBlank()
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 汇总要交给内核的 extraNodes。
     *
     * @param remoteJson NODE_LIST_URL 的响应正文；传 null 或垃圾串都按「远端不可用」处理，绝不抛。
     * @param mainland   是否按中国大陆过滤远端表，对应桌面 _is_china_mainland()。
     * @param extra      调用方额外配置的节点，对应桌面 CONFIG["terracotta_extra_nodes"]。
     */
    fun publicNodes(
        remoteJson: String? = null,
        mainland: Boolean = true,
        extra: List<String> = emptyList(),
    ): List<String> {
        val listed = LinkedHashSet<String>()

        fun add(url: String) {
            val text = url.trim()
            if (validNodeUrl(text)) listed.add(text)
        }

        add(HMCL_CUSTOM_NODE)
        for (url in extra) add(url)
        for (url in KERNEL_DEFAULT_NODES) add(url)
        for (url in parseNodeList(remoteJson, mainland)) add(url)

        return listed.toList()
    }

    /** 解析 /nodes 的响应。任何异常都吞掉返回空表——这是降级路径，不是错误路径。 */
    fun parseNodeList(remoteJson: String?, mainland: Boolean): List<String> {
        val body = remoteJson?.trim().orEmpty()
        if (body.isEmpty()) return emptyList()
        return try {
            val rows = JSONArray(body)
            val out = ArrayList<String>(rows.length())
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val url = row.optString("url").trim()
                if (!validNodeUrl(url)) continue
                val region = row.optString("region").trim()
                // region 为空 = 不限地区，照收；否则只收和本机地区一致的
                if (region.isNotEmpty() && mainland != region.equals("cn", true)) continue
                out.add(url)
            }
            out
        } catch (e: Exception) {
            emptyList()
        }
    }

    // ---------------------------------------------------------------- 房间号

    /** 上游 room.rs 的 CHARS：0-9A-Z 去掉容易认错的 I 和 O，共 34 个。 */
    const val ROOM_CHARS = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"

    private const val ROOM_TEMPLATE = "U/XXXX-XXXX-XXXX-XXXX"
    private const val ROOM_BODY = "XXXX-XXXX-XXXX-XXXX"
    private val THIRTY_FOUR: BigInteger = BigInteger.valueOf(34)
    private val SEVEN: BigInteger = BigInteger.valueOf(7)

    private fun lookupRoomChar(raw: Char): Int? {
        val char = when (raw) {
            'I' -> '1'
            'O' -> '0'
            else -> raw
        }
        val idx = ROOM_CHARS.indexOf(char)
        return if (idx >= 0) idx else null
    }

    /**
     * 上游 Room::from / scaffolding::parse：在文本里滑窗找 U/XXXX-XXXX-XXXX-XXXX，
     * 按 34 进制倒序累加，种子必须能被 7 整除。命中就返回规范化后的房间号。
     *
     * 种子上界是 34^16 ≈ 3.2e24，超出 Long，所以用 BigInteger（上游用的是 u128）。
     */
    fun parseRoom(text: String?): String? {
        val chars = text?.uppercase().orEmpty()
        if (chars.length < ROOM_TEMPLATE.length) return null
        for (start in 0..chars.length - ROOM_TEMPLATE.length) {
            val window = chars.substring(start, start + ROOM_TEMPLATE.length)
            if (window[0] != 'U' || window[1] != '/') continue
            val body = window.substring(2)
            var value = BigInteger.ZERO
            var ok = true
            for (i in ROOM_BODY.length - 1 downTo 0) {
                if (i == 4 || i == 9 || i == 14) {
                    if (body[i] != '-') {
                        ok = false
                        break
                    }
                    continue
                }
                val digit = lookupRoomChar(body[i])
                if (digit == null) {
                    ok = false
                    break
                }
                value = value.multiply(THIRTY_FOUR).add(BigInteger.valueOf(digit.toLong()))
            }
            if (ok && value.mod(SEVEN) == BigInteger.ZERO) return roomFromValue(value)
        }
        return null
    }

    /** 上游 from_value 的房间号那一支：34 进制正序展开，在第 4/8/12 位前插分隔符。 */
    fun roomFromValue(seed: BigInteger): String {
        val code = StringBuilder("U/")
        var value = seed
        for (i in 0 until 16) {
            val digit = value.mod(THIRTY_FOUR).toInt()
            value = value.divide(THIRTY_FOUR)
            if (i == 4 || i == 8 || i == 12) code.append('-')
            code.append(ROOM_CHARS[digit])
        }
        return code.toString()
    }

    /** v0.3.14 的 TerracottaLegacy 格式，0.4.2 已移除；只用来把错误话说明白。 */
    fun looksLikeLegacyRoom(text: String?): Boolean {
        val chars = text?.uppercase().orEmpty()
        if (chars.length < 29) return false
        for (start in 0..chars.length - 29) {
            val seg = chars.substring(start, start + 29)
            val array = ArrayList<Int>(25)
            var good = true
            outer@ for (i in 0 until 5) {
                for (j in 0 until 5) {
                    val v = lookupRoomChar(seg[i * 6 + j])
                    if (v == null) {
                        good = false
                        break@outer
                    }
                    array.add(v)
                }
                if (i != 4 && seg[i * 6 + 5] != '-') {
                    good = false
                    break@outer
                }
            }
            if (!good || array.size != 25) continue
            var checking = 0
            for (i in 0 until 24) checking = (checking + array[i]) % 34
            if (checking == array[24]) return true
        }
        return false
    }

    /** v0.3.14 的 PCL2CE 格式，0.4.2 已移除；同样只用于报错。 */
    fun looksLikePcl2ceRoom(text: String?): Boolean {
        val chars = text?.trim()?.uppercase().orEmpty()
        if (chars.isEmpty() || chars.length > 10) return false
        var value = 0L
        for (char in chars) {
            value = when (char) {
                in '2'..'9' -> value * 32 + (char - '2')
                in 'A'..'H' -> value * 32 + (char - 'A' + 8)
                in 'J'..'N' -> value * 32 + (char - 'J' + 16)
                in 'P'..'Z' -> value * 32 + (char - 'P' + 21)
                else -> return false
            }
        }
        if (value >= 999_999_999_965_536L) return false
        val digits = value.toString().length
        if (digits == 14) return true
        if (digits == 15) return value % 100_000 < 65_536
        return false
    }

    /** 房间号不合法时给一句说得清的话，对齐桌面 room_error。 */
    fun roomError(text: String?): String {
        val raw = text?.trim().orEmpty()
        if (raw.isEmpty()) return "请输入房间号。"
        if (looksLikeLegacyRoom(raw)) {
            return "这是陶瓦旧版房间号。官方 0.4.2 已移除 TerracottaLegacy 格式，" +
                "请让房主用当前陶瓦 / HMCL 重新开房（房间号以 U/ 开头）。"
        }
        if (looksLikePcl2ceRoom(raw)) {
            return "这是 PCL CE 旧房间号。官方 0.4.2 已移除 PCL2CE 格式，" +
                "请双方都用当前陶瓦 / HMCL 开房，房间号形如 U/XXXX-XXXX-XXXX-XXXX。"
        }
        val upper = raw.uppercase()
        if (upper.contains("U/") || upper.startsWith("U")) {
            return "房间号校验失败。请向房主重新复制完整的 U/XXXX-XXXX-XXXX-XXXX。"
        }
        return "房间号须为陶瓦 0.4.2 格式 U/XXXX-XXXX-XXXX-XXXX。官方内核已不再接受旧版 PCL / 旧陶瓦房间号。"
    }

    // ---------------------------------------------------------------- 直连

    /** 直连地址解析结果。[error] 为空才能用，非空时是下面三个码之一。 */
    data class DirectTarget(val host: String, val port: Int, val error: String = "")

    const val DIRECT_EMPTY = "empty"
    const val DIRECT_LOOPBACK = "loopback"
    const val DIRECT_BAD_PORT = "bad_port"

    /** 本机地址不是「房主的公网地址」，与桌面 terracotta_direct_connect 挡的是同一批。 */
    private val LOOPBACK = setOf("127.0.0.1", "localhost", "::1", "0.0.0.0")

    /**
     * 解析用户敲进来的直连地址，口径同桌面 `split_join_url` + `terracotta_direct_connect`：
     * 地址里可以自带端口，端口单独填也行（填了以它为准），都不填按 25565。
     *
     * 地址本身的拆分交给 [Servers.splitAddress]——IPv6 要写成 `[fe80::1]:25565` 那一套
     * 规则那边已经钉过用例了，不在这里再实现一遍。
     */
    fun parseDirect(address: String?, port: String = ""): DirectTarget {
        val text = address?.trim().orEmpty().substringAfterLast("://")
        if (text.isEmpty()) return DirectTarget("", 0, DIRECT_EMPTY)
        val typed = port.trim()
        if (typed.isNotEmpty() && (typed.toIntOrNull() ?: 0) !in 1..65535) {
            return DirectTarget("", 0, DIRECT_BAD_PORT)
        }
        val (host, resolved) = Servers.splitAddress(text, typed.ifEmpty { null })
        if (host.isBlank()) return DirectTarget("", 0, DIRECT_EMPTY)
        if (host.lowercase() in LOOPBACK) return DirectTarget(host, resolved, DIRECT_LOOPBACK)
        return DirectTarget(host, resolved)
    }

    /**
     * 把直连地址摆成多人游戏列表里的「陶瓦联机大厅」那一行，对齐桌面 `write_lobby_server`：
     * 同名的、同地址的旧行都去掉，新行排最前。纯函数，落盘由调用方交给 [Servers.writeAll]。
     */
    fun withLobby(existing: List<ServerEntry>, host: String, port: Int): List<ServerEntry> {
        val head = ServerEntry(name = LOBBY_NAME, ip = host, port = port)
        val rest = existing.filterNot { it.name == LOBBY_NAME || (it.ip == host && it.port == port) }
        return (listOf(head) + rest).mapIndexed { i, row -> row.copy(index = i) }
    }

    // ---------------------------------------------------------------- 文案

    /**
     * 对齐桌面 _STATE_LABEL 的 14 个状态。
     *
     * 其中 missing / unsupported / installing / launching 是宿主自己的装载阶段，
     * 安卓走 JNI 没有下载内核这一步，但键保留，UI 复用同一张表就不必分叉。
     */
    val STATE_LABEL: Map<String, String> = linkedMapOf(
        "missing" to "未下载联机核心",
        "unsupported" to "当前系统架构暂不支持陶瓦联机",
        "installing" to "正在下载联机核心…",
        "launching" to "正在初始化联机核心",
        "unknown" to "正在初始化联机核心",
        "waiting" to "联机核心已就绪",
        "host-scanning" to "正在扫描局域网世界",
        "host-starting" to "正在启动房间",
        "host-ok" to "已启动房间",
        "guest-connecting" to "正在加入房间",
        "guest-starting" to "正在加入房间",
        "guest-ok" to "已加入房间",
        "exception" to "联机出错",
        "fatal" to "联机内核已停止",
    )

    /** 内核 ExceptionType 的枚举名，顺序与下面的文案一一对应（也就是内核给的 type 下标）。 */
    val EXCEPTION_KINDS: List<String> = listOf(
        "PingHostFail",
        "PingHostRst",
        "GuestEasytierCrash",
        "HostEasytierCrash",
        "PingServerRst",
        "ScaffoldingInvalidResponse",
    )

    /** 对齐桌面 _EXC 的 6 条，文案与 HMCL I18N_zh_CN.properties 一致。 */
    val EXCEPTIONS: List<String> = listOf(
        "加入房间失败：找不到房主。房间已关闭，或尚未连上公共中继",
        "房间连接断开：房间已关闭或网络不稳定",
        "加入房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
        "创建房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
        "房间已关闭：您已退出游戏世界，房间已自动关闭",
        "协议错误：房主发送了错误的响应数据，请向开发者反馈该问题",
    )

    val DIFFICULTY: Map<String, String> = linkedMapOf(
        "EASIEST" to "当前网络状态极好：稍等一下就成功！",
        "SIMPLE" to "当前网络状态较好：建立连接需要一段时间……",
        "MEDIUM" to "当前网络状态中等：已启用抗干扰备用线路，连接可能失败",
        "TOUGH" to "当前网络状态极差：已启用抗干扰备用线路，连接可能失败",
    )

    /** PingHostFail 时追加这一句：多半不是协议问题，是两端没用同一条会合节点。 */
    const val PING_HOST_HINT =
        "陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道。官方公共节点连不上时，必须和 HMCL 用同一条自定义会合节点。" +
            "请完全退出后重试；已带上本机 HMCL 成功加入时用的那条 terracotta.glavo.site 节点。"

    /**
     * 内核给的异常标识翻成中文。
     *
     * 桌面 HTTP 那边 type 是下标整数；安卓 JNI 这边的 JSON 尚未实测，可能给名字，
     * 所以两种都认，认不出来就回落到通用文案。
     */
    fun exceptionText(type: Any?): String {
        when (type) {
            null -> return STATE_LABEL.getValue("exception")
            is Number -> {
                val idx = type.toInt()
                return EXCEPTIONS.getOrNull(idx) ?: STATE_LABEL.getValue("exception")
            }
        }
        val text = type.toString().trim()
        if (text.isEmpty()) return STATE_LABEL.getValue("exception")
        text.toIntOrNull()?.let { return EXCEPTIONS.getOrNull(it) ?: STATE_LABEL.getValue("exception") }
        val named = EXCEPTION_KINDS.indexOfFirst { it.equals(text, true) }
        return if (named >= 0) EXCEPTIONS[named] else STATE_LABEL.getValue("exception")
    }

    // ---------------------------------------------------------------- 状态快照

    data class Profile(val name: String, val vendor: String, val kind: String)

    data class Snapshot(
        val state: String,
        val label: String,
        val index: Long = 0,
        val room: String = "",
        val url: String = "",
        val difficulty: String = "",
        val difficultyHint: String = "",
        val profiles: List<Profile> = emptyList(),
        val error: String = "",
        val errorHint: String = "",
        val raw: String = "",
    )

    fun unsupported(reason: String): Snapshot =
        Snapshot(state = "unsupported", label = STATE_LABEL.getValue("unsupported"), error = reason, raw = "")

    fun fatal(reason: String): Snapshot =
        Snapshot(state = "fatal", label = STATE_LABEL.getValue("fatal"), error = reason, raw = "")

    /**
     * 把 TerracottaAndroidAPI.getState() 的 JSON 翻成快照，字段口径照桌面 snapshot()。
     *
     * 故意写得宽容：多余的键忽略，缺的键给默认值，整串解析不了就当 unknown。
     * 安卓那边 getState 的确切 JSON 形状还没实测过（见交付说明），raw 原样留着好排查。
     */
    fun parseState(json: String?): Snapshot {
        val body = json?.trim().orEmpty()
        if (body.isEmpty()) return Snapshot("unknown", STATE_LABEL.getValue("unknown"))
        val data = try {
            JSONObject(body)
        } catch (e: Exception) {
            return Snapshot("unknown", STATE_LABEL.getValue("unknown"), raw = body)
        }

        val state = data.optString("state").ifBlank { "unknown" }
        val room = data.optString("room").ifBlank { data.optString("code") }
        val difficulty = data.optString("difficulty").uppercase()

        val profiles = ArrayList<Profile>()
        data.optJSONArray("profiles")?.let { rows ->
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                profiles.add(
                    Profile(
                        name = row.optString("name").ifBlank { "玩家" },
                        vendor = row.optString("vendor"),
                        kind = row.optString("kind"),
                    ),
                )
            }
        }

        var label = STATE_LABEL[state] ?: state
        var error = ""
        var errorHint = ""
        if (state == "exception") {
            val type = if (data.has("type")) data.opt("type") else data.opt("kind")
            error = exceptionText(type)
            label = error
            if (error == EXCEPTIONS[0]) errorHint = PING_HOST_HINT
        }

        return Snapshot(
            state = state,
            label = label,
            index = data.optLong("index", 0L),
            room = room,
            url = data.optString("url"),
            difficulty = difficulty,
            difficultyHint = DIFFICULTY[difficulty].orEmpty(),
            profiles = profiles,
            error = error,
            errorHint = errorHint,
            raw = body,
        )
    }
}
