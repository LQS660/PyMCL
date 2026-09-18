package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** 启动页资讯的一条。字段与桌面 `mclauncher/news.py` 落盘的那份逐个对齐。 */
data class NewsItem(
    val title: String,
    val body: String,
    val version: String = "",
    val image: String = "",
    val date: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("title", title)
        .put("body", body)
        .put("version", version)
        .put("image", image)
        .put("date", date)
}

/**
 * 启动页新闻：Mojang 的 launchercontent，拉不到就走缓存。
 *
 * 对齐桌面 `mclauncher/news.py`——同样两个地址、同样 12 条上限、同样 160 字截断，
 * 缓存也落在 `cache/news.json`，所以桌面写下的那份拷到手机上直接能读。
 *
 * 解析与缓存都是纯函数 + 显式传文件，网络走注入进来的 [TextFetcher]：
 * 整条逻辑不联网也能测。
 */
object NewsRepo {
    /** v2 在前、老地址垫底，跟桌面 `news.URLS` 同序。 */
    val URLS = listOf(
        "https://launchercontent.mojang.com/v2/javaPatchNotes.json",
        "https://launchercontent.mojang.com/javaPatchNotes.json",
    )

    const val MAX_ROWS = 12
    const val BODY_LIMIT = 160

    /** 首页那张卡只列前几条，跟桌面 `_fill_news` 一致。 */
    const val CARD_ROWS = 6

    val cacheFile: File get() = File(Paths.cache, "news.json")

    /** 上游给的整份 JSON → 归一化的几条。认对象（entries / patchNotes）也认裸数组。 */
    fun parse(text: String): List<NewsItem> {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return emptyList()
        if (trimmed.startsWith("[")) {
            return rowsFrom(runCatching { JSONArray(trimmed) }.getOrNull())
        }
        val obj = runCatching { JSONObject(trimmed) }.getOrNull() ?: return emptyList()
        return rowsFrom(obj.optJSONArray("entries") ?: obj.optJSONArray("patchNotes"))
    }

    fun rowsFrom(entries: JSONArray?): List<NewsItem> {
        if (entries == null) return emptyList()
        val out = ArrayList<NewsItem>()
        for (i in 0 until minOf(entries.length(), MAX_ROWS)) {
            val o = entries.optJSONObject(i) ?: continue
            out.add(
                NewsItem(
                    title = firstOf(o, "title", "version", "id"),
                    body = clip(firstOf(o, "shortText", "body", "subtitle")),
                    version = firstOf(o, "version", "id"),
                    image = imageOf(o),
                    date = firstOf(o, "date", "updated_at").take(10),
                ),
            )
        }
        return out
    }

    fun loadCached(file: File = cacheFile): List<NewsItem> {
        if (!file.isFile) return emptyList()
        return parse(runCatching { file.readText(Charsets.UTF_8) }.getOrDefault(""))
    }

    fun writeCache(rows: List<NewsItem>, file: File = cacheFile) {
        file.parentFile?.mkdirs()
        val arr = JSONArray()
        rows.forEach { arr.put(it.toJson()) }
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(arr.toString(2), Charsets.UTF_8)
        if (file.exists()) file.delete()
        if (!tmp.renameTo(file)) {
            file.writeText(arr.toString(2), Charsets.UTF_8)
            tmp.delete()
        }
    }

    /**
     * 拉一次。地址挨个试，**第一个真解出东西来的**才算成功并顺手刷新缓存；
     * 一条都没拉到就原样退回缓存里的那份，而不是把界面清空。
     */
    fun fetch(fetcher: TextFetcher, file: File = cacheFile): List<NewsItem> {
        for (url in URLS) {
            val body = fetcher.get(listOf(url), CatalogFiles.JSON_HEADERS) ?: continue
            val rows = parse(body)
            if (rows.isEmpty()) continue
            runCatching { writeCache(rows, file) }
            return rows
        }
        return loadCached(file)
    }

    private fun firstOf(o: JSONObject, vararg keys: String): String {
        for (key in keys) {
            val value = o.optString(key)
            if (value.isNotEmpty() && value != "null") return value
        }
        return ""
    }

    /** 正文超长就截断加省略号——卡片只有两行，整篇更新日志贴上去会把卡撑破。 */
    private fun clip(body: String): String {
        val text = body.trim()
        return if (text.length > BODY_LIMIT) text.take(BODY_LIMIT) + "…" else text
    }

    /** 上游的封面有时是 `{"url":…}`，有时直接就是一个地址串。 */
    private fun imageOf(o: JSONObject): String {
        for (key in listOf("image", "cardBackground")) {
            o.optJSONObject(key)?.let { nested ->
                val url = nested.optString("url")
                if (url.isNotEmpty()) return url
            }
            val direct = o.optString(key)
            if (direct.isNotEmpty() && direct != "null" && !direct.startsWith("{")) return direct
        }
        return ""
    }
}
