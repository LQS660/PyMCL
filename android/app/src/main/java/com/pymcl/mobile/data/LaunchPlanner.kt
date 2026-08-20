package com.pymcl.mobile.data

import com.pymcl.mobile.model.LaunchPlan
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object LaunchPlanner {
    fun plan(
        instance: String,
        version: String,
        username: String,
        memoryMb: Int,
        instDir: File = Paths.instanceDir(instance),
    ): LaunchPlan {
        val inst = instDir
        val json = resolveJson(inst, version)
        val jsonFile = File(inst, "versions/$version/$version.json")
        val missing = mutableListOf<String>()
        if (!jsonFile.isFile) missing += jsonFile.absolutePath
        val jar = JavaRuntime.versionJar(inst, json, version)
        if (!jar.isFile) missing += jar.absolutePath
        val main = json.optString("mainClass", "net.minecraft.client.main.Main")
        val classpath = mutableListOf<String>()
        if (jar.isFile) classpath += jar.absolutePath
        val libs = json.optJSONArray("libraries")
        var nativesMissing = false
        if (libs != null) {
            val libRoot = File(inst, "libraries")
            for (i in 0 until libs.length()) {
                val lib = libs.optJSONObject(i) ?: continue
                if (Installer.hasNativesClassifiers(lib) || Installer.isNativesArtifact(lib)) {
                    nativesMissing = true
                }
                if (!Installer.allowedByRules(lib)) continue
                val path = Installer.artifactRelPath(lib) ?: continue
                val f = File(libRoot, path.replace("/", File.separator))
                if (f.isFile) classpath += f.absolutePath else missing += f.absolutePath
            }
        }
        val gdir = gameDirOf(inst, version)
        gdir.mkdirs()
        val jvm = listOf("-Xmx${memoryMb}M", "-Xms${(memoryMb / 2).coerceAtLeast(512)}M")
        val game = listOf(
            "--username", username,
            "--version", version,
            "--gameDir", gdir.absolutePath,
            "--assetsDir", File(inst, "assets").absolutePath,
            "--accessToken", "0",
            "--uuid", "00000000-0000-0000-0000-000000000000",
            "--userType", "legacy",
        )
        return LaunchPlan(
            instance = instance,
            version = version,
            mainClass = main,
            classpath = classpath,
            gameArgs = game,
            jvmArgs = jvm,
            missing = missing.distinct(),
            nativesMissing = nativesMissing,
            gameDir = gdir.absolutePath,
        )
    }

    fun gameDirOf(instDir: File, version: String): File {
        val f = File(instDir, "versions/$version/pymcl.json")
        if (!f.isFile) return instDir
        val iso = runCatching { JSONObject(f.readText()).optString("isolation", "none") }.getOrDefault("none")
        return if (iso == "all" || iso == "saves") File(instDir, "versions/$version") else instDir
    }

    fun resolveJson(instDir: File, version: String, seen: MutableSet<String> = mutableSetOf()): JSONObject {
        val file = File(instDir, "versions/$version/$version.json")
        val child = if (file.isFile) JSONObject(file.readText()) else JSONObject()
        val parentId = child.optString("inheritsFrom")
        if (parentId.isBlank() || !seen.add(parentId)) return child
        return mergeVersionJson(resolveJson(instDir, parentId, seen), child)
    }

    fun mergeVersionJson(parent: JSONObject, child: JSONObject): JSONObject {
        val out = JSONObject(parent.toString())
        val keys = child.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            when (key) {
                "libraries" -> {
                    val merged = JSONArray()
                    parent.optJSONArray("libraries")?.let { arr ->
                        for (i in 0 until arr.length()) merged.put(arr.get(i))
                    }
                    child.optJSONArray("libraries")?.let { arr ->
                        for (i in 0 until arr.length()) merged.put(arr.get(i))
                    }
                    out.put("libraries", merged)
                }
                "arguments" -> {
                    val pa = parent.optJSONObject("arguments") ?: JSONObject()
                    val ca = child.optJSONObject("arguments") ?: JSONObject()
                    val merged = JSONObject()
                    for (kind in listOf("jvm", "game")) {
                        val arr = JSONArray()
                        pa.optJSONArray(kind)?.let { a -> for (i in 0 until a.length()) arr.put(a.get(i)) }
                        ca.optJSONArray(kind)?.let { a -> for (i in 0 until a.length()) arr.put(a.get(i)) }
                        if (arr.length() > 0) merged.put(kind, arr)
                    }
                    out.put("arguments", merged)
                }
                else -> if (!child.isNull(key)) out.put(key, child.get(key))
            }
        }
        return out
    }

    fun describe(plan: LaunchPlan): String {
        val b = StringBuilder()
        b.appendLine("实例 ${plan.instance} / ${plan.version}")
        b.appendLine("main ${plan.mainClass}")
        b.appendLine("gameDir ${plan.gameDir.ifBlank { "-" }}")
        b.appendLine("classpath ${plan.classpath.size} 项")
        b.appendLine("缺文件 ${plan.missing.size}")
        if (plan.nativesMissing) {
            b.appendLine("官方 natives 已跳过，进游戏走 Android LWJGL/JNI")
        }
        plan.missing.take(8).forEach { b.appendLine("  - $it") }
        return b.toString().trim()
    }
}
