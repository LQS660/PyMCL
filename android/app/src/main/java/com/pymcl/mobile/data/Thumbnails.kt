package com.pymcl.mobile.data

import java.io.File
import java.net.URI
import java.security.MessageDigest

/**
 * 搜索结果图标 / 账号头像的缩略图缓存，对齐桌面 `mclauncher/thumbnails.py`。
 *
 * - [thumbPath]：url → 本地缓存路径（文件可能还不存在），`cache/thumbs/<sha1(url) 前 24 位><后缀>`；
 * - [ensureThumb]：命中且没过期（7 天）直接给路径；否则下载落盘，失败回空串；
 * - 失败会记进冷却表：10 分钟内再问同一个 url 直接回空串、不碰网络。桌面那边踩过的坑——
 *   失败不落盘、又没有冷却，账号页每刷一次就把每个头像重新排队，线程池被塞满，
 *   目录页的图标排在后面等；表满 512 条时只留最近的一半。
 *
 * 目录与下载都能注入：单测用临时目录和假的 [ThumbFetcher]，一行网络不沾。
 */
fun interface ThumbFetcher {
    /** 把 [url] 下到 [dest]；失败抛异常即可，冷却表由调用方记。 */
    fun fetch(url: String, dest: File)
}

object Thumbnails {
    const val CACHE_TTL_MS: Long = 7L * 24 * 3600 * 1000
    const val FAIL_TTL_MS: Long = 10L * 60 * 1000
    const val FAIL_CAP = 512

    private val IMAGE_SUFFIXES = setOf(".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico")

    private val lock = Any()
    private val recentFailures = HashMap<String, Long>()

    /** 时钟可替换：单测里把「7 天后」「10 分钟后」拨出来，不用真等。 */
    @Volatile
    internal var clock: () -> Long = { System.currentTimeMillis() }

    /** 真身：走 [Http.download]（`.part` 落成再改名，半个文件不会被当成缓存）。 */
    val httpFetcher: ThumbFetcher = ThumbFetcher { url, dest -> Http.download(url, dest) }

    /** 缓存目录，跟桌面一样挂在 cache 下。 */
    fun dir(): File = File(Paths.cache, "thumbs").also { it.mkdirs() }

    /** 桌面 `_hash_url`：sha1 十六进制取前 24 位。 */
    fun hashUrl(url: String): String {
        val md = MessageDigest.getInstance("SHA-1")
        md.update(url.toByteArray(Charsets.UTF_8))
        return md.digest().joinToString("") { "%02x".format(it) }.take(24)
    }

    /** 桌面 `_ext_from_url`：只认几种图片后缀，其余一律 .png。 */
    fun extFromUrl(url: String): String {
        val path = runCatching { URI(url).path }.getOrNull().orEmpty()
        val slash = path.lastIndexOf('/')
        val dot = path.lastIndexOf('.')
        val suffix = if (dot > slash) path.substring(dot).lowercase() else ""
        return if (suffix in IMAGE_SUFFIXES) suffix else ".png"
    }

    /** 本地缓存路径；空 url 给空串。文件可能不存在——只查位置，不联网。 */
    fun thumbPath(url: String, dir: File = dir()): String {
        if (url.isBlank()) return ""
        return File(dir, hashUrl(url) + extFromUrl(url)).path
    }

    /** 这个 url 刚下过没下成、还在冷却期，别再排队。 */
    fun recentlyFailed(url: String): Boolean {
        if (url.isBlank()) return false
        synchronized(lock) {
            val stamp = recentFailures[url] ?: return false
            if (clock() - stamp >= FAIL_TTL_MS) {
                recentFailures.remove(url)
                return false
            }
            return true
        }
    }

    internal fun noteFailure(url: String) {
        synchronized(lock) {
            recentFailures.remove(url)
            if (recentFailures.size >= FAIL_CAP) {
                // 只留最近的一半，别让一个长会话把这张表攒成漏；先裁再记，这一条一定留下
                val keep = recentFailures.entries.sortedBy { it.value }.takeLast(FAIL_CAP / 2)
                recentFailures.clear()
                keep.forEach { recentFailures[it.key] = it.value }
            }
            recentFailures[url] = clock()
        }
    }

    internal fun forgetFailure(url: String) {
        synchronized(lock) { recentFailures.remove(url) }
    }

    /** 冷却表条数，给单测与设置页看。 */
    fun failureCount(): Int = synchronized(lock) { recentFailures.size }

    fun resetFailures() = synchronized(lock) { recentFailures.clear() }

    /**
     * 确保缩略图已缓存，返回本地路径（失败返回空串）。
     *
     * 缓存 7 天内有效；过期或没有就重下。失败记进冷却表，[FAIL_TTL_MS] 内不再碰网络。
     */
    fun ensureThumb(url: String, dir: File = dir(), fetcher: ThumbFetcher = httpFetcher): String {
        if (url.isBlank()) return ""
        val local = thumbPath(url, dir)
        val file = File(local)
        if (file.isFile && clock() - file.lastModified() < CACHE_TTL_MS) return local
        if (recentlyFailed(url)) return ""
        try {
            file.parentFile?.mkdirs()
            fetcher.fetch(url, file)
        } catch (e: Exception) {
            noteFailure(url)
            return ""
        }
        if (!file.isFile) {
            noteFailure(url)
            return ""
        }
        forgetFailure(url)
        return local
    }

    /** 批量：{url: 本地路径或空串}。 */
    fun batchEnsure(
        urls: List<String>,
        dir: File = dir(),
        fetcher: ThumbFetcher = httpFetcher,
    ): Map<String, String> {
        val out = LinkedHashMap<String, String>()
        for (u in urls) out[u] = ensureThumb(u, dir, fetcher)
        return out
    }

    fun clearCache(dir: File = dir()) {
        if (!dir.isDirectory) return
        dir.listFiles()?.forEach { f -> if (f.isFile) f.delete() }
    }

    fun cachedSize(dir: File = dir()): Int {
        if (!dir.isDirectory) return 0
        return dir.listFiles()?.count { it.isFile } ?: 0
    }
}
