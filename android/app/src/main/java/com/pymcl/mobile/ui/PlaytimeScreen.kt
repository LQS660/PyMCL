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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t

/** 游玩时长：总时长 + 按实例、按版本的明细，数据和桌面 playtime.json 同一份。 */
@Composable
fun PlaytimeScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var confirming by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.reloadPlaytime() }

    // 排序结果只随数据变，不随每次重组重排
    val rows = remember(vm.playtime) {
        vm.playtime.entries
            .filter { it.value.total > 0 }
            .sortedByDescending { it.value.total }
    }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("游玩时长"), t("总计 {0}").fmt(vm.totalPlaytimeText())) {
            TextButton(onClick = { confirming = true }, enabled = rows.isNotEmpty()) {
                Text(t("清除记录"), color = ErrorRed)
            }
        }
        Spacer(Modifier.height(8.dp))

        if (rows.isEmpty()) {
            EmptyHint(t("还没有游玩记录\n启动游戏后会自动记录"), Modifier.weight(1f))
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(rows, key = { it.key }) { (name, stat) ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(name, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Text(vm.formatPlaytime(stat.total), color = PclGreen, fontSize = 13.sp)
                    }
                    Spacer(Modifier.height(4.dp))
                    stat.versions.entries
                        .filter { it.value > 0 }
                        .sortedByDescending { it.value }
                        .forEach { (version, seconds) ->
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text(version, color = PclMuted, fontSize = 12.sp, modifier = Modifier.weight(1f))
                                Pill(vm.formatPlaytime(seconds))
                            }
                        }
                    Text(t("{0} 次游玩记录").fmt(stat.sessions.size), color = PclMuted, fontSize = 11.sp)
                }
            }
        }
    }

    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text(t("确认清除")) },
            text = { Text(t("清除所有游玩时长记录？此操作不可恢复。")) },
            confirmButton = {
                TextButton(onClick = {
                    vm.clearPlaytime()
                    confirming = false
                }) { Text(t("清除"), color = ErrorRed) }
            },
            dismissButton = { TextButton(onClick = { confirming = false }) { Text(t("取消")) } },
        )
    }
}
