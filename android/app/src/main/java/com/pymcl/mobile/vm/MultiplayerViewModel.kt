package com.pymcl.mobile.vm

import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pymcl.mobile.data.TerracottaCore
import com.pymcl.mobile.data.TerracottaRepo
import com.pymcl.mobile.data.TerracottaVpnCoordinator
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 联机页的全局提示位。
 *
 * VpnCoordinator 的 Notice 从内核线程 / 计时器线程上打过来，这里统一切回主线程再写，
 * 界面重建也不会丢——它不跟着 Activity 走。
 */
object TerracottaNotices {
    private val main = Handler(Looper.getMainLooper())

    var last by mutableStateOf<String?>(null)
        private set

    fun push(message: String) {
        if (Looper.myLooper() === Looper.getMainLooper()) last = message else main.post { last = message }
    }

    fun clear() {
        if (Looper.myLooper() === Looper.getMainLooper()) last = null else main.post { last = null }
    }
}

/**
 * 联机页的状态持有与轮询。
 *
 * 单独一个 ViewModel，不往 AppViewModel 里塞——那边同事刚加了一批 AI 的状态，
 * 两拨人改同一个类容易互相盖掉。
 *
 * 决策与文案都不在这里：状态名、异常文案、房间号规则全走 [TerracottaCore]，
 * 真正调内核走 [TerracottaRepo]，VPN 授权走 [TerracottaVpnCoordinator]。
 */
class MultiplayerViewModel(app: Application) : AndroidViewModel(app) {

    /** 轮询间隔，与桌面 multiplayer_page.py 的 1200ms 对齐。 */
    private val pollIntervalMs = 1200L

    var snapshot by mutableStateOf(
        TerracottaCore.Snapshot("missing", TerracottaCore.STATE_LABEL.getValue("missing")),
    )
        private set

    /** 输入框里的原文，用户打什么就是什么。 */
    var roomInput by mutableStateOf("")
        private set

    /** 归一化后的房间号；为空说明现在这串还不是合法的 U/ 码。 */
    var normalizedRoom by mutableStateOf<String?>(null)
        private set

    /** 输入框下面那行提示。合法时给归一化结果，不合法时给 roomError 的话。 */
    var roomHint by mutableStateOf("")
        private set

    var busy by mutableStateOf(false)
        private set

    /** 内核版本横幅，排查「两端对不对得上」时有用。 */
    var kernelInfo by mutableStateOf<String?>(null)
        private set

    var fatal by mutableStateOf<String?>(null)
        private set

    private var pollJob: Job? = null

    val notice: String? get() = TerracottaNotices.last

    fun dismissNotice() = TerracottaNotices.clear()

    // ------------------------------------------------------------ 生命周期

    /** 联机页可见时调。内核只初始化一次，重复进页面不会重复拉起。 */
    fun onEnter() {
        startPolling()
        if (TerracottaRepo.isStarted()) {
            kernelInfo = describeKernel()
            return
        }
        viewModelScope.launch {
            busy = true
            try {
                val meta = TerracottaRepo.initialize(
                    getApplication(),
                    TerracottaVpnCoordinator.kernelCallback,
                )
                kernelInfo = "陶瓦 ${meta.terracottaVersion} · EasyTier ${meta.easyTierVersion}"
                fatal = null
                TerracottaRepo.setWaiting()
            } catch (e: Exception) {
                fatal = e.message ?: e.toString()
            } finally {
                busy = false
            }
            // 刻意放在 finally 外面：协程被取消时不该再发一次挂起调用
            refresh()
        }
    }

    fun onLeave() {
        pollJob?.cancel()
        pollJob = null
    }

    override fun onCleared() {
        onLeave()
        super.onCleared()
    }

    private fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            while (isActive) {
                refresh()
                delay(pollIntervalMs)
            }
        }
    }

    private suspend fun refresh() {
        snapshot = TerracottaRepo.state()
    }

    private fun describeKernel(): String? {
        val meta = TerracottaRepo.metadata() ?: return null
        return "陶瓦 ${meta.terracottaVersion} · EasyTier ${meta.easyTierVersion}"
    }

    // ------------------------------------------------------------ 房间号输入

    /**
     * 边打边归一化。
     *
     * 交给 [TerracottaCore.parseRoom] 是因为它本来就是滑动窗口：整段话里夹着房间号
     * 也能捞出来，O/I 也会按上游规则换回 0/1。所以用户直接粘一句「房间号 U/xxx 快进」
     * 也认得。
     */
    fun onRoomInput(text: String) {
        roomInput = text
        val parsed = TerracottaCore.parseRoom(text)
        normalizedRoom = parsed
        roomHint = when {
            text.isBlank() -> ""
            parsed != null && parsed != text.trim().uppercase() -> "已识别为 $parsed"
            parsed != null -> ""
            else -> TerracottaCore.roomError(text)
        }
    }

    /** 用户点了「用识别到的房间号」，把输入框换成规范形式。 */
    fun applyNormalized() {
        normalizedRoom?.let { onRoomInput(it) }
    }

    // ------------------------------------------------------------ 三条路径

    fun host(player: String) {
        if (busy) return
        viewModelScope.launch {
            busy = true
            try {
                TerracottaRepo.host(player = player.ifBlank { null })
            } catch (e: Exception) {
                TerracottaNotices.push(e.message ?: "开房失败")
            } finally {
                busy = false
            }
            // 刻意放在 finally 外面：协程被取消时不该再发一次挂起调用
            refresh()
        }
    }

    fun join(player: String) {
        if (busy) return
        val room = normalizedRoom
        if (room == null) {
            TerracottaNotices.push(TerracottaCore.roomError(roomInput))
            return
        }
        viewModelScope.launch {
            busy = true
            try {
                TerracottaRepo.join(room, player.ifBlank { null })?.let { TerracottaNotices.push(it) }
            } catch (e: Exception) {
                TerracottaNotices.push(e.message ?: "加入房间失败")
            } finally {
                busy = false
            }
            // 刻意放在 finally 外面：协程被取消时不该再发一次挂起调用
            refresh()
        }
    }

    /** 断开：内核回到 waiting，VPN 那条隧道也收掉。 */
    fun disconnect() {
        if (busy) return
        viewModelScope.launch {
            busy = true
            try {
                TerracottaRepo.setWaiting()
                TerracottaVpnCoordinator.shutdown()
            } catch (e: Exception) {
                TerracottaNotices.push(e.message ?: "断开失败")
            } finally {
                busy = false
            }
            // 刻意放在 finally 外面：协程被取消时不该再发一次挂起调用
            refresh()
        }
    }

    /** 导出内核日志，打洞失败时让用户能把原文贴给我们。 */
    fun dumpLogs(onReady: (String) -> Unit) {
        viewModelScope.launch {
            onReady(runCatching { TerracottaRepo.collectLogs() }.getOrElse { it.message.orEmpty() })
        }
    }

    // ------------------------------------------------------------ 给界面的派生量

    /** 当前是不是已经开成 / 进成房间了，决定要不要显示「断开」。 */
    val connected: Boolean
        get() = snapshot.state in CONNECTED_STATES

    /** 正在建立中，这时候两个按钮都该灰掉。 */
    val working: Boolean
        get() = busy || snapshot.state in WORKING_STATES

    companion object {
        private val CONNECTED_STATES = setOf("host-ok", "guest-ok")
        private val WORKING_STATES = setOf(
            "installing", "launching", "host-scanning", "host-starting",
            "guest-connecting", "guest-starting",
        )
    }
}
