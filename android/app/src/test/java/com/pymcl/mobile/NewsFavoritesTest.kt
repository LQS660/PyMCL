package com.pymcl.mobile

import com.pymcl.mobile.data.CatalogFavorites
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.ContentInstall
import com.pymcl.mobile.data.FavoriteItem
import com.pymcl.mobile.data.FileKind
import com.pymcl.mobile.data.NewsItem
import com.pymcl.mobile.data.NewsRepo
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.model.CatalogHit
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 启动页资讯、商店收藏夹、世界目录搜索三条的纯逻辑部分。
 * 全程不联网：拉取走注入的 [TextFetcher]，缓存与配置都指到临时目录。
 */
class NewsFavoritesTest {
    private lateinit var tmp: File

    @Before
    fun setUp() {
        tmp = kotlin.io.path.createTempDirectory("pymcl-news").toFile()
    }

    @After
    fun tearDown() {
        // 配置是全局单例，别把这一条测试写进去的东西留给下一条
        Settings.loadFromForTest(File(tmp, "no-such-config.json"))
        tmp.deleteRecursively()
    }

    private fun cache() = File(tmp, "cache/news.json")

    /** 按地址给正文；表里没有的地址当拉不到（返回 null）。 */
    private fun fetcher(vararg pairs: Pair<String, String>) = TextFetcher { urls, _ ->
        urls.firstNotNullOfOrNull { url -> pairs.firstOrNull { it.first == url }?.second }
    }

    // ---------------------------------------------------------------- 资讯解析

    @Test
    fun parsesTheV2PatchNotesShape() {
        val rows = NewsRepo.parse(
            """{"version":1,"entries":[
                 {"title":"1.21.4","version":"1.21.4","shortText":"冬季更新",
                  "image":{"url":"https://img/1.png","title":"x"},"date":"2026-09-18T10:00:00Z"}]}""",
        )
        assertEquals(1, rows.size)
        assertEquals("1.21.4", rows[0].title)
        assertEquals("冬季更新", rows[0].body)
        assertEquals("https://img/1.png", rows[0].image)
        // 日期只留 yyyy-mm-dd，跟桌面 news._rows_from 的 [:10] 一致
        assertEquals("2026-09-18", rows[0].date)
    }

    @Test
    fun parsesTheLegacyPatchNotesKeyAndBareArray() {
        assertEquals("旧", NewsRepo.parse("""{"patchNotes":[{"title":"旧"}]}""")[0].title)
        assertEquals("裸的", NewsRepo.parse("""[{"title":"裸的"}]""")[0].title)
    }

    @Test
    fun fallsBackThroughTitleBodyAndImageKeys() {
        val rows = NewsRepo.parse(
            """{"entries":[{"id":"24w40a","body":"快照","cardBackground":"https://img/2.png","updated_at":"2026-01-02"}]}""",
        )
        // 没 title 就拿 version，再没有就拿 id——三级回落跟桌面同序
        assertEquals("24w40a", rows[0].title)
        assertEquals("24w40a", rows[0].version)
        assertEquals("快照", rows[0].body)
        assertEquals("https://img/2.png", rows[0].image)
        assertEquals("2026-01-02", rows[0].date)
    }

    @Test
    fun longBodyIsClippedLikeDesktop() {
        val long = "字".repeat(400)
        val row = NewsRepo.parse("""{"entries":[{"title":"t","shortText":"$long"}]}""")[0]
        assertEquals(NewsRepo.BODY_LIMIT + 1, row.body.length)
        assertTrue(row.body.endsWith("…"))
    }

    @Test
    fun atMostTwelveRowsComeBack() {
        val entries = (1..30).joinToString(",") { """{"title":"t$it"}""" }
        assertEquals(NewsRepo.MAX_ROWS, NewsRepo.parse("""{"entries":[$entries]}""").size)
    }

    @Test
    fun brokenPayloadsAreEmptyNotACrash() {
        for (junk in listOf("", "   ", "这不是 JSON", "{{{", "null", "{}", """{"entries":"oops"}""", "[1,2,3]")) {
            assertTrue("junk: $junk", NewsRepo.parse(junk).isEmpty())
        }
    }

    // ---------------------------------------------------------------- 资讯缓存

    @Test
    fun cacheRoundTripsThroughDisk() {
        val rows = listOf(NewsItem("标题", "正文", "1.21", "https://img", "2026-09-18"))
        NewsRepo.writeCache(rows, cache())
        assertEquals(rows, NewsRepo.loadCached(cache()))
    }

    @Test
    fun missingCacheIsEmpty() {
        assertTrue(NewsRepo.loadCached(cache()).isEmpty())
    }

    @Test
    fun fetchWritesTheCacheAndPrefersTheFirstUrl() {
        val rows = NewsRepo.fetch(
            fetcher(NewsRepo.URLS[0] to """{"entries":[{"title":"新的"}]}"""),
            cache(),
        )
        assertEquals(listOf("新的"), rows.map { it.title })
        assertEquals(listOf("新的"), NewsRepo.loadCached(cache()).map { it.title })
    }

    @Test
    fun fetchFallsToTheSecondUrlWhenTheFirstGivesNothingUsable() {
        val rows = NewsRepo.fetch(
            fetcher(
                NewsRepo.URLS[0] to "<html>404</html>",
                NewsRepo.URLS[1] to """{"patchNotes":[{"title":"老地址"}]}""",
            ),
            cache(),
        )
        assertEquals(listOf("老地址"), rows.map { it.title })
    }

    @Test
    fun offlineKeepsTheCachedRowsInsteadOfBlankingTheCard() {
        NewsRepo.writeCache(listOf(NewsItem("上次的", "正文")), cache())
        val rows = NewsRepo.fetch(TextFetcher { _, _ -> null }, cache())
        assertEquals(listOf("上次的"), rows.map { it.title })
        // 拉不到时不能把上一份缓存冲掉
        assertEquals(listOf("上次的"), NewsRepo.loadCached(cache()).map { it.title })
    }

    @Test
    fun offlineWithoutCacheIsEmpty() {
        assertTrue(NewsRepo.fetch(TextFetcher { _, _ -> null }, cache()).isEmpty())
    }

    // ---------------------------------------------------------------- 收藏夹

    private val sodium = CatalogHit("Sodium", "sodium", "fast", 42, "Modrinth", "jelly", "AA")

    @Test
    fun favoriteKeyFallsBackFromSlugToIdToName() {
        assertEquals("sodium", CatalogFavorites.keyOf(FavoriteItem("Sodium", "Modrinth", "sodium", "AA")).second)
        assertEquals("AA", CatalogFavorites.keyOf(FavoriteItem("Sodium", "Modrinth", "", "AA")).second)
        assertEquals("Sodium", CatalogFavorites.keyOf(FavoriteItem("Sodium", "Modrinth")).second)
    }

    @Test
    fun togglingAddsThenRemovesTheSameProject() {
        val item = CatalogFavorites.of(sodium)
        val added = CatalogFavorites.toggleIn(emptyList(), item)
        assertEquals(listOf(item), added)
        assertTrue(CatalogFavorites.contains(added, item))
        assertEquals(emptyList<FavoriteItem>(), CatalogFavorites.toggleIn(added, item))
    }

    @Test
    fun sameSlugFromAnotherSourceIsADifferentFavorite() {
        val mr = CatalogFavorites.of(sodium)
        val cf = mr.copy(source = "CurseForge")
        val rows = CatalogFavorites.toggleIn(CatalogFavorites.toggleIn(emptyList(), mr), cf)
        assertEquals(2, rows.size)
        // 改了显示名但 slug 没变，仍然算同一条：再点一次是取消而不是又加一条
        assertEquals(1, CatalogFavorites.toggleIn(rows, mr.copy(name = "Sodium 中文名")).size)
    }

    @Test
    fun favoritesRoundTripThroughJson() {
        val rows = listOf(CatalogFavorites.of(sodium), FavoriteItem("天空岛", "CurseForge", "", "99"))
        assertEquals(rows, CatalogFavorites.parse(CatalogFavorites.toJson(rows)))
    }

    @Test
    fun favoritesWrittenByDesktopAreReadBack() {
        // 桌面 toggle_favorite 缺字段写的是 null，读回来不能变成 "null" 这四个字母
        File(tmp, "config.json").writeText(
            """{"catalog_favorites":[
                 {"name":"天空岛","source":"CurseForge","slug":null,"id":"99"},
                 {"name":"","source":"","slug":null,"id":null}]}""",
            Charsets.UTF_8,
        )
        Settings.loadFromForTest(File(tmp, "config.json"))

        val rows = CatalogFavorites.list()
        // 四个字段全空的那条读不出键，直接丢掉
        assertEquals(1, rows.size)
        assertEquals("天空岛", rows[0].name)
        assertEquals("", rows[0].slug)
        assertEquals("99", rows[0].id)
        assertEquals(SettingsKeys.CATALOG_FAVORITES, "catalog_favorites")
    }

    @Test
    fun noFavoritesKeyMeansEmptyNotACrash() {
        Settings.loadFromForTest(File(tmp, "empty.json"))
        assertEquals(emptyList<FavoriteItem>(), CatalogFavorites.list())
    }

    @Test
    fun favoriteGoesBackToAHitThatCanBeInstalled() {
        val hit = CatalogFavorites.toHit(CatalogFavorites.of(sodium))
        assertEquals(sodium.name, hit.name)
        assertEquals(sodium.slug, hit.slug)
        assertEquals(sodium.source, hit.source)
        assertEquals(sodium.projectId, hit.projectId)
    }

    // ---------------------------------------------------------------- 世界搜索

    @Test
    fun worldSearchUrlsCarryClassIdAndPopularityOrder() {
        val urls = CatalogRepo.curseForgeUrls("skyblock")
        assertEquals(2, urls.size)
        assertTrue(urls[0].contains("mcimirror.top"))
        assertTrue(urls[1].startsWith("https://api.curseforge.com/"))
        urls.forEach {
            assertTrue(it.contains("classId=${CatalogRepo.CF_CLASS_WORLD}"))
            assertTrue(it.contains("gameId=432"))
            // 缺省是升序，漏了这两个参数最冷门的会排最前
            assertTrue(it.contains("sortField=2"))
            assertTrue(it.contains("sortOrder=desc"))
        }
    }

    @Test
    fun worldSearchEncodesChineseQuery() {
        assertTrue(CatalogRepo.curseForgeUrls("空岛").all { it.contains("%E7%A9%BA%E5%B2%9B") })
    }

    @Test
    fun blankWorldQueryNeverHitsTheNetwork() {
        assertEquals(emptyList<CatalogHit>(), CatalogRepo.searchWorlds(""))
        assertEquals(emptyList<CatalogHit>(), CatalogRepo.searchWorlds("  "))
        assertEquals(emptyList<CatalogHit>(), CatalogRepo.searchKind(CatalogRepo.KIND_WORLD, ""))
    }

    @Test
    fun worldTabIsWiredToTheCurseForgeOnlyPath() {
        assertTrue(CatalogRepo.KIND_WORLD in CatalogRepo.KINDS)
        assertFalse(CatalogRepo.KIND_WORLD in CatalogRepo.LOCAL_KINDS)
        assertEquals("", CatalogRepo.projectType(CatalogRepo.KIND_WORLD))
    }

    @Test
    fun worldsArePickedWithoutALoaderFilter() {
        assertEquals("", ContentInstall.loaderFor(FileKind.WORLD, "fabric"))
        assertEquals("fabric", ContentInstall.loaderFor(FileKind.MOD, "fabric"))
    }
}
