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
}
