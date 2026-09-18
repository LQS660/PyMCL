package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.AiConfig
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.FeedbackRepo
import com.pymcl.mobile.data.I18n
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.Recommendation
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.SettingsLogic
import com.pymcl.mobile.data.SmartRecommendation
import com.pymcl.mobile.data.UpdateCheck
import com.pymcl.mobile.data.UpdateInfo
import com.pymcl.mobile.data.UpdateKind
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 设置页里的二级入口，由外壳负责真正切页。 */
enum class SettingsRoute { Theme, Layout, Account, Java, Feedback, FirstRun, GlobalMods }

/** 内存滑杆的区间。智能推荐要按这个上限夹一道，所以摘成常量，别两处各写一个数。 */
private const val MEMORY_MIN_MB = 512
private const val MEMORY_MAX_MB = 8192

/**
 * 设置页。对齐 `app/pages/settings_page.py` 的全部可用档位（去掉桌面独有的窗口 / 多开 / 侧栏）：
 * 游戏与隔离、下载、内存与 JVM、账号与更新、AI 接入、反馈，外加通往主题 / 布局 /
 * 账号 / Java / 反馈几个二级页的入口。
 *
 * **所有改动只写内存**，落盘在离开本页时一次性做（见下面的 DisposableEffect）。
 * 桌面那边是点「保存」才落盘，手机上没有那个按钮，所以改成走这条路——
 * 否则拖一次内存滑杆就是几十次 config.json 写入。
 */
@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    onNavigate: (SettingsRoute) -> Unit = {},
    onThemeChanged: () -> Unit = {},
    onLanguageChanged: () -> Unit = {},
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    // 每个档位一份本地状态：改一个开关只重组这一张卡，不动整页
    var language by remember { mutableStateOf(I18n.language) }
    var isolation by remember { mutableStateOf(Settings.str(SettingsKeys.DEFAULT_ISOLATION, "all")) }
    var shareLibs by remember { mutableStateOf(Settings.bool(SettingsKeys.SHARED_LIBRARIES)) }
    var shareAssets by remember { mutableStateOf(Settings.bool(SettingsKeys.SHARED_ASSETS)) }
    var downloadSource by remember { mutableStateOf(Settings.str(SettingsKeys.DOWNLOAD_SOURCE, "auto")) }
    var communitySource by remember { mutableStateOf(Settings.str(SettingsKeys.COMMUNITY_SOURCE, "auto")) }
    var threads by remember { mutableIntStateOf(Settings.int(SettingsKeys.DOWNLOAD_THREADS, 8)) }
    var limitKbps by remember { mutableIntStateOf(Settings.int(SettingsKeys.DOWNLOAD_LIMIT, 0)) }
    var useProxy by remember { mutableStateOf(Settings.bool(SettingsKeys.USE_SYSTEM_PROXY, true)) }
    var memory by remember { mutableIntStateOf(Settings.int(SettingsKeys.MEMORY_MB, 2048)) }
    var jvmArgs by remember { mutableStateOf(Settings.str(SettingsKeys.DEFAULT_JVM_ARGS)) }
    var msClient by remember { mutableStateOf(Settings.str(SettingsKeys.MS_CLIENT_ID, Paths.MS_CLIENT)) }
    var curseKey by remember { mutableStateOf(Settings.str(SettingsKeys.CURSEFORGE_API_KEY)) }
    var updateUrl by remember { mutableStateOf(Settings.str(SettingsKeys.UPDATE_URL)) }
    var autoUpdate by remember { mutableStateOf(Settings.bool(SettingsKeys.AUTO_CHECK_UPDATE, true)) }
    var aiGateway by remember { mutableStateOf(Settings.str(SettingsKeys.AI_GATEWAY_URL)) }
    var aiBase by remember { mutableStateOf(Settings.str(SettingsKeys.AI_BASE_URL)) }
    var aiKey by remember { mutableStateOf(Settings.str(SettingsKeys.AI_API_KEY)) }
    var aiModel by remember { mutableStateOf(Settings.str(SettingsKeys.AI_MODEL, AiRepo.MODEL)) }
    var aiConfirm by remember { mutableStateOf(Settings.bool(SettingsKeys.AI_CONFIRM_WRITES, true)) }
    var aiPermission by remember { mutableStateOf(Settings.str(SettingsKeys.AI_PERMISSION_MODE, "standard")) }
    var feedbackUrl by remember { mutableStateOf(Settings.str(SettingsKeys.FEEDBACK_URL)) }
    var feedbackConsent by remember { mutableStateOf(Settings.bool(SettingsKeys.FEEDBACK_CONSENT)) }
    var heartbeat by remember { mutableStateOf(Settings.bool(SettingsKeys.FEEDBACK_HEARTBEAT, true)) }
    var testing by remember { mutableStateOf(false) }
    var recommendation by remember { mutableStateOf<Recommendation?>(null) }
    var probing by remember { mutableStateOf(false) }
    var checkingUpdate by remember { mutableStateOf(false) }
    var updateInfo by remember { mutableStateOf(UpdateCheck.last) }
    val uriHandler = LocalUriHandler.current

    // 离开设置页 = 写盘时机。攒了多少改动都只写这一次
    DisposableEffect(Unit) {
        onDispose { Settings.flushIfDirty() }
    }

    // 启动时那一次后台检查可能在本页开着的时候才回来：订阅一下，结果行跟着刷
    DisposableEffect(Unit) {
        val listener: (UpdateInfo) -> Unit = { info -> updateInfo = info }
        UpdateCheck.addListener(listener)
        onDispose { UpdateCheck.removeListener(listener) }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t("设置"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                Text(t("改了立刻生效，退出本页时统一写盘"), color = c.muted, fontSize = 12.sp)
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "nav") {
            PclCard {
                PclSectionTitle(t("更多设置"))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    PclLink(t("主题")) { onNavigate(SettingsRoute.Theme) }
                    PclLink(t("启动页布局")) { onNavigate(SettingsRoute.Layout) }
                    PclLink(t("账号")) { onNavigate(SettingsRoute.Account) }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    PclLink("Java") { onNavigate(SettingsRoute.Java) }
                    PclLink(t("反馈")) { onNavigate(SettingsRoute.Feedback) }
                    // 桌面把「全局 Mod」挂在设置页的维护工具卡片上，这里跟着放在设置页
                    PclLink(t("全局 Mod")) { onNavigate(SettingsRoute.GlobalMods) }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    PclLink(t("重新运行首次引导")) {
                        Settings.set(SettingsKeys.FIRST_RUN, true)
                        Settings.flushIfDirty()
                        onNavigate(SettingsRoute.FirstRun)
                    }
                }
            }
        }

        item(key = "language") {
            PclCard {
                PclSectionTitle(t("语言"), t("词表与桌面版同一份；切换后界面立刻重绘"))
                PclOptionRow(
                    label = "",
                    options = I18n.LANGUAGES,
                    selected = language,
                ) {
                    language = I18n.setLanguage(it)
                    // 语言是全局的，别等离开本页再落盘：切完外壳立刻整树重建，本页会被销毁再造
                    Settings.set(SettingsKeys.LANGUAGE, language)
                    Settings.flushIfDirty()
                    onLanguageChanged()
                }
            }
        }

        item(key = "game") {
            PclCard {
                PclSectionTitle(t("游戏"), t("只影响以后新建的版本，已装好的不受影响"))
                PclOptionRow(
                    label = t("新版本默认隔离"),
                    options = listOf("all" to t("完全独立"), "mods" to t("只隔离模组"), "none" to t("共用一套")),
                    selected = isolation,
                ) {
                    isolation = it
                    Settings.set(SettingsKeys.DEFAULT_ISOLATION, it)
                }
                PclSwitchRow(t("共享 libraries"), shareLibs, t("多个实例共用一份依赖库，省空间")) {
                    shareLibs = it
                    Settings.set(SettingsKeys.SHARED_LIBRARIES, it)
                }
                PclSwitchRow(t("共享 assets"), shareAssets, t("资源文件也共用一份")) {
                    shareAssets = it
                    Settings.set(SettingsKeys.SHARED_ASSETS, it)
                }
            }
        }

        item(key = "download") {
            PclCard {
                PclSectionTitle(t("下载"))
                PclOptionRow(
                    label = t("文件下载源"),
                    options = listOf(
                        "auto" to t("自动（官方慢则 BMCLAPI）"),
                        "official" to t("仅官方"),
                        "bmclapi" to t("仅 BMCLAPI"),
                    ),
                    selected = downloadSource,
                ) {
                    downloadSource = it
                    Settings.set(SettingsKeys.DOWNLOAD_SOURCE, it)
                }
                PclOptionRow(
                    label = t("模组 / 整合包源"),
                    options = listOf("auto" to t("自动"), "official" to t("官方"), "mcim" to t("MCIM 镜像")),
                    selected = communitySource,
                ) {
                    communitySource = it
                    Settings.set(SettingsKeys.COMMUNITY_SOURCE, it)
                }
                PclSliderRow(t("并发线程"), threads, 1..32, "", onChange = { threads = it }) {
                    Settings.set(SettingsKeys.DOWNLOAD_THREADS, SettingsLogic.clampThreads(threads))
                }
                PclSliderRow(
                    t("限速"),
                    limitKbps,
                    0..20480,
                    if (limitKbps == 0) t(" KB/s（0 = 不限）") else " KB/s",
                    onChange = { limitKbps = it },
                ) {
                    Settings.set(SettingsKeys.DOWNLOAD_LIMIT, limitKbps)
                }
                PclSwitchRow(t("跟随系统代理"), useProxy, t("关掉就强制直连")) {
                    useProxy = it
                    Settings.set(SettingsKeys.USE_SYSTEM_PROXY, it)
                }
                PclKeyValue(t("清单地址"), SettingsLogic.manifestUrls(downloadSource).first())
            }
        }

        item(key = "runtime") {
            PclCard {
                PclSectionTitle(t("内存与 JVM"))
                PclSliderRow(t("默认内存"), memory, MEMORY_MIN_MB..MEMORY_MAX_MB, " MB", onChange = { memory = it }) {
                    Settings.set(SettingsKeys.MEMORY_MB, SettingsLogic.clampMemory(memory))
                }
                PclTextRow(t("默认 JVM 参数"), jvmArgs, t("留空用推荐参数")) {
                    jvmArgs = it
                    Settings.set(SettingsKeys.DEFAULT_JVM_ARGS, it)
                }

                // 智能推荐。桌面挂在设置页的「维护工具」卡上，手机上就近放在内存滑杆下面：
                // 推荐的就是这根滑杆的值，隔一张卡去看没有意义。
                PclSectionTitle(t("智能推荐"), t("根据硬件自动推荐内存和 Java 设置"))
                recommendation?.let { rec ->
                    PclKeyValue(t("本机"), t("{0} GB 内存 · {1} 核 CPU").fmt(rec.totalRamGb, rec.cpuCount))
                    PclKeyValue(t("推荐内存"), t("{0} MB").fmt(rec.memoryMb))
                    Text(t("按物理内存分档，且不超过物理内存的 75%"), color = c.muted, fontSize = 11.sp)
                    if (rec.memoryMb > MEMORY_MAX_MB) {
                        Text(
                            t("这根滑杆最高 {0} MB，应用时按上限取").fmt(MEMORY_MAX_MB),
                            color = c.muted,
                            fontSize = 11.sp,
                        )
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    PclLink(if (probing) t("检测中…") else t("查看推荐"), enabled = !probing) {
                        scope.launch {
                            probing = true
                            notice.clear()
                            try {
                                // 读 /proc/meminfo 是磁盘 IO，别占主线程
                                recommendation = withContext(Dispatchers.IO) {
                                    SmartRecommendation.of(SmartRecommendation.probe())
                                }
                            } catch (failure: Exception) {
                                notice.fail(t("{0} 失败：{1}").fmt(t("智能推荐"), failure.message))
                            } finally {
                                probing = false
                            }
                        }
                    }
                    recommendation?.let { rec ->
                        PclLink(t("应用推荐")) {
                            val applied = SmartRecommendation.applicableMemoryMb(
                                rec.memoryMb, MEMORY_MAX_MB, MEMORY_MIN_MB,
                            )
                            memory = applied
                            Settings.set(SettingsKeys.MEMORY_MB, applied)
                            notice.ok(t("内存已设为 {0} MB，退出本页时写盘").fmt(applied))
                        }
                    }
                }
                PclLink(t("去 Java 页管理运行时")) { onNavigate(SettingsRoute.Java) }
            }
        }

        item(key = "account") {
            PclCard {
                PclSectionTitle(t("账号与更新"))
                PclTextRow(t("微软 OAuth 客户端 ID"), msClient, t("换成自己的应用 ID 也行")) {
                    msClient = it
                    Settings.set(SettingsKeys.MS_CLIENT_ID, it)
                }
                PclTextRow("CurseForge API Key", curseKey, secret = true) {
                    curseKey = it
                    Settings.set(SettingsKeys.CURSEFORGE_API_KEY, it)
                }
                PclTextRow(t("更新检查地址"), updateUrl) {
                    updateUrl = it
                    Settings.set(SettingsKeys.UPDATE_URL, it)
                }
                PclSwitchRow(t("启动时自动检查更新"), autoUpdate, t("打开启动器后在后台检查自更新清单")) {
                    autoUpdate = it
                    Settings.set(SettingsKeys.AUTO_CHECK_UPDATE, it)
                }
                updateInfo?.let { info ->
                    PclKeyValue(t("上次检查"), updateStatusText(info))
                    if (info.hasUpdate && info.notes.isNotBlank()) {
                        Text(info.notes, color = c.muted, fontSize = 11.sp)
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PclButton(if (checkingUpdate) t("检查中…") else t("检查更新"), enabled = !checkingUpdate) {
                        scope.launch {
                            checkingUpdate = true
                            notice.clear()
                            try {
                                // 地址读的是内存里那份，上面刚改的「更新检查地址」不用先写盘
                                val url = UpdateCheck.manifestUrl()
                                val info = withContext(Dispatchers.IO) { UpdateCheck.check(url) }
                                updateInfo = info
                                // 对齐桌面 _check_update：有更新 / 已最新走 info，失败与拒签走 error
                                val bad = info.kind == UpdateKind.FAILED || info.kind == UpdateKind.UNSIGNED
                                if (bad) notice.fail(updateStatusText(info)) else notice.ok(updateStatusText(info))
                            } finally {
                                checkingUpdate = false
                            }
                        }
                    }
                    val downloadUrl = updateInfo?.takeIf { it.hasUpdate }?.url.orEmpty()
                    if (downloadUrl.isNotBlank()) {
                        // 手机上换 APK 归系统安装器，这里只把下载页交给浏览器
                        PclLink(t("打开下载页")) {
                            try {
                                uriHandler.openUri(downloadUrl)
                            } catch (e: Exception) {
                                notice.fail(t("打不开链接：{0}").fmt(e.message))
                            }
                        }
                    }
                }
            }
        }

        item(key = "ai") {
            PclCard {
                PclSectionTitle(
                    t("AI 接入"),
                    t("填了密钥就直连下面的接口；不填则走公益网关，令牌由网关保管，不进手机。"),
                )
                PclKeyValue(t("当前"), AiRepo.describe(AiConfig.current()))
                PclTextRow(t("公益网关根地址"), aiGateway, "${t("留空用")} ${AiRepo.PUBLIC_BASE}") {
                    aiGateway = it
                    Settings.set(SettingsKeys.AI_GATEWAY_URL, it)
                }
                PclTextRow(t("接口地址（到 /v1 为止）"), aiBase) {
                    aiBase = it
                    Settings.set(SettingsKeys.AI_BASE_URL, it)
                    Settings.set(SettingsKeys.AI_MODE, if (aiKey.isBlank()) "public" else "custom")
                }
                PclTextRow(t("密钥（留空则走网关）"), aiKey, secret = true) {
                    aiKey = it
                    Settings.set(SettingsKeys.AI_API_KEY, it)
                    Settings.set(SettingsKeys.AI_MODE, if (it.isBlank()) "public" else "custom")
                }
                PclTextRow(t("模型"), aiModel, "${t("留空用")} ${AiRepo.MODEL}") {
                    aiModel = it
                    Settings.set(SettingsKeys.AI_MODEL, it)
                }
                PclSwitchRow(t("执行前先问我"), aiConfirm, t("关掉后装模组、启动游戏这类改动会直接执行")) {
                    aiConfirm = it
                    Settings.set(SettingsKeys.AI_CONFIRM_WRITES, it)
                }
                PclOptionRow(
                    label = t("确认范围"),
                    options = listOf("standard" to t("全部写操作都确认"), "full" to t("只确认破坏性操作")),
                    selected = aiPermission,
                ) {
                    aiPermission = it
                    Settings.set(SettingsKeys.AI_PERMISSION_MODE, it)
                }
                Text(
                    t("删实例、删模组、改模组配置属于不可恢复的操作，无论这两项怎么设都仍然会弹确认。"),
                    color = c.muted,
                    fontSize = 11.sp,
                )
                PclButton(if (testing) t("测试中…") else t("测试连接"), enabled = !testing) {
                    scope.launch {
                        testing = true
                        notice.clear()
                        // AiConfig 从落盘的 config.json 读，所以测之前先把攒着的改动刷出去，
                        // 不然测的是上一版配置
                        Settings.flushIfDirty()
                        val cfg = AiConfig.current()
                        try {
                            val line = withContext(Dispatchers.IO) { AiRepo.testConnection(cfg) }
                            notice.ok(line)
                        } catch (e: Exception) {
                            notice.fail(t("连不上：{0}").fmt(e.message))
                        } finally {
                            testing = false
                        }
                    }
                }
            }
        }

        item(key = "feedback") {
            PclCard {
                PclSectionTitle(t("反馈与崩溃上报"))
                PclSwitchRow(t("同意上传反馈内容"), feedbackConsent, t("不同意就一条都不发")) {
                    feedbackConsent = it
                    Settings.set(SettingsKeys.FEEDBACK_CONSENT, it)
                }
                PclTextRow(t("反馈中心地址"), feedbackUrl, "${t("留空用")} ${FeedbackRepo.DEFAULT_URL}") {
                    feedbackUrl = it
                    Settings.set(SettingsKeys.FEEDBACK_URL, it)
                }
                PclSwitchRow(t("在线心跳"), heartbeat, t("让开发者知道有多少人在用；不含任何账号信息")) {
                    heartbeat = it
                    Settings.set(SettingsKeys.FEEDBACK_HEARTBEAT, it)
                }
                PclLink(t("去反馈页")) { onNavigate(SettingsRoute.Feedback) }
            }
        }

        item(key = "cleaner") { CleanerCard() }

        item(key = "about") {
            PclCard {
                PclSectionTitle(t("关于"))
                PclKeyValue(t("数据目录"), Paths.root.absolutePath)
                PclKeyValue(t("版本"), "PyMCL ${Paths.APP_VERSION} · android")
                PclLink(t("立刻写盘")) {
                    val wrote = Settings.flushIfDirty()
                    notice.ok(if (wrote) t("已写入 config.json") else t("没有待写入的改动"))
                }
            }
        }
    }
}

/**
 * `UpdateInfo.message` 是桌面 `updater.check()` 同款中文，留给日志与对比；界面上按 [UpdateKind]
 * 挑译文，失败原因原样拼进去（对齐桌面：清单缺 SHA-256 一样算拒绝）。
 */
private fun updateStatusText(info: UpdateInfo): String = when (info.kind) {
    UpdateKind.UP_TO_DATE -> t("已是最新版本")
    UpdateKind.UPDATE -> t("发现 {0}").fmt(info.latest)
    UpdateKind.UNSIGNED -> t("更新清单缺少有效 SHA-256，已拒绝自动更新")
    UpdateKind.FAILED -> t("检查更新失败: {0}").fmt(info.error)
}
