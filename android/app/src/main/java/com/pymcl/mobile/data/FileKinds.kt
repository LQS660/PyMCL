package com.pymcl.mobile.data

import java.io.File
import java.util.zip.ZipFile

/**
 * 认一认用户给进来的是什么东西，对齐桌面 app/file_kinds.py。
 *
 * 判定尽量看内容、不看后缀：改过名的 .mrpack、CurseForge 导出的 zip、只是换了
 * 扩展名的资源包都要认得出来。一个文件同时像两样东西时（64x64 的 PNG 既可能是
 * 皮肤也可能是壁纸）两种都列出来交给用户挑——猜错比多问一句烦人得多。
 *
 * 这里只做判定，不落盘、不联网、不碰界面。入口收的是本地文件路径；SAF 的
 * content:// 归后续那条活，调用方先把流落成临时文件再进来。
 */
enum class FileKind {
    MODPACK, MOD, RESOURCEPACK, SHADERPACK, DATAPACK, WORLD, SKIN, WALLPAPER
}

/**
 * @param kinds 候选类型，最像的在前；空 = 认不出来
 * @param sure  true 可以直接照办，false 要问用户一句
 */
data class FileGuess(
    val path: String,
    val name: String,
    val kinds: List<FileKind> = emptyList(),
    val sure: Boolean = false,
    val detail: String = "",
)

object FileKinds {
    val IMAGE_SUFFIXES = setOf("png", "jpg", "jpeg", "webp", "bmp", "gif")
    val VIDEO_SUFFIXES = setOf("mp4", "mkv", "webm", "mov", "avi", "m4v")

    /** 皮肤贴图只有这两种尺寸，跟桌面 mclauncher/skin.py 的 VALID_SIZES 同一套。 */
    val SKIN_SIZES = setOf(64 to 64, 64 to 32)

    /** 认包只看前几层：标志文件都在浅处，别为一个判断把几千个模组条目全遍历一遍。 */
    const val SCAN_LIMIT = 4000
    const val MAX_NEST = 3

    private val MOD_MARKERS = setOf(
        "fabric.mod.json",
        "quilt.mod.json",
        "meta-inf/mods.toml",
        "meta-inf/neoforge.mods.toml",
        "mcmod.info",
    )

    fun identify(path: String): FileGuess = identify(File(path))

    fun identify(file: File): FileGuess {
        val base = FileGuess(path = file.path, name = file.name.ifEmpty { file.path })
        if (!file.exists()) return base.copy(detail = "这个路径不存在")

        val suffix = file.extension.lowercase()
        if (suffix in VIDEO_SUFFIXES) {
            return base.copy(kinds = listOf(FileKind.WALLPAPER), sure = true, detail = "视频 · 可以当动态壁纸")
        }
        if (suffix in IMAGE_SUFFIXES) {
            val size = if (suffix == "png") pngSize(file) else null
            if (size != null && size in SKIN_SIZES) {
                // 皮肤贴图也是一张能当壁纸的 PNG，光看文件分不出来，两种都给。
                return base.copy(
                    kinds = listOf(FileKind.SKIN, FileKind.WALLPAPER),
                    detail = "${size.first}x${size.second} 的 PNG，尺寸正好是皮肤贴图",
                )
            }
            return base.copy(kinds = listOf(FileKind.WALLPAPER), sure = true, detail = "图片")
        }

        val names = entryNames(file) ?: return base.copy(detail = "打不开，也认不出是什么")

        // jar 先判：它也是个 zip，交给整合包那套探针只是白读一遍。
        if (suffix == "jar") return base.merge(identifyJar(names))

        val pack = ModpackIndex.probe(file)
        if (pack != null) {
            val mc = pack.mcVersion.ifBlank { "未知版本" }
            return base.copy(
                kinds = listOf(FileKind.MODPACK),
                sure = true,
                detail = "${pack.format.label} · Minecraft $mc",
            )
        }
        return base.merge(identifyArchive(names))
    }

    // ------------------------------------------------------------ 纯判定

    /** jar 里有什么就是什么。加载器安装器要单独挑出来：丢进 mods 只会启动失败。 */
    fun identifyJar(names: List<String>): FileGuess {
        val flat = names.toHashSet()
        if ("install_profile.json" in flat) {
            return FileGuess("", "", detail = "这是加载器安装器，不是模组；装加载器请到「游戏」页")
        }
        if (MOD_MARKERS.any { it in flat }) {
            return FileGuess("", "", kinds = listOf(FileKind.MOD), sure = true, detail = "Minecraft 模组")
        }
        return FileGuess("", "", kinds = listOf(FileKind.MOD), detail = "jar 包，但里面没有模组描述文件")
    }

    /** 压缩包 / 目录：按里面有什么认。 */
    fun identifyArchive(names: List<String>): FileGuess {
        if (hasEntry(names, "level.dat")) {
            return FileGuess("", "", kinds = listOf(FileKind.WORLD), sure = true, detail = "带 level.dat，是一个存档")
        }
        if (hasDir(names, "shaders")) {
            return FileGuess("", "", kinds = listOf(FileKind.SHADERPACK), sure = true, detail = "带 shaders 目录")
        }
        if (hasEntry(names, "pack.mcmeta")) {
            val assets = hasDir(names, "assets")
            val data = hasDir(names, "data")
            if (assets && !data) {
                return FileGuess("", "", kinds = listOf(FileKind.RESOURCEPACK), sure = true, detail = "带 pack.mcmeta 与 assets")
            }
            if (data && !assets) {
                return FileGuess("", "", kinds = listOf(FileKind.DATAPACK), sure = true, detail = "带 pack.mcmeta 与 data")
            }
            return FileGuess(
                "", "",
                kinds = listOf(FileKind.RESOURCEPACK, FileKind.DATAPACK),
                detail = "有 pack.mcmeta，但资源包和数据包的目录都在",
            )
        }
        return FileGuess("", "", detail = "压缩包里没有认得出来的标志文件")
    }

    /**
     * 根目录、或恰好裹了一层目录的位置上有这个文件。
     *
     * 只认前两层：资源包里 assets/minecraft/… 底下也可能躺着同名文件，按「任意
     * 深度」判会把一堆包认错。
     */
    fun hasEntry(names: List<String>, target: String): Boolean =
        names.any { it.substringAfterLast('/') == target && it.count { c -> c == '/' } <= 1 }

    fun hasDir(names: List<String>, target: String): Boolean =
        names.any { name -> name.split('/').take(2).any { it == target } }

    /** 只读 PNG 头拿宽高。不是 PNG、读不动都返回 null。 */
    fun pngSize(file: File): Pair<Int, Int>? {
        val head = runCatching {
            file.inputStream().use { input ->
                val buf = ByteArray(24)
                var read = 0
                while (read < 24) {
                    val n = input.read(buf, read, 24 - read)
                    if (n <= 0) break
                    read += n
                }
                if (read < 24) null else buf
            }
        }.getOrNull() ?: return null
        return pngSize(head)
    }

    fun pngSize(head: ByteArray): Pair<Int, Int>? {
        if (head.size < 24) return null
        val magic = byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte(), 0x0D, 0x0A, 0x1A, 0x0A)
        for (i in magic.indices) if (head[i] != magic[i]) return null
        if (String(head, 12, 4, Charsets.US_ASCII) != "IHDR") return null
        return beInt(head, 16) to beInt(head, 20)
    }

    private fun beInt(b: ByteArray, at: Int): Int =
        ((b[at].toInt() and 0xFF) shl 24) or
            ((b[at + 1].toInt() and 0xFF) shl 16) or
            ((b[at + 2].toInt() and 0xFF) shl 8) or
            (b[at + 3].toInt() and 0xFF)

    /**
     * 包里（或目录里）的相对路径，统一成小写正斜杠。读不了返回 null——**损坏的
     * zip 走的就是这条路，不抛异常**。
     */
    fun entryNames(file: File): List<String>? {
        if (file.isDirectory) return walkNames(file)
        return runCatching {
            ZipFile(file).use { zf ->
                zf.entries().asSequence()
                    .take(SCAN_LIMIT)
                    .map { it.name.replace('\\', '/').lowercase() }
                    .toList()
            }
        }.getOrNull()
    }

    private fun walkNames(root: File): List<String> {
        val out = ArrayList<String>()
        val stack = ArrayDeque<Pair<File, Int>>()
        stack.addLast(root to 0)
        while (stack.isNotEmpty() && out.size < SCAN_LIMIT) {
            val (folder, depth) = stack.removeLast()
            val children = folder.listFiles() ?: continue
            for (child in children.sortedBy { it.name }) {
                val rel = child.path.removePrefix(root.path).trimStart('\\', '/')
                out.add(rel.replace('\\', '/').lowercase())
                if (out.size >= SCAN_LIMIT) break
                if (child.isDirectory && depth + 1 < MAX_NEST) stack.addLast(child to depth + 1)
            }
        }
        return out
    }

    /** 判定函数只填 kinds/sure/detail，路径那两格由入口补上。 */
    private fun FileGuess.merge(verdict: FileGuess): FileGuess =
        copy(kinds = verdict.kinds, sure = verdict.sure, detail = verdict.detail)
}
