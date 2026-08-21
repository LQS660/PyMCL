package com.pymcl.mobile.data

import com.pymcl.mobile.model.ModSearchResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray

class CatalogRepo(private val client: OkHttpClient = Http.client) {
    suspend fun searchMods(query: String, limit: Int = 20): Result<List<ModSearchResult>> =
        withContext(Dispatchers.IO) {
            if (query.isBlank()) return@withContext Result.success(emptyList())
            val url = Http.MODRINTH_API.toHttpUrlOrNull()
                ?.newBuilder()
                ?.addPathSegments("search")
                ?.addQueryParameter("query", query)
                ?.addQueryParameter("limit", limit.toString())
                ?.build()
                ?: return@withContext Result.failure(IllegalArgumentException("无效 API URL"))
            runCatching {
                val request = Request.Builder().url(url).get().build()
                client.newCall(request).execute().use { response ->
                    check(response.isSuccessful) { "HTTP ${response.code}" }
                    parseResults(JSONArray(response.body?.string().orEmpty()))
                }
            }
        }

    private fun parseResults(array: JSONArray): List<ModSearchResult> = buildList {
        for (i in 0 until array.length()) {
            val item = array.getJSONObject(i)
            add(
                ModSearchResult(
                    projectId = item.getString("project_id"),
                    slug = item.getString("slug"),
                    title = item.getString("title"),
                    description = item.optString("description"),
                    downloads = item.optLong("downloads"),
                ),
            )
        }
    }
}
