package com.pymcl.mobile.data

/**
 * 从一堆候选版本里挑出最合适的那一个，对齐桌面 mclauncher/mods.py:531 `_pick_version`。
 *
 * 全是纯函数：收一份已经解析好的候选列表，给一个结果。**网络在 [CatalogFiles]**。
 *
 * 挑不中时不给一句笼统的「没有合适版本」，而是回答**到底卡在哪一步**——
 * 是这个模组压根没出过这个 MC 版本，还是出了但不支持你这个加载器。这两句话
 * 用户能照着做的事完全不同：前者要换 MC 版本，后者要换加载器。
 */

enum class CatalogSource { MODRINTH, CURSEFORGE }

/** 一个候选版本。文件复用 [PackFile]（t-242 就是这个形状：地址 + 校验和 + 大小）。 */
data class CatalogVersion(
    val id: String,
    val name: String = "",
    val versionNumber: String = "",
    /** release / beta / alpha，别的字串一律当 release 之下的未知档。 */
    val channel: String = CHANNEL_RELEASE,
    val gameVersions: List<String> = emptyList(),
    /** 已归一化的加载器名，见 [VersionPick.normalizeLoader]。 */
    val loaders: List<String> = emptyList(),
    val files: List<PackFile> = emptyList(),
    /** ISO 8601 时间串；直接按字典序比就是时间序。 */
    val published: String = "",
    val source: CatalogSource = CatalogSource.MODRINTH,
) {
    companion object {
        const val CHANNEL_RELEASE = "release"
        const val CHANNEL_BETA = "beta"
        const val CHANNEL_ALPHA = "alpha"
    }
}

enum class PickFailure {
    /** 这个项目一个版本都没解析出来（空列表 / 响应坏了）。 */
    NO_VERSIONS,

    /** 有版本，但没有支持这个 MC 版本的。 */
    NO_SUCH_GAME_VERSION,

    /** 有支持这个 MC 版本的，但都不支持这个加载器。 */
    NO_SUCH_LOADER,

    /** 版本挑中了，但它没带任何可下载的文件。 */
    NO_FILE,

    /** CurseForge 要 API key，设置里没填。 */
    NEED_API_KEY,
}

sealed class PickResult {
    data class Picked(
        val version: CatalogVersion,
        val file: PackFile,
        /** 非空时是一句要让用户看见的提醒，比如「这个版本没声明支持你的加载器」。 */
        val warning: String = "",
    ) : PickResult()

    data class Failed(val reason: PickFailure, val message: String) : PickResult()
}

object VersionPick {
    /** 各家对加载器的叫法不一样，归一化到同一套再比。 */
    fun normalizeLoader(raw: String): String {
        val s = raw.trim().lowercase()
        return when {
            s.isEmpty() -> ""
            s.startsWith("fabric") -> "fabric"
            s.startsWith("neoforge") -> "neoforge"
            s.startsWith("forge") -> "forge"
            s.startsWith("quilt") -> "quilt"
            s.startsWith("liteloader") -> "liteloader"
            else -> s
        }
    }

    /** release 最优，其次 beta，再次 alpha；认不出来的排在 beta 与 alpha 之间。 */
    fun channelRank(channel: String): Int = when (channel.trim().lowercase()) {
        CatalogVersion.CHANNEL_RELEASE -> 0
        CatalogVersion.CHANNEL_BETA -> 2
        CatalogVersion.CHANNEL_ALPHA -> 3
        else -> 1
    }

    /**
     * 挑一个。
     *
     * @param mcVersion 目标 MC 版本；留空 = 不按版本过滤
     * @param loader    目标加载器；留空 = 不按加载器过滤
     * @param strictLoader true 时加载器对不上就失败；false 时退而求其次挑一个并带上提醒
     *   （桌面那边就是这个行为：`_pick_version` 找不到匹配加载器会 warning 之后仍返回最新的一个）
     */
    fun pick(
        versions: List<CatalogVersion>,
        mcVersion: String = "",
        loader: String = "",
        strictLoader: Boolean = false,
    ): PickResult {
        val usable = versions.filter { it.files.isNotEmpty() }
        if (versions.isEmpty()) {
            return PickResult.Failed(PickFailure.NO_VERSIONS, "这个项目没有可用的版本")
        }
        if (usable.isEmpty()) {
            return PickResult.Failed(PickFailure.NO_FILE, "这个项目的版本里没有可下载的文件")
        }

        // 第一刀：MC 版本
        val byGame = if (mcVersion.isBlank()) usable else usable.filter { mcVersion in it.gameVersions }
        if (byGame.isEmpty()) {
            val have = usable.flatMap { it.gameVersions }.distinct().sortedDescending().take(6)
            val tail = if (have.isEmpty()) "它没声明支持任何 MC 版本" else "它支持的是 ${have.joinToString("、")}"
            return PickResult.Failed(
                PickFailure.NO_SUCH_GAME_VERSION,
                "没有支持 MC $mcVersion 的版本；$tail",
            )
        }

        // 第二刀：加载器
        val want = normalizeLoader(loader)
        val byLoader = if (want.isEmpty()) byGame else byGame.filter { want in it.loaders }
        if (byLoader.isEmpty()) {
            val have = byGame.flatMap { it.loaders }.distinct().sorted()
            val tail = if (have.isEmpty()) "这些版本没声明加载器" else "这些版本支持的是 ${have.joinToString("、")}"
            if (strictLoader) {
                return PickResult.Failed(
                    PickFailure.NO_SUCH_LOADER,
                    "有支持 MC $mcVersion 的版本，但都不支持 $want；$tail",
                )
            }
            // 宽松档：还是给一个，但把话说明白
            val fallback = best(byGame)
            return PickResult.Picked(
                fallback,
                pickFile(fallback),
                "这个版本没声明支持 $want（$tail），装上去可能不兼容",
            )
        }

        val chosen = best(byLoader)
        return PickResult.Picked(chosen, pickFile(chosen))
    }

    /** release 优于 beta；同档取最新。两条都定死了顺序，所以结果是确定的。 */
    fun best(candidates: List<CatalogVersion>): CatalogVersion =
        candidates.sortedWith(
            compareBy<CatalogVersion> { channelRank(it.channel) }
                .thenByDescending { it.published }
                .thenByDescending { it.versionNumber },
        ).first()

    /**
     * 一个版本可能带主文件、源码包等好几个。这里直接取第一个——解析那一层
     * （[CatalogFiles]）已经把标了 primary 的排到最前面了。
     */
    private fun pickFile(version: CatalogVersion): PackFile = version.files.first()
}
