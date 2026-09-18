package com.pymcl.mobile.data

import com.pymcl.mobile.model.BackupEntry
import com.pymcl.mobile.model.MediaEntry
import com.pymcl.mobile.model.SaveEntry
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

class SaveError(message: String) : RuntimeException(message)

/** 存档 / 备份 / 截图 / 崩溃报告 / 日志，语义对齐桌面 `mclauncher/saves.py`。 */
object Saves {
    const val BACKUP_DIR = "backups"

    private val stampSuffix = Regex("""-(\d{8}-\d{6})(-\d+)?$""")

    val MEDIA_KINDS = mapOf(
        "screenshots" to listOf("png", "jpg", "jpeg"),
        "crash-reports" to listOf("txt"),
        "logs" to listOf("log", "gz", "txt"),
    )

    /** 只允许碰 [folder] 的直接子项，挡掉 `../` 之类的路径穿越。 */
    fun safeChild(folder: File, name: String, what: String = "存档"): File {
        val root = folder.canonicalFile
        val target = File(root, name).canonicalFile
        if (target.parentFile != root) throw SaveError("非法${what}名: $name")
        return target
    }

    fun savesDir(gameDir: File): File = File(gameDir, "saves")

    fun backupsDir(gameDir: File): File = File(gameDir, BACKUP_DIR)

    fun list(gameDir: File): List<SaveEntry> {
        val folder = savesDir(gameDir)
        if (!folder.isDirectory) return emptyList()
        return folder.listFiles()
            ?.filter { it.isDirectory && !it.name.startsWith(".") }
            ?.sortedBy { it.name.lowercase() }
            ?.map { dir ->
                val icon = File(dir, "icon.png")
                SaveEntry(
                    name = dir.name,
                    path = dir.absolutePath,
                    icon = if (icon.isFile) icon.absolutePath else "",
                    bytes = dirSize(dir),
                    mtime = dir.lastModified(),
                )
            }
            ?: emptyList()
    }

    fun delete(gameDir: File, name: String) {
        val target = safeChild(savesDir(gameDir), name)
        if (!target.exists()) throw SaveError("存档不存在: $name")
        target.deleteRecursively()
    }

    fun rename(gameDir: File, name: String, newName: String): SaveEntry {
        val src = safeChild(savesDir(gameDir), name)
        if (!src.isDirectory) throw SaveError("存档不存在: $name")
        val clean = Names.sanitize(newName, name)
        val dest = safeChild(savesDir(gameDir), clean)
        if (dest.exists()) throw SaveError("已有同名存档: $clean")
        if (!src.renameTo(dest)) throw SaveError("重命名失败: $name")
        return SaveEntry(dest.name, dest.absolutePath, bytes = dirSize(dest), mtime = dest.lastModified())
    }

    fun listMedia(gameDir: File, kind: String, limit: Int = 200): List<MediaEntry> {
        val exts = MEDIA_KINDS[kind] ?: throw SaveError("未知类型: $kind")
        val folder = File(gameDir, kind)
        if (!folder.isDirectory) return emptyList()
        return folder.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() in exts }
            ?.sortedByDescending { it.lastModified() }
            ?.take(limit)
            ?.map { MediaEntry(it.name, it.absolutePath, it.length(), it.lastModified()) }
            ?: emptyList()
    }

    fun listBackups(gameDir: File, saveName: String = ""): List<BackupEntry> {
        val folder = backupsDir(gameDir)
        if (!folder.isDirectory) return emptyList()
        return folder.listFiles()
            ?.filter { it.isFile && it.extension.equals("zip", true) }
            ?.map { f ->
                BackupEntry(f.name, f.absolutePath, originOf(f.nameWithoutExtension), f.length(), f.lastModified())
            }
            ?.filter { saveName.isEmpty() || it.save == saveName }
            ?.sortedByDescending { it.mtime }
            ?: emptyList()
    }

    /** `我的世界-20260917-190000-2` → `我的世界`。没有时间戳就原样返回。 */
    internal fun originOf(stem: String): String = stampSuffix.replace(stem, "")

    fun backup(
        gameDir: File,
        name: String,
        now: Long = System.currentTimeMillis(),
        onProgress: (Int, Int) -> Unit = { _, _ -> },
    ): BackupEntry {
        val src = safeChild(savesDir(gameDir), name)
        if (!src.isDirectory) throw SaveError("存档不存在: $name")
        val dir = backupsDir(gameDir).also { it.mkdirs() }
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date(now))
        var dest = File(dir, "${src.name}-$stamp.zip")
        var n = 1
        while (dest.exists()) {
            dest = File(dir, "${src.name}-$stamp-$n.zip")
            n++
        }
        val part = File(dir, dest.name + ".part")
        try {
            zipInto(src, part, onProgress)
            if (!part.renameTo(dest)) throw SaveError("备份落盘失败: ${dest.name}")
        } catch (e: Throwable) {
            part.delete()
            throw e
        }
        return BackupEntry(dest.name, dest.absolutePath, src.name, dest.length(), dest.lastModified())
    }

    fun deleteBackup(gameDir: File, backupName: String) {
        val archive = safeChild(backupsDir(gameDir), backupName, "备份")
        if (!archive.isFile) throw SaveError("备份不存在: $backupName")
        archive.delete()
    }

    /**
     * 还原备份。默认不覆盖同名存档，而是另存为「原名-还原」——
     * 用户点错一下不该把正在玩的档冲掉。
     */
    fun restore(
        gameDir: File,
        backupName: String,
        targetName: String = "",
        overwrite: Boolean = false,
    ): SaveEntry {
        val archive = safeChild(backupsDir(gameDir), backupName, "备份")
        if (!archive.isFile) throw SaveError("备份不存在: $backupName")
        val root = savesDir(gameDir).also { it.mkdirs() }
        val origin = targetName.ifBlank { originOf(archive.nameWithoutExtension) }
        var dest = safeChild(root, origin)
        if (dest.exists()) {
            if (overwrite) {
                dest.deleteRecursively()
            } else {
                var n = 1
                while (dest.exists()) {
                    dest = safeChild(root, "$origin-还原${if (n > 1) n else ""}")
                    n++
                }
            }
        }
        val staging = File(root, ".restore-${System.nanoTime()}")
        staging.deleteRecursively()
        staging.mkdirs()
        try {
            val tops = unzipInto(archive, staging)
            val inner = if (tops.size == 1) File(staging, tops.first()) else staging
            if (!inner.renameTo(dest)) {
                inner.copyRecursively(dest, overwrite = true)
            }
        } finally {
            staging.deleteRecursively()
        }
        return SaveEntry(dest.name, dest.absolutePath, bytes = dirSize(dest), mtime = dest.lastModified())
    }

    fun export(
        gameDir: File,
        name: String,
        dest: File,
        onProgress: (Int, Int) -> Unit = { _, _ -> },
    ): File {
        val src = safeChild(savesDir(gameDir), name)
        if (!src.isDirectory) throw SaveError("存档不存在: $name")
        var out = dest
        if (out.isDirectory) out = File(out, "${src.name}.zip")
        if (!out.name.endsWith(".zip", true)) out = File(out.parentFile, out.name + ".zip")
        out.parentFile?.mkdirs()
        zipInto(src, out, onProgress)
        return out
    }

    /** 把 datapacks/ 里的一个包塞进某个存档。游戏只认存档目录下的 datapacks。 */
    fun installDatapack(gameDir: File, instDir: File, filename: String, saveName: String): File {
        val src = safeChild(File(instDir, "datapacks"), filename, "数据包")
        if (!src.isFile) throw SaveError("数据包不存在: $filename")
        val destDir = File(safeChild(savesDir(gameDir), saveName), "datapacks").also { it.mkdirs() }
        val dest = File(destDir, src.name)
        src.copyTo(dest, overwrite = true)
        return dest
    }

    internal fun zipInto(src: File, dest: File, onProgress: (Int, Int) -> Unit = { _, _ -> }) {
        val files = src.walkTopDown().filter { it.isFile }.toList()
        val total = files.size.coerceAtLeast(1)
        dest.parentFile?.mkdirs()
        ZipOutputStream(dest.outputStream().buffered()).use { zip ->
            files.forEachIndexed { i, f ->
                val rel = f.relativeTo(src.parentFile).invariantPath()
                zip.putNextEntry(ZipEntry(rel))
                f.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
                onProgress(i + 1, total)
            }
        }
    }

    /** 解压到 [destRoot]，返回压缩包里的顶层目录名。逐条校验落点，挡掉 `../`。 */
    internal fun unzipInto(archive: File, destRoot: File): Set<String> {
        val root = destRoot.canonicalFile
        val tops = linkedSetOf<String>()
        ZipFile(archive).use { zip ->
            val entries = zip.entries().toList().filter { !it.isDirectory }
            if (entries.isEmpty()) throw SaveError("备份是空的")
            for (entry in entries) {
                val parts = entry.name.replace('\\', '/').split('/').filter { it.isNotEmpty() && it != "." }
                if (parts.isEmpty() || parts.any { it == ".." }) {
                    throw SaveError("备份包含非法路径: ${entry.name}")
                }
                val target = File(root, parts.joinToString(File.separator)).canonicalFile
                if (target != root && !target.path.startsWith(root.path + File.separator)) {
                    throw SaveError("备份包含非法路径: ${entry.name}")
                }
                tops += parts.first()
                target.parentFile?.mkdirs()
                zip.getInputStream(entry).use { input ->
                    target.outputStream().use { input.copyTo(it) }
                }
            }
        }
        return tops
    }

    /**
     * 目录占用。只统计前 [limit] 个文件——存档动辄上万个 region 块，
     * 在列表里为了显示一行大小走完整棵树，滑动就卡住了。
     */
    fun dirSize(path: File, limit: Int = 80): Long {
        var total = 0L
        var n = 0
        for (f in path.walkTopDown()) {
            if (!f.isFile) continue
            total += f.length()
            n++
            if (n >= limit) break
        }
        return total
    }

    fun formatSize(bytes: Long): String = when {
        bytes >= 1L shl 30 -> String.format(Locale.US, "%.1f GB", bytes / (1L shl 30).toDouble())
        bytes >= 1L shl 20 -> String.format(Locale.US, "%.1f MB", bytes / (1L shl 20).toDouble())
        bytes >= 1024 -> String.format(Locale.US, "%.0f KB", bytes / 1024.0)
        else -> "$bytes B"
    }

    private fun File.invariantPath(): String = path.replace(File.separatorChar, '/')
}
