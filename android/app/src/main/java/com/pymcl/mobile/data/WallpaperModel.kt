package com.pymcl.mobile.data

import kotlin.random.Random

/**
 * 壁纸的纯逻辑层：清单、轮播、撤销栈、观感参数。
 *
 * 对齐桌面 app/background.py 的 WallpaperPlaylist 与 mclauncher/config.py 的
 * background_history / push_background_history。
 *
 * 这个文件不引任何 Android 类型、也不引 org.json——落盘归 [WallpaperStore]，
 * 画面归 ui/WallpaperLayer.kt。这样轮播与撤销栈能在普通 JVM 单测里直接跑。
 */

enum class WallpaperKind { IMAGE, VIDEO }

/**
 * 一张壁纸的引用。[uri] 从哪来不归这一层管（本地路径、SAF content://、以后的
 * 文件夹轮播都只是一串字符串），渲染层拿到什么解不开就回退底色。
 */
data class WallpaperRef(
    val uri: String,
    val kind: WallpaperKind = WallpaperKind.IMAGE,
)

/** 观感三档，都是 0..100 的整数，跟桌面设置页那三个滑杆一一对应。 */
data class WallpaperLook(
    /** 0 = 原图。 */
    val blur: Int = 0,
    /** 盖在壁纸上的主题底色浓度，0 = 不盖。 */
    val scrim: Int = 0,
    /** 顶栏 / 底栏的不透明度，100 = 纯色，调低壁纸才透得出来。 */
    val panelAlpha: Int = 100,
) {
    fun clamped(): WallpaperLook = WallpaperLook(
        blur = blur.coerceIn(0, 100),
        scrim = scrim.coerceIn(0, 100),
        panelAlpha = panelAlpha.coerceIn(0, 100),
    )

    companion object {
        val DEFAULT = WallpaperLook()
    }
}

/**
 * 壁纸清单与播放位置。
 *
 * [order] 是 items 下标的一个排列，[cursor] 指向 order 里的位置——顺序播时
 * order 就是 0..n-1，随机播时是洗好的一轮。把「一轮的排列」存下来而不是每次
 * 现随机，是为了做到一轮之内不重复：桌面那边是同一个道理。
 */
data class WallpaperPlaylist(
    val items: List<WallpaperRef> = emptyList(),
    val shuffle: Boolean = false,
    /** 自动轮播间隔，0 = 不自动翻。 */
    val intervalMinutes: Int = 0,
    val order: List<Int> = emptyList(),
    val cursor: Int = 0,
) {
    val isEmpty: Boolean get() = items.isEmpty()

    /** 只有多于一张且设了间隔才谈得上自动轮播。 */
    val rotates: Boolean get() = intervalMinutes > 0 && items.size > 1

    fun current(): WallpaperRef? {
        val slot = order.getOrNull(cursor) ?: return null
        return items.getOrNull(slot)
    }

    /**
     * 把 order / cursor 校正到与 items、shuffle 一致。
     * items 换过、shuffle 开关翻过之后一定要过一遍，否则 cursor 会指到空处。
     */
    fun normalized(random: Random = Random.Default): WallpaperPlaylist {
        if (items.isEmpty()) return copy(order = emptyList(), cursor = 0)
        val fixed = if (orderIsValid()) order else freshOrder(random, avoidFirst = -1)
        return copy(order = fixed, cursor = cursor.coerceIn(0, fixed.lastIndex))
    }

    /**
     * 往前一张。[exists] 用来跳过已经不在磁盘上的那些，一轮之内最多跳
     * items.size 次；全都不存在时照样返回一个合法位置，由渲染层回退底色，
     * 这一层不负责报错。
     */
    fun advanced(
        random: Random = Random.Default,
        exists: (WallpaperRef) -> Boolean = { true },
    ): WallpaperPlaylist {
        val base = normalized(random)
        if (base.items.isEmpty()) return base
        var cur = base
        repeat(base.items.size) {
            cur = cur.stepped(random)
            val ref = cur.current()
            if (ref != null && exists(ref)) return cur
        }
        return cur
    }

    /** 清单里第一张还在的图；一张都不在返回 null。 */
    fun firstAvailable(exists: (WallpaperRef) -> Boolean): WallpaperRef? =
        order.asSequence()
            .mapNotNull { items.getOrNull(it) }
            .firstOrNull(exists)

    fun withItems(items: List<WallpaperRef>, random: Random = Random.Default): WallpaperPlaylist =
        copy(items = items, order = emptyList(), cursor = 0).normalized(random)

    fun withShuffle(shuffle: Boolean, random: Random = Random.Default): WallpaperPlaylist =
        copy(shuffle = shuffle, order = emptyList(), cursor = 0).normalized(random)

    private fun orderIsValid(): Boolean {
        if (order.size != items.size) return false
        if (!shuffle) return order == items.indices.toList()
        return order.toHashSet() == items.indices.toHashSet()
    }

    private fun stepped(random: Random): WallpaperPlaylist {
        if (cursor < order.lastIndex) return copy(cursor = cursor + 1)
        val last = order.lastOrNull() ?: -1
        return copy(order = freshOrder(random, avoidFirst = last), cursor = 0)
    }

    private fun freshOrder(random: Random, avoidFirst: Int): List<Int> {
        val base = items.indices.toList()
        if (!shuffle || base.size <= 1) return base
        var picked = base.shuffled(random)
        // 一轮播完换排列时，新一轮的头一张不能又是刚播完的那张：那样用户看到
        // 的是同一张连着出现两次，随机在他眼里就是坏的。
        var guard = 0
        while (picked.first() == avoidFirst && guard < RESHUFFLE_TRIES) {
            picked = base.shuffled(random)
            guard++
        }
        if (picked.first() == avoidFirst) picked = picked.drop(1) + picked.first()
        return picked
    }

    private companion object {
        const val RESHUFFLE_TRIES = 8
    }
}

/** 撤销栈里的一格：能还原的就是清单与观感这两样。 */
data class WallpaperSnapshot(
    val playlist: WallpaperPlaylist,
    val look: WallpaperLook,
)

/** 定长撤销栈，后进先出，超出 [cap] 丢最旧的那一格。 */
data class WallpaperHistory(
    val entries: List<WallpaperSnapshot> = emptyList(),
    val cap: Int = DEFAULT_CAP,
) {
    val canUndo: Boolean get() = entries.isNotEmpty()

    fun pushed(snapshot: WallpaperSnapshot): WallpaperHistory {
        if (cap <= 0) return copy(entries = emptyList())
        val next = entries + snapshot
        return copy(entries = if (next.size <= cap) next else next.takeLast(cap))
    }

    /** 弹出栈顶；空栈返回原样与 null。 */
    fun popped(): Pair<WallpaperHistory, WallpaperSnapshot?> {
        val top = entries.lastOrNull() ?: return this to null
        return copy(entries = entries.dropLast(1)) to top
    }

    companion object {
        const val DEFAULT_CAP = 10
    }
}

/** 壁纸的完整状态。UI 只跟这一个对象打交道。 */
data class WallpaperState(
    val playlist: WallpaperPlaylist = WallpaperPlaylist(),
    val look: WallpaperLook = WallpaperLook.DEFAULT,
    val history: WallpaperHistory = WallpaperHistory(),
) {
    fun snapshot(): WallpaperSnapshot = WallpaperSnapshot(playlist, look)

    /** 用户自己动的改动（换清单、调滑杆、翻开随机）：记一笔，之后退得回来。 */
    fun edited(
        playlist: WallpaperPlaylist = this.playlist,
        look: WallpaperLook = this.look,
    ): WallpaperState = WallpaperState(
        playlist = playlist,
        look = look.clamped(),
        history = history.pushed(snapshot()),
    )

    /** 用户点「下一张」：算一次改动，记。 */
    fun advancedByUser(
        random: Random = Random.Default,
        exists: (WallpaperRef) -> Boolean = { true },
    ): WallpaperState = edited(playlist = playlist.advanced(random, exists))

    /**
     * 定时器自己翻的那一下：**不记**。十分钟翻一张，记进去几轮就把撤销栈
     * 冲光了，用户真正想退回的那一步反而没了。
     */
    fun rotated(
        random: Random = Random.Default,
        exists: (WallpaperRef) -> Boolean = { true },
    ): WallpaperState = copy(playlist = playlist.advanced(random, exists))

    /** 退回上一步；栈空时原样返回。 */
    fun undone(): WallpaperState {
        val (rest, top) = history.popped()
        if (top == null) return this
        return WallpaperState(playlist = top.playlist, look = top.look, history = rest)
    }

    /** 清回纯色，但这一步本身也能撤销回来。 */
    fun clearedToBaseColor(): WallpaperState = edited(
        playlist = WallpaperPlaylist(shuffle = playlist.shuffle, intervalMinutes = playlist.intervalMinutes),
    )

    fun normalized(random: Random = Random.Default): WallpaperState =
        copy(playlist = playlist.normalized(random), look = look.clamped())
}

/**
 * [WallpaperState] ↔ 普通 Map 的编解码。
 *
 * 停在 Map 这一层是故意的：org.json 在单测里是另一份实现，把它挡在
 * [WallpaperStore] 里，这份编解码就能跟轮播逻辑一起在纯 JVM 下测。
 */
object WallpaperCodec {
    const val KEY_ITEMS = "items"
    const val KEY_URI = "uri"
    const val KEY_KIND = "kind"
    const val KEY_SHUFFLE = "shuffle"
    const val KEY_INTERVAL = "interval_minutes"
    const val KEY_ORDER = "order"
    const val KEY_CURSOR = "cursor"
    const val KEY_BLUR = "blur"
    const val KEY_SCRIM = "scrim"
    const val KEY_PANEL_ALPHA = "panel_alpha"
    const val KEY_HISTORY = "history"
    const val KEY_HISTORY_CAP = "history_cap"
    const val KEY_PLAYLIST = "playlist"
    const val KEY_LOOK = "look"

    fun toMap(state: WallpaperState): Map<String, Any?> = mapOf(
        KEY_PLAYLIST to playlistToMap(state.playlist),
        KEY_LOOK to lookToMap(state.look),
        KEY_HISTORY_CAP to state.history.cap,
        KEY_HISTORY to state.history.entries.map {
            mapOf(KEY_PLAYLIST to playlistToMap(it.playlist), KEY_LOOK to lookToMap(it.look))
        },
    )

    fun fromMap(raw: Map<*, *>?): WallpaperState {
        val top = asMap(raw) ?: return WallpaperState()
        val cap = intOf(top[KEY_HISTORY_CAP], WallpaperHistory.DEFAULT_CAP)
        val entries = asList(top[KEY_HISTORY]).mapNotNull { asMap(it) }.map {
            WallpaperSnapshot(
                playlist = playlistFromMap(asMap(it[KEY_PLAYLIST])),
                look = lookFromMap(asMap(it[KEY_LOOK])),
            )
        }
        return WallpaperState(
            playlist = playlistFromMap(asMap(top[KEY_PLAYLIST])),
            look = lookFromMap(asMap(top[KEY_LOOK])),
            history = WallpaperHistory(entries = entries, cap = cap),
        ).normalized()
    }

    private fun playlistToMap(p: WallpaperPlaylist): Map<String, Any?> = mapOf(
        KEY_ITEMS to p.items.map { mapOf(KEY_URI to it.uri, KEY_KIND to it.kind.name) },
        KEY_SHUFFLE to p.shuffle,
        KEY_INTERVAL to p.intervalMinutes,
        KEY_ORDER to p.order,
        KEY_CURSOR to p.cursor,
    )

    private fun playlistFromMap(raw: Map<String, Any?>?): WallpaperPlaylist {
        if (raw == null) return WallpaperPlaylist()
        val items = asList(raw[KEY_ITEMS]).mapNotNull { entry ->
            val m = asMap(entry) ?: return@mapNotNull null
            val uri = m[KEY_URI]?.toString().orEmpty()
            if (uri.isBlank()) return@mapNotNull null
            WallpaperRef(uri, kindOf(m[KEY_KIND]))
        }
        val order = asList(raw[KEY_ORDER]).mapNotNull { intOfOrNull(it) }
        return WallpaperPlaylist(
            items = items,
            shuffle = raw[KEY_SHUFFLE] == true || raw[KEY_SHUFFLE]?.toString() == "true",
            intervalMinutes = intOf(raw[KEY_INTERVAL], 0),
            order = order,
            cursor = intOf(raw[KEY_CURSOR], 0),
        )
    }

    private fun lookToMap(l: WallpaperLook): Map<String, Any?> = mapOf(
        KEY_BLUR to l.blur,
        KEY_SCRIM to l.scrim,
        KEY_PANEL_ALPHA to l.panelAlpha,
    )

    private fun lookFromMap(raw: Map<String, Any?>?): WallpaperLook {
        if (raw == null) return WallpaperLook.DEFAULT
        return WallpaperLook(
            blur = intOf(raw[KEY_BLUR], 0),
            scrim = intOf(raw[KEY_SCRIM], 0),
            panelAlpha = intOf(raw[KEY_PANEL_ALPHA], 100),
        ).clamped()
    }

    private fun kindOf(raw: Any?): WallpaperKind =
        if (WallpaperKind.VIDEO.name.equals(raw?.toString(), true)) WallpaperKind.VIDEO else WallpaperKind.IMAGE

    /**
     * 统一收成 `Map<String, Any?>`。星投影的 `Map<*, *>` 不能直接按键取值，
     * 而解析出来的 JSON 键本来就都是字符串，在入口处转一次最省事。
     */
    private fun asMap(raw: Any?): Map<String, Any?>? {
        val m = raw as? Map<*, *> ?: return null
        return m.entries.associate { (k, v) -> k.toString() to v }
    }

    private fun asList(raw: Any?): List<*> = raw as? List<*> ?: emptyList<Any?>()

    private fun intOfOrNull(raw: Any?): Int? = when (raw) {
        is Number -> raw.toInt()
        is String -> raw.toIntOrNull()
        else -> null
    }

    private fun intOf(raw: Any?, fallback: Int): Int = intOfOrNull(raw) ?: fallback
}
