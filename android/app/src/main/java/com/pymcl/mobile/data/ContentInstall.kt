package com.pymcl.mobile.data

import java.io.File

class ContentError(message: String) : RuntimeException(message)

/** 商店里一条搜索结果真正装下来之后的结果。 */
data class InstalledContent(
    val kind: FileKind,
    val name: String,
    val path: String,
    val warning: String = "",
)

/**
 * 「商店里搜到一个东西」→「它落到磁盘上正确的那个目录」。
 *
 * 目录选择跟隔离档位走：开了「独立 Mod」的版本有自己的 mods / resourcepacks，
 * 吃大锅饭的版本落在实例根；存档还要再看「隔离存档」那一档。这一层只决定
 * 落点与解包方式，找具体文件地址是 [CatalogFiles] + [VersionPick] 的事。
 */
object ContentInstall {
    /** 下载页分区 → 内容类型。与 [CatalogRepo.KINDS] 一一对应。 */
    fun kindOf(tab: String): FileKind? = when (tab) {
        "Mod", "mod" -> FileKind.MOD
        "资源包", "resourcepack" -> FileKind.RESOURCEPACK
        "光影包", "shader", "shaderpack" -> FileKind.SHADERPACK
        "数据包", "datapack" -> FileKind.DATAPACK
        "世界", "world" -> FileKind.WORLD
        "整合包", "modpack" -> FileKind.MODPACK
        else -> null
    }

    /**
     * 挑文件时该带哪个加载器。
     *
     * 世界只是一包存档，谁的加载器都能读，CurseForge 上也没有一个世界会声明 fabric/forge；
     * 照搬当前版本的加载器去挑，[VersionPick] 会一路走到宽松档，装是装上了，却附一句
     * 「没声明支持 fabric，装上去可能不兼容」的假警告。桌面 `worlds.install_world`
     * 从头到尾不看加载器，这里跟它一致。
     */
    fun loaderFor(kind: FileKind, loader: String): String = if (kind == FileKind.WORLD) "" else loader

    /** 每种内容落在游戏目录下的哪个子目录。 */
    fun folderOf(kind: FileKind): String = when (kind) {
        FileKind.MOD -> "mods"
        FileKind.RESOURCEPACK -> "resourcepacks"
        FileKind.SHADERPACK -> "shaderpacks"
        FileKind.DATAPACK -> "datapacks"
        FileKind.WORLD -> "saves"
        FileKind.MODPACK -> "modpacks"
        FileKind.SKIN -> "skins"
        FileKind.WALLPAPER -> "wallpapers"
    }

    /**
     * 落点目录。mods / config 跟「隔离 Mod」走，saves 跟「隔离存档」走，
     * 其余按游戏工作目录——和 `VersionSettings` 的档位定义保持一致。
     */
    fun targetDir(instDir: File, version: String, kind: FileKind): File {
        if (version.isBlank()) return File(instDir, folderOf(kind))
        val settings = VersionSettings.load(instDir, version)
        val root = when (kind) {
            FileKind.MOD -> if (VersionSettings.isolatedMods(settings)) File(instDir, "versions/$version") else instDir
            FileKind.WORLD -> if (VersionSettings.isolatedSaves(settings)) File(instDir, "versions/$version") else instDir
            else -> VersionSettings.gameDir(instDir, version, settings)
        }
        return File(root, folderOf(kind))
    }

    /**
     * 把上游给的文件名落到 [dir] 的直接下一层。
     *
     * 带目录分隔符的一律**拒绝**而不是悄悄截掉：Modrinth 的 `filename` 与
     * CurseForge 的 `fileName` 本来就不含斜杠，出现了就说明响应不对劲或被人做过手脚，
     * 这时候静悄悄改写成另一个名字装下去，比报错更难查。
     */
    fun resolveUnder(dir: File, rawName: String): File {
        val name = rawName.trim()
        if (name.isEmpty() || name == "." || name == "..") throw ContentError("非法文件名: $rawName")
        if (name.contains('/') || name.contains('\\')) throw ContentError("非法文件名: $rawName")
        val root = dir.canonicalFile
        val dest = File(root, name).canonicalFile
        if (dest.parentFile != root) throw ContentError("非法文件名: $rawName")
        return dest
    }

    /** 重名不覆盖，改成 `xxx-2.jar` 另存——用户手里那份可能是改过的。 */
    fun uniqueUnder(dir: File, rawName: String): File {
        var dest = resolveUnder(dir, rawName)
        if (!dest.exists()) return dest
        val stem = dest.nameWithoutExtension
        val ext = dest.extension.takeIf { it.isNotEmpty() }?.let { ".$it" }.orEmpty()
        var n = 2
        while (dest.exists()) {
            dest = resolveUnder(dir, "$stem-$n$ext")
            n++
        }
        return dest
    }

    /**
     * 装一个已经挑好的文件。
     *
     * 世界是个例外：它得解到 `saves/<世界名>/` 里，压缩包本身留着没用；
     * 其余类型原样落一个文件就行。
     */
    fun install(
        instDir: File,
        version: String,
        kind: FileKind,
        file: PackFile,
        downloader: PackDownloader,
        warning: String = "",
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ): InstalledContent {
        val dir = targetDir(instDir, version, kind).also { it.mkdirs() }
        if (kind == FileKind.WORLD) {
            // 暂存放实例的 cache 下而不是全局缓存：这样这条路不碰 Android，也跟着实例一起清
            val staging = File(instDir, "cache/world-${System.nanoTime()}.zip")
            staging.parentFile?.mkdirs()
            try {
                downloader.fetch(file.urls, staging, file.sha1.takeIf { it.isNotBlank() }, onProgress)
                val tops = Saves.unzipInto(staging, dir)
                val name = tops.firstOrNull() ?: file.path.substringBeforeLast('.')
                return InstalledContent(kind, name, File(dir, name).absolutePath, warning)
            } finally {
                staging.delete()
            }
        }
        val dest = uniqueUnder(dir, file.path)
        downloader.fetch(file.urls, dest, file.sha1.takeIf { it.isNotBlank() }, onProgress)
        return InstalledContent(kind, dest.name, dest.absolutePath, warning)
    }

    /**
     * 完整一条：拿搜索结果 → 问上游要具体文件 → 装。
     * 挑不中时把 [VersionPick] 给的那句人话原样抛出来，不要压成「安装失败」。
     */
    fun installFromCatalog(
        instDir: File,
        version: String,
        tab: String,
        slug: String,
        projectId: String,
        source: CatalogSource,
        mcVersion: String,
        loader: String,
        keys: CatalogKeys,
        fetcher: TextFetcher,
        downloader: PackDownloader,
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ): InstalledContent {
        val kind = kindOf(tab) ?: throw ContentError("「$tab」这一类还不支持直接安装")
        val want = loaderFor(kind, loader)
        val picked = when (source) {
            CatalogSource.MODRINTH -> CatalogFiles.resolveModrinth(slug, mcVersion, want, fetcher)
            CatalogSource.CURSEFORGE -> CatalogFiles.resolveCurseForge(
                projectId.toLongOrNull() ?: throw ContentError("CurseForge 项目 id 不是数字: $projectId"),
                mcVersion,
                want,
                keys,
                fetcher,
            )
        }
        return when (picked) {
            is PickResult.Failed -> throw ContentError(picked.message)
            is PickResult.Picked -> install(instDir, version, kind, picked.file, downloader, picked.warning, onProgress)
        }
    }
}
