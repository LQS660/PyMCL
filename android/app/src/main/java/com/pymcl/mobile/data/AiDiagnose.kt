package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject

/** 一条诊断结论：认出了什么、凭什么认的、该怎么办。 */
data class Finding(
    val code: String,
    val title: String,
    val evidence: List<String>,
    val advice: List<String>,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("code", code)
        .put("title", title)
        .put("evidence", JSONArray(evidence))
        .put("advice", JSONArray(advice))
}

/** 整份诊断。[recognized] 为 false 时 [findings] 为空，[summary] 明确写「未识别」。 */
data class Diagnosis(
    val recognized: Boolean,
    val findings: List<Finding>,
    val summary: String,
    val scannedChars: Int,
    val truncated: Boolean,
) {
    fun toJson(): JSONObject {
        val arr = JSONArray()
        findings.forEach { arr.put(it.toJson()) }
        return JSONObject()
            .put("recognized", recognized)
            .put("summary", summary)
            .put("findings", arr)
            .put("scanned_chars", scannedChars)
            .put("truncated", truncated)
    }
}

/**
 * 崩溃 / 启动失败诊断。规则式，签名多数照抄桌面 mclauncher/crash.py（PCL 同源），
 * 另加手机端 FCL / GL / JNI 那一层桌面没有的崩溃面。
 *
 * 认不出来就明说「未识别」，不蒙。超长日志只看头尾（与桌面 head_tail_lines 同思路）。
 */
object CrashDiagnoser {
    const val CODE_OOM = "out_of_memory"
    const val CODE_JAVA = "java_version"
    const val CODE_MISSING_DEP = "mod_missing_dependency"
    const val CODE_DUPLICATE = "mod_duplicate"
    const val CODE_INCOMPATIBLE = "mod_incompatible"
    const val CODE_MOD_CRASH = "mod_crash"
    const val CODE_GRAPHICS = "graphics_driver"
    const val CODE_ANDROID = "android_runtime"
    const val CODE_AUTH = "auth_failure"
    const val CODE_UNKNOWN = "unknown"

    /** 头尾各留多少行；中间那段对定位原因几乎没用，却最容易撑爆内存。 */
    const val HEAD_LINES = 400
    const val TAIL_LINES = 1500
    const val MAX_LINE_CHARS = 2000
    const val MAX_EVIDENCE = 4

    private class Rule(
        val code: String,
        val title: String,
        val advice: List<String>,
        val patterns: List<Regex>,
        /** 命中行里再抠一段当证据（比如缺的依赖名）；null 就用整行。 */
        val extract: ((String) -> String?)? = null,
    )

    private fun rx(vararg literal: String): List<Regex> = literal.map { Regex(Regex.escape(it)) }

    private val RULES: List<Rule> = listOf(
        // 越具体的越靠前：同一份日志能同时命中 OOM 与「模组崩了」时，先说具体的。
        Rule(
            CODE_MISSING_DEP, "缺少前置模组",
            listOf("按提示把缺的前置模组装上（Fabric 模组多半要 Fabric API）", "确认前置的版本与当前游戏版本匹配"),
            rx("Missing or unsupported mandatory dependencies:", "Unmet dependency listing:", "requires any version of", "which is missing!"),
            extract = { line ->
                Regex("""requires any version of ([A-Za-z0-9_.\-]+)""").find(line)?.let { "缺少前置：" + it.groupValues[1] }
            },
        ),
        Rule(
            CODE_DUPLICATE, "同一个模组装了两份",
            listOf("到 mods 文件夹删掉重复的那份，只留一个版本"),
            rx("DuplicateModsFoundException", "Found duplicate mods", "Found a duplicate mod", "ModResolutionException: Duplicate"),
        ),
        Rule(
            CODE_INCOMPATIBLE, "模组版本不匹配 / 互不兼容",
            listOf("检查报出的模组是否为当前游戏版本和加载器构建的", "换成与游戏版本匹配的模组版本，或先移出它再试"),
            rx(
                "Incompatible mods found!", "Mixin apply failed", "Mixin prepare failed", "MixinApplyError",
                "MixinTransformerError", "Replace mod ", "Some of your mods are incompatible",
                "but only the wrong version is present",
            ) + listOf(
                Regex("""requires version [^\n]+ of minecraft"""),
                Regex("""java\.lang\.NoSuchMethodError: '?(net\.minecraft|com\.mojang)"""),
                Regex("""java\.lang\.NoSuchFieldError: [A-Za-z_]"""),
                Regex("""java\.lang\.NoClassDefFoundError: net/minecraft"""),
            ),
        ),
        Rule(
            CODE_JAVA, "Java 版本不对",
            listOf("按游戏版本换 Java：≤1.16 用 8，1.17–1.20.4 用 17，1.20.5+ 用 21", "启动配置里让运行时「自动选择」"),
            rx(
                "Unsupported class file major version", "Unsupported major.minor version",
                "has been compiled by a more recent version of the Java Runtime", "UnsupportedClassVersionError",
                "because module java.base does not export", "java.lang.NoSuchFieldException: ucp",
                "jdk.nashorn.api.scripting.NashornScriptEngineFactory", "Unable to make protected final java.lang.Class java.lang.ClassLoader.defineClass",
                "The requested compatibility level JAVA_11 could not be set", "Level is not supported by the active JRE or ASM version",
            ),
        ),
        Rule(
            CODE_OOM, "内存不足",
            listOf("把分配内存调小一点（手机上一般 1.5–3 GB 最稳），并关掉后台应用", "减少同时加载的模组、光影或调低渲染距离"),
            rx(
                "java.lang.OutOfMemoryError", "an out of memory error", "Could not reserve enough space",
                "The system is out of physical RAM or swap space", "Out of Memory Error", "OutOfMemoryError",
            ),
        ),
        Rule(
            CODE_GRAPHICS, "显卡 / 渲染器问题",
            listOf("换一个渲染器再试（gl4es ↔ zink / vgpu），部分光影在手机上不可用", "先关掉光影和高分辨率资源包"),
            rx(
                "The driver does not appear to support OpenGL", "Pixel format not accelerated", "Couldn't set pixel format",
                "1282: Invalid operation", "GLFW error", "Failed to create EGL context", "eglCreateContext", "EGL_BAD_",
                "Maybe try a lower resolution resourcepack?",
            ),
        ),
        Rule(
            CODE_ANDROID, "手机运行时（FCL / JNI）崩溃",
            listOf("重装运行时（启动页会重新解压 JRE 与原生库）", "换渲染器或关掉插件后再试；若仍复现，把这段日志一起反馈"),
            rx(
                "dlopen failed", "java.lang.UnsatisfiedLinkError", "JNI DETECTED ERROR IN APPLICATION", "Fatal signal ",
                "No implementation found for", "JNI_OnLoad", "libfclauncher", "FCLBridge",
            ) + listOf(Regex("""\bSIG(SEGV|ABRT|BUS|ILL)\b""")),
        ),
        Rule(
            CODE_AUTH, "账号验证失败",
            listOf("重新登录账号，或改用离线模式", "用了外置登录（authlib-injector）的话检查皮肤站地址与令牌"),
            rx(
                "InvalidCredentialsException", "Status: 401", "Invalid session (Try restarting your game",
                "AuthenticationException", "Failed to verify username",
            ),
        ),
        Rule(
            CODE_MOD_CRASH, "某个模组自己崩了",
            listOf("先把报出的模组移出 mods 文件夹再试；确认它与游戏版本匹配", "有更新就更新它，没有就去模组页反馈"),
            rx("Caught exception from ", "LoaderExceptionModCrash", "Failed to create mod instance", "-- MOD ", "Failure message:", "Suspected Mod")
                + listOf(Regex("""/FATAL\]""")),
            extract = { line ->
                Regex("""Caught exception from ([^\n(]+)""").find(line)?.groupValues?.get(1)?.trim()
                    ?: Regex("""Failed to create mod instance\. Mod[Ii][Dd]:? ?([^,\s]+)""").find(line)?.groupValues?.get(1)
            },
        ),
    )

    /** [latest] 是 latest.log，[crash] 是崩溃报告（可空）。两段各自截头尾后合起来扫。 */
    fun diagnose(latest: String?, crash: String? = null): Diagnosis {
        val (text, truncated) = prepare(latest, crash)
        if (text.isBlank()) {
            return Diagnosis(false, emptyList(), "日志是空的，没有可分析的内容", 0, truncated)
        }
        val lines = text.split('\n')
        val findings = ArrayList<Finding>()
        for (rule in RULES) {
            val hits = ArrayList<String>()
            for (raw in lines) {
                if (hits.size >= MAX_EVIDENCE) break
                val line = if (raw.length > MAX_LINE_CHARS) raw.substring(0, MAX_LINE_CHARS) else raw
                if (rule.patterns.any { it.containsMatchIn(line) }) {
                    val piece = rule.extract?.invoke(line)?.takeIf { it.isNotBlank() } ?: line.trim()
                    if (piece !in hits) hits.add(piece.take(240))
                }
            }
            if (hits.isNotEmpty()) findings.add(Finding(rule.code, rule.title, hits, rule.advice))
        }
        if (findings.isEmpty()) {
            return Diagnosis(
                recognized = false,
                findings = emptyList(),
                summary = "未识别：日志里没有已知的崩溃特征。可以把 latest.log 末尾和崩溃报告一起发出来人工看。",
                scannedChars = text.length,
                truncated = truncated,
            )
        }
        val primary = findings.first()
        val summary = if (findings.size == 1) primary.title
        else primary.title + "（另外还发现：" + findings.drop(1).joinToString("、") { it.title } + "）"
        return Diagnosis(true, findings, summary, text.length, truncated)
    }

    /** 统一换行、去掉 NUL 等控制字符，各段只留头 [HEAD_LINES] + 尾 [TAIL_LINES] 行。 */
    internal fun prepare(latest: String?, crash: String?): Pair<String, Boolean> {
        var truncated = false
        val parts = ArrayList<String>()
        for (raw in listOf(latest, crash)) {
            if (raw.isNullOrBlank()) continue
            val cleaned = raw.replace("\r\n", "\n").replace('\r', '\n').replace(Regex("[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F]"), "")
            val lines = cleaned.split('\n')
            if (lines.size > HEAD_LINES + TAIL_LINES) {
                truncated = true
                parts.add(lines.take(HEAD_LINES).joinToString("\n"))
                parts.add(lines.takeLast(TAIL_LINES).joinToString("\n"))
            } else {
                parts.add(cleaned)
            }
        }
        return parts.joinToString("\n") to truncated
    }
}
