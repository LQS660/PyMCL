package com.pymcl.mobile.data

import java.io.File

/**
 * 一类可下载内容的全部差异。
 *
 * 桌面 `app/pages/catalog_page.py` 是一份代码兼六类，差异全收在页尾那几个 `*_SPEC`
 * 字典里；这里照同一个思路走：**六类共用一个 Screen，不同的地方只在这张表上**。
 * 复制六份页面的话，以后加一列（比如「导出」）要改六处，总有一处会漏。
 */
data class CatalogSpec(
    val kind: FileKind,
    /** 下载页顶部分区名，与 [CatalogRepo.KINDS] 一一对应。 */
    val tab: String,
    val title: String,
    val searchTitle: String,
    val emptySearch: String,
    val emptyInstalled: String,
    val localLabel: String,
    /** 认得的扩展名；世界是目录，所以它这一栏是压缩包的扩展名。 */
    val extensions: List<String>,
    val linkPlaceholder: String,
    /** 已装内容落在游戏目录下的哪个子目录。 */
    val folder: String,
    /** 只有模组能靠改名停用；别的类型游戏不认 `.disabled`。 */
    val supportsToggle: Boolean = false,
    /** 已装项是目录还是文件。世界是目录。 */
    val installedIsDir: Boolean = false,
    /** 这一类能从哪些源搜。世界只有 CurseForge 有。 */
    val sources: List<String> = listOf("Modrinth", "CurseForge"),
) {
    fun dirIn(instDir: File, version: String): File = ContentInstall.targetDir(instDir, version, kind)
}

object CatalogKinds {
    val MOD = CatalogSpec(
        kind = FileKind.MOD,
        tab = "Mod",
        title = "模组",
        searchTitle = "搜索 Mod",
        emptySearch = "没有找到相关模组",
        emptyInstalled = "还没有安装模组",
        localLabel = "导入 jar",
        extensions = listOf("jar", "zip", "litemod"),
        linkPlaceholder = "https://…/mod.jar",
        folder = "mods",
        supportsToggle = true,
    )

    val MODPACK = CatalogSpec(
        kind = FileKind.MODPACK,
        tab = "整合包",
        title = "整合包",
        searchTitle = "搜索整合包",
        emptySearch = "没有找到相关整合包",
        emptyInstalled = "还没有导入整合包",
        localLabel = "导入文件",
        extensions = listOf("mrpack", "zip"),
        linkPlaceholder = "https://…/pack.mrpack",
        folder = "modpacks",
    )

    val RESOURCEPACK = CatalogSpec(
        kind = FileKind.RESOURCEPACK,
        tab = "资源包",
        title = "资源包",
        searchTitle = "搜索资源包",
        emptySearch = "没有找到相关资源包",
        emptyInstalled = "还没有安装资源包",
        localLabel = "导入 zip",
        extensions = listOf("zip"),
        linkPlaceholder = "https://…/pack.zip",
        folder = "resourcepacks",
    )

    val SHADERPACK = CatalogSpec(
        kind = FileKind.SHADERPACK,
        tab = "光影包",
        title = "光影包",
        searchTitle = "搜索光影包",
        emptySearch = "没有找到相关光影",
        emptyInstalled = "还没有安装光影",
        localLabel = "导入 zip",
        extensions = listOf("zip"),
        linkPlaceholder = "https://…/shader.zip",
        folder = "shaderpacks",
    )

    val DATAPACK = CatalogSpec(
        kind = FileKind.DATAPACK,
        tab = "数据包",
        title = "数据包",
        searchTitle = "搜索数据包",
        emptySearch = "没有找到相关数据包",
        emptyInstalled = "还没有安装数据包",
        localLabel = "导入 zip",
        extensions = listOf("zip"),
        linkPlaceholder = "https://…/datapack.zip",
        folder = "datapacks",
    )

    val WORLD = CatalogSpec(
        kind = FileKind.WORLD,
        tab = "世界",
        title = "世界",
        searchTitle = "搜索世界",
        emptySearch = "没有找到相关世界",
        emptyInstalled = "还没有世界存档",
        localLabel = "导入 zip",
        extensions = listOf("zip"),
        linkPlaceholder = "https://…/world.zip",
        folder = "saves",
        installedIsDir = true,
        // Modrinth 没有「世界」这个 project_type，桌面那边的世界页也只列 CurseForge
        sources = listOf("CurseForge"),
    )

    /** 顺序与下载页分区一致，少一个多一个都会让两处对不上。 */
    val ALL: List<CatalogSpec> = listOf(MOD, MODPACK, RESOURCEPACK, SHADERPACK, DATAPACK, WORLD)

    fun byTab(tab: String): CatalogSpec? = ALL.firstOrNull { it.tab == tab }

    fun byKind(kind: FileKind): CatalogSpec? = ALL.firstOrNull { it.kind == kind }

    /** 下载页那几个分区里，有哪些是本页能管的。 */
    fun manageableTabs(): List<String> = ALL.map { it.tab }
}
