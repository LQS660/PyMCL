package com.pymcl.mobile.data

import com.pymcl.mobile.model.CatalogHit
import org.json.JSONObject

object CatalogRepo {
    fun searchMods(query: String): List<CatalogHit> {
        val q = query.trim().ifEmpty { "sodium" }
        val url = "${Paths.MCIM}/modrinth/v2/search?query=${java.net.URLEncoder.encode(q, "UTF-8")}&limit=20&index=relevance&facets=${
            java.net.URLEncoder.encode("[[\"project_type:mod\"]]", "UTF-8")
        }"
        val fallback = "https://api.modrinth.com/v2/search?query=${java.net.URLEncoder.encode(q, "UTF-8")}&limit=20&index=relevance&facets=${
            java.net.URLEncoder.encode("[[\"project_type:mod\"]]", "UTF-8")
        }"
        val body = try {
            Http.getText(url)
        } catch (_: Exception) {
            Http.getText(fallback)
        }
        val hits = JSONObject(body).optJSONArray("hits") ?: return emptyList()
        return (0 until hits.length()).map { i ->
            val o = hits.getJSONObject(i)
            CatalogHit(
                name = o.optString("title"),
                slug = o.optString("slug"),
                description = o.optString("description"),
                downloads = o.optLong("downloads"),
                source = "Modrinth",
                author = o.optString("author"),
                projectId = o.optString("project_id"),
            )
        }
    }

    fun searchKind(kind: String, query: String): List<CatalogHit> {
        val q = query.trim()
        if (q.isEmpty()) return emptyList()
        val type = when (kind) {
            "整合包" -> "modpack"
            "资源包" -> "resourcepack"
            "光影包" -> "shader"
            "数据包" -> "datapack"
            else -> "mod"
        }
        val facets = java.net.URLEncoder.encode("[[\"project_type:$type\"]]", "UTF-8")
        val enc = java.net.URLEncoder.encode(q, "UTF-8")
        val url = "${Paths.MCIM}/modrinth/v2/search?query=$enc&limit=20&index=relevance&facets=$facets"
        val body = Http.getText(url)
        val hits = JSONObject(body).optJSONArray("hits") ?: return emptyList()
        return (0 until hits.length()).map { i ->
            val o = hits.getJSONObject(i)
            CatalogHit(
                name = o.optString("title"),
                slug = o.optString("slug"),
                description = o.optString("description"),
                downloads = o.optLong("downloads"),
                source = "Modrinth",
                author = o.optString("author"),
                projectId = o.optString("project_id"),
            )
        }
    }
}
