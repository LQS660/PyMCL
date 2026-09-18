package com.pymcl.mobile.data

import java.io.File
import java.io.InputStream
import java.nio.file.Files
import java.util.Locale

/** Provider documents are staged privately and removed on both success and failure. */
object DocumentImport {
    fun <T> consume(
        cacheDir: File,
        displayName: String,
        extensions: Collection<String>,
        open: () -> InputStream?,
        consumeFile: (File) -> T,
    ): T {
        require(displayName.isNotBlank() && displayName != "." && displayName != ".." &&
            displayName.none { it == '/' || it == '\\' || it == ':' || it.code < 32 }) {
            "非法文件名: $displayName"
        }
        require(displayName.substringAfterLast('.', "").lowercase(Locale.ROOT) in extensions) {
            "只认 ${extensions.joinToString("/")} 文件"
        }
        val root = File(cacheDir, "content-import").canonicalFile
        check(root.isDirectory || root.mkdirs()) { "无法创建导入缓存" }
        val staging = Files.createTempDirectory(root.toPath(), "document-").toFile().canonicalFile
        check(staging.parentFile == root) { "导入缓存路径越界" }
        try {
            val file = File(staging, displayName)
            val input = open() ?: error("无法读取所选文件")
            input.use { source -> file.outputStream().buffered().use { source.copyTo(it) } }
            return consumeFile(file)
        } finally {
            check(staging.canonicalFile.parentFile == root) { "导入缓存路径已改变" }
            check(staging.deleteRecursively()) { "无法清理导入缓存" }
        }
    }
}
