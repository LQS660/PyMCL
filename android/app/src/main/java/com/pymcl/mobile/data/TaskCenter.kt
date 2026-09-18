package com.pymcl.mobile.data

import com.pymcl.mobile.model.TaskInfo

/**
 * 下载任务中心的纯逻辑：哪些任务算下载、进度文案怎么拆、红点怎么数。
 *
 * 判定必须和 UI 那边用的是同一份，否则底部下载条的计数会和任务页的卡片对不上
 * （桌面端就因为两处各留一份、漏了「皮肤站登录」而错过一次）。
 */
object TaskCenter {
    /** 分隔符左边是状态，右边是速度。安装器发的进度串就长这样。 */
    const val SPEED_SEP = "  |  "

    /** 标题以这些开头的才进下载条和红点计数。 */
    val DOWNLOAD_PREFIXES = listOf(
        "安装游戏", "安装整合包", "安装模组", "安装光影", "安装资源包",
        "安装数据包", "安装世界", "下载 Java", "备份存档", "导出存档",
        "导出整合包", "皮肤站登录", "安装", "下载",
    )

    /** 这些是交互流程，不该出现在下载条里。 */
    val EXCLUDED_PREFIXES = listOf("启动游戏", "微软登录")

    fun isDownloadTitle(title: String): Boolean {
        val text = title.trim()
        if (text.isEmpty()) return false
        if (EXCLUDED_PREFIXES.any { text.startsWith(it) }) return false
        return DOWNLOAD_PREFIXES.any { text.startsWith(it) }
    }

    /** `解压 libraries  |  3.2 MB/s` → (`解压 libraries`, `3.2 MB/s`)。 */
    fun splitProgressMessage(message: String): Pair<String, String> {
        val text = message.ifBlank { "" }
        val cut = text.indexOf(SPEED_SEP)
        if (cut < 0) return text to ""
        return text.substring(0, cut).trim() to text.substring(cut + SPEED_SEP.length).trim()
    }

    fun percent(current: Long, total: Long): Int =
        if (total <= 0) 0 else ((current * 100) / total).toInt().coerceIn(0, 100)

    fun activeCount(tasks: List<TaskInfo>): Int =
        tasks.count { !it.done && isDownloadTitle(it.title) }

    /**
     * 导航上那个红点里的字。0 不显示（返回空串），过百收成 `99+`——
     * 与桌面 `_update_task_badge` 同一口径，两端的角标不会一个写 100 一个写 99+。
     */
    fun badgeText(count: Int): String = when {
        count <= 0 -> ""
        count > 99 -> "99+"
        else -> count.toString()
    }

    fun finished(tasks: List<TaskInfo>): List<TaskInfo> = tasks.filter { it.done }

    fun clearFinished(tasks: List<TaskInfo>): List<TaskInfo> = tasks.filter { !it.done }

    /** 整合包安装默认展开日志：它最容易半路失败，用户第一时间就要看到原因。 */
    fun autoExpandLog(title: String): Boolean = title.contains("整合包")

    fun summary(task: TaskInfo): String {
        if (task.done) return if (task.success) "✔ ${task.message}" else "✘ ${task.message}"
        val (status, speed) = splitProgressMessage(task.message)
        val head = status.ifBlank { "处理中…" }
        return if (speed.isEmpty()) head else "$head · $speed"
    }

    fun humanSpeed(bytesPerSecond: Long): String = when {
        bytesPerSecond <= 0 -> ""
        bytesPerSecond >= 1L shl 20 ->
            String.format(java.util.Locale.US, "%.1f MB/s", bytesPerSecond / (1L shl 20).toDouble())
        bytesPerSecond >= 1024 ->
            String.format(java.util.Locale.US, "%.0f KB/s", bytesPerSecond / 1024.0)
        else -> "$bytesPerSecond B/s"
    }

    /** 每条任务只留最近 [limit] 行日志，安装整合包能刷出几万行。 */
    fun appendLog(task: TaskInfo, line: String, limit: Int = 40): TaskInfo =
        task.copy(log = (task.log + line).takeLast(limit))
}
