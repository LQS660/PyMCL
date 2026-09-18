package com.pymcl.mobile

import com.pymcl.mobile.data.TerracottaVpnGate
import com.pymcl.mobile.data.VpnDenyReason
import com.pymcl.mobile.data.VpnGateAction
import com.pymcl.mobile.data.VpnTimer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * VPN 授权状态机的单测。
 *
 * 不碰 Android、不碰 JNI，计时器是注入的假货——所以「25 秒超时」这条能在毫秒内验完，
 * 不用真等。
 */
class TerracottaVpnGateTest {

    /** 假计时器：只记下待执行的动作，由测试自己决定什么时候触发。 */
    private class FakeTimer : VpnTimer {
        var lastDelayMs: Long = -1
        var cancelled = false
        private var pending: (() -> Unit)? = null

        val armed: Boolean get() = pending != null

        override fun schedule(delayMs: Long, action: () -> Unit): VpnTimer.Handle {
            lastDelayMs = delayMs
            pending = action
            cancelled = false
            return VpnTimer.Handle {
                cancelled = true
                pending = null
            }
        }

        /** 让时间「走到点」。 */
        fun fire() {
            val action = pending
            pending = null
            action?.invoke()
        }
    }

    private class Recorder : (VpnGateAction) -> Unit {
        val actions = mutableListOf<VpnGateAction>()
        override fun invoke(action: VpnGateAction) {
            actions.add(action)
        }

        val last: VpnGateAction get() = actions.last()
        val lastReject: VpnGateAction.Reject get() = last as VpnGateAction.Reject
        val lastBusy: VpnGateAction.Busy get() = last as VpnGateAction.Busy
    }

    private fun gateWith(timer: FakeTimer, recorder: Recorder, timeoutMs: Long = 25_000L) =
        TerracottaVpnGate(timeoutMs = timeoutMs, timer = timer, onAction = recorder)

    // ------------------------------------------------------------ 超时兵底

    @Test
    fun timeoutAutomaticallyRejectsSoKernelIsNotStuck() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = true)
        assertEquals(VpnGateAction.AskConsent(token), rec.last)
        assertTrue("应该已经上了闹钟", timer.armed)
        assertEquals(25_000L, timer.lastDelayMs)

        timer.fire()

        val reject = rec.lastReject
        assertEquals(token, reject.token)
        assertEquals(VpnDenyReason.TIMED_OUT, reject.reason)
        assertTrue("超时提示不能是空的", reject.reason.message.isNotBlank())
        assertEquals(TerracottaVpnGate.Stage.SETTLED, gate.stage())
    }

    @Test
    fun timeoutStaysUnderTheKernelDeadline() {
        // 内核那边硬性 30 秒，留够余量给 reject 自己走完
        assertEquals(25_000L, TerracottaVpnGate.DEFAULT_TIMEOUT_MS)
        assertEquals(30_000L, TerracottaVpnGate.KERNEL_DEADLINE_MS)
        assertTrue(TerracottaVpnGate.DEFAULT_TIMEOUT_MS < TerracottaVpnGate.KERNEL_DEADLINE_MS)
    }

    @Test
    fun timeoutDoesNotEscapeEvenIfListenerThrows() {
        val timer = FakeTimer()
        val boom = TerracottaVpnGate(timeoutMs = 1_000L, timer = timer) {
            if (it is VpnGateAction.Reject) throw IllegalStateException("界面炸了")
        }
        boom.onKernelRequest(supported = true, needsConsent = true)
        // 兵底自己不能再炸一次，否则计时器线程直接没了
        timer.fire()
        assertEquals(TerracottaVpnGate.Stage.SETTLED, boom.stage())
    }

    @Test
    fun lateConsentAfterTimeoutIsIgnored() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = true)
        timer.fire()
        val countAfterTimeout = rec.actions.size

        // 用户过了一分钟才点「允许」，这时候再去建 TUN 只会撞上已经 reject 掉的请求
        gate.onConsentResult(token, granted = true)
        gate.onEstablished(token)
        assertEquals(countAfterTimeout, rec.actions.size)
    }

    // ------------------------------------------------------------ 三种失败情形

    @Test
    fun userDenialRejectsWithItsOwnMessage() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = true)
        gate.onConsentResult(token, granted = false)

        val reject = rec.lastReject
        assertEquals(VpnDenyReason.USER_DENIED, reject.reason)
        assertTrue("拒绝后闹钟要撤掉", timer.cancelled)
        assertFalse(timer.armed)
    }

    @Test
    fun unsupportedDeviceRejectsImmediatelyWithoutArmingTimer() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = false, needsConsent = false)

        val reject = rec.lastReject
        assertEquals(token, reject.token)
        assertEquals(VpnDenyReason.UNSUPPORTED, reject.reason)
        assertFalse("不支持就不必上闹钟", timer.armed)
        assertEquals(-1L, timer.lastDelayMs)
    }

    @Test
    fun duplicateRequestIsReportedWithoutTouchingTheLiveOne() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val first = gate.onKernelRequest(supported = true, needsConsent = true)
        val second = gate.onKernelRequest(supported = true, needsConsent = true)

        val busy = rec.lastBusy
        assertEquals(second, busy.token)
        assertEquals(VpnDenyReason.DUPLICATE, busy.reason)
        // 关键：不能是 Reject。内核同时只挂得住一个请求，reject 会把飞着的那个也打死
        assertTrue(rec.actions.none { it is VpnGateAction.Reject })
        assertEquals(first, gate.currentToken())
        assertEquals(TerracottaVpnGate.Stage.AWAITING_CONSENT, gate.stage())
        assertTrue("第一轮的闹钟不能被顶掉", timer.armed)
    }

    // ------------------------------------------------------------ 正常路径与其它分支

    @Test
    fun alreadyAuthorizedSkipsConsentAndGoesStraightToEstablish() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = false)

        assertEquals(VpnGateAction.Establish(token), rec.last)
        assertEquals(TerracottaVpnGate.Stage.ESTABLISHING, gate.stage())
        assertTrue("这一段同样要有超时保护", timer.armed)
    }

    @Test
    fun grantedConsentLeadsToEstablishThenReady() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = true)
        gate.onConsentResult(token, granted = true)
        assertEquals(VpnGateAction.Establish(token), rec.last)
        assertTrue("授权通过之后闹钟还得继续走，建 TUN 也可能卡住", timer.armed)

        gate.onEstablished(token)
        assertEquals(VpnGateAction.Ready(token), rec.last)
        assertTrue(timer.cancelled)
        assertEquals(TerracottaVpnGate.Stage.SETTLED, gate.stage())
    }

    @Test
    fun establishFailureRejects() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = false)
        gate.onEstablishFailed(token)

        assertEquals(VpnDenyReason.ESTABLISH_FAILED, rec.lastReject.reason)
        assertTrue(timer.cancelled)
    }

    @Test
    fun consentUnavailableKeepsTheTwoCasesApart() {
        val timer = FakeTimer()
        val noUi = Recorder()
        val gateA = gateWith(timer, noUi)
        val tokenA = gateA.onKernelRequest(supported = true, needsConsent = true)
        gateA.onConsentUnavailable(tokenA, VpnDenyReason.NO_UI)
        assertEquals(VpnDenyReason.NO_UI, noUi.lastReject.reason)

        val rom = Recorder()
        val gateB = gateWith(FakeTimer(), rom)
        val tokenB = gateB.onKernelRequest(supported = true, needsConsent = true)
        gateB.onConsentUnavailable(tokenB)
        assertEquals(VpnDenyReason.UNSUPPORTED, rom.lastReject.reason)
    }

    @Test
    fun staleTokensAreIgnored() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val token = gate.onKernelRequest(supported = true, needsConsent = true)
        val before = rec.actions.size
        gate.onConsentResult(token - 1, granted = true)
        gate.onEstablished(token + 99)
        gate.onEstablishFailed(0)
        assertEquals(before, rec.actions.size)
    }

    @Test
    fun resetAllowsANewRound() {
        val timer = FakeTimer()
        val rec = Recorder()
        val gate = gateWith(timer, rec)

        val first = gate.onKernelRequest(supported = true, needsConsent = true)
        gate.onConsentResult(first, granted = false)
        gate.reset()
        assertEquals(TerracottaVpnGate.Stage.IDLE, gate.stage())

        val second = gate.onKernelRequest(supported = true, needsConsent = true)
        assertTrue(second > first)
        assertEquals(VpnGateAction.AskConsent(second), rec.last)
    }

    // ------------------------------------------------------------ 文案

    @Test
    fun everyDenyReasonCarriesAScreenReadyChineseMessage() {
        assertEquals(6, VpnDenyReason.entries.size)
        VpnDenyReason.entries.forEach { reason ->
            assertNotNull(reason.message)
            assertTrue("${reason.name} 的文案是空的", reason.message.isNotBlank())
            assertTrue("${reason.name} 的文案里没有中文", reason.message.any { it.code in 0x4E00..0x9FFF })
        }
        // 这几条用户最常撞上，措辞必须点明下一步该干嘛
        assertTrue(VpnDenyReason.TIMED_OUT.message.contains("重试"))
        assertTrue(VpnDenyReason.USER_DENIED.message.contains("重试"))
        assertTrue(VpnDenyReason.ESTABLISH_FAILED.message.contains("重试"))
    }
}
