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
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.byLabel
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.SaveEntry
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel
import java.io.File

/** 存档管理：存档 / 备份 / 截图 / 崩溃报告 / 日志五档，备份还原导出都在这里。 */
@Composable
fun SavesScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var deleting by remember { mutableStateOf<String?>(null) }
    var renaming by remember { mutableStateOf<SaveEntry?>(null) }
    var datapackFor by remember { mutableStateOf<SaveEntry?>(null) }

    LaunchedEffect(vm.instance, vm.versionId, vm.saveKind) { vm.reloadSaves() }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("存档管理"), t("目录 {0}").fmt(vm.gameDir.absolutePath))
        Spacer(Modifier.height(6.dp))
        // 类型名是键（vm 与目录名都按它走），芯片上显示译文，点回来再反查成键
        ChipRow(t("类型"), AppViewModel.SAVE_KINDS.map(::t), t(vm.saveKind)) { picked ->
            vm.selectSaveKind(AppViewModel.SAVE_KINDS.byLabel(picked, ::t) ?: picked)
        }
        BusyBar(vm)
        ErrorLine(vm)
        Spacer(Modifier.height(4.dp))

        when (vm.saveKind) {
            AppViewModel.SAVE_KIND_SAVES -> SaveList(
                vm,
                Modifier.weight(1f),
                onDelete = { deleting = it },
                onRename = { renaming = it },
                onDatapack = { datapackFor = it },
            )
            AppViewModel.SAVE_KIND_BACKUPS -> BackupList(vm, Modifier.weight(1f))
            else -> MediaList(vm, Modifier.weight(1f))
        }
    }

    deleting?.let { name ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(t("删除存档")) },
            text = { Text(t("确定删除「{0}」？删掉就找不回来了，建议先备份。").fmt(name)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteSave(name)
                    deleting = null
                }) { Text(t("删除"), color = ErrorRed) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(t("取消")) } },
        )
    }

    renaming?.let { save ->
        TextPrompt(t("重命名存档"), save.name) { value ->
            if (value != save.name) vm.renameSave(save.name, value)
            renaming = null
        }
    }

    datapackFor?.let { save ->
        val packs = remember(save.name) { vm.datapacks() }
        AlertDialog(
            onDismissRequest = { datapackFor = null },
            title = { Text(t("把数据包装进「{0}」").fmt(save.name)) },
            text = {
                if (packs.isEmpty()) {
                    Text(t("datapacks 目录是空的，先到下载页装数据包。"))
                } else {
                    Column {
                        packs.forEach { pack ->
                            TextButton(onClick = {
                                vm.installDatapack(pack, save.name)
                                datapackFor = null
                            }) { Text(pack, color = PclGreen) }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { datapackFor = null }) { Text(t("关闭")) } },
        )
    }
}

@Composable
private fun SaveList(
    vm: AppViewModel,
    modifier: Modifier,
    onDelete: (String) -> Unit,
    onRename: (SaveEntry) -> Unit,
    onDatapack: (SaveEntry) -> Unit,
) {
    if (vm.saves.isEmpty()) {
        EmptyHint(t("这个目录下还没有存档"), modifier)
        return
    }
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(vm.saves, key = { it.name }) { save ->
            CardBox {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(save.name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(Saves.formatSize(save.bytes), color = PclMuted, fontSize = 11.sp)
                    }
                    if (save.icon.isNotBlank()) Pill(t("有封面"))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { vm.backupSave(save.name) }) { Text(t("备份"), color = PclGreen) }
                    TextButton(onClick = {
                        vm.exportSave(save.name, File(vm.instDir, "exports/${save.name}.zip"))
                    }) { Text(t("导出 zip"), color = PclGreen) }
                    TextButton(onClick = { onDatapack(save) }) { Text(t("数据包"), color = PclGreen) }
                    TextButton(onClick = { onRename(save) }) { Text(t("改名"), color = PclGreen) }
                    TextButton(onClick = { onDelete(save.name) }) { Text(t("删除"), color = ErrorRed) }
                }
            }
        }
    }
}

@Composable
private fun BackupList(vm: AppViewModel, modifier: Modifier) {
    if (vm.backups.isEmpty()) {
        EmptyHint(t("还没有备份。到「存档」里选一个点「备份」"), modifier)
        return
    }
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(vm.backups, key = { it.name }) { backup ->
            CardBox {
                Text(backup.name, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Text(
                    t("来自「{0}」 · {1}").fmt(backup.save, Saves.formatSize(backup.bytes)),
                    color = PclMuted,
                    fontSize = 11.sp,
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { vm.restoreBackup(backup.name) }) { Text(t("还原"), color = PclGreen) }
                    TextButton(onClick = { vm.deleteBackup(backup.name) }) { Text(t("删除"), color = ErrorRed) }
                }
                Text(t("同名存档已存在时会另存为「原名-还原」，不会覆盖。"), color = PclMuted, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun MediaList(vm: AppViewModel, modifier: Modifier) {
    if (vm.media.isEmpty()) {
        EmptyHint(t("{0}目录是空的").fmt(t(vm.saveKind)), modifier)
        return
    }
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items(vm.media, key = { it.path }) { row ->
            CardBox {
                Text(row.name, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(Saves.formatSize(row.bytes), color = PclMuted, fontSize = 11.sp)
            }
        }
    }
}
