package com.pymcl.mobile.data

import android.content.Context
import com.pymcl.mobile.model.VersionEntry
import com.pymcl.mobile.model.VersionManifest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File

class ManifestRepo(
    private val context: Context,
    private val client: OkHttpClient = Http.client,
) {
    suspend fun fetchManifest(forceRefresh: Boolean = false): Result<VersionManifest> =
        withContext(Dispatchers.IO) {
            val cache = Paths.versionManifestCache(context)
            if (!forceRefresh && cache.isFile) {
                runCatching { parseManifest(cache.readText()) }
                    .onSuccess { return@withContext Result.success(it) }
            }
            val urls = listOf(Http.BMCL_MANIFEST, Http.OFFICIAL_MANIFEST)
            for (url in urls) {
                val result = runCatching {
                    val request = Request.Builder().url(url).get().build()
                    client.newCall(request).execute().use { response ->
                        check(response.isSuccessful) { "HTTP ${response.code} from $url" }
                        val body = response.body?.string().orEmpty()
                        cache.parentFile?.mkdirs()
                        cache.writeText(body)
                        parseManifest(body)
                    }
                }
                if (result.isSuccess) return@withContext result
            }
            Result.failure(IllegalStateException("无法拉取版本清单"))
        }

    fun readCached(): VersionManifest? {
        val cache = Paths.versionManifestCache(context)
        if (!cache.isFile) return null
        return runCatching { parseManifest(cache.readText()) }.getOrNull()
    }

    private fun parseManifest(json: String): VersionManifest {
        val root = JSONObject(json)
        val versions = root.getJSONArray("versions")
        val entries = buildList {
            for (i in 0 until versions.length()) {
                val item = versions.getJSONObject(i)
                add(
                    VersionEntry(
                        id = item.getString("id"),
                        type = item.getString("type"),
                        url = item.getString("url"),
                        releaseTime = item.getString("time"),
                    ),
                )
            }
        }
        return VersionManifest(
            latestRelease = root.getJSONObject("latest").getString("release"),
            latestSnapshot = root.getJSONObject("latest").getString("snapshot"),
            versions = entries,
        )
    }
}
