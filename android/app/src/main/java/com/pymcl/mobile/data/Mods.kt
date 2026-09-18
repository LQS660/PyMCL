package com.pymcl.mobile.data

import com.pymcl.mobile.model.ModEntry
import com.pymcl.mobile.model.ModTarget
import java.io.File

class ModError(message: String) : RuntimeException(message)

/**
 * 已装模组的增删启停，对齐桌面模组管理页。
 *
 * 禁用不是删文件，而是在文件名后加 `.disabled`（HMCL / PCL 同一套约定），
 * 所以 [ModEntry.filename] 一律是去掉这个后缀的原名，UI 和调用方都不用自己判断。
 */
object Mods {
    const val DISABLED_SUFFIX = ".disabled"

    val JAR_EXTS = listOf("jar", "zip", "litemod")

    fun baseName(fileName: String): String =
        if (fileName.endsWith(DISABLED_SUFFIX, true)) {
            fileName.dropLast(DISABLED_SUFFIX.length)
        } else {
            fileName
        }

    fun isEnabled(fileName: String): Boolean = !fileName.endsWith(DISABLED_SUFFIX, true)

    fun looksLikeMod(fileName: String): Boolean =
        baseName(fileName).substringAfterLast('.', "").lowercase() in JAR_EXTS

    /**
     * 模组落在哪儿：没给版本就是大锅饭（实例根的 mods），
     * 给了版本则按它的隔离档位走——只有开了「隔离 Mod」或「完全独立」才有自己的一份。
     */
    fun dirFor(instDir: File, version: String = ""): File =
        if (version.isBlank()) File(instDir, "mods") else VersionSettings.modsDir(instDir, version)

    /** 下拉框里能选的目标：大锅饭 + 所有开了独立模组的版本。 */
    fun targets(instDir: File): List<ModTarget> {
        val out = mutableListOf(ModTarget("大锅饭（所有版本共用）", ""))
        InstanceStore.installedVersionsIn(instDir).forEach { id ->
            if (VersionSettings.isolatedMods(VersionSettings.load(instDir, id))) {
                out += ModTarget("$id（独立）", id)
            }
        }
        return out
    }

    fun list(instDir: File, version: String = ""): List<ModEntry> {
        val dir = dirFor(instDir, version)
        if (!dir.isDirectory) return emptyList()
        return dir.listFiles()
            ?.filter { it.isFile && looksLikeMod(it.name) }
            ?.map {
                ModEntry(
                    filename = baseName(it.name),
                    path = it.absolutePath,
                    bytes = it.length(),
                    enabled = isEnabled(it.name),
                    mtime = it.lastModified(),
                )
            }
            ?.sortedBy { it.filename.lowercase() }
            ?: emptyList()
    }

    /** 同一个模组可能以启用或禁用两种文件名躺在盘上，两个都找一遍。 */
    fun locate(instDir: File, filename: String, version: String = ""): File? {
        val dir = dirFor(instDir, version)
        val base = baseName(filename)
        val enabled = File(dir, base)
        if (enabled.isFile) return enabled
        val disabled = File(dir, base + DISABLED_SUFFIX)
        return if (disabled.isFile) disabled else null
    }

    fun setEnabled(instDir: File, filename: String, enabled: Boolean, version: String = ""): File {
        val current = locate(instDir, filename, version) ?: throw ModError("模组不存在: $filename")
        val dir = current.parentFile
        val base = baseName(current.name)
        val target = File(dir, if (enabled) base else base + DISABLED_SUFFIX)
        if (current.path == target.path) return current
        if (target.exists()) throw ModError("目标文件已存在: ${target.name}")
        if (!current.renameTo(target)) throw ModError("切换失败: $filename")
        return target
    }

    fun delete(instDir: File, filename: String, version: String = "") {
        val current = locate(instDir, filename, version) ?: throw ModError("模组不存在: $filename")
        if (!current.delete()) throw ModError("删除失败: $filename")
    }

    /** 导入一个本地 jar。重名不覆盖，而是 `xxx-2.jar` 另存。 */
    fun install(instDir: File, src: File, version: String = ""): ModEntry {
        if (!src.isFile) throw ModError("文件不存在: ${src.name}")
        if (!looksLikeMod(src.name)) throw ModError("不是模组文件: ${src.name}")
        val dir = dirFor(instDir, version).also { it.mkdirs() }
        var dest = File(dir, src.name)
        var n = 2
        while (dest.exists()) {
            val stem = src.nameWithoutExtension
            dest = File(dir, "$stem-$n.${src.extension}")
            n++
        }
        src.copyTo(dest)
        return ModEntry(dest.name, dest.absolutePath, dest.length(), true, dest.lastModified())
    }

    fun export(instDir: File, filename: String, destDir: File, version: String = ""): File {
        val src = locate(instDir, filename, version) ?: throw ModError("模组不存在: $filename")
        destDir.mkdirs()
        val dest = File(destDir, baseName(src.name))
        src.copyTo(dest, overwrite = true)
        return dest
    }

    fun summary(rows: List<ModEntry>): String {
        val on = rows.count { it.enabled }
        val size = rows.sumOf { it.bytes }
        return "启用 $on · 禁用 ${rows.size - on} · ${Saves.formatSize(size)}"
    }

    fun filter(rows: List<ModEntry>, query: String): List<ModEntry> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return rows
        return rows.filter { it.filename.lowercase().contains(q) }
    }

    /**
     * 从文件名猜一个用来比对更新的「模组 id + 版本」。
     * `sodium-fabric-0.5.8+mc1.20.1.jar` → `sodium-fabric` / `0.5.8+mc1.20.1`。
     */
    fun splitVersion(filename: String): Pair<String, String> {
        val stem = baseName(filename).substringBeforeLast('.')
        val cut = Regex("""-(\d[\w.+]*)$""").find(stem) ?: return stem to ""
        return stem.substring(0, cut.range.first) to cut.groupValues[1]
    }
}
