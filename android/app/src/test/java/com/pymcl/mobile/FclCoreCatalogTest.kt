package com.pymcl.mobile

import com.pymcl.mobile.data.FclCoreCatalog
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `:FCLCore` 真的接进来了没有。
 *
 * 这几条断言看着像废话，但它们是**编译期 + 运行期双份证据**：
 * `FclCoreCatalog` 里存的是 `Class<*>` 而不是字符串，所以上游改包名会让它编不过；
 * 这里再核一遍类的全名，是为了防止有人把它偷偷换成同名的自家占位类。
 */
class FclCoreCatalogTest {
    @Test
    fun forgeNewInstallTaskIsTheRealUpstreamClass() {
        val forge = FclCoreCatalog.byLoader("forge")
        assertNotNull(forge)
        assertEquals(
            "com.tungsten.fclcore.download.forge.ForgeNewInstallTask",
            forge!!.taskClass.name,
        )
    }

    @Test
    fun everyInstallerPointsIntoFclCore() {
        assertTrue(FclCoreCatalog.installers.isNotEmpty())
        FclCoreCatalog.installers.forEach {
            assertTrue(
                "${it.loader} 指到了 ${it.taskClass.name}，不在 fclcore 里",
                it.taskClass.name.startsWith("com.tungsten.fclcore.download."),
            )
        }
    }

    @Test
    fun theTwoOldSchemeEntriesAreThere() {
        // opus-5-5 的 filterNeoForgeVersions 会回退到 1.20.1 以前那个 <mc>-<build> 号段
        assertEquals(
            "com.tungsten.fclcore.download.neoforge.NeoForgeOldInstallTask",
            FclCoreCatalog.byLoader("neoforge-old")?.taskClass?.name,
        )
        assertEquals(
            "com.tungsten.fclcore.download.game.GameInstallTask",
            FclCoreCatalog.byLoader("vanilla")?.taskClass?.name,
        )
    }

    @Test
    fun vanillaIsReachableButNotOfferedAsALoader() {
        // 原版不是加载器，不该出现在「装哪个加载器」那张选单上
        assertTrue(FclCoreCatalog.installers.any { it.loader == "vanilla" })
        assertFalse(FclCoreCatalog.loaderOnly.any { it.loader == "vanilla" })
        assertEquals(FclCoreCatalog.installers.size - 1, FclCoreCatalog.loaderOnly.size)
    }

    @Test
    fun loaderNamesGoThroughTheSameNormalizationAsVersionPick() {
        // 「Forge」「forge」「FORGE」都得落到同一条上
        assertEquals("forge", FclCoreCatalog.byLoader("Forge")?.loader)
        assertEquals("fabric", FclCoreCatalog.byLoader("Fabric")?.loader)
        assertEquals("neoforge", FclCoreCatalog.byLoader("NeoForge")?.loader)
        assertEquals("quilt", FclCoreCatalog.byLoader("quilt")?.loader)
        assertNull(FclCoreCatalog.byLoader("不存在的加载器"))
    }

    @Test
    fun onlyTheOnesThatRunProcessorsNeedTheJvmHost() {
        val needing = FclCoreCatalog.needingJvmHost().map { it.loader }.toSet()
        // Forge 1.13+ / NeoForge / OptiFine 要在本机跑 processor
        assertTrue("forge" in needing)
        assertTrue("neoforge" in needing)
        assertTrue("optifine" in needing)
        // Fabric / Quilt 只下文件，不该被拖去等一个 JVM
        assertFalse("fabric" in needing)
        assertFalse("quilt" in needing)
    }

    @Test
    fun describeListsEveryInstallerOnItsOwnLine() {
        val lines = FclCoreCatalog.describe().lines()
        assertEquals(FclCoreCatalog.installers.size, lines.size)
        assertTrue(lines.any { it.contains("ForgeNewInstallTask") && it.contains("JVM 宿主") })
    }
}
