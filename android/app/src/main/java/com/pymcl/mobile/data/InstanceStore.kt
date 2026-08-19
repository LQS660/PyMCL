package com.pymcl.mobile.data

import com.pymcl.mobile.model.InstanceInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object InstanceStore {
    private val dirs = listOf(
        "mods", "config", "saves", "resourcepacks", "shaderpacks",
        "datapacks", "screenshots", "crash-reports", "logs",
        "versions", "libraries",
    )

    fun list(): List<InstanceInfo> {
        val root = Paths.instancesRoot
        if (!root.isDirectory) return emptyList()
        return root.listFiles()
            ?.filter { it.isDirectory && File(it, ".instance.json").isFile }
            ?.map { info(it.name) }
            ?.sortedBy { it.name.lowercase() }
            ?: emptyList()
    }

    fun ensureDefault() {
        if (list().isEmpty()) create("default")
    }

    fun create(raw: String): InstanceInfo {
        val name = unique(raw)
        val dir = Paths.instanceDir(name)
        dir.mkdirs()
        dirs.forEach { File(dir, it).mkdirs() }
        Paths.writeJson(
            File(dir, ".instance.json"),
            JSONObject().put("name", name).put("java", "自动选择"),
        )
        return info(name)
    }

    fun delete(name: String) {
        Paths.instanceDir(name).deleteRecursively()
    }

    fun rename(name: String, newRaw: String) {
        val destName = Names.sanitize(newRaw)
        val src = Paths.instanceDir(name)
        val dest = Paths.instanceDir(destName)
        if (dest.exists()) throw IllegalStateException("实例已存在: $destName")
        if (!src.renameTo(dest)) throw IllegalStateException("重命名失败")
        val meta = File(dest, ".instance.json")
        val obj = Paths.readJson(meta)
        obj.put("name", destName)
        Paths.writeJson(meta, obj)
    }

    fun installedVersions(name: String): List<String> {
        val vdir = File(Paths.instanceDir(name), "versions")
        if (!vdir.isDirectory) return emptyList()
        return vdir.listFiles()
            ?.filter { it.isDirectory && File(it, "${it.name}.json").isFile }
            ?.map { it.name }
            ?.sorted()
            ?: emptyList()
    }

    fun info(name: String): InstanceInfo {
        val dir = Paths.instanceDir(name)
        return InstanceInfo(name, installedVersions(name), dir.absolutePath)
    }

    private fun unique(raw: String): String {
        val base = Names.sanitize(raw)
        val existing = list().map { it.name }.toSet()
        if (base !in existing && !Paths.instanceDir(base).exists()) return base
        var n = 2
        while (true) {
            val name = "$base-$n"
            if (name !in existing && !Paths.instanceDir(name).exists()) return name
            n++
        }
    }

    fun loadConfig(): JSONObject {
        val obj = Paths.readJson(Paths.configFile, JSONObject())
        if (!obj.has("memory_mb")) obj.put("memory_mb", 2048)
        if (!obj.has("username")) obj.put("username", "Player")
        if (!obj.has("download_source")) obj.put("download_source", "bmclapi")
        if (!obj.has("ai_url")) obj.put("ai_url", "")
        return obj
    }

    fun saveConfig(obj: JSONObject) = Paths.writeJson(Paths.configFile, obj)

    fun loadAccounts(): List<JSONObject> {
        val root = Paths.readJson(Paths.accountsFile, JSONObject().put("accounts", JSONArray()))
        val arr = root.optJSONArray("accounts") ?: JSONArray()
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }

    fun saveAccounts(list: List<JSONObject>) {
        val arr = JSONArray()
        list.forEach { arr.put(it) }
        Paths.writeJson(Paths.accountsFile, JSONObject().put("accounts", arr))
    }
}
