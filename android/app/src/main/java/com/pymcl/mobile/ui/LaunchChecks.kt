package com.pymcl.mobile.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.CrashAction
import com.pymcl.mobile.data.CrashActionResult
import com.pymcl.mobile.data.CrashActions
import com.pymcl.mobile.data.CrashReport
import com.pymcl.mobile.data.GameRuntime
import com.pymcl.mobile.data.Mods
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.Preflight
import com.pymcl.mobile.data.PreflightItem
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel

/**
 * 启动页上「先查再启」那两张卡：启动前体检（对齐桌面 `preflight_launch` 那个弹窗）与
 * 崩溃归因下面的一键修复按钮（对齐桌面 `apply_crash_action`）。
 *
 * data 层的 [Preflight] / [CrashActions] 只出码不出文案，标题、说明、按钮字全在这里按码取词——
 * 所以中文只出现在 `t("…")` 里，英文界面不会漏中文。
 */

private val WarnOrange = Color(0xFFE8862E)

// ---------------------------------------------------------------- 体检文案

/** 体检码 → 标题。 */
fun preflightTitle(code: String): String = when (code) {
    "no_instance" -> t("实例目录不存在")
    "not_writable" -> t("实例目录不可写")
    "no_version" -> t("未选择版本")
    "no_version_json" -> t("版本未安装")
    "files_missing" -> t("版本文件缺失")
    "disk_low" -> t("磁盘空间不足")
    "disk_warn" -> t("磁盘空间偏低")
    "mod_unzipped" -> t("Mods 被解压成了文件夹")
    "vanilla_mods" -> t("原版版本不会加载模组")
    "java_unavailable" -> t("本包没有这个版本要的 Java")
    "java_not_ready" -> t("Java 运行时还没解压")
    "memory_high" -> t("分配内存接近可用物理内存")
    "ready" -> t("预检通过")
    "check_failed" -> t("启动预检失败")
    else -> code
}

/** 体检码 → 说明。[PreflightItem.detail] / [PreflightItem.amount] 是这句里的变量部分。 */
fun preflightDetail(item: PreflightItem): String = when (item.code) {
    "no_version" -> t("请先到「下载 → 原版游戏」安装版本")
    "no_version_json" -> t("找不到 {0} 的版本 JSON").fmt(item.detail)
    "files_missing" -> t("缺 {0} 个文件，点「修复」重新下载：").fmt(item.amount) + "\n" + item.detail
    "disk_low" -> t("实例所在盘仅剩约 {0} MB，至少需要 512 MB").fmt(item.amount)
    "disk_warn" -> t("实例所在盘剩余约 {0} MB，建议清理后再装大整合包").fmt(item.amount)
    "mod_unzipped" -> t("直接放整个 .jar/.zip 即可。请删掉这些文件夹：") + "\n" + item.detail
    "vanilla_mods" -> t("mods 里有 {0} 个 jar，但当前版本名像原版。请安装 Fabric/Forge 等加载器。").fmt(item.amount)
    "java_unavailable" -> t("这个版本要 Java {0}（{1}），本包只带 JRE 17/21").fmt(item.amount, item.detail)
    "java_not_ready" -> t("Java {0} 会在点启动时自动解压，第一次较慢").fmt(item.amount)
    "memory_high" -> t("系统当前可用约 {0} MB，建议调到 {1} MB").fmt(item.detail, item.amount)
    "ready" -> t("未发现阻塞问题")
    else -> item.detail
}

/** 「去修」按钮上的字；空串 = 这条没有落点。 */
fun preflightFixLabel(fix: String): String = when (fix) {
    Preflight.FIX_DOWNLOAD -> t("去下载")
    Preflight.FIX_REPAIR -> t("修复")
    Preflight.FIX_JAVA -> t("去 Java 页")
    Preflight.FIX_MEMORY -> t("调到建议值")
    Preflight.FIX_MODS -> t("去看 Mods")
    else -> ""
}

fun preflightLevelLabel(level: String): String = when (level) {
    Preflight.ERROR -> t("错误")
    Preflight.WARN -> t("警告")
    else -> t("通过")
}

// ---------------------------------------------------------------- 修复文案

/** 动作 id → 按钮字，沿用桌面 build_actions 的说法。 */
fun crashActionLabel(action: CrashAction): String = when (action.id) {
    CrashActions.DISABLE_MODS -> if ("mod_dup" in action.codes) t("禁用重复 Mod") else t("禁用嫌疑 Mod")
    CrashActions.OPEN_MODS -> t("打开 mods 文件夹")
    CrashActions.BUMP_MEMORY -> t("提高默认内存")
    CrashActions.TRIM_MEMORY -> t("调低默认内存")
    CrashActions.NEED_JAVA -> if (action.major > 0) t("下载 Java {0}").fmt(action.major) else t("重装 Java 运行时")
    CrashActions.REPAIR_VERSION -> t("修复该版本文件")
    CrashActions.OPEN_CRASH_FILE -> t("打开崩溃报告")
    CrashActions.OPEN_GPU_HINT -> t("查看显卡驱动提示")
    CrashActions.RESET_JVM_ARGS -> t("清空自定义 JVM 参数")
    else -> action.id
}

/** 动作执行结果 → 那一行反馈。 */
fun crashResultText(result: CrashActionResult): String = when (result.code) {
    CrashActions.R_DISABLED ->
        t("已禁用 {0} 个 Mod").fmt(result.count) +
            if (result.detail.isBlank()) "" else t("；部分失败：") + result.detail
    CrashActions.R_DISABLE_FAILED -> t("未能禁用：") + result.detail
    CrashActions.R_JVM_CLEARED -> t("已清空自定义 JVM 参数")
    CrashActions.R_GPU_HINT ->
        t("渲染相关崩溃：换一个渲染器再试，关掉光影与高清材质；手机上 OpenGL 靠 GL4ES / Zink 翻译，1.17 以上通常要 Zink。")
    CrashActions.R_GOTO -> when (result.route) {
        CrashActions.ROUTE_MEMORY -> t("默认内存已设为 {0} MB").fmt(result.count)
        CrashActions.ROUTE_REPAIR -> t("已开始修复")
        CrashActions.ROUTE_JAVA -> t("已跳到 Java 页")
        CrashActions.ROUTE_MODS -> t("已跳到实例页，Mods 在「内容」里")
        else -> ""
    }
    else -> t("未知动作: {0}").fmt(result.detail)
}

// ---------------------------------------------------------------- 体检卡

/** 体检结果那张卡。没跑过体检（`vm.preflight == null`）时什么都不画。 */
@Composable
fun PreflightCard(vm: AppViewModel) {
    val result = vm.preflight ?: return
    val errors = result.errors.size
    val warns = result.warns.size
    CardBox {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(t("启动前体检"), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Pill(
                when {
                    errors > 0 -> t("{0} 项错误").fmt(errors)
                    warns > 0 -> t("{0} 项警告").fmt(warns)
                    else -> t("通过")
                },
                when {
                    errors > 0 -> ErrorRed
                    warns > 0 -> WarnOrange
                    else -> PclGreen
                },
            )
            TextButton(onClick = { vm.runPreflight() }) { Text(t("重新体检"), color = PclGreen, fontSize = 12.sp) }
            TextButton(onClick = { vm.preflight = null }) { Text(t("关闭"), color = PclMuted, fontSize = 12.sp) }
        }
        result.items.forEach { item -> PreflightRow(item, vm) }
    }
}

@Composable
private fun PreflightRow(item: PreflightItem, vm: AppViewModel) {
    val color = when (item.level) {
        Preflight.ERROR -> ErrorRed
        Preflight.WARN -> WarnOrange
        else -> PclGreen
    }
    Spacer(Modifier.height(4.dp))
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Pill(preflightLevelLabel(item.level), color)
        Spacer(Modifier.width(6.dp))
        Text(preflightTitle(item.code), fontWeight = FontWeight.SemiBold, fontSize = 13.sp, modifier = Modifier.weight(1f))
        val fix = preflightFixLabel(item.fix)
        if (fix.isNotBlank()) {
            TextButton(onClick = { applyPreflightFix(item, vm) }, enabled = !vm.busy) {
                Text(fix, color = PclGreen, fontSize = 12.sp)
            }
        }
    }
    val detail = preflightDetail(item)
    if (detail.isNotBlank()) Text(detail, color = PclMuted, fontSize = 11.sp)
}

/** 「去修」落到哪：下载页原版分区 / 修复任务 / Java 页 / 直接把内存滑到建议值 / 实例页。 */
private fun applyPreflightFix(item: PreflightItem, vm: AppViewModel) {
    when (item.fix) {
        Preflight.FIX_DOWNLOAD -> {
            vm.downloadTab = CatalogRepo.KIND_VANILLA
            vm.tab = MainTab.Download.index
        }
        Preflight.FIX_REPAIR -> if (vm.versionId.isNotBlank()) vm.repairVersion(vm.versionId)
        Preflight.FIX_JAVA -> {
            vm.pendingMineRoute = "java"
            vm.tab = MainTab.Mine.index
        }
        Preflight.FIX_MEMORY -> if (item.amount > 0) {
            vm.memoryMb = item.amount
            vm.persistUi()
            vm.runPreflight()
        }
        Preflight.FIX_MODS -> vm.tab = MainTab.Instances.index
    }
}

// ---------------------------------------------------------------- 崩溃卡

/**
 * 上一次非正常退出的归因 + 一键修复。
 *
 * 游戏是在另一个 Activity 里跑的，退出时那边已经把日志尾巴交给 `CrashReporter.analyze`
 * 归过因了；这里让用户回到启动页时第一眼看见「为什么没起来」，并且能直接点按钮修——
 * 停用嫌疑 Mod、调内存、修版本、去 Java 页，跟桌面崩溃弹窗里的「建议操作」一样。
 */
@Composable
fun CrashCard(vm: AppViewModel) {
    val report = GameRuntime.lastCrash ?: return
    var notice by remember(report) { mutableStateOf("") }
    var showExcerpt by remember { mutableStateOf(false) }
    val clipboard = LocalClipboardManager.current

    CardBox {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(report.headline, color = ErrorRed, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            TextButton(onClick = { GameRuntime.clearCrash() }) { Text(t("知道了"), color = PclGreen) }
        }
        if (report.summary.isNotBlank()) {
            Text(report.summary, color = PclText, fontSize = 12.sp)
        }
        val advice = report.adviceText()
        if (advice.isNotBlank()) {
            Text(advice, color = PclMuted, fontSize = 11.sp)
        }
        Text(t("退出码 {0} · 完整日志在存档页的「崩溃报告」里").fmt(report.exitCode), color = PclMuted, fontSize = 11.sp)
        CrashActionButtons(vm, report, onResult = { notice = it }, onShowExcerpt = { showExcerpt = true })
        if (notice.isNotBlank()) {
            Text(notice, color = PclGreen, fontSize = 11.sp)
        }
    }

    if (showExcerpt) {
        AlertDialog(
            onDismissRequest = { showExcerpt = false },
            title = { Text(t("崩溃报告")) },
            text = {
                Text(
                    report.excerpt.ifBlank { t("没有可打开的崩溃文件") },
                    fontFamily = FontFamily.Monospace,
                    fontSize = 10.sp,
                    modifier = Modifier.height(320.dp).verticalScroll(rememberScrollState()),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    clipboard.setText(AnnotatedString(report.excerpt))
                    showExcerpt = false
                }) { Text(t("复制"), color = PclGreen) }
            },
            dismissButton = { TextButton(onClick = { showExcerpt = false }) { Text(t("关闭")) } },
        )
    }
}

/** 归因 → 按钮排。桌面 build_actions 的顺序就是按钮顺序；一个都排不出来就整段不占位。 */
@Composable
private fun CrashActionButtons(
    vm: AppViewModel,
    report: CrashReport,
    onResult: (String) -> Unit,
    onShowExcerpt: () -> Unit,
) {
    val actions = remember(report, vm.memoryMb) {
        val instDir = Paths.instanceDir(report.instance.ifBlank { vm.instance })
        CrashActions.build(
            report.reasons,
            modsDir = runCatching { Mods.dirFor(instDir, report.version) }.getOrNull(),
            hasVersion = report.version.isNotBlank(),
            hasCrashFile = report.excerpt.isNotBlank(),
            memoryMb = vm.memoryMb,
        )
    }
    if (actions.isEmpty()) return
    Spacer(Modifier.height(4.dp))
    Text(t("建议操作"), color = PclMuted, fontSize = 11.sp)
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        actions.forEach { action ->
            OutlinedButton(
                onClick = {
                    if (action.id == CrashActions.OPEN_CRASH_FILE) {
                        onShowExcerpt()
                        return@OutlinedButton
                    }
                    vm.applyCrashAction(action, report) { result ->
                        when (result.route) {
                            CrashActions.ROUTE_JAVA -> {
                                vm.pendingMineRoute = "java"
                                vm.tab = MainTab.Mine.index
                            }
                            CrashActions.ROUTE_MODS -> vm.tab = MainTab.Instances.index
                            CrashActions.ROUTE_CRASH -> onShowExcerpt()
                        }
                        onResult(crashResultText(result))
                    }
                },
                enabled = !vm.busy,
            ) { Text(crashActionLabel(action), fontSize = 12.sp) }
        }
    }
}
