package com.pymcl.mobile.data

import com.pymcl.mobile.model.VersionCard
import org.json.JSONObject
import java.io.File

class VersionError(message: String) : RuntimeException(message)

/** 版本管理页的动作：改名、复制、隐藏、卸载、修复，以及卡片上那几行信息怎么算出来。 */
object VersionOps {
    /** [loaderOf] 认不出加载器时给的名字。UI 层按它判断「能不能装加载器」，显示时再过词表。 */
    const val LOADER_VANILLA = "原版"

    private val mcPattern = Regex("""\d+\.\d+(\.\d+)?""")

    fun versionDir(instDir: File, version: String): File = File(instDir, "versions/$version")

    fun jsonFile(instDir: File, version: String): File =
        File(versionDir(instDir, version), "$version.json")

    /** 从合成后的 json 认加载器。判定顺序有讲究：NeoForge 的 mainClass 里也带 forge。 */
    fun loaderOf(json: JSONObject): String {
        val main = json.optString("mainClass").lowercase()
        val libs = json.optJSONArray("libraries")
        val names = buildList {
            if (libs != null) {
                for (i in 0 until libs.length()) {
                    add(libs.optJSONObject(i)?.optString("name").orEmpty().lowercase())
                }
            }
        }
        fun has(token: String) = names.any { it.contains(token) }
        return when {
            has("net.neoforged") || main.contains("neoforge") -> "NeoForge"
            has("net.minecraftforge") || main.contains("forge") -> "Forge"
            has("org.quiltmc") || main.contains("quilt") -> "Quilt"
            has("net.fabricmc") || main.contains("knot") -> "Fabric"
            has("optifine") -> "OptiFine"
            has("liteloader") -> "LiteLoader"
            else -> LOADER_VANILLA
        }
    }

    /** 卡片左上角那一小块的配色，与桌面版本管理页同一套。 */
    fun loaderColor(loader: String): String = when (loader) {
        "Fabric" -> "#C8A165"
        "Forge" -> "#4C6EA8"
        "NeoForge" -> "#E07A3F"
        "Quilt" -> "#9B59B6"
        "OptiFine" -> "#2FA36B"
        "LiteLoader" -> "#8A9099"
        else -> "#4C8BF5"
    }

    /**
     * 版本号对应的 Minecraft 本体版本。优先用 json 里的 `inheritsFrom` / `clientVersion`，
     * 都没有就从 id 里抠一个 `1.20.1` 出来——`1.20.1-forge-47.2.0` 这种最常见。
     */
    fun mcVersionOf(instDir: File, version: String): String {
        val raw = readJson(instDir, version)
        val inherits = raw?.optString("inheritsFrom").orEmpty()
        if (inherits.isNotBlank()) return inherits
        val client = raw?.optString("clientVersion").orEmpty()
        if (client.isNotBlank()) return client
        return mcPattern.find(version)?.value.orEmpty()
    }

    private fun readJson(instDir: File, version: String): JSONObject? {
        val f = jsonFile(instDir, version)
        if (!f.isFile) return null
        return runCatching { JSONObject(f.readText()) }.getOrNull()
    }

    fun cards(instDir: File, includeHidden: Boolean = false): List<VersionCard> =
        InstanceStore.installedVersionsIn(instDir)
            .map { card(instDir, it) }
            .filter { includeHidden || !it.hidden }

    fun card(instDir: File, version: String): VersionCard {
        val settings = VersionSettings.load(instDir, version)
        val merged = runCatching { LaunchPlanner.resolveJson(instDir, version) }.getOrDefault(JSONObject())
        val loader = loaderOf(merged)
        return VersionCard(
            id = version,
            mc = mcVersionOf(instDir, version),
            loader = loader,
            mods = Mods.list(instDir, version).size,
            isolated = VersionSettings.isolatedMods(settings),
            hidden = settings.hidden,
        )
    }

    fun filter(rows: List<VersionCard>, query: String): List<VersionCard> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return rows
        return rows.filter { it.id.lowercase().contains(q) || it.loader.lowercase().contains(q) }
    }

    /** 版本目录名就是版本 id，所以改名要连目录、json 文件名和 json 里的 id 一起改。 */
    fun rename(instDir: File, version: String, newRaw: String): String {
        val newId = Names.sanitize(newRaw, version)
        if (newId == version) return version
        val src = versionDir(instDir, version)
        if (!src.isDirectory) throw VersionError("版本不存在: $version")
        val dest = versionDir(instDir, newId)
        if (dest.exists()) throw VersionError("已有同名版本: $newId")
        if (!src.renameTo(dest)) throw VersionError("重命名失败: $version")
        retitle(dest, version, newId)
        return newId
    }

    fun copy(instDir: File, version: String, newRaw: String): String {
        val newId = Names.sanitize(newRaw, "$version-copy")
        val src = versionDir(instDir, version)
        if (!src.isDirectory) throw VersionError("版本不存在: $version")
        val dest = versionDir(instDir, newId)
        if (dest.exists()) throw VersionError("已有同名版本: $newId")
        src.copyRecursively(dest)
        retitle(dest, version, newId)
        return newId
    }

    private fun retitle(dir: File, oldId: String, newId: String) {
        val oldJson = File(dir, "$oldId.json")
        val newJson = File(dir, "$newId.json")
        if (oldJson.isFile) oldJson.renameTo(newJson)
        val oldJar = File(dir, "$oldId.jar")
        if (oldJar.isFile) oldJar.renameTo(File(dir, "$newId.jar"))
        if (newJson.isFile) {
            runCatching {
                val obj = JSONObject(newJson.readText())
                obj.put("id", newId)
                newJson.writeText(obj.toString(2), Charsets.UTF_8)
            }
        }
    }

    fun setHidden(instDir: File, version: String, hidden: Boolean) {
        val s = VersionSettings.load(instDir, version)
        VersionSettings.save(instDir, version, s.copy(hidden = hidden))
    }

    fun toggleHidden(instDir: File, version: String): Boolean {
        val hidden = !VersionSettings.load(instDir, version).hidden
        setHidden(instDir, version, hidden)
        return hidden
    }

    fun uninstall(instDir: File, version: String) {
        val dir = versionDir(instDir, version)
        if (!dir.isDirectory) throw VersionError("版本不存在: $version")
        if (!dir.deleteRecursively()) throw VersionError("卸载失败: $version")
    }

    /** 修复前先看缺什么：返回缺失文件的绝对路径，空表就是齐的。 */
    fun missingFiles(instDir: File, version: String): List<String> =
        LaunchPlanner.plan("repair", version, "Player", 2048, instDir).missing

    /** 导出一份能直接跑的启动脚本，方便用户搬到别处或贴给别人排错。 */
    fun launchScript(instDir: File, version: String, username: String, memoryMb: Int): String {
        val plan = LaunchPlanner.plan("export", version, username, memoryMb, instDir)
        val sep = if (File.separatorChar == '\\') ";" else ":"
        val cp = plan.classpath.joinToString(sep)
        return buildString {
            appendLine("#!/bin/sh")
            appendLine("# PyMCL 导出的启动脚本 · $version")
            appendLine("cd \"${plan.gameDir}\"")
            append("exec java ")
            append(plan.jvmArgs.joinToString(" "))
            append(" -cp \"$cp\" ")
            append(plan.mainClass)
            append(" ")
            appendLine(plan.gameArgs.joinToString(" "))
        }
    }
}
