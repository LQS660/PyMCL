package com.pymcl.mobile.data

import java.io.File

data class CrashReport(
    val headline: String,
    val summary: String,
    val reason: String,
    val exitCode: Int,
    val excerpt: String,
    val help: String = "",
    /** 逐条归因，按确定度从高到低。空 = 没分析出原因。 */
    val advices: List<CrashAdvice> = emptyList(),
    /**
     * 归因的原始结构，[CrashActions] 据此排一键修复动作。
     *
     * [reason] 那串逗号拼出来的码够展示、不够做事——「怀疑哪个 Mod」「缺哪个大版本」
     * 全在 [CrashReason.extras] 里，拼成字符串就丢了。
     */
    val reasons: List<CrashReason> = emptyList(),
    /** 崩的是哪个实例 / 哪个版本，修复动作要按它定位 mods 目录与版本设置。 */
    val instance: String = "",
    val version: String = "",
) {
    /** 界面上那一整段「原因 + 建议」。没分析出来时返回空串，由调用方决定说什么。 */
    fun adviceText(): String = advices.joinToString("\n\n") { a ->
        if (a.detail.isBlank()) a.headline else "${a.headline}\n${a.detail}"
    }

    /** 还建议把日志发给人看吗。任何一条说要，就是要。 */
    val needHelp: Boolean get() = advices.isEmpty() || advices.any { it.needHelp }
}

/**
 * 崩溃捕获与日志摘取。对齐 `app/pages/crash_dialog.py` + `mclauncher/crash.py`。
 *
 * 这里只做「能离线判的那部分」：退出码解释、日志关键字归因、脱敏、摘录。
 * 真正的上报走 [FeedbackRepo.submitCrash]。
 */
object CrashReporter {
    /** 日志尾巴最多带这么多字符上报，再多后台也看不完，还容易超包体。 */
    const val MAX_EXCERPT = 6000

    /**
     * 令牌、会话 ID、正版 UUID 一律抹掉。
     *
     * 崩溃日志里 `--accessToken` 后面跟的就是能登进别人账号的那串东西，
     * 它跟着反馈发出去就是事故，所以脱敏放在组装之前而不是发送之前。
     */
    fun filterSecrets(text: String): String {
        var out = text
        out = Regex("""(--accessToken\s+)\S+""").replace(out, "$1<hidden>")
        out = Regex("""(--session\s+)\S+""").replace(out, "$1<hidden>")
        out = Regex("""(?i)("?access_?token"?\s*[:=]\s*"?)[A-Za-z0-9._\-]{16,}""")
            .replace(out, "$1<hidden>")
        out = Regex("""(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}""").replace(out, "$1<hidden>")
        out = Regex("""(?i)("?uuid"?\s*[:=]\s*"?)[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}""")
            .replace(out, "$1<hidden>")
        return out
    }

    /** 退出码解释，跟桌面 `crash.exit_hint` 同一套说法。 */
    fun exitHint(code: Int): String = when (code) {
        0 -> "正常退出"
        1 -> "游戏自己抛了异常退出，看日志最后那段堆栈"
        -1, 255 -> "进程被强行结束"
        137, -9 -> "被系统杀掉了，多半是内存给少了"
        139, -11 -> "原生层崩溃（段错误），常见于显卡驱动或 LWJGL 版本不对"
        143, -15 -> "收到终止信号，一般是你自己点了停止"
        else -> "退出码 $code"
    }

    /** 日志关键字 → 一句人话。顺序有讲究：越具体的越靠前。 */
    private val SIGNATURES: List<Pair<Regex, String>> = listOf(
        Regex("java\\.lang\\.OutOfMemoryError") to "内存不够了，把分配内存调大一档再试",
        Regex("Pixel format not accelerated|Failed to create window|GLFW error") to
            "显卡/驱动没能建出窗口，换一档 LWJGL 或关掉光影",
        Regex("UnsupportedClassVersionError") to "Java 版本太低，这个游戏版本要更高的 Java",
        Regex("java\\.lang\\.ClassNotFoundException") to "少了依赖库，多半是安装没下全，重新安装这个版本",
        Regex("Mixin apply(ing)? failed|MixinApplyError") to "有模组的 Mixin 打不上去，通常是模组之间冲突",
        Regex("Incompatible mod set|requires .* which is missing") to "模组前置缺失或版本不匹配",
        Regex("DuplicateModsFoundException|Duplicate mods") to "装了两份同一个模组，删掉旧的那份",
        Regex("java\\.lang\\.NoSuchMethodError|NoSuchFieldError") to
            "模组和游戏版本对不上，换一个匹配这个游戏版本的模组",
        Regex("Caused by: java\\.io\\.FileNotFoundException") to "少文件，重新安装这个版本能补齐",
    )

    fun classify(log: String): String? =
        SIGNATURES.firstOrNull { it.first.containsMatchIn(log) }?.second

    /**
     * 日志摘录：头几行交代环境，尾巴那段才是崩溃现场。
     * 中间掐掉——真正有用的信息从来不在一个 20 万行日志的正中间。
     */
    fun excerpt(log: String, head: Int = 30, tail: Int = 120): String {
        val lines = log.lineSequence().toList()
        if (lines.size <= head + tail) return filterSecrets(log).take(MAX_EXCERPT)
        val merged = lines.take(head) +
            listOf("… 中间省略 ${lines.size - head - tail} 行 …") +
            lines.takeLast(tail)
        return filterSecrets(merged.joinToString("\n")).take(MAX_EXCERPT)
    }

    /** 有没有崩：被用户主动停掉的不算崩溃，否则每次点停止都弹一个崩溃框。 */
    fun looksLikeCrash(exitCode: Int, cancelled: Boolean): Boolean =
        !cancelled && exitCode != 0

    /**
     * 完整分析。
     *
     * [classify] 那张九条的小表还留着——它是一眼能认出来的那几种，一句话就能答；
     * 真正的归因走 [CrashRules]（移植自桌面 crash.py，分四档、几十条规则）。
     * 两者都没命中时才说「没匹配到已知原因」。
     *
     * @param crashReport crash-reports 里那一份，没有就留空
     * @param hsErr hs_err_pid*.log，安卓上少见但不是没有
     */
    fun analyze(
        exitCode: Int,
        log: String,
        cancelled: Boolean = false,
        crashReport: String = "",
        hsErr: String = "",
        instance: String = "",
        version: String = "",
    ): CrashReport {
        // 用户自己点的停止：一个字的诊断都不要出。游戏被掐死在半路，日志里
        // 留着什么异常都不代表「它崩了」，报出来只会让人去修一个不存在的问题。
        val reasons = if (cancelled) emptyList() else CrashRules.analyze(log, crashReport, hsErr)
        val advices = reasons.map { CrashRules.describe(it) }
        val quick = if (cancelled) null else classify(log)
        val headline = when {
            advices.isNotEmpty() -> advices.first().headline
            quick != null -> quick
            looksLikeCrash(exitCode, cancelled) -> "游戏异常退出"
            else -> "游戏已退出"
        }
        return CrashReport(
            headline = headline,
            summary = exitHint(exitCode),
            reason = reasons.joinToString(",") { it.code }.ifBlank { quick.orEmpty() },
            exitCode = exitCode,
            excerpt = excerpt(filterSecrets(log) + if (crashReport.isBlank()) "" else "\n\n$crashReport"),
            help = if (advices.isNotEmpty() || quick != null) {
                ""
            } else {
                "日志里没匹配到已知原因，把这份日志发给开发者最快。"
            },
            advices = advices,
            reasons = reasons,
            instance = instance,
            version = version,
        )
    }

    /** 把这一次的崩溃现场落到 exports/，用户自己也能翻出来发给别人。 */
    fun export(report: CrashReport, dest: File = File(Paths.exportsRoot, "crash-${System.currentTimeMillis()}.txt")): File {
        dest.parentFile?.mkdirs()
        dest.writeText(
            buildString {
                appendLine("PyMCL ${Paths.APP_VERSION} · android")
                appendLine(report.headline)
                appendLine(report.summary)
                if (report.reason.isNotBlank()) appendLine("判定：${report.reason}")
                appendLine()
                append(report.excerpt)
            },
            Charsets.UTF_8,
        )
        return dest
    }

    /** 游戏进程的最新日志。找不到就返回空串，不要抛——崩溃处理路径上不能再崩。 */
    fun latestLog(instance: String): String {
        val candidates = listOf(
            File(Paths.instanceDir(instance), "logs/latest.log"),
            File(Paths.instanceDir(instance), "crash-reports"),
        )
        val direct = candidates[0]
        if (direct.isFile) return runCatching { direct.readText() }.getOrDefault("")
        val crashDir = candidates[1]
        val newest = crashDir.listFiles()
            ?.filter { it.isFile && it.name.endsWith(".txt") }
            ?.maxByOrNull { it.lastModified() }
            ?: return ""
        return runCatching { newest.readText() }.getOrDefault("")
    }
}
