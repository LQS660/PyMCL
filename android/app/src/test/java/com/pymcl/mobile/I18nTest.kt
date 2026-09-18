package com.pymcl.mobile

import com.pymcl.mobile.data.I18n
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * 多语言：取词 / 回落 / 叠层 / 切换，外加一条护栏——ui 下不允许再出现没包 t() 的中文字面量。
 * 全部纯 JVM：词表从 `app/src/main/assets/locales/` 按文件装，不碰 Android Context。
 */
class I18nTest {

    /** Gradle 跑单测时工作目录是模块目录（app/）；从 android/ 或仓库根跑也兜一下。 */
    private fun firstDir(vararg candidates: String): File? =
        candidates.map { File(it) }.firstOrNull { it.isDirectory }

    private fun localesDir(): File {
        val dir = firstDir("src/main/assets/locales", "app/src/main/assets/locales", "android/app/src/main/assets/locales")
        assertTrue("找不到 assets/locales，测试没装到任何词表", dir != null)
        return dir!!
    }

    private fun uiDir(): File {
        val dir = firstDir(
            "src/main/java/com/pymcl/mobile/ui",
            "app/src/main/java/com/pymcl/mobile/ui",
            "android/app/src/main/java/com/pymcl/mobile/ui",
        )
        assertTrue("找不到 ui 源码目录，护栏没扫到任何东西", dir != null)
        return dir!!
    }

    @Before
    fun fresh() {
        I18n.reset()
    }

    @After
    fun restore() {
        I18n.reset()
    }

    // ---------------------------------------------------------------- 装表

    @Test
    fun loadsMainAndOverlayTablesFromAssetsDir() {
        I18n.loadFromDir(localesDir())
        assertTrue(I18n.hasMain("zh_CN"))
        assertTrue(I18n.hasMain("en"))
        assertTrue(I18n.hasOverlay("en"))
        assertTrue(I18n.hasOverlay("zh_CN"))
        // 主表是桌面 mclauncher/locales 的原样副本，千条上下；叠层是安卓独有的那几百条
        assertTrue("zh_CN 主表太小: ${I18n.mainSize("zh_CN")}", I18n.mainSize("zh_CN") >= 1000)
        assertTrue("en 主表太小: ${I18n.mainSize("en")}", I18n.mainSize("en") >= 1000)
        assertTrue("en 叠层为空", I18n.overlaySize("en") >= 300)
        assertEquals(listOf("zh_CN", "en"), I18n.available())
    }

    @Test
    fun englishComesFromMainTableAndOverlay() {
        I18n.loadFromDir(localesDir())
        I18n.setLanguage("en")
        // 主表里的词（桌面 en.json）
        assertEquals("AI Assistant", t("AI 助手"))
        // 只有安卓叠层才有的词
        assertEquals("Me", t("我的"))
        assertEquals("Leave blank to use", t("留空用"))
    }

    @Test
    fun chineseIsIdentityAndDoesNotLeakEnglish() {
        I18n.loadFromDir(localesDir())
        I18n.setLanguage("zh_CN")
        assertEquals("AI 助手", t("AI 助手"))
        assertEquals("我的", t("我的"))
        // zh_CN 与 en 之间不互相兜底：中文界面上不该冒出英文
        assertEquals("这句话不在任何词表里", t("这句话不在任何词表里"))
    }

    // ---------------------------------------------------------------- 回落

    @Test
    fun missingKeyFallsBackToChineseSource() {
        I18n.putMain("en", mapOf("有" to "yes"))
        I18n.setLanguage("en")
        assertEquals("yes", t("有"))
        assertEquals("没有这条", t("没有这条"))
        assertEquals("", t(""))
    }

    @Test
    fun emptyTranslationCountsAsMissing() {
        I18n.putMain("en", mapOf("键" to ""))
        I18n.setLanguage("en")
        assertEquals("键", t("键"))
    }

    // ---------------------------------------------------------------- 叠层

    @Test
    fun overlayWinsOverMainTable() {
        I18n.putMain("en", mapOf("键" to "main", "只在主表" to "main-only"))
        I18n.putOverlay("en", mapOf("键" to "overlay", "只在叠层" to "overlay-only", "空的" to ""))
        I18n.setLanguage("en")
        assertEquals("overlay", t("键"))
        assertEquals("main-only", t("只在主表"))
        assertEquals("overlay-only", t("只在叠层"))
        // 叠层里写了空串等于没写，继续往主表 / 中文回落
        assertEquals("空的", t("空的"))
    }

    @Test
    fun loadFromStreamsFillsBothLayers() {
        val main = """{"甲":"A"}""".byteInputStream()
        val overlay = """{"乙":"B"}""".byteInputStream()
        I18n.load("en", main, overlay)
        assertEquals("A", I18n.t("甲", "en"))
        assertEquals("B", I18n.t("乙", "en"))
        // 传 null 的那一层不动
        I18n.load("en", null, """{"乙":"B2"}""".byteInputStream())
        assertEquals("A", I18n.t("甲", "en"))
        assertEquals("B2", I18n.t("乙", "en"))
    }

    @Test
    fun badJsonBecomesEmptyTableNotACrash() {
        assertEquals(emptyMap<String, String>(), I18n.parse("{not json"))
        assertEquals(mapOf("a" to "b"), I18n.parse("""{"a":"b","":"skipped"}"""))
    }

    // ---------------------------------------------------------------- 切换

    @Test
    fun switchingLanguageNormalizesAndBumpsRevision() {
        I18n.loadFromDir(localesDir())
        val r0 = I18n.revision
        assertEquals("en", I18n.setLanguage("en"))
        assertEquals("en", I18n.language)
        assertEquals(r0 + 1, I18n.revision)
        // 同一门语言再设一次不算切换
        I18n.setLanguage("en")
        assertEquals(r0 + 1, I18n.revision)
        // 连字符、空白都收成表里的代码；不认识的退回默认
        assertEquals("zh_CN", I18n.setLanguage(" zh-CN "))
        assertEquals("zh_CN", I18n.setLanguage("fr"))
        assertEquals("zh_CN", I18n.setLanguage(null))
        assertEquals("zh_CN", I18n.setLanguage(""))
        assertEquals(I18n.DEFAULT_LANG, I18n.language)
    }

    @Test
    fun sameKeyChangesWithLanguage() {
        I18n.loadFromDir(localesDir())
        I18n.setLanguage("zh_CN")
        val zh = t("设置")
        I18n.setLanguage("en")
        val en = t("设置")
        assertEquals("设置", zh)
        assertNotEquals(zh, en)
        assertTrue(en.isNotBlank())
    }

    @Test
    fun fmtReplacesIndexedPlaceholders() {
        assertEquals("第 1 / 3 步", "第 {0} / {1} 步".fmt(1, 3))
        assertEquals("a  b", "{0} {2} {1}".fmt("a", "b", ""))
        assertEquals("x", "x".fmt())
        assertEquals("空", "{0}".fmt(null).ifEmpty { "空" })
    }

    // ---------------------------------------------------------------- 护栏

    /**
     * ui 下每一条 t("…") 的中文键，en 主表或 en 叠层里都得有非空译文。
     * 少了不会崩（回落中文），但英文界面上就会混进一句中文——所以当回归拦。
     */
    @Test
    fun everyUiKeyHasEnglishText() {
        I18n.loadFromDir(localesDir())
        val missing = ArrayList<String>()
        for (file in uiDir().walkTopDown().filter { it.isFile && it.extension == "kt" }) {
            val src = file.readText(Charsets.UTF_8)
            for (range in KtLiterals.literals(src)) {
                val lit = src.substring(range)
                if (!KtLiterals.wrappedByT(src, range.first) || lit.contains('$') || lit.startsWith("\"\"\"")) continue
                val key = KtLiterals.unescape(lit.substring(1, lit.length - 1))
                if (!KtLiterals.CJK.containsMatchIn(key)) continue
                if (I18n.t(key, "en") == key) missing.add("${file.name}: $key")
            }
        }
        assertEquals("这些 ui 词条在 en 主表和 en.android.json 叠层里都没有英文: $missing", emptyList<String>(), missing)
    }

    /** 叠层文件本身要是合法 JSON、键值都是字符串，且 zh_CN 叠层与 en 叠层键集一致。 */
    @Test
    fun overlayFilesAreWellFormedAndInSync() {
        val dir = localesDir()
        val en = JSONObject(File(dir, "en.android.json").readText(Charsets.UTF_8))
        val zh = JSONObject(File(dir, "zh_CN.android.json").readText(Charsets.UTF_8))
        assertEquals(en.keySet(), zh.keySet())
        for (key in en.keySet()) {
            assertTrue("en.android.json 里「$key」译文为空", en.getString(key).isNotBlank())
            assertEquals("zh_CN 叠层应当是恒等映射", key, zh.getString(key))
        }
    }

    /**
     * 护栏：ui 下的 .kt 里，含中文的字符串字面量必须是 `t(` 的直接参数（模板里的 `${…}` 表达式不算）。
     * 照 AiTest.noHardcodedSecretInMainSources 的写法用相对路径，从 android/ 目录跑。
     */
    @Test
    fun noUnwrappedChineseLiteralInUiSources() {
        val hits = ArrayList<String>()
        var scanned = 0
        for (file in uiDir().walkTopDown().filter { it.isFile && it.extension == "kt" }) {
            scanned++
            val src = file.readText(Charsets.UTF_8)
            for (range in KtLiterals.literals(src)) {
                val lit = src.substring(range)
                if (!KtLiterals.CJK.containsMatchIn(KtLiterals.stripTemplates(lit))) continue
                if (KtLiterals.wrappedByT(src, range.first)) continue
                val line = src.substring(0, range.first).count { it == '\n' } + 1
                hits.add("${file.name}:$line: ${lit.take(80)}")
            }
        }
        assertTrue("ui 目录下一个 .kt 都没扫到", scanned > 0)
        assertEquals("ui 下仍有未包 t() 的中文字面量 (${hits.size} 处): $hits", emptyList<String>(), hits)
    }
}

/**
 * 够用就好的 Kotlin 字面量扫描器：跳过 `//` 与 `/* */` 注释，认普通字符串、原始字符串、
 * 字符字面量，字符串里的 `${…}` 连同其中嵌套的字符串整段跳过。只给上面的护栏用。
 */
object KtLiterals {
    val CJK = Regex("[\\u3400-\\u9fff\\u3000-\\u303f\\uff00-\\uffef]")

    fun literals(src: String): List<IntRange> {
        val out = ArrayList<IntRange>()
        var i = 0
        val n = src.length
        while (i < n) {
            val c = src[i]
            when {
                src.startsWith("//", i) -> {
                    val j = src.indexOf('\n', i)
                    i = if (j < 0) n else j
                }
                src.startsWith("/*", i) -> {
                    val j = src.indexOf("*/", i + 2)
                    i = if (j < 0) n else j + 2
                }
                src.startsWith("\"\"\"", i) -> {
                    val j = src.indexOf("\"\"\"", i + 3)
                    val end = if (j < 0) n else j + 3
                    out.add(i until end)
                    i = end
                }
                c == '"' -> {
                    val end = skipString(src, i)
                    out.add(i until end)
                    i = end
                }
                c == '\'' -> {
                    var j = i + 1
                    while (j < n && src[j] != '\'') {
                        if (src[j] == '\\') j++
                        j++
                    }
                    i = j + 1
                }
                else -> i++
            }
        }
        return out
    }

    /** 从开头的引号走到收尾引号之后，返回收尾引号后一位的下标。 */
    private fun skipString(src: String, start: Int): Int {
        val n = src.length
        var j = start + 1
        while (j < n) {
            val ch = src[j]
            when {
                ch == '\\' -> j += 2
                src.startsWith("\${", j) -> j = skipTemplate(src, j)
                ch == '"' -> return j + 1
                else -> j++
            }
        }
        return n
    }

    /** `${` 起步，配对到对应的 `}`，中间嵌套的字符串整个跳过；返回 `}` 后一位。 */
    private fun skipTemplate(src: String, start: Int): Int {
        val n = src.length
        var k = start + 2
        var depth = 1
        while (k < n && depth > 0) {
            when (src[k]) {
                '{' -> depth++
                '}' -> depth--
                '"' -> k = skipString(src, k) - 1
            }
            k++
        }
        return k
    }

    /** 去掉字面量里的 `${…}` 段，剩下的才是这一条自己的文字。 */
    fun stripTemplates(lit: String): String {
        val sb = StringBuilder()
        var i = 0
        val n = lit.length
        while (i < n) {
            when {
                lit[i] == '\\' -> {
                    sb.append(lit, i, minOf(n, i + 2))
                    i += 2
                }
                lit.startsWith("\${", i) -> i = skipTemplate(lit, i)
                else -> sb.append(lit[i++])
            }
        }
        return sb.toString()
    }

    /** 字面量前面紧挨着的是不是 `t(` / `I18n.t(`（允许中间有空白，且 `t` 前不能是标识符或点）。 */
    fun wrappedByT(src: String, start: Int): Boolean {
        val pre = src.substring(0, start).trimEnd()
        if (pre.endsWith("I18n.t(")) return true
        if (!pre.endsWith("t(")) return false
        val before = pre.getOrNull(pre.length - 3) ?: return true
        return !(before.isLetterOrDigit() || before == '_' || before == '.')
    }

    fun unescape(body: String): String = body
        .replace("\\\"", "\"")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\$", "$")
        .replace("\\\\", "\\")
}
