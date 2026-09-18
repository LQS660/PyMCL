package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 启动页卡片的一格。
 *
 * 坐标是「画布比例」而不是像素：x/y/w/h 都是 0..1。手机屏幕尺寸差得远，
 * 存绝对像素的话换台机器就溢出屏幕了——桌面 `mclauncher/ui_layout.py` 也是这个口径，
 * 两端读写同一个 `ui_layout` 键，桌面上排好的布局手机上打开就是同一个。
 */
data class LayoutItem(
    val type: String,
    val x: Float,
    val y: Float,
    val w: Float,
    val h: Float,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("type", type)
        .put("x", x.toDouble())
        .put("y", y.toDouble())
        .put("w", w.toDouble())
        .put("h", h.toDouble())
}

data class LayoutDoc(val version: Int, val items: List<LayoutItem>) {
    fun toJson(): JSONObject {
        val arr = JSONArray()
        items.forEach { arr.put(it.toJson()) }
        return JSONObject().put("version", version).put("items", arr)
    }
}

object LayoutStore {
    const val LAYOUT_VERSION = 1

    /** 认得的卡片类型，跟桌面 `CARD_MIN_SIZE` 的白名单一致。 */
    val KNOWN_CARDS = setOf(
        "banner", "config", "log", "news", "quick", "notes", "playtime", "tasks", "skin",
    )

    /** 手机是窄屏，出厂布局竖着摞，不照搬桌面的两列。 */
    fun defaultDoc(): LayoutDoc = LayoutDoc(
        version = LAYOUT_VERSION,
        items = listOf(
            LayoutItem("banner", 0f, 0f, 1f, 0.22f),
            LayoutItem("config", 0f, 0.22f, 1f, 0.34f),
            LayoutItem("quick", 0f, 0.56f, 0.5f, 0.16f),
            LayoutItem("tasks", 0.5f, 0.56f, 0.5f, 0.16f),
            LayoutItem("log", 0f, 0.72f, 1f, 0.28f),
        ),
    )

    /** 越界、重叠出屏、不认识的卡片全在这儿收掉——存进来的可能是桌面排的。 */
    fun parseDoc(json: JSONObject?): LayoutDoc? {
        if (json == null) return null
        val arr = json.optJSONArray("items") ?: return null
        val items = (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val type = o.optString("type")
            if (type !in KNOWN_CARDS) return@mapNotNull null
            val x = o.optDouble("x", 0.0).toFloat().coerceIn(0f, 1f)
            val y = o.optDouble("y", 0.0).toFloat().coerceIn(0f, 1f)
            val w = o.optDouble("w", 1.0).toFloat().coerceIn(0.05f, 1f)
            val h = o.optDouble("h", 0.2).toFloat().coerceIn(0.05f, 1f)
            LayoutItem(type, x, y, minOf(w, 1f - x), minOf(h, 1f - y))
        }
        if (items.isEmpty()) return null
        return LayoutDoc(json.optInt("version", LAYOUT_VERSION), items)
    }

    fun activeDoc(): LayoutDoc =
        parseDoc(Settings.all().optJSONObject(SettingsKeys.UI_LAYOUT)) ?: defaultDoc()

    fun saveActive(doc: LayoutDoc) {
        Settings.set(SettingsKeys.UI_LAYOUT, doc.toJson())
        Settings.flushIfDirty()
    }

    fun activeProfile(): String = Settings.str(SettingsKeys.UI_LAYOUT_PROFILE)

    fun profiles(): List<String> {
        val obj = Settings.all().optJSONObject(SettingsKeys.UI_LAYOUTS) ?: return emptyList()
        return obj.keys().asSequence().toList().sorted()
    }

    fun saveProfile(name: String, doc: LayoutDoc = activeDoc()) {
        val clean = name.trim()
        if (clean.isEmpty()) throw IllegalArgumentException("方案名不能为空")
        val obj = Settings.all().optJSONObject(SettingsKeys.UI_LAYOUTS) ?: JSONObject()
        obj.put(clean, doc.toJson())
        Settings.update(
            mapOf(
                SettingsKeys.UI_LAYOUTS to obj,
                SettingsKeys.UI_LAYOUT to doc.toJson(),
                SettingsKeys.UI_LAYOUT_PROFILE to clean,
            ),
        )
        Settings.flushIfDirty()
    }

    fun activateProfile(name: String): LayoutDoc {
        val obj = Settings.all().optJSONObject(SettingsKeys.UI_LAYOUTS)
        val doc = parseDoc(obj?.optJSONObject(name))
            ?: throw IllegalArgumentException("没有这个布局方案：$name")
        Settings.update(
            mapOf(
                SettingsKeys.UI_LAYOUT to doc.toJson(),
                SettingsKeys.UI_LAYOUT_PROFILE to name,
            ),
        )
        Settings.flushIfDirty()
        return doc
    }

    fun deleteProfile(name: String) {
        val obj = Settings.all().optJSONObject(SettingsKeys.UI_LAYOUTS) ?: return
        obj.remove(name)
        Settings.set(SettingsKeys.UI_LAYOUTS, obj)
        if (activeProfile() == name) Settings.set(SettingsKeys.UI_LAYOUT_PROFILE, "")
        Settings.flushIfDirty()
    }

    fun resetToDefault(): LayoutDoc {
        val doc = defaultDoc()
        Settings.update(
            mapOf(
                SettingsKeys.UI_LAYOUT to doc.toJson(),
                SettingsKeys.UI_LAYOUT_PROFILE to "",
            ),
        )
        Settings.flushIfDirty()
        return doc
    }

    fun exportTo(dest: File, doc: LayoutDoc = activeDoc()): File {
        dest.parentFile?.mkdirs()
        Paths.writeJson(dest, doc.toJson())
        return dest
    }

    fun importFrom(src: File): LayoutDoc {
        val doc = parseDoc(Paths.readJson(src, JSONObject()))
            ?: throw IllegalArgumentException("这不是一份能用的布局文件")
        saveActive(doc)
        return doc
    }
}
