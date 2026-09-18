package com.pymcl.mobile.data

/** 一篇常见问题。三个字段与桌面 `help_content.ARTICLES` 的 id / title / body 逐条一致。 */
data class HelpArticle(val id: String, val title: String, val body: String)

/**
 * 轻量帮助 / 常见问题，移植自 `mclauncher/help_content.py`（对齐 PCL「能查到答案」的最低体验，
 * 不做独立帮助站）。文章内容是内容不是界面文案，原样保留中文；展示时由 UI 层过一遍 t()，
 * 词表里有译文就换、没有就照中文出。**改文章请先改 Python 那份**，单测会拿两边逐条比对。
 */
object HelpContent {
    val ARTICLES: List<HelpArticle> = listOf(
        HelpArticle(
            id = "launch-fail",
            title = "启动失败 / 闪退怎么办",
            body = "1. 看崩溃弹窗里的「建议操作」，能禁用嫌疑 Mod、提高内存、下载合适 Java、修复版本文件。\n" +
                "2. 启动页点启动前会做预检：磁盘不足、Mods 被解压成文件夹、Java 过旧会直接拦住。\n" +
                "3. 仍不行：到「反馈」页把错误报告发给开发者（同意上传后才会发送）。",
        ),
        HelpArticle(
            id = "java",
            title = "Java 怎么选",
            body = "启动时默认自动匹配。也可在「下载 → Java」按版本下载：\n" +
                "· Java 8：1.16 及更早\n" +
                "· Java 17：1.18 – 1.20.4\n" +
                "· Java 21：1.20.5+\n" +
                "发行版推荐 Adoptium；也可用 Zulu / Microsoft。",
        ),
        HelpArticle(
            id = "mods",
            title = "模组 / 整合包安装",
            body = "到「下载」页搜索 Modrinth / CurseForge（国内走镜像）。\n" +
                "原版版本不会加载 mods 文件夹里的 jar，需要先装 Fabric / Forge / Quilt / NeoForge。\n" +
                "不要把 .jar 解压成文件夹，否则会预检失败。",
        ),
        HelpArticle(
            id = "account",
            title = "账号与正版登录",
            body = "支持离线、微软设备码、皮肤站（Yggdrasil）、统一通行证（Nide8）。\n" +
                "微软登录请按弹窗打开链接并输入代码；关掉窗口会取消后台轮询。",
        ),
        HelpArticle(
            id = "multiplayer",
            title = "陶瓦联机",
            body = "「联机」页可开房 / 加入。房间号形如 U/XXXX-XXXX-XXXX-XXXX。\n" +
                "双方都要用兼容的陶瓦内核；防火墙提示按页面指引放行。",
        ),
        HelpArticle(
            id = "isolation",
            title = "版本隔离与存档",
            body = "每个实例是独立的 .minecraft。版本设置里可选隔离档位。\n" +
                "存档可在版本相关对话框里备份 / 还原；删世界前建议先备份。",
        ),
    )

    /** 对齐 `list_articles()`：只给 id 与标题。 */
    fun list(): List<Pair<String, String>> = ARTICLES.map { it.id to it.title }

    /** 对齐 `get_article()`：按 id 找，两边都会 trim；找不到给 null。 */
    fun get(id: String?): HelpArticle? {
        val key = (id ?: "").trim()
        return ARTICLES.firstOrNull { it.id == key }
    }

    /**
     * 对齐 `search_articles()`：空查询回全部；否则在「标题 + 换行 + 正文」里做不分大小写的子串匹配。
     * 匹配的是原文，不是译文——跟桌面同一份结果，切了语言也一样。
     */
    fun search(query: String = ""): List<HelpArticle> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return ARTICLES
        return ARTICLES.filter { matches(it, q) }
    }

    /**
     * 单篇匹配，跟 [search] 同一口径：`query` 已经 trim + 小写。UI 层在英文界面下还会拿译文
     * 再试一遍——那不是桌面有的行为，所以留在 UI 里，不放进这个对齐口径的函数。
     */
    fun matches(article: HelpArticle, query: String): Boolean =
        query.isEmpty() || (article.title + "\n" + article.body).lowercase().contains(query)
}
