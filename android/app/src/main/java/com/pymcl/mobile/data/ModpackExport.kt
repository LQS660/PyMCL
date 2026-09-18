package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 把实例导出成 Modrinth .mrpack，对齐桌面 `mclauncher/export_pack.py` 的 `export_mrpack`：
 * `mods/` 下的 `*.jar` 逐个算 sha1 去问 Modrinth，认得的写进 `files`（带下载地址与 sha512），
 * 认不得的连同 config / resourcepacks / shaderpacks / datapacks 一起进 `overrides/`。
 *
 * 跟 [ModpackInstall] 同一个套路，分两步：
 * - [collect] 扫目录 + 注入进来的 [HashLookup]，不落盘；
 * - [write] 才真的压包：`modrinth.index.json` + `overrides/…`。
 *
 * 所以编排（哪些进 files、哪些进 overrides、索引长什么样、路径怎么算）全能不联网地测，
 * 只有「按 sha1 问 Modrinth」那一下要替身。
 */

/** 索引头部要写的那几样。桌面读的是实例 meta 里的 `modpack` 段，没有就用实例名 / 1.0.0。 */
data class PackMeta(
    val name: String,
    val version: String = "1.0.0",
    val mcVersion: String = "",
    /** Modrinth 的依赖键：forge / neoforge / fabric-loader / quilt-loader；空 = 原版。 */
    val loader: String = "",
    val loaderVersion: String = "",
    val instanceName: String = name,
)

/** `files` 里的一条：Modrinth 认得的模组。 */
data class ExportFile(
    val path: String,
    val sha1: String,
    val sha512: String,
    val url: String,
    val size: Long,
)

data class ExportPlan(
    val meta: PackMeta,
    val files: List<ExportFile> = emptyList(),
    /** (包里相对 overrides/ 的路径, 本地文件)。 */
    val overrides: List<Pair<String, File>> = emptyList(),
)

/** 按 sha1 问 Modrinth 这个文件是哪一版：返回 version 对象的 JSON 文本，没查到给 null。 */
fun interface HashLookup {
    fun lookup(sha1: String): String?
}

object ModpackExport {
    /** 桌面 `OVERRIDE_DIRS`，顺序一致。 */
    val OVERRIDE_DIRS = listOf("config", "resourcepacks", "shaderpacks", "datapacks")

    const val MODRINTH_HASH = "https://api.modrinth.com/v2/version_file/"

    /** 版本 json 认出来的加载器名 → Modrinth 依赖键。认不出的（OptiFine / LiteLoader / 原版）给空。 */
    fun modrinthLoaderKey(loader: String): String = when (loader.trim().lowercase()) {
        "forge" -> "forge"
        "neoforge" -> "neoforge"
        "fabric", "fabric-loader" -> "fabric-loader"
        "quilt", "quilt-loader" -> "quilt-loader"
        else -> ""
    }

    /** MCIM 镜像优先、官方垫底——跟 [CatalogRepo.searchUrls] 一个顺序。 */
    fun hashUrls(sha1: String): List<String> = listOf(
        "${Paths.MCIM}/modrinth/v2/version_file/$sha1",
        "$MODRINTH_HASH$sha1",
    )

    /** 真身：候选地址挨个试，都不通给 null（当作 Modrinth 不认得，进 overrides）。 */
    fun lookupWith(fetcher: TextFetcher): HashLookup = HashLookup { sha1 ->
        fetcher.get(hashUrls(sha1), emptyMap())
    }

    /**
     * 从合成后的版本 json 里抠加载器版本：
     * `net.fabricmc:fabric-loader:0.16.0` → 0.16.0；`net.minecraftforge:forge:1.20.1-47.2.0` → 47.2.0。
     */
    fun loaderVersionOf(json: JSONObject): String {
        val libs = json.optJSONArray("libraries") ?: return ""
        val names = (0 until libs.length()).mapNotNull { libs.optJSONObject(it)?.optString("name") }
            .filter { it.isNotBlank() }
        fun ver(prefix: String): String? =
            names.firstOrNull { it.startsWith(prefix) }?.split(':')?.getOrNull(2)?.takeIf { it.isNotBlank() }
        ver("net.fabricmc:fabric-loader:")?.let { return it }
        ver("org.quiltmc:quilt-loader:")?.let { return it }
        ver("net.neoforged:neoforge:")?.let { return it }
        (ver("net.minecraftforge:forge:") ?: ver("net.minecraftforge:fmlloader:"))?.let { return it.substringAfter('-', it) }
        return ""
    }

    /**
     * 索引头部怎么填：先认 `.instance.json` 里装整合包时留下的 `modpack` 段
     * （name / version / mc_version / loader / loader_version，与桌面同名），
     * 没有就从选中版本推——mc 版本走 [VersionOps.mcVersionOf]，加载器走 [VersionOps.loaderOf]。
     */
    fun metaFor(instDir: File, instanceName: String, version: String, versionJson: JSONObject?): PackMeta {
        val inst = Paths.readJson(File(instDir, ".instance.json"))
        val pack = inst.optJSONObject("modpack") ?: JSONObject()
        val mc = pack.optString("mc_version")
            .ifBlank { if (version.isBlank()) "" else VersionOps.mcVersionOf(instDir, version) }
        val loader = modrinthLoaderKey(pack.optString("loader"))
            .ifBlank { versionJson?.let { modrinthLoaderKey(VersionOps.loaderOf(it)) }.orEmpty() }
        val loaderVersion = pack.optString("loader_version")
            .ifBlank { versionJson?.let { loaderVersionOf(it) }.orEmpty() }
        return PackMeta(
            name = pack.optString("name").ifBlank { instanceName },
            version = pack.optString("version").ifBlank { "1.0.0" },
            mcVersion = mc,
            loader = loader,
            loaderVersion = loaderVersion,
            instanceName = instanceName,
        )
    }

    /** 桌面默认落点：`exports/<实例名>.mrpack`。 */
    fun defaultDest(instanceName: String): File =
        File(Paths.exportsRoot, Paths.sanitizeFileName(instanceName, "modpack") + ".mrpack")

    /**
     * Modrinth version 对象里挑「主文件」：标了 primary 的优先（多个时取最后一个），
     * 一个都没标就取第一个——与桌面 `export_mrpack` 那个循环一模一样。没有下载地址给 null。
     */
    fun primaryFile(versionJson: String): JSONObject? {
        val obj = runCatching { JSONObject(versionJson) }.getOrNull() ?: return null
        val files = obj.optJSONArray("files") ?: return null
        var primary: JSONObject? = null
        for (i in 0 until files.length()) {
            val f = files.optJSONObject(i) ?: continue
            if (f.optBoolean("primary") || primary == null) primary = f
        }
        return primary?.takeIf { it.optString("url").isNotBlank() }
    }

    /**
     * 扫一遍内容根，编排出 files 与 overrides。
     *
     * @param contentRoot 实例内容目录（开了隔离就是版本目录），下面有 mods / config / …
     * @param onNote (在干什么, 已完成, 总数)，与桌面 on_note 同序
     */
    fun collect(
        contentRoot: File,
        meta: PackMeta,
        lookup: HashLookup,
        onNote: (String, Int, Int) -> Unit = { _, _, _ -> },
    ): ExportPlan {
        val files = ArrayList<ExportFile>()
        val overrides = ArrayList<Pair<String, File>>()

        val modsDir = File(contentRoot, "mods")
        if (modsDir.isDirectory) {
            val jars = modsDir.listFiles()
                ?.filter { it.isFile && it.name.lowercase().endsWith(".jar") && !isLink(it) }
                ?.sortedBy { it.name.lowercase() }
                .orEmpty()
            jars.forEachIndexed { i, jar ->
                onNote("解析模组 ${jar.name}", i, jars.size)
                val digest = sha1Of(jar)
                val primary = runCatching { lookup.lookup(digest) }.getOrNull()?.let { primaryFile(it) }
                if (primary != null) {
                    files.add(
                        ExportFile(
                            path = "mods/${jar.name}",
                            sha1 = digest,
                            sha512 = primary.optJSONObject("hashes")?.optString("sha512").orEmpty(),
                            url = primary.optString("url"),
                            size = primary.optLong("size", 0L).takeIf { it > 0 } ?: jar.length(),
                        ),
                    )
                } else {
                    overrides.add("mods/${jar.name}" to jar)
                }
            }
        }

        for (folder in OVERRIDE_DIRS) {
            val src = File(contentRoot, folder)
            if (!src.isDirectory || isLink(src)) continue
            // 不跟着符号链接走出实例目录：包是要发给别人的，不能把链接指向的东西一起打进去
            val entries = src.walkTopDown().onEnter { dir -> !isLink(dir) }
                .filter { it.isFile && !isLink(it) }
                .sortedBy { it.path }
            for (p in entries) {
                val rel = folder + "/" + p.relativeTo(src).invariantSeparatorsPath
                overrides.add(rel to p)
            }
        }
        return ExportPlan(meta, files, overrides)
    }

    /** `modrinth.index.json` 的内容，字段与桌面一致；files 里只留有 sha1 的。 */
    fun buildIndex(plan: ExportPlan): JSONObject {
        val meta = plan.meta
        val deps = JSONObject()
        if (meta.mcVersion.isNotBlank()) deps.put("minecraft", meta.mcVersion)
        if (meta.loader.isNotBlank() && meta.loaderVersion.isNotBlank()) {
            deps.put(meta.loader.lowercase(), meta.loaderVersion)
        }
        val files = JSONArray()
        for (f in plan.files) {
            if (f.sha1.isBlank()) continue
            files.put(
                JSONObject()
                    .put("path", f.path)
                    .put("hashes", JSONObject().put("sha1", f.sha1).put("sha512", f.sha512))
                    .put("downloads", JSONArray().put(f.url))
                    .put("fileSize", f.size),
            )
        }
        return JSONObject()
            .put("formatVersion", 1)
            .put("game", "minecraft")
            .put("versionId", meta.version.ifBlank { "1.0.0" })
            .put("name", meta.name.ifBlank { meta.instanceName })
            .put("summary", "由 PyMCL 从实例 ${meta.instanceName} 导出")
            .put("files", files)
            .put("dependencies", deps)
    }

    /** 真压包。先写 `.tmp` 再改名：中途失败不会留半个 .mrpack 冒充成品。 */
    fun write(plan: ExportPlan, dest: File): File {
        dest.parentFile?.mkdirs()
        val tmp = File(dest.parentFile, dest.name + ".tmp")
        try {
            ZipOutputStream(tmp.outputStream().buffered(64 * 1024)).use { zip ->
                zip.putNextEntry(ZipEntry(ModpackIndex.MRPACK_INDEX))
                zip.write(buildIndex(plan).toString(2).toByteArray(Charsets.UTF_8))
                zip.closeEntry()
                for ((rel, file) in plan.overrides) {
                    zip.putNextEntry(ZipEntry("overrides/$rel"))
                    file.inputStream().use { it.copyTo(zip, 64 * 1024) }
                    zip.closeEntry()
                }
            }
            if (dest.exists()) dest.delete()
            if (!tmp.renameTo(dest)) {
                tmp.copyTo(dest, overwrite = true)
                tmp.delete()
            }
        } catch (e: Exception) {
            tmp.delete()
            throw e
        }
        return dest
    }

    /** 一步到位：collect + write，最后报一句「导出完成」。 */
    fun export(
        contentRoot: File,
        meta: PackMeta,
        dest: File,
        lookup: HashLookup,
        onNote: (String, Int, Int) -> Unit = { _, _, _ -> },
    ): File {
        val plan = collect(contentRoot, meta, lookup, onNote)
        write(plan, dest)
        onNote("导出完成", 1, 1)
        return dest
    }

    private fun isLink(f: File): Boolean = Files.isSymbolicLink(f.toPath())

    private fun sha1Of(file: File): String {
        val md = MessageDigest.getInstance("SHA-1")
        file.inputStream().buffered(64 * 1024).use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
