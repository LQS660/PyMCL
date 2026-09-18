package com.pymcl.mobile.data

import com.pymcl.mobile.model.ModEntry

/** 一个已装模组的检查结果。 */
data class ModUpdate(
    val entry: ModEntry,
    val currentVersion: String,
    val latest: CatalogVersion? = null,
    val file: PackFile? = null,
    val reason: String = "",
) {
    /** 上游有一个跟本地不同名的新版。同名就当已是最新，不拿版本号大小去猜。 */
    val hasUpdate: Boolean get() = file != null && file.path != entry.filename
}

/**
 * 「检查更新」：拿已装模组的文件名去上游问一遍有没有新版。
 *
 * 匹配靠文件名——本地 jar 里没有 Modrinth 的 project id，这是唯一的线索。
 * 所以**判定尽量保守**：问不到就说问不到，绝不把「没匹配上」当成「已是最新」，
 * 也绝不拿版本号字符串比大小（`0.10` 和 `0.9` 谁大，各家规则都不一样）。
 */
object ModUpdates {
    /** 一次最多问这么多，免得一屏模组把上游打出限流。 */
    const val MAX_BATCH = 40

    /** `sodium-fabric-0.5.8+mc1.20.1.jar` → 查询用的 slug 猜测。 */
    fun slugGuess(filename: String): String {
        val (name, _) = Mods.splitVersion(filename)
        return name.lowercase()
            .replace(Regex("""[_\s]+"""), "-")
            .replace(Regex("""-(fabric|forge|neoforge|quilt|mc\d[\w.]*)$"""), "")
            .trim('-')
    }

    fun currentVersionOf(filename: String): String = Mods.splitVersion(filename).second

    /**
     * 批量检查。
     *
     * @param mcVersion / [loader] 从当前选中的版本推出来，这样拿到的就是能用的那一版。
     */
    fun check(
        mods: List<ModEntry>,
        mcVersion: String,
        loader: String,
        fetcher: TextFetcher,
        limit: Int = MAX_BATCH,
    ): List<ModUpdate> = mods.take(limit).map { entry ->
        val slug = slugGuess(entry.filename)
        val current = currentVersionOf(entry.filename)
        if (slug.isBlank()) {
            return@map ModUpdate(entry, current, reason = "从文件名认不出这是哪个模组")
        }
        when (val picked = CatalogFiles.resolveModrinth(slug, mcVersion, loader, fetcher)) {
            is PickResult.Failed -> ModUpdate(entry, current, reason = picked.message)
            is PickResult.Picked -> ModUpdate(
                entry = entry,
                currentVersion = current,
                latest = picked.version,
                file = picked.file,
                reason = picked.warning,
            )
        }
    }

    fun updatable(rows: List<ModUpdate>): List<ModUpdate> = rows.filter { it.hasUpdate }

    fun summary(rows: List<ModUpdate>): String {
        if (rows.isEmpty()) return "没有可检查的模组"
        val up = updatable(rows).size
        val failed = rows.count { it.file == null }
        return "查了 ${rows.size} 个 · 可更新 $up · 没查到 $failed"
    }

    fun describe(row: ModUpdate): String = when {
        row.hasUpdate -> "${row.currentVersion.ifBlank { "未知版本" }} → ${row.latest?.versionNumber.orEmpty()}"
        row.file != null -> "已是最新"
        else -> row.reason.ifBlank { "没查到" }
    }
}
