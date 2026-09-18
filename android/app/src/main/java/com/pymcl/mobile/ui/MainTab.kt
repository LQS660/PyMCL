package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.People
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.DownloadDock
import com.pymcl.mobile.data.I18n
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.TaskCenter
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.theme.PclDanger
import com.pymcl.mobile.vm.AppViewModel

/**
 * 底部导航的六格。
 *
 * 前四格的下标**必须**保持 0 启动 / 1 实例 / 2 联机 / 3 下载：游戏域那几个
 * Screen 里有 `vm.tab = 0` 这类跳转，换了下标就跳错页。
 */
enum class MainTab(
    val route: String,
    val icon: ImageVector,
    val index: Int,
) {
    Launch("launch", Icons.Outlined.PlayArrow, 0),
    Instances("instances", Icons.Outlined.GridView, 1),
    Multiplayer("multiplayer", Icons.Outlined.People, 2),
    Download("download", Icons.Outlined.Download, 3),
    Ai("ai", Icons.Outlined.Chat, 4),
    Mine("mine", Icons.Outlined.Settings, 5),
    ;

    /** 每次取都走词表：枚举常量只初始化一次，写在构造参数里切了语言底栏不会跟着换。 */
    val label: String
        get() = when (this) {
            Launch -> t("启动")
            Instances -> t("实例")
            Multiplayer -> t("联机")
            Download -> t("下载")
            Ai -> "AI"
            Mine -> t("我的")
        }

    companion object {
        fun byIndex(index: Int): MainTab = entries.firstOrNull { it.index == index } ?: Launch
    }
}

/** 「我的」这一格下面的二级页。桌面是侧栏里的平级项，手机上收进一层。 */
private enum class MineRoute { Hub, Settings, Theme, Layout, Account, Java, Feedback, GlobalMods }

/** 「我的」页里卡片的顺序。标题与说明走下面两个函数，组合时才取词。 */
private val MINE_ORDER = listOf(
    MineRoute.Account, MineRoute.Java, MineRoute.Settings,
    MineRoute.Theme, MineRoute.Layout, MineRoute.Feedback,
)

private fun mineTitle(route: MineRoute): String = when (route) {
    MineRoute.Hub -> t("我的")
    MineRoute.Account -> t("账号")
    MineRoute.Java -> "Java"
    MineRoute.Settings -> t("设置")
    MineRoute.Theme -> t("主题")
    MineRoute.Layout -> t("启动页布局")
    MineRoute.Feedback -> t("反馈")
    MineRoute.GlobalMods -> t("全局 Mod")
}

private fun mineHint(route: MineRoute): String = when (route) {
    MineRoute.Hub -> ""
    MineRoute.Account -> t("微软 / 离线 / 皮肤站 / 统一通行证，皮肤也在这儿")
    MineRoute.Java -> t("本机运行时、下载新版本、给实例单独指定")
    MineRoute.Settings -> t("游戏、下载、内存、AI、更新")
    MineRoute.Theme -> t("主题色、深色模式、壁纸与主题包")
    MineRoute.Layout -> t("卡片方案的保存 / 切换 / 导入导出")
    MineRoute.Feedback -> t("提交问题、上报崩溃、看本机配置")
    MineRoute.GlobalMods -> t("共享模组池，没开隔离的版本共用这一份")
}

/**
 * 应用外壳：顶栏 + 内容 + 底部导航。
 *
 * 游戏域那七个 Screen 由 `Screens.kt` 提供，本域这几页由本文件挂进来。
 * 首次启动先走引导页，引导走完才进主界面。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppScaffold(vm: AppViewModel) {
    // 改主题色 / 切深色要让整棵树换配色：revision 变了就整体重组一次
    var themeRevision by remember { mutableStateOf(Settings.revision) }
    // 切语言同理：t() 是组合时现取的，把整棵树按 key 重建一遍，所有文案就换过来了
    var langRevision by remember { mutableIntStateOf(I18n.revision) }
    var firstRun by remember { mutableStateOf(Settings.bool(SettingsKeys.FIRST_RUN, true)) }
    var mine by remember { mutableStateOf(MineRoute.Hub) }

    // 启动页「去 Java 页」这类跨格跳转：别的 Screen 只能改 vm.tab，「我的」下面那一层由这里接
    LaunchedEffect(vm.pendingMineRoute) {
        val route = vm.pendingMineRoute ?: return@LaunchedEffect
        mine = when (route) {
            "java" -> MineRoute.Java
            "settings" -> MineRoute.Settings
            "feedback" -> MineRoute.Feedback
            else -> MineRoute.Hub
        }
        vm.tab = MainTab.Mine.index
        vm.pendingMineRoute = null
    }

    com.pymcl.mobile.theme.PyMclTheme(
        themeColor = remember(themeRevision) { Settings.str(SettingsKeys.THEME_COLOR, "#2E9B6B") },
        dark = remember(themeRevision) { Settings.bool(SettingsKeys.UI_DARK) },
    ) {
        key(langRevision) {
            val c = LocalPclColors.current
            val panel = c.panel(Settings.int(SettingsKeys.UI_SIDEBAR_OPACITY, 85))

            if (firstRun) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(c.background)
                        .padding(horizontal = 20.dp, vertical = 24.dp),
                ) {
                    FirstRunScreen(onDone = { firstRun = false })
                }
            } else {
                Scaffold(
                    containerColor = c.background,
                    topBar = {
                        TopAppBar(
                            title = {
                                Text(
                                    if (vm.tab == MainTab.Mine.index && mine != MineRoute.Hub) {
                                        mineTitle(mine)
                                    } else {
                                        "PyMCL"
                                    },
                                    fontWeight = FontWeight.Bold,
                                    color = c.text,
                                )
                            },
                            navigationIcon = {
                                if (vm.tab == MainTab.Mine.index && mine != MineRoute.Hub) {
                                    PclLink(t("返回")) { mine = MineRoute.Hub }
                                }
                            },
                            colors = TopAppBarDefaults.topAppBarColors(containerColor = panel),
                        )
                    },
                    bottomBar = {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .background(panel)
                                .padding(vertical = 4.dp),
                        ) {
                            MainTab.entries.forEach { tab ->
                                val on = vm.tab == tab.index
                                Column(
                                    Modifier
                                        .weight(1f)
                                        .clickable {
                                            if (on && tab == MainTab.Mine) mine = MineRoute.Hub
                                            vm.tab = tab.index
                                        }
                                        .padding(vertical = 6.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    Box {
                                        Icon(
                                            imageVector = tab.icon,
                                            contentDescription = tab.label,
                                            tint = if (on) c.accent else c.muted,
                                        )
                                        // 任务角标挂在「下载」这一格：手机上任务页收在下载板块里，
                                        // 位置等同桌面侧栏的「下载任务」项
                                        val badge = if (tab == MainTab.Download) {
                                            TaskCenter.badgeText(vm.activeDownloads)
                                        } else {
                                            ""
                                        }
                                        if (badge.isNotEmpty()) {
                                            Text(
                                                badge,
                                                modifier = Modifier
                                                    .align(Alignment.TopEnd)
                                                    .offset(x = 10.dp, y = (-5).dp)
                                                    .background(PclDanger, RoundedCornerShape(8.dp))
                                                    .padding(horizontal = 4.dp),
                                                color = Color.White,
                                                fontSize = 9.sp,
                                                fontWeight = FontWeight.Bold,
                                            )
                                        }
                                    }
                                    Text(
                                        tab.label,
                                        fontSize = 11.sp,
                                        color = if (on) c.accent else c.muted,
                                    )
                                }
                            }
                        }
                    },
                ) { pad ->
                    Box(
                        Modifier
                            .fillMaxSize()
                            .padding(pad)
                            .padding(horizontal = 16.dp, vertical = 8.dp)
                            .imePadding(),
                    ) {
                        when (MainTab.byIndex(vm.tab)) {
                            MainTab.Launch -> LaunchScreen(vm)
                            MainTab.Instances -> InstanceScreen(vm)
                            MainTab.Multiplayer -> MultiplayerScreen(vm)
                            MainTab.Download -> DownloadHub(vm)
                            MainTab.Ai -> AiScreen(
                                onOpenSettings = {
                                    vm.tab = MainTab.Mine.index
                                    mine = MineRoute.Settings
                                },
                            )

                            MainTab.Mine -> when (mine) {
                                MineRoute.Hub -> MineHub { mine = it }
                                MineRoute.Settings -> SettingsScreen(
                                    onNavigate = { route ->
                                        mine = when (route) {
                                            SettingsRoute.Theme -> MineRoute.Theme
                                            SettingsRoute.Layout -> MineRoute.Layout
                                            SettingsRoute.Account -> MineRoute.Account
                                            SettingsRoute.Java -> MineRoute.Java
                                            SettingsRoute.Feedback -> MineRoute.Feedback
                                            SettingsRoute.GlobalMods -> MineRoute.GlobalMods
                                            SettingsRoute.FirstRun -> {
                                                firstRun = true
                                                MineRoute.Hub
                                            }
                                        }
                                    },
                                    onThemeChanged = { themeRevision = Settings.revision },
                                    onLanguageChanged = { langRevision = I18n.revision },
                                )

                                MineRoute.Theme -> ThemeScreen(
                                    onThemeChanged = { themeRevision = Settings.revision },
                                )

                                MineRoute.Layout -> LayoutSettingsScreen()
                                MineRoute.Account -> AccountScreen()
                                MineRoute.Java -> JavaScreen(instance = vm.instance)
                                MineRoute.Feedback -> FeedbackScreen()
                                MineRoute.GlobalMods -> GlobalModsScreen(vm)
                            }
                        }
                        DownloadDockBar(
                            vm,
                            pageKeyOf(vm.tab, mine, vm.downloadTab),
                            Modifier.align(Alignment.BottomCenter),
                        )
                    }
                }
            }
        }
    }
}

/** 这一刻落在哪一页，收成桌面侧栏那套 key —— 悬浮下载坞按它决定收不收起来。 */
private fun pageKeyOf(tab: Int, mine: MineRoute, downloadKind: String): String =
    when (MainTab.byIndex(tab)) {
        MainTab.Launch -> DownloadDock.PAGE_LAUNCH
        MainTab.Instances -> DownloadDock.PAGE_INSTANCE
        MainTab.Multiplayer -> DownloadDock.PAGE_MULTIPLAYER
        MainTab.Download ->
            if (downloadKind == CatalogRepo.KIND_TASKS) DownloadDock.PAGE_TASKS else DownloadDock.PAGE_DOWNLOAD

        MainTab.Ai -> DownloadDock.PAGE_AI
        MainTab.Mine -> when (mine) {
            MineRoute.Hub -> DownloadDock.PAGE_MINE
            MineRoute.Settings -> DownloadDock.PAGE_SETTINGS
            MineRoute.Theme -> DownloadDock.PAGE_THEME
            MineRoute.Layout -> DownloadDock.PAGE_LAYOUT
            MineRoute.Account -> DownloadDock.PAGE_ACCOUNT
            MineRoute.Java -> DownloadDock.PAGE_JAVA
            MineRoute.Feedback -> DownloadDock.PAGE_FEEDBACK
            MineRoute.GlobalMods -> DownloadDock.PAGE_MODS
        }
    }

@Composable
private fun MineHub(onPick: (MineRoute) -> Unit) {
    val c = LocalPclColors.current
    Column(
        Modifier.fillMaxSize(),
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(10.dp),
    ) {
        Text(t("我的"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
        MINE_ORDER.forEach { route ->
            val title = mineTitle(route)
            val hint = mineHint(route)
            PclCard(Modifier.clickable { onPick(route) }) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    PclTile(title, c.accent, size = 34)
                    Column(Modifier.weight(1f)) {
                        Text(title, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(hint, color = c.muted, fontSize = 11.sp)
                    }
                    Text("›", color = c.muted, fontSize = 18.sp)
                }
            }
        }
        Text(
            "${t("数据目录")} ${com.pymcl.mobile.data.Paths.root.absolutePath}",
            color = c.muted,
            fontSize = 10.sp,
        )
    }
}
