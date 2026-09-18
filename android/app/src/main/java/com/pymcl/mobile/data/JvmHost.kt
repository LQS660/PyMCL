package com.pymcl.mobile.data

import android.content.Context
import com.tungsten.fclauncher.FCLConfig
import com.tungsten.fclauncher.FCLauncher
import com.tungsten.fclauncher.bridge.FCLBridge
import com.tungsten.fclauncher.bridge.FCLBridgeCallback
import com.tungsten.fclauncher.utils.FCLPath
import java.io.File
import java.util.ArrayDeque

/** 这次要跑的那个 JVM 是干什么的。日志文件名与标题都按它分。 */
enum class JvmJob(val title: String, val logName: String) {
    API_INSTALLER("安装器", "latest_api_installer.log"),
    JAR_EXECUTOR("Jar 运行", "latest_jar_executor.log"),
}

/** 宿主对外的一帧状态。Activity 只认这个，不直接碰 FCLBridge。 */
data class JvmRun(
    val job: JvmJob,
    val running: Boolean = false,
    val exitCode: Int? = null,
    val cancelled: Boolean = false,
    val lines: List<String> = emptyList(),
) {
    val finished: Boolean get() = exitCode != null || cancelled
}

/**
 * 加载器安装器 / Jar 执行器的 JVM 宿主。
 *
 * `FCLauncher.launchMinecraft` 那条路已经有 `GameActivity` 在跑了，
 * 另外两个入口（`launchJarExecutor` / `launchAPIInstaller`）同样需要一个
 * 「能挂日志、能等退出码」的宿主——这个文件就是那一半的非 UI 部分。
 *
 * **这里不接任何具体安装逻辑**（Forge 怎么装是另一条活）。它只回答一件事：
 * 起一个 JVM、把它的输出实时喂出来、拿到退出码、中途能掐掉。
 */
object JvmHost {
    /** 日志最多留这么多行。安装器能刷出几万行，全留在内存里没意义也没人看。 */
    const val MAX_LINES = 600

    @Volatile
    private var bridge: FCLBridge? = null

    @Volatile
    private var current: JvmRun? = null

    private val buffer = ArrayDeque<String>(MAX_LINES)

    // ---------------------------------------------------------------- 纯逻辑
    /**
     * 日志环形缓冲：超出 [MAX_LINES] 就从头丢。
     * 摘成纯函数是为了能离线测——真跑一次 JVM 在这台机器上验不了。
     */
    fun appended(lines: List<String>, incoming: String, cap: Int = MAX_LINES): List<String> {
        // 内核一次可能吐好几行，按行切开再入队，否则一「行」里塞着十行没法滚动
        val fresh = incoming.split('\n').filter { it.isNotBlank() }
        if (fresh.isEmpty()) return lines
        val merged = lines + fresh
        return if (merged.size <= cap) merged else merged.takeLast(cap)
    }

    /** 退出码 → 一句人话。安装器的 0 是成功，别的都得让用户看见原因。 */
    fun exitSummary(job: JvmJob, code: Int?, cancelled: Boolean): String = when {
        cancelled -> "${job.title}已取消"
        code == null -> "${job.title}进行中…"
        code == 0 -> "${job.title}完成"
        code == 1 -> "${job.title}失败：Java 抛了异常，看上面最后那段堆栈"
        code == 137 || code == -9 -> "${job.title}被系统杀掉了，多半是内存不够"
        else -> "${job.title}失败，退出码 $code"
    }

    fun succeeded(run: JvmRun): Boolean = run.exitCode == 0 && !run.cancelled

    /** 日志目录跟游戏那条路共用，方便用户一次把两份日志都发出来。 */
    fun logDir(context: Context): File =
        (context.getExternalFilesDir("logs") ?: File(context.filesDir, "logs")).also { it.mkdirs() }

    fun logFile(context: Context, job: JvmJob): File = File(logDir(context), job.logName)

    // ---------------------------------------------------------------- 真跑
    /**
     * 起一个 JVM。
     *
     * [args] 是完整的 java 命令行参数（`-cp`、主类、主类自己的参数都在里面），
     * 由调用方按具体安装器拼好——拼参数是那条活的事，不是宿主的事。
     *
     * 返回的 [FCLBridge] 还**没有** execute：JVM 要等 Activity 那边的 Surface
     * 就绪才能起（跟游戏那条路一样），所以真正的启动在 [attach] 里。
     */
    fun prepare(
        context: Context,
        job: JvmJob,
        args: List<String>,
        workingDir: File,
        jreDirName: String = "jre17",
    ): JvmRun {
        FCLPath.loadPaths(context.applicationContext)
        val javaHome = when (jreDirName) {
            "jre8" -> FCLPath.JAVA_8_PATH
            "jre21" -> FCLPath.JAVA_21_PATH
            "jre25" -> FCLPath.JAVA_25_PATH
            else -> FCLPath.JAVA_17_PATH
        }
        val config = FCLConfig(
            context,
            logDir(context).absolutePath,
            javaHome,
            workingDir.absolutePath,
            // 安装器是无头的，用不上渲染器；但 FCLConfig 这一格不可空，
            // 只好给跟游戏那条路同一个 GL4ES——它只是被记进环境变量，不会真去开窗
            headlessRenderer(),
            args.toTypedArray(),
        )
        val created = when (job) {
            JvmJob.API_INSTALLER -> FCLauncher.launchAPIInstaller(config)
            JvmJob.JAR_EXECUTOR -> FCLauncher.launchJarExecutor(config)
        }
        created.setJava(jreDirName)
        synchronized(this) {
            buffer.clear()
            bridge = created
            current = JvmRun(job = job, running = false)
        }
        return current!!
    }

    /**
     * Surface 就绪后把 JVM 真正拉起来。[onUpdate] 每来一行日志或退出时回调一次。
     *
     * 回调发生在内核线程上，调用方自己切回主线程——这里不替它切，
     * 免得把一个 Handler 的生命周期藏进这个 object 里。
     */
    fun attach(surface: android.view.Surface, onUpdate: (JvmRun) -> Unit) {
        val b = bridge ?: throw IllegalStateException("还没有 prepare")
        val job = current?.job ?: JvmJob.API_INSTALLER
        current = current?.copy(running = true)
        onUpdate(current!!)
        b.execute(
            surface,
            object : FCLBridgeCallback {
                override fun onCursorModeChange(mode: Int) = Unit

                override fun onLog(log: String) {
                    val next = synchronized(this@JvmHost) {
                        val merged = appended(buffer.toList(), log)
                        buffer.clear()
                        buffer.addAll(merged)
                        current = current?.copy(lines = merged) ?: JvmRun(job, true, lines = merged)
                        current!!
                    }
                    onUpdate(next)
                }

                override fun onExit(code: Int) {
                    val next = synchronized(this@JvmHost) {
                        current = current?.copy(running = false, exitCode = code)
                            ?: JvmRun(job, false, exitCode = code)
                        current!!
                    }
                    onUpdate(next)
                }
            },
        )
    }

    /**
     * 掐掉。
     *
     * FCLBridge 没有「优雅停止」这一档，只能打断它那个线程；
     * 所以这里把 `cancelled` 标上，界面据此说「已取消」而不是「失败，退出码 -1」——
     * 用户自己点的取消不该长得像一次崩溃。
     */
    fun cancel(): JvmRun? {
        val b = bridge ?: return current
        runCatching { b.thread?.interrupt() }
        synchronized(this) {
            current = current?.copy(running = false, cancelled = true)
        }
        return current
    }

    private fun headlessRenderer(): com.mio.data.Renderer = com.mio.data.Renderer(
        "Holy-GL4ES",
        "GL4ES",
        "libgl4es_114.so",
        "libEGL.so",
        "",
        null,
        null,
        com.mio.data.Renderer.ID_GL4ES,
        "",
        "1.21.4",
    )

    fun snapshot(): JvmRun? = current

    fun reset() {
        synchronized(this) {
            bridge = null
            current = null
            buffer.clear()
        }
    }
}
