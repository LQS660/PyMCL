package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.SettingsLogic
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors

/**
 * 最后一步指给用户看的那几件事，跟桌面 `first_run.HIGHLIGHTS` 对齐（去掉桌面独有的侧栏那条）。
 * 写成函数而不是顶层常量：组合时才取词，切了语言这一页跟着换。
 */
private fun highlights(): List<Pair<String, String>> = listOf(
    t("账号在底部「账号」页") to
        t("微软正版、离线、皮肤站、统一通行证都在那儿；离线账号还能绑一张自己的皮肤。"),
    t("Java 不用自己找") to
        t("启动时按游戏版本自动挑；想指定就去「Java」页，能给单个实例单独钉一个。"),
    t("换个样子") to
        t("「设置 → 主题」能改主题色、深色模式、壁纸和观感，整套还能存成主题包一键换。"),
    t("崩了不用抄日志") to
        t("崩溃后「设置 → 反馈」里能一键上报，日志会自动摘录并抹掉令牌。"),
    t("这个向导随时能再看") to
        t("「设置 → 重新运行首次引导」，下载源、内存、隔离会再问一遍。"),
)

/**
 * 首次启动引导。对齐 `app/pages/first_run.py`：分四步，前两步问设置，最后一步纯介绍。
 * 每一步都能跳过；跳过后不再自动弹，设置页里能手动重跑。
 */
@Composable
fun FirstRunScreen(
    modifier: Modifier = Modifier,
    onDone: () -> Unit,
) {
    val c = LocalPclColors.current
    var step by rememberSaveable { mutableIntStateOf(0) }
    var source by rememberSaveable { mutableStateOf(Settings.str(SettingsKeys.DOWNLOAD_SOURCE, "auto")) }
    var memory by rememberSaveable { mutableIntStateOf(Settings.int(SettingsKeys.MEMORY_MB, 2048)) }
    var isolation by rememberSaveable { mutableStateOf(Settings.str(SettingsKeys.DEFAULT_ISOLATION, "all")) }
    var username by rememberSaveable { mutableStateOf(Settings.str(SettingsKeys.USERNAME, "Player")) }

    val last = 3
    val hints = listOf(
        t("三步就能开始玩。"),
        t("下载源决定从哪儿拉文件；国内网络建议保持「自动」。"),
        t("这两项只影响以后新建的版本，已经装好的不受影响。"),
        t("最后几句，都是容易错过的地方。"),
    )

    fun finish(skipped: Boolean) {
        if (!skipped) {
            Settings.update(
                mapOf(
                    SettingsKeys.DOWNLOAD_SOURCE to source,
                    SettingsKeys.MEMORY_MB to SettingsLogic.clampMemory(memory),
                    SettingsKeys.DEFAULT_ISOLATION to isolation,
                    SettingsKeys.USERNAME to username.trim().ifBlank { "Player" },
                ),
            )
        }
        Settings.set(SettingsKeys.FIRST_RUN, false)
        Settings.flushIfDirty()
        onDone()
    }

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(t("欢迎使用 PyMCL"), fontWeight = FontWeight.Bold, fontSize = 22.sp, color = c.text)
        Text(hints[step], color = c.muted, fontSize = 13.sp)

        when (step) {
            0 -> PclCard {
                PclSectionTitle(t("三步就能开始玩"))
                Text(t("1. 选下载源"), color = c.text, fontSize = 14.sp)
                Text(t("2. 定默认内存和版本隔离"), color = c.text, fontSize = 14.sp)
                Text(t("3. 看一眼几个容易错过的功能"), color = c.text, fontSize = 14.sp)
                Text(t("这些以后都能在设置里改；不想现在弄就点「跳过」。"), color = c.muted, fontSize = 12.sp)
            }

            1 -> PclCard {
                PclSectionTitle(t("下载源"), t("官方慢的时候「自动」会自己切到 BMCLAPI 镜像"))
                PclOptionRow(
                    label = "",
                    options = listOf(
                        "auto" to t("自动（官方慢则 BMCLAPI）"),
                        "official" to t("仅官方"),
                        "bmclapi" to t("仅 BMCLAPI"),
                    ),
                    selected = source,
                ) { source = it }
                PclGap()
                PclTextRow(t("离线角色名"), username) { username = it }
            }

            2 -> PclCard {
                PclSectionTitle(t("默认内存与隔离"))
                PclSliderRow(t("默认内存"), memory, 512..8192, " MB", onChange = { memory = it })
                PclOptionRow(
                    label = t("新版本默认隔离"),
                    options = listOf(
                        "all" to t("完全独立"),
                        "mods" to t("只隔离模组"),
                        "none" to t("共用一套"),
                    ),
                    selected = isolation,
                ) { isolation = it }
                Text(
                    t("「完全独立」= 每个版本有自己的 mods / 配置 / 存档，换版本不会把上一个版本的模组拖进去。"),
                    color = c.muted,
                    fontSize = 12.sp,
                )
            }

            else -> PclCard {
                highlights().forEach { (title, body) ->
                    Text(title, fontWeight = FontWeight.SemiBold, color = c.text, fontSize = 14.sp)
                    Text(body, color = c.muted, fontSize = 12.sp)
                    PclGap(4)
                }
            }
        }

        Text(t("第 {0} / {1} 步").fmt(step + 1, last + 1), color = c.muted, fontSize = 12.sp)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PclLink(t("上一步"), enabled = step > 0) { step-- }
            PclLink(t("跳过")) { finish(skipped = true) }
            PclButton(if (step == last) t("开始使用") else t("下一步")) {
                if (step == last) finish(skipped = false) else step++
            }
        }
    }
}
