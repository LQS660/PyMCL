package com.pymcl.mobile

import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.Http
import com.pymcl.mobile.data.Installer
import com.pymcl.mobile.data.JavaRuntime
import com.pymcl.mobile.data.LaunchArgs
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.ManifestRepo
import com.pymcl.mobile.data.Names
import com.pymcl.mobile.model.VersionRow
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class CoreLogicTest {
    @Test
    fun sanitizeStripsIllegal() {
        assertEquals("abc-def", Names.sanitize("abc/def"))
        assertEquals("游戏", Names.sanitize("   "))
        assertEquals("CON-游戏", Names.sanitize("CON"))
    }

    @Test
    fun bmclRewritesLibraries() {
        val u = "https://libraries.minecraft.net/com/mojang/patchy/1.1/patchy-1.1.jar"
        val m = Names.rewriteBmcl(u)
        assertTrue(m!!.startsWith("https://bmclapi2.bangbang93.com/maven/"))
        assertEquals(listOf(m, u), Names.expand(u))
    }

    @Test
    fun sha1Known() {
        assertEquals("a94a8fe5ccb19ba61c4c0873d391e987982fbbd3", Http.sha1OfString("test"))
    }

    @Test
    fun manifestParse() {
        val json = JSONObject(
            """{"versions":[{"id":"1.20.1","type":"release","url":"https://x","sha1":"a","releaseTime":"t"}]}""",
        )
        val rows = ManifestRepo.parse(json)
        assertEquals(1, rows.size)
        assertEquals("1.20.1", rows[0].id)
        assertEquals("release", rows[0].type)
        assertEquals("https://x", rows[0].url)
        assertEquals("a", rows[0].sha1)
    }

    @Test
    fun libraryRulesSkipWindowsOsx() {
        val windows = JSONObject(
            """{"name":"org.lwjgl:lwjgl:3.3.1:natives-windows","rules":[{"action":"allow","os":{"name":"windows"}}],"downloads":{"artifact":{"path":"org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar"}}}""",
        )
        val osx = JSONObject(
            """{"name":"ca.weblite:java-objc-bridge:1.1","rules":[{"action":"allow","os":{"name":"osx"}}],"downloads":{"artifact":{"path":"ca/weblite/java-objc-bridge/1.1/java-objc-bridge-1.1.jar"}}}""",
        )
        val universal = JSONObject(
            """{"name":"com.mojang:patchy:1.1","downloads":{"artifact":{"path":"com/mojang/patchy/1.1/patchy-1.1.jar"}}}""",
        )
        val notOsx = JSONObject(
            """{"name":"com.google.guava:guava:32.1.2-jre","rules":[{"action":"allow"},{"action":"disallow","os":{"name":"osx"}}],"downloads":{"artifact":{"path":"com/google/guava/guava/32.1.2-jre/guava-32.1.2-jre.jar"}}}""",
        )
        assertFalse(Installer.allowedByRules(windows))
        assertFalse(Installer.allowedByRules(osx))
        assertTrue(Installer.allowedByRules(universal))
        assertTrue(Installer.allowedByRules(notOsx))
        assertTrue(Installer.skipReason(windows)!!.contains("windows"))
        assertTrue(Installer.skipReason(osx)!!.contains("osx"))
        assertNull(Installer.skipReason(universal))
        assertEquals("com/mojang/patchy/1.1/patchy-1.1.jar", Installer.artifactRelPath(universal))
        assertNull(Installer.artifactRelPath(windows))
        assertNull(Installer.artifactRelPath(osx))
    }

    @Test
    fun nativesClassifiersSkipped() {
        val lwjgl2 = JSONObject(
            """{"name":"org.lwjgl.lwjgl:lwjgl:2.9.4","natives":{"windows":"natives-windows","linux":"natives-linux","osx":"natives-osx"},"downloads":{"artifact":{"path":"org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4.jar"},"classifiers":{"natives-windows":{"path":"org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4-natives-windows.jar"}}}}""",
        )
        val linuxNatives = JSONObject(
            """{"name":"org.lwjgl:lwjgl:3.3.1:natives-linux","rules":[{"action":"allow","os":{"name":"linux"}}],"downloads":{"artifact":{"path":"org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-linux.jar"}}}""",
        )
        assertTrue(Installer.hasNativesClassifiers(lwjgl2))
        assertEquals("org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4.jar", Installer.artifactRelPath(lwjgl2))
        assertNull(Installer.skipReason(lwjgl2))
        assertTrue(Installer.allowedByRules(linuxNatives))
        assertTrue(Installer.isNativesArtifact(linuxNatives))
        assertTrue(Installer.skipReason(linuxNatives)!!.contains("LWJGL"))
        assertNull(Installer.artifactRelPath(linuxNatives))
    }

    @Test
    fun searchKindEmptyDoesNotNeedNetwork() {
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("mod", ""))
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("整合包", "   "))
        assertEquals(emptyList<Any>(), CatalogRepo.searchKind("资源包", "\t"))
    }

    @Test
    fun launchPlanSkipsWindowsOsxAndNatives() {
        val root = kotlin.io.path.createTempDirectory("pymcl-test").toFile()
        try {
            val vdir = File(root, "versions/1.20.1")
            vdir.mkdirs()
            File(vdir, "1.20.1.jar").writeText("jar")
            File(vdir, "1.20.1.json").writeText(
                """
                {
                  "mainClass": "net.minecraft.client.main.Main",
                  "libraries": [
                    {
                      "name": "com.mojang:patchy:1.1",
                      "downloads": { "artifact": { "path": "com/mojang/patchy/1.1/patchy-1.1.jar" } }
                    },
                    {
                      "name": "org.lwjgl:lwjgl:3.3.1:natives-windows",
                      "downloads": { "artifact": { "path": "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar" } },
                      "rules": [{ "action": "allow", "os": { "name": "windows" } }]
                    },
                    {
                      "name": "ca.weblite:java-objc-bridge:1.1",
                      "rules": [{ "action": "allow", "os": { "name": "osx" } }],
                      "downloads": { "artifact": { "path": "ca/weblite/java-objc-bridge/1.1/java-objc-bridge-1.1.jar" } }
                    },
                    {
                      "name": "org.lwjgl.lwjgl:lwjgl:2.9.4",
                      "natives": { "windows": "natives-windows" },
                      "downloads": {
                        "artifact": { "path": "org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4.jar" },
                        "classifiers": { "natives-windows": { "path": "org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4-natives-windows.jar" } }
                      }
                    }
                  ]
                }
                """.trimIndent(),
            )
            File(root, "libraries/com/mojang/patchy/1.1").mkdirs()
            File(root, "libraries/com/mojang/patchy/1.1/patchy-1.1.jar").writeText("a")
            File(root, "libraries/org/lwjgl/lwjgl/lwjgl/2.9.4").mkdirs()
            File(root, "libraries/org/lwjgl/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4.jar").writeText("b")

            val plan = LaunchPlanner.plan("t", "1.20.1", "Player", 2048, instDir = root)
            assertEquals("net.minecraft.client.main.Main", plan.mainClass)
            assertTrue(plan.classpath.any { it.replace('\\', '/').endsWith("patchy-1.1.jar") })
            assertTrue(plan.classpath.any { it.replace('\\', '/').endsWith("lwjgl-2.9.4.jar") })
            assertTrue(plan.classpath.none { it.contains("natives-windows") })
            assertTrue(plan.classpath.none { it.contains("java-objc-bridge") })
            assertTrue(plan.missing.none { it.contains("natives-windows") })
            assertTrue(plan.missing.none { it.contains("java-objc-bridge") })
            assertTrue(plan.nativesMissing)
            assertTrue(plan.missing.isEmpty())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun inheritsFromMergesLibrariesAndParentJar() {
        val root = kotlin.io.path.createTempDirectory("pymcl-inh").toFile()
        try {
            File(root, "versions/1.20.1").mkdirs()
            File(root, "versions/1.20.1/1.20.1.jar").writeText("jar")
            File(root, "versions/1.20.1/1.20.1.json").writeText(
                """{"id":"1.20.1","mainClass":"net.minecraft.client.main.Main","libraries":[{"name":"com.mojang:patchy:1.1","downloads":{"artifact":{"path":"com/mojang/patchy/1.1/patchy-1.1.jar"}}}]}""",
            )
            File(root, "versions/1.20.1-fabric").mkdirs()
            File(root, "versions/1.20.1-fabric/1.20.1-fabric.json").writeText(
                """{"id":"1.20.1-fabric","inheritsFrom":"1.20.1","mainClass":"net.fabricmc.loader.impl.launch.knot.KnotClient","libraries":[{"name":"net.fabricmc:fabric-loader:0.16.0","downloads":{"artifact":{"path":"net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar"}}}]}""",
            )
            File(root, "libraries/com/mojang/patchy/1.1").mkdirs()
            File(root, "libraries/com/mojang/patchy/1.1/patchy-1.1.jar").writeText("a")
            File(root, "libraries/net/fabricmc/fabric-loader/0.16.0").mkdirs()
            File(root, "libraries/net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar").writeText("b")
            File(root, "versions/1.20.1-fabric/pymcl.json").writeText("""{"isolation":"all"}""")

            val plan = LaunchPlanner.plan("t", "1.20.1-fabric", "Player", 2048, instDir = root)
            assertEquals("net.fabricmc.loader.impl.launch.knot.KnotClient", plan.mainClass)
            assertTrue(plan.classpath.any { it.replace('\\', '/').endsWith("patchy-1.1.jar") })
            assertTrue(plan.classpath.any { it.replace('\\', '/').endsWith("fabric-loader-0.16.0.jar") })
            assertTrue(plan.classpath.any { it.replace('\\', '/').endsWith("1.20.1.jar") })
            assertTrue(plan.missing.isEmpty())
            assertTrue(plan.gameDir.replace('\\', '/').endsWith("versions/1.20.1-fabric"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun publicAiUsesHttpLowercaseHost() {
        assertEquals("http://new.s.3q.hair/v1", AiRepo.PUBLIC_BASE)
        assertEquals("deepseek-v4-flash", AiRepo.MODEL)
        val body = AiRepo.chatBody("下一款游戏")
        assertTrue(body.contains("deepseek-v4-flash"))
        assertTrue(body.contains("下一款游戏"))
        val reply = AiRepo.parseChatReply(
            """{"choices":[{"message":{"role":"assistant","content":"好"}}]}""",
        )
        assertEquals("好", reply)
        val err = AiRepo.formatError(
            429,
            """{"error":{"message":"1分钟内最多请求5次","type":"new_api_error"}}""",
        )
        assertTrue(err.contains("429"))
        assertTrue(err.contains("1分钟内最多请求5次"))
    }

    @Test
    fun defaultVersionPrefersInstalledThen121() {
        val rows = listOf(
            VersionRow("26.2", "release", "u"),
            VersionRow("1.21.1", "release", "u"),
            VersionRow("1.20.1", "release", "u"),
        )
        assertEquals("1.20.1", Names.pickDefaultVersion(rows, listOf("1.20.1")))
        assertEquals("1.21.1", Names.pickDefaultVersion(rows, emptyList()))
        assertEquals("26.2", Names.pickDefaultVersion(listOf(rows[0]), emptyList()))
    }

    @Test
    fun javaRuntimePicksJreAndLwjgl() {
        val v17 = JSONObject("""{"id":"1.20.1","javaVersion":{"majorVersion":17},"libraries":[{"name":"org.lwjgl:lwjgl:3.3.1"}]}""")
        val v21 = JSONObject("""{"id":"1.21.1","javaVersion":{"majorVersion":21},"libraries":[{"name":"org.lwjgl:lwjgl:3.3.3"}]}""")
        val v34 = JSONObject("""{"id":"26.1","javaVersion":{"majorVersion":21},"libraries":[{"name":"org.lwjgl:lwjgl:3.4.1"}]}""")
        assertEquals(17, JavaRuntime.javaMajor(v17, "1.20.1"))
        assertEquals("jre17", JavaRuntime.jreDirName(17))
        assertEquals(21, JavaRuntime.javaMajor(v21, "1.21.1"))
        assertEquals("jre21", JavaRuntime.jreDirName(21))
        assertEquals("3.3.3", JavaRuntime.lwjglPack(v21))
        assertEquals("3.4.1", JavaRuntime.lwjglPack(v34))
        assertTrue(JavaRuntime.needsLwjglX(JSONObject("""{"libraries":[{"name":"org.lwjgl.lwjgl:lwjgl:2.9.4"}]}""")))
        assertFalse(JavaRuntime.needsLwjglX(v21))
        assertEquals("12", JavaRuntime.assetIndex(JSONObject("""{"assetIndex":{"id":"12"}}""")))
        assertTrue(JavaRuntime.isLwjglLibraryPath("libraries/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar"))
        assertFalse(JavaRuntime.isLwjglLibraryPath("libraries/com/mojang/patchy/1.1/patchy-1.1.jar"))
        assertEquals(36, JavaRuntime.offlineUuid("Player").length)
    }

    @Test
    fun gameArgsSkipQuickPlayKeepResolution() {
        val json = JSONObject(
            """
            {"arguments":{"game":[
              "--username","Player",
              {"rules":[{"action":"allow","features":{"has_custom_resolution":true}}],"value":["--width","${'$'}{resolution_width}"]},
              {"rules":[{"action":"allow","features":{"is_quick_play_singleplayer":true}}],"value":["--quickPlaySingleplayer","${'$'}{quickPlaySingleplayer}"]},
              {"rules":[{"action":"allow","features":{"is_demo_user":true}}],"value":"--demo"}
            ]}}
            """.trimIndent(),
        )
        val args = LaunchArgs.extractGameArgs(json)
        assertTrue(args.contains("--username"))
        assertTrue(args.contains("--width"))
        assertFalse(args.any { it.contains("quickPlay") })
        assertFalse(args.contains("--demo"))
    }
}
