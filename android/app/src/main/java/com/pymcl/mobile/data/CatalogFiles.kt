package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

/**
 * 把「搜到一个 mod / 整合包」接到「拿到具体文件的下载地址」，对齐桌面
 * mclauncher/mods.py 的 `list_versions` / `cf_files`。
 *
 * 分工跟前几轮一致：
 * - `parse*` 是**纯函数**，收 JSON 文本给候选列表，所以解析与挑选全都能不联网地测；
 * - 真正的拉取走注入进来的 [TextFetcher]。
 *
 * **源码里不放任何 key。** CurseForge 的 API key 跟 AI 密钥一个口径，从
 * config.json 读（[CatalogKeys.fromConfig]）；没填就只走 Modrinth，并给一句
 * 能直接上屏的话，而不是闷着报个错。
 */

/** 拉一段文本。多个候选地址按顺序试（镜像在前、官方垫底）。拿不到给 null。 */
fun interface TextFetcher {
    fun get(urls: List<String>, headers: Map<String, String>): String?
}

data class CatalogKeys(val curseForgeApiKey: String = "") {
    val hasCurseForge: Boolean get() = curseForgeApiKey.isNotBlank()

    companion object {
        const val CONFIG_KEY = "curseforge_api_key"

        /** 从 config.json 读。碰 [Paths]，所以只能在设备上跑。 */
        fun fromConfig(): CatalogKeys =
            CatalogKeys(runCatching { InstanceStore.loadConfig().optString(CONFIG_KEY) }.getOrDefault(""))
    }
}

object CatalogFiles {
    const val MODRINTH_OFFICIAL = "https://api.modrinth.com/v2"
    const val CURSEFORGE_OFFICIAL = "https://api.curseforge.com/v1"

    /** 没有 key 时给用户看的那句话。放在这儿是为了只写一遍。 */
    const val NEED_KEY_MESSAGE =
        "CurseForge 需要 API key 才能查下载地址。去设置里填上，或者改用 Modrinth 上的同名项目。"

    val JSON_HEADERS = mapOf("Accept" to "application/json")

    // ------------------------------------------------------------ 地址

    fun modrinthVersionUrls(slug: String, mcVersion: String = "", loader: String = ""): List<String> {
        val q = StringBuilder()
        if (mcVersion.isNotBlank()) q.append("?game_versions=").append(enc("[\"$mcVersion\"]"))
        if (loader.isNotBlank()) {
            q.append(if (q.isEmpty()) "?" else "&").append("loaders=").append(enc("[\"${VersionPick.normalizeLoader(loader)}\"]"))
        }
        val tail = "/project/${enc(slug)}/version$q"
        // MCIM 镜像在前，官方垫底；国内直连官方经常超时
        return listOf("${Paths.MCIM}/modrinth/v2$tail", "$MODRINTH_OFFICIAL$tail")
    }

    fun curseForgeFileUrls(projectId: Long, mcVersion: String = "", loader: String = ""): List<String> {
        val q = StringBuilder("?pageSize=50")
        if (mcVersion.isNotBlank()) q.append("&gameVersion=").append(enc(mcVersion))
        cfLoaderType(loader)?.let { q.append("&modLoaderType=").append(it) }
        return listOf("$CURSEFORGE_OFFICIAL/mods/$projectId/files$q")
    }

    // ------------------------------------------------------------ 解析（纯）

    /** Modrinth `/project/{slug}/version` 的响应。解不动就返回空表，不抛。 */
    fun parseModrinthVersions(json: String): List<CatalogVersion> {
        val arr = runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        val out = ArrayList<CatalogVersion>(arr.length())
        for (i in 0 until arr.length()) {
            val v = arr.optJSONObject(i) ?: continue
            val files = parseModrinthFiles(v.optJSONArray("files"))
            out.add(
                CatalogVersion(
                    id = v.optString("id"),
                    name = v.optString("name"),
                    versionNumber = v.optString("version_number"),
                    channel = v.optString("version_type").ifBlank { CatalogVersion.CHANNEL_RELEASE },
                    gameVersions = stringsOf(v.optJSONArray("game_versions")),
                    loaders = stringsOf(v.optJSONArray("loaders")).map { VersionPick.normalizeLoader(it) },
                    files = files,
                    published = v.optString("date_published"),
                    source = CatalogSource.MODRINTH,
                ),
            )
        }
        return out
    }

    /** CurseForge `/mods/{id}/files` 的响应。 */
    fun parseCurseForgeFiles(json: String): List<CatalogVersion> {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return emptyList()
        val arr = root.optJSONArray("data") ?: return emptyList()
        val out = ArrayList<CatalogVersion>(arr.length())
        for (i in 0 until arr.length()) {
            val f = arr.optJSONObject(i) ?: continue
            val url = f.optString("downloadUrl")
            val name = f.optString("fileName")
            // CF 的 gameVersions 是一锅端：MC 版本号和加载器名混在同一个数组里
            val raw = stringsOf(f.optJSONArray("gameVersions"))
            val loaders = raw.mapNotNull { knownLoader(it) }.distinct()
            val games = raw.filterNot { looksLikeLoader(it) }
            val files = if (url.isBlank() || name.isBlank()) {
                emptyList()
            } else {
                listOf(PackFile(name, listOf(url), sha1 = cfSha1(f.optJSONArray("hashes")), size = f.optLong("fileLength", 0L)))
            }
            out.add(
                CatalogVersion(
                    id = f.optLong("id", 0L).toString(),
                    name = name,
                    versionNumber = f.optString("displayName").ifBlank { name },
                    channel = cfChannel(f.optInt("releaseType", 1)),
                    gameVersions = games,
                    loaders = loaders,
                    files = files,
                    published = f.optString("fileDate"),
                    source = CatalogSource.CURSEFORGE,
                ),
            )
        }
        return out
    }

    // ------------------------------------------------------------ 编排

    /**
     * Modrinth：拉版本表 → 挑一个。
     *
     * 先按 MC 版本 + 加载器问一次；空了就只按 MC 版本再问一次（跟桌面
     * `_pick_version` 一样——服务端的过滤偶尔比实际严），最后交给
     * [VersionPick.pick] 定夺并给出失败原因。
     */
    fun resolveModrinth(
        slug: String,
        mcVersion: String,
        loader: String,
        fetcher: TextFetcher,
    ): PickResult {
        val json = JSON_HEADERS
        var versions = parseModrinthVersions(fetcher.get(modrinthVersionUrls(slug, mcVersion, loader), json).orEmpty())
        if (versions.isEmpty()) {
            versions = parseModrinthVersions(fetcher.get(modrinthVersionUrls(slug, mcVersion), json).orEmpty())
        }
        if (versions.isEmpty()) {
            versions = parseModrinthVersions(fetcher.get(modrinthVersionUrls(slug), json).orEmpty())
        }
        return VersionPick.pick(versions, mcVersion, loader)
    }

    /**
     * CurseForge：**没 key 就明确告诉用户**，不要闷着失败。
     * key 从外面传进来，这一层不去碰配置，也就不碰 Android。
     */
    fun resolveCurseForge(
        projectId: Long,
        mcVersion: String,
        loader: String,
        keys: CatalogKeys,
        fetcher: TextFetcher,
    ): PickResult {
        if (!keys.hasCurseForge) return PickResult.Failed(PickFailure.NEED_API_KEY, NEED_KEY_MESSAGE)
        val body = fetcher.get(
            curseForgeFileUrls(projectId, mcVersion, loader),
            JSON_HEADERS + ("x-api-key" to keys.curseForgeApiKey),
        )
        return VersionPick.pick(parseCurseForgeFiles(body.orEmpty()), mcVersion, loader)
    }

    // ------------------------------------------------------------ 小工具

    private fun parseModrinthFiles(arr: JSONArray?): List<PackFile> {
        if (arr == null) return emptyList()
        val files = ArrayList<Pair<Boolean, PackFile>>(arr.length())
        for (i in 0 until arr.length()) {
            val f = arr.optJSONObject(i) ?: continue
            val url = f.optString("url")
            if (url.isBlank()) continue
            val hashes = f.optJSONObject("hashes") ?: JSONObject()
            files.add(
                f.optBoolean("primary") to PackFile(
                    path = f.optString("filename").ifBlank { url.substringAfterLast('/') },
                    urls = listOf(url),
                    sha1 = hashes.optString("sha1"),
                    sha512 = hashes.optString("sha512"),
                    size = f.optLong("size", 0L),
                ),
            )
        }
        // 标了 primary 的排前面：VersionPick 直接取第一个
        return files.sortedByDescending { it.first }.map { it.second }
    }

    private fun cfChannel(releaseType: Int): String = when (releaseType) {
        1 -> CatalogVersion.CHANNEL_RELEASE
        2 -> CatalogVersion.CHANNEL_BETA
        3 -> CatalogVersion.CHANNEL_ALPHA
        else -> CatalogVersion.CHANNEL_RELEASE
    }

    /** CF 的 hashes 是 [{value, algo}]，algo 1 = sha1、2 = md5。 */
    private fun cfSha1(arr: JSONArray?): String {
        if (arr == null) return ""
        for (i in 0 until arr.length()) {
            val h = arr.optJSONObject(i) ?: continue
            if (h.optInt("algo") == 1) return h.optString("value")
        }
        return ""
    }

    /** CF 的 modLoaderType：1=Forge 4=Fabric 5=Quilt 6=NeoForge。 */
    private fun cfLoaderType(loader: String): Int? = when (VersionPick.normalizeLoader(loader)) {
        "forge" -> 1
        "fabric" -> 4
        "quilt" -> 5
        "neoforge" -> 6
        else -> null
    }

    private val LOADER_WORDS = setOf("forge", "fabric", "quilt", "neoforge", "liteloader", "rift", "modloader")

    /** CF 把加载器名混进 gameVersions 里；靠这张表把两类分开。 */
    fun looksLikeLoader(token: String): Boolean {
        val s = token.trim().lowercase()
        if (s in LOADER_WORDS) return true
        // MC 版本号一律以数字开头（1.20.1、23w31a）。「Java 17」「Client」这类既不是版本
        // 也不是加载器，一并归到这边滤掉——反正没人拿它当 MC 版本去匹配。
        return s.firstOrNull()?.isDigit() != true
    }

    /**
     * 真正是加载器的那些，返回归一化后的名字；不是就 null。
     *
     * 跟 [looksLikeLoader] 分开两个函数是因为它们问的不是同一件事：
     * 前者问「这一项**不该**当 MC 版本吧」，「Java 17」「Client」也算 true；
     * 后者问「这一项**是**哪个加载器」，那两个都得是 null。早先只有前者，
     * 于是 `gameVersions: ["1.20.1","Forge","Java 17"]` 会解析出
     * `loaders = [forge, java 17]`，按加载器筛版本时多一个永远匹配不上的值。
     */
    fun knownLoader(token: String): String? {
        val s = VersionPick.normalizeLoader(token)
        return if (s in LOADER_WORDS) s else null
    }

    private fun stringsOf(arr: JSONArray?): List<String> {
        if (arr == null) return emptyList()
        return (0 until arr.length()).mapNotNull { arr.optString(it).takeIf { s -> s.isNotBlank() } }
    }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
}
