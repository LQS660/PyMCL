package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File

/** 一个主题包：颜色、深浅、壁纸与观感那几档，跟桌面 themes.py 的字段一一对应。 */
data class ThemePack(
    val name: String,
    val themeColor: String,
    val dark: Boolean,
    val background: String = "",
    val backgroundFolder: String = "",
    val sidebarOpacity: Int = 85,
    val backgroundBlur: Int = 0,
    val backgroundDim: Int = 25,
    val backgroundShuffle: Boolean = false,
    val backgroundInterval: Int = 10,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("name", name)
        .put(SettingsKeys.THEME_COLOR, themeColor)
        .put(SettingsKeys.UI_DARK, dark)
        .put(SettingsKeys.UI_BACKGROUND, background)
        .put(SettingsKeys.UI_BACKGROUND_FOLDER, backgroundFolder)
        .put(SettingsKeys.UI_SIDEBAR_OPACITY, sidebarOpacity)
        .put(SettingsKeys.UI_BACKGROUND_BLUR, backgroundBlur)
        .put(SettingsKeys.UI_BACKGROUND_DIM, backgroundDim)
        .put(SettingsKeys.UI_BACKGROUND_SHUFFLE, backgroundShuffle)
        .put(SettingsKeys.UI_BACKGROUND_INTERVAL, backgroundInterval)
}

/**
 * 主题包体系。对齐 `mclauncher/themes.py`：保存 / 加载 / 删除 / 导入 / 导出。
 *
 * 主题包换壁纸也要能撤销——这条路径绕开了设置页的保存按钮，不在这儿补一次
 * 历史栈，用主题包换掉的那张就退不回来了（桌面那边踩过这个坑）。
 */
object ThemeStore {
    fun parse(json: JSONObject, fallbackName: String = "未命名"): ThemePack = ThemePack(
        name = json.optString("name", fallbackName).ifBlank { fallbackName },
        themeColor = json.optString(SettingsKeys.THEME_COLOR, "#2E9B6B"),
        dark = json.optBoolean(SettingsKeys.UI_DARK, false),
        background = json.optString(SettingsKeys.UI_BACKGROUND),
        backgroundFolder = json.optString(SettingsKeys.UI_BACKGROUND_FOLDER),
        sidebarOpacity = json.optInt(SettingsKeys.UI_SIDEBAR_OPACITY, 85),
        backgroundBlur = json.optInt(SettingsKeys.UI_BACKGROUND_BLUR, 0),
        backgroundDim = json.optInt(SettingsKeys.UI_BACKGROUND_DIM, 25),
        backgroundShuffle = json.optBoolean(SettingsKeys.UI_BACKGROUND_SHUFFLE, false),
        backgroundInterval = json.optInt(SettingsKeys.UI_BACKGROUND_INTERVAL, 10),
    )

    fun current(name: String = "当前主题"): ThemePack = ThemePack(
        name = name,
        themeColor = Settings.str(SettingsKeys.THEME_COLOR, "#2E9B6B"),
        dark = Settings.bool(SettingsKeys.UI_DARK),
        background = Settings.str(SettingsKeys.UI_BACKGROUND),
        backgroundFolder = Settings.str(SettingsKeys.UI_BACKGROUND_FOLDER),
        sidebarOpacity = Settings.int(SettingsKeys.UI_SIDEBAR_OPACITY, 85),
        backgroundBlur = Settings.int(SettingsKeys.UI_BACKGROUND_BLUR, 0),
        backgroundDim = Settings.int(SettingsKeys.UI_BACKGROUND_DIM, 25),
        backgroundShuffle = Settings.bool(SettingsKeys.UI_BACKGROUND_SHUFFLE),
        backgroundInterval = Settings.int(SettingsKeys.UI_BACKGROUND_INTERVAL, 10),
    )

    fun list(): List<ThemePack> {
        val files = Paths.themesRoot.listFiles()
            ?.filter { it.isFile && it.name.endsWith(".json") }
            ?.sortedBy { it.name }
            ?: return emptyList()
        return files.mapNotNull { f ->
            val json = Paths.readJson(f, JSONObject())
            if (json.length() == 0) null else parse(json, f.nameWithoutExtension)
        }
    }

    fun save(name: String): ThemePack {
        val pack = current(name)
        Paths.writeJson(Paths.themeFile(name), pack.toJson())
        return pack
    }

    fun delete(name: String) {
        Paths.themeFile(name).takeIf { it.isFile }?.delete()
    }

    /**
     * 应用一个主题包。返回要写进配置的那一批键，**壁纸历史已经算进去了**。
     * 单独摘成函数是为了能离线测：真正落盘在 [load] 里。
     */
    fun applyUpdates(
        pack: ThemePack,
        oldImage: String,
        oldFolder: String,
        images: List<String>,
        folders: List<String>,
    ): Map<String, Any> {
        val updates = mutableMapOf<String, Any>(
            SettingsKeys.THEME_COLOR to pack.themeColor,
            SettingsKeys.UI_DARK to pack.dark,
            SettingsKeys.UI_BACKGROUND to pack.background,
            SettingsKeys.UI_BACKGROUND_FOLDER to pack.backgroundFolder,
            SettingsKeys.UI_SIDEBAR_OPACITY to SettingsLogic.clampPercent(pack.sidebarOpacity),
            SettingsKeys.UI_BACKGROUND_BLUR to SettingsLogic.clampBlur(pack.backgroundBlur),
            SettingsKeys.UI_BACKGROUND_DIM to SettingsLogic.clampPercent(pack.backgroundDim),
            SettingsKeys.UI_BACKGROUND_SHUFFLE to pack.backgroundShuffle,
            SettingsKeys.UI_BACKGROUND_INTERVAL to pack.backgroundInterval.coerceAtLeast(1),
        )
        if (pack.background != oldImage || pack.backgroundFolder != oldFolder) {
            val (nextImages, nextFolders) =
                SettingsLogic.pushBackgroundHistory(images, folders, oldImage, oldFolder)
            updates[SettingsKeys.UI_BACKGROUND_HISTORY] = nextImages
            updates[SettingsKeys.UI_BACKGROUND_FOLDER_HISTORY] = nextFolders
        }
        return updates
    }

    fun load(name: String): ThemePack {
        val file = Paths.themeFile(name)
        if (!file.isFile) throw IllegalArgumentException("主题包不存在：$name")
        val pack = parse(Paths.readJson(file), name)
        val updates = applyUpdates(
            pack,
            Settings.str(SettingsKeys.UI_BACKGROUND),
            Settings.str(SettingsKeys.UI_BACKGROUND_FOLDER),
            Settings.list(SettingsKeys.UI_BACKGROUND_HISTORY),
            Settings.list(SettingsKeys.UI_BACKGROUND_FOLDER_HISTORY),
        )
        updates.forEach { (k, v) ->
            if (v is List<*>) {
                Settings.setList(k, v.map { it.toString() })
            } else {
                Settings.set(k, v)
            }
        }
        Settings.flushIfDirty()
        return pack
    }

    fun exportTo(name: String, dest: File): File {
        val src = Paths.themeFile(name)
        if (!src.isFile) throw IllegalArgumentException("主题包不存在：$name")
        dest.parentFile?.mkdirs()
        src.copyTo(dest, overwrite = true)
        return dest
    }

    fun importFrom(src: File): String {
        if (!src.isFile) throw IllegalArgumentException("文件不存在：${src.path}")
        val json = Paths.readJson(src, JSONObject())
        if (json.length() == 0) throw IllegalArgumentException("这不是一个有效的主题包")
        val pack = parse(json, src.nameWithoutExtension)
        Paths.writeJson(Paths.themeFile(pack.name), pack.toJson())
        return pack.name
    }

    /** 撤销上一张壁纸：两个栈成对弹出，才能把当时那一整套状态退回去。 */
    fun undoBackground(): Boolean {
        val (images, folders) = SettingsLogic.pairHistory(
            Settings.list(SettingsKeys.UI_BACKGROUND_HISTORY),
            Settings.list(SettingsKeys.UI_BACKGROUND_FOLDER_HISTORY),
        )
        if (images.isEmpty()) return false
        Settings.update(
            mapOf(
                SettingsKeys.UI_BACKGROUND to images.last(),
                SettingsKeys.UI_BACKGROUND_FOLDER to folders.last(),
            ),
        )
        Settings.setList(SettingsKeys.UI_BACKGROUND_HISTORY, images.dropLast(1))
        Settings.setList(SettingsKeys.UI_BACKGROUND_FOLDER_HISTORY, folders.dropLast(1))
        Settings.flushIfDirty()
        return true
    }
}
