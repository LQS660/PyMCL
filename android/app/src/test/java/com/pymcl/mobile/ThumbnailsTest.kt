package com.pymcl.mobile

import com.pymcl.mobile.data.ThumbFetcher
import com.pymcl.mobile.data.Thumbnails
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files

/**
 * 缩略图缓存，对照桌面 `mclauncher/thumbnails.py` 与 `tests/test_thumb_negative_cache.py`：
 * 路径怎么算、命中怎么算、过期怎么算、失败冷却多久、冷却表怎么裁。全部用临时目录 + 假下载器。
 */
class ThumbnailsTest {
    private lateinit var dir: File
    private var now = 1_700_000_000_000L

    @Before
    fun fresh() {
        dir = Files.createTempDirectory("thumbs-").toFile()
        Thumbnails.resetFailures()
        Thumbnails.clock = { now }
    }

    @After
    fun cleanup() {
        Thumbnails.clock = { System.currentTimeMillis() }
        Thumbnails.resetFailures()
        dir.deleteRecursively()
    }

    /** 记次数的假下载器：每次都真写一个文件，内容是第几次。 */
    private class CountingFetcher : ThumbFetcher {
        var calls = 0
        override fun fetch(url: String, dest: File) {
            calls++
            dest.writeText("img#$calls")
        }
    }

    private class FailingFetcher : ThumbFetcher {
        var calls = 0
        override fun fetch(url: String, dest: File) {
            calls++
            throw IOException("HTTP 502 $url")
        }
    }

    private val url = "https://cdn.modrinth.com/data/AANobbMI/icon.png"

    // ------------------------------------------------------------------ 路径

    @Test
    fun thumbPathHashesUrlAndKeepsImageSuffix() {
        val p = File(Thumbnails.thumbPath(url, dir))
        assertEquals(dir, p.parentFile)
        assertTrue(p.name.endsWith(".png"))
        // sha1 前 24 位，与桌面 _hash_url 同一口径
        assertEquals(24, p.nameWithoutExtension.length)
        assertTrue(p.nameWithoutExtension.all { it in "0123456789abcdef" })

        assertTrue(Thumbnails.thumbPath("https://x/y/z.JPG?size=64", dir).endsWith(".jpg"))
        assertTrue(Thumbnails.thumbPath("https://x/y/a.webp", dir).endsWith(".webp"))
        // 不认识的后缀 / 没后缀一律 .png；查询串里的点不算后缀
        assertTrue(Thumbnails.thumbPath("https://mc-heads.net/avatar/Steve/128", dir).endsWith(".png"))
        assertTrue(Thumbnails.thumbPath("https://x/y/file.bin", dir).endsWith(".png"))
        assertTrue(Thumbnails.thumbPath("https://x/y/noext?v=1.2", dir).endsWith(".png"))

        assertEquals(Thumbnails.thumbPath(url, dir), Thumbnails.thumbPath(url, dir))
        assertNotEquals(Thumbnails.thumbPath(url, dir), Thumbnails.thumbPath("$url?x=1", dir))
        assertEquals("", Thumbnails.thumbPath("", dir))
        assertEquals("", Thumbnails.thumbPath("   ", dir))
    }

    @Test
    fun hashIsStableAndHexOnly() {
        assertEquals(Thumbnails.hashUrl(url), Thumbnails.hashUrl(url))
        assertEquals(24, Thumbnails.hashUrl("anything").length)
        assertEquals(".png", Thumbnails.extFromUrl("not a url at all"))
    }

    // ------------------------------------------------------------------ 命中 / 过期

    @Test
    fun ensureDownloadsOnceThenServesFromCache() {
        val fetcher = CountingFetcher()
        val first = Thumbnails.ensureThumb(url, dir, fetcher)
        assertEquals(Thumbnails.thumbPath(url, dir), first)
        assertEquals("img#1", File(first).readText())
        assertEquals(1, fetcher.calls)

        val second = Thumbnails.ensureThumb(url, dir, fetcher)
        assertEquals(first, second)
        assertEquals("缓存还在有效期内不该再下", 1, fetcher.calls)
        assertEquals(1, Thumbnails.cachedSize(dir))
    }

    @Test
    fun expiredCacheIsFetchedAgain() {
        val fetcher = CountingFetcher()
        val path = Thumbnails.ensureThumb(url, dir, fetcher)
        val file = File(path)
        // 把文件时间钉死，再把时钟拨到 7 天之后
        assertTrue(file.setLastModified(now))
        now += Thumbnails.CACHE_TTL_MS + 1
        Thumbnails.ensureThumb(url, dir, fetcher)
        assertEquals(2, fetcher.calls)
        assertEquals("img#2", file.readText())
    }

    @Test
    fun blankUrlIsANoop() {
        val fetcher = CountingFetcher()
        assertEquals("", Thumbnails.ensureThumb("", dir, fetcher))
        assertEquals("", Thumbnails.ensureThumb("  ", dir, fetcher))
        assertEquals(0, fetcher.calls)
        assertFalse(Thumbnails.recentlyFailed(""))
    }

    // ------------------------------------------------------------------ 失败冷却

    @Test
    fun failureReturnsEmptyAndIsNotRetriedWithinCooldown() {
        val fetcher = FailingFetcher()
        assertEquals("", Thumbnails.ensureThumb(url, dir, fetcher))
        assertEquals(1, fetcher.calls)
        assertTrue(Thumbnails.recentlyFailed(url))
        // 失败不落盘
        assertEquals(0, Thumbnails.cachedSize(dir))

        // 冷却期内再问：直接回空串，不碰下载器
        assertEquals("", Thumbnails.ensureThumb(url, dir, fetcher))
        assertEquals("", Thumbnails.ensureThumb(url, dir, fetcher))
        assertEquals(1, fetcher.calls)

        // 过了冷却再问才会重试
        now += Thumbnails.FAIL_TTL_MS
        assertFalse(Thumbnails.recentlyFailed(url))
        assertEquals("", Thumbnails.ensureThumb(url, dir, fetcher))
        assertEquals(2, fetcher.calls)
    }

    @Test
    fun successAfterCooldownClearsTheFailure() {
        assertEquals("", Thumbnails.ensureThumb(url, dir, FailingFetcher()))
        assertEquals(1, Thumbnails.failureCount())
        now += Thumbnails.FAIL_TTL_MS
        val ok = CountingFetcher()
        val path = Thumbnails.ensureThumb(url, dir, ok)
        assertTrue(path.isNotEmpty())
        assertEquals(1, ok.calls)
        assertEquals(0, Thumbnails.failureCount())
        assertFalse(Thumbnails.recentlyFailed(url))
    }

    @Test
    fun fetcherThatWritesNothingCountsAsFailure() {
        val silent = ThumbFetcher { _, _ -> }
        assertEquals("", Thumbnails.ensureThumb(url, dir, silent))
        assertTrue(Thumbnails.recentlyFailed(url))
    }

    @Test
    fun failureTableIsCappedAndKeepsTheNewest() {
        val fetcher = FailingFetcher()
        for (i in 0 until Thumbnails.FAIL_CAP) {
            now += 1
            Thumbnails.ensureThumb("https://x/$i.png", dir, fetcher)
        }
        assertEquals(Thumbnails.FAIL_CAP, Thumbnails.failureCount())
        // 第 513 条：先裁到一半再记，新的这一条一定在
        now += 1
        Thumbnails.ensureThumb("https://x/newest.png", dir, fetcher)
        assertEquals(Thumbnails.FAIL_CAP / 2 + 1, Thumbnails.failureCount())
        assertTrue(Thumbnails.recentlyFailed("https://x/newest.png"))
        // 留下的是最近的那一半：最老的被裁掉、最新的旧条目还在
        assertFalse(Thumbnails.recentlyFailed("https://x/0.png"))
        assertTrue(Thumbnails.recentlyFailed("https://x/${Thumbnails.FAIL_CAP - 1}.png"))
    }

    // ------------------------------------------------------------------ 批量 / 清理

    @Test
    fun batchEnsureMapsEveryUrlToPathOrEmpty() {
        val fetcher = ThumbFetcher { u, dest -> if (u.contains("bad")) throw IOException("nope") else dest.writeText("ok") }
        val urls = listOf("https://x/a.png", "https://x/bad.png", "https://x/c.jpg")
        val out = Thumbnails.batchEnsure(urls, dir, fetcher)
        assertEquals(urls, out.keys.toList())
        assertEquals(Thumbnails.thumbPath("https://x/a.png", dir), out["https://x/a.png"])
        assertEquals("", out["https://x/bad.png"])
        assertTrue(out["https://x/c.jpg"]!!.endsWith(".jpg"))
        assertEquals(2, Thumbnails.cachedSize(dir))

        Thumbnails.clearCache(dir)
        assertEquals(0, Thumbnails.cachedSize(dir))
        assertTrue("清缓存只删文件，目录本身留着", dir.isDirectory)
    }

    @Test
    fun cacheHelpersToleratePathsThatDoNotExist() {
        val ghost = File(dir, "nope")
        assertEquals(0, Thumbnails.cachedSize(ghost))
        Thumbnails.clearCache(ghost)
        assertFalse(ghost.exists())
    }
}
