package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File
import java.util.UUID

object JavaRuntime {
    fun javaMajor(json: JSONObject, versionId: String = ""): Int {
        val listed = json.optJSONObject("javaVersion")?.optInt("majorVersion", 0) ?: 0
        if (listed > 0) return listed
        val id = versionId.ifBlank { json.optString("id") }
        val n = mcNumber(id)
        return when {
            n >= 1.205 -> 21
            n >= 1.18 -> 17
            n >= 1.17 -> 16
            else -> 8
        }
    }

    fun jreDirName(major: Int): String = when {
        major >= 25 -> "jre25"
        major >= 21 -> "jre21"
        major >= 17 -> "jre17"
        else -> "jre8"
    }

    fun lwjglPack(json: JSONObject): String {
        val libs = json.optJSONArray("libraries") ?: return "3.3.3"
        var best = "3.3.3"
        for (i in 0 until libs.length()) {
            val name = libs.optJSONObject(i)?.optString("name").orEmpty()
            val parts = name.split(":")
            if (parts.size < 3) continue
            if (parts[0] != "org.lwjgl" || parts[1] != "lwjgl") continue
            val ver = parts[2]
            if (compareVer(ver, "3.4.1") >= 0) return "3.4.1"
            if (compareVer(ver, "3.3.3") >= 0) best = "3.3.3"
        }
        return best
    }

    fun needsLwjglX(json: JSONObject): Boolean {
        val libs = json.optJSONArray("libraries") ?: return false
        for (i in 0 until libs.length()) {
            val name = libs.optJSONObject(i)?.optString("name").orEmpty()
            if (name.startsWith("org.lwjgl.lwjgl:lwjgl:2")) return true
        }
        return false
    }

    fun offlineUuid(username: String): String {
        return UUID.nameUUIDFromBytes("OfflinePlayer:$username".toByteArray(Charsets.UTF_8)).toString()
    }

    fun isLwjglLibraryPath(path: String): Boolean {
        val p = path.replace('\\', '/')
        return p.contains("/org/lwjgl/")
    }

    fun mcNumber(id: String): Double {
        val m = Regex("""(\d+)\.(\d+)(?:\.(\d+))?""").find(id) ?: return 0.0
        val major = m.groupValues[1].toInt()
        val minor = m.groupValues[2].toInt()
        val patch = m.groupValues.getOrNull(3)?.toIntOrNull() ?: 0
        return major + minor / 100.0 + patch / 10000.0
    }

    fun compareVer(a: String, b: String): Int {
        val pa = a.split('.', '-').mapNotNull { it.toIntOrNull() }
        val pb = b.split('.', '-').mapNotNull { it.toIntOrNull() }
        val n = maxOf(pa.size, pb.size)
        for (i in 0 until n) {
            val x = pa.getOrElse(i) { 0 }
            val y = pb.getOrElse(i) { 0 }
            if (x != y) return x.compareTo(y)
        }
        return 0
    }

    fun assetIndex(json: JSONObject): String {
        return json.optJSONObject("assetIndex")?.optString("id").orEmpty()
            .ifBlank { json.optString("assets") }
    }

    fun versionJar(instDir: File, json: JSONObject, version: String): File {
        val direct = File(instDir, "versions/$version/$version.jar")
        if (direct.isFile) return direct
        val inherited = json.optString("inheritsFrom")
        if (inherited.isNotBlank()) {
            val parent = File(instDir, "versions/$inherited/$inherited.jar")
            if (parent.isFile) return parent
        }
        return direct
    }
}
