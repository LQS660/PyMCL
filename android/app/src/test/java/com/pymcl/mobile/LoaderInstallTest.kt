package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogFiles
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.Loader
import com.pymcl.mobile.data.LoaderError
import com.pymcl.mobile.data.LoaderInstall
import com.pymcl.mobile.data.PackDownloader
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.data.VersionOps
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class LoaderInstallTest {
    private lateinit var inst: File

    /** 只落一个占位文件，一行网络代码都不沾。 */
    private val fakeDownloader = PackDownloader { urls, dest, _, _ ->
        if (urls.isEmpty()) throw IllegalStateException("没有地址")
        dest.parentFile?.mkdirs()
        dest.writeText(urls.first())
    }

    private fun fetcherOf(body: String?) = TextFetcher { _, _ -> body }

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-loader").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    private fun vanilla(mc: String = "1.20.1") {
        File(inst, "versions/$mc").mkdirs()
        File(inst, "versions/$mc/$mc.json").writeText(
            """{"id":"$mc","mainClass":"net.minecraft.client.main.Main","assetIndex":{"id":"5"},
               "libraries":[{"name":"com.mojang:patchy:1.1","downloads":{"artifact":{"path":"com/mojang/patchy/1.1/patchy-1.1.jar"}}}]}""",
        )
        File(inst, "versions/$mc/$mc.jar").writeText("jar")
        File(inst, "libraries/com/mojang/patchy/1.1").mkdirs()
        File(inst, "libraries/com/mojang/patchy/1.1/patchy-1.1.jar").writeText("a")
    }

    private val fabricProfile = """
        {
          "id": "fabric-loader-0.16.0-1.20.1",
          "inheritsFrom": "1.20.1",
          "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
          "assetIndex": {"id": "should-be-dropped"},
          "downloads": {"client": {"url": "https://x"}},
          "libraries": [
            {"name": "net.fabricmc:fabric-loader:0.16.0", "url": "https://maven.fabricmc.net/"},
            {"name": "org.ow2.asm:asm:9.6", "url": "https://maven.fabricmc.net/"}
          ]
        }
    """.trimIndent()

    // ---- 名字与地址 ------------------------------------------------------

    @Test
    fun loaderOfNormalizesAliases() {
        assertEquals(Loader.FABRIC, Loader.of("Fabric"))
        assertEquals(Loader.NEOFORGE, Loader.of("NeoForge"))
        assertEquals(Loader.FORGE, Loader.of("forge"))
        assertEquals(Loader.QUILT, Loader.of("Quilt-Loader"))
        assertNull(Loader.of("liteloader"))
    }

    @Test
    fun versionIdFollowsHmclNaming() {
        assertEquals("1.20.1-fabric-0.16.0", LoaderInstall.versionIdOf(Loader.FABRIC, "1.20.1", "0.16.0"))
        assertEquals("1.20.1-quilt-0.26", LoaderInstall.versionIdOf(Loader.QUILT, "1.20.1", "0.26"))
        assertEquals("1.20.1-neoforge-47.1.0", LoaderInstall.versionIdOf(Loader.NEOFORGE, "1.20.1", "47.1.0"))
    }

    @Test
    fun forgeVersionIdDropsTheDuplicatedMcPrefix() {
        assertEquals("1.20.1-forge-47.2.0", LoaderInstall.versionIdOf(Loader.FORGE, "1.20.1", "1.20.1-47.2.0"))
        assertEquals("1.20.1-forge-47.2.0", LoaderInstall.versionIdOf(Loader.FORGE, "1.20.1", "47.2.0"))
    }

    @Test
    fun buildListUrlsPointAtTheRightMeta() {
        assertTrue(LoaderInstall.buildListUrls(Loader.FABRIC, "1.20.1").single().startsWith(LoaderInstall.FABRIC_META))
        assertTrue(LoaderInstall.buildListUrls(Loader.QUILT, "1.20.1").single().startsWith(LoaderInstall.QUILT_META))
        assertEquals(3, LoaderInstall.buildListUrls(Loader.FORGE, "1.20.1").size)
    }

    @Test
    fun profileUrlsOnlyExistForMetaOnlyLoaders() {
        assertTrue(LoaderInstall.profileJsonUrls(Loader.FABRIC, "1.20.1", "0.16.0").isNotEmpty())
        assertTrue(LoaderInstall.profileJsonUrls(Loader.FORGE, "1.20.1", "47.2.0").isEmpty())
        assertTrue(LoaderInstall.isMetaOnly(Loader.FABRIC))
        assertFalse(LoaderInstall.isMetaOnly(Loader.NEOFORGE))
    }

    // ---- 构建号解析 ------------------------------------------------------

    @Test
    fun parseLoaderBuildsReadsVersionAndStability() {
        val builds = LoaderInstall.parseLoaderBuilds(
            """[{"loader":{"version":"0.16.0","stable":true}},{"loader":{"version":"0.16.1","stable":false}}]""",
        )
        assertEquals(listOf("0.16.0", "0.16.1"), builds.map { it.id })
        assertTrue(builds[0].stable)
        assertFalse(builds[1].stable)
    }

    @Test
    fun parseLoaderBuildsToleratesGarbage() {
        assertTrue(LoaderInstall.parseLoaderBuilds("not json").isEmpty())
        assertTrue(LoaderInstall.parseLoaderBuilds("""[{"loader":{}},{}]""").isEmpty())
    }

    @Test
    fun parseMavenVersionsPullsEveryEntry() {
        val xml = "<metadata><versioning><versions><version>1.20.1-47.2.0</version><version>1.19.2-43.2.0</version></versions></versioning></metadata>"
        assertEquals(listOf("1.20.1-47.2.0", "1.19.2-43.2.0"), LoaderInstall.parseMavenVersions(xml))
    }

    @Test
    fun parseBmclForgePrefixesTheMcVersion() {
        assertEquals(
            listOf("1.20.1-47.2.0", "1.20.1-47.1.0"),
            LoaderInstall.parseBmclForge("""[{"version":"47.2.0"},{"version":"47.1.0"},{}]""", "1.20.1"),
        )
    }

    @Test
    fun filterForgeVersionsKeepsOnlyThisMcAndSortsNewestFirst() {
        val all = listOf("1.19.2-43.2.0", "1.20.1-47.1.0", "1.20.1-47.2.0", "1.20.1-47.10.0")
        assertEquals(
            listOf("1.20.1-47.10.0", "1.20.1-47.2.0", "1.20.1-47.1.0"),
            LoaderInstall.filterForgeVersions(all, "1.20.1"),
        )
    }

    @Test
    fun forgeSortKeyIsNumericNotLexical() {
        assertTrue(LoaderInstall.forgeSortKey("1.20.1-47.10.0", "1.20.1") > LoaderInstall.forgeSortKey("1.20.1-47.2.0", "1.20.1"))
        assertEquals(-1L, LoaderInstall.forgeSortKey("1.20.1-weird", "1.20.1"))
    }

    @Test
    fun neoforgePrefixUsesTheTableThenDerives() {
        assertEquals("47.1", LoaderInstall.neoforgePrefix("1.20.1"))
        assertEquals("21.4", LoaderInstall.neoforgePrefix("1.21.4"))
        assertEquals("", LoaderInstall.neoforgePrefix("1.19.2"))
        assertEquals("", LoaderInstall.neoforgePrefix(""))
    }

    @Test
    fun filterNeoForgeReturnsNothingRatherThanEverything() {
        // 前缀推不出来时宁可给空表：不过滤会把别的 MC 版本的构建混进下拉框
        val all = listOf("21.4.1-beta", "20.4.100", "21.4.2")
        assertTrue(LoaderInstall.filterNeoForgeVersions(all, "1.19.2").isEmpty())
        assertEquals(listOf("21.4.2", "21.4.1-beta"), LoaderInstall.filterNeoForgeVersions(all, "1.21.4"))
    }

    @Test
    fun filterNeoForgeFallsBackToTheOldNumbering() {
        // 1.20.1 的号段是 47.1.x，但早期构建用的是 `<mc>-<build>`，两种都得认
        assertEquals(listOf("1.20.1-47.1.0"), LoaderInstall.filterNeoForgeVersions(listOf("1.20.1-47.1.0"), "1.20.1"))
    }

    // ---- maven 坐标 ------------------------------------------------------

    @Test
    fun mavenPathExpandsGroupToFolders() {
        assertEquals(
            "net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar",
            LoaderInstall.mavenPath("net.fabricmc:fabric-loader:0.16.0"),
        )
    }

    @Test
    fun mavenPathKeepsClassifierAndExtension() {
        assertEquals(
            "a/b/1.0/b-1.0-natives-linux.jar",
            LoaderInstall.mavenPath("a:b:1.0:natives-linux"),
        )
        assertEquals("a/b/1.0/b-1.0.zip", LoaderInstall.mavenPath("a:b:1.0@zip"))
    }

    @Test
    fun mavenPathRejectsIncompleteCoordinates() {
        assertNull(LoaderInstall.mavenPath("a:b"))
        assertNull(LoaderInstall.mavenPath(""))
    }

    // ---- 版本 json 合成 --------------------------------------------------

    @Test
    fun normalizeProfileRewritesIdAndParent() {
        val out = LoaderInstall.normalizeProfile(JSONObject(fabricProfile), "1.20.1", "1.20.1-fabric-0.16.0")
        assertEquals("1.20.1-fabric-0.16.0", out.getString("id"))
        assertEquals("1.20.1", out.getString("inheritsFrom"))
        assertEquals("net.fabricmc.loader.impl.launch.knot.KnotClient", out.getString("mainClass"))
    }

    @Test
    fun normalizeProfileDropsWhatTheParentAlreadyOwns() {
        val out = LoaderInstall.normalizeProfile(JSONObject(fabricProfile), "1.20.1", "x")
        assertFalse(out.has("assetIndex"))
        assertFalse(out.has("downloads"))
    }

    @Test(expected = LoaderError::class)
    fun normalizeProfileRejectsProfileWithoutMainClass() {
        LoaderInstall.normalizeProfile(JSONObject("""{"id":"x","libraries":[]}"""), "1.20.1", "x")
    }

    @Test
    fun librariesOfBuildsThreeCandidateUrls() {
        val libs = LoaderInstall.librariesOf(JSONObject(fabricProfile))
        assertEquals(2, libs.size)
        val loaderLib = libs.first { it.path.contains("fabric-loader") }
        assertEquals("net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar", loaderLib.path)
        assertTrue(loaderLib.urls.any { it.startsWith("https://maven.fabricmc.net/") })
        assertTrue(loaderLib.urls.any { it.contains("bmclapi") })
    }

    @Test
    fun librariesOfPrefersTheDeclaredArtifactUrl() {
        val libs = LoaderInstall.librariesOf(
            JSONObject(
                """{"libraries":[{"name":"a:b:1.0","downloads":{"artifact":{"path":"a/b/1.0/b-1.0.jar","url":"https://direct/b.jar","sha1":"aa","size":7}}}]}""",
            ),
        )
        assertEquals("https://direct/b.jar", libs.single().urls.first())
        assertEquals("aa", libs.single().sha1)
        assertEquals(7L, libs.single().size)
    }

    @Test
    fun librariesOfSkipsOtherPlatforms() {
        val libs = LoaderInstall.librariesOf(
            JSONObject(
                """{"libraries":[{"name":"a:b:1.0","rules":[{"action":"allow","os":{"name":"windows"}}],"downloads":{"artifact":{"path":"a/b/1.0/b-1.0.jar"}}}]}""",
            ),
        )
        assertTrue(libs.isEmpty())
    }

    // ---- 落盘与继承链 ----------------------------------------------------

    @Test(expected = LoaderError::class)
    fun installRefusesWithoutTheVanillaVersion() {
        LoaderInstall.installProfile(
            inst, "1.20.1", "1.20.1-fabric-0.16.0",
            LoaderInstall.normalizeProfile(JSONObject(fabricProfile), "1.20.1", "1.20.1-fabric-0.16.0"),
            fakeDownloader,
        )
    }

    @Test
    fun installWritesVersionJsonAndLibraries() {
        vanilla()
        val id = LoaderInstall.installMetaLoader(
            inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader,
        )
        assertEquals("1.20.1-fabric-0.16.0", id)
        assertTrue(File(inst, "versions/$id/$id.json").isFile)
        assertTrue(File(inst, "libraries/net/fabricmc/fabric-loader/0.16.0/fabric-loader-0.16.0.jar").isFile)
        assertTrue(File(inst, "libraries/org/ow2/asm/asm/9.6/asm-9.6.jar").isFile)
    }

    @Test
    fun installedLoaderShowsUpAsAnInstalledVersion() {
        vanilla()
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        val cards = VersionOps.cards(inst).map { it.id }
        assertTrue(cards.contains("1.20.1"))
        assertTrue(cards.contains("1.20.1-fabric-0.16.0"))
    }

    @Test
    fun installedLoaderIsDetectedAsFabric() {
        vanilla()
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        val card = VersionOps.card(inst, "1.20.1-fabric-0.16.0")
        assertEquals("Fabric", card.loader)
        assertEquals("1.20.1", card.mc)
    }

    @Test
    fun inheritsFromChainResolvesAfterInstall() {
        vanilla()
        val id = LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        assertEquals(listOf(id, "1.20.1"), LaunchPlanner.chain(inst, id))
        val merged = LaunchPlanner.resolveJson(inst, id)
        assertEquals("net.fabricmc.loader.impl.launch.knot.KnotClient", merged.getString("mainClass"))
        // 父版本的 assetIndex 得透过来，子版本里我们特意删掉了它
        assertEquals("5", merged.getJSONObject("assetIndex").getString("id"))
    }

    @Test
    fun planUsesTheParentJarAndBothLibrarySets() {
        vanilla()
        val id = LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        val plan = LaunchPlanner.plan("t", id, "Player", 2048, inst)
        assertTrue(plan.missing.isEmpty())
        assertTrue(plan.classpath.any { it.endsWith("1.20.1.jar") })
        assertTrue(plan.classpath.any { it.endsWith("patchy-1.1.jar") })
        assertTrue(plan.classpath.any { it.endsWith("fabric-loader-0.16.0.jar") })
        assertEquals("net.fabricmc.loader.impl.launch.knot.KnotClient", plan.mainClass)
    }

    @Test
    fun installIsIdempotentOnSecondRun() {
        vanilla()
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader)
        assertEquals(2, VersionOps.cards(inst).size)
    }

    @Test
    fun installReportsProgressToCompletion() {
        vanilla()
        var last = 0 to 0
        LoaderInstall.installMetaLoader(
            inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(fabricProfile), fakeDownloader,
            onProgress = { cur, total -> last = cur to total },
        )
        assertEquals(2 to 2, last)
    }

    @Test(expected = LoaderError::class)
    fun metaLoaderFailsLoudlyWhenUpstreamIsDown() {
        vanilla()
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf(null), fakeDownloader)
    }

    @Test(expected = LoaderError::class)
    fun metaLoaderRejectsNonJsonProfile() {
        vanilla()
        LoaderInstall.installMetaLoader(inst, Loader.FABRIC, "1.20.1", "0.16.0", fetcherOf("<html>502</html>"), fakeDownloader)
    }

    @Test
    fun forgeSaysWhyItCannotRunYet() {
        vanilla()
        try {
            LoaderInstall.installMetaLoader(inst, Loader.FORGE, "1.20.1", "47.2.0", fetcherOf("{}"), fakeDownloader)
            throw AssertionError("应当明确拒绝")
        } catch (e: LoaderError) {
            assertTrue(e.message!!.contains("processors"))
        }
    }

    @Test
    fun jsonHeadersAskForJson() {
        assertEquals("application/json", CatalogFiles.JSON_HEADERS["Accept"])
    }

    // ---- 要跑 processors 的那一支 ----------------------------------------

    /** 造一个最小但形状真实的 Forge 安装器 jar。 */
    private fun forgeInstaller(withProcessors: Boolean): File {
        val patched = "net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-client.jar"
        val processors = if (!withProcessors) "[]" else """
            [{"sides":["client"],"jar":"net.minecraftforge:binarypatcher:1.1.1",
              "args":["--clean","{MINECRAFT_JAR}","--output","{PATCHED}"],
              "outputs":{"{PATCHED}":""}}]
        """.trimIndent()
        val profile = """
            {"json":"/version.json",
             "data":{"PATCHED":{"client":"[net.minecraftforge:forge:1.20.1-47.2.0:client]","server":"x"}},
             "processors":$processors,
             "libraries":[{"name":"net.minecraftforge:binarypatcher:1.1.1","url":"https://maven.minecraftforge.net/"}]}
        """.trimIndent()
        val versionJson = """
            {"id":"upstream-name","inheritsFrom":"1.20.1","mainClass":"cpw.mods.bootstraplauncher.BootstrapLauncher",
             "libraries":[{"name":"net.minecraftforge:forge:1.20.1-47.2.0","url":"https://maven.minecraftforge.net/"}]}
        """.trimIndent()
        val f = File(inst, "forge-installer.jar")
        java.util.zip.ZipOutputStream(f.outputStream()).use { zip ->
            mapOf(
                "install_profile.json" to profile,
                "version.json" to versionJson,
                "data/client.lzma" to "binpatch",
            ).forEach { (name, body) ->
                zip.putNextEntry(java.util.zip.ZipEntry(name))
                zip.write(body.toByteArray())
                zip.closeEntry()
            }
        }
        // 安装器本体走 downloader 下下来，这里直接把它塞进 downloader 会写到的位置
        return f
    }

    /**
     * 安装器本体从「网上」拿：把造好的 jar 拷过去。
     * processor 用的那颗 jar 得是**真 jar 且带 Main-Class**——`mainClassOf` 读的就是它，
     * 落一个纯文本占位会在这一步炸，那正是线上会发生的事。
     */
    private fun installerDownloader(installer: File) = PackDownloader { urls, dest, _, _ ->
        dest.parentFile?.mkdirs()
        when {
            urls.any { it.contains("installer") } -> installer.copyTo(dest, overwrite = true)
            dest.name.startsWith("binarypatcher") -> java.util.jar.JarOutputStream(
                dest.outputStream(),
                java.util.jar.Manifest().apply {
                    mainAttributes.putValue("Manifest-Version", "1.0")
                    mainAttributes.putValue("Main-Class", "net.minecraftforge.binarypatcher.ConsoleTool")
                },
            ).use { }
            else -> dest.writeText(urls.firstOrNull().orEmpty())
        }
    }

    @Test
    fun installerCoordinatesResolveToADownloadableFile() {
        val forge = LoaderInstall.installerFile(Loader.FORGE, "1.20.1", "47.2.0")!!
        assertEquals("forge-1.20.1-47.2.0-installer.jar", forge.path)
        assertTrue(forge.urls.any { it.startsWith("https://maven.minecraftforge.net/") })
        assertTrue(forge.urls.any { it.contains("bmclapi") })
        val neo = LoaderInstall.installerFile(Loader.NEOFORGE, "1.21.1", "21.1.9")!!
        assertTrue(neo.urls.first().startsWith("https://maven.neoforged.net/"))
        assertNull(LoaderInstall.installerFile(Loader.FABRIC, "1.20.1", "0.16.0"))
    }

    @Test
    fun optifineInstallerGoesThroughTheMirror() {
        val of = LoaderInstall.installerFile(Loader.OPTIFINE, "1.20.1", "HD_U_I6")!!
        assertTrue(of.urls.single().contains("/optifine/1.20.1/HD/U_I6"))
    }

    @Test
    fun processorBranchNoLongerRefusesOutright() {
        vanilla()
        var ran = 0
        val id = LoaderInstall.installProcessorLoader(
            instDir = inst,
            loader = Loader.FORGE,
            mc = "1.20.1",
            build = "47.2.0",
            downloader = installerDownloader(forgeInstaller(true)),
            runJvm = { step, _, _ ->
                ran++
                // 替身 processor：把它声明的产物造出来，真 JVM 做的也是这件事
                step.outputs.keys.forEach { File(it).also { f -> f.parentFile?.mkdirs() }.writeText("patched") }
                0
            },
        )
        assertEquals("1.20.1-forge-47.2.0", id)
        assertEquals(1, ran)
    }

    @Test
    fun theInstalledForgeIsRecognisedAndLaunchable() {
        vanilla()
        val id = LoaderInstall.installProcessorLoader(
            inst, Loader.FORGE, "1.20.1", "47.2.0",
            installerDownloader(forgeInstaller(true)),
            { step, _, _ ->
                step.outputs.keys.forEach { File(it).also { f -> f.parentFile?.mkdirs() }.writeText("patched") }
                0
            },
        )
        assertEquals("Forge", VersionOps.card(inst, id).loader)
        assertEquals("1.20.1", VersionOps.card(inst, id).mc)
        val plan = LaunchPlanner.plan("t", id, "Player", 2048, inst)
        assertEquals("cpw.mods.bootstraplauncher.BootstrapLauncher", plan.mainClass)
        assertTrue(plan.classpath.any { it.endsWith("1.20.1.jar") })
        assertTrue(plan.classpath.any { it.replace('\\', '/').contains("net/minecraftforge/forge/1.20.1-47.2.0") })
        assertTrue(plan.missing.isEmpty())
    }

    @Test
    fun theUpstreamVersionIdIsRewrittenToOurs() {
        vanilla()
        val id = LoaderInstall.installProcessorLoader(
            inst, Loader.FORGE, "1.20.1", "47.2.0",
            installerDownloader(forgeInstaller(false)), null,
        )
        val json = JSONObject(File(inst, "versions/$id/$id.json").readText())
        assertEquals(id, json.getString("id"))
        assertEquals("1.20.1", json.getString("inheritsFrom"))
    }

    @Test
    fun aProfileWithoutProcessorsSkipsTheJvmEntirely() {
        vanilla()
        val id = LoaderInstall.installProcessorLoader(
            inst, Loader.FORGE, "1.20.1", "47.2.0",
            installerDownloader(forgeInstaller(false)),
            runJvm = { _, _, _ -> throw AssertionError("不该起 JVM") },
        )
        assertTrue(File(inst, "versions/$id/$id.json").isFile)
    }

    @Test
    fun aFailingProcessorAbortsWithItsExitCode() {
        vanilla()
        try {
            LoaderInstall.installProcessorLoader(
                inst, Loader.FORGE, "1.20.1", "47.2.0",
                installerDownloader(forgeInstaller(true)),
                { _, _, _ -> 137 },
            )
            throw AssertionError("应当失败")
        } catch (e: LoaderError) {
            assertTrue(e.message!!.contains("137"))
        }
    }

    @Test
    fun aProcessorThatProducesNothingIsCaught() {
        vanilla()
        try {
            LoaderInstall.installProcessorLoader(
                inst, Loader.FORGE, "1.20.1", "47.2.0",
                installerDownloader(forgeInstaller(true)),
                { _, _, _ -> 0 },
            )
            throw AssertionError("应当失败")
        } catch (e: LoaderError) {
            assertTrue(e.message!!.contains("产物不对"))
        }
    }

    @Test
    fun withoutAJvmHostItSaysSoInsteadOfHalfInstalling() {
        vanilla()
        try {
            LoaderInstall.installProcessorLoader(
                inst, Loader.FORGE, "1.20.1", "47.2.0",
                installerDownloader(forgeInstaller(true)), null,
            )
            throw AssertionError("应当失败")
        } catch (e: LoaderError) {
            assertTrue(e.message!!.contains("JVM 宿主"))
        }
    }

    @Test
    fun theWorkingCopyOfTheInstallerIsCleanedUp() {
        vanilla()
        LoaderInstall.installProcessorLoader(
            inst, Loader.FORGE, "1.20.1", "47.2.0",
            installerDownloader(forgeInstaller(false)), null,
        )
        val leftovers = File(inst, "cache").listFiles()?.filter { it.isDirectory && it.name.startsWith("installer-") }
        assertEquals(emptyList<File>(), leftovers)
    }

    @Test
    fun processorInstallStillNeedsTheVanillaVersion() {
        try {
            LoaderInstall.installProcessorLoader(
                inst, Loader.FORGE, "1.20.1", "47.2.0",
                installerDownloader(forgeInstaller(false)), null,
            )
            throw AssertionError("应当失败")
        } catch (e: LoaderError) {
            assertTrue(e.message!!.contains("先装原版"))
        }
    }

    @Test
    fun mainClassIsReadFromTheJarManifest() {
        val jar = File(inst, "tool.jar")
        java.util.jar.JarOutputStream(
            jar.outputStream(),
            java.util.jar.Manifest().apply {
                mainAttributes.putValue("Manifest-Version", "1.0")
                mainAttributes.putValue("Main-Class", "com.example.Tool")
            },
        ).use { }
        assertEquals("com.example.Tool", LoaderInstall.mainClassOf(jar))
        assertNull(LoaderInstall.mainClassOf(File(inst, "nope.jar")))
    }
}
