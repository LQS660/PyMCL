package com.pymcl.mobile.data

import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** 一次更新检查的结论，字段名与桌面 `updater.check()` 返回的字典一一对应。 */
data class UpdateInfo(
    val ok: Boolean,
    val current: String,
    val latest: String,
    val hasUpdate: Boolean,
    /** 与桌面同一句中文（`发现 x` / `已是最新版本` / `更新清单缺少有效 SHA-256…` / `检查更新失败: …`）。 */
    val message: String,
    val notes: String = "",
    val url: String = "",
    val sha256: String = "",
    /** 失败时的原始错误，UI 层拼译文用；成功为空。 */
    val error: String = "",
) {
    /** 这四种之一，UI 层按它挑译文。 */
    val kind: UpdateKind
        get() = when {
            error.isNotEmpty() -> UpdateKind.FAILED
            hasUpdate -> UpdateKind.UPDATE
            !ok -> UpdateKind.UNSIGNED
            else -> UpdateKind.UP_TO_DATE
        }
}

enum class UpdateKind { UP_TO_DATE, UPDATE, UNSIGNED, FAILED }

/**
 * 启动器自更新的「查清单」这一半，端点与版本比较规则照 `mclauncher/updater.py`：
 * 清单地址取 `update_url`（空则 [DEFAULT_URL]），12 秒超时；版本号按 `.`/`-` 切段、每段只取数字、
 * 补到 3 段、最多比 4 段；有新版但清单没给合法 SHA-256 就**拒绝**当成有更新（自动更新是一道
 * 代码执行边界，桌面那边的注释原话）。
 *
 * 安卓不走桥，也不下包：手机上换 APK 归系统安装器，这里只做「有没有新版、在哪下」。
 * 网络失败不抛，回一个 `ok=false` 的 [UpdateInfo]，界面照常起来。
 */
object UpdateCheck {
    const val DEFAULT_URL = "https://pymcl.dev/update.json"
    const val TIMEOUT_SEC = 12L

    private val SHA256 = Regex("^[0-9a-fA-F]{64}$")
    private val startupDone = AtomicBoolean(false)
    private val listeners = CopyOnWriteArraySet<(UpdateInfo) -> Unit>()

    /** 最近一次结论（含失败），设置页直接展示；还没查过为 null。 */
    @Volatile
    var last: UpdateInfo? = null
        private set

    @Volatile
    var lastCheckedAt: Long = 0L
        private set

    /**
     * 每次 [check] 出结论都会叫一遍（在查的那条线程上）。启动时那一次是后台跑的，
     * 设置页若正开着，靠这个把结果行刷出来，不用它自己去轮询 [last]。
     */
    fun addListener(listener: (UpdateInfo) -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: (UpdateInfo) -> Unit) {
        listeners.remove(listener)
    }

    /** 对齐 `_parse`：`3.2.0-beta1` → [3, 2, 0, 1]，`v2` → [2, 0, 0]，空 → [0, 0, 0]。 */
    fun parseVersion(ver: String?): List<Int> {
        val bits = ArrayList<Int>()
        for (part in (ver ?: "").ifEmpty { "0" }.replace('-', '.').split('.')) {
            val digits = part.filter { it.isDigit() }
            bits.add(digits.toIntOrNull() ?: digits.take(9).toIntOrNull() ?: 0)
        }
        while (bits.size < 3) bits.add(0)
        return bits.take(4)
    }

    /** Python 元组比较：逐位比，前缀相同则更长的更大。 */
    fun compareVersions(a: String?, b: String?): Int {
        val x = parseVersion(a)
        val y = parseVersion(b)
        for (i in 0 until minOf(x.size, y.size)) {
            if (x[i] != y[i]) return x[i].compareTo(y[i])
        }
        return x.size.compareTo(y.size)
    }

    fun newer(remote: String?, local: String = Paths.APP_VERSION): Boolean = compareVersions(remote, local) > 0

    fun validSha256(value: String?): Boolean = SHA256.matches((value ?: "").trim())

    fun manifestUrl(): String = Settings.str(SettingsKeys.UPDATE_URL).trim().ifEmpty { DEFAULT_URL }

    /** 对齐 `check()` 拿到清单之后的那段判定；纯函数，单测直接喂 JSON。 */
    fun evaluate(data: JSONObject?, current: String = Paths.APP_VERSION): UpdateInfo {
        val obj = data ?: JSONObject()
        val latest = obj.optString("version").ifEmpty { obj.optString("latest") }
        val has = latest.isNotEmpty() && newer(latest, current)
        val sha256 = obj.optString("sha256").trim().lowercase()
        val signed = has && validSha256(sha256)
        val integrityError = has && !signed
        return UpdateInfo(
            ok = !integrityError,
            current = current,
            latest = latest.ifEmpty { current },
            hasUpdate = signed,
            message = when {
                integrityError -> "更新清单缺少有效 SHA-256，已拒绝自动更新"
                has -> "发现 $latest"
                else -> "已是最新版本"
            },
            notes = obj.optString("notes").ifEmpty { obj.optString("changelog") },
            url = obj.optString("url").ifEmpty { obj.optString("download") },
            sha256 = sha256,
        )
    }

    /** 对齐 `check()` 的失败分支。 */
    fun failure(error: Throwable, current: String = Paths.APP_VERSION): UpdateInfo {
        val reason = error.message?.takeIf { it.isNotBlank() } ?: error.javaClass.simpleName
        return UpdateInfo(
            ok = false,
            current = current,
            latest = current,
            hasUpdate = false,
            message = "检查更新失败: $reason",
            error = reason,
        )
    }

    /**
     * 查一次。`fetch` 可替换，单测里塞一个假的；默认走 [fetchText]（12 秒超时的 OkHttp）。
     * 无论成败都记进 [last]，绝不抛出。
     */
    fun check(
        url: String = manifestUrl(),
        current: String = Paths.APP_VERSION,
        fetch: (String) -> String = ::fetchText,
    ): UpdateInfo {
        val info = try {
            val body = fetch(url)
            evaluate(JSONObject(body), current)
        } catch (e: Exception) {
            failure(e, current)
        }
        last = info
        lastCheckedAt = System.currentTimeMillis()
        for (listener in listeners) {
            try {
                listener(info)
            } catch (_: Exception) {
                // 监听者自己的问题不该把检查这条线拖死
            }
        }
        return info
    }

    /**
     * 启动时那一次：`auto_check_update` 关着就不查（回 null）；整个进程只查一次，
     * 之后再调直接给上次结果。对齐桌面 `main_window._boot_extras`：开关关着直接 return，
     * 失败静默（这里是记进 [last]，不弹任何东西）。
     */
    fun checkOnStartup(
        enabled: Boolean = Settings.bool(SettingsKeys.AUTO_CHECK_UPDATE, true),
        url: String = manifestUrl(),
        current: String = Paths.APP_VERSION,
        fetch: (String) -> String = ::fetchText,
    ): UpdateInfo? {
        if (!enabled) return null
        if (startupDone.getAndSet(true)) return last
        return check(url, current, fetch)
    }

    /**
     * [checkOnStartup] 的后台版：`Application.onCreate` 里调，起一条守护线程去查，
     * 主线程一步不等（网络在主线程上 Android 会直接抛 NetworkOnMainThreadException）。
     * 开关与地址都在线程里现读，`Settings` 首次加载那一下也不占主线程。
     */
    fun checkOnStartupAsync(): Thread {
        val worker = Thread({
            try {
                checkOnStartup()
            } catch (e: Exception) {
                // check() 自己已经兜住了网络与解析错误；这里只防 Settings/Paths 还没就位这类极端情况
                last = failure(e)
            }
        }, "pymcl-update-check")
        worker.isDaemon = true
        worker.start()
        return worker
    }

    /** 单测之间清状态。 */
    fun reset() {
        startupDone.set(false)
        last = null
        lastCheckedAt = 0L
        listeners.clear()
    }

    private fun fetchText(url: String): String {
        val client = Http.client.newBuilder().callTimeout(TIMEOUT_SEC, TimeUnit.SECONDS).build()
        val req = Request.Builder().url(url).header("User-Agent", Paths.UA).get().build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw HttpException("HTTP ${resp.code} $url")
            return body
        }
    }
}
