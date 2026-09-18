package com.pymcl.mobile

import com.pymcl.mobile.data.GlobalMods
import com.pymcl.mobile.data.ModError
import com.pymcl.mobile.data.VersionSettings
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 全局（共享）模组池：列举 / 启停 / 删除 / 放入，以及「这一份对谁生效」。
 *
 * 落点必须恒等于实例根的 mods——页面上没有「安装目标」这一档，
 * 一旦跟着版本走，用户在全局页上关掉的就不是他看到的那个 jar。
 */
class GlobalModsTest {
    private lateinit var inst: File

    @Before
    fun setUp() {
        inst = kotlin.io.path.createTempDirectory("pymcl-global-mods").toFile()
    }

    @After
    fun tearDown() {
        inst.deleteRecursively()
    }

    private fun pooled(name: String, body: String = "jar"): File {
        val dir = File(inst, "mods").also { it.mkdirs() }
        return File(dir, name).also { it.writeText(body) }
    }

    private fun installedVersion(id: String, isolation: String) {
        File(inst, "versions/$id").mkdirs()
        File(inst, "versions/$id/$id.json").writeText("""{"id":"$id"}""")
        VersionSettings.save(inst, id, VersionSettings.load(inst, id).copy(isolation = isolation))
    }

    @Test
    fun poolIsAlwaysTheInstanceRootMods() {
        installedVersion("1.20.1", VersionSettings.ALL)
        assertEquals(File(inst, "mods"), GlobalMods.dir(inst))
    }

    @Test
    fun listIsEmptyBeforeAnyJarLands() {
        assertTrue(GlobalMods.list(inst).isEmpty())
    }

    @Test
    fun listReportsBothStatesAndIgnoresIsolatedCopies() {
        installedVersion("1.20.1", VersionSettings.ALL)
        pooled("a.jar")
        pooled("b.jar.disabled")
        File(inst, "versions/1.20.1/mods").mkdirs()
        File(inst, "versions/1.20.1/mods/private.jar").writeText("x")
        val rows = GlobalMods.list(inst)
        assertEquals(listOf("a.jar", "b.jar"), rows.map { it.filename })
        assertEquals(listOf(true, false), rows.map { it.enabled })
    }

    @Test
    fun setEnabledFlipsTheDisabledSuffixInPlace() {
        pooled("a.jar")
        assertEquals("a.jar.disabled", GlobalMods.setEnabled(inst, "a.jar", false).name)
        assertFalse(GlobalMods.list(inst).single().enabled)
        assertEquals("a.jar", GlobalMods.setEnabled(inst, "a.jar", true).name)
        assertTrue(GlobalMods.list(inst).single().enabled)
    }

    @Test(expected = ModError::class)
    fun setEnabledRejectsAJarThatIsNotInThePool() {
        installedVersion("1.20.1", VersionSettings.ALL)
        File(inst, "versions/1.20.1/mods").mkdirs()
        File(inst, "versions/1.20.1/mods/private.jar").writeText("x")
        GlobalMods.setEnabled(inst, "private.jar", false)
    }

    @Test
    fun deleteRemovesEitherState() {
        pooled("a.jar")
        pooled("b.jar.disabled")
        GlobalMods.delete(inst, "a.jar")
        GlobalMods.delete(inst, "b.jar")
        assertTrue(GlobalMods.list(inst).isEmpty())
    }

    @Test
    fun installLandsInThePoolWithoutOverwriting() {
        pooled("sodium.jar", "old")
        val src = File(inst, "incoming/sodium.jar").also { it.parentFile.mkdirs(); it.writeText("new") }
        assertEquals("sodium-2.jar", GlobalMods.install(inst, src).filename)
        assertEquals("old", File(inst, "mods/sodium.jar").readText())
    }

    @Test
    fun consumersAreTheVersionsWithoutIsolatedMods() {
        installedVersion("1.20.1", VersionSettings.ALL)
        installedVersion("1.21", VersionSettings.NONE)
        installedVersion("1.19", VersionSettings.MODS)
        installedVersion("1.18", VersionSettings.SAVES)
        // 只隔离存档的仍然吃共享池；隔离模组的那两个各用各的
        assertEquals(listOf("1.18", "1.21"), GlobalMods.consumers(inst))
    }

    @Test
    fun consumersIsEmptyWithoutInstalledVersions() {
        assertTrue(GlobalMods.consumers(inst).isEmpty())
    }
}
