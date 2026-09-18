package com.pymcl.mobile.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import net.burningtnt.terracotta.TerracottaAndroidAPI
import java.util.Locale

/**
 * 陶瓦联机的仓库层：把 TerracottaAndroidAPI 那套静态 JNI 调用包成协程友好的接口。
 *
 * 分工：判断与文案全在 TerracottaCore（纯逻辑、可单测），这里只负责
 * 「什么时候调内核、把什么喂进去、把返回的 JSON 交给 Core 翻译」。
 *
 * 编译前提：需要 :Terracotta 模块进构建（t-135）。在那之前本文件解析不到
 * net.burningtnt.terracotta，属预期内。
 */
object TerracottaRepo {
    @Volatile
    private var started = false

    @Volatile
    private var metadata: Metadata? = null

    @Volatile
    private var cachedNodes: List<String>? = null

    data class Metadata(
        val terracottaVersion: String,
        val compileTime: Long,
        val easyTierVersion: String,
    )

    /** 内核起没起来。没起来时所有 set* 都会被挡在外面，不让 JNI 抛 IllegalStateException。 */
    fun isStarted(): Boolean = started

    fun metadata(): Metadata? = metadata

    /**
     * 拉起 rust 后端。callback 由调用方给——VpnService 的实现和 manifest 权限归下一批，
     * 这里只负责把回调透传给内核。
     */
    suspend fun initialize(
        context: Context,
        callback: TerracottaAndroidAPI.VpnServiceCallback,
    ): Metadata = withContext(Dispatchers.IO) {
        val meta = TerracottaAndroidAPI.initialize(context.applicationContext, callback)
        val wrapped = Metadata(
            terracottaVersion = meta.terracottaVersion,
            compileTime = meta.terracottaCompileTime,
            easyTierVersion = meta.easyTierVersion,
        )
        metadata = wrapped
        started = true
        wrapped
    }

    // ---------------------------------------------------------------- 节点表

    /**
     * 算出要交给内核的 extraNodes。
     *
     * 共识 d-157：这份表必须含 HMCL_CUSTOM_NODE，两端会合节点对不齐就打不通洞。
     * 远端表拉不到不是错误，降级用内置表继续走。
     *
     * @param extra 调用方额外配置的节点，对应桌面 CONFIG["terracotta_extra_nodes"]。
     * @param force 忽略缓存重新拉一次。
     */
    suspend fun nodes(extra: List<String> = emptyList(), force: Boolean = false): List<String> =
        withContext(Dispatchers.IO) {
            if (!force) cachedNodes?.let { return@withContext it }
            val remote = try {
                Http.getText(TerracottaCore.NODE_LIST_URL)
            } catch (e: Exception) {
                null
            }
            val listed = sendableNodes(remote, isChinaMainland(), extra)
            cachedNodes = listed
            listed
        }

    /**
     * 算出**真正交给内核**的那一份节点表，并把它记下来。
     *
     * 单独抽出来是为了让 d-157 那条约束可验证：`setScanning` / `setGuesting` 收到的
     * 就是这个函数的返回值，而它是纯的、能离线断言首位必须是 HMCL_CUSTOM_NODE。
     * 之前只能测 [TerracottaCore.publicNodes] 这个工厂，证不到调用点。
     */
    internal fun sendableNodes(remote: String?, mainland: Boolean, extra: List<String>): List<String> {
        val listed = TerracottaCore.publicNodes(remote, mainland, extra)
        lastSent = listed
        return listed
    }

    @Volatile
    private var lastSent: List<String> = emptyList()

    /** 上一次递给内核的节点表。联机页直接把它摆出来，打不通时第一眼能看见首位是谁。 */
    fun lastSentNodes(): List<String> = lastSent

    /** 对应桌面 _is_china_mainland()：本启动器默认按中国大陆处理。 */
    fun isChinaMainland(): Boolean {
        val locale = Locale.getDefault()
        if (locale.country.equals("CN", true)) return true
        return locale.language.equals("zh", true)
    }

    // ---------------------------------------------------------------- 房间号

    /** 不碰内核的格式预检，输入框边打边校验用这个。 */
    fun normalizeRoom(code: String?): String? = TerracottaCore.parseRoom(code)

    fun roomError(code: String?): String = TerracottaCore.roomError(code)

    /**
     * 让内核判房间号类型。只有 SCAFFOLDING 能用——0.4.2 已经移除另外两种，
     * 内核实际也只编进了 scaffolding，这里把 null 和理论上的旧格式都翻成人话。
     *
     * @return null 表示可用；非 null 是要展示给用户的错误。
     */
    fun checkRoom(code: String?): String? {
        val raw = code?.trim().orEmpty()
        if (raw.isEmpty()) return TerracottaCore.roomError(raw)
        if (!started) {
            // 内核没起来就退回纯格式校验，至少能挡住明显打错的
            return if (TerracottaCore.parseRoom(raw) != null) null else TerracottaCore.roomError(raw)
        }
        return when (TerracottaAndroidAPI.parseRoomCode(raw)) {
            TerracottaAndroidAPI.RoomType.SCAFFOLDING -> null
            null -> TerracottaCore.roomError(raw)
            else -> TerracottaCore.roomError(raw)
        }
    }

    // ---------------------------------------------------------------- 状态

    suspend fun state(): TerracottaCore.Snapshot = withContext(Dispatchers.IO) {
        if (!started) return@withContext TerracottaCore.Snapshot("missing", TerracottaCore.STATE_LABEL.getValue("missing"))
        try {
            TerracottaCore.parseState(TerracottaAndroidAPI.getState())
        } catch (e: Exception) {
            TerracottaCore.fatal(e.message ?: e.toString())
        }
    }

    suspend fun setWaiting() = withContext(Dispatchers.IO) {
        require(started) { "陶瓦内核尚未初始化。" }
        TerracottaAndroidAPI.setWaiting()
    }

    /**
     * 开房：扫局域网世界并开一个房间。
     *
     * @param room 想沿用的房间号，传 null 让内核现生成一个。
     */
    suspend fun host(
        player: String? = null,
        room: String? = null,
        extra: List<String> = emptyList(),
    ) = withContext(Dispatchers.IO) {
        require(started) { "陶瓦内核尚未初始化。" }
        TerracottaAndroidAPI.setScanning(room?.trim()?.ifBlank { null }, player, nodes(extra))
    }

    /**
     * 加入房间。
     *
     * @return null 表示已受理；非 null 是要展示给用户的错误。
     */
    suspend fun join(
        room: String,
        player: String? = null,
        extra: List<String> = emptyList(),
    ): String? = withContext(Dispatchers.IO) {
        require(started) { "陶瓦内核尚未初始化。" }
        checkRoom(room)?.let { return@withContext it }
        val accepted = TerracottaAndroidAPI.setGuesting(room.trim(), player, nodes(extra))
        if (accepted) null else TerracottaCore.roomError(room)
    }

    /** 内核日志，排查打洞失败时给用户导出用。 */
    suspend fun collectLogs(limit: Int = 200_000): String = withContext(Dispatchers.IO) {
        if (!started) return@withContext ""
        try {
            TerracottaAndroidAPI.collectLogs().use { reader -> reader.readText().takeLast(limit) }
        } catch (e: Exception) {
            ""
        }
    }
}
