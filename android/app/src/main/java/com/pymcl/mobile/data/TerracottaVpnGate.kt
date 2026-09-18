package com.pymcl.mobile.data

import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * VPN 授权流程的纯状态机。
 *
 * 这里一行 Android、一行 JNI 都不碰，所以能在 JVM 单测里直接跑完整条流程，
 * 包括超时——计时器是注入的，测试不用真等 25 秒。
 *
 * 为什么非要有超时：内核那边 VpnServiceRequest 必须在 **30 秒内**被
 * startVpnService 或 reject 掉，否则整个陶瓦内核卡死、之后再也发不出新请求
 * （TerracottaAndroidAPI.java L436-438 里那句 Log.wtf 就是这个）。
 * 用户盯着系统弹窗发呆、或者顺手切了后台，都会撞上。所以宁可自动 reject 让他重试，
 * 也不能把内核停在那儿。
 */

/** 授权没走通的原因。每一条都带一句可以直接显示给用户的中文。 */
enum class VpnDenyReason(val message: String) {
    USER_DENIED("你拒绝了 VPN 授权。陶瓦联机要靠它建虚拟网卡，没有就进不了房间；重试可以再授权一次。"),
    UNSUPPORTED("这台设备用不了 VPN（可能是定制系统关掉了这项能力），陶瓦联机暂时没法用。"),
    TIMED_OUT("VPN 授权等太久，已自动取消——联机内核不能一直等下去。请重试，并在系统弹窗出现时尽快点「允许」。"),
    DUPLICATE("上一次 VPN 授权还没结束，请先处理完系统弹窗再试。"),
    ESTABLISH_FAILED("VPN 虚拟网卡没建起来，通常是被别的 VPN 应用占着。关掉其它 VPN 后重试。"),
    NO_UI("当前界面没接上授权入口，弹不出 VPN 授权框。请回到联机页再试一次。"),
}

/** 状态机要外界替它做的事。token 用来对齐一轮请求，迟到的回调按 token 丢掉。 */
sealed interface VpnGateAction {
    val token: Long

    /** 需要拉系统那张 VPN 授权弹窗。Intent 在 coordinator 手上，这里只发信号。 */
    data class AskConsent(override val token: Long) : VpnGateAction

    /** 已经授权过了，去把 VpnService 拉起来并把 TUN 交回内核。 */
    data class Establish(override val token: Long) : VpnGateAction

    /** 这一轮走不通了，必须调 request.reject() 把内核放出来。 */
    data class Reject(override val token: Long, val reason: VpnDenyReason) : VpnGateAction

    /** TUN 已经交回内核，这一轮收工。 */
    data class Ready(override val token: Long) : VpnGateAction

    /**
     * 上一轮还在飞就又来了一次。
     *
     * 跟 Reject 的区别很重要：**不要动内核**。内核同一时刻只挂得住一个请求，
     * 这时候去 reject 会把正在飞的那一个也打死。只把 [reason] 显示出来就行。
     */
    data class Busy(override val token: Long, val reason: VpnDenyReason) : VpnGateAction
}

/** 可注入的计时器。生产用 [ScheduledVpnTimer]，单测用假的，不必真等。 */
interface VpnTimer {
    fun interface Handle {
        fun cancel()
    }

    fun schedule(delayMs: Long, action: () -> Unit): Handle
}

/** 生产实现：一条守护线程的 ScheduledExecutorService，纯 JVM，不依赖 Android。 */
class ScheduledVpnTimer(
    private val executor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "terracotta-vpn-timer").apply { isDaemon = true }
    },
) : VpnTimer {
    override fun schedule(delayMs: Long, action: () -> Unit): VpnTimer.Handle {
        val future = executor.schedule({ runCatching { action() } }, delayMs, TimeUnit.MILLISECONDS)
        return VpnTimer.Handle { future.cancel(false) }
    }
}

class TerracottaVpnGate(
    /** 兵底超时。内核给 30 秒，这里留 5 秒余量给 reject 本身走完。 */
    val timeoutMs: Long = DEFAULT_TIMEOUT_MS,
    private val timer: VpnTimer = ScheduledVpnTimer(),
    private val onAction: (VpnGateAction) -> Unit,
) {
    companion object {
        const val DEFAULT_TIMEOUT_MS = 25_000L

        /** 内核那边的硬上限，仅作参考，别把 timeoutMs 设到它以上。 */
        const val KERNEL_DEADLINE_MS = 30_000L
    }

    enum class Stage { IDLE, AWAITING_CONSENT, ESTABLISHING, SETTLED }

    private val lock = Any()
    private val seq = AtomicLong(0)

    private var stage: Stage = Stage.IDLE
    private var token: Long = 0
    private var handle: VpnTimer.Handle? = null

    fun stage(): Stage = synchronized(lock) { stage }

    fun currentToken(): Long = synchronized(lock) { token }

    /**
     * 内核发来了一次 VpnService 请求。
     *
     * @param supported    这台设备到底能不能起 VPN（coordinator 拿 VpnService.prepare 探过）。
     * @param needsConsent 还没授权过、需要拉系统弹窗。
     * @return 本轮 token，后面的回调都要带着它回来。
     */
    fun onKernelRequest(supported: Boolean, needsConsent: Boolean): Long {
        val next = seq.incrementAndGet()
        // 动作在锁里算好，回调放到锁外发——监听器里再调回本类不会自锁
        val action = synchronized(lock) {
            if (stage == Stage.AWAITING_CONSENT || stage == Stage.ESTABLISHING) {
                // 不碰内核，上一轮还在飞
                VpnGateAction.Busy(next, VpnDenyReason.DUPLICATE)
            } else {
                token = next
                if (!supported) {
                    stage = Stage.SETTLED
                    VpnGateAction.Reject(next, VpnDenyReason.UNSUPPORTED)
                } else {
                    stage = if (needsConsent) Stage.AWAITING_CONSENT else Stage.ESTABLISHING
                    armTimeout(next)
                    if (needsConsent) VpnGateAction.AskConsent(next) else VpnGateAction.Establish(next)
                }
            }
        }
        onAction(action)
        return next
    }

    /** 系统授权弹窗回来了。 */
    fun onConsentResult(token: Long, granted: Boolean) {
        val action = synchronized(lock) {
            if (!isLive(token) || stage != Stage.AWAITING_CONSENT) return
            if (granted) {
                stage = Stage.ESTABLISHING
                VpnGateAction.Establish(token)
            } else {
                settleLocked()
                VpnGateAction.Reject(token, VpnDenyReason.USER_DENIED)
            }
        }
        onAction(action)
    }

    /**
     * 弹窗根本拉不起来。
     *
     * @param reason [VpnDenyReason.NO_UI] = 当前没有界面能接这张卡；
     *   [VpnDenyReason.UNSUPPORTED] = ROM 里压根没有这个授权界面。两者给用户的话不一样，别混。
     */
    fun onConsentUnavailable(token: Long, reason: VpnDenyReason = VpnDenyReason.UNSUPPORTED) {
        val action = synchronized(lock) {
            if (!isLive(token)) return
            settleLocked()
            VpnGateAction.Reject(token, reason)
        }
        onAction(action)
    }

    /** TUN 建好并交回内核了。 */
    fun onEstablished(token: Long) {
        val action = synchronized(lock) {
            if (!isLive(token)) return
            settleLocked()
            VpnGateAction.Ready(token)
        }
        onAction(action)
    }

    /** VpnService.Builder.establish() 失败，或者 Service 压根没起来。 */
    fun onEstablishFailed(token: Long) {
        val action = synchronized(lock) {
            if (!isLive(token)) return
            settleLocked()
            VpnGateAction.Reject(token, VpnDenyReason.ESTABLISH_FAILED)
        }
        onAction(action)
    }

    /** 会话结束后归位，下一次请求才能重新开始。 */
    fun reset() {
        synchronized(lock) {
            handle?.cancel()
            handle = null
            stage = Stage.IDLE
            token = 0
        }
    }

    private fun armTimeout(forToken: Long) {
        handle?.cancel()
        handle = timer.schedule(timeoutMs) { fireTimeout(forToken) }
    }

    private fun fireTimeout(forToken: Long) {
        val action = synchronized(lock) {
            if (!isLive(forToken)) return
            settleLocked()
            VpnGateAction.Reject(forToken, VpnDenyReason.TIMED_OUT)
        }
        // 超时回调跑在计时器线程上，异常吞掉——这是兵底，它自己不能再炸一次
        runCatching { onAction(action) }
    }

    /** 这一轮还活着吗：token 对得上，且还没落定。 */
    private fun isLive(candidate: Long): Boolean =
        candidate == token && stage != Stage.IDLE && stage != Stage.SETTLED

    private fun settleLocked() {
        handle?.cancel()
        handle = null
        stage = Stage.SETTLED
    }
}
