package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.zip.ZipFile

/** 一条依赖声明。[version] 是原始范围文本（"*" = 任意）。 */
data class ModDep(val id: String, val version: String = "*")

/**
 * 一个模组 jar 的元数据。[source] 说明信息从哪来：
 * fabric.mod.json / quilt.mod.json / mods.toml / neoforge.mods.toml / mcmod.info / filename（只从文件名猜）。
 * 从文件名猜出来的字段只当线索，分析时会明说「推不出」。
 */
data class ModMeta(
    val file: String,
    val id: String,
    val name: String = id,
    val version: String = "",
    val loader: String = "",
    val mcVersion: String = "",
    val depends: List<ModDep> = emptyList(),
    val breaks: List<ModDep> = emptyList(),
    val enabled: Boolean = true,
    val source: String = "filename",
    val error: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("file", file)
        .put("id", id)
        .put("name", name)
        .put("version", version)
        .put("loader", loader)
        .put("mc_version", mcVersion)
        .put("enabled", enabled)
        .put("source", source)
        .put("depends", JSONArray(depends.map { it.id }))
        .also { if (error.isNotEmpty()) it.put("error", error) }
}

data class ConflictIssue(
    val type: String,
    val severity: String,
    val message: String,
    val files: List<String>,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("type", type)
        .put("severity", severity)
        .put("message", message)
        .put("files", JSONArray(files))
}

data class ConflictReport(
    val loader: String,
    val mcVersion: String,
    val mods: List<ModMeta>,
    val issues: List<ConflictIssue>,
    /** 推不出来的地方明说，不编：比如元数据没写版本范围、文件名看不出加载器。 */
    val notes: List<String>,
) {
    fun toJson(): JSONObject {
        val ms = JSONArray()
        mods.forEach { ms.put(it.toJson()) }
        val iss = JSONArray()
        issues.forEach { iss.put(it.toJson()) }
        return JSONObject()
            .put("loader", loader.ifEmpty { "unknown" })
            .put("mc_version", mcVersion.ifEmpty { "unknown" })
            .put("mod_count", mods.size)
            .put("enabled", mods.count { it.enabled })
            .put("issue_count", issues.size)
            .put("issues", iss)
            .put("notes", JSONArray(notes))
            .put("mods", ms)
    }
}

/**
 * 模组冲突分析，对齐桌面 mclauncher/ai/conflict.py 的 scan_conflicts：
 * 重复 id（两个版本）、加载器不匹配、MC 版本不匹配、缺依赖、声明互斥。
 * 元数据解析不依赖任何 TOML/JSON 库之外的东西（org.json 是平台自带）。
 */
object ModConflictAnalyzer {
    const val TYPE_DUPLICATE = "duplicate_id"
    const val TYPE_LOADER = "loader_mismatch"
    const val TYPE_MC_VERSION = "mc_version_mismatch"
    const val TYPE_MISSING_DEP = "missing_dep"
    const val TYPE_BREAKS = "breaks"

    private val SKIP_DEP = setOf(
        "minecraft", "java", "forge", "neoforge", "fabricloader", "fabric-loader",
        "quilt_loader", "quilt-loader", "fabric-language-kotlin",
    )
    private val FABRIC_API_ALIASES = setOf("fabric-api", "fabricapi", "fabric")

    // ---------------------------------------------------------------- 分析

    fun analyze(mods: List<ModMeta>, loader: String, mcVersion: String): ConflictReport {
        val issues = ArrayList<ConflictIssue>()
        val notes = ArrayList<String>()
        val loaderNorm = normalizeLoader(loader)
        val enabled = mods.filter { it.enabled }

        // 1. 同一个 id 装了多份
        enabled.filter { it.id.isNotEmpty() }.groupBy { it.id.lowercase() }.forEach { (id, group) ->
            if (group.size > 1) {
                val versions = group.map { it.version.ifEmpty { "?" } }.distinct()
                issues.add(
                    ConflictIssue(
                        TYPE_DUPLICATE, "error",
                        "模组 $id 装了 ${group.size} 份（版本 ${versions.joinToString(" / ")}），只留一个",
                        group.map { it.file },
                    ),
                )
            }
        }

        val present = enabled.map { it.id.lowercase() }.filter { it.isNotEmpty() }.toSet()
        for (m in enabled) {
            // 2. 加载器不匹配（quilt 能装 fabric 模组）
            val ml = normalizeLoader(m.loader)
            if (loaderNorm.isNotEmpty() && ml.isNotEmpty() && ml != loaderNorm && !(loaderNorm == "quilt" && ml == "fabric")) {
                issues.add(ConflictIssue(TYPE_LOADER, "error", "${m.file} 是 $ml 模组，当前实例是 $loaderNorm", listOf(m.file)))
            } else if (loaderNorm.isNotEmpty() && ml.isEmpty()) {
                notes.add("${m.file}：看不出是哪个加载器的模组（元数据来自 ${m.source}），没法判断是否匹配")
            }

            // 3. MC 版本不匹配。元数据里声明的才算证据；只从文件名猜出来的 1.x 只能当提醒。
            if (mcVersion.isNotEmpty()) {
                val declared = m.depends.firstOrNull { it.id.equals("minecraft", true) }?.version?.takeIf { it.isNotEmpty() && it != "*" }
                    ?: m.mcVersion.takeIf { it.isNotEmpty() && m.source != "filename" }
                val guessed = if (declared == null && m.source == "filename") m.mcVersion.takeIf { it.isNotEmpty() } else null
                if (declared != null) {
                    when (VersionRange.matches(declared, mcVersion)) {
                        false -> issues.add(
                            ConflictIssue(TYPE_MC_VERSION, "error", "${m.file} 要 Minecraft $declared，当前实例是 $mcVersion", listOf(m.file)),
                        )
                        null -> notes.add("${m.file}：版本范围「$declared」看不懂，没法判断是否匹配 $mcVersion")
                        true -> {}
                    }
                } else if (guessed != null) {
                    if (VersionRange.matches(guessed, mcVersion) == false) {
                        notes.add("${m.file}：文件名看着像给 Minecraft $guessed 的，当前实例是 $mcVersion——只凭文件名不能确定，装前核对一下")
                    }
                } else if (m.source != "filename") {
                    notes.add("${m.file}：元数据没有声明支持的 Minecraft 版本，跳过版本匹配")
                }
            }

            // 4. 缺依赖
            for (dep in m.depends) {
                val did = dep.id.lowercase()
                if (did.isEmpty() || did in SKIP_DEP) continue
                if (did in FABRIC_API_ALIASES) {
                    if (present.none { it in FABRIC_API_ALIASES }) {
                        issues.add(ConflictIssue(TYPE_MISSING_DEP, "error", "${m.name.ifEmpty { m.file }} 需要 Fabric API", listOf(m.file)))
                    }
                    continue
                }
                if (did !in present) {
                    issues.add(ConflictIssue(TYPE_MISSING_DEP, "error", "${m.name.ifEmpty { m.file }} 缺少依赖 $did", listOf(m.file)))
                }
            }

            // 5. 声明互斥
            for (br in m.breaks) {
                val bid = br.id.lowercase()
                if (bid.isNotEmpty() && bid in present) {
                    issues.add(ConflictIssue(TYPE_BREAKS, "error", "${m.id} 与 $bid 不兼容", listOf(m.file)))
                }
            }
        }
        if (loaderNorm.isEmpty() && mods.isNotEmpty()) notes.add("实例的加载器未知，没做加载器匹配检查")
        if (mcVersion.isEmpty() && mods.isNotEmpty()) notes.add("实例的 Minecraft 版本未知，没做版本匹配检查")
        return ConflictReport(loaderNorm, mcVersion, mods, issues, notes.distinct())
    }

    fun normalizeLoader(raw: String): String {
        val s = raw.trim().lowercase()
        return when {
            s.isEmpty() || s == "unknown" -> ""
            s.contains("neoforge") -> "neoforge"
            s.contains("forge") -> "forge"
            s.contains("quilt") -> "quilt"
            s.contains("fabric") -> "fabric"
            s.contains("liteloader") -> "liteloader"
            s == "无" || s == "vanilla" || s == "none" -> ""
            else -> s
        }
    }

    // ---------------------------------------------------------------- 元数据解析

    /** 读一个 jar。任何异常都收进 [ModMeta.error]，并退回文件名推断。 */
    fun readJar(file: File): ModMeta {
        val fromName = fromFileName(file.name)
        return try {
            ZipFile(file).use { zip ->
                fun text(name: String): String? = zip.getEntry(name)?.let { e ->
                    zip.getInputStream(e).use { it.readBytes().toString(Charsets.UTF_8) }
                }
                text("fabric.mod.json")?.let { return parseFabricModJson(it, fromName) }
                text("quilt.mod.json")?.let { return parseQuiltModJson(it, fromName) }
                text("META-INF/neoforge.mods.toml")?.let { return parseModsToml(it, "neoforge", fromName) }
                text("META-INF/mods.toml")?.let { return parseModsToml(it, "forge", fromName) }
                text("mcmod.info")?.let { return parseMcmodInfo(it, fromName) }
                fromName
            }
        } catch (e: Exception) {
            fromName.copy(error = e.message ?: e.toString())
        }
    }

    /**
     * 只从文件名猜：`sodium-fabric-0.5.8+mc1.20.1.jar` → id sodium / loader fabric / 0.5.8 / mc 1.20.1。
     * 猜不到的字段留空，source 标 filename。
     */
    fun fromFileName(fileName: String): ModMeta {
        val enabled = !fileName.lowercase().endsWith(".disabled")
        var stem = fileName
        for (suffix in listOf(".jar.disabled", ".disabled", ".jar")) {
            if (stem.lowercase().endsWith(suffix)) {
                stem = stem.substring(0, stem.length - suffix.length)
                break
            }
        }
        val lower = stem.lowercase()
        val loader = when {
            Regex("""(^|[-_+ .])neoforge([-_+ .]|$)""").containsMatchIn(lower) -> "neoforge"
            Regex("""(^|[-_+ .])forge([-_+ .]|$)""").containsMatchIn(lower) -> "forge"
            Regex("""(^|[-_+ .])fabric([-_+ .]|$)""").containsMatchIn(lower) && !lower.startsWith("fabric-api") -> "fabric"
            Regex("""(^|[-_+ .])quilt([-_+ .]|$)""").containsMatchIn(lower) -> "quilt"
            else -> ""
        }
        // MC 版本：1.7 起算，免得把模组自己的 1.0.0 当成游戏版本
        val mc = Regex("""(?<![\d.])(1\.(?:[7-9]|[1-9]\d)(?:\.\d{1,2})?)(?![\d.])""").find(lower)?.groupValues?.get(1).orEmpty()
        // 模组版本：第一段「数字.数字…」且不是刚认出来的 MC 版本
        val version = Regex("""(?<![\d.])(\d+\.\d+(?:\.\d+)*)(?![\d.])""").findAll(stem)
            .map { it.groupValues[1] }
            .firstOrNull { it != mc }
            .orEmpty()
        val loaderWords = setOf("fabric", "forge", "neoforge", "quilt", "mc")
        val words = stem.split(Regex("""[-_+ ]"""))
            .takeWhile { part -> part.isNotEmpty() && !part[0].isDigit() && !Regex("""^mc\d""").containsMatchIn(part.lowercase()) }
            .toMutableList()
        while (words.size > 1 && words.last().lowercase() in loaderWords) words.removeAt(words.size - 1)
        val id = words.joinToString("-").lowercase().ifEmpty { stem.lowercase() }
        return ModMeta(
            file = fileName, id = id, name = id, version = version, loader = loader, mcVersion = mc,
            enabled = enabled, source = "filename",
        )
    }

    fun parseFabricModJson(text: String, fallback: ModMeta): ModMeta {
        val o = runCatching { JSONObject(text) }.getOrNull()
            ?: return fallback.copy(error = "fabric.mod.json 不是合法 JSON")
        return fallback.copy(
            id = o.optString("id").ifEmpty { fallback.id },
            name = o.optString("name").ifEmpty { o.optString("id").ifEmpty { fallback.name } },
            version = o.optString("version"),
            loader = "fabric",
            depends = depMap(o.opt("depends")),
            breaks = depMap(o.opt("breaks")) + depMap(o.opt("conflicts")),
            source = "fabric.mod.json",
        )
    }

    fun parseQuiltModJson(text: String, fallback: ModMeta): ModMeta {
        val o = runCatching { JSONObject(text) }.getOrNull()
            ?: return fallback.copy(error = "quilt.mod.json 不是合法 JSON")
        val ql = o.optJSONObject("quilt_loader") ?: o
        val meta = ql.optJSONObject("metadata")
        return fallback.copy(
            id = ql.optString("id").ifEmpty { fallback.id },
            name = meta?.optString("name").orEmpty().ifEmpty { ql.optString("id").ifEmpty { fallback.name } },
            version = ql.optString("version"),
            loader = "quilt",
            depends = depMap(ql.opt("depends")),
            breaks = depMap(ql.opt("breaks")),
            source = "quilt.mod.json",
        )
    }

    /** Fabric/Quilt 的 depends 既可能是 {id: range}，也可能是 [{id, versions}] 或 ["id"]。 */
    private fun depMap(raw: Any?): List<ModDep> {
        val out = ArrayList<ModDep>()
        when (raw) {
            is JSONObject -> raw.keys().forEach { k ->
                val v = raw.opt(k)
                val range = when (v) {
                    is JSONArray -> (0 until v.length()).map { v.optString(it) }.filter { it.isNotEmpty() }.joinToString(" || ")
                    null -> "*"
                    else -> v.toString()
                }
                out.add(ModDep(k, range.ifEmpty { "*" }))
            }
            is JSONArray -> for (i in 0 until raw.length()) {
                when (val item = raw.opt(i)) {
                    is JSONObject -> {
                        val id = item.optString("id").ifEmpty { item.optString("mod") }
                        val vers = item.opt("versions") ?: item.opt("version")
                        val range = when (vers) {
                            is JSONArray -> (0 until vers.length()).map { vers.optString(it) }.joinToString(" || ")
                            null -> "*"
                            else -> vers.toString()
                        }
                        if (id.isNotEmpty()) out.add(ModDep(id, range.ifEmpty { "*" }))
                    }
                    is String -> if (item.isNotEmpty()) out.add(ModDep(item, "*"))
                }
            }
        }
        return out
    }

    /**
     * Forge / NeoForge 的 mods.toml，行式解析（对齐桌面 _parse_mods_toml_fallback），不依赖 TOML 库。
     * 只取第一个 [[mods]]，只取它名下 mandatory 的依赖。
     */
    fun parseModsToml(text: String, flavor: String, fallback: ModMeta): ModMeta {
        var loader = flavor
        val mods = ArrayList<MutableMap<String, String>>()
        val deps = ArrayList<MutableMap<String, String>>()
        var mode = ""
        var cur: MutableMap<String, String>? = null
        for (raw in text.lines()) {
            val s = raw.trim()
            if (s.isEmpty() || s.startsWith("#")) continue
            if (s.startsWith("[[mods]]")) {
                cur = HashMap<String, String>().also { mods.add(it) }
                mode = "mod"
                continue
            }
            val dm = Regex("""^\[\[dependencies\.([^\]]+)\]\]""").find(s)
            if (dm != null) {
                cur = HashMap<String, String>().also { it["owner"] = dm.groupValues[1]; deps.add(it) }
                mode = "dep"
                continue
            }
            if (s.startsWith("[")) {
                mode = ""
                cur = null
                continue
            }
            val eq = s.indexOf('=')
            if (eq < 0) continue
            val k = s.substring(0, eq).trim()
            val v = tomlValue(s.substring(eq + 1))
            if (k == "modLoader" && mode != "dep") loader = v
            cur?.put(k, v)
        }
        val primary = mods.firstOrNull() ?: return fallback.copy(
            loader = if (loader.contains("neo", true)) "neoforge" else "forge",
            source = if (flavor == "neoforge") "neoforge.mods.toml" else "mods.toml",
            error = "mods.toml 里没有 [[mods]]",
        )
        val id = primary["modId"].orEmpty().ifEmpty { fallback.id }
        val depends = ArrayList<ModDep>()
        val breaks = ArrayList<ModDep>()
        for (d in deps) {
            val owner = d["owner"].orEmpty()
            if (id.isNotEmpty() && owner.isNotEmpty() && owner != id) continue
            val did = d["modId"].orEmpty()
            if (did.isEmpty()) continue
            val range = d["versionRange"].orEmpty().ifEmpty { d["version"].orEmpty() }.ifEmpty { "*" }
            val type = d["type"].orEmpty().lowercase()
            val mandatory = d["mandatory"]?.lowercase() != "false" && type != "optional"
            if (type in setOf("incompatible", "broke", "break", "breaks")) breaks.add(ModDep(did, range))
            else if (mandatory) depends.add(ModDep(did, range))
        }
        return fallback.copy(
            id = id,
            name = primary["displayName"].orEmpty().ifEmpty { id },
            version = primary["version"].orEmpty().let { if (it.startsWith("\${")) "" else it },
            loader = if (loader.contains("neo", true) || flavor == "neoforge") "neoforge" else "forge",
            depends = depends,
            breaks = breaks,
            source = if (flavor == "neoforge") "neoforge.mods.toml" else "mods.toml",
        )
    }

    /** 取 `= ` 右边的值：带引号的只取引号内（后面的 # 注释自然被丢掉），不带引号的砍掉 ` #` 之后。 */
    internal fun tomlValue(rawValue: String): String {
        val v = rawValue.trim()
        Regex("""^"((?:[^"\\]|\\.)*)"""").find(v)?.let { return it.groupValues[1].replace("\\\"", "\"") }
        Regex("""^'([^']*)'""").find(v)?.let { return it.groupValues[1] }
        val hash = v.indexOf('#')
        return (if (hash >= 0) v.substring(0, hash) else v).trim()
    }

    fun parseMcmodInfo(text: String, fallback: ModMeta): ModMeta {
        val row: JSONObject? = runCatching {
            val t = text.trim()
            if (t.startsWith("[")) JSONArray(t).optJSONObject(0) else JSONObject(t)
        }.getOrNull()
        if (row == null) return fallback.copy(loader = "forge", source = "mcmod.info", error = "mcmod.info 不是合法 JSON")
        val required = row.optJSONArray("requiredMods")
        val deps = if (required != null) (0 until required.length()).map { ModDep(required.optString(it), "*") } else emptyList()
        return fallback.copy(
            id = row.optString("modid").ifEmpty { fallback.id },
            name = row.optString("name").ifEmpty { fallback.name },
            version = row.optString("version"),
            mcVersion = row.optString("mcversion"),
            loader = "forge",
            depends = deps.filter { it.id.isNotEmpty() },
            source = "mcmod.info",
        )
    }

    // ---------------------------------------------------------------- 实例侧

    /**
     * 从 versions/<id>/<id>.json 认加载器与 MC 版本。认不出的字段留空。
     * 例：id "fabric-loader-0.15.11-1.20.1" → fabric / 1.20.1；"1.20.1-forge-47.2.0" → forge / 1.20.1；
     * 纯原版 "1.20.1" → "" / 1.20.1。
     */
    fun detectInstanceTarget(versionId: String, versionJson: JSONObject?): Pair<String, String> {
        val idLower = versionId.lowercase()
        val libs = versionJson?.optJSONArray("libraries")
        val libNames = if (libs != null) (0 until libs.length()).mapNotNull { libs.optJSONObject(it)?.optString("name") } else emptyList()
        val blob = (idLower + " " + libNames.joinToString(" ")).lowercase()
        val loader = when {
            blob.contains("neoforge") -> "neoforge"
            blob.contains("minecraftforge") || Regex("""(^|[-_ ])forge([-_ ]|$)""").containsMatchIn(idLower) -> "forge"
            blob.contains("quilt") -> "quilt"
            blob.contains("fabric-loader") || blob.contains("net.fabricmc:fabric-loader") -> "fabric"
            else -> ""
        }
        val inherits = versionJson?.optString("inheritsFrom").orEmpty()
        val mc = inherits.ifEmpty {
            Regex("""(?<![\d.])(1\.\d{1,2}(?:\.\d{1,2})?)(?![\d.])""").find(versionId)?.groupValues?.get(1).orEmpty()
        }
        return loader to mc
    }
}

/**
 * 版本范围判断。看得懂的几种写法：精确 `1.20.1`、通配 `1.20.x` / `1.20.*`、`~1.20`、`^1.20`、
 * 比较符组合 `>=1.20 <1.21`、多选 `a || b`、Maven 区间 `[1.20,1.21)`。
 * 看不懂返回 null，调用方要如实说「推不出」。
 */
object VersionRange {
    fun matches(range: String, actual: String): Boolean? {
        val r = range.trim()
        if (r.isEmpty() || r == "*") return true
        if (r.contains("||")) {
            val parts = r.split("||").map { matches(it.trim(), actual) }
            if (parts.any { it == true }) return true
            return if (parts.any { it == null }) null else false
        }
        val a = parse(actual) ?: return null
        if (r.startsWith("[") || r.startsWith("(")) return maven(r, a)
        val clauses = r.split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (clauses.size > 1 && clauses.all { it.startsWith(">") || it.startsWith("<") || it.startsWith("=") }) {
            val results = clauses.map { matches(it, actual) }
            if (results.any { it == null }) return null
            return results.all { it == true }
        }
        if (clauses.size > 1) return null
        val c = clauses.first()
        return when {
            c.endsWith(".x") || c.endsWith(".*") -> {
                val base = parse(c.dropLast(2)) ?: return null
                a.size >= base.size && a.take(base.size) == base
            }
            c.startsWith("~") -> {
                val base = parse(c.drop(1)) ?: return null
                // ~1.20.1 = >=1.20.1 <1.21 ；~1.20 = >=1.20 <1.21
                val keep = if (base.size >= 2) 2 else 1
                compare(a, base) >= 0 && a.take(keep) == base.take(keep)
            }
            c.startsWith("^") -> {
                val base = parse(c.drop(1)) ?: return null
                compare(a, base) >= 0 && a.first() == base.first()
            }
            c.startsWith(">=") -> parse(c.drop(2))?.let { compare(a, it) >= 0 }
            c.startsWith("<=") -> parse(c.drop(2))?.let { compare(a, it) <= 0 }
            c.startsWith(">") -> parse(c.drop(1))?.let { compare(a, it) > 0 }
            c.startsWith("<") -> parse(c.drop(1))?.let { compare(a, it) < 0 }
            c.startsWith("=") -> parse(c.drop(1))?.let { compare(a, it) == 0 }
            else -> parse(c)?.let { compare(a, it) == 0 }
        }
    }

    private fun maven(r: String, a: List<Int>): Boolean? {
        val m = Regex("""^([\[(])\s*([^,\]\)]*)\s*(?:,\s*([^\]\)]*))?\s*([\])])$""").find(r) ?: return null
        val lowIncl = m.groupValues[1] == "["
        val highIncl = m.groupValues[4] == "]"
        val lowRaw = m.groupValues[2].trim()
        val highRaw = m.groupValues[3].trim()
        val noComma = !r.contains(",")
        if (noComma) {
            val exact = parse(lowRaw) ?: return null
            return compare(a, exact) == 0
        }
        if (lowRaw.isNotEmpty()) {
            val low = parse(lowRaw) ?: return null
            val c = compare(a, low)
            if (c < 0 || (c == 0 && !lowIncl)) return false
        }
        if (highRaw.isNotEmpty()) {
            val high = parse(highRaw) ?: return null
            val c = compare(a, high)
            if (c > 0 || (c == 0 && !highIncl)) return false
        }
        return true
    }

    /** "1.20.1" → [1,20,1]；带 -pre/-rc/快照写法一律看不懂（返回 null）。 */
    fun parse(v: String): List<Int>? {
        val s = v.trim()
        if (!Regex("""^\d+(\.\d+)*$""").matches(s)) return null
        return s.split('.').map { it.toIntOrNull() ?: return null }
    }

    private fun compare(a: List<Int>, b: List<Int>): Int {
        val n = maxOf(a.size, b.size)
        for (i in 0 until n) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x.compareTo(y)
        }
        return 0
    }
}
