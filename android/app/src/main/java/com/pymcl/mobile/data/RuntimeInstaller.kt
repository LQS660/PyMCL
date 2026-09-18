package com.pymcl.mobile.data

import android.content.Context
import android.system.Os
import com.tungsten.fclauncher.FCLauncher
import com.tungsten.fclauncher.utils.Architecture
import com.tungsten.fclauncher.utils.FCLPath
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.xz.XZCompressorInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.Locale
import java.util.zip.ZipInputStream

object RuntimeInstaller {
    fun ensure(context: Context, jreDirName: String, onLog: (String) -> Unit) {
        FCLPath.loadPaths(context.applicationContext)
        onLog("检查运行时 $jreDirName")
        installDir(context, File(FCLPath.LWJGL_DIR, "3.3.3"), "app_runtime/lwjgl/3.3.3", onLog)
        installDir(context, File(FCLPath.LWJGL_DIR, "3.4.1"), "app_runtime/lwjgl/3.4.1", onLog)
        installDir(context, File(FCLPath.CACIOCAVALLO_17_DIR), "app_runtime/caciocavallo17", onLog)
        if (jreDirName == "jre8") {
            installDir(context, File(FCLPath.CACIOCAVALLO_8_DIR), "app_runtime/caciocavallo", onLog)
        }
        installJna(context, onLog)
        val javaHome = when (jreDirName) {
            "jre8" -> FCLPath.JAVA_8_PATH
            "jre21" -> FCLPath.JAVA_21_PATH
            "jre25" -> FCLPath.JAVA_25_PATH
            else -> FCLPath.JAVA_17_PATH
        }
        installJava(context, javaHome, "app_runtime/java/$jreDirName", onLog)
        copyPluginJars(context, onLog)
        writeResolv()
        onLog("运行时就绪 $javaHome")
    }

    fun ready(context: Context, jreDirName: String): Boolean {
        FCLPath.loadPaths(context.applicationContext)
        val javaHome = when (jreDirName) {
            "jre8" -> FCLPath.JAVA_8_PATH
            "jre21" -> FCLPath.JAVA_21_PATH
            "jre25" -> FCLPath.JAVA_25_PATH
            else -> FCLPath.JAVA_17_PATH
        }
        return isLatest(context, File(javaHome), "app_runtime/java/$jreDirName") &&
            isLatest(context, File(FCLPath.LWJGL_DIR + "/3.3.3"), "app_runtime/lwjgl/3.3.3") &&
            File(FCLPath.MIO_LAUNCH_WRAPPER).isFile
    }

    private fun installDir(context: Context, dest: File, assetDir: String, onLog: (String) -> Unit) {
        if (isLatest(context, dest, assetDir)) return
        onLog("解压 $assetDir")
        dest.deleteRecursively()
        dest.mkdirs()
        copyAssets(context, assetDir, dest)
        copyVersion(context, assetDir, dest)
    }

    private fun installJna(context: Context, onLog: (String) -> Unit) {
        val dest = File(FCLPath.JNA_PATH)
        if (isLatest(context, dest, "app_runtime/jna") && dest.walkTopDown().any { it.name == "libjnidispatch.so" }) {
            return
        }
        onLog("解压 JNA")
        dest.deleteRecursively()
        dest.mkdirs()
        copyAssets(context, "app_runtime/jna", dest)
        dest.listFiles()?.filter { it.name.endsWith(".zip") }?.forEach { zip ->
            unzip(zip, File(FCLPath.RUNTIME_DIR))
            zip.delete()
        }
        copyVersion(context, "app_runtime/jna", dest)
    }

    private fun installJava(context: Context, destPath: String, assetDir: String, onLog: (String) -> Unit) {
        val dest = File(destPath)
        if (isLatest(context, dest, assetDir) && File(dest, "bin/java").isFile) return
        onLog("解压 Java $assetDir（第一次较慢）")
        dest.deleteRecursively()
        dest.mkdirs()
        val arch = Architecture.archAsString(Architecture.getDeviceArchitecture())
        uncompressTarXz(context, "$assetDir/universal.tar.xz", dest)
        uncompressTarXz(context, "$assetDir/bin-$arch.tar.xz", dest)
        copyVersion(context, assetDir, dest)
        patchJava(context, dest)
        onLog("Java 已写入 $destPath")
    }

    fun isLatest(context: Context, dest: File, assetDir: String): Boolean {
        val versionFile = File(dest, "version")
        val want = runCatching {
            context.assets.open("$assetDir/version").bufferedReader().use { it.readText().trim() }
        }.getOrNull() ?: return dest.exists()
        if (!versionFile.isFile) return false
        return versionFile.readText().trim() == want
    }

    private fun copyVersion(context: Context, assetDir: String, dest: File) {
        runCatching {
            context.assets.open("$assetDir/version").use { input ->
                File(dest, "version").outputStream().use { input.copyTo(it) }
            }
        }
    }

    private fun copyPluginJars(context: Context, onLog: (String) -> Unit) {
        File(FCLPath.PLUGIN_DIR).mkdirs()
        listOf(
            "game/MioLibPatcher.jar" to File(FCLPath.LIB_PATCHER_PATH),
            "game/MioLaunchWrapper.jar" to File(FCLPath.MIO_LAUNCH_WRAPPER),
        ).forEach { (asset, dest) ->
            if (dest.isFile && dest.length() > 0) return@forEach
            dest.parentFile?.mkdirs()
            runCatching {
                context.assets.open(asset).use { input -> dest.outputStream().use { input.copyTo(it) } }
                onLog("写入 ${dest.name}")
            }.onFailure { onLog("缺 $asset: ${it.message}") }
        }
    }

    private fun writeResolv() {
        val file = File(FCLPath.JAVA_PATH, "resolv.conf")
        if (file.isFile) return
        file.parentFile?.mkdirs()
        val china = Locale.getDefault() == Locale.CHINA || Locale.getDefault().country.equals("CN", true)
        file.writeText(
            if (china) "nameserver 8.8.8.8\nnameserver 8.8.4.4\n"
            else "nameserver 1.1.1.1\nnameserver 1.0.0.1\n",
        )
    }

    private fun copyAssets(context: Context, src: String, dest: File) {
        val names = context.assets.list(src) ?: emptyArray()
        if (names.isNotEmpty()) {
            dest.mkdirs()
            names.forEach { name ->
                copyAssets(context, "$src/$name", File(dest, name))
            }
            return
        }
        dest.parentFile?.mkdirs()
        context.assets.open(src).use { input ->
            FileOutputStream(dest).use { output -> input.copyTo(output, 64 * 1024) }
        }
    }

    private fun uncompressTarXz(context: Context, asset: String, dest: File) {
        dest.mkdirs()
        context.assets.open(asset).use { raw ->
            TarArchiveInputStream(XZCompressorInputStream(raw)).use { tar ->
                while (true) {
                    val entry = tar.nextTarEntry ?: break
                    val outFile = File(dest, entry.name)
                    if (!outFile.canonicalPath.startsWith(dest.canonicalPath)) {
                        throw IOException("zip-slip ${entry.name}")
                    }
                    if (entry.isSymbolicLink) {
                        outFile.parentFile?.mkdirs()
                        runCatching {
                            Os.symlink(
                                entry.linkName.replace("..", dest.absolutePath),
                                outFile.absolutePath,
                            )
                        }
                    } else if (entry.isDirectory) {
                        outFile.mkdirs()
                        outFile.setExecutable(true, false)
                    } else {
                        outFile.parentFile?.mkdirs()
                        FileOutputStream(outFile).use { os -> tar.copyTo(os, 64 * 1024) }
                        if (entry.name.contains("/bin/") || entry.name.endsWith(".so")) {
                            outFile.setExecutable(true, false)
                        }
                    }
                }
            }
        }
    }

    private fun unzip(zip: File, dest: File) {
        dest.mkdirs()
        ZipInputStream(zip.inputStream().buffered()).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                val outFile = File(dest, entry.name)
                if (!outFile.canonicalPath.startsWith(dest.canonicalPath)) continue
                if (entry.isDirectory) {
                    outFile.mkdirs()
                } else {
                    outFile.parentFile?.mkdirs()
                    FileOutputStream(outFile).use { zis.copyTo(it, 64 * 1024) }
                }
                zis.closeEntry()
            }
        }
    }

    private fun patchJava(context: Context, dest: File) {
        unpack200(context.applicationInfo.nativeLibraryDir, dest)
        val javaPath = dest.absolutePath
        val libFolder = runCatching { FCLauncher.getJavaLibDir(javaPath) }.getOrDefault("/lib")
        val folder = if (FCLauncher.isJDK8(javaPath)) "/jre$libFolder" else libFolder
        val ftIn = File(dest, "$folder/libfreetype.so.6")
        val ftOut = File(dest, "$folder/libfreetype.so")
        if (ftIn.exists() && (!ftOut.exists() || ftIn.length() != ftOut.length())) {
            ftIn.renameTo(ftOut)
        }
        val ftJre = File(dest, "${FCLauncher.getJavaLibDir(javaPath)}/libfreetype.so")
        if (FCLauncher.isJDK8(javaPath) && ftJre.exists()) {
            ftJre.renameTo(ftOut)
        }
        val awt = File(dest, "$folder/libawt_xawt.so")
        awt.delete()
        val src = File(context.applicationInfo.nativeLibraryDir, "libawt_xawt.so")
        if (src.isFile) src.copyTo(awt, overwrite = true)
    }

    private fun unpack200(nativeDir: String, javaHome: File) {
        val bin = File(nativeDir, "libunpack200.so")
        if (!bin.isFile) return
        javaHome.walkTopDown().filter { it.isFile && it.name.endsWith(".pack") }.forEach { pack ->
            val jar = File(pack.path.removeSuffix(".pack"))
            runCatching {
                ProcessBuilder("./libunpack200.so", "-r", pack.absolutePath, jar.absolutePath)
                    .directory(File(nativeDir))
                    .start()
                    .waitFor()
            }
        }
    }

    /**
     * 不带 Context 的重载：`GameRuntime.installedMajor()` 那种地方手上没有 Context。
     *
     * 两条路都算数——随包解出来的（FCLPath 下）和 Java 页从发行版下的（[Paths.javaRoot] 下）
     * 只要有一个装好了，这个大版本就是能用的。FCLPath 在 Application 起来之前访问会抛，
     * 所以包一层 runCatching：答不上来就当没装，不要把调用方一起带崩。
     */
    fun ready(major: Int): Boolean {
        val jre = JavaRuntime.jreDirName(major)
        val bundled = runCatching {
            ready(com.pymcl.mobile.PyMclApp.instance, jre)
        }.getOrDefault(false)
        return bundled || downloaded(major)
    }

    // ------------------------------------------------- 发行版下载（Java 页用）
    /**
     * 上面那条路解的是**随包带的** JRE 17/21，够启动游戏就行。
     * 桌面 Java 页还能从 Adoptium / Zulu / Microsoft 下别的大版本（8、11），
     * 那批装在 [Paths.javaRoot] 下面，跟 FCL 那套各走各的，互不覆盖。
     */
    fun downloadedDir(major: Int): File = File(Paths.javaRoot, JavaRuntime.jreDirName(major))

    fun downloaded(major: Int): Boolean = File(downloadedDir(major), "bin/java").isFile

    fun ensureDownloaded(
        major: Int,
        vendor: String,
        abi: String,
        onLog: (String) -> Unit = {},
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ): File {
        val dest = downloadedDir(major)
        if (downloaded(major)) {
            onLog("Java $major 已就绪 ${dest.name}")
            return dest
        }
        val url = JavaRuntime.downloadUrl(vendor, major, abi)
        onLog("下载 Java $major（${JavaRuntime.vendorLabel(vendor)}）")
        val archive = File(Paths.cache, "jre-$major-$vendor.bin")
        Http.download(url, archive, null, onProgress)

        onLog("解包 Java $major")
        dest.deleteRecursively()
        dest.mkdirs()
        try {
            extractArchive(archive, dest)
        } finally {
            archive.delete()
        }
        // 发行版的包都多套一层 jdk-21.0.x+y-jre/，提上来 bin/java 才在预期位置
        flattenSingleRoot(dest)
        markExecutable(dest)
        if (!File(dest, "bin/java").isFile) {
            throw IOException("解包后没找到 bin/java，这个包的结构不认识：$url")
        }
        onLog("Java $major 就绪 ${dest.absolutePath}")
        return dest
    }

    fun removeDownloaded(major: Int): Boolean = downloadedDir(major).deleteRecursively()

    /** 看头两个字节自己判 gzip / zip，别让调用方去猜发行版给的是哪种包。 */
    internal fun extractArchive(archive: File, dest: File) {
        archive.inputStream().buffered(64 * 1024).use { raw ->
            raw.mark(4)
            val b0 = raw.read()
            val b1 = raw.read()
            raw.reset()
            when {
                b0 == 0x1F && b1 == 0x8B ->
                    java.util.zip.GZIPInputStream(raw, 64 * 1024).use { untarInto(it, dest) }
                b0 == 'P'.code && b1 == 'K'.code -> unzipInto(raw, dest)
                else -> untarInto(raw, dest)
            }
        }
    }

    /**
     * 最小 tar 读取器：只认 ustar 的普通文件、目录、GNU 长名。
     *
     * 这里不用 commons-compress 的 TarArchiveInputStream 不是为了省依赖
     * （上面那条路已经在用它了），而是因为发行版给的是 tar.**gz**，
     * 而 commons 那条路上我们只引了 xz 解压器。
     */
    internal fun untarInto(input: java.io.InputStream, dest: File) {
        val header = ByteArray(512)
        var pendingLongName: String? = null
        while (true) {
            if (!readFully(input, header)) break
            if (header.all { it == 0.toByte() }) break
            val rawName = cString(header, 0, 100)
            val size = octal(header, 124, 12)
            val mode = octal(header, 100, 8)
            val type = header[156].toInt().toChar()
            val prefix = cString(header, 345, 155)
            val name = pendingLongName ?: if (prefix.isEmpty()) rawName else "$prefix/$rawName"
            pendingLongName = null

            if (type == 'L') {
                val bytes = ByteArray(size.toInt())
                readFully(input, bytes)
                skipPadding(input, size)
                pendingLongName = String(bytes, Charsets.UTF_8).trimEnd('\u0000')
                continue
            }

            val outFile = File(dest, name)
            if (!outFile.canonicalPath.startsWith(dest.canonicalPath + File.separator) &&
                outFile.canonicalPath != dest.canonicalPath
            ) {
                throw IOException("zip-slip $name")
            }
            when (type) {
                '5' -> outFile.mkdirs()
                '0', '\u0000' -> {
                    outFile.parentFile?.mkdirs()
                    FileOutputStream(outFile).buffered(64 * 1024).use { copyExactly(input, it, size) }
                    if (mode and 0b001_001_001L != 0L) outFile.setExecutable(true, false)
                }
                else -> skipExactly(input, size)
            }
            skipPadding(input, size)
        }
    }

    internal fun unzipInto(input: java.io.InputStream, dest: File) {
        ZipInputStream(input).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                val outFile = File(dest, entry.name)
                if (!outFile.canonicalPath.startsWith(dest.canonicalPath)) {
                    zis.closeEntry()
                    continue
                }
                if (entry.isDirectory) {
                    outFile.mkdirs()
                } else {
                    outFile.parentFile?.mkdirs()
                    FileOutputStream(outFile).buffered(64 * 1024).use { zis.copyTo(it, 64 * 1024) }
                }
                zis.closeEntry()
            }
        }
    }

    /** 包里只有一个顶层目录时把它拆掉，`bin/java` 才落在我们期望的位置上。 */
    internal fun flattenSingleRoot(dest: File) {
        val children = dest.listFiles() ?: return
        if (children.size != 1 || !children[0].isDirectory) return
        if (File(dest, "bin").isDirectory) return
        val inner = children[0]
        inner.listFiles()?.forEach { it.renameTo(File(dest, it.name)) }
        inner.delete()
    }

    /** tar 里 mode 位丢了的情况下兜一手：bin/ 和 .so 必须可执行，否则起不来。 */
    internal fun markExecutable(dest: File) {
        File(dest, "bin").listFiles()?.forEach { it.setExecutable(true, false) }
        dest.walkTopDown().forEach {
            if (it.isFile && it.name.endsWith(".so")) it.setExecutable(true, false)
        }
    }

    internal fun octal(buf: ByteArray, at: Int, len: Int): Long {
        var value = 0L
        for (i in at until at + len) {
            val c = buf[i].toInt()
            if (c == 0 || c == ' '.code) {
                if (value != 0L) break else continue
            }
            if (c < '0'.code || c > '7'.code) break
            value = value * 8 + (c - '0'.code)
        }
        return value
    }

    internal fun cString(buf: ByteArray, at: Int, len: Int): String {
        var end = at
        while (end < at + len && buf[end] != 0.toByte()) end++
        return String(buf, at, end - at, Charsets.UTF_8)
    }

    private fun readFully(input: java.io.InputStream, buf: ByteArray): Boolean {
        var done = 0
        while (done < buf.size) {
            val n = input.read(buf, done, buf.size - done)
            if (n < 0) return false
            done += n
        }
        return true
    }

    private fun copyExactly(input: java.io.InputStream, out: java.io.OutputStream, size: Long) {
        val buf = ByteArray(64 * 1024)
        var left = size
        while (left > 0) {
            val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
            if (n <= 0) break
            out.write(buf, 0, n)
            left -= n
        }
    }

    private fun skipExactly(input: java.io.InputStream, size: Long) {
        var left = size
        val buf = ByteArray(64 * 1024)
        while (left > 0) {
            val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
            if (n <= 0) break
            left -= n
        }
    }

    /** tar 的记录按 512 对齐，读完正文要把补零那截吃掉。 */
    private fun skipPadding(input: java.io.InputStream, size: Long) {
        val rem = (size % 512).toInt()
        if (rem != 0) skipExactly(input, (512 - rem).toLong())
    }
}
