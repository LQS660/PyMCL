package com.pymcl.mobile.data

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.InputStream

/**
 * 多语言，词表与桌面 `mclauncher/i18n.py` 同源。
 *
 * 键就是中文原文：`t("启动游戏")` 在 zh_CN 下原样返回，在 en 下查 `en.json`。
 * 词表按语言分两层：`assets/locales/<lang>.json` 是桌面 `mclauncher/locales/` 的原样副本，
 * 由桌面那边维护、这里只读；安卓独有的词放 `<lang>.android.json` 叠层，**先查叠层再查主表**，
 * 两处都没有就回落中文原文——所以 zh_CN 与 en 之间不互相兜底，中文界面上不会冒出英文。
 *
 * 语言从 [SettingsKeys.LANGUAGE] 来：[init] 时读一次，设置页切换时调 [setLanguage]。
 * 表本身不依赖 Android：单测用 [loadFromDir] / [load] 从文件或流装进来即可。
 */
object I18n {
    const val DEFAULT_LANG = "zh_CN"
    const val ASSET_DIR = "locales"
    const val OVERLAY_SUFFIX = ".android.json"
    const val MAIN_SUFFIX = ".json"

    /** 语言代码 → 显示名，顺序即设置页里的顺序；与桌面 `i18n.LANGUAGES` 一致。 */
    val LANGUAGES: List<Pair<String, String>> = listOf(
        "zh_CN" to "简体中文",
        "en" to "English",
    )

    @Volatile
    private var main: Map<String, Map<String, String>> = emptyMap()

    @Volatile
    private var overlay: Map<String, Map<String, String>> = emptyMap()

    /** 当前语言代码，永远是 [normalize] 过的。 */
    @Volatile
    var language: String = DEFAULT_LANG
        private set

    /** 每切一次语言 +1，外壳据此把整棵界面树重组一遍。 */
    @Volatile
    var revision: Int = 0
        private set

    /** 取词：叠层 → 主表 → 中文原文。空串原样返回。 */
    fun t(zh: String): String = t(zh, language)

    fun t(zh: String, lang: String): String {
        if (zh.isEmpty()) return zh
        overlay[lang]?.get(zh)?.let { if (it.isNotEmpty()) return it }
        main[lang]?.get(zh)?.let { if (it.isNotEmpty()) return it }
        return zh
    }

    /** `zh-CN` / ` en ` 这类写法都收成表里的代码；空或不认识的退回 [DEFAULT_LANG]。 */
    fun normalize(lang: String?): String {
        val code = (lang ?: "").trim().replace('-', '_')
        if (code.isEmpty()) return DEFAULT_LANG
        return if (isKnown(code)) code else DEFAULT_LANG
    }

    /** 切语言。返回实际生效的代码；没变就不涨 [revision]。 */
    fun setLanguage(lang: String?): String {
        val code = normalize(lang)
        synchronized(this) {
            if (code != language) {
                language = code
                revision++
            }
        }
        return code
    }

    /** 表里有过（主表或叠层）、或在 [LANGUAGES] 里列了名字的语言。 */
    fun isKnown(lang: String): Boolean =
        LANGUAGES.any { it.first == lang } || main.containsKey(lang) || overlay.containsKey(lang)

    /** 有词表可查的语言代码，按 [LANGUAGES] 顺序，其余附在后面。 */
    fun available(): List<String> {
        val listed = LANGUAGES.map { it.first }
        val extra = (main.keys + overlay.keys).filter { it !in listed }.sorted()
        return listed + extra
    }

    fun hasMain(lang: String): Boolean = main.containsKey(lang)

    fun hasOverlay(lang: String): Boolean = overlay.containsKey(lang)

    /** 主表条数，给设置页 / 单测看一眼词表有没有真装进来。 */
    fun mainSize(lang: String): Int = main[lang]?.size ?: 0

    fun overlaySize(lang: String): Int = overlay[lang]?.size ?: 0

    // ------------------------------------------------------------------ 装表

    /** 应用启动时调：从 assets 读全部词表，再按设置里的语言切过去。 */
    fun init(context: Context) {
        loadFromAssets(context)
        setLanguage(Settings.str(SettingsKeys.LANGUAGE, DEFAULT_LANG))
    }

    fun loadFromAssets(context: Context) {
        val assets = context.assets
        val names = runCatching { assets.list(ASSET_DIR)?.toList() }.getOrNull().orEmpty()
        loadNamed(names) { name -> runCatching { assets.open("$ASSET_DIR/$name") }.getOrNull() }
    }

    /** 单测 / 工具用：从一个目录装，目录里躺着 `<lang>.json` 与 `<lang>.android.json`。 */
    fun loadFromDir(dir: File) {
        val names = dir.listFiles()?.filter { it.isFile }?.map { it.name }.orEmpty()
        loadNamed(names) { name -> File(dir, name).takeIf { it.isFile }?.inputStream() }
    }

    /** 给一门语言装主表 / 叠层；传 null 的那一份不动。 */
    fun load(lang: String, mainJson: InputStream?, overlayJson: InputStream?) {
        mainJson?.let { putMain(lang, parse(it)) }
        overlayJson?.let { putOverlay(lang, parse(it)) }
    }

    fun putMain(lang: String, table: Map<String, String>) {
        synchronized(this) { main = main + (lang to table) }
    }

    fun putOverlay(lang: String, table: Map<String, String>) {
        synchronized(this) { overlay = overlay + (lang to table) }
    }

    /** 清空全部词表并回到默认语言，单测之间互不串味。 */
    fun reset() {
        synchronized(this) {
            main = emptyMap()
            overlay = emptyMap()
            language = DEFAULT_LANG
            revision++
        }
    }

    private fun loadNamed(names: List<String>, open: (String) -> InputStream?) {
        val mains = HashMap<String, Map<String, String>>()
        val overlays = HashMap<String, Map<String, String>>()
        for (name in names.sorted()) {
            when {
                name.endsWith(OVERLAY_SUFFIX) -> {
                    val lang = name.removeSuffix(OVERLAY_SUFFIX)
                    open(name)?.let { overlays[lang] = parse(it) }
                }
                name.endsWith(MAIN_SUFFIX) -> {
                    val lang = name.removeSuffix(MAIN_SUFFIX)
                    open(name)?.let { mains[lang] = parse(it) }
                }
            }
        }
        synchronized(this) {
            main = main + mains
            overlay = overlay + overlays
        }
    }

    /** 坏 JSON 当空表：一份词表写错不该把整个启动器拖死，缺词会回落中文。 */
    fun parse(input: InputStream): Map<String, String> {
        val text = input.use { it.readBytes().toString(Charsets.UTF_8) }
        return parse(text)
    }

    fun parse(text: String): Map<String, String> {
        val obj = runCatching { JSONObject(text) }.getOrNull() ?: return emptyMap()
        val out = HashMap<String, String>(obj.length())
        for (key in obj.keys()) {
            val value = obj.optString(key, "")
            if (key.isNotEmpty()) out[key] = value
        }
        return out
    }
}

/** UI 层统一用这个：`Text(t("设置"))`。 */
fun t(zh: String): String = I18n.t(zh)

/** 一组枚举的显示名；`ChipRow` 这类按显示名回传选中项的控件，用它把名字反查回枚举。 */
fun <E> List<E>.byLabel(label: String, labelOf: (E) -> String): E? = firstOrNull { labelOf(it) == label }

/** 词表里的 `{0}` `{1}` 占位替换，与桌面词表同一种写法：`t("第 {0} / {1} 步").fmt(1, 3)`。 */
fun String.fmt(vararg args: Any?): String {
    var out = this
    args.forEachIndexed { i, arg -> out = out.replace("{$i}", arg?.toString() ?: "") }
    return out
}
