package com.pymcl.mobile.data

import com.pymcl.mobile.model.CatalogHit
import org.json.JSONArray
import org.json.JSONObject

/**
 * 收藏夹里的一条。四个字段与桌面 `BackendAPI.toggle_favorite` 写进 config 的那四个键同名，
 * 所以两端读写的是同一份 `catalog_favorites`：桌面收藏的项目手机上能看见，反过来也一样。
 */
data class FavoriteItem(
    val name: String,
    val source: String,
    val slug: String = "",
    val id: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("name", name)
        .put("source", source)
        .put("slug", slug)
        .put("id", id)
}

/**
 * 商店收藏夹，对齐桌面 `BackendAPI.catalog_favorites` / `toggle_favorite`。
 *
 * 判重键跟桌面一字不差：`(来源, slug 或 id 或 名字)`。桌面那边缺字段写的是 `null`，
 * 这里写空串——两种在桌面的 `str(... or ...)` 下都是假值，落到同一条键上，不会重复收藏。
 *
 * 列表的增删是纯函数（[toggleIn] / [contains]），落盘那一步才碰 [Settings]。
 */
object CatalogFavorites {
    /** 判重键。先 slug、没有就 id、再没有就拿名字顶，跟桌面同序。 */
    fun keyOf(item: FavoriteItem): Pair<String, String> =
        item.source to listOf(item.slug, item.id, item.name).firstOrNull { it.isNotBlank() }.orEmpty()

    fun contains(rows: List<FavoriteItem>, item: FavoriteItem): Boolean =
        rows.any { keyOf(it) == keyOf(item) }

    /** 收了就取消、没收就加到末尾——一次点击的结果就是这张新表。 */
    fun toggleIn(rows: List<FavoriteItem>, item: FavoriteItem): List<FavoriteItem> {
        val key = keyOf(item)
        val kept = rows.filter { keyOf(it) != key }
        return if (kept.size != rows.size) kept else kept + item
    }

    fun parse(arr: JSONArray?): List<FavoriteItem> {
        if (arr == null) return emptyList()
        val out = ArrayList<FavoriteItem>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val item = FavoriteItem(
                name = text(o, "name"),
                source = text(o, "source"),
                slug = text(o, "slug"),
                id = text(o, "id"),
            )
            // 四个字段全空的一条点不开也装不了，读回来只会在列表里占一行空白
            if (keyOf(item).second.isNotBlank()) out.add(item)
        }
        return out
    }

    fun toJson(rows: List<FavoriteItem>): JSONArray {
        val arr = JSONArray()
        rows.forEach { arr.put(it.toJson()) }
        return arr
    }

    fun list(): List<FavoriteItem> = parse(Settings.all().optJSONArray(SettingsKeys.CATALOG_FAVORITES))

    fun toggle(item: FavoriteItem): List<FavoriteItem> = save(toggleIn(list(), item))

    fun save(rows: List<FavoriteItem>): List<FavoriteItem> {
        Settings.set(SettingsKeys.CATALOG_FAVORITES, toJson(rows))
        Settings.flushIfDirty()
        return rows
    }

    /** 搜索结果 → 收藏条目。描述、下载量这些会过期的字段不存，用时现搜。 */
    fun of(hit: CatalogHit): FavoriteItem =
        FavoriteItem(name = hit.name, source = hit.source, slug = hit.slug, id = hit.projectId)

    /** 收藏条目 → 搜索结果，让收藏夹里那一行能直接走安装那条路。 */
    fun toHit(item: FavoriteItem): CatalogHit = CatalogHit(
        name = item.name,
        slug = item.slug,
        description = "",
        downloads = 0,
        source = item.source,
        projectId = item.id,
    )

    private fun text(o: JSONObject, key: String): String {
        if (o.isNull(key)) return ""
        return o.optString(key).trim()
    }
}
