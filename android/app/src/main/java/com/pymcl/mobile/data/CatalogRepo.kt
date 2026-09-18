package com.pymcl.mobile.data

import com.pymcl.mobile.model.CatalogHit
import org.json.JSONObject
import java.net.URLEncoder

object CatalogRepo {
    /**
     * 有专属页面的三个分区名。UI 层按名字分流时引用这几个常量，别在界面文件里
     * 再写一遍中文——那边的中文字面量全要过 t()，而分区名是键，不能翻。
     */
    const val KIND_VANILLA = "原版游戏"
    const val KIND_MODPACK = "整合包"
    const val KIND_WORLD = "世界"
    const val KIND_TASKS = "下载任务"

    /** 世界在 CurseForge 的 classId，跟桌面 `catalog_files.CF_CLASS_WORLD` 同一个数。 */
    const val CF_CLASS_WORLD = 17

    /** 下载页顶部的分区，顺序与桌面 download_hub 一致。 */
    val KINDS = listOf(
        KIND_VANILLA, "Mod", KIND_MODPACK, "数据包", "资源包", "光影包", KIND_WORLD, KIND_TASKS,
    )

    /** 不走网络的分区：本地页面，点进去不该发搜索请求。 */
    val LOCAL_KINDS = setOf(KIND_VANILLA, KIND_TASKS)

    /** 分区 → Modrinth `project_type`。「世界」Modrinth 没有对应类型，返回空串。 */
    fun projectType(kind: String): String = when (kind) {
        "整合包", "modpack" -> "modpack"
        "资源包", "resourcepack" -> "resourcepack"
        "光影包", "shader" -> "shader"
        "数据包", "datapack" -> "datapack"
        "世界", "world" -> ""
        else -> "mod"
    }

    fun searchMods(query: String): List<CatalogHit> = searchKind("Mod", query.ifBlank { "sodium" })

    fun searchKind(kind: String, query: String): List<CatalogHit> {
        val q = query.trim()
        if (q.isEmpty() || kind in LOCAL_KINDS) return emptyList()
        val type = projectType(kind)
        if (type.isEmpty()) return searchWorlds(q)
        val body = Http.getTextFirst(searchUrls(type, q)).second
        return parseModrinth(body)
    }

    /**
     * 世界目录搜索，对齐桌面 `BackendAPI.search_worlds`。
     *
     * Modrinth 没有「世界」这个 project_type，桌面 `catalog_files.search_projects` 在
     * `kind == "world"` 时也是把 Modrinth 那一路直接关掉、只问 CurseForge——这里同理。
     */
    fun searchWorlds(query: String): List<CatalogHit> {
        val q = query.trim()
        if (q.isEmpty()) return emptyList()
        return parseCurseForge(Http.getTextFirst(curseForgeUrls(q)).second)
    }

    /** MCIM 镜像优先、官方垫底——和桌面 `mirrors.py` 的顺序一致。 */
    internal fun searchUrls(type: String, query: String, limit: Int = 20): List<String> {
        val enc = URLEncoder.encode(query, "UTF-8")
        val facets = URLEncoder.encode("[[\"project_type:$type\"]]", "UTF-8")
        val tail = "search?query=$enc&limit=$limit&index=relevance&facets=$facets"
        return listOf(
            "${Paths.MCIM}/modrinth/v2/$tail",
            "https://api.modrinth.com/v2/$tail",
        )
    }

    internal fun parseModrinth(body: String): List<CatalogHit> {
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
                iconUrl = o.optString("icon_url"),
            )
        }
    }

    /**
     * CurseForge 那一路的地址，走 MCIM 的 CF 代理，官方垫底。
     *
     * `sortField=2&sortOrder=desc` 不能省：CurseForge 缺省是升序，漏了会把最冷门的
     * 排到最前面——桌面 `mods.search_curseforge` 也是显式按人气倒序要的。
     */
    internal fun curseForgeUrls(query: String, classId: Int = CF_CLASS_WORLD, limit: Int = 20): List<String> {
        val enc = URLEncoder.encode(query, "UTF-8")
        val tail = "v1/mods/search?gameId=432&classId=$classId&searchFilter=$enc" +
            "&sortField=2&sortOrder=desc&pageSize=$limit"
        return listOf(
            "${Paths.MCIM}/curseforge/$tail",
            "https://api.curseforge.com/$tail",
        )
    }

    internal fun parseCurseForge(body: String): List<CatalogHit> {
        val arr = JSONObject(body).optJSONArray("data") ?: return emptyList()
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            val authors = o.optJSONArray("authors")
            CatalogHit(
                name = o.optString("name"),
                slug = o.optString("slug"),
                description = o.optString("summary"),
                downloads = o.optLong("downloadCount"),
                source = "CurseForge",
                author = authors?.optJSONObject(0)?.optString("name").orEmpty(),
                projectId = o.optString("id"),
                iconUrl = o.optJSONObject("logo")?.optString("thumbnailUrl").orEmpty(),
            )
        }
    }
}
