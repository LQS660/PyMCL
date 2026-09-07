package com.pymcl.mobile.data

object Names {
    private val illegal = Regex("""[\\/:*?"<>|\x00-\x1f]""")
    private val reserved = setOf(
        "CON", "PRN", "AUX", "NUL",
        *(1..9).map { "COM$it" }.toTypedArray(),
        *(1..9).map { "LPT$it" }.toTypedArray(),
    )

    fun sanitize(raw: String, fallback: String = "游戏"): String {
        var s = illegal.replace(raw.trim(), "-")
        s = Regex("""\s+""").replace(s, " ").trim(' ', '.')
        if (s.isEmpty()) s = fallback
        if (s.uppercase() in reserved) s = "$s-游戏"
        if (s.length > 48) s = s.take(48).trimEnd(' ', '.')
        if (s.isEmpty()) s = fallback
        return s
    }

    fun rewriteBmcl(url: String): String? {
        val map = listOf(
            "https://piston-meta.mojang.com/" to "${Paths.BMCL}/",
            "https://launchermeta.mojang.com/" to "${Paths.BMCL}/",
            "https://piston-data.mojang.com/" to "${Paths.BMCL}/",
            "https://resources.download.minecraft.net/" to "${Paths.BMCL}/assets/",
            "https://libraries.minecraft.net/" to "${Paths.BMCL}/maven/",
        )
        for ((from, to) in map) {
            if (url.startsWith(from)) return to + url.substring(from.length)
        }
        return null
    }

    fun expand(url: String): List<String> {
        val mirror = rewriteBmcl(url)
        return if (mirror != null) listOf(mirror, url) else listOf(url)
    }

    private val preferredVersions = listOf("1.21.1", "1.21", "1.20.1", "1.20.4", "1.19.4")

    fun pickDefaultVersion(rows: List<com.pymcl.mobile.model.VersionRow>, installed: List<String>): String {
        installed.lastOrNull()?.let { return it }
        for (id in preferredVersions) {
            if (rows.any { it.id == id }) return id
        }
        return rows.firstOrNull { it.type == "release" }?.id.orEmpty()
    }
}
