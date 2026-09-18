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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.ModUpdates
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.ModEntry
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel
import java.io.File

/** 模组管理：启停、删除、导入、导出，目标在「大锅饭」和独立版本之间切。 */
@Composable
fun ModsScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var importing by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<ModEntry?>(null) }

    LaunchedEffect(vm.instance, vm.modTarget) { vm.reloadMods() }

    // 过滤在内存里做，用户每敲一个字不回盘重列目录
    val rows = remember(vm.modQuery, vm.mods.size, vm.mods.toList()) { vm.filteredMods() }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("模组管理"), vm.modsSummary())
        Spacer(Modifier.height(6.dp))
        ChipRow(
            t("安装目标"),
            vm.modTargets.map { it.label },
            vm.modTargets.firstOrNull { it.value == vm.modTarget }?.label.orEmpty(),
        ) { label ->
            vm.selectModTarget(vm.modTargets.firstOrNull { it.label == label }?.value.orEmpty())
        }
        Text(
            t("「大锅饭」是所有共用版本合吃的那一份；把某个版本切成「独立」后，它会单独列出来，改它不影响别人。"),
            color = PclMuted,
            fontSize = 11.sp,
        )
        Spacer(Modifier.height(6.dp))
        SearchRow(
            value = vm.modQuery,
            label = t("按文件名筛选"),
            actionText = t("导入 jar"),
            onValueChange = { vm.modQuery = it },
            onAction = { importing = true },
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.checkModUpdates() }, enabled = !vm.modUpdateBusy && vm.mods.isNotEmpty()) {
                Text(if (vm.modUpdateBusy) t("检查中…") else t("检查更新"), color = PclGreen)
            }
            if (vm.modUpdateSummary.isNotBlank()) {
                Text(vm.modUpdateSummary, color = PclMuted, fontSize = 11.sp)
            }
        }
        ErrorLine(vm)
        UpdatesCard(vm)
        Spacer(Modifier.height(6.dp))

        if (rows.isEmpty()) {
            EmptyHint(
                if (vm.mods.isEmpty()) t("还没有安装模组，点「导入 jar」或到「下载」页安装") else t("没有匹配的模组"),
                Modifier.weight(1f),
            )
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(rows, key = { it.filename }) { mod ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                mod.filename,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 13.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                Saves.formatSize(mod.bytes) + if (mod.enabled) "" else t(" · 已禁用"),
                                color = PclMuted,
                                fontSize = 11.sp,
                            )
                        }
                        Switch(
                            checked = mod.enabled,
                            onCheckedChange = { vm.setModEnabled(mod.filename, it) },
                            colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                        )
                        TextButton(onClick = {
                            vm.exportMod(mod.filename, File(vm.instDir, "exports"))
                        }) { Text(t("导出"), color = PclGreen) }
                        TextButton(onClick = { deleting = mod }) { Text(t("删除"), color = ErrorRed) }
                    }
                }
            }
        }
    }

    if (importing) {
        ImportPathPrompt { path ->
            if (path.isNotBlank()) vm.importMod(File(path))
            importing = false
        }
    }

    deleting?.let { mod ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(t("删除确认")) },
            text = { Text(t("将删除模组文件「{0}」，不可恢复。").fmt(mod.filename)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteMod(mod.filename)
                    deleting = null
                }) { Text(t("删除"), color = ErrorRed) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(t("取消")) } },
        )
    }
}

/** 查更新的结果。只列真的能更新的那些；查不到的原因收在概要里，不占一行。 */
@Composable
private fun UpdatesCard(vm: AppViewModel) {
    val rows = ModUpdates.updatable(vm.modUpdates.toList())
    if (rows.isEmpty()) return
    CardBox {
        Text(t("可更新 {0} 个").fmt(rows.size), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
        rows.forEach { row ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(row.entry.filename, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(ModUpdates.describe(row), color = PclMuted, fontSize = 11.sp)
                }
                TextButton(onClick = { vm.applyModUpdate(row) }, enabled = !vm.busy) {
                    Text(t("更新"), color = PclGreen)
                }
            }
        }
        Text(t("更新后旧版会被停用而不是删掉，新版起不来时还能换回去。"), color = PclMuted, fontSize = 10.sp)
    }
}

@Composable
private fun ImportPathPrompt(onDone: (String) -> Unit) {
    var path by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { onDone("") },
        title = { Text(t("导入 jar")) },
        text = {
            Column {
                Text(t("填本机上 jar 的完整路径；系统选择器的接线归设置域那一半。"), color = PclMuted, fontSize = 12.sp)
                OutlinedTextField(
                    value = path,
                    onValueChange = { path = it },
                    label = { Text("/sdcard/Download/sodium.jar") },
                    singleLine = true,
                    colors = FieldColors(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onDone(path) }, enabled = path.isNotBlank()) {
                Text(t("导入"), color = PclGreen)
            }
        },
        dismissButton = { TextButton(onClick = { onDone("") }) { Text(t("取消")) } },
    )
}
