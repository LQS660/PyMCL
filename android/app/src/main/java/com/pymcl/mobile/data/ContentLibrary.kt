package com.pymcl.mobile.data

import java.io.File

/** 已装的一项内容。目录型（世界）与文件型（模组、资源包…）共用这一种。 */
data class ContentEntry(
    val name: String,
    val path: String,
    val bytes: Long = 0,
    val isDir: Boolean = false,
    val enabled: Boolean = true,
    val mtime: Long = 0,
)

/**
 * 「已装了哪些」这一半，六类共用一套。
 *
 * 装进去那一半在 [ContentInstall]，这里只管列、删、从本地导入。模组的启停仍然
 * 走 [Mods]——那套 `.disabled` 改名的约定只有模组适用，别的类型游戏根本不认。
 */
object ContentLibrary {
    fun list(instDir: File, version: String, spec: CatalogSpec): List<ContentEntry> {
        if (spec.kind == FileKind.MOD) {
            return Mods.list(instDir, version).map {
                ContentEntry(it.filename, it.path, it.bytes, false, it.enabled, it.mtime)
            }
        }
        val dir = spec.dirIn(instDir, version)
        if (!dir.isDirectory) return emptyList()
        return dir.listFiles()
            ?.filter { matches(it, spec) }
            ?.sortedBy { it.name.lowercase() }
            ?.map {
                ContentEntry(
                    name = it.name,
                    path = it.absolutePath,
                    bytes = if (it.isDirectory) Saves.dirSize(it) else it.length(),
                    isDir = it.isDirectory,
                    mtime = it.lastModified(),
                )
            }
            ?: emptyList()
    }

    internal fun matches(file: File, spec: CatalogSpec): Boolean {
        if (spec.installedIsDir) return file.isDirectory && !file.name.startsWith(".")
        return file.isFile && file.extension.lowercase() in spec.extensions
    }

    fun delete(instDir: File, version: String, spec: CatalogSpec, name: String) {
        if (spec.kind == FileKind.MOD) {
            Mods.delete(instDir, name, version)
            return
        }
        val target = ContentInstall.resolveUnder(spec.dirIn(instDir, version), name)
        if (!target.exists()) throw ContentError("${spec.title}不存在: $name")
        val ok = if (target.isDirectory) target.deleteRecursively() else target.delete()
        if (!ok) throw ContentError("删除失败: $name")
    }

    /**
     * 从本地导入一份。世界给的是压缩包，得解到 `saves/` 下面去，
     * 跟从商店装下来那条路走同一个解包实现。
     */
    fun importLocal(instDir: File, version: String, spec: CatalogSpec, src: File): ContentEntry {
        if (!src.isFile) throw ContentError("文件不存在: ${src.name}")
        if (src.extension.lowercase() !in spec.extensions) {
            throw ContentError("${spec.title}只认 ${spec.extensions.joinToString("/")} 文件")
        }
        if (spec.kind == FileKind.MOD) {
            val row = Mods.install(instDir, src, version)
            return ContentEntry(row.filename, row.path, row.bytes, false, row.enabled, row.mtime)
        }
        val dir = spec.dirIn(instDir, version).also { it.mkdirs() }
        if (spec.installedIsDir) {
            val tops = Saves.unzipInto(src, dir)
            val name = tops.firstOrNull() ?: src.nameWithoutExtension
            val out = File(dir, name)
            return ContentEntry(name, out.absolutePath, Saves.dirSize(out), true, mtime = out.lastModified())
        }
        val dest = ContentInstall.uniqueUnder(dir, src.name)
        src.copyTo(dest)
        return ContentEntry(dest.name, dest.absolutePath, dest.length(), false, mtime = dest.lastModified())
    }

    fun filter(rows: List<ContentEntry>, query: String): List<ContentEntry> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return rows
        return rows.filter { it.name.lowercase().contains(q) }
    }

    fun summary(rows: List<ContentEntry>, spec: CatalogSpec): String {
        if (rows.isEmpty()) return spec.emptyInstalled
        val size = Saves.formatSize(rows.sumOf { it.bytes })
        if (!spec.supportsToggle) return "${rows.size} 个 · $size"
        val on = rows.count { it.enabled }
        return "启用 $on · 禁用 ${rows.size - on} · $size"
    }
}
