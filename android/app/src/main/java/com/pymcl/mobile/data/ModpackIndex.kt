package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.zip.ZipFile

/**
 * 整合包清单解析，对齐桌面 app/pages/modpack_drop.py 的 _probe_mrpack /
 * _probe_curseforge 与 mclauncher/modpack.py 的安装那一段。
 *
 * 支持两种格式：
 * - **Modrinth .mrpack** —— 包里的 `modrinth.index.json`，文件清单**自带下载
 *   地址与校验和**，解出来就能直接下。
 * - **CurseForge .zip** —— 包里的 `manifest.json`，只有 `projectID/fileID`，
 *   真正的下载地址要另外找 API 换。这里**只把这两个号解出来**，换地址是外面
 *   的事（见 [ModpackInstall.InstallPlan.unresolved]）。
 *
 * 只解析、不下载、不落盘。[parseMrpack] / [parseCurseForge] 直接收 JSON 文本，
 * 所以清单解析这一块能脱离 Android 与网络单测。
 */
enum class PackFormat(val label: String) {
    MRPACK("Modrinth .mrpack"),
    CURSEFORGE("CurseForge .zip"),
}

/** 清单里的一个文件。mrpack 直接给全，CurseForge 的 overrides 走这条、模组走 [CursePackRef]。 */
data class PackFile(
    /** 相对整合包内容根的路径，正斜杠。 */
    val path: String,
    /** 候选下载地址，按顺序试；前面的失败就换下一个。 */
    val urls: List<String>,
    val sha1: String = "",
    val sha512: String = "",
    val size: Long = 0,
    /** mrpack 的 env.client 声明；服务端专属的文件不该下到手机上。 */
    val clientSupported: Boolean = true,
)

/** CurseForge 清单里的一条模组引用：地址还没解出来。 */
data class CursePackRef(
    val projectId: Long,
    val fileId: Long,
    val required: Boolean = true,
)

data class ModpackInfo(
    val format: PackFormat,
    val name: String = "",
    val version: String = "",
    val mcVersion: String = "",
    val loader: String = "",
    val loaderVersion: String = "",
    val files: List<PackFile> = emptyList(),
    val refs: List<CursePackRef> = emptyList(),
    /** overrides 目录名，按顺序找第一个存在的。 */
    val overridesDirs: List<String> = listOf("overrides", "client-overrides"),
) {
    val loaderLabel: String
        get() = when {
            loader.isBlank() -> "原版（未声明加载器）"
            else -> listOf(LOADER_LABELS[loader] ?: loader, loaderVersion).filter { it.isNotBlank() }.joinToString(" ")
        }

    companion object {
        val LOADER_LABELS = mapOf(
            "forge" to "Forge",
            "neoforge" to "NeoForge",
            "fabric-loader" to "Fabric",
            "fabric" to "Fabric",
            "quilt-loader" to "Quilt",
            "quilt" to "Quilt",
            "liteloader" to "LiteLoader",
        )
    }
}

object ModpackIndex {
    const val MRPACK_INDEX = "modrinth.index.json"
    const val CF_MANIFEST = "manifest.json"

    /** 跟桌面 modpack_drop._probe_mrpack 同一个顺序。一个包实际只会声明一种。 */
    private val MRPACK_LOADER_KEYS = listOf("forge", "neoforge", "fabric-loader", "quilt-loader")

    /**
     * 先下后解：把远端整合包拉到 [dest] 再认。
     *
     * t-242 那一版只吃本地包，于是「搜到一个整合包」跟「装它」之间是断开的。
     * 下载走注入进来的 [PackDownloader]，所以这一段照样能不联网地测。
     *
     * @return 包本体与解析结果；下载失败或不是整合包时返回 null（文件会留在 [dest]，
     *   调用方要清就自己清——留着能让用户自己去看那到底是个什么文件）
     */
    fun probeRemote(file: PackFile, dest: File, downloader: PackDownloader): Pair<File, ModpackInfo>? =
        runCatching {
            if (file.urls.isEmpty()) return null
            dest.parentFile?.mkdirs()
            downloader.fetch(file.urls, dest, file.sha1.ifBlank { null }) { _, _ -> }
            val info = probe(dest) ?: return null
            dest to info
        }.getOrNull()

    /** 认一下这个 zip 是不是整合包，不是就返回 null。损坏的包也返回 null，不抛。 */
    fun probe(file: File): ModpackInfo? = runCatching {
        ZipFile(file).use { zf ->
            val names = zf.entries().asSequence().take(FileKinds.SCAN_LIMIT).map { it.name }.toList()
            val mrpack = memberOf(names, MRPACK_INDEX)?.let { parseMrpack(readEntry(zf, it)) }
            if (mrpack != null) return@use mrpack
            memberOf(names, CF_MANIFEST)?.let { parseCurseForge(readEntry(zf, it)) }
        }
    }.getOrNull()

    /**
     * 在包里找标志文件，返回**最浅**的那个成员名；找不到给 null。
     * 只认前 [FileKinds.MAX_NEST] 层：再深就不是这个包的索引了。
     */
    fun memberOf(names: List<String>, marker: String): String? {
        var best: String? = null
        for (raw in names) {
            val n = raw.replace('\\', '/')
            val parts = n.split('/')
            if (!parts.last().equals(marker, ignoreCase = true)) continue
            if (parts.size > FileKinds.MAX_NEST + 1) continue
            val current = best
            if (current == null || parts.size < current.split('/').size) best = n
        }
        return best
    }

    // ------------------------------------------------------------ 纯解析

    fun parseMrpack(json: String): ModpackInfo? {
        val idx = jsonObjectOrNull(json) ?: return null
        val deps = idx.optJSONObject("dependencies") ?: JSONObject()
        // formatVersion / files 至少得有一个，否则这就是别的东西碰巧同名
        if (!idx.has("files") && !idx.has("formatVersion") && !deps.has("minecraft")) return null

        val loader = MRPACK_LOADER_KEYS.firstOrNull { deps.optString(it).isNotBlank() }.orEmpty()
        val files = idx.optJSONArray("files").objects().mapNotNull { f ->
            val path = f.optString("path").trim()
            if (path.isEmpty()) return@mapNotNull null
            val urls = f.optJSONArray("downloads").strings().filter { it.isNotBlank() }
            val hashes = f.optJSONObject("hashes") ?: JSONObject()
            val client = f.optJSONObject("env")?.optString("client").orEmpty()
            PackFile(
                path = path,
                urls = urls,
                sha1 = hashes.optString("sha1"),
                sha512 = hashes.optString("sha512"),
                size = f.optLong("fileSize", f.optLong("size", 0L)),
                // 未声明 env 的按「客户端要」算：mrpack 里绝大多数文件就是没写。
                clientSupported = client != "unsupported" && client != "server",
            )
        }
        return ModpackInfo(
            format = PackFormat.MRPACK,
            name = idx.optString("name"),
            version = idx.optString("versionId"),
            mcVersion = deps.optString("minecraft"),
            loader = loader,
            loaderVersion = if (loader.isBlank()) "" else deps.optString(loader),
            files = files,
        )
    }

    fun parseCurseForge(json: String): ModpackInfo? {
        val mf = jsonObjectOrNull(json) ?: return null
        // 模组自己也可能带 manifest.json，但不会有 minecraft 这一段——
        // 少了这个判断，随便一个 jar 都会被当成整合包。
        val mc = mf.optJSONObject("minecraft") ?: return null

        val loaders = mc.optJSONArray("modLoaders").objects()
        val primary = loaders.firstOrNull { it.optBoolean("primary") } ?: loaders.firstOrNull()
        val id = primary?.optString("id").orEmpty()
        val loader = id.substringBefore('-', id)
        val loaderVersion = if (id.contains('-')) id.substringAfter('-') else ""

        val refs = mf.optJSONArray("files").objects().mapNotNull { f ->
            val pid = f.optLong("projectID", 0L)
            val fid = f.optLong("fileID", 0L)
            if (pid <= 0 || fid <= 0) return@mapNotNull null
            CursePackRef(pid, fid, f.optBoolean("required", true))
        }
        val overrides = mf.optString("overrides").trim().ifBlank { "overrides" }
        return ModpackInfo(
            format = PackFormat.CURSEFORGE,
            name = mf.optString("name"),
            version = mf.optString("version"),
            mcVersion = mc.optString("version"),
            loader = loader,
            loaderVersion = loaderVersion,
            refs = refs,
            overridesDirs = listOf(overrides),
        )
    }

    // ------------------------------------------------------------ 小工具

    private fun readEntry(zf: ZipFile, name: String): String {
        val entry = zf.getEntry(name) ?: return ""
        return zf.getInputStream(entry).use { it.readBytes() }
            .decodeToString()
            .removePrefix("\uFEFF") // 有些导出工具会带 BOM
    }

    private fun jsonObjectOrNull(text: String): JSONObject? =
        runCatching { JSONObject(text.removePrefix("\uFEFF")) }.getOrNull()

    private fun JSONArray?.objects(): List<JSONObject> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { optJSONObject(it) }
    }

    private fun JSONArray?.strings(): List<String> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { optString(it).takeIf { s -> s.isNotEmpty() } }
    }
}
