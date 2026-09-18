package com.pymcl.mobile.data

import android.os.Build
import org.json.JSONObject

/**
 * 反馈要附带的本机配置。对齐 `mclauncher/sysinfo.py` 的字段名。
 *
 * 结果缓存 [CACHE_MS]：反馈页每次刷新都重新问一遍系统属性没有意义，
 * 而心跳是 30 秒一次，不缓存就是每 30 秒做一次无谓的采集。
 */
object SysInfo {
    const val CACHE_MS = 120_000L

    @Volatile
    private var cached: JSONObject? = null

    @Volatile
    private var cachedAt = 0L

    fun collect(force: Boolean = false): JSONObject {
        val now = System.currentTimeMillis()
        cached?.let { if (!force && now - cachedAt < CACHE_MS) return it }
        val info = build()
        cached = info
        cachedAt = now
        return info
    }

    private fun build(): JSONObject {
        val runtime = Runtime.getRuntime()
        return JSONObject()
            .put("os", "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
            .put("abi", Build.SUPPORTED_ABIS.joinToString(","))
            .put("app_version", Paths.APP_VERSION)
            .put("jvm_max_mb", runtime.maxMemory() / (1024 * 1024))
            .put("cpu_cores", runtime.availableProcessors())
            .put("memory_setting_mb", Settings.int(SettingsKeys.MEMORY_MB, 2048))
            .put("download_source", Settings.str(SettingsKeys.DOWNLOAD_SOURCE, "auto"))
            .put("java_installed", JavaRuntime.scanInstalled(Paths.javaRoot).map { it.name }.joinToString(","))
            .put("instances", Paths.instancesRoot.listFiles()?.count { it.isDirectory } ?: 0)
    }

    /** 反馈页那块只读预览。字段顺序固定，用户一眼就知道会发出去什么。 */
    fun describe(info: JSONObject = collect()): String = buildString {
        appendLine("系统        ${info.optString("os")}")
        appendLine("设备        ${info.optString("device")}")
        appendLine("指令集      ${info.optString("abi")}")
        appendLine("启动器      PyMCL ${info.optString("app_version")} (android)")
        appendLine("CPU 核心    ${info.optInt("cpu_cores")}")
        appendLine("进程上限    ${info.optLong("jvm_max_mb")} MB")
        appendLine("分配内存    ${info.optInt("memory_setting_mb")} MB")
        appendLine("下载源      ${info.optString("download_source")}")
        appendLine("已装 Java   ${info.optString("java_installed").ifBlank { "无" }}")
        append("实例数      ${info.optInt("instances")}")
    }
}
