package com.pymcl.mobile

import com.pymcl.mobile.data.JvmHost
import com.pymcl.mobile.data.JvmJob
import com.pymcl.mobile.data.JvmRun
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM 宿主里能离线测的那一半。
 *
 * 真起一个 JVM 这台机器上验不了（出不了 APK），所以把宿主拆成了
 * 「纯逻辑」与「碰内核」两段，这里钉的是前者：日志怎么攒、退出码怎么翻译、
 * 用户点的取消怎么跟真失败区分开。
 */
class JvmHostTest {
    @Test
    fun oneKernelCallbackCanCarryManyLines() {
        // 内核一次可能吐好几行，不切开的话一「行」里塞着十行，滚动和复制都不对
        val out = JvmHost.appended(emptyList(), "第一行\n第二行\n第三行")
        assertEquals(listOf("第一行", "第二行", "第三行"), out)
    }

    @Test
    fun blankChunksDoNotPushRealLinesOut() {
        val base = listOf("a", "b")
        assertEquals(base, JvmHost.appended(base, ""))
        assertEquals(base, JvmHost.appended(base, "\n\n   \n"))
    }

    @Test
    fun logRingDropsTheOldestNotTheNewest() {
        // 安装器能刷出几万行，留着最新的那 600 行才有用
        var lines = emptyList<String>()
        repeat(1000) { lines = JvmHost.appended(lines, "line $it", cap = 600) }
        assertEquals(600, lines.size)
        assertEquals("line 999", lines.last())
        assertEquals("line 400", lines.first())
    }

    @Test
    fun capIsRespectedEvenWhenOneChunkOverflowsIt() {
        val chunk = (1..50).joinToString("\n") { "l$it" }
        val lines = JvmHost.appended(emptyList(), chunk, cap = 10)
        assertEquals(10, lines.size)
        assertEquals("l50", lines.last())
    }

    @Test
    fun cancellingLooksLikeCancellingNotLikeCrashing() {
        // 用户自己点的取消不该长得像一次崩溃
        val cancelled = JvmHost.exitSummary(JvmJob.API_INSTALLER, null, cancelled = true)
        assertTrue(cancelled.contains("已取消"))
        assertFalse(cancelled.contains("失败"))
    }

    @Test
    fun exitCodesGetPlainLanguage() {
        assertTrue(JvmHost.exitSummary(JvmJob.API_INSTALLER, 0, false).contains("完成"))
        assertTrue(JvmHost.exitSummary(JvmJob.API_INSTALLER, 1, false).contains("堆栈"))
        assertTrue(JvmHost.exitSummary(JvmJob.API_INSTALLER, 137, false).contains("内存"))
        assertTrue(JvmHost.exitSummary(JvmJob.API_INSTALLER, 42, false).contains("42"))
        // 还在跑的时候不能说成功也不能说失败
        val running = JvmHost.exitSummary(JvmJob.JAR_EXECUTOR, null, false)
        assertTrue(running.contains("进行中"))
        assertTrue(running.contains("Jar 运行"))
    }

    @Test
    fun onlyACleanZeroCountsAsSuccess() {
        assertTrue(JvmHost.succeeded(JvmRun(JvmJob.API_INSTALLER, exitCode = 0)))
        assertFalse(JvmHost.succeeded(JvmRun(JvmJob.API_INSTALLER, exitCode = 1)))
        assertFalse(JvmHost.succeeded(JvmRun(JvmJob.API_INSTALLER)))
        // 取消时哪怕退出码碰巧是 0 也不算成功
        assertFalse(JvmHost.succeeded(JvmRun(JvmJob.API_INSTALLER, exitCode = 0, cancelled = true)))
    }

    @Test
    fun finishedCoversBothExitAndCancel() {
        assertFalse(JvmRun(JvmJob.API_INSTALLER, running = true).finished)
        assertTrue(JvmRun(JvmJob.API_INSTALLER, exitCode = 0).finished)
        assertTrue(JvmRun(JvmJob.API_INSTALLER, cancelled = true).finished)
    }

    @Test
    fun eachJobWritesItsOwnLogFile() {
        // 两种任务的日志不能混在一个文件里，否则用户发上来的那份对不上事
        assertEquals("latest_api_installer.log", JvmJob.API_INSTALLER.logName)
        assertEquals("latest_jar_executor.log", JvmJob.JAR_EXECUTOR.logName)
        assertTrue(JvmJob.entries.map { it.logName }.toSet().size == JvmJob.entries.size)
    }
}
