package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.Loader
import com.pymcl.mobile.data.LoaderInstall
import com.pymcl.mobile.data.VersionOps
import com.pymcl.mobile.data.VersionSettings
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.VersionCard
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel

/** 版本管理：每个已装版本一张卡，卡上直接切「独立 / 大锅饭」，更多动作进菜单。 */
@Composable
fun VersionManageScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var filter by remember { mutableStateOf("") }
    var menuFor by remember { mutableStateOf<VersionCard?>(null) }
    var renaming by remember { mutableStateOf<VersionCard?>(null) }
    var copying by remember { mutableStateOf<VersionCard?>(null) }
    var seedAsk by remember { mutableStateOf<VersionCard?>(null) }
    var loaderFor by remember { mutableStateOf<VersionCard?>(null) }
    var settingFor by remember { mutableStateOf<String?>(null) }

    settingFor?.let { id ->
        VersionSetupScreen(vm, id, onClose = { settingFor = null }, modifier = modifier)
        return
    }

    LaunchedEffect(vm.instance, vm.showHidden) { vm.reloadVersionCards() }

    // 过滤只在输入或列表真的变了时重算一次，别每帧都跑一遍全表
    val rows = remember(filter, vm.versionCards.size, vm.versionCards.toList()) {
        com.pymcl.mobile.data.VersionOps.filter(vm.versionCards.toList(), filter)
    }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("版本管理"), t("{0} 个版本 · 实例 {1}").fmt(vm.versionCards.size, vm.instance))
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = filter,
                onValueChange = { filter = it },
                label = { Text(t("搜索已安装的版本")) },
                modifier = Modifier.weight(1f),
                singleLine = true,
                colors = FieldColors(),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = vm.showHidden,
                onCheckedChange = { vm.updateShowHidden(it) },
                colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
            )
            Text(t("显示隐藏"), fontSize = 13.sp)
        }
        ErrorLine(vm)

        if (rows.isEmpty()) {
            EmptyHint(
                if (filter.isBlank()) t("还没有安装任何版本，去「下载」页装一个") else t("没有匹配的版本"),
                Modifier.weight(1f),
            )
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(rows, key = { it.id }) { card ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(card.id, fontWeight = FontWeight.SemiBold)
                            Text(
                                "Minecraft ${card.mc.ifBlank { "?" }} · ${card.loader}",
                                color = PclMuted,
                                fontSize = 12.sp,
                            )
                        }
                        Pill(t("模组 {0}").fmt(card.mods))
                        if (card.hidden) {
                            Spacer(Modifier.height(0.dp))
                            Pill(t("已隐藏"), PclMuted)
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(t("独立模组"), color = PclMuted, fontSize = 12.sp)
                        Switch(
                            checked = card.isolated,
                            onCheckedChange = { on ->
                                if (on) seedAsk = card else vm.toggleIsolation(card.id, false, false)
                            },
                            colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                        )
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = {
                            vm.versionId = card.id
                            vm.tab = 0
                        }) { Text(t("启动"), color = PclGreen) }
                        TextButton(onClick = {
                            vm.selectModTarget(if (card.isolated) card.id else "")
                            vm.tab = 1
                        }) { Text(t("模组"), color = PclGreen) }
                        TextButton(onClick = { settingFor = card.id }) { Text(t("设置"), color = PclGreen) }
                        TextButton(onClick = { menuFor = card }) { Text(t("更多"), color = PclGreen) }
                    }
                }
            }
        }
    }

    seedAsk?.let { card ->
        AlertDialog(
            onDismissRequest = { seedAsk = null },
            title = { Text(t("转为独立模组")) },
            text = {
                Text(
                    t("「{0}」将拥有自己的 mods / config 目录。\n\n").fmt(card.id) +
                        t("要把实例里现有的共享模组复制一份过去吗？\n") +
                        t("选「复制一份」保持现在能玩的样子；选「留空」从零开始装。"),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    vm.toggleIsolation(card.id, true, seed = true)
                    seedAsk = null
                }) { Text(t("复制一份"), color = PclGreen) }
            },
            dismissButton = {
                TextButton(onClick = {
                    vm.toggleIsolation(card.id, true, seed = false)
                    seedAsk = null
                }) { Text(t("留空")) }
            },
        )
    }

    menuFor?.let { card ->
        AlertDialog(
            onDismissRequest = { menuFor = null },
            title = { Text(card.id) },
            text = {
                Column {
                    VersionSettings.LABELS.forEach { (mode, label) ->
                        TextButton(onClick = {
                            vm.setIsolationMode(card.id, mode, seed = mode == VersionSettings.ALL)
                            menuFor = null
                        }) { Text(t("隔离细分：{0}").fmt(t(label)), color = PclGreen) }
                    }
                    if (card.loader == VersionOps.LOADER_VANILLA) {
                        TextButton(onClick = {
                            loaderFor = card
                            vm.reloadLoaderBuilds(card.mc.ifBlank { card.id })
                            menuFor = null
                        }) { Text(t("装加载器…"), color = PclGreen) }
                    }
                    TextButton(onClick = { renaming = card; menuFor = null }) { Text(t("重命名"), color = PclGreen) }
                    TextButton(onClick = { copying = card; menuFor = null }) { Text(t("复制一份"), color = PclGreen) }
                    TextButton(onClick = {
                        vm.toggleVersionHidden(card.id)
                        menuFor = null
                    }) { Text(t("隐藏 / 取消隐藏"), color = PclGreen) }
                    TextButton(onClick = {
                        vm.repairVersion(card.id)
                        menuFor = null
                    }) { Text(t("修复（补全缺失文件）"), color = PclGreen) }
                    TextButton(onClick = {
                        vm.append(vm.exportLaunchScript(card.id))
                        menuFor = null
                    }) { Text(t("导出启动脚本到日志"), color = PclGreen) }
                    TextButton(onClick = {
                        vm.uninstallVersion(card.id)
                        menuFor = null
                    }) { Text(t("卸载这个版本"), color = ErrorRed) }
                }
            },
            confirmButton = { TextButton(onClick = { menuFor = null }) { Text(t("关闭")) } },
        )
    }

    loaderFor?.let { card ->
        val mc = card.mc.ifBlank { card.id }
        AlertDialog(
            onDismissRequest = { loaderFor = null },
            title = { Text(t("在 {0} 上装加载器").fmt(mc)) },
            text = {
                Column {
                    ChipRow(t("加载器"), Loader.entries.map { it.label }, vm.loaderKind.label) { label ->
                        Loader.entries.firstOrNull { it.label == label }?.let {
                            vm.loaderKind = it
                            vm.reloadLoaderBuilds(mc)
                        }
                    }
                    if (!LoaderInstall.isMetaOnly(vm.loaderKind)) {
                        Text(
                            t("这一档要先在本机跑一遍安装器里的 processors，会跳到安装器页面、可能要好几分钟。") +
                                t("中途别锁屏，想停随时可以取消。"),
                            color = PclMuted,
                            fontSize = 11.sp,
                        )
                    }
                    when {
                        vm.loaderBusy -> Text(t("正在拉构建号…"), color = PclMuted, fontSize = 12.sp)
                        vm.loaderBuilds.isEmpty() -> Text(t("这个 MC 版本没有可用构建"), color = PclMuted, fontSize = 12.sp)
                        else -> LazyColumn(Modifier.height(240.dp)) {
                            items(vm.loaderBuilds.toList(), key = { it.id }) { build ->
                                TextButton(
                                    onClick = {
                                        vm.installLoader(mc, build.id)
                                        loaderFor = null
                                    },
                                ) {
                                    Text(
                                        build.label + if (build.stable) "" else t("（预览）"),
                                        color = if (build.stable) PclGreen else PclMuted,
                                    )
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { loaderFor = null }) { Text(t("关闭")) } },
        )
    }

    renaming?.let { card -> TextPrompt(t("重命名版本"), card.id) { value -> vm.renameVersion(card.id, value); renaming = null } }
    copying?.let { card -> TextPrompt(t("复制版本"), "${card.id}-copy") { value -> vm.copyVersion(card.id, value); copying = null } }
}

/** 一次性的单行输入对话框，改名 / 复制 / 加服务器都用它。 */
@Composable
fun TextPrompt(title: String, initial: String, onDone: (String) -> Unit) {
    var text by remember(initial) { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = { onDone(initial) },
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                singleLine = true,
                colors = FieldColors(),
            )
        },
        confirmButton = {
            TextButton(onClick = { onDone(text) }, enabled = text.isNotBlank()) {
                Text(t("确定"), color = PclGreen)
            }
        },
        dismissButton = { TextButton(onClick = { onDone(initial) }) { Text(t("取消")) } },
    )
}
