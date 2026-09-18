package com.pymcl.mobile

import com.pymcl.mobile.data.HelpContent
import com.pymcl.mobile.data.I18n
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * 常见问题 / 帮助库（对齐 `help_articles` / `help_article`）。
 *
 * 核心一条是**逐条对照桌面**：把 `mclauncher/help_content.py` 里 `ARTICLES` 的 id / title / body
 * 解析出来，跟 [HelpContent.ARTICLES] 一一比对——两边谁改了文章，这条就红，逼着先改 Python 那份再同步。
 * 照 AiTest.noHardcodedSecretInMainSources 的写法用相对路径，从 android/ 目录跑（app/、仓库根也兜一下）。
 */
class HelpContentTest {

    private fun firstFile(vararg candidates: String): File? =
        candidates.map { File(it) }.firstOrNull { it.isFile }

    private fun firstDir(vararg candidates: String): File? =
        candidates.map { File(it) }.firstOrNull { it.isDirectory }

    private fun desktopModule(): File {
        val file = firstFile(
            "../mclauncher/help_content.py",
            "../../mclauncher/help_content.py",
            "mclauncher/help_content.py",
        )
        assertTrue("找不到 mclauncher/help_content.py，没法跟桌面对照", file != null)
        return file!!
    }

    private fun localesDir(): File {
        val dir = firstDir("src/main/assets/locales", "app/src/main/assets/locales", "android/app/src/main/assets/locales")
        assertTrue("找不到 assets/locales", dir != null)
        return dir!!
    }

    @After
    fun restore() {
        I18n.reset()
    }

    // ---------------------------------------------------------------- 与桌面逐条对照

    @Test
    fun articlesMatchDesktopModuleOneToOne() {
        val desktop = PyArticles.parse(desktopModule().readText(Charsets.UTF_8))
        assertTrue("桌面 ARTICLES 解析出来是空的，解析器坏了", desktop.isNotEmpty())
        assertEquals("文章条数两边不一致", desktop.size, HelpContent.ARTICLES.size)
        for ((i, expected) in desktop.withIndex()) {
            val actual = HelpContent.ARTICLES[i]
            assertEquals("第 ${i + 1} 篇 id", expected.id, actual.id)
            assertEquals("「${expected.id}」标题", expected.title, actual.title)
            assertEquals("「${expected.id}」正文", expected.body, actual.body)
        }
    }

    @Test
    fun idsAreUniqueAndNonBlank() {
        val ids = HelpContent.ARTICLES.map { it.id }
        assertEquals(ids.size, ids.toSet().size)
        assertTrue(ids.all { it.isNotBlank() && it.trim() == it })
        assertTrue(HelpContent.ARTICLES.all { it.title.isNotBlank() && it.body.isNotBlank() })
    }

    // ---------------------------------------------------------------- list / get / search

    @Test
    fun listGivesIdAndTitleOnlyInOrder() {
        val rows = HelpContent.list()
        assertEquals(HelpContent.ARTICLES.size, rows.size)
        for ((i, row) in rows.withIndex()) {
            assertEquals(HelpContent.ARTICLES[i].id, row.first)
            assertEquals(HelpContent.ARTICLES[i].title, row.second)
        }
    }

    @Test
    fun getTrimsAndReturnsNullForUnknown() {
        val java = HelpContent.get("java")
        assertEquals("Java 怎么选", java?.title)
        assertEquals(java, HelpContent.get("  java \n"))
        assertNull(HelpContent.get("nope"))
        assertNull(HelpContent.get(""))
        assertNull(HelpContent.get(null))
        // 对齐桌面：按 id 精确匹配，不认标题
        assertNull(HelpContent.get("Java 怎么选"))
    }

    @Test
    fun searchEmptyGivesAllAndMatchesCaseInsensitiveSubstring() {
        assertEquals(HelpContent.ARTICLES, HelpContent.search(""))
        assertEquals(HelpContent.ARTICLES, HelpContent.search("   "))
        // 只有「陶瓦联机」这篇的标题 / 正文里有「陶瓦」
        assertEquals(listOf("multiplayer"), HelpContent.search("陶瓦").map { it.id })
        // 大小写不敏感 + 正文也算：Java 那篇标题里有，启动失败那篇正文里有「下载合适 Java」
        val java = HelpContent.search("JAVA").map { it.id }
        assertTrue(java.contains("java"))
        assertTrue(java.contains("launch-fail"))
        assertEquals(HelpContent.search("java"), HelpContent.search(" Java "))
        assertEquals(emptyList<Any>(), HelpContent.search("这个词肯定不在任何一篇里xyz"))
    }

    @Test
    fun matchesAgreesWithSearch() {
        for (q in listOf("", "java", "存档", "modrinth", "xyz-不存在")) {
            val viaSearch = HelpContent.search(q).map { it.id }
            val viaMatches = HelpContent.ARTICLES.filter { HelpContent.matches(it, q.trim().lowercase()) }.map { it.id }
            assertEquals("query=$q", viaSearch, viaMatches)
        }
    }

    // ---------------------------------------------------------------- 词表

    /** 文章展示时过 t()：每篇标题与正文在 en 主表或 en.android.json 里都要有英文，否则英文界面上整篇是中文。 */
    @Test
    fun everyArticleHasEnglishTitleAndBody() {
        I18n.loadFromDir(localesDir())
        for (a in HelpContent.ARTICLES) {
            assertNotEquals("「${a.id}」标题没有英文", a.title, I18n.t(a.title, "en"))
            assertNotEquals("「${a.id}」正文没有英文", a.body, I18n.t(a.body, "en"))
            // 中文界面原样
            assertEquals(a.title, I18n.t(a.title, "zh_CN"))
            assertEquals(a.body, I18n.t(a.body, "zh_CN"))
        }
    }
}

/**
 * 够用就好的 `help_content.py` 读取器：只看 `ARTICLES = [` 到 `def list_articles` 之间，
 * 按顺序收集字符串字面量，再按 `"id"` / `"title"` / `"body"` 这三个键归位；
 * `body` 那一段是括号里相邻字面量的隐式拼接，照 Python 的规则直接连起来。
 */
object PyArticles {
    data class Article(val id: String, val title: String, val body: String)

    fun parse(src: String): List<Article> {
        val start = src.indexOf("ARTICLES")
        val end = src.indexOf("def list_articles")
        require(start >= 0 && end > start) { "help_content.py 里找不到 ARTICLES 块" }
        val lits = literals(src.substring(start, end))
        val out = ArrayList<Article>()
        var id: String? = null
        var title: String? = null
        var body: StringBuilder? = null
        fun flush() {
            if (id != null) out.add(Article(id!!, title ?: "", body?.toString() ?: ""))
            id = null; title = null; body = null
        }
        var i = 0
        while (i < lits.size) {
            when (lits[i]) {
                "id" -> { flush(); id = lits.getOrNull(i + 1); i += 2 }
                "title" -> { title = lits.getOrNull(i + 1); i += 2 }
                "body" -> { body = StringBuilder(); i++ }
                else -> { body?.append(lits[i]); i++ }
            }
        }
        flush()
        return out
    }

    /** 依次取出单引号 / 双引号字面量（处理 \n \t \\ \" \' 转义），跳过 `#` 注释。 */
    fun literals(src: String): List<String> {
        val out = ArrayList<String>()
        var i = 0
        val n = src.length
        while (i < n) {
            val c = src[i]
            when {
                c == '#' -> {
                    val j = src.indexOf('\n', i)
                    i = if (j < 0) n else j
                }
                c == '"' || c == '\'' -> {
                    val sb = StringBuilder()
                    var j = i + 1
                    while (j < n && src[j] != c) {
                        if (src[j] == '\\' && j + 1 < n) {
                            j++
                            when (src[j]) {
                                'n' -> sb.append('\n')
                                't' -> sb.append('\t')
                                '\\' -> sb.append('\\')
                                '"' -> sb.append('"')
                                '\'' -> sb.append('\'')
                                else -> sb.append('\\').append(src[j])
                            }
                        } else {
                            sb.append(src[j])
                        }
                        j++
                    }
                    out.add(sb.toString())
                    i = j + 1
                }
                else -> i++
            }
        }
        return out
    }
}
