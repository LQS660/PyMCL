package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

data class FeedbackRow(
    val id: String,
    val category: String,
    val title: String,
    val time: Long,
)

class FeedbackError(message: String) : RuntimeException(message)

/**
 * 反馈上报。对齐 `app/pages/feedback_page.py` + `mclauncher/feedback.py`。
 *
 * 没有明确同意过就一条都不发：这条是硬闸，不是提示。
 */
object FeedbackRepo {
    const val DEFAULT_URL = "http://114.66.28.184:53611"
    private const val MAX_HISTORY = 30

    /** 分类与桌面 `feedback_defaults.CATEGORIES` 同序同名，后台看板才对得上。 */
    val CATEGORIES: List<Pair<String, String>> = listOf(
        "bug" to "功能异常",
        "crash" to "崩溃闪退",
        "download" to "下载问题",
        "multiplayer" to "联机",
        "ai" to "AI 助手",
        "ui" to "界面体验",
        "suggest" to "建议",
        "other" to "其他",
    )

    fun categoryLabel(key: String): String =
        CATEGORIES.firstOrNull { it.first == key }?.second ?: "其他"

    fun resolveUrl(): String =
        Settings.str(SettingsKeys.FEEDBACK_URL).trim().trimEnd('/').ifBlank { DEFAULT_URL }

    fun hasConsent(): Boolean = Settings.bool(SettingsKeys.FEEDBACK_CONSENT)

    fun setConsent(ok: Boolean) {
        Settings.set(SettingsKeys.FEEDBACK_CONSENT, ok)
        Settings.flushIfDirty()
    }

    /** 设备 ID 只用来把同一台机器的多条反馈串起来，不含任何账号信息。 */
    fun deviceId(): String {
        val existing = Settings.str(SettingsKeys.DEVICE_ID)
        if (existing.isNotBlank()) return existing
        val fresh = UUID.randomUUID().toString()
        Settings.set(SettingsKeys.DEVICE_ID, fresh)
        Settings.flushIfDirty()
        return fresh
    }

    /**
     * 组装上报体。标题空了就拿正文第一行顶上，两个都空才算空——
     * 跟桌面 `feedback.submit` 的收敛顺序一致，否则同一条反馈两端 ID 对不上。
     */
    fun buildPayload(
        deviceId: String,
        category: String,
        title: String,
        body: String,
        contact: String,
        sysinfo: JSONObject?,
        crash: JSONObject? = null,
    ): JSONObject {
        val cat = category.trim().lowercase()
            .takeIf { key -> CATEGORIES.any { it.first == key } } ?: "other"
        val cleanTitle = title.trim().take(120)
        val cleanBody = body.trim().take(16000)
        if (cleanTitle.isEmpty() && cleanBody.isEmpty()) {
            throw FeedbackError("请填写标题或描述")
        }
        val finalTitle = cleanTitle.ifEmpty {
            cleanBody.lineSequence().firstOrNull().orEmpty().take(80).ifEmpty { "未命名问题" }
        }
        return JSONObject()
            .put("device_id", deviceId)
            .put("category", cat)
            .put("title", finalTitle)
            .put("body", cleanBody)
            .put("contact", contact.trim().take(120))
            .put("app_version", Paths.APP_VERSION)
            .put("platform", "android")
            .put("crash", crash ?: JSONObject.NULL)
            .put("sysinfo", sysinfo ?: JSONObject())
    }

    fun submit(
        category: String,
        title: String,
        body: String,
        contact: String = "",
        includeSysinfo: Boolean = true,
        crash: JSONObject? = null,
    ): String {
        if (!hasConsent()) throw FeedbackError("需要先同意上传这些内容，反馈页顶上那个开关。")
        val payload = buildPayload(
            deviceId(),
            category,
            title,
            body,
            contact,
            if (includeSysinfo) SysInfo.collect() else null,
            crash,
        )
        val (code, respBody) = Http.postJson("${resolveUrl()}/api/feedback", payload.toString())
        if (code !in 200..299) throw FeedbackError("发送失败 HTTP $code ${respBody.take(160)}")
        val id = runCatching { JSONObject(respBody).optString("id") }.getOrNull().orEmpty()
        addHistory(
            FeedbackRow(
                id = id.ifBlank { "local-${System.currentTimeMillis()}" },
                category = payload.optString("category"),
                title = payload.optString("title"),
                time = System.currentTimeMillis(),
            ),
        )
        return id
    }

    fun submitCrash(report: CrashReport, extra: String = ""): String {
        val body = listOf(extra.trim(), report.summary, report.excerpt.take(8000))
            .filter { it.isNotBlank() }
            .joinToString("\n\n")
        val crash = JSONObject()
            .put("headline", report.headline)
            .put("summary", report.summary)
            .put("reason", report.reason)
            .put("exit_code", report.exitCode)
        return submit("crash", report.headline.take(120), body.ifBlank { report.headline }, crash = crash)
    }

    fun history(): List<FeedbackRow> {
        val arr = Paths.readJson(Paths.feedbackHistoryFile).optJSONArray("rows")
            ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            FeedbackRow(
                id = o.optString("id"),
                category = o.optString("category"),
                title = o.optString("title"),
                time = o.optLong("time"),
            )
        }
    }

    fun addHistory(row: FeedbackRow) {
        val rows = (listOf(row) + history()).take(MAX_HISTORY)
        val arr = JSONArray()
        rows.forEach {
            arr.put(
                JSONObject()
                    .put("id", it.id)
                    .put("category", it.category)
                    .put("title", it.title)
                    .put("time", it.time),
            )
        }
        Paths.writeJson(Paths.feedbackHistoryFile, JSONObject().put("rows", arr))
    }
}
