package com.pymcl.mobile.data

import com.pymcl.mobile.model.VersionRow
import org.json.JSONObject

object ManifestRepo {
    fun fetch(force: Boolean = false): List<VersionRow> {
        if (!force && Paths.manifestCache.isFile &&
            System.currentTimeMillis() - Paths.manifestCache.lastModified() < 4 * 3600_000
        ) {
            runCatching { return parse(JSONObject(Paths.manifestCache.readText())) }
        }
        val (_, body) = Http.getTextFirst(listOf(Paths.BMCL_MANIFEST, Paths.MOJANG_MANIFEST))
        Paths.manifestCache.writeText(body, Charsets.UTF_8)
        return parse(JSONObject(body))
    }

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

    fun fetchVersionJson(row: VersionRow): JSONObject {
        val cache = java.io.File(Paths.cache, "${row.id}.json")
        if (cache.isFile) {
            runCatching { return JSONObject(cache.readText()) }
        }
        val (_, body) = Http.getTextFirst(Names.expand(row.url))
        cache.writeText(body, Charsets.UTF_8)
        return JSONObject(body)
    }
}
