package com.pymcl.mobile.data

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log
import net.burningtnt.terracotta.TerracottaAndroidAPI

/**
 * 把内核的 VpnService 请求、系统授权弹窗、[TerracottaVpnService] 三者串起来。
 *
 * 决策全在 [TerracottaVpnGate]（纯状态机、可单测）里，这里只做它吩咐的事：
 * 探一下要不要授权、把 Intent 递给界面、拉服务、把 TUN 交回内核、或者 reject 放内核走。
 *
 * **不依赖任何具体 Activity**：界面那边实现 [ConsentLauncher] / [Notice] 两个函数式接口
 * 挂进来就行，走 ActivityResultLauncher 还是老的 startActivityForResult 都随它。
 *
 * 编译前提：需要 :Terracotta 模块进构建（t-135）。在那之前本文件解析不到
 * net.burningtnt.terracotta，属预期内；纯逻辑那部分在 TerracottaVpnGate，不受影响。
 */
object TerracottaVpnCoordinator {
    private const val TAG = "TerracottaVpn"

    /** 界面把系统给的授权 Intent 拉起来。拉不起来（没 Activity、ROM 没这界面）返回 false。 */
    fun interface ConsentLauncher {
        fun launch(intent: Intent): Boolean
    }

    /** 往界面上顶一句话。Toast、SnackBar、状态条都行。 */
    fun interface Notice {
        fun show(message: String)
    }

    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var launcher: ConsentLauncher? = null

    @Volatile
    private var notice: Notice? = null

    @Volatile
    private var consentIntent: Intent? = null

    @Volatile
    private var lastDeny: VpnDenyReason? = null

    private val gate = TerracottaVpnGate(onAction = { action -> dispatch(action) })

    /**
     * 交给 [TerracottaRepo.initialize] 的那个回调。
     *
     * 内核在需要网卡时从它自己的线程上调进来，然后**阻塞等**我们 startVpnService 或 reject，
     * 上限 30 秒。所以这个方法里一步都不能久留，真正的等待交给 gate 的兵底超时。
     */
    val kernelCallback: TerracottaAndroidAPI.VpnServiceCallback =
        TerracottaAndroidAPI.VpnServiceCallback { onKernelRequest() }

    /** 进程起来时挂一次，给的是 applicationContext。 */
    fun attach(context: Context) {
        appContext = context.applicationContext
    }

    /** 界面可见时挂上去；[detachUi] 在界面走的时候摘掉，别让它攥着 Activity。 */
    fun attachUi(launcher: ConsentLauncher, notice: Notice? = null) {
        this.launcher = launcher
        this.notice = notice
    }

    fun detachUi() {
        launcher = null
        notice = null
    }

    /** 最近一次失败的原因，界面重建后想补一句提示可以读它。 */
    fun lastDenial(): VpnDenyReason? = lastDeny

    fun stage(): TerracottaVpnGate.Stage = gate.stage()

    // ------------------------------------------------------------ 内核侧入口

    private fun onKernelRequest() {
        lastDeny = null
        val ctx = appContext
        if (ctx == null) {
            Log.w(TAG, "内核要 VPN，但 coordinator 还没 attach")
            // 连 prepare 都做不了，直接把内核放走，别让它卡满 30 秒
            rejectKernel()
            surface(VpnDenyReason.NO_UI)
            return
        }
        // prepare() 返回 null = 已经授过权；返回 Intent = 要拉系统弹窗；抛异常 = 这机器没 VPN
        val prepared = runCatching { VpnService.prepare(ctx) }
        if (prepared.isFailure) {
            Log.w(TAG, "VpnService.prepare 失败，按不支持处理", prepared.exceptionOrNull())
            gate.onKernelRequest(supported = false, needsConsent = false)
            return
        }
        val intent = prepared.getOrNull()
        consentIntent = intent
        gate.onKernelRequest(supported = true, needsConsent = intent != null)
    }

    // ------------------------------------------------------------ 界面侧入口

    /**
     * 系统授权弹窗回来了。界面拿到 `RESULT_OK` 就传 true。
     *
     * 迟到的结果（比如已经超时自动 reject 过了）会被 gate 按 token 丢掉，不会误触发。
     */
    fun onConsentResult(granted: Boolean) {
        gate.onConsentResult(gate.currentToken(), granted)
    }

    // ------------------------------------------------------------ 服务侧入口

    /** [TerracottaVpnService] 被拉起来之后回调进来，这时才拿得到 Builder。 */
    fun onServiceStarted(service: TerracottaVpnService, token: Long) {
        val ok = runCatching {
            val request = TerracottaAndroidAPI.getPendingVpnServiceRequest()
            val pfd = request.startVpnService(service.newBuilder())
            service.retain(pfd)
            true
        }.getOrElse {
            Log.w(TAG, "建立 TUN 失败", it)
            false
        }
        if (ok) gate.onEstablished(token) else gate.onEstablishFailed(token)
    }

    fun onRevoked() {
        surface(VpnDenyReason.ESTABLISH_FAILED)
        gate.reset()
    }

    /** 退出联机时收尾。 */
    fun shutdown() {
        appContext?.let { TerracottaVpnService.stop(it) }
        gate.reset()
        consentIntent = null
    }

    // ------------------------------------------------------------ 状态机的手脚

    private fun dispatch(action: VpnGateAction) {
        when (action) {
            is VpnGateAction.AskConsent -> {
                val intent = consentIntent
                val ui = launcher
                when {
                    intent == null -> gate.onConsentUnavailable(action.token, VpnDenyReason.UNSUPPORTED)
                    ui == null -> gate.onConsentUnavailable(action.token, VpnDenyReason.NO_UI)
                    !runCatching { ui.launch(intent) }.getOrDefault(false) ->
                        gate.onConsentUnavailable(action.token, VpnDenyReason.UNSUPPORTED)
                }
            }

            is VpnGateAction.Establish -> {
                consentIntent = null
                val ctx = appContext
                if (ctx == null || !TerracottaVpnService.establish(ctx, action.token)) {
                    gate.onEstablishFailed(action.token)
                }
            }

            is VpnGateAction.Reject -> {
                consentIntent = null
                rejectKernel()
                surface(action.reason)
                gate.reset()
            }

            is VpnGateAction.Ready -> {
                consentIntent = null
                lastDeny = null
                gate.reset()
            }

            // 上一轮还在飞：只出个声，绝不碰内核——那会把正在飞的那个也打死
            is VpnGateAction.Busy -> surface(action.reason)
        }
    }

    /**
     * 把内核从等待里放出来。
     *
     * 没有挂起的请求时 getPendingVpnServiceRequest 会抛 IllegalStateException，
     * 那说明已经被别的路径处理过了，吞掉即可——这是兵底，它自己不能再炸一次。
     */
    private fun rejectKernel() {
        runCatching { TerracottaAndroidAPI.getPendingVpnServiceRequest().reject() }
            .onFailure { Log.d(TAG, "reject 时已无挂起请求：${it.message}") }
    }

    private fun surface(reason: VpnDenyReason) {
        lastDeny = reason
        runCatching { notice?.show(reason.message) }
    }
}
