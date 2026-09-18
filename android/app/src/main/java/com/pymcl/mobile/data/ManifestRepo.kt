package com.pymcl.mobile.data

import com.pymcl.mobile.model.VersionRow
import org.json.JSONObject
import java.io.File

object ManifestRepo {
    private const val CACHE_TTL_MS = 4 * 3600_000L

    fun fetch(force: Boolean = false): List<VersionRow> {
        if (!force && fresh(Paths.manifestCache)) {
            runCatching { return parse(JSONObject(Paths.manifestCache.readText())) }
        }
        val (_, body) = Http.getTextFirst(listOf(Paths.BMCL_MANIFEST, Paths.MOJANG_MANIFEST))
        Paths.manifestCache.writeText(body, Charsets.UTF_8)
        return parse(JSONObject(body))
    }

    internal fun fresh(cache: File, now: Long = System.currentTimeMillis()): Boolean =
        cache.isFile && now - cache.lastModified() < CACHE_TTL_MS

    fun parse(root: JSONObject): List<VersionRow> {
        val arr = root.optJSONArray("versions") ?: return emptyList()
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            VersionRow(
                id = o.optString("id"),
                type = o.optString("type"),
                url = o.optString("url"),
                sha1 = o.optString("sha1"),
                releaseTime = o.optString("releaseTime"),
            )
        }
    }

    fun latest(root: JSONObject): Pair<String, String> {
        val latest = root.optJSONObject("latest") ?: return "" to ""
        return latest.optString("release") to latest.optString("snapshot")
    }

    fun fetchVersionJson(row: VersionRow): JSONObject {
        val cache = File(Paths.cache, "${row.id}.json")
        if (cache.isFile) {
            runCatching { return JSONObject(cache.readText()) }
        }
        val (_, body) = Http.getTextFirst(Names.expand(row.url))
        cache.writeText(body, Charsets.UTF_8)
        return JSONObject(body)
    }
}
