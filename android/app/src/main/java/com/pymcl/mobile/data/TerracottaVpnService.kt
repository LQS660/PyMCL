package com.pymcl.mobile.data

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log

/**
 * 陶瓦联机的 VpnService 本体。
 *
 * 全限定名 **com.pymcl.mobile.data.TerracottaVpnService** 是跟 manifest 里
 * `<service android:permission="android.permission.BIND_VPN_SERVICE">` 那条约定死的，
 * 改名两边就对不上、服务起不来。
 *
 * 它自己不做决策——什么时候起、什么时候放弃，全在 [TerracottaVpnGate]（纯状态机）里。
 * 这里只干三件事：被拉起来时把自己交给 [TerracottaVpnCoordinator] 去建 TUN、
 * 攥住内核还回来的那个 fd、退出时关掉它。
 *
 * 那个 fd 必须由我们关：TerracottaAndroidAPI.VpnServiceRequest#startVpnService
 * 的文档写着 "Developers must close this file descriptor after EasyTier exits."
 */
class TerracottaVpnService : VpnService() {

    @Volatile
    private var connection: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            teardown("收到停止指令")
            stopSelf()
            return START_NOT_STICKY
        }
        val token = intent?.getLongExtra(EXTRA_TOKEN, 0L) ?: 0L
        // 建 TUN 要用 VpnService.Builder，而 Builder 是本服务的内部类，只能从这儿给出去
        TerracottaVpnCoordinator.onServiceStarted(this, token)
        // 不要 START_STICKY：内核重启后会自己重新发请求，系统替我们重拉反而拿不到 pending request
        return START_NOT_STICKY
    }

    /**
     * 造一个预置好会话名的 Builder 交出去。
     *
     * Builder 是 VpnService 的内部类，只能从服务实例里 new，所以这一步必须留在本类。
     * 地址、路由、DNS 不在这里填——内核的 VpnServiceRequest#startVpnService 会自己
     * addAddress / addDnsServer / addRoute 再 establish()，我们多填反而会跟它打架。
     */
    fun newBuilder(): Builder = Builder().setSession(SESSION_NAME)

    /** 建好的 TUN 交给服务保管，服务销毁时统一关闭。 */
    fun retain(pfd: ParcelFileDescriptor) {
        val previous = connection
        connection = pfd
        if (previous !== pfd) runCatching { previous?.close() }
    }

    /** 用户在系统设置里断掉了这条 VPN，或者别的 VPN 抢走了。 */
    override fun onRevoke() {
        teardown("VPN 已被系统或用户断开")
        TerracottaVpnCoordinator.onRevoked()
        stopSelf()
        super.onRevoke()
    }

    override fun onDestroy() {
        teardown("服务销毁")
        super.onDestroy()
    }

    private fun teardown(why: String) {
        val pfd = connection ?: return
        connection = null
        runCatching { pfd.close() }.onFailure { Log.w(TAG, "关闭 TUN 失败（$why）", it) }
    }

    companion object {
        private const val TAG = "TerracottaVpn"

        const val ACTION_ESTABLISH = "com.pymcl.mobile.action.TERRACOTTA_VPN_ESTABLISH"
        const val ACTION_STOP = "com.pymcl.mobile.action.TERRACOTTA_VPN_STOP"
        const val EXTRA_TOKEN = "terracotta_vpn_token"

        /** 系统 VPN 会话名，会显示在通知栏和系统设置里。 */
        const val SESSION_NAME = "陶瓦联机"

        /**
         * 拉起服务去建 TUN。
         *
         * 注意时机：Android 8 起后台起服务受限，**要在前台调**——正常路径上这一下
         * 紧跟在系统授权弹窗关闭之后，或者用户刚点了「开始联机」，都还在前台。
         * 起不来返回 false，调用方应当据此走 establishFailed。
         */
        fun establish(context: Context, token: Long): Boolean = runCatching {
            val intent = Intent(context, TerracottaVpnService::class.java)
                .setAction(ACTION_ESTABLISH)
                .putExtra(EXTRA_TOKEN, token)
            context.startService(intent) != null
        }.getOrElse {
            Log.w(TAG, "拉起 VpnService 失败", it)
            false
        }

        fun stop(context: Context) {
            runCatching {
                context.startService(
                    Intent(context, TerracottaVpnService::class.java).setAction(ACTION_STOP),
                )
            }
        }
    }
}
