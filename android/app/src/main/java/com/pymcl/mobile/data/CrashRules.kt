package com.pymcl.mobile.data

/**
 * 崩溃归因规则，移植自桌面 `mclauncher/crash.py`（它自己又对齐 PCL 的 GetAnalyzeResult）。
 *
 * 设计上刻意做成**纯文本进、结构化出**：喂三段日志，吐一串 [CrashReason]，
 * 不碰文件、不碰网络、不碰界面。所以每一条规则都能用一段真实形状的日志片段单测，
 * 这台机器出不出 APK 跟它一点关系没有。
 *
 * 分三档，跟桌面 `crit1 / crit2 / crit3` 一一对应，**顺序有意义**：
 * 前一档命中就不再往下找。原因是后面那两档越来越靠猜，先报出来的必须是最确定的那个——
 * 「内存不够」和「怀疑某个 Mod」同时报出来，用户会先去折腾后者。
 */
data class CrashReason(val code: String, val extras: List<String> = emptyList()) {
    val first: String get() = extras.firstOrNull().orEmpty()
}

/** 一条归因翻成人话。[needHelp] = 还是建议把日志发给人看。 */
data class CrashAdvice(val headline: String, val detail: String, val needHelp: Boolean)

object CrashRules {
    // ---------------------------------------------------------------- 归因
    /**
     * @param mc    latest.log / 进程标准输出那一路
     * @param crash crash-reports 里那一份
     * @param hs    hs_err_pid*.log（JVM 自己崩的那种）；安卓上很少见但不是没有
     */
    fun analyze(mc: String, crash: String = "", hs: String = ""): List<CrashReason> {
        if (mc.isBlank() && crash.isBlank() && hs.isBlank()) {
            return listOf(CrashReason("no_files"))
        }
        crit1(mc, crash, hs).takeIf { it.isNotEmpty() }?.let { return it }
        crit2(mc, crash).takeIf { it.isNotEmpty() }?.let { return it }
        stackKeywords(mc, crash, hs).takeIf { it.isNotEmpty() }?.let { return it }
        return crit3(mc, crash)
    }

    /** 第一档：一条日志文本唯一对应一个原因，基本不会误判。 */
    private fun crit1(mc: String, crash: String, hs: String): List<CrashReason> {
        val out = LinkedHashMap<String, MutableList<String>>()
        fun add(code: String, extras: List<String> = emptyList()) {
            out.getOrPut(code) { mutableListOf() }.let { cur ->
                extras.forEach { if (it.isNotBlank() && it !in cur) cur.add(it) }
            }
        }

        if (crash.isNotBlank()) {
            if ("Unable to make protected final java.lang.Class java.lang.ClassLoader.defineClass" in crash) {
                add("java_too_new")
            }
            if ("Failed loading config file " in crash) {
                val mod = seek(crash, """Failed loading config file .+ for modid ([^\n]+)""")
                val cfg = seek(crash, """Failed loading config file (.+?) of type""")
                add("mod_config", listOf(mod, cfg))
            }
            if ("maximum id range exceeded" in crash) add("mod_id_limit")
            if ("java.lang.OutOfMemoryError" in crash) add("oom")
            if ("Pixel format not accelerated" in crash) add("pixel_format")
            if ("Manually triggered debug crash" in crash) add("debug_crash")
            if ("Multiple entries with same key: " in crash) {
                add("mod_certain", listOf(seek(crash, """Multiple entries with same key: ([^=\n]+)""")))
            }
            if ("LoaderExceptionModCrash: Caught exception from " in crash) {
                add("mod_certain", listOf(seek(crash, """LoaderExceptionModCrash: Caught exception from ([^\n]+)""")))
            }
            if ("-- MOD " in crash) {
                val chunk = between(crash, "-- MOD ", "Failure message:")
                if (chunk.contains(".jar", true)) {
                    add("mod_certain", listOf(seek(chunk, """Mod File: (.+)""")))
                } else {
                    add("loader_error", listOf(seek(crash, """Failure message: ([\s\S]+?)\tMod""").replace('\t', ' ').trim()))
                }
            }
        }

        if (mc.isNotBlank()) {
            if ("Unrecognized option:" in mc) add("jvm_args")
            if ("Found multiple arguments for option fml.forgeVersion, but you asked for only one" in mc) add("multi_forge_json")
            if ("java.lang.ClassCastException: java.base/jdk" in mc || "java.lang.ClassCastException: class jdk." in mc) add("jdk")
            if (OPTIFINE_FORGE_MARKS.any { it in mc }) add("optifine_forge")
            if ("Open J9 is not supported" in mc || "OpenJ9 is incompatible" in mc || ".J9VMInternals." in mc) add("openj9")
            if (JAVA_TOO_NEW_MARKS.any { it in mc }) add("java_too_new")
            if ("The directories below appear to be extracted jar files" in mc ||
                "Extracted mod jars found, loading will NOT continue" in mc
            ) {
                add("mod_unzipped")
            }
            if ("java.lang.ClassNotFoundException: org.spongepowered.asm.launch.MixinTweaker" in mc) add("mixin_bootstrap")
            if ("java.lang.OutOfMemoryError" in mc || "an out of memory error" in mc) add("oom")
            if ("Shaders Mod detected. Please remove it, OptiFine has built-in support for shaders." in mc) add("shaders_optifine")
            if ("java.lang.NoSuchMethodError: sun.security.util.ManifestEntryVerifier" in mc ||
                "java.lang.NoSuchMethodError: 'void sun.security.util.ManifestEntryVerifier" in mc
            ) {
                add("old_forge_new_java")
            }
            if ("1282: Invalid operation" in mc) add("opengl_1282")
            if ("signer information does not match signer information of other classes in the same package" in mc) {
                add("verify_fail", listOf(seek(mc, """class "([^"]+)"'s signer information""")))
            }
            if ("Maybe try a lower resolution resourcepack?" in mc) add("hd_pack")
            if ("ChunkManager\$ProxyTicketManager.shouldForceTicks(J)Z" in mc && "OptiFine" in mc) add("optifine_world")
            if ("com.electronwill.nightconfig.core.io.ParsingException: Not enough data available" in mc &&
                "mod_config" !in out
            ) {
                add("nightconfig")
            }
            if ("Cannot find launch target fmlclient, unable to launch" in mc) add("forge_incomplete")
            if ("Invalid module name: '' is not a Java identifier" in mc) add("mod_name_chars")
            if (NEED_JAVA11_MARKS.any { it in mc }) add("need_java11")
            if ("Unsupported class file major version" in mc || "Unsupported major.minor version" in mc ||
                "Level is not supported by the active JRE or ASM version" in mc
            ) {
                add("java_mismatch")
            }
            if ("Could not reserve enough space" in mc) add("oom")
            if ("Caught exception from " in mc) {
                add("mod_certain", listOf(seek(mc, """Caught exception from ([^\n]+)""")))
            }
            if ("DuplicateModsFoundException" in mc || "Found a duplicate mod" in mc ||
                "Found duplicate mods" in mc || "ModResolutionException: Duplicate" in mc
            ) {
                add("mod_dup", searchAll(mc, """([^\\/\s]+\.jar)""").distinct().take(8))
            }
            if ("Incompatible mods found!" in mc) {
                add("mod_incompat", listOf(seek(mc, """Incompatible mods found![\s\S]+?: ([\s\S]+?)\tat """).trim()))
            }
            if ("Missing or unsupported mandatory dependencies:" in mc) {
                val block = seek(mc, """Missing or unsupported mandatory dependencies:((?:[\n\r]+\t.*)+)""")
                add("mod_missing", block.lines().map { it.trim() }.filter { it.isNotEmpty() })
            }
            // --- 安卓特有，桌面没有 ---
            if (ANDROID_GLES_MARKS.any { it in mc }) add("gles_renderer")
            if ("dlopen failed" in mc || "cannot locate symbol" in mc) {
                add("native_lib", listOf(seek(mc, """dlopen failed: ([^\n]+)""")))
            }
            if ("UnsatisfiedLinkError" in mc) {
                add("native_lib", listOf(seek(mc, """UnsatisfiedLinkError: ([^\n]+)""")))
            }
            if ("Could not create the Java Virtual Machine" in mc || "Error occurred during initialization of VM" in mc) {
                add("jvm_start")
            }
        }

        if (hs.isNotBlank()) {
            if ("The system is out of physical RAM or swap space" in hs || "Out of Memory Error" in hs) add("oom")
            if ("EXCEPTION_ACCESS_VIOLATION" in hs || "SIGSEGV" in hs) add("native_crash")
        }
        return out.map { CrashReason(it.key, it.value.filter { s -> s.isNotBlank() }) }
    }

    /** 第二档：Mixin 注入失败、加载器自己给的方案，比第一档模糊一点但仍然指得准。 */
    private fun crit2(mc: String, crash: String): List<CrashReason> {
        val out = LinkedHashMap<String, MutableList<String>>()
        fun add(code: String, extras: List<String> = emptyList()) {
            out.getOrPut(code) { mutableListOf() }.let { cur ->
                extras.forEach { if (it.isNotBlank() && it !in cur) cur.add(it) }
            }
        }

        fun mixin(text: String): Boolean {
            if (text.isBlank()) return false
            val hit = MIXIN_MARKS.any { it in text }
            if (!hit) return false
            val name = seek(text, """from mod ([^./ ]+)\] from""")
                .ifBlank { seek(text, """for mod ([^./ ]+) failed""") }
            if (name.isNotBlank()) {
                add("mixin", listOf(name))
                return true
            }
            add("mixin")
            return true
        }

        var isMixin = false
        if (mc.isNotBlank()) {
            isMixin = mixin(mc)
            if ("An exception was thrown, the game will display an error screen and halt." in mc) {
                add("forge_error", listOf(seek(mc, """Exception: ([\s\S]+?)\n\tat """).trim()))
            }
            FABRIC_SOLUTION_MARKS.forEach { mark ->
                if (mark in mc) {
                    val block = mc.substringAfter(mark, "").lineSequence()
                        .takeWhile { it.isBlank() || it.trimStart().startsWith("-") }
                        .map { it.trim(' ', '\t', '-') }
                        .filter { it.isNotEmpty() }
                        .toList()
                    add("fabric_solution", block)
                }
            }
            if (!isMixin && "due to errors, provided by " in mc) {
                add("mod_certain", listOf(seek(mc, """due to errors, provided by '([^']+)'""")))
            }
        }
        if (crash.isNotBlank()) {
            mixin(crash)
            if ("Suspected Mod" in crash) {
                val raw = between(crash, "Suspected Mod", "Stacktrace")
                if (!raw.startsWith("s: None")) {
                    add("mod_suspect", searchAll(raw, """\(([^)\n]+)\)""").distinct().take(6))
                }
            }
        }
        return out.map { CrashReason(it.key, it.value.filter { s -> s.isNotBlank() }) }
    }

    /**
     * 第三档：从堆栈里刨可疑包名。
     *
     * 只在日志里出现过加载器字样时才做——纯原版崩溃刨出来的全是 `net.minecraft`，
     * 报给用户等于噪音。
     */
    private fun stackKeywords(mc: String, crash: String, hs: String): List<CrashReason> {
        val blob = mc + crash + hs
        if (LOADER_TOKENS.none { it in blob }) return emptyList()
        val words = stackSuspects(blob)
        if (words.isEmpty()) return emptyList()
        return listOf(CrashReason("stack_keyword", words))
    }

    /** 第四档：世界里的坏方块 / 坏实体，以及加载器自己说的失败。 */
    private fun crit3(mc: String, crash: String): List<CrashReason> {
        val out = mutableListOf<CrashReason>()
        if (mc.isNotBlank()) {
            if (mc.length < 100 && "at net." !in mc && "INFO]" !in mc) {
                out.add(CrashReason("tiny_output", listOf(mc.trim())))
            }
            if ("Mod resolution failed" in mc) out.add(CrashReason("loader_error"))
            if ("Failed to create mod instance." in mc) {
                val id = seek(mc, """Failed to create mod instance. ModID: ([^,\n]+)""")
                    .ifBlank { seek(mc, """Failed to create mod instance. ModId ([^\n]+?) for """) }
                out.add(CrashReason("mod_init", listOf(id)))
            }
        }
        if (crash.isNotBlank()) {
            if ("\tBlock location: World: " in crash) {
                val block = seek(crash, """\tBlock: Block\{([^}]+)}""")
                val loc = seek(crash, """\tBlock location: World: (\([^)]+\))""")
                out.add(CrashReason("bad_block", listOf("$block $loc".trim())))
            }
            if ("\tEntity's Exact location: " in crash) {
                val type = seek(crash, """\tEntity Type: ([^\n]+?) \(""")
                val loc = seek(crash, """\tEntity's Exact location: ([^\n]+)""").trim()
                out.add(CrashReason("bad_entity", listOf(if (type.isNotBlank()) "$type ($loc)" else loc)))
            }
        }
        return out.filter { it.code.isNotBlank() }
    }

    // ---------------------------------------------------------------- 文案
    /**
     * 归因 → 人话。文案沿用桌面那份（PCL 口径），只把三处桌面专属的说法换成安卓的：
     * 「启动设置里的 Java 虚拟机参数」→「设置页的默认 JVM 参数」、
     * 「本实例的 Java 选项」→「Java 页」、「电脑」→「手机」。
     */
    fun describe(reason: CrashReason): CrashAdvice {
        val e = reason.extras
        val one = reason.first
        val many = e.joinToString("\n - ")
        return when (reason.code) {
            "jvm_args" -> advice("Java 参数有误", "游戏没能跑起来。去「设置 → 内存与 JVM」检查默认 JVM 参数。", false)
            "mod_unzipped" -> advice(
                "有 Mod 被解压了",
                "整个 .jar 直接放进 mods 目录即可，解压成文件夹就会出错。删掉 mods 里已解压的文件夹再启动。",
                false,
            )
            "oom" -> advice(
                "内存不够",
                "去「设置 → 内存与 JVM」把分配内存调大一档，并删掉过高的材质、Mod、光影。" +
                    "手机内存本来就比电脑紧，启动前把别的应用划掉也有用。",
                true,
            )
            "openj9" -> advice("用的是 OpenJ9", "去「Java」页换一个非 OpenJ9 的运行时再启动。", false)
            "jdk" -> advice("Java 版本过高或用了 JDK", "去「Java」页换 Java 8 再启动。", false)
            "java_too_new" -> advice("Java 版本过高", "去「Java」页换一个低版本的运行时再启动。", false)
            "java_mismatch" -> advice("Java 版本对不上", "这个游戏版本不兼容当前 Java，去「Java」页换一个合适的。", false)
            "need_java11" -> advice("有 Mod 需要 Java 11", "去「Java」页装并选中 Java 11 再启动。", false)
            "mod_name_chars" -> advice(
                "Mod 文件名里有特殊字符",
                "把它改成只含英文、数字、减号、下划线和小数点再启动。",
                false,
            )
            "mixin_bootstrap" -> advice("缺 MixinBootstrap", "装一个 MixinBootstrap 再试。", false)
            "tiny_output" -> advice("程序只返回了这一句", one, true)
            "optifine_world" -> advice("这个 OptiFine 版本有问题", "换一个 OptiFine 版本试试，这个问题只在特定版本出现。", true)
            "hd_pack" -> advice("材质分辨率过高", "手机 GPU 吃不下这张材质，先把高清材质移除。", true)
            "nightconfig" -> advice("Night Config 出问题", "可以装一个 Night Config Fixes 模组。", true)
            "opengl_1282" -> advice("光影或材质导致渲染出错", "先把这些额外资源删掉再启动。", true)
            "mod_id_limit" -> advice("Mod 装太多，超出 ID 上限", "装 JEID 一类的修复 Mod，或删掉部分大型 Mod。", false)
            "verify_fail" -> advice("文件校验失败", "有文件损坏了。把游戏（含 Mod）删掉重新下载一次。", true)
            "forge_incomplete" -> advice("Forge 装得不全", "重新装一次相同版本的 Forge。", true)
            "debug_crash" -> advice("这是你自己触发的调试崩溃", "游戏本身没有问题。", false)
            "optifine_forge" -> advice(
                "OptiFine 与当前 Forge 不兼容",
                "去 OptiFine 官网看它兼容哪个 Forge 版本，按对应版本重装。",
                false,
            )
            "shaders_optifine" -> advice(
                "同时装了 OptiFine 和 Shaders Mod",
                "OptiFine 已经自带光影功能，删掉 Shaders Mod 再启动。",
                false,
            )
            "old_forge_new_java" -> advice(
                "低版本 Forge 配了过新的 Java",
                "把 Forge 升到 36.2.26 以上，或去「Java」页换一个低于 8.0.320 的运行时。",
                false,
            )
            "multi_forge_json" -> advice("版本 Json 里有多个 Forge", "这个版本文件坏了，重新全新安装一次 Forge。", false)
            "no_files" -> advice("没找到日志", "游戏出了问题，但没有任何日志可分析。", true)

            "mod_missing" -> if (e.isEmpty()) {
                advice("缺前置 Mod", "按错误报告里的日志补齐依赖。", true)
            } else {
                advice("缺前置 Mod", "缺这些依赖：\n - $many", false)
            }

            "stack_keyword" -> if (e.size <= 1) {
                advice("分析到一个可疑关键词", "可疑词：${one.ifBlank { "未知" }}。知道它对应哪个 Mod 就先停用它。", true)
            } else {
                advice("分析到几个可疑关键词", "可疑词：${e.joinToString("、")}。认出哪个是哪个 Mod 就先停用它。", true)
            }

            "mod_suspect" -> if (e.size <= 1) {
                advice("怀疑是某个 Mod", "怀疑「${one.ifBlank { "未知" }}」，但不完全确定。先停用它看还崩不崩。", true)
            } else {
                advice("怀疑是这几个 Mod 之一", "怀疑：\n - $many\n\n依次停用，看还崩不崩。", true)
            }

            "mod_certain" -> if (e.size <= 1) {
                advice("某个 Mod 导致了崩溃", "是「${one.ifBlank { "未知" }}」。先停用它，再看还崩不崩。", true)
            } else {
                advice("这几个 Mod 导致了崩溃", "涉及：\n - $many\n\n依次停用，再看还崩不崩。", true)
            }

            "mixin" -> when {
                e.isEmpty() -> advice("有 Mod 注入失败", "一般是 Mod 之间不兼容，或它自己有 Bug。逐个停用来定位。", true)
                e.size == 1 -> advice("「$one」注入失败", "一般是它跟别的 Mod 或当前环境不兼容。先停用它。", true)
                else -> advice("这几个 Mod 注入失败", "涉及：\n - $many", true)
            }

            "mod_config" -> if (e.size >= 2) {
                advice("「${e[0]}」的配置文件坏了", "配置文件 ${e[1]} 读不出来。删掉它让 Mod 重新生成一份。", false)
            } else {
                advice("某个 Mod 的配置文件坏了", "涉及「${one.ifBlank { "未知" }}」。删掉它的配置让它重新生成。", false)
            }

            "mod_init" -> if (e.size <= 1) {
                advice("「${one.ifBlank { "未知" }}」初始化失败", "游戏没能加载完。先停用它。", true)
            } else {
                advice("这几个 Mod 初始化失败", "涉及：\n - $many", true)
            }

            "bad_block" -> if (one.isNotBlank()) {
                advice("世界里有个方块出了问题", "问题方块：$one。\n新建一个世界试试：能进就是这个方块的事，还崩就是别处。", true)
            } else {
                advice("世界里的某些方块出了问题", "新建一个世界试一次。", true)
            }

            "bad_entity" -> when {
                "minecraft:player" in one -> advice("玩家实体导致了崩溃", one, true)
                one.isNotBlank() -> advice("某个实体导致了崩溃", "实体：$one", true)
                else -> advice("世界里的某个实体导致了崩溃", "", true)
            }

            "mod_dup" -> if (e.size >= 2) {
                advice("装了重复的 Mod", "重复的是：\n - $many\n\n每个 Mod 只能有一份，删掉多余的再启动。", false)
            } else {
                advice("可能装了重复的 Mod", "每个 Mod 只能有一份，检查一下 mods 目录。", true)
            }

            "fabric_solution" -> if (e.isNotEmpty()) {
                advice("Fabric 给出了解决方案", e.joinToString("\n"), false)
            } else {
                advice("Fabric 可能已给出方案", "按错误报告里的日志处理。", true)
            }
            "forge_error" -> if (one.isNotBlank()) advice("Forge 给出了错误信息", one, false)
            else advice("Forge 可能已给出错误信息", "按错误报告里的日志处理。", true)
            "mod_incompat" -> if (one.isNotBlank()) advice("装的 Mod 互相不兼容", one, false)
            else advice("装的 Mod 互相不兼容", "按错误报告里的日志处理。", true)
            "loader_error" -> if (one.isNotBlank()) advice("Mod 加载器给出了错误信息", one, false)
            else advice("Mod 加载器可能已给出错误信息", "按错误报告里的日志处理。", true)

            // ------------------------------------------------ 安卓特有
            "gles_renderer" -> advice(
                "渲染器跟这个游戏版本对不上",
                "手机上 OpenGL 是靠 GL4ES / Zink 翻译成 GLES 的，版本不匹配就起不来窗口。" +
                    "换一个渲染器再试；1.17 以上通常要 Zink。",
                true,
            )
            "native_lib" -> advice(
                "原生库没加载起来",
                (if (one.isNotBlank()) "缺的是：$one\n" else "") +
                    "多半是这台机器的 ABI 跟运行时对不上（本应用只出 arm64-v8a），" +
                    "或者 Java 运行时解压了一半。去「Java」页把它删掉重装一次。",
                true,
            )
            "native_crash" -> advice(
                "原生层崩溃（段错误）",
                "通常来自 GPU 驱动或 LWJGL。换一个渲染器、关掉光影再试；仍然崩就把这份日志发出来。",
                true,
            )
            "jvm_start" -> advice(
                "Java 虚拟机没起来",
                "常见是分配内存超过了手机可用内存。去「设置 → 内存与 JVM」调小一档再试。",
                true,
            )

            "pixel_format", "no_opengl" -> advice(
                "拿不到可用的图形环境",
                "换一个渲染器再试。这台手机的 GPU 驱动可能不支持当前这一档。",
                true,
            )

            else -> advice("分析到错误原因（${reason.code}）", "但没有更详细的说明，把这份日志发给能帮你的人最快。", true)
        }
    }

    private fun advice(headline: String, detail: String, needHelp: Boolean) =
        CrashAdvice(headline, detail, needHelp)

    // ---------------------------------------------------------------- 工具
    /** 取第一个捕获组；取不到返回空串——归因失败不该把整条分析链炸掉。 */
    internal fun seek(text: String, pattern: String): String =
        runCatching {
            Regex(pattern, setOf(RegexOption.MULTILINE)).find(text)?.groupValues?.getOrNull(1).orEmpty()
        }.getOrDefault("")

    internal fun searchAll(text: String, pattern: String): List<String> =
        runCatching {
            Regex(pattern, setOf(RegexOption.MULTILINE)).findAll(text)
                .mapNotNull { it.groupValues.getOrNull(1) }
                .filter { it.isNotBlank() }
                .toList()
        }.getOrDefault(emptyList())

    internal fun between(text: String, left: String, right: String): String {
        val a = text.indexOf(left)
        if (a < 0) return ""
        val from = a + left.length
        val b = text.indexOf(right, from)
        return if (b < 0) text.substring(from) else text.substring(from, b)
    }

    /**
     * 从堆栈里刨可疑的第三方包名。
     *
     * 关键在那张忽略前缀表：不滤掉 `net.minecraft` / `java` / `sun` 这些，
     * 刨出来的全是游戏和 JDK 自己的类，对用户没有任何意义。
     */
    internal fun stackSuspects(stack: String): List<String> {
        val hits = searchAll(stack, """\bat ([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)+)\.""")
        return hits
            .map { it.substringBeforeLast('.') }
            .filter { it.contains('.') }
            .filterNot { candidate -> STACK_IGNORE.any { candidate == it || candidate.startsWith("$it.") } }
            .map { it.split('.').take(2).joinToString(".") }
            .distinct()
            .take(5)
    }

    // ---------------------------------------------------------------- 常量
    /** 堆栈里这些前缀是游戏、JDK、加载器自己的，报给用户没有意义。 */
    private val STACK_IGNORE = setOf(
        "java", "javax", "jdk", "sun", "com.sun", "kotlin", "scala",
        "net.minecraft", "com.mojang", "net.minecraftforge", "net.neoforged",
        "net.fabricmc", "org.quiltmc", "cpw.mods", "org.spongepowered",
        "org.apache", "org.lwjgl", "io.netty", "com.google", "it.unimi",
        "org.objectweb", "org.slf4j", "oolloo.jlw", "com.tungsten", "org.lwjglx",
    )

    private val LOADER_TOKENS = listOf("orge", "abric", "uilt", "iteloader", "eoForge")

    private val MIXIN_MARKS = listOf(
        "Mixin prepare failed ", "Mixin apply failed ", "MixinApplyError",
        "MixinTransformerError", "mixin.injection.throwables.",
    )

    private val FABRIC_SOLUTION_MARKS = listOf(
        "A potential solution has been determined:\n",
        "A potential solution has been determined, this may resolve your problem:\n",
        "确定了一种可能的解决方法，这样做可能会解决你的问题：\n",
    )

    private val JAVA_TOO_NEW_MARKS = listOf(
        "java.lang.NoSuchFieldException: ucp",
        "because module java.base does not export",
        "java.lang.ClassNotFoundException: jdk.nashorn.api.scripting.NashornScriptEngineFactory",
        "java.lang.ClassNotFoundException: java.lang.invoke.LambdaMetafactory",
    )

    private val NEED_JAVA11_MARKS = listOf(
        "has been compiled by a more recent version of the Java Runtime (class file version 55.0)",
        "sun.misc.Unsafe.defineAnonymousClass(Class,byte[],Object[])Class/invokeVirtual",
        "The requested compatibility level JAVA_11 could not be set",
    )

    private val OPTIFINE_FORGE_MARKS = listOf(
        "java.lang.NoSuchMethodError: 'void net.minecraft.client.renderer.texture.SpriteContents.",
        "java.lang.NoSuchMethodError: 'java.lang.String com.mojang.blaze3d.systems.RenderSystem.getBackendDescription",
        "java.lang.NoSuchMethodError: 'void net.minecraft.client.renderer.block.model.BakedQuad.",
        "java.lang.NoSuchMethodError: 'void net.minecraftforge.client.gui.overlay.ForgeGui.renderSelectedItemName",
        "java.lang.NoSuchMethodError: 'void net.minecraft.server.level.DistanceManager",
        "java.lang.NoSuchMethodError: 'net.minecraft.network.chat.FormattedText net.minecraft.client.gui.Font.ellipsize",
    )

    /** 安卓特有：GL4ES / Zink 翻译层跟游戏要的 GL 版本对不上。 */
    private val ANDROID_GLES_MARKS = listOf(
        "Pixel format not accelerated",
        "Failed to create window",
        "GLFW error",
        "The driver does not appear to support OpenGL",
        "OpenGL 3.2 or higher is required",
        "libgl4es",
        "GLX is not supported",
    )
}
