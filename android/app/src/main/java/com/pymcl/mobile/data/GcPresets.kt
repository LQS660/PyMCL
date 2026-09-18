package com.pymcl.mobile.data

/**
 * 垃圾回收器预设，对齐桌面 `mclauncher/gc.py`（它又对齐 PCL 2.12）。
 *
 * 只负责「这个预设对应哪串 JVM 参数」以及「往已有参数里接的时候要不要接」，
 * 真正拼命令行是 [LaunchPlanner] 的事。
 */
object GcPresets {
    const val FOLLOW_GLOBAL = ""

    val LABELS: Map<String, String> = linkedMapOf(
        "auto" to "G1（推荐）",
        "g1" to "G1",
        "g1_tuned" to "调优 G1",
        "zgc" to "ZGC",
        "none" to "不指定",
    )

    val ARGS: Map<String, String> = mapOf(
        "auto" to "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 " +
            "-XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M",
        "g1" to "-XX:+UseG1GC",
        "g1_tuned" to "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 " +
            "-XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M " +
            "-XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:+ParallelRefProcEnabled",
        "zgc" to "-XX:+UseZGC -XX:+UnlockExperimentalVMOptions",
        "none" to "",
    )

    /** 已经写了 GC 旗标的参数串，说明用户自己定过，不再往上叠一层。 */
    private val GC_FLAGS = setOf(
        "-XX:+UseG1GC", "-XX:+UseZGC", "-XX:+UseShenandoahGC",
        "-XX:+UseParallelGC", "-XX:+UseConcMarkSweepGC", "-XX:+UseSerialGC",
    )

    fun label(key: String): String = LABELS[key] ?: "跟随全局"

    fun keyOf(label: String): String = LABELS.entries.firstOrNull { it.value == label }?.key ?: FOLLOW_GLOBAL

    fun presetArgs(key: String): String = ARGS[key.trim().lowercase()] ?: ARGS.getValue("auto")

    internal fun hasGcFlag(args: List<String>): Boolean =
        args.any { it in GC_FLAGS || (it.startsWith("-XX:+Use") && it.contains("GC")) }

    /** 把预设接到已有 JVM 参数前面。已经有 GC 旗标就原样返回，不重复指定。 */
    fun apply(preset: String, existing: String = ""): String {
        val bits = VersionSettings.splitArgs(existing)
        if (hasGcFlag(bits)) return existing.trim()
        val extra = presetArgs(preset)
        if (extra.isEmpty()) return existing.trim()
        if (existing.isBlank()) return extra
        return "$extra ${existing.trim()}"
    }
}
