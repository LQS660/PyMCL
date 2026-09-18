package com.pymcl.mobile.ui

import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.data.byLabel
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.vm.AppViewModel

/** 实例页顶部的四个分区。用枚举而不是中文名当键：显示名走词表，切了语言选中项不丢。 */
private enum class Section { Instances, Versions, Content, Saves }

private fun sectionLabel(section: Section): String = when (section) {
    Section.Instances -> t("实例")
    Section.Versions -> t("版本")
    Section.Content -> t("内容")
    Section.Saves -> t("存档")
}

/**
 * 实例页：新建 / 切换 / 删除实例，下面挂着「当前实例」的四个二级页。
 *
 * 版本 / 模组 / 存档按语义都属于某一个实例，所以收在这里而不是占底栏一格——
 * 底栏已经六格，再加就挤成图标堆了（与 opus-5-3 对齐过）。外壳 MainTab 按这个名字接线。
 */
@Composable
fun InstanceScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var newName by remember { mutableStateOf("") }
    var section by remember { mutableStateOf(Section.Instances) }

    LaunchedEffect(Unit) { vm.refreshLocal() }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("实例"), t("{0} 个实例 · 当前 {1}").fmt(vm.instances.size, vm.instance))
        ChipRow("", Section.entries.map(::sectionLabel), sectionLabel(section)) { picked ->
            section = Section.entries.byLabel(picked, ::sectionLabel) ?: Section.Instances
        }

        when (section) {
            Section.Versions -> {
                VersionManageScreen(vm, Modifier.weight(1f))
                return@Column
            }
            Section.Content -> {
                // 一页吃六类：模组 / 整合包 / 资源包 / 光影包 / 数据包 / 世界
                ContentLibraryScreen(vm, Modifier.weight(1f))
                return@Column
            }
            Section.Saves -> {
                SavesScreen(vm, Modifier.weight(1f))
                return@Column
            }
            Section.Instances -> Unit
        }

        Spacer(Modifier.height(8.dp))
        SearchRow(
            value = newName,
            label = t("新实例名"),
            actionText = t("新建"),
            onValueChange = { newName = it },
            onAction = {
                vm.createInstance(newName.ifBlank { t("游戏") })
                newName = ""
            },
        )
        ErrorLine(vm)
        Spacer(Modifier.height(8.dp))

        if (vm.instances.isEmpty()) {
            EmptyHint(t("还没有实例，上面起个名字点「新建」"), Modifier.weight(1f))
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(vm.instances, key = { it.name }) { inst ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(
                            Modifier
                                .weight(1f)
                                .clickable { vm.selectInstance(inst.name) },
                        ) {
                            Row {
                                Text(inst.name, fontWeight = FontWeight.SemiBold)
                                if (inst.name == vm.instance) {
                                    Spacer(Modifier.height(0.dp))
                                    Text(t("  · 当前"), color = PclGreen, fontSize = 12.sp)
                                }
                            }
                            Text(t("{0} 个版本").fmt(inst.versions.size), color = PclMuted, fontSize = 12.sp)
                            Text(
                                inst.path,
                                color = PclMuted,
                                fontSize = 10.sp,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        // 桌面实例卡上的「导出为 .mrpack」；落到 exports/<实例>.mrpack
                        TextButton(onClick = { vm.exportModpack(inst.name) }, enabled = !vm.busy) {
                            Text(t("导出"), color = PclGreen)
                        }
                        TextButton(onClick = { vm.deleteInstance(inst.name) }) {
                            Text(t("删除"), color = ErrorRed)
                        }
                    }
                }
            }
        }
    }
}
