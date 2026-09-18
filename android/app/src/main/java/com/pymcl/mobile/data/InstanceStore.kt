package com.pymcl.mobile.data

import com.pymcl.mobile.model.InstanceInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object InstanceStore {
    private val dirs = listOf(
        "mods", "config", "saves", "resourcepacks", "shaderpacks",
        "datapacks", "screenshots", "crash-reports", "logs",
        "versions", "libraries", "backups",
    )

    fun list(): List<InstanceInfo> = listIn(Paths.instancesRoot)

    fun listIn(root: File): List<InstanceInfo> {
        if (!root.isDirectory) return emptyList()
        return root.listFiles()
            ?.filter { it.isDirectory && File(it, ".instance.json").isFile }
            ?.map { infoOf(it) }
            ?.sortedBy { it.name.lowercase() }
            ?: emptyList()
    }

    fun ensureDefault() {
        if (list().isEmpty()) create("default")
    }

    fun create(raw: String): InstanceInfo = createIn(Paths.instancesRoot, raw)

    fun createIn(root: File, raw: String): InstanceInfo {
        val name = unique(root, raw)
        val dir = File(root, name)
        dir.mkdirs()
        dirs.forEach { File(dir, it).mkdirs() }
        Paths.writeJson(
            File(dir, ".instance.json"),
            JSONObject().put("name", name).put("java", "自动选择"),
        )
        return infoOf(dir)
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

    fun installedVersions(name: String): List<String> = installedVersionsIn(Paths.instanceDir(name))

    /** 只认 `versions/<id>/<id>.json` 齐全的目录：半个下载留下的空壳不该出现在版本列表里。 */
    fun installedVersionsIn(instDir: File): List<String> {
        val vdir = File(instDir, "versions")
        if (!vdir.isDirectory) return emptyList()
        return vdir.listFiles()
            ?.filter { it.isDirectory && File(it, "${it.name}.json").isFile }
            ?.map { it.name }
            ?.sorted()
            ?: emptyList()
    }

    fun info(name: String): InstanceInfo = infoOf(Paths.instanceDir(name))

    fun infoOf(dir: File): InstanceInfo =
        InstanceInfo(dir.name, installedVersionsIn(dir), dir.absolutePath)

    private fun unique(root: File, raw: String): String {
        val base = Names.sanitize(raw)
        if (!File(root, base).exists()) return base
        var n = 2
        while (File(root, "$base-$n").exists()) n++
        return "$base-$n"
    }

    fun loadConfig(): JSONObject = withDefaults(Paths.readJson(Paths.configFile, JSONObject()))

    fun withDefaults(obj: JSONObject): JSONObject {
        if (!obj.has("memory_mb")) obj.put("memory_mb", 2048)
        if (!obj.has("username")) obj.put("username", "Player")
        if (!obj.has("download_source")) obj.put("download_source", "bmclapi")
        if (!obj.has("ai_url")) obj.put("ai_url", "")
        if (!obj.has("show_hidden_versions")) obj.put("show_hidden_versions", false)
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
