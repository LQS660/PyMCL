package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject

/**
 * 壁纸配置的落盘薄层：只管 config.json 里 "wallpaper" 这一个键。
 *
 * 判断一律不在这儿——清单、轮播、撤销栈的行为全在 [WallpaperCodec] 与
 * WallpaperModel.kt 里，这个文件只做 Map ↔ JSON 与读写文件。
 *
 * [load] / [save] 走 [Paths] 的 filesDir，只能在设备上跑；[toJson] / [toPlain]
 * 是纯的（org.json 在单测里是 Maven 那份实现），所以往返可以单测。
 */
object WallpaperStore {
    const val CONFIG_KEY = "wallpaper"

    fun load(): WallpaperState =
        WallpaperCodec.fromMap(toPlain(Paths.readJson(Paths.configFile).opt(CONFIG_KEY)) as? Map<*, *>)

    /**
     * 读—改—写同一份 config.json，跟 AppViewModel.persistUi() 是同一个套路。
     * 两边同时写会互相覆盖，那是这份配置文件本来就有的问题，本轮不引入也不修。
     */
    fun save(state: WallpaperState) {
        val cfg = Paths.readJson(Paths.configFile)
        cfg.put(CONFIG_KEY, toJson(WallpaperCodec.toMap(state)))
        Paths.writeJson(Paths.configFile, cfg)
    }

    /** Map / List / 基本类型 → JSONObject / JSONArray。 */
    fun toJson(value: Any?): Any = when (value) {
        null -> JSONObject.NULL
        is Map<*, *> -> JSONObject().also { obj ->
            value.forEach { (k, v) -> obj.put(k.toString(), toJson(v)) }
        }
        is Iterable<*> -> JSONArray().also { arr -> value.forEach { arr.put(toJson(it)) } }
        else -> value
    }

    /** JSONObject / JSONArray → Map / List；JSONObject.NULL 收敛成 null。 */
    fun toPlain(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().associateWith { toPlain(value.opt(it)) }
        is JSONArray -> (0 until value.length()).map { toPlain(value.opt(it)) }
        else -> value
    }
}
