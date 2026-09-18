package com.pymcl.mobile.data

import java.io.File

/**
 * 崩溃弹窗上的一个可点动作。[id] 决定怎么执行，其余字段是这条动作自己的参数。
 *
 * 跟 [PreflightItem] 一样只出码不出文案：按钮上写什么由界面按 [id] 取词。
 */
data class CrashAction(
    val id: String,
    val mods: List<String> = emptyList(),
    val major: Int = 0,
    val memoryMb: Int = 0,
    val codes: List<String> = emptyList(),
)

/**
 * 动作执行的结果。
 *
 * [code] 是结果码，界面按它取文案；[count] / [detail] 是文案里的变量部分。
 * [route] 非空表示这一条得由界面接着做——手机上没有「打开 Mods 文件夹」这回事，
 * 对应的动作只能是跳到那个页面去。
 */
data class CrashActionResult(
    val ok: Boolean,
    val code: String,
    val count: Int = 0,
    val detail: String = "",
    val route: String = "",
)

/**
 * 崩溃归因 → 可一键执行的修复动作，移植自桌面 `mclauncher/crash.py:build_actions`
 * 与 `app/backend.py:apply_crash_action`。
 *
 * 桌面那七个动作 id 原样保留；[CrashRules] 里安卓独有的那几条归因按语义接到最近的一个上，
 * 只多出一个 [TRIM_MEMORY]——`jvm_start`（虚拟机根本没起来）要的是把内存**调小**，
 * 跟 `oom` 要的调大正好相反，塞进同一个 id 会让按钮说反话。
 *
 * 执行端只做「纯文件操作」那几条（停用模组、清 JVM 参数）；改内存、修版本、装 Java、
 * 翻目录这些要动全局状态或换页面，一律回 [CrashActionResult.route] 交给界面。
 */
object CrashActions {
    // ------------------------------------------------------------ 动作 id
    const val DISABLE_MODS = "disable_mods"
    const val OPEN_MODS = "open_mods_folder"
    const val BUMP_MEMORY = "bump_memory"
    const val TRIM_MEMORY = "trim_memory"
    const val NEED_JAVA = "need_java"
    const val REPAIR_VERSION = "repair_version"
    const val OPEN_CRASH_FILE = "open_crash_file"
    const val OPEN_GPU_HINT = "open_gpu_hint"
    const val RESET_JVM_ARGS = "reset_jvm_args"

    // ------------------------------------------------------------ 结果码
    const val R_DISABLED = "disabled"
    const val R_DISABLE_FAILED = "disable_failed"
    const val R_JVM_CLEARED = "jvm_cleared"
    const val R_GPU_HINT = "gpu_hint"
    const val R_GOTO = "goto"
    const val R_UNKNOWN = "unknown"

    // ------------------------------------------------------------ 跳转落点
    const val ROUTE_MEMORY = "memory"
    const val ROUTE_REPAIR = "repair"
    const val ROUTE_JAVA = "java"
    const val ROUTE_MODS = "mods"
    const val ROUTE_CRASH = "crash"

    /** 内存上下限，与桌面 apply_crash_action 的 1024–32768 一致。 */
    const val MIN_MEMORY_MB = 1024
    const val MAX_MEMORY_MB = 32768

    /** 一条动作最多带这么多个模组名，再多按钮上也写不下。 */
    private const val MAX_MODS = 8

    /**
     * 按归因结果排出建议动作，顺序即按钮顺序。同 id 同参数的只留一条。
     *
     * @param modsDir       这个版本实际读的 mods 目录；不存在就只按归因里的名字来
     * @param hasVersion    报告里有版本号才给「修复该版本」
     * @param hasCrashFile  crash-reports 里确实有一份文件才给「打开崩溃报告」
     * @param memoryMb      当前分配内存，用来算调大 / 调小之后的目标值
     */
    fun build(
        reasons: List<CrashReason>,
        modsDir: File? = null,
        hasVersion: Boolean = false,
        hasCrashFile: Boolean = false,
        memoryMb: Int = 2048,
    ): List<CrashAction> {
        val out = mutableListOf<CrashAction>()
        val seen = mutableSetOf<String>()

        fun add(action: CrashAction) {
            val key = "${action.id}|${action.mods.joinToString(",")}|${action.major}|${action.memoryMb}"
            if (seen.add(key)) out += action
        }

        for (reason in reasons) {
            val code = reason.code
            val extras = reason.extras
            when {
                code in MOD_CODES -> {
                    val mods = resolveMods(modsDir, extras)
                    if (mods.isNotEmpty()) {
                        add(CrashAction(DISABLE_MODS, mods = mods, codes = listOf(code)))
                    } else if (modsDir?.isDirectory == true) {
                        add(CrashAction(OPEN_MODS, codes = listOf(code)))
                    }
                }

                code == "oom" -> add(
                    CrashAction(
                        BUMP_MEMORY,
                        memoryMb = (memoryMb + 1024).coerceAtMost(MAX_MEMORY_MB),
                        codes = listOf(code),
                    ),
                )

                code == "jvm_start" -> add(
                    CrashAction(
                        TRIM_MEMORY,
                        memoryMb = (memoryMb - 1024).coerceAtLeast(MIN_MEMORY_MB),
                        codes = listOf(code),
                    ),
                )

                code in JAVA_CODES -> add(
                    CrashAction(NEED_JAVA, major = javaMajorFor(code), codes = listOf(code)),
                )

                // 原生库没加载起来：不是缺某个大版本，是随包那份运行时解坏了，去 Java 页重装
                code == "native_lib" -> add(CrashAction(NEED_JAVA, codes = listOf(code)))

                code in REPAIR_CODES -> if (hasVersion) {
                    add(CrashAction(REPAIR_VERSION, codes = listOf(code)))
                }

                code in OPEN_MODS_CODES -> {
                    add(CrashAction(OPEN_MODS, codes = listOf(code)))
                    if (code == "mod_dup" && extras.isNotEmpty()) {
                        // 重复安装时留一份、停掉其余的，跟桌面一样只从第二份开始动
                        val dup = resolveMods(modsDir, extras)
                        val rest = if (dup.size > 1) dup.drop(1) else dup
                        if (rest.isNotEmpty()) {
                            add(CrashAction(DISABLE_MODS, mods = rest, codes = listOf(code)))
                        }
                    }
                }

                code in GPU_CODES -> add(CrashAction(OPEN_GPU_HINT, codes = listOf(code)))

                code == "jvm_args" -> add(CrashAction(RESET_JVM_ARGS, codes = listOf(code)))
            }
        }

        if (hasCrashFile) add(CrashAction(OPEN_CRASH_FILE, codes = listOf("_file")))
        return out
    }

    /**
     * 执行一条动作。
     *
     * @param instDir 崩溃那次用的实例目录
     * @param version 崩溃那次的版本 id，停用模组 / 清 JVM 参数都要按它定位
     */
    fun apply(action: CrashAction, instDir: File, version: String = ""): CrashActionResult =
        when (action.id) {
            DISABLE_MODS -> disableMods(action.mods, instDir, version)
            RESET_JVM_ARGS -> resetJvmArgs(instDir, version)
            OPEN_GPU_HINT -> CrashActionResult(true, R_GPU_HINT)
            BUMP_MEMORY, TRIM_MEMORY ->
                CrashActionResult(true, R_GOTO, count = clampMemory(action.memoryMb), route = ROUTE_MEMORY)
            REPAIR_VERSION -> CrashActionResult(true, R_GOTO, route = ROUTE_REPAIR)
            NEED_JAVA -> CrashActionResult(true, R_GOTO, count = action.major, route = ROUTE_JAVA)
            OPEN_MODS -> CrashActionResult(true, R_GOTO, route = ROUTE_MODS)
            OPEN_CRASH_FILE -> CrashActionResult(true, R_GOTO, route = ROUTE_CRASH)
            else -> CrashActionResult(false, R_UNKNOWN, detail = action.id)
        }

    fun clampMemory(mb: Int): Int = mb.coerceIn(MIN_MEMORY_MB, MAX_MEMORY_MB)

    private fun disableMods(mods: List<String>, instDir: File, version: String): CrashActionResult {
        val done = mutableListOf<String>()
        val failed = mutableListOf<String>()
        for (name in mods) {
            runCatching { Mods.setEnabled(instDir, name, false, version) }
                .onSuccess { done += name }
                .onFailure { failed += "$name: ${it.message}" }
        }
        if (done.isEmpty()) {
            return CrashActionResult(false, R_DISABLE_FAILED, detail = failed.joinToString("; "))
        }
        return CrashActionResult(true, R_DISABLED, done.size, failed.joinToString("; "))
    }

    /** 全局默认参数和这个版本自己的都清掉——只清一处，另一处还会把游戏顶回同一个坑。 */
    private fun resetJvmArgs(instDir: File, version: String): CrashActionResult {
        Settings.set(SettingsKeys.DEFAULT_JVM_ARGS, "")
        if (version.isNotBlank()) {
            runCatching {
                val current = VersionSettings.load(instDir, version)
                VersionSettings.save(instDir, version, current.copy(jvmArgs = "", gc = ""))
            }
        }
        return CrashActionResult(true, R_JVM_CLEARED)
    }

    /**
     * 把归因里那几个名字对到 mods 目录真实存在的文件上，移植自桌面 `_match_mod_files`。
     * 目录不在或一个都没对上时退回归因给的原名——按钮照样能点，只是停用那一步可能失败。
     */
    internal fun resolveMods(modsDir: File?, names: List<String>): List<String> {
        val wanted = names.map { it.trim() }.filter { it.isNotEmpty() }
        if (wanted.isEmpty()) return emptyList()
        val matched = matchModFiles(modsDir, wanted)
        return (if (matched.isNotEmpty()) matched else wanted).take(MAX_MODS)
    }

    internal fun matchModFiles(modsDir: File?, names: List<String>): List<String> {
        val dir = modsDir ?: return emptyList()
        if (!dir.isDirectory) return emptyList()
        val files = dir.listFiles()?.filter { it.isFile && Mods.looksLikeMod(it.name) }.orEmpty()
        if (files.isEmpty()) return emptyList()
        val byName = files.associateBy { it.name.lowercase() }
        val byStem = files.associateBy { Mods.baseName(it.name).substringBeforeLast('.').lowercase() }
        val hit = LinkedHashSet<String>()
        for (raw in names) {
            val low = raw.lowercase()
            val stem = Mods.baseName(raw).substringBeforeLast('.').lowercase()
            val exact = byName[low] ?: byStem[stem]
            if (exact != null) {
                hit += Mods.baseName(exact.name)
                continue
            }
            val fuzzy = files.firstOrNull {
                val n = it.name.lowercase()
                low.isNotEmpty() && (n.contains(low) || (stem.isNotEmpty() && n.contains(stem)))
            }
            if (fuzzy != null) hit += Mods.baseName(fuzzy.name)
        }
        return hit.toList()
    }

    /** 哪一档 Java，照抄桌面 build_actions 里那串 if。 */
    internal fun javaMajorFor(code: String): Int = when (code) {
        "need_java11" -> 11
        "jdk", "java_too_old", "old_forge_new_java" -> 8
        else -> 17
    }

    private val MOD_CODES = setOf(
        "mod_suspect", "stack_keyword", "mod_name_chars", "shaders_optifine",
        "mod_certain", "mixin", "mod_config", "mod_init", "mod_incompat",
        "optifine_forge", "mixin_bootstrap", "nightconfig",
    )

    private val JAVA_CODES = setOf(
        "openj9", "jdk", "java_too_new", "java_mismatch",
        "need_java11", "old_forge_new_java", "java_too_old",
    )

    private val REPAIR_CODES = setOf(
        "forge_incomplete", "verify_fail", "multi_forge_json",
        "libs_missing", "assets_index_missing", "assets_missing",
        "natives_missing", "loader_error", "forge_error",
    )

    private val OPEN_MODS_CODES = setOf(
        "mod_unzipped", "mod_duplicate", "mod_breaks", "mod_dup",
        "mod_missing", "mod_id_limit", "hd_pack",
    )

    /** 渲染 / 驱动这一类，安卓上 GL 是翻译层，提示词跟桌面不同但落点一样。 */
    private val GPU_CODES = setOf(
        "pixel_format", "no_opengl", "opengl_1282", "gles_renderer", "native_crash",
    )
}
