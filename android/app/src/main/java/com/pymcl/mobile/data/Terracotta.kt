package com.pymcl.mobile.data

/**
 * 陶瓦联机的纯逻辑：房间号解析、状态文案、会合节点清单。
 *
 * 协议层与桌面 PyMCL 用的官方 v0.4.2 同源（见共识 d-157），所以房间号字母表、
 * 种子校验规则、状态机名字三处必须逐字一致，安卓和 Windows 才能进同一个房间。
 */
object Terracotta {
    /** 官方 Room 字母表：去掉了形近的 I 和 O，一共 34 个。 */
    const val ROOM_CHARS = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"

    const val ROOM_PREFIX = "U/"

    /** `U/XXXX-XXXX-XXXX-XXXX` 一共 21 个字符。 */
    const val ROOM_WIDTH = 21

    private const val BODY_WIDTH = ROOM_WIDTH - 2
    private val DASH_POSITIONS = setOf(4, 9, 14)

    /**
     * HMCL 进房间时额外传的自定义会合节点（官方 `/nodes` 里没有这一条）。
     *
     * **这一条不能少**：安卓内核内置的 4 条节点就是 [KERNEL_DEFAULT_NODES]，
     * 不含这条会合节点；两端不在同一条会合节点上就碰不上头，失败会报成
     * `PingHostFail`，看上去像协议不对，实际只是没碰上面。见 d-157。
     */
    const val HMCL_CUSTOM_NODE = "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0"

    /** 内核 `fetch_public_nodes` 兜底的 4 条，与桌面 KERNEL_DEFAULT_NODES 一致。 */
    val KERNEL_DEFAULT_NODES = listOf(
        "tcp://public.easytier.top:11010",
        "tcp://public2.easytier.cn:54321",
        "https://etnode.zkitefly.eu.org/node1",
        "https://etnode.zkitefly.eu.org/node2",
    )

    /**
     * 传给 `setScanning` / `setGuesting` 的 extraNodes。
     * [HMCL_CUSTOM_NODE] 永远排在第一位，用户自配的接在后面。
     */
    fun extraNodes(configured: List<String> = emptyList()): List<String> {
        val out = mutableListOf(HMCL_CUSTOM_NODE)
        configured.forEach { raw ->
            val url = raw.trim()
            if (url.isNotEmpty() && url !in out) out += url
        }
        return out
    }

    /** 状态机名字与桌面 `_STATE_LABEL` 同源，文案可以直接复用。 */
    val STATE_LABELS = mapOf(
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

    /** 与 HMCL I18N 陶瓦条目对齐，下标就是内核回的异常序号。 */
    val EXCEPTIONS = listOf(
        "加入房间失败：找不到房主。房间已关闭，或尚未连上公共中继",
        "房间连接断开：房间已关闭或网络不稳定",
        "加入房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
        "创建房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
        "房间已关闭：您已退出游戏世界，房间已自动关闭",
        "协议错误：房主发送了错误的响应数据，请向开发者反馈该问题",
    )

    val DIFFICULTY = mapOf(
        "EASIEST" to "当前网络状态极好：稍等一下就成功！",
        "SIMPLE" to "当前网络状态较好：建立连接需要一段时间……",
        "MEDIUM" to "当前网络状态中等：已启用抗干扰备用线路，连接可能失败",
        "TOUGH" to "当前网络状态极差：已启用抗干扰备用线路，连接可能失败",
    )

    /** 多人游戏列表里双击的那一行，与官方 FakeServer MOTD 一致。 */
    const val LOBBY_NAME = "陶瓦联机大厅"

    const val PING_HOST_HINT =
        "陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道。官方公共节点连不上时，必须和 HMCL 用同一条自定义会合节点。" +
            "请完全退出后重试；已带上本机 HMCL 成功加入时用的那条 terracotta.glavo.site 节点。"

    fun stateLabel(state: String): String = STATE_LABELS[state] ?: STATE_LABELS.getValue("unknown")

    fun exceptionText(code: Int): String =
        EXCEPTIONS.getOrElse(code) { "联机出错（未知错误 $code）" }

    /** I/O 在字母表里不存在，按官方实现当成 1/0。 */
    internal fun lookupChar(ch: Char): Int? {
        val c = when (ch) {
            'I' -> '1'
            'O' -> '0'
            else -> ch
        }
        val idx = ROOM_CHARS.indexOf(c)
        return if (idx >= 0) idx else null
    }

    /** 16 位 34 进制，低位在前。种子 34^16 远超 Long，所以全程只按位算、不还原成整数。 */
    private const val DIGITS = 16

    internal fun roomFromValue(value: Long): String {
        var v = value
        val digits = IntArray(DIGITS)
        for (i in 0 until DIGITS) {
            digits[i] = (v % 34).toInt()
            v /= 34
        }
        return format(digits)
    }

    internal fun format(digits: IntArray): String {
        val sb = StringBuilder(ROOM_PREFIX)
        for (i in 0 until DIGITS) {
            if (i == 4 || i == 8 || i == 12) sb.append('-')
            sb.append(ROOM_CHARS[digits[i]])
        }
        return sb.toString()
    }

    /**
     * 官方 `Room::from` / `scaffolding::parse`：在整段文字里滑窗找房间号，
     * 种子必须能被 7 整除。找不到返回 null——用户粘一整段聊天记录也能认出来。
     *
     * 返回的是规范形式：I/O 会被换回 1/0，大小写和分隔符一并归一。
     */
    fun parseRoom(text: String): String? {
        val chars = text.uppercase()
        if (chars.length < ROOM_WIDTH) return null
        val digits = IntArray(DIGITS)
        for (start in 0..(chars.length - ROOM_WIDTH)) {
            if (chars[start] != 'U' || chars[start + 1] != '/') continue
            val body = chars.substring(start + 2, start + ROOM_WIDTH)
            var slot = 0
            var ok = true
            for (i in 0 until BODY_WIDTH) {
                if (i in DASH_POSITIONS) {
                    if (body[i] != '-') {
                        ok = false
                        break
                    }
                    continue
                }
                val digit = lookupChar(body[i])
                if (digit == null) {
                    ok = false
                    break
                }
                digits[slot++] = digit
            }
            if (!ok || slot != DIGITS) continue
            // 从最高位做带模的 Horner，避免 34^16 溢出 Long
            var mod = 0
            for (i in DIGITS - 1 downTo 0) {
                mod = (mod * 34 + digits[i]) % 7
            }
            if (mod == 0) return format(digits)
        }
        return null
    }

    fun looksLikeRoom(text: String): Boolean = parseRoom(text) != null
}
