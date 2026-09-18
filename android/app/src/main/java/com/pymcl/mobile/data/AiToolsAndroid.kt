package com.pymcl.mobile.data

import com.pymcl.mobile.model.CatalogHit
import org.json.JSONObject
import java.io.File

/**
 * [AiToolHost] 的 Android 实现：全部只读，直接读现有的 InstanceStore / CatalogRepo / AuthRepo。
 * 没有任何写入路径——写入类工具要过 [WriteGate]，本轮没有实现放行。
 */
object AndroidToolHost : AiToolHost {
    override val defaultInstance: String
        get() = InstanceStore.list().firstOrNull()?.name ?: "default"

    override fun listInstances(): Map<String, List<String>> =
        InstanceStore.list().associate { it.name to it.versions }

    override fun installedVersions(instance: String): List<String> = InstanceStore.installedVersions(instance)

    override fun listMods(instance: String): List<String> {
        val dir = File(Paths.instanceDir(instance), "mods")
        if (!dir.isDirectory) return emptyList()
        return dir.listFiles()
            ?.filter { it.isFile && (it.name.endsWith(".jar", true) || it.name.endsWith(".jar.disabled", true)) }
            ?.map { it.name }
            ?.sorted()
            ?: emptyList()
    }

    override fun searchMods(query: String): List<CatalogHit> = CatalogRepo.searchMods(query)

    override fun currentSettings(): JSONObject {
        val cfg = InstanceStore.loadConfig()
        val ai = AiConfig.fromConfig(cfg)
        return JSONObject()
            .put("username", cfg.optString("username", "Player"))
            .put("memory_mb", cfg.optInt("memory_mb", 2048))
            .put("download_source", cfg.optString("download_source", "bmclapi"))
            .put("default_instance", defaultInstance)
            .put("ai_mode", AiRepo.describe(ai))
            .put("ai_model", ai.effectiveModel)
            .put("ai_key_configured", ai.hasKey)
    }

    override fun listAccounts(): List<String> =
        AuthRepo.accounts().map { if (it.type == "offline") "离线" else "${it.name}（${it.type}）" }

    /** 日志最多读这么多字节，尾部优先——诊断只看头尾，中间读进来也是白占内存。 */
    private const val MAX_LOG_BYTES = 2L * 1024 * 1024

    override fun readLatestLog(instance: String): String =
        readTail(File(Paths.instanceDir(instance), "logs/latest.log"))

    override fun readLatestCrashReport(instance: String): String {
        val dir = File(Paths.instanceDir(instance), "crash-reports")
        val newest = dir.listFiles()
            ?.filter { it.isFile && it.name.startsWith("crash-") && it.name.endsWith(".txt") }
            ?.maxByOrNull { it.lastModified() }
            ?: return ""
        return readTail(newest)
    }

    override fun modMetas(instance: String): List<ModMeta> {
        val dir = File(Paths.instanceDir(instance), "mods")
        if (!dir.isDirectory) return emptyList()
        return dir.listFiles()
            ?.filter { it.isFile && (it.name.endsWith(".jar", true) || it.name.endsWith(".jar.disabled", true)) }
            ?.sortedBy { it.name.lowercase() }
            ?.map { ModConflictAnalyzer.readJar(it) }
            ?: emptyList()
    }

    override fun instanceTarget(instance: String): Pair<String, String> {
        val versions = InstanceStore.installedVersions(instance)
        if (versions.isEmpty()) return "" to ""
        // 多个版本时优先带加载器的那个：它才是真正会被启动、也才会装 mods 的
        val pick = versions.firstOrNull { v ->
            val l = v.lowercase()
            l.contains("fabric") || l.contains("forge") || l.contains("quilt")
        } ?: versions.first()
        val json = Paths.readJson(File(Paths.instanceDir(instance), "versions/$pick/$pick.json"), JSONObject())
        return ModConflictAnalyzer.detectInstanceTarget(pick, json)
    }

    private fun readTail(file: File): String {
        if (!file.isFile) return ""
        return try {
            val len = file.length()
            if (len <= MAX_LOG_BYTES) return file.readText(Charsets.UTF_8)
            java.io.RandomAccessFile(file, "r").use { raf ->
                raf.seek(len - MAX_LOG_BYTES)
                val buf = ByteArray(MAX_LOG_BYTES.toInt())
                raf.readFully(buf)
                "…(前面 ${len - MAX_LOG_BYTES} 字节已略)\n" + buf.toString(Charsets.UTF_8)
            }
        } catch (e: Exception) {
            ""
        }
    }
}
