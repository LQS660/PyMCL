package com.pymcl.mobile.data

import java.io.File

object GameRuntime {
    const val ENGINE = "PyMCL Runtime / FCLauncher JNI"

    /** 包里带的 JRE 大版本。 */
    val MAJORS = listOf(17, 21)

    fun installedMajor(): Int? = MAJORS.firstOrNull { RuntimeInstaller.ready(it) }

    fun installed(): String {
        val major = installedMajor() ?: return "未解压（点启动会自动装 JRE）"
        return "$ENGINE · JRE $major"
    }

    /**
     * 本次游玩的计时。启动链交棒给运行时的那一刻开，`GameActivity` 退出时收。
     *
     * 放在这里而不是 ViewModel 里，是因为收的那一端在另一个 Activity 上，
     * 而那时候承载 ViewModel 的 MainActivity 很可能已经被系统回收了。
     */
    @Volatile
    private var session: Playtime.Tracker? = null

    /** 本次运行的游戏工作目录。退出时要去它的 crash-reports 里取最新那份。 */
    @Volatile
    private var sessionGameDir: File? = null

    /** 崩溃归因出来的一键修复动作要按这两个定位 mods 目录与版本设置。 */
    @Volatile
    private var sessionInstance = ""

    @Volatile
    private var sessionVersion = ""

    @Synchronized
    fun beginSession(instance: String, version: String) {
        endSession()
        val instDir = Paths.instanceDir(instance)
        sessionGameDir = if (version.isBlank()) instDir else VersionSettings.gameDir(instDir, version)
        sessionInstance = instance
        sessionVersion = version
        session = Playtime.Tracker(Paths.root, instance, version).also { it.start() }
    }

    /** 返回本次游玩秒数；没在计时或时长为 0 时返回 0，不写盘。 */
    @Synchronized
    fun endSession(): Long {
        val seconds = session?.stop() ?: 0
        session = null
        return seconds
    }

    /**
     * 上一次非正常退出的归因结果。
     *
     * 跟计时器同样的理由放在这里：产生它的是 `GameActivity`，要看它的是启动页，
     * 而那两者之间隔着一次 Activity 销毁。为 null 表示上一次是好好退出的。
     */
    @Volatile
    var lastCrash: CrashReport? = null
        private set

    /**
     * 游戏退出时叫一次。退出码为 0 就顺手把上一次的归因清掉，别让旧红条挂着。
     *
     * 除了日志尾巴，还要把**最新那份 crash-report 全文**一起交上去：归因规则里
     * 「哪个方块 / 实体弄崩的」「是哪个 mod 的配置炸了」这一整档只认那份文本，
     * 只喂 latest.log 的话那些结论一条都出不来（opus-5-3 在 t-556 里点名要的）。
     */
    fun recordExit(exitCode: Int, log: String) {
        if (exitCode == 0) {
            lastCrash = null
            return
        }
        lastCrash = runCatching {
            CrashReporter.analyze(
                exitCode,
                log,
                crashReport = latestCrashReport(),
                instance = sessionInstance,
                version = sessionVersion,
            )
        }.getOrNull()
    }

    /** 只取最新一份，且只取末尾这么多——那份常有几百 KB，整份拼进去没意义。 */
    private const val CRASH_TAIL = 64 * 1024

    internal fun latestCrashReport(dir: File? = sessionGameDir): String {
        val gameDir = dir ?: return ""
        val newest = runCatching { Saves.listMedia(gameDir, "crash-reports", limit = 1) }
            .getOrDefault(emptyList())
            .firstOrNull()
            ?: return ""
        return runCatching { File(newest.path).readText().takeLast(CRASH_TAIL) }.getOrDefault("")
    }

    fun clearCrash() {
        lastCrash = null
    }
}
