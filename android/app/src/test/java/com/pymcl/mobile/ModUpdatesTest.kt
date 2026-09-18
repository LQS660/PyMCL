package com.pymcl.mobile

import com.pymcl.mobile.data.ModUpdates
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.model.ModEntry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ModUpdatesTest {
    private fun mod(name: String) = ModEntry(name, "/mods/$name")

    private fun versions(slugToVersion: Map<String, String>) = TextFetcher { urls, _ ->
        val slug = urls.first().substringAfter("/project/").substringBefore("/version")
        slugToVersion[slug]?.let { version ->
            """
            [{"id":"v","name":"$version","version_number":"$version","version_type":"release",
              "game_versions":["1.20.1"],"loaders":["fabric"],"date_published":"2024-05-01",
              "files":[{"url":"https://cdn/$slug-$version.jar","filename":"$slug-$version.jar",
                        "primary":true,"hashes":{"sha1":""},"size":10}]}]
            """.trimIndent()
        }
    }

    // ---- 从文件名猜 slug --------------------------------------------------

    @Test
    fun slugDropsVersionAndLoaderSuffix() {
        assertEquals("sodium", ModUpdates.slugGuess("sodium-fabric-0.5.8+mc1.20.1.jar"))
        assertEquals("lithium", ModUpdates.slugGuess("lithium-1.2.3.jar"))
        assertEquals("iris", ModUpdates.slugGuess("Iris-forge-1.6.jar"))
    }

    @Test
    fun slugNormalisesSeparatorsAndCase() {
        assertEquals("just-enough-items", ModUpdates.slugGuess("Just_Enough Items-9.1.jar"))
    }

    @Test
    fun slugSurvivesAnUnversionedName() {
        assertEquals("mymod", ModUpdates.slugGuess("mymod.jar"))
    }

    @Test
    fun currentVersionComesFromTheFileName() {
        assertEquals("0.5.8+mc1.20.1", ModUpdates.currentVersionOf("sodium-fabric-0.5.8+mc1.20.1.jar"))
        assertEquals("", ModUpdates.currentVersionOf("mymod.jar"))
    }

    // ---- 批量检查 --------------------------------------------------------

    @Test
    fun aNewerUpstreamFileCountsAsAnUpdate() {
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar")), "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.6.0")),
        )
        assertEquals(1, rows.size)
        assertTrue(rows.single().hasUpdate)
        assertEquals("0.6.0", rows.single().latest?.versionNumber)
        assertEquals("sodium-0.6.0.jar", rows.single().file?.path)
    }

    @Test
    fun theSameFileNameIsNotAnUpdate() {
        // 同名就当已是最新；不拿版本号字符串比大小，各家规则都不一样
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar")), "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.5.8")),
        )
        assertFalse(rows.single().hasUpdate)
        assertEquals("已是最新", ModUpdates.describe(rows.single()))
    }

    @Test
    fun aModThatCannotBeFoundIsReportedNotAssumedCurrent() {
        val rows = ModUpdates.check(
            listOf(mod("some-private-mod-1.0.jar")), "1.20.1", "fabric",
            versions(emptyMap()),
        )
        assertFalse(rows.single().hasUpdate)
        assertNull(rows.single().file)
        assertTrue(rows.single().reason.isNotBlank())
        assertFalse(ModUpdates.describe(rows.single()) == "已是最新")
    }

    @Test
    fun aMismatchedGameVersionComesBackWithTheRealReason() {
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar")), "1.21.4", "fabric",
            versions(mapOf("sodium" to "0.6.0")),
        )
        assertTrue(rows.single().reason.contains("1.20.1"))
    }

    @Test
    fun updatableFiltersToTheActionableOnes() {
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar"), mod("lithium-1.0.jar"), mod("ghost-1.0.jar")),
            "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.6.0", "lithium" to "1.0")),
        )
        assertEquals(3, rows.size)
        assertEquals(listOf("sodium-0.5.8.jar"), ModUpdates.updatable(rows).map { it.entry.filename })
    }

    @Test
    fun summaryCountsAllThreeOutcomes() {
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar"), mod("lithium-1.0.jar"), mod("ghost-1.0.jar")),
            "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.6.0", "lithium" to "1.0")),
        )
        assertEquals("查了 3 个 · 可更新 1 · 没查到 1", ModUpdates.summary(rows))
    }

    @Test
    fun anEmptyListSaysSo() {
        assertEquals("没有可检查的模组", ModUpdates.summary(emptyList()))
    }

    @Test
    fun theBatchIsCappedSoWeDoNotHammerUpstream() {
        val many = (1..60).map { mod("mod$it-1.0.jar") }
        val rows = ModUpdates.check(many, "1.20.1", "fabric", versions(emptyMap()))
        assertEquals(ModUpdates.MAX_BATCH, rows.size)
    }

    @Test
    fun anUnreadableFileNameIsSkippedWithAReason() {
        val rows = ModUpdates.check(listOf(mod("-1.0.jar")), "1.20.1", "fabric", versions(emptyMap()))
        assertTrue(rows.single().reason.isNotBlank())
        assertFalse(rows.single().hasUpdate)
    }

    @Test
    fun describeShowsTheVersionJump() {
        val rows = ModUpdates.check(
            listOf(mod("sodium-0.5.8.jar")), "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.6.0")),
        )
        assertEquals("0.5.8 → 0.6.0", ModUpdates.describe(rows.single()))
    }

    @Test
    fun anUnversionedLocalFileStillReadsSensibly() {
        val rows = ModUpdates.check(
            listOf(mod("sodium.jar")), "1.20.1", "fabric",
            versions(mapOf("sodium" to "0.6.0")),
        )
        assertEquals("未知版本 → 0.6.0", ModUpdates.describe(rows.single()))
    }
}
