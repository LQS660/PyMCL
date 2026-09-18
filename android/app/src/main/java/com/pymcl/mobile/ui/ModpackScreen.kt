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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import com.pymcl.mobile.data.Names
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel
import java.io.File

/** 整合包导入：Modrinth 的 .mrpack 与 CurseForge 的 manifest.json 都认，装成一个独立版本。 */
@Composable
fun ModpackScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var path by remember { mutableStateOf("") }
    val info = vm.pendingModpack

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("整合包导入"), t("装进实例 {0}，自动切成完全独立").fmt(vm.instance))
        Spacer(Modifier.height(6.dp))
        SearchRow(
            value = path,
            label = t("整合包完整路径（.mrpack / .zip）"),
            actionText = t("读取"),
            actionEnabled = path.isNotBlank() && !vm.busy,
            onValueChange = { path = it },
            onAction = { vm.inspectModpack(File(path)) },
        )
        BusyBar(vm)
        ErrorLine(vm)
        Spacer(Modifier.height(6.dp))

        // 桌面实例页那条「导出为 .mrpack」：模组能在 Modrinth 认出来的写下载地址，其余连同配置进 overrides
        CardBox {
            Text(t("导出整合包"), fontWeight = FontWeight.SemiBold)
            Text(
                t("把实例 {0} 的模组与 config / 资源包 / 光影 / 数据包打成 .mrpack，落在 exports/ 下").fmt(
                    vm.instance + if (vm.versionId.isBlank()) "" else " · ${vm.versionId}",
                ),
                color = PclMuted,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(6.dp))
            PrimaryBtn(t("导出为 .mrpack"), enabled = !vm.busy) { vm.exportModpack() }
        }
        Spacer(Modifier.height(6.dp))

        if (info == null) {
            EmptyHint(
                t("先填整合包路径再点「读取」。\n读完这里会列出它要装哪些文件，确认无误再开始。"),
                Modifier.weight(1f),
            )
            return@Column
        }

        val versionName = remember(info) {
            val base = Names.sanitize(info.name.ifBlank { "modpack" })
            if (info.mcVersion.isBlank()) base else "$base-${info.mcVersion}"
        }
        CardBox {
            Text(info.name.ifBlank { t("未命名整合包") }, fontWeight = FontWeight.SemiBold)
            Text(
                "${info.format.label} · Minecraft ${info.mcVersion.ifBlank { "?" }} · ${info.loaderLabel}",
                color = PclMuted,
                fontSize = 12.sp,
            )
            Text(
                t("{0} 个直链文件 · {1} 个 CurseForge 引用").fmt(info.files.size, info.refs.size),
                color = PclMuted,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                PrimaryBtn(t("装成版本「{0}」").fmt(versionName), enabled = !vm.busy) {
                    vm.installModpack(File(path), versionName)
                }
                TextButton(onClick = { vm.pendingModpack = null }) { Text(t("取消"), color = PclGreen) }
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(t("清单里的文件"), color = PclMuted, fontSize = 12.sp)
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(info.files, key = { it.path }) { file ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        file.path,
                        fontSize = 12.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    if (file.size > 0) {
                        Text(Saves.formatSize(file.size), color = PclMuted, fontSize = 11.sp)
                    }
                    if (!file.clientSupported) Pill(t("服务端专用"), PclMuted)
                }
            }
            items(info.refs, key = { "${it.projectId}-${it.fileId}" }) { ref ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "CurseForge ${ref.projectId} / ${ref.fileId}",
                        fontSize = 12.sp,
                        modifier = Modifier.weight(1f),
                    )
                    if (!ref.required) Pill(t("可选"), PclMuted)
                }
            }
        }
    }
}
