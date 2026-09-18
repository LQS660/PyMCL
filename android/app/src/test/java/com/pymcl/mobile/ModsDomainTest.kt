package com.pymcl.mobile

import com.pymcl.mobile.data.ModError
import com.pymcl.mobile.data.Mods
import com.pymcl.mobile.data.VersionSettings
import com.pymcl.mobile.model.ModEntry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class ModsDomainTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-mods").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    private fun shared(name: String, body: String = "jar"): File {
        val dir = File(inst, "mods").also { it.mkdirs() }
        return File(dir, name).also { it.writeText(body) }
    }

    private fun installedVersion(id: String, isolation: String) {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText("""{"id":"$id"}""")
        VersionSettings.save(inst, id, VersionSettings.load(inst, id).copy(isolation = isolation))
    }

    @Test
    fun baseNameStripsDisabledSuffix() {
        assertEquals("sodium.jar", Mods.baseName("sodium.jar.disabled"))
        assertEquals("sodium.jar", Mods.baseName("sodium.jar"))
    }

    @Test
    fun isEnabledFollowsSuffix() {
        assertTrue(Mods.isEnabled("sodium.jar"))
        assertFalse(Mods.isEnabled("sodium.jar.disabled"))
        assertFalse(Mods.isEnabled("sodium.jar.DISABLED"))
    }

    @Test
    fun looksLikeModAcceptsKnownExtensions() {
        assertTrue(Mods.looksLikeMod("a.jar"))
        assertTrue(Mods.looksLikeMod("a.zip"))
        assertTrue(Mods.looksLikeMod("a.litemod"))
        assertTrue(Mods.looksLikeMod("a.jar.disabled"))
        assertFalse(Mods.looksLikeMod("a.txt"))
        assertFalse(Mods.looksLikeMod("readme"))
    }

    @Test
    fun dirForFallsBackToSharedPool() {
        assertEquals(File(inst, "mods"), Mods.dirFor(inst))
    }

    @Test
    fun dirForUsesVersionFolderWhenIsolated() {
        installedVersion("1.20.1", VersionSettings.ALL)
        assertEquals(File(inst, "versions/1.20.1/mods"), Mods.dirFor(inst, "1.20.1"))
    }

    @Test
    fun dirForStaysSharedWhenVersionIsNotIsolated() {
        installedVersion("1.20.1", VersionSettings.NONE)
        assertEquals(File(inst, "mods"), Mods.dirFor(inst, "1.20.1"))
    }

    @Test
    fun savesOnlyIsolationStillSharesMods() {
        installedVersion("1.20.1", VersionSettings.SAVES)
        assertEquals(File(inst, "mods"), Mods.dirFor(inst, "1.20.1"))
    }

    @Test
    fun targetsAlwaysStartWithSharedPool() {
        val rows = Mods.targets(inst)
        assertEquals(1, rows.size)
        assertEquals("", rows[0].value)
    }

    @Test
    fun targetsListIsolatedVersionsOnly() {
        installedVersion("1.20.1", VersionSettings.ALL)
        installedVersion("1.21", VersionSettings.NONE)
        installedVersion("1.19", VersionSettings.MODS)
        assertEquals(listOf("", "1.19", "1.20.1"), Mods.targets(inst).map { it.value })
    }

    @Test
    fun listIsEmptyWithoutFolder() {
        assertTrue(Mods.list(inst).isEmpty())
    }

    @Test
    fun listReportsEnabledAndDisabled() {
        shared("a.jar")
        shared("b.jar.disabled")
        val rows = Mods.list(inst)
        assertEquals(listOf("a.jar", "b.jar"), rows.map { it.filename })
        assertTrue(rows[0].enabled)
        assertFalse(rows[1].enabled)
    }

    @Test
    fun listSkipsNonModFiles() {
        shared("a.jar")
        File(inst, "mods/notes.txt").writeText("x")
        assertEquals(1, Mods.list(inst).size)
    }

    @Test
    fun listSortsCaseInsensitively() {
        shared("Zeta.jar")
        shared("alpha.jar")
        assertEquals(listOf("alpha.jar", "Zeta.jar"), Mods.list(inst).map { it.filename })
    }

    @Test
    fun locateFindsBothStates() {
        shared("a.jar")
        shared("b.jar.disabled")
        assertEquals("a.jar", Mods.locate(inst, "a.jar")!!.name)
        assertEquals("b.jar.disabled", Mods.locate(inst, "b.jar")!!.name)
        assertNull(Mods.locate(inst, "c.jar"))
    }

    @Test
    fun setEnabledFalseAddsSuffix() {
        shared("a.jar")
        val out = Mods.setEnabled(inst, "a.jar", false)
        assertEquals("a.jar.disabled", out.name)
        assertFalse(Mods.list(inst)[0].enabled)
    }

    @Test
    fun setEnabledTrueRemovesSuffix() {
        shared("a.jar.disabled")
        val out = Mods.setEnabled(inst, "a.jar", true)
        assertEquals("a.jar", out.name)
        assertTrue(Mods.list(inst)[0].enabled)
    }

    @Test
    fun setEnabledIsIdempotent() {
        shared("a.jar")
        Mods.setEnabled(inst, "a.jar", true)
        assertEquals(listOf(true), Mods.list(inst).map { it.enabled })
    }

    @Test(expected = ModError::class)
    fun setEnabledRejectsMissingMod() {
        Mods.setEnabled(inst, "nope.jar", false)
    }

    @Test(expected = ModError::class)
    fun setEnabledRefusesToClobberExistingFile() {
        shared("a.jar")
        shared("a.jar.disabled")
        Mods.setEnabled(inst, "a.jar", false)
    }

    @Test
    fun deleteRemovesEitherState() {
        shared("a.jar.disabled")
        Mods.delete(inst, "a.jar")
        assertTrue(Mods.list(inst).isEmpty())
    }

    @Test(expected = ModError::class)
    fun deleteRejectsMissingMod() {
        Mods.delete(inst, "nope.jar")
    }

    @Test
    fun installCopiesIntoTargetFolder() {
        val src = File(inst, "incoming/sodium.jar").also { it.parentFile.mkdirs(); it.writeText("s") }
        val row = Mods.install(inst, src)
        assertEquals("sodium.jar", row.filename)
        assertTrue(File(inst, "mods/sodium.jar").isFile)
    }

    @Test
    fun installDoesNotOverwriteExisting() {
        shared("sodium.jar", "old")
        val src = File(inst, "incoming/sodium.jar").also { it.parentFile.mkdirs(); it.writeText("new") }
        val row = Mods.install(inst, src)
        assertEquals("sodium-2.jar", row.filename)
        assertEquals("old", File(inst, "mods/sodium.jar").readText())
    }

    @Test(expected = ModError::class)
    fun installRejectsMissingFile() {
        Mods.install(inst, File(inst, "nope.jar"))
    }

    @Test(expected = ModError::class)
    fun installRejectsNonMod() {
        val src = File(inst, "incoming/readme.txt").also { it.parentFile.mkdirs(); it.writeText("x") }
        Mods.install(inst, src)
    }

    @Test
    fun installGoesIntoIsolatedVersionFolder() {
        installedVersion("1.20.1", VersionSettings.ALL)
        val src = File(inst, "incoming/a.jar").also { it.parentFile.mkdirs(); it.writeText("a") }
        Mods.install(inst, src, "1.20.1")
        assertTrue(File(inst, "versions/1.20.1/mods/a.jar").isFile)
        assertTrue(Mods.list(inst).isEmpty())
    }

    @Test
    fun exportStripsDisabledSuffix() {
        shared("a.jar.disabled")
        val out = Mods.export(inst, "a.jar", File(inst, "exports"))
        assertEquals("a.jar", out.name)
        assertTrue(out.isFile)
    }

    @Test(expected = ModError::class)
    fun exportRejectsMissingMod() {
        Mods.export(inst, "nope.jar", File(inst, "exports"))
    }

    @Test
    fun summaryCountsBothStatesAndSize() {
        val rows = listOf(
            ModEntry("a.jar", "", 1024, true),
            ModEntry("b.jar", "", 1024, false),
        )
        assertEquals("启用 1 · 禁用 1 · 2 KB", Mods.summary(rows))
    }

    @Test
    fun filterIsCaseInsensitiveSubstring() {
        val rows = listOf(ModEntry("Sodium.jar", ""), ModEntry("lithium.jar", ""))
        assertEquals(listOf("Sodium.jar"), Mods.filter(rows, "sod").map { it.filename })
        assertEquals(2, Mods.filter(rows, "  ").size)
    }

    @Test
    fun splitVersionSeparatesNameAndVersion() {
        assertEquals("sodium-fabric" to "0.5.8+mc1.20.1", Mods.splitVersion("sodium-fabric-0.5.8+mc1.20.1.jar"))
        assertEquals("lithium" to "1.2.3", Mods.splitVersion("lithium-1.2.3.jar.disabled"))
    }

    @Test
    fun splitVersionLeavesUnversionedNameAlone() {
        assertEquals("mymod" to "", Mods.splitVersion("mymod.jar"))
    }
}
