package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File

class InstallCancelled : RuntimeException("已取消")

object Installer {
    @Volatile
    var cancelled = false

    /** version JSON 的 os.name；Android 当 linux，windows/osx 库会被 rules 跳过。 */
    const val RULES_OS = "linux"

    fun installVanilla(
        instance: String,
        row: com.pymcl.mobile.model.VersionRow,
        onProgress: (Long, Long, String) -> Unit,
        onLog: (String) -> Unit,
        instDir: File = Paths.instanceDir(instance),
    ) {
        cancelled = false
        val inst = instDir
        inst.mkdirs()
        val vdir = File(inst, "versions/${row.id}")
        vdir.mkdirs()
        val libRoot = File(inst, "libraries")
        libRoot.mkdirs()
        onLog("拉取版本 JSON ${row.id}")
        val json = ManifestRepo.fetchVersionJson(row)
        val jsonFile = File(vdir, "${row.id}.json")
        jsonFile.writeText(json.toString(2), Charsets.UTF_8)

        val jar = File(vdir, "${row.id}.jar")
        val client = json.optJSONObject("downloads")?.optJSONObject("client")
        if (client != null) {
            val url = client.optString("url")
            val sha1 = client.optString("sha1")
            val size = client.optLong("size", 0)
            onLog("下载客户端 ${row.id}.jar")
            downloadFirst(Names.expand(url), jar, sha1) { d, t ->
                tick()
                onProgress(d, if (t > 0) t else size, "客户端 ${fmt(d)}/${fmt(if (t > 0) t else size)}")
            }
        } else {
            onLog("版本 JSON 无 downloads.client，跳过客户端 jar")
        }

        val libs = json.optJSONArray("libraries")
        if (libs != null) {
            val total = libs.length()
            var done = 0
            for (i in 0 until total) {
                tick()
                val lib = libs.getJSONObject(i)
                val name = lib.optString("name", "?")
                onProgress(done.toLong(), total.toLong(), "依赖库 ${done + 1}/$total")
                val skip = skipReason(lib)
                if (skip != null) {
                    onLog(skip)
                    done++
                    continue
                }
                if (hasNativesClassifiers(lib)) {
                    onLog("跳过 natives classifiers $name：Android 用自研 LWJGL")
                }
                val path = artifactRelPath(lib)
                if (path.isNullOrBlank()) {
                    done++
                    continue
                }
                val dest = File(libRoot, path.replace("/", File.separator))
                val artifact = lib.optJSONObject("downloads")?.optJSONObject("artifact")
                val url = artifact?.optString("url").orEmpty()
                val sha1 = artifact?.optString("sha1")
                if (url.isNotBlank()) {
                    downloadFirst(Names.expand(url), dest, sha1)
                }
                done++
            }
        }

        jsonFile.writeText(json.toString(2), Charsets.UTF_8)
        onLog("已写入 ${jsonFile.path}")
        onLog("客户端 ${jar.path}${if (jar.isFile) "" else "（缺失）"}")
        onLog("依赖库 ${libRoot.path}")
        onLog("安装完成 ${row.id} → $instance")
        onProgress(1, 1, "完成")
    }

    fun allowedByRules(lib: JSONObject, osName: String = RULES_OS): Boolean {
        val rules = lib.optJSONArray("rules") ?: return true
        var allow = false
        for (i in 0 until rules.length()) {
            val rule = rules.optJSONObject(i) ?: continue
            if (ruleMatches(rule, osName)) {
                allow = rule.optString("action", "allow") == "allow"
            }
        }
        return allow
    }

    fun hasNativesClassifiers(lib: JSONObject): Boolean {
        if (lib.has("natives")) return true
        return lib.optJSONObject("downloads")?.has("classifiers") == true
    }

    fun isNativesArtifact(lib: JSONObject): Boolean {
        if (mavenIsNatives(lib.optString("name"))) return true
        val path = lib.optJSONObject("downloads")?.optJSONObject("artifact")?.optString("path").orEmpty()
        return pathLooksNatives(path)
    }

    /** 可进 classpath / 需要下载的 Java artifact 相对路径；natives 与未允许的库返回 null。 */
    fun artifactRelPath(lib: JSONObject): String? {
        if (!allowedByRules(lib)) return null
        if (isNativesArtifact(lib)) return null
        val path = lib.optJSONObject("downloads")?.optJSONObject("artifact")?.optString("path").orEmpty()
        return path.takeIf { it.isNotBlank() }
    }

    fun skipReason(lib: JSONObject): String? {
        val name = lib.optString("name", "?")
        if (!allowedByRules(lib)) {
            val os = osNames(lib).joinToString("/").ifBlank { "unknown" }
            return "跳过库 $name：rules os.name=$os（Android 跳过 windows/osx）"
        }
        if (isNativesArtifact(lib)) {
            return "跳过 natives classifiers $name：Android 用自研 LWJGL"
        }
        if (hasNativesClassifiers(lib)) {
            val path = lib.optJSONObject("downloads")?.optJSONObject("artifact")?.optString("path").orEmpty()
            if (path.isBlank()) {
                return "跳过 natives classifiers $name：Android 用自研 LWJGL"
            }
        }
        return null
    }

    fun osNames(lib: JSONObject): List<String> {
        val rules = lib.optJSONArray("rules") ?: return emptyList()
        val names = mutableListOf<String>()
        for (i in 0 until rules.length()) {
            val n = rules.optJSONObject(i)?.optJSONObject("os")?.optString("name").orEmpty()
            if (n.isNotBlank()) names += n
        }
        return names.distinct()
    }

    internal fun mavenIsNatives(name: String): Boolean {
        val parts = name.split(":")
        return parts.size >= 4 && parts[3].startsWith("natives-", ignoreCase = true)
    }

    internal fun pathLooksNatives(path: String): Boolean {
        if (path.isBlank()) return false
        val file = path.substringAfterLast('/').substringAfterLast('\\')
        return file.contains("-natives-", ignoreCase = true) ||
            file.startsWith("natives-", ignoreCase = true)
    }

    private fun ruleMatches(rule: JSONObject, osName: String): Boolean {
        val os = rule.optJSONObject("os") ?: return true
        val name = os.optString("name")
        if (name.isNotBlank() && !name.equals(osName, ignoreCase = true)) return false
        return true
    }

    private fun downloadFirst(
        urls: List<String>,
        dest: File,
        sha1: String?,
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ) {
        var last: Exception? = null
        for (url in urls) {
            tick()
            try {
                Http.download(url, dest, sha1, onProgress)
                return
            } catch (e: Exception) {
                last = e
            }
        }
        throw last ?: HttpException("download failed ${dest.name}")
    }

    private fun tick() {
        if (cancelled) throw InstallCancelled()
    }

    private fun fmt(n: Long): String {
        if (n <= 0) return "?"
        return "%.1f MB".format(n / 1024.0 / 1024.0)
    }
}
