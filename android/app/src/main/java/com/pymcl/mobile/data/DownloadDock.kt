package com.pymcl.mobile.data

import com.pymcl.mobile.model.TaskInfo

/**
 * 悬浮下载坞的纯逻辑：这一刻该不该露面、跟的是哪一条任务。
 *
 * 口径对齐桌面 `app/main_window.py::_place_download_dock`——有在跑的下载才出现，
 * 并且设置 / 实例 / 任务 / 反馈这四页上自动收起：那几页要么本来就在讲下载进度，
 * 要么底部另有操作区，再压一条坞上去只会挡住内容。
 *
 * 页面 key 照抄桌面侧栏那一套名字，手机上的底栏格子与「我的」二级页都往这套上收，
 * 两端的隐藏页集合才能是同一份。
 */
object DownloadDock {
    const val PAGE_LAUNCH = "launch"
    const val PAGE_INSTANCE = "instance"
    const val PAGE_MULTIPLAYER = "multiplayer"
    const val PAGE_DOWNLOAD = "download"
    const val PAGE_TASKS = "tasks"
    const val PAGE_AI = "ai"
    const val PAGE_MINE = "mine"
    const val PAGE_SETTINGS = "settings"
    const val PAGE_THEME = "theme"
    const val PAGE_LAYOUT = "layout"
    const val PAGE_ACCOUNT = "account"
    const val PAGE_JAVA = "java"
    const val PAGE_MODS = "mods"
    const val PAGE_FEEDBACK = "feedback"

    /** 桌面 `_place_download_dock` 里的 hide_on，一个不多一个不少。 */
    val HIDDEN_PAGES = setOf(PAGE_SETTINGS, PAGE_INSTANCE, PAGE_TASKS, PAGE_FEEDBACK)

    fun hidesDock(pageKey: String): Boolean = pageKey in HIDDEN_PAGES

    fun visible(activeCount: Int, pageKey: String): Boolean = activeCount > 0 && !hidesDock(pageKey)

    /** 坞上跟着显示的那条：最新一条还没做完的下载任务（任务是往表头插的）。 */
    fun current(tasks: List<TaskInfo>): TaskInfo? =
        tasks.firstOrNull { !it.done && TaskCenter.isDownloadTitle(it.title) }
}
