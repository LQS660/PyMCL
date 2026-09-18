package com.pymcl.mobile.data

import java.io.File
import java.io.OutputStream
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** 批量导出里被跳过的那一项。 */
data class ExportFailure(val name: String, val reason: String)

/** 批量导出的结果：成功的名字与失败的原因，对齐桌面 content_export.export_many 的回执。 */
data class BatchExport(val exported: List<String>, val failed: List<ExportFailure>)

/** Streams installed content to a caller-owned SAF destination. */
object ContentExport {
    fun filename(name: String, spec: CatalogSpec): String =
        if (spec.installedIsDir) "$name.zip" else name

    /** 多选导出的建议文件名。一次只写一个包，包里一项一条。 */
    fun bundleName(spec: CatalogSpec, count: Int): String = "pymcl-${spec.folder}-$count.zip"

    fun write(instDir: File, version: String, spec: CatalogSpec, name: String, output: OutputStream) {
        val source = resolve(instDir, version, spec, name)
        if (spec.installedIsDir) {
            val zip = ZipOutputStream(output)
            zipTree(source, treeEntries(source), zip)
            zip.finish()
            zip.flush()
        } else {
            source.inputStream().use { it.copyTo(output) }
            output.flush()
        }
    }

    /**
     * 多选导出：一次写一个 zip，顶层一项一条，目录型（世界）整棵子树带进去。
     *
     * 桌面 export_contents 是往一个文件夹里逐个落地，安卓拿不到那样的文件夹——
     * 保存选择器给的是单个 content:// 目标，所以收敛成一个压缩包。
     * **单项失败不打断其余**这一点跟桌面一致：拦下来的项连原因一起带回去，
     * 让调用方去说人话，而不是让用户对着半个包猜少了什么。
     */
    fun writeMany(
        instDir: File,
        version: String,
        spec: CatalogSpec,
        names: List<String>,
        output: OutputStream,
    ): BatchExport {
        require(spec.kind != FileKind.MODPACK) { "整合包请使用实例导出" }
        val exported = ArrayList<String>()
        val failed = ArrayList<ExportFailure>()
        val zip = ZipOutputStream(output)
        for (name in names) {
            // 校验与列目录都在写第一个字节之前做完：一项过不了只丢这一项，
            // 已经写进流里的条目不会被它带成半截。
            val planned: Pair<File, List<File>>? = try {
                val source = resolve(instDir, version, spec, name)
                source to if (spec.installedIsDir) treeEntries(source) else emptyList()
            } catch (failure: Exception) {
                failed += ExportFailure(name, failure.message ?: failure.toString())
                null
            }
            val (source, entries) = planned ?: continue
            // 这一段的异常是目标流写不动了，整个包都没救，直接往外抛。
            if (spec.installedIsDir) {
                zipTree(source, entries, zip)
            } else {
                zip.putNextEntry(ZipEntry(source.name))
                source.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
            exported += name
        }
        zip.finish()
        zip.flush()
        return BatchExport(exported, failed)
    }

    /** 定位并校验一项，不写任何字节。 */
    private fun resolve(instDir: File, version: String, spec: CatalogSpec, name: String): File {
        require(spec.kind != FileKind.MODPACK) { "整合包请使用实例导出" }
        val source = ContentInstall.resolveUnder(spec.dirIn(instDir, version), name)
        if (spec.installedIsDir) {
            require(source.isDirectory) { "目录不存在: $name" }
        } else {
            require(source.isFile) { "文件不存在: $name" }
            require(!Files.isSymbolicLink(File(spec.dirIn(instDir, version), name).toPath())) { "不能导出符号链接" }
        }
        return source
    }

    /** Do not traverse linked folders or export files outside the selected world. */
    private fun treeEntries(source: File): List<File> {
        val root = source.canonicalFile.toPath()
        val entries = source.walkTopDown().onEnter { dir ->
            check(!Files.isSymbolicLink(dir.toPath())) { "不能导出符号链接: ${dir.name}" }
            true
        }.toList()
        entries.forEach { file ->
            check(!Files.isSymbolicLink(file.toPath()) && file.canonicalFile.toPath().startsWith(root)) {
                "导出路径越界: ${file.name}"
            }
        }
        return entries
    }

    private fun zipTree(source: File, entries: List<File>, zip: ZipOutputStream) {
        for (file in entries) {
            val relative = file.relativeTo(source).invariantSeparatorsPath
            val path = source.name + (if (relative.isBlank()) "" else "/$relative") +
                (if (file.isDirectory) "/" else "")
            zip.putNextEntry(ZipEntry(path))
            if (file.isFile) file.inputStream().use { it.copyTo(zip) }
            zip.closeEntry()
        }
    }
}
