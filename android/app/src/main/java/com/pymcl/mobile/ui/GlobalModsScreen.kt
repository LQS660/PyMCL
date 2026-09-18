package com.pymcl.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
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
import com.pymcl.mobile.data.GlobalMods
import com.pymcl.mobile.data.Mods
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.ModEntry
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.vm.AppViewModel

/**
 * 全局（共享）模组池，对齐桌面 `app/pages/global_mods_dialog.py`：列出共享池里的 jar、
 * 逐个启停、外加桌面对话框没有的删除。入口跟桌面一样挂在设置页。
 *
 * 桌面那颗「打开文件夹」按钮在这儿换成「放入 jar」：共享池躺在应用私有目录里，
 * 系统文件管理器根本进不去，能把 jar 送进来的只有 SAF 选择器。目录路径照样列出来，
 * 方便对着日志核对。
 */
@Composable
fun GlobalModsScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    val c = LocalPclColors.current
    var deleting by remember { mutableStateOf<ModEntry?>(null) }
    // 扩展名由 Mods.install 再校一遍，选择器这里只做宽松筛选——网盘 provider 给的
    // MIME 往往是 application/octet-stream，按 jar 过滤会把文件全灰掉。
    val pickJar = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) vm.importGlobalMod(uri)
    }

    LaunchedEffect(vm.instance) { vm.reloadGlobalMods() }

    val rows = vm.globalMods.toList()

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(t("全局 Mod"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                        Text(
                            t("共享池里的 jar，所有没开「隔离 Mod」的版本都吃这一份"),
                            color = c.muted,
                            fontSize = 12.sp,
                        )
                    }
                    PclLink(t("放入 jar")) { pickJar.launch(arrayOf("*/*")) }
                }
                ErrorLine(vm)
            }
        }

        item(key = "where") {
            PclCard {
                PclSectionTitle(t("共享池"), Mods.summary(rows))
                PclKeyValue(t("目录"), GlobalMods.dir(vm.instDir).absolutePath)
                PclKeyValue(
                    t("生效版本"),
                    vm.globalModVersions.toList().ifEmpty { listOf(t("还没有装任何版本")) }.joinToString(" / "),
                )
                Text(
                    t("开了「隔离 Mod」的版本各用各的一份，不受这一页影响。"),
                    color = c.muted,
                    fontSize = 11.sp,
                )
            }
        }

        if (rows.isEmpty()) {
            item(key = "empty") { PclCard { PclEmpty(t("共享池还是空的，点右上角「放入 jar」放一个进来。")) } }
        }

        items(rows, key = { it.path }) { row ->
            PclCard {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            row.filename,
                            fontWeight = FontWeight.SemiBold,
                            color = c.text,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            Saves.formatSize(row.bytes) + (if (row.enabled) "" else t(" · 已禁用")),
                            color = c.muted,
                            fontSize = 11.sp,
                        )
                    }
                    Switch(
                        checked = row.enabled,
                        onCheckedChange = { vm.setGlobalModEnabled(row.filename, it) },
                        colors = SwitchDefaults.colors(checkedTrackColor = c.accent),
                    )
                    PclLink(t("删除")) { deleting = row }
                }
            }
        }
    }

    deleting?.let { row ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(t("删除确认")) },
            text = { Text(t("将从共享池删除「{0}」，不可恢复。").fmt(row.filename)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteGlobalMod(row.filename)
                    deleting = null
                }) { Text(t("删除"), color = ErrorRed) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(t("取消")) } },
        )
    }
}
