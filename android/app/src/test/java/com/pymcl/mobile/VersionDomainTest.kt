package com.pymcl.mobile

import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.VersionError
import com.pymcl.mobile.data.VersionOps
import com.pymcl.mobile.data.VersionSettings
import com.pymcl.mobile.model.VersionCard
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class VersionDomainTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-version").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    private fun version(id: String, json: String = """{"id":"$id"}""") {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText(json)
        File(inst, "versions/$id/$id.jar").writeText("jar")
    }

    // ---- VersionSettings ------------------------------------------------

    @Test
    fun defaultsAreSharedPool() {
        val s = VersionSettings.load(inst, "1.20.1")
        assertEquals(VersionSettings.NONE, s.isolation)
        assertFalse(VersionSettings.isolatedMods(s))
        assertFalse(VersionSettings.isolatedAnywhere(s))
    }

    @Test
    fun unknownIsolationFallsBackToNone() {
        val s = VersionSettings.fromJson(JSONObject("""{"isolation":"weird"}"""))
        assertEquals(VersionSettings.NONE, s.isolation)
    }

    @Test
    fun saveAndLoadRoundTripEveryField() {
        version("1.20.1")
        val want = VersionSettings.load(inst, "1.20.1").copy(
            isolation = VersionSettings.MODS,
            memoryMb = 4096,
            jvmArgs = "-XX:+UseG1GC",
            gameArgs = "--fullscreen",
            server = "mc.a.com",
            port = "25566",
            hidden = true,
            windowMode = "maximize",
            windowWidth = 1920,
            windowHeight = 1080,
            skipAssets = true,
        )
        VersionSettings.save(inst, "1.20.1", want)
        assertEquals(want, VersionSettings.load(inst, "1.20.1"))
    }

    @Test
    fun corruptSettingsFileFallsBackToDefaults() {
        version("1.20.1")
        VersionSettings.file(inst, "1.20.1").writeText("not json")
        assertEquals(VersionSettings.NONE, VersionSettings.load(inst, "1.20.1").isolation)
    }

    @Test
    fun isolatedModsCoversModsAndAll() {
        assertTrue(VersionSettings.isolatedMods(VersionSettings.fromJson(JSONObject("""{"isolation":"mods"}"""))))
        assertTrue(VersionSettings.isolatedMods(VersionSettings.fromJson(JSONObject("""{"isolation":"all"}"""))))
        assertFalse(VersionSettings.isolatedMods(VersionSettings.fromJson(JSONObject("""{"isolation":"saves"}"""))))
    }

    @Test
    fun isolatedSavesCoversSavesAndAll() {
        assertTrue(VersionSettings.isolatedSaves(VersionSettings.fromJson(JSONObject("""{"isolation":"saves"}"""))))
        assertTrue(VersionSettings.isolatedSaves(VersionSettings.fromJson(JSONObject("""{"isolation":"all"}"""))))
        assertFalse(VersionSettings.isolatedSaves(VersionSettings.fromJson(JSONObject("""{"isolation":"mods"}"""))))
    }

    @Test
    fun gameDirFollowsIsolation() {
        version("1.20.1")
        assertEquals(inst, VersionSettings.gameDir(inst, "1.20.1"))
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.ALL)
        assertEquals(File(inst, "versions/1.20.1"), VersionSettings.gameDir(inst, "1.20.1"))
    }

    @Test
    fun savesDirFollowsSavesIsolationOnly() {
        version("1.20.1")
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.MODS)
        assertEquals(File(inst, "saves"), VersionSettings.savesDir(inst, "1.20.1"))
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.SAVES)
        assertEquals(File(inst, "versions/1.20.1/saves"), VersionSettings.savesDir(inst, "1.20.1"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun setIsolationRejectsUnknownMode() {
        version("1.20.1")
        VersionSettings.setIsolation(inst, "1.20.1", "nope")
    }

    @Test
    fun setIsolationWithSeedCopiesSharedMods() {
        version("1.20.1")
        File(inst, "mods").mkdirs()
        File(inst, "mods/sodium.jar").writeText("s")
        File(inst, "config").mkdirs()
        File(inst, "config/a.toml").writeText("a")
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.ALL, seed = true)
        assertTrue(File(inst, "versions/1.20.1/mods/sodium.jar").isFile)
        assertTrue(File(inst, "versions/1.20.1/config/a.toml").isFile)
    }

    @Test
    fun setIsolationWithoutSeedLeavesVersionEmpty() {
        version("1.20.1")
        File(inst, "mods").mkdirs()
        File(inst, "mods/sodium.jar").writeText("s")
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.ALL)
        assertFalse(File(inst, "versions/1.20.1/mods/sodium.jar").exists())
        assertTrue(File(inst, "versions/1.20.1/mods").isDirectory)
    }

    @Test
    fun seedDoesNotOverwriteExistingFile() {
        version("1.20.1")
        File(inst, "mods").mkdirs()
        File(inst, "mods/sodium.jar").writeText("shared")
        File(inst, "versions/1.20.1/mods").mkdirs()
        File(inst, "versions/1.20.1/mods/sodium.jar").writeText("mine")
        VersionSettings.setIsolation(inst, "1.20.1", VersionSettings.ALL, seed = true)
        assertEquals("mine", File(inst, "versions/1.20.1/mods/sodium.jar").readText())
    }

    @Test
    fun applyLayoutCreatesExpectedFoldersPerMode() {
        version("1.20.1")
        VersionSettings.applyLayout(inst, "1.20.1", VersionSettings.load(inst, "1.20.1").copy(isolation = VersionSettings.SAVES))
        assertTrue(File(inst, "versions/1.20.1/saves").isDirectory)
        VersionSettings.applyLayout(inst, "1.20.1", VersionSettings.load(inst, "1.20.1").copy(isolation = VersionSettings.MODS))
        assertTrue(File(inst, "versions/1.20.1/config").isDirectory)
    }

    @Test
    fun addressOfJoinsHostAndPort() {
        val base = VersionSettings.load(inst, "x")
        assertEquals("", VersionSettings.addressOf(base))
        assertEquals("mc.a.com", VersionSettings.addressOf(base.copy(server = "mc.a.com")))
        assertEquals("mc.a.com:25566", VersionSettings.addressOf(base.copy(server = "mc.a.com", port = "25566")))
        assertEquals("mc.a.com", VersionSettings.addressOf(base.copy(server = "mc.a.com", port = "0")))
    }

    @Test
    fun splitArgsHandlesQuotesAndSpacing() {
        assertEquals(listOf("-Xmx2G", "-Dfoo=bar"), VersionSettings.splitArgs("  -Xmx2G   -Dfoo=bar "))
        assertEquals(listOf("-Dpath=C:\\Program Files\\x"), VersionSettings.splitArgs("\"-Dpath=C:\\Program Files\\x\""))
        assertEquals(listOf("a b", "c"), VersionSettings.splitArgs("'a b' c"))
    }

    @Test
    fun splitArgsKeepsDeliberateEmptyArgument() {
        assertEquals(listOf("a", "", "b"), VersionSettings.splitArgs("a \"\" b"))
    }

    @Test
    fun splitArgsOfBlankIsEmpty() {
        assertTrue(VersionSettings.splitArgs("   ").isEmpty())
    }

    // ---- LaunchPlanner --------------------------------------------------

    @Test
    fun chainStopsAtSelfWhenNoParent() {
        version("1.20.1")
        assertEquals(listOf("1.20.1"), LaunchPlanner.chain(inst, "1.20.1"))
    }

    @Test
    fun chainFollowsInheritsFrom() {
        version("1.20.1")
        version("fab", """{"id":"fab","inheritsFrom":"1.20.1"}""")
        assertEquals(listOf("fab", "1.20.1"), LaunchPlanner.chain(inst, "fab"))
    }

    @Test
    fun chainSurvivesSelfReferencingJson() {
        version("loop", """{"id":"loop","inheritsFrom":"loop"}""")
        assertEquals(listOf("loop"), LaunchPlanner.chain(inst, "loop"))
    }

    @Test
    fun chainSurvivesTwoWayLoop() {
        version("a", """{"id":"a","inheritsFrom":"b"}""")
        version("b", """{"id":"b","inheritsFrom":"a"}""")
        assertEquals(listOf("a", "b"), LaunchPlanner.chain(inst, "a"))
    }

    @Test
    fun resolveJsonLetsChildWin() {
        version("1.20.1", """{"id":"1.20.1","mainClass":"vanilla.Main","assetIndex":{"id":"5"}}""")
        version("fab", """{"id":"fab","inheritsFrom":"1.20.1","mainClass":"knot.Client"}""")
        val merged = LaunchPlanner.resolveJson(inst, "fab")
        assertEquals("knot.Client", merged.optString("mainClass"))
        assertEquals("5", merged.optJSONObject("assetIndex")!!.optString("id"))
        assertEquals("fab", merged.optString("id"))
    }

    @Test
    fun resolveJsonDedupesLibrariesByGroupArtifact() {
        version(
            "1.20.1",
            """{"id":"1.20.1","libraries":[{"name":"org.ow2.asm:asm:9.3","downloads":{"artifact":{"path":"a/old.jar"}}}]}""",
        )
        version(
            "fab",
            """{"id":"fab","inheritsFrom":"1.20.1","libraries":[{"name":"org.ow2.asm:asm:9.6","downloads":{"artifact":{"path":"a/new.jar"}}}]}""",
        )
        val libs = LaunchPlanner.resolveJson(inst, "fab").getJSONArray("libraries")
        assertEquals(1, libs.length())
        assertEquals("org.ow2.asm:asm:9.6", libs.getJSONObject(0).getString("name"))
    }

    @Test
    fun libKeyDropsVersionAndClassifier() {
        assertEquals("org.lwjgl:lwjgl", LaunchPlanner.libKey(JSONObject("""{"name":"org.lwjgl:lwjgl:3.3.1:natives-linux"}""")))
        assertEquals("a/b.jar", LaunchPlanner.libKey(JSONObject("""{"downloads":{"artifact":{"path":"a/b.jar"}}}""")))
    }

    @Test
    fun baseJarPrefersTheOldestAncestorThatHasOne() {
        version("1.20.1")
        File(inst, "versions/fab").mkdirs()
        File(inst, "versions/fab/fab.json").writeText("""{"id":"fab","inheritsFrom":"1.20.1"}""")
        val jar = LaunchPlanner.baseJar(inst, listOf("fab", "1.20.1"))
        assertEquals("1.20.1.jar", jar.name)
    }

    @Test
    fun planReportsMissingJsonAndJar() {
        val plan = LaunchPlanner.plan("t", "nope", "Player", 2048, inst)
        assertEquals(2, plan.missing.size)
        assertTrue(plan.missing.any { it.endsWith("nope.json") })
        assertTrue(plan.missing.any { it.endsWith("nope.jar") })
    }

    @Test
    fun planPutsGameDirIntoArgs() {
        version("1.20.1")
        val plan = LaunchPlanner.plan("t", "1.20.1", "Steve", 2048, inst)
        val i = plan.gameArgs.indexOf("--gameDir")
        assertEquals(inst.absolutePath, plan.gameArgs[i + 1])
        assertEquals("Steve", plan.gameArgs[plan.gameArgs.indexOf("--username") + 1])
    }

    @Test
    fun planMemoryComesFromVersionSettingWhenSet() {
        version("1.20.1")
        VersionSettings.save(inst, "1.20.1", VersionSettings.load(inst, "1.20.1").copy(memoryMb = 6144))
        val plan = LaunchPlanner.plan("t", "1.20.1", "Player", 2048, inst)
        assertTrue(plan.jvmArgs.contains("-Xmx6144M"))
        assertTrue(plan.jvmArgs.contains("-Xms3072M"))
    }

    @Test
    fun planXmsNeverDropsBelowFloor() {
        version("1.20.1")
        val plan = LaunchPlanner.plan("t", "1.20.1", "Player", 600, inst)
        assertTrue(plan.jvmArgs.contains("-Xms512M"))
    }

    @Test
    fun planAppendsCustomArgs() {
        version("1.20.1")
        VersionSettings.save(
            inst,
            "1.20.1",
            VersionSettings.load(inst, "1.20.1").copy(jvmArgs = "-XX:+UseG1GC", gameArgs = "--fullscreen"),
        )
        val plan = LaunchPlanner.plan("t", "1.20.1", "Player", 2048, inst)
        assertTrue(plan.jvmArgs.contains("-XX:+UseG1GC"))
        assertTrue(plan.gameArgs.contains("--fullscreen"))
    }

    @Test
    fun planAddsQuickPlayWhenServerConfigured() {
        version("1.20.1")
        VersionSettings.save(
            inst,
            "1.20.1",
            VersionSettings.load(inst, "1.20.1").copy(server = "mc.a.com", port = "25566"),
        )
        val plan = LaunchPlanner.plan("t", "1.20.1", "Player", 2048, inst)
        val i = plan.gameArgs.indexOf("--quickPlayMultiplayer")
        assertTrue(i >= 0)
        assertEquals("mc.a.com:25566", plan.gameArgs[i + 1])
    }

    @Test
    fun describeMentionsCountsAndMissing() {
        version("1.20.1")
        val text = LaunchPlanner.describe(LaunchPlanner.plan("t", "1.20.1", "Player", 2048, inst))
        assertTrue(text.contains("实例 t / 1.20.1"))
        assertTrue(text.contains("缺文件 0"))
    }

    // ---- VersionOps -----------------------------------------------------

    @Test
    fun loaderDetectionCoversEveryFamily() {
        fun loader(json: String) = VersionOps.loaderOf(JSONObject(json))
        assertEquals("Fabric", loader("""{"libraries":[{"name":"net.fabricmc:fabric-loader:0.16.0"}]}"""))
        assertEquals("Forge", loader("""{"libraries":[{"name":"net.minecraftforge:forge:47.2.0"}]}"""))
        assertEquals("NeoForge", loader("""{"libraries":[{"name":"net.neoforged:neoforge:21.1.9"}]}"""))
        assertEquals("Quilt", loader("""{"libraries":[{"name":"org.quiltmc:quilt-loader:0.26"}]}"""))
        assertEquals("OptiFine", loader("""{"libraries":[{"name":"optifine:OptiFine:1.20.1"}]}"""))
        assertEquals("原版", loader("""{"libraries":[{"name":"com.mojang:patchy:1.1"}]}"""))
    }

    @Test
    fun neoForgeWinsOverForgeOnMixedNames() {
        val json = JSONObject("""{"mainClass":"net.neoforged.forge.Main","libraries":[]}""")
        assertEquals("NeoForge", VersionOps.loaderOf(json))
    }

    @Test
    fun loaderColorsAreDistinct() {
        val names = listOf("Fabric", "Forge", "NeoForge", "Quilt", "原版")
        assertEquals(names.size, names.map { VersionOps.loaderColor(it) }.toSet().size)
    }

    @Test
    fun mcVersionPrefersInheritsFromThenId() {
        version("1.20.1")
        version("fab", """{"id":"fab","inheritsFrom":"1.20.1"}""")
        assertEquals("1.20.1", VersionOps.mcVersionOf(inst, "fab"))
        version("1.20.1-forge-47.2.0")
        assertEquals("1.20.1", VersionOps.mcVersionOf(inst, "1.20.1-forge-47.2.0"))
    }

    @Test
    fun cardsHideHiddenVersionsByDefault() {
        version("a")
        version("b")
        VersionOps.setHidden(inst, "b", true)
        assertEquals(listOf("a"), VersionOps.cards(inst).map { it.id })
        assertEquals(listOf("a", "b"), VersionOps.cards(inst, includeHidden = true).map { it.id })
    }

    @Test
    fun cardCountsModsForIsolatedVersion() {
        version("a")
        VersionSettings.setIsolation(inst, "a", VersionSettings.ALL)
        File(inst, "versions/a/mods").mkdirs()
        File(inst, "versions/a/mods/x.jar").writeText("x")
        val card = VersionOps.card(inst, "a")
        assertEquals(1, card.mods)
        assertTrue(card.isolated)
    }

    @Test
    fun toggleHiddenFlipsAndReports() {
        version("a")
        assertTrue(VersionOps.toggleHidden(inst, "a"))
        assertFalse(VersionOps.toggleHidden(inst, "a"))
    }

    @Test
    fun filterMatchesIdAndLoader() {
        val rows = listOf(
            VersionCard("1.20.1", "1.20.1", "原版", 0, false, false),
            VersionCard("1.20.1-fabric", "1.20.1", "Fabric", 2, true, false),
        )
        assertEquals(1, VersionOps.filter(rows, "fabric").size)
        assertEquals(2, VersionOps.filter(rows, "1.20").size)
        assertEquals(2, VersionOps.filter(rows, "").size)
    }

    @Test
    fun renameMovesFolderAndRewritesId() {
        version("旧")
        val out = VersionOps.rename(inst, "旧", "新")
        assertEquals("新", out)
        assertTrue(File(inst, "versions/新/新.json").isFile)
        assertTrue(File(inst, "versions/新/新.jar").isFile)
        assertEquals("新", JSONObject(File(inst, "versions/新/新.json").readText()).getString("id"))
        assertFalse(File(inst, "versions/旧").exists())
    }

    @Test(expected = VersionError::class)
    fun renameRejectsExistingTarget() {
        version("a")
        version("b")
        VersionOps.rename(inst, "a", "b")
    }

    @Test(expected = VersionError::class)
    fun renameRejectsMissingVersion() {
        VersionOps.rename(inst, "nope", "x")
    }

    @Test
    fun copyLeavesOriginalIntact() {
        version("a")
        assertEquals("a-copy", VersionOps.copy(inst, "a", "a-copy"))
        assertTrue(File(inst, "versions/a/a.json").isFile)
        assertTrue(File(inst, "versions/a-copy/a-copy.json").isFile)
    }

    @Test
    fun uninstallRemovesTheFolder() {
        version("a")
        VersionOps.uninstall(inst, "a")
        assertFalse(File(inst, "versions/a").exists())
    }

    @Test(expected = VersionError::class)
    fun uninstallRejectsMissingVersion() {
        VersionOps.uninstall(inst, "nope")
    }

    @Test
    fun missingFilesIsEmptyForCompleteVersion() {
        version("1.20.1")
        assertTrue(VersionOps.missingFiles(inst, "1.20.1").isEmpty())
    }

    @Test
    fun missingFilesListsAbsentLibrary() {
        version(
            "1.20.1",
            """{"id":"1.20.1","libraries":[{"name":"com.mojang:patchy:1.1","downloads":{"artifact":{"path":"com/mojang/patchy/1.1/patchy-1.1.jar"}}}]}""",
        )
        assertEquals(1, VersionOps.missingFiles(inst, "1.20.1").size)
    }

    @Test
    fun launchScriptCarriesMainClassAndGameDir() {
        version("1.20.1", """{"id":"1.20.1","mainClass":"net.minecraft.client.main.Main"}""")
        val script = VersionOps.launchScript(inst, "1.20.1", "Steve", 2048)
        assertTrue(script.contains("net.minecraft.client.main.Main"))
        assertTrue(script.contains("--username Steve"))
        assertTrue(script.contains("-Xmx2048M"))
    }
}
