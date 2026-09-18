package com.pymcl.mobile

import com.pymcl.mobile.data.CrashReporter
import com.pymcl.mobile.data.CrashRules
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 崩溃归因规则，逐条钉。
 *
 * 每个用例喂的都是**真实形状**的日志片段（照着 Forge / Fabric / JVM 实际会打出来的
 * 那一行写），不是自己造的关键词——规则靠字面匹配，造出来的样本测不出真问题。
 */
class CrashRulesTest {
    private fun codes(mc: String, crash: String = "", hs: String = "") =
        CrashRules.analyze(mc, crash, hs).map { it.code }

    private fun first(mc: String, crash: String = "", hs: String = "") =
        CrashRules.analyze(mc, crash, hs).first()

    // ------------------------------------------------------------ 分档顺序
    @Test
    fun theMostCertainReasonWinsNotTheVaguestOne() {
        // 内存不够（第一档）和可疑堆栈（第三档）同时存在时，只报前者——
        // 两个都报，用户会先去折腾那个猜出来的
        val log = """
            [23:11:04] [Render thread/ERROR]: java.lang.OutOfMemoryError: Java heap space
            	at dev.someone.badmod.Renderer.tick(Renderer.java:44)
            	at net.minecraftforge.eventbus.ASMEventHandler.invoke(ASMEventHandler.java:73)
        """.trimIndent()
        assertEquals(listOf("oom"), codes(log))
    }

    @Test
    fun noLogsAtAllIsItsOwnAnswer() {
        assertEquals(listOf("no_files"), codes("", "", ""))
    }

    // ------------------------------------------------------------ 第一档
    @Test
    fun outOfMemoryIsRecognizedFromBothShapes() {
        assertTrue("oom" in codes("java.lang.OutOfMemoryError: Java heap space"))
        assertTrue("oom" in codes("Terminating due to java.lang.OutOfMemoryError: Metaspace"))
        assertTrue("oom" in codes("# There is insufficient memory ... an out of memory error"))
        assertTrue("oom" in codes("Could not reserve enough space for 2097152KB object heap"))
    }

    @Test
    fun badJvmArgumentsAreCalledOut() {
        assertTrue("jvm_args" in codes("Unrecognized option: -XX:+UseFancyGC"))
    }

    @Test
    fun extractedModFoldersAreCalledOut() {
        val log = "The directories below appear to be extracted jar files. Fix this before you continue."
        assertTrue("mod_unzipped" in codes(log))
        assertTrue("mod_unzipped" in codes("Extracted mod jars found, loading will NOT continue"))
    }

    @Test
    fun javaTooNewCoversAllFourSignatures() {
        assertTrue("java_too_new" in codes("java.lang.NoSuchFieldException: ucp"))
        assertTrue("java_too_new" in codes("... because module java.base does not export sun.security.util"))
        assertTrue(
            "java_too_new" in
                codes("java.lang.ClassNotFoundException: jdk.nashorn.api.scripting.NashornScriptEngineFactory"),
        )
        assertTrue(
            "java_too_new" in
                codes("", "Unable to make protected final java.lang.Class java.lang.ClassLoader.defineClass"),
        )
    }

    @Test
    fun javaVersionMismatchIsSeparateFromTooNew() {
        assertTrue("java_mismatch" in codes("Unsupported class file major version 65"))
        assertTrue("java_mismatch" in codes("Unsupported major.minor version 52.0"))
        assertTrue("need_java11" in codes("The requested compatibility level JAVA_11 could not be set"))
        assertTrue("openj9" in codes("Open J9 is not supported"))
        assertTrue("jdk" in codes("java.lang.ClassCastException: class jdk.internal.loader.ClassLoaders"))
    }

    @Test
    fun duplicateModsListTheJarNames() {
        val log = """
            net.minecraftforge.fml.ModLoadingException: DuplicateModsFoundException
            	mod jei : /storage/emulated/0/pymcl/.minecraft/default/mods/jei-15.2.0.27.jar
            	mod jei : /storage/emulated/0/pymcl/.minecraft/default/mods/jei-15.2.0.28.jar
        """.trimIndent()
        val reason = CrashRules.analyze(log).first { it.code == "mod_dup" }
        assertTrue("jei-15.2.0.27.jar" in reason.extras)
        assertTrue("jei-15.2.0.28.jar" in reason.extras)
    }

    @Test
    fun missingDependenciesAreListedLineByLine() {
        val log = """
            Missing or unsupported mandatory dependencies:
            	Mod ID: 'fabric-api', Requested by: 'sodium', Expected range: '>=0.92.0'
            	Mod ID: 'cloth-config', Requested by: 'sodium', Expected range: '*'
        """.trimIndent()
        val reason = CrashRules.analyze(log).first { it.code == "mod_missing" }
        assertEquals(2, reason.extras.size)
        assertTrue(reason.extras[0].contains("fabric-api"))
    }

    @Test
    fun theCulpritModIsPulledOutOfCaughtExceptionFrom() {
        val log = "Caught exception from someawesomemod (Some Awesome Mod)"
        val reason = CrashRules.analyze(log).first { it.code == "mod_certain" }
        assertTrue(reason.first.startsWith("someawesomemod"))
    }

    @Test
    fun optifineForgeIncompatibilityIsNamed() {
        val log = "java.lang.NoSuchMethodError: 'void net.minecraft.client.renderer.block.model.BakedQuad.<init>'"
        assertTrue("optifine_forge" in codes(log))
    }

    @Test
    fun debugCrashIsNotTreatedAsARealProblem() {
        val reason = CrashRules.analyze("", "Manually triggered debug crash").first()
        assertEquals("debug_crash", reason.code)
        assertFalse(CrashRules.describe(reason).needHelp)
    }

    // ------------------------------------------------------------ 第二档
    @Test
    fun mixinFailureNamesTheModWhenTheLogSaysIt() {
        val log = "Mixin apply failed sodium.mixins.json:MixinChunkRenderer from mod sodium] from phase"
        val reason = CrashRules.analyze(log).first { it.code == "mixin" }
        assertEquals("sodium", reason.first)
    }

    @Test
    fun mixinFailureWithoutANameStillReportsMixin() {
        val log = "org.spongepowered.asm.mixin.transformer.throwables.MixinTransformerError: An unexpected critical error"
        assertTrue("mixin" in codes(log))
        assertTrue(CrashRules.analyze(log).first { it.code == "mixin" }.extras.isEmpty())
    }

    @Test
    fun fabricSolutionBlockIsHandedStraightToTheUser() {
        val log = """
            A potential solution has been determined:
            	 - Replace mod 'Sodium' (sodium) 0.4.4 with version 0.5.8 or later.
            	 - Install fabric-api, version 0.92.0 or later.
            Some more log after the block
        """.trimIndent()
        val reason = CrashRules.analyze(log).first { it.code == "fabric_solution" }
        assertEquals(2, reason.extras.size)
        assertTrue(reason.extras[0].contains("Sodium"))
        // 这一条是加载器自己算出来的，不需要再让用户求助
        assertFalse(CrashRules.describe(reason).needHelp)
    }

    // ------------------------------------------------------------ 第三档
    @Test
    fun stackSuspectsSkipTheGameAndTheJdk() {
        val stack = """
            java.lang.NullPointerException
            	at net.minecraft.client.Minecraft.run(Minecraft.java:1)
            	at java.base/java.lang.Thread.run(Thread.java:840)
            	at org.spongepowered.asm.mixin.Mixin.apply(Mixin.java:2)
            	at dev.someone.badmod.Hook.tick(Hook.java:3)
            NeoForge is present
        """.trimIndent()
        val words = CrashRules.stackSuspects(stack)
        // 只有第三方那个包该被报出来
        assertTrue("dev.someone" in words)
        assertFalse(words.any { it.startsWith("net.minecraft") })
        assertFalse(words.any { it.startsWith("java") })
        assertFalse(words.any { it.startsWith("org.spongepowered") })
    }

    @Test
    fun vanillaCrashesDoNotGetStackGuesses() {
        // 日志里没有任何加载器字样时不刨堆栈——刨出来全是 net.minecraft，对用户是噪音
        val stack = """
            java.lang.NullPointerException
            	at dev.someone.badmod.Hook.tick(Hook.java:3)
        """.trimIndent()
        assertTrue(codes(stack).none { it == "stack_keyword" })
    }

    @Test
    fun badBlockAndBadEntityAreLocated() {
        val crash = """
            -- Block being ticked --
            	Block: Block{minecraft:chest}
            	Block location: World: (100,64,-200), Section: (at 4,0,8 in 6,4,-13)
        """.trimIndent()
        val reason = CrashRules.analyze("", crash).first { it.code == "bad_block" }
        assertTrue(reason.first.contains("minecraft:chest"))
        assertTrue(reason.first.contains("100,64,-200"))

        val entityCrash = """
            -- Entity being ticked --
            	Entity Type: minecraft:zombie (net.minecraft.world.entity.monster.Zombie)
            	Entity's Exact location: 12.50, 64.00, -33.20
        """.trimIndent()
        val e = CrashRules.analyze("", entityCrash).first { it.code == "bad_entity" }
        assertTrue(e.first.contains("minecraft:zombie"))
    }

    @Test
    fun aVeryShortOutputIsShownVerbatim() {
        val reason = CrashRules.analyze("Error: could not open `-Xmx`").first()
        assertEquals("tiny_output", reason.code)
        assertTrue(CrashRules.describe(reason).detail.contains("-Xmx"))
    }

    // -------------------------------------------------------- 安卓特有规则
    @Test
    fun rendererMismatchIsAnAndroidOnlyRule() {
        // 手机上 OpenGL 是 GL4ES / Zink 翻译成 GLES 的，版本对不上就开不出窗口
        assertTrue("gles_renderer" in codes("[LWJGL] GLFW error 65543: GLX: Failed to create context"))
        assertTrue("gles_renderer" in codes("OpenGL 3.2 or higher is required"))
        val advice = CrashRules.describe(CrashRules.analyze("OpenGL 3.2 or higher is required").first())
        assertTrue(advice.detail.contains("Zink"))
    }

    @Test
    fun missingNativeLibraryPointsAtTheAbiOrABrokenRuntime() {
        val log = "java.lang.UnsatisfiedLinkError: dlopen failed: library \"libopenal.so\" not found"
        val reason = CrashRules.analyze(log).first { it.code == "native_lib" }
        val advice = CrashRules.describe(reason)
        assertTrue(advice.detail.contains("arm64-v8a"))
        assertTrue(advice.detail.contains("Java"))
    }

    @Test
    fun jvmFailingToStartBlamesTheMemorySetting() {
        val log = "Error occurred during initialization of VM\nCould not reserve enough space for object heap"
        assertTrue("jvm_start" in codes(log))
        val advice = CrashRules.describe(CrashRules.analyze(log).first { it.code == "jvm_start" })
        assertTrue(advice.detail.contains("内存"))
    }

    @Test
    fun nativeSegfaultIsRecognizedFromHsErr() {
        assertTrue("native_crash" in codes("", "", "#  SIGSEGV (0xb) at pc=0x0000007f, pid=1234"))
    }

    // ------------------------------------------------------------ 文案
    @Test
    fun everyAdviceSaysSomethingAndroidUsersCanActOn() {
        // 桌面文案里的「电脑」「启动设置」在手机上没有对应物，移植时必须换掉
        listOf("jvm_args", "oom", "jdk", "java_too_new", "need_java11").forEach { code ->
            val advice = CrashRules.describe(com.pymcl.mobile.data.CrashReason(code))
            assertTrue("$code 的建议是空的", advice.detail.isNotBlank())
            assertFalse("$code 还在说「启动设置」", advice.detail.contains("启动设置"))
        }
        assertTrue(CrashRules.describe(com.pymcl.mobile.data.CrashReason("jdk")).detail.contains("Java"))
    }

    @Test
    fun unknownCodesStillProduceSomethingReadable() {
        val advice = CrashRules.describe(com.pymcl.mobile.data.CrashReason("从未见过的码"))
        assertTrue(advice.headline.contains("从未见过的码"))
        assertTrue(advice.needHelp)
    }

    // -------------------------------------------------- 跟 CrashReporter 的接线
    @Test
    fun reporterSurfacesTheAdviceNotJustTheStack() {
        val report = CrashReporter.analyze(1, "java.lang.OutOfMemoryError: Java heap space")
        assertTrue(report.advices.isNotEmpty())
        assertTrue(report.headline.contains("内存"))
        assertTrue(report.adviceText().contains("设置"))
        assertEquals("oom", report.reason)
    }

    @Test
    fun cancellingSkipsAnalysisEntirely() {
        // 用户自己点的停止不该被分析成一次崩溃
        val report = CrashReporter.analyze(143, "java.lang.OutOfMemoryError", cancelled = true)
        assertTrue(report.advices.isEmpty())
        assertEquals("游戏已退出", report.headline)
    }

    @Test
    fun theExcerptIsStillRedacted() {
        // 这一条跟脱敏那几条是一对：分析这条路加进来之后，令牌照样不能漏出去
        val report = CrashReporter.analyze(
            1,
            "--accessToken eyJhbGciOiJIUzI1NiJ9.secretsecret --username Player\njava.lang.OutOfMemoryError",
        )
        assertFalse(report.excerpt.contains("eyJhbGciOiJIUzI1NiJ9"))
        assertTrue(report.excerpt.contains("<hidden>"))
        assertTrue(report.excerpt.contains("--username Player"))
    }
}
