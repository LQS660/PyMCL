package com.pymcl.mobile.data

import com.pymcl.mobile.model.PlaytimeSession
import com.pymcl.mobile.model.PlaytimeStat
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 游玩时长统计，落盘格式与桌面 `playtime.json` 完全一致，
 * 两端可以互相读——搬个目录过去时长不会丢。
 */
object Playtime {
    const val FILE_NAME = "playtime.json"

    /** 只留最近这么多条会话，跟桌面一样，免得文件无限长。 */
    const val MAX_SESSIONS = 500

    fun file(root: File): File = File(root, FILE_NAME)

    fun load(root: File): Map<String, PlaytimeStat> {
        val f = file(root)
        if (!f.isFile) return emptyMap()
        val obj = runCatching { JSONObject(f.readText()) }.getOrNull() ?: return emptyMap()
        return parse(obj)
    }

    fun parse(obj: JSONObject): Map<String, PlaytimeStat> {
        val instances = obj.optJSONObject("instances") ?: return emptyMap()
        val out = linkedMapOf<String, PlaytimeStat>()
        instances.keys().forEach { name ->
            val row = instances.optJSONObject(name) ?: return@forEach
            out[name] = statOf(row)
        }
        return out
    }

    private fun statOf(row: JSONObject): PlaytimeStat {
        val versions = linkedMapOf<String, Long>()
        row.optJSONObject("versions")?.let { vs ->
            vs.keys().forEach { versions[it] = vs.optLong(it) }
        }
        val sessions = mutableListOf<PlaytimeSession>()
        row.optJSONArray("sessions")?.let { arr ->
            for (i in 0 until arr.length()) {
                val s = arr.optJSONObject(i) ?: continue
                sessions += PlaytimeSession(
                    start = s.optLong("start"),
                    duration = s.optLong("duration"),
                    version = s.optString("version"),
                )
            }
        }
        return PlaytimeStat(row.optLong("total"), versions, sessions)
    }

    fun save(root: File, data: Map<String, PlaytimeStat>) {
        val instances = JSONObject()
        data.forEach { (name, stat) ->
            val versions = JSONObject()
            stat.versions.forEach { (v, secs) -> versions.put(v, secs) }
            val sessions = JSONArray()
            stat.sessions.forEach { s ->
                sessions.put(
                    JSONObject()
                        .put("start", s.start)
                        .put("duration", s.duration)
                        .put("version", s.version),
                )
            }
            instances.put(
                name,
                JSONObject()
                    .put("total", stat.total)
                    .put("versions", versions)
                    .put("sessions", sessions),
            )
        }
        val f = file(root)
        f.parentFile?.mkdirs()
        f.writeText(JSONObject().put("instances", instances).toString(2), Charsets.UTF_8)
    }

    /** 记一次游玩。`duration` 是秒；非正数直接忽略，不留空记录。 */
    fun record(
        root: File,
        instance: String,
        version: String,
        duration: Long,
        now: Long = System.currentTimeMillis() / 1000,
    ): PlaytimeStat {
        val data = load(root).toMutableMap()
        val old = data[instance] ?: PlaytimeStat()
        if (duration <= 0) return old
        val versions = old.versions.toMutableMap()
        versions[version] = (versions[version] ?: 0) + duration
        val sessions = (old.sessions + PlaytimeSession(now - duration, duration, version))
            .takeLast(MAX_SESSIONS)
        val stat = PlaytimeStat(old.total + duration, versions, sessions)
        data[instance] = stat
        save(root, data)
        return stat
    }

    fun get(root: File, instance: String): PlaytimeStat = load(root)[instance] ?: PlaytimeStat()

    fun totalOf(data: Map<String, PlaytimeStat>): Long = data.values.sumOf { it.total }

    /**
     * 清记录。`instance` 为空清全部；给了 `version` 就只摘掉那个版本的会话，
     * 并按剩下的会话重算总数——直接减会在旧数据缺会话时把总数减成负的。
     */
    fun clear(root: File, instance: String = "", version: String = "") {
        if (instance.isEmpty()) {
            save(root, emptyMap())
            return
        }
        val data = load(root).toMutableMap()
        val old = data[instance] ?: return
        if (version.isEmpty()) {
            data.remove(instance)
        } else {
            val kept = old.sessions.filter { it.version != version }
            val versions = linkedMapOf<String, Long>()
            kept.forEach { versions[it.version] = (versions[it.version] ?: 0) + it.duration }
            data[instance] = PlaytimeStat(kept.sumOf { it.duration }, versions, kept)
        }
        save(root, data)
    }

    fun format(seconds: Long): String {
        val s = if (seconds < 0) 0 else seconds
        val hours = s / 3600
        val mins = (s % 3600) / 60
        val secs = s % 60
        return when {
            hours > 0 -> "$hours 小时 $mins 分钟"
            mins > 0 -> "$mins 分钟 $secs 秒"
            else -> "$secs 秒"
        }
    }

    /** 包在一次启动外面：`start()` 记时刻，`stop()` 落盘并返回本次秒数。 */
    class Tracker(
        private val root: File,
        private val instance: String,
        private val version: String,
        private val clock: () -> Long = { System.currentTimeMillis() / 1000 },
    ) {
        private var startedAt = 0L

        fun start() {
            startedAt = clock()
        }

        fun stop(): Long {
            if (startedAt <= 0) return 0
            val duration = clock() - startedAt
            startedAt = 0
            if (duration <= 0) return 0
            Playtime.record(root, instance, version, duration, clock())
            return duration
        }
    }
}
