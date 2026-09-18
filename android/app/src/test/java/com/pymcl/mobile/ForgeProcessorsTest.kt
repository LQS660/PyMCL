package com.pymcl.mobile

import com.pymcl.mobile.data.ForgeProcessors
import com.pymcl.mobile.data.ProcessorError
import com.pymcl.mobile.data.ProcessorStep
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class ForgeProcessorsTest {
    private lateinit var root: File
    private lateinit var libs: File

    /** 「从安装器 jar 里解出这个条目」的替身：落一个同名文件就够验路径了。 */
    private fun extract(entry: String): File =
        File(root, "extracted/${entry.substringAfterLast('/')}").also {
            it.parentFile?.mkdirs()
            it.writeText(entry)
        }

    private val mainClasses = mapOf(
        "binarypatcher-1.1.1.jar" to "net.minecraftforge.binarypatcher.ConsoleTool",
        "ForgeAutoRenamingTool-1.0.1-all.jar" to "net.minecraftforge.fart.Main",
    )

    private fun mainClassOf(jar: File): String? = mainClasses[jar.name]

    @Before
    fun setUp() {
        root = kotlin.io.path.createTempDirectory("pymcl-forge").toFile()
        libs = File(root, "libraries").also { it.mkdirs() }
    }

    @After
    fun tearDown() {
        root.deleteRecursively()
    }

    private val profile = JSONObject(
        """
        {
          "json": "/version.json",
          "data": {
            "MAPPINGS": {"client": "[de.oceanlabs.mcp:mcp_config:1.20.1@zip]", "server": "x"},
            "PATCHED":  {"client": "[net.minecraftforge:forge:1.20.1-47.2.0:client]", "server": "x"},
            "SIDE_NAME": {"client": "'client'", "server": "'server'"},
            "BINPATCH": {"client": "data/client.lzma", "server": "data/server.lzma"}
          },
          "processors": [
            {
              "sides": ["client"],
              "jar": "net.minecraftforge:binarypatcher:1.1.1",
              "classpath": ["org.ow2.asm:asm:9.6"],
              "args": ["--clean", "{MINECRAFT_JAR}", "--output", "{PATCHED}", "--apply", "{BINPATCH}", "--side", "{SIDE_NAME}"],
              "outputs": {"{PATCHED}": "'deadbeef'"}
            },
            {
              "sides": ["server"],
              "jar": "net.minecraftforge:binarypatcher:1.1.1",
              "args": ["--server-only"]
            },
            {
              "jar": "net.minecraftforge:ForgeAutoRenamingTool:1.0.1:all",
              "args": ["--input", "{PATCHED}", "--map", "{MAPPINGS}", "--lib", "[org.ow2.asm:asm:9.6]"]
            }
          ],
          "libraries": [
            {"name": "net.minecraftforge:binarypatcher:1.1.1", "url": "https://maven.minecraftforge.net/"}
          ]
        }
        """.trimIndent(),
    )

    private fun data() = ForgeProcessors.resolveData(profile, libraryDir = libs, extractEntry = ::extract)

    private fun extras() = ForgeProcessors.extrasOf(root, File(root, "installer.jar"), File(root, "1.20.1.jar"))

    // ---- 基础 ------------------------------------------------------------

    @Test
    fun installerCoordinatesFollowUpstreamNaming() {
        assertEquals(
            "net.minecraftforge:forge:1.20.1-47.2.0:installer",
            ForgeProcessors.forgeInstallerCoord("1.20.1", "47.2.0"),
        )
        assertEquals(
            "net.minecraftforge:forge:1.20.1-47.2.0:installer",
            ForgeProcessors.forgeInstallerCoord("1.20.1", "1.20.1-47.2.0"),
        )
        assertEquals(
            "net.neoforged:neoforge:21.1.9:installer",
            ForgeProcessors.neoForgeInstallerCoord("21.1.9"),
        )
    }

    @Test
    fun optifineGoesThroughTheMirror() {
        assertTrue(ForgeProcessors.optifineUrl("1.20.1", "HD_U", "I6").contains("/optifine/1.20.1/HD_U/I6"))
    }

    @Test
    fun versionJsonEntryStripsTheLeadingSlash() {
        assertEquals("version.json", ForgeProcessors.versionJsonEntry(profile))
        assertEquals("version.json", ForgeProcessors.versionJsonEntry(JSONObject("{}")))
        assertEquals("a/b.json", ForgeProcessors.versionJsonEntry(JSONObject("""{"json":"/a/b.json"}""")))
    }

    @Test
    fun needsProcessorsSeparatesOldFromNew() {
        assertTrue(ForgeProcessors.needsProcessors(profile))
        assertFalse(ForgeProcessors.needsProcessors(JSONObject("{}")))
        assertFalse(ForgeProcessors.needsProcessors(JSONObject("""{"processors":[]}""")))
    }

    // ---- data 段的三种写法 ------------------------------------------------

    @Test
    fun mavenValuesBecomeLocalPaths() {
        val mappings = data().getValue("MAPPINGS")
        assertTrue(mappings.replace('\\', '/').endsWith("de/oceanlabs/mcp/mcp_config/1.20.1/mcp_config-1.20.1.zip"))
        assertTrue(mappings.startsWith(libs.absolutePath))
    }

    @Test
    fun mavenValuesKeepTheClassifier() {
        val patched = data().getValue("PATCHED")
        assertTrue(patched.replace('\\', '/').endsWith("net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-client.jar"))
    }

    @Test
    fun quotedValuesStayLiteral() {
        assertEquals("client", data().getValue("SIDE_NAME"))
    }

    @Test
    fun bareValuesAreExtractedFromTheInstaller() {
        val binpatch = data().getValue("BINPATCH")
        assertTrue(binpatch.replace('\\', '/').endsWith("extracted/client.lzma"))
        assertTrue(File(binpatch).isFile)
    }

    @Test
    fun onlyTheClientSideIsTaken() {
        val values = data().values.toList()
        assertFalse(values.any { it.contains("server") })
    }

    @Test
    fun emptyDataSectionIsFine() {
        assertTrue(ForgeProcessors.resolveData(JSONObject("{}"), libraryDir = libs, extractEntry = ::extract).isEmpty())
    }

    @Test(expected = ProcessorError::class)
    fun aBrokenMavenCoordinateIsRejected() {
        ForgeProcessors.resolveValue("[not:acoord]", libs, ::extract)
    }

    // ---- 占位符替换 ------------------------------------------------------

    @Test
    fun placeholdersComeFromDataAndExtras() {
        val d = data()
        val e = extras()
        assertEquals(d.getValue("PATCHED"), ForgeProcessors.substitute("{PATCHED}", libs, d, e))
        assertEquals("client", ForgeProcessors.substitute("{SIDE}", libs, d, e))
        assertEquals(File(root, "1.20.1.jar").absolutePath, ForgeProcessors.substitute("{MINECRAFT_JAR}", libs, d, e))
    }

    @Test
    fun extrasWinOverData() {
        val out = ForgeProcessors.substitute("{PATCHED}", libs, mapOf("PATCHED" to "from-data"), mapOf("PATCHED" to "from-extras"))
        assertEquals("from-extras", out)
    }

    @Test
    fun plainArgumentsPassThrough() {
        assertEquals("--clean", ForgeProcessors.substitute("--clean", libs, emptyMap()))
    }

    @Test
    fun inlineMavenArgumentsBecomePaths() {
        val out = ForgeProcessors.substitute("[org.ow2.asm:asm:9.6]", libs, emptyMap())
        assertTrue(out.replace('\\', '/').endsWith("org/ow2/asm/asm/9.6/asm-9.6.jar"))
    }

    @Test
    fun anUnknownPlaceholderIsAnErrorNotAFilename() {
        // 留在命令行里的话 processor 会把 {NOPE} 当真实文件名去找，报的错指不到根因
        try {
            ForgeProcessors.substitute("{NOPE}", libs, emptyMap())
            throw AssertionError("应当报错")
        } catch (e: ProcessorError) {
            assertTrue(e.message!!.contains("{NOPE}"))
        }
    }

    // ---- 展开成命令行 ----------------------------------------------------

    @Test
    fun planKeepsOnlyTheClientSteps() {
        val steps = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf)
        assertEquals(2, steps.size)
        assertFalse(steps.any { it.args.contains("--server-only") })
    }

    @Test
    fun stepsWithoutASidesListAreKept() {
        val steps = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf)
        assertTrue(steps.any { it.mainClass == "net.minecraftforge.fart.Main" })
    }

    @Test
    fun theProcessorJarLeadsItsOwnClasspath() {
        val step = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf).first()
        assertTrue(step.classpath.first().replace('\\', '/').endsWith("binarypatcher-1.1.1.jar"))
        assertTrue(step.classpath.any { it.replace('\\', '/').endsWith("asm-9.6.jar") })
        assertEquals(step.classpath.size, step.classpath.toSet().size)
    }

    @Test
    fun argumentsAreFullyResolved() {
        val step = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf).first()
        assertFalse(step.args.any { it.startsWith("{") })
        assertTrue(step.args.contains("--clean"))
        assertEquals(File(root, "1.20.1.jar").absolutePath, step.args[step.args.indexOf("--clean") + 1])
        assertEquals("client", step.args.last())
    }

    @Test
    fun outputKeysAndHashesAreResolvedToo() {
        val step = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf).first()
        assertEquals(1, step.outputs.size)
        assertEquals(data().getValue("PATCHED"), step.outputs.keys.first())
        assertEquals("deadbeef", step.outputs.values.first())
    }

    @Test
    fun commandLineStartsWithClasspathThenMainClass() {
        val step = ForgeProcessors.plan(profile, libs, data(), extras(), ::mainClassOf).first()
        val cmd = step.commandLine(";")
        assertEquals("-cp", cmd[0])
        assertTrue(cmd[1].contains(";"))
        assertEquals("net.minecraftforge.binarypatcher.ConsoleTool", cmd[2])
        assertEquals(step.args, cmd.drop(3))
    }

    @Test(expected = ProcessorError::class)
    fun aJarWithoutMainClassIsRejected() {
        ForgeProcessors.plan(profile, libs, data(), extras(), mainClassOf = { null })
    }

    @Test(expected = ProcessorError::class)
    fun aProcessorWithoutAJarIsRejected() {
        ForgeProcessors.buildStep(JSONObject("""{"args":[]}"""), libs, emptyMap(), emptyMap(), ::mainClassOf)
    }

    @Test
    fun noProcessorsMeansAnEmptyPlan() {
        assertTrue(ForgeProcessors.plan(JSONObject("{}"), libs, emptyMap(), emptyMap(), ::mainClassOf).isEmpty())
    }

    // ---- 产物核对 --------------------------------------------------------

    @Test
    fun missingOutputIsReported() {
        val step = ProcessorStep("j", "M", emptyList(), emptyList(), mapOf(File(root, "gone.jar").path to ""))
        assertEquals(1, ForgeProcessors.verifyOutputs(step) { "" }.size)
    }

    @Test
    fun presentOutputWithoutAHashPasses() {
        val f = File(root, "out.jar").also { it.writeText("x") }
        val step = ProcessorStep("j", "M", emptyList(), emptyList(), mapOf(f.path to ""))
        assertTrue(ForgeProcessors.verifyOutputs(step) { "" }.isEmpty())
    }

    @Test
    fun mismatchedHashIsReported() {
        val f = File(root, "out.jar").also { it.writeText("x") }
        val step = ProcessorStep("j", "M", emptyList(), emptyList(), mapOf(f.path to "'aaaa'"))
        assertEquals(1, ForgeProcessors.verifyOutputs(step) { "bbbb" }.size)
    }

    @Test
    fun matchingHashPassesRegardlessOfCase() {
        val f = File(root, "out.jar").also { it.writeText("x") }
        val step = ProcessorStep("j", "M", emptyList(), emptyList(), mapOf(f.path to "AAAA"))
        assertTrue(ForgeProcessors.verifyOutputs(step) { "aaaa" }.isEmpty())
    }

    @Test
    fun quotedLiteralsAreUnquotedAtPlanTime() {
        // 脱引号放在 substitute 里做一次，下游（参数、产物校验和）就不用各自再想一遍
        assertEquals("client", ForgeProcessors.substitute("'client'", libs, emptyMap()))
        assertEquals("deadbeef", ForgeProcessors.substitute("'deadbeef'", libs, emptyMap()))
    }

    @Test
    fun profileLibrariesReuseTheLoaderInstallShape() {
        val libsOut = ForgeProcessors.libraries(profile)
        assertEquals(1, libsOut.size)
        assertEquals("net/minecraftforge/binarypatcher/1.1.1/binarypatcher-1.1.1.jar", libsOut.single().path)
        assertTrue(libsOut.single().urls.any { it.startsWith("https://maven.minecraftforge.net/") })
    }

    @Test
    fun extrasCoverEveryWellKnownToken() {
        val e = extras()
        listOf("SIDE", "ROOT", "INSTALLER", "LIBRARY_DIR", "MINECRAFT_JAR").forEach {
            assertTrue(it, e.containsKey(it))
        }
        assertNull(e["NOPE"])
    }
}
