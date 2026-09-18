package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.DownloadDock
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.TaskCenter
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.TaskInfo
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel

/** 任务中心：进度、速度、可展开日志；整合包安装默认把日志展开。 */
@Composable
fun TasksScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxSize()) {
        SectionHeader(t("下载任务"), t("进行中 {0} · 共 {1}").fmt(vm.activeDownloads, vm.tasks.size)) {
            TextButton(
                onClick = { vm.clearFinishedTasks() },
                enabled = vm.tasks.any { it.done },
            ) { Text(t("清除已完成"), color = PclGreen) }
        }
        Spacer(Modifier.height(8.dp))

        if (vm.tasks.isEmpty()) {
            EmptyHint(t("暂无任务 —— 去下载板块里装版本 / 整合包 / 模组，或备份存档"), Modifier.weight(1f))
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(vm.tasks, key = { it.id }) { task -> TaskCard(vm, task) }
        }
    }
}

/**
 * 悬浮下载坞：压在内容区底部的一条，不论在哪一页都能看见当前下载的进度与速度，
 * 倒着点一下能就地摊开日志，不用先跳到任务页。
 *
 * 露不露面交给 [DownloadDock.visible] 判——隐藏页集合与桌面共用同一份定义。
 */
@Composable
fun DownloadDockBar(vm: AppViewModel, pageKey: String, modifier: Modifier = Modifier) {
    if (!DownloadDock.visible(vm.activeDownloads, pageKey)) return
    val task = DownloadDock.current(vm.tasks.toList()) ?: return
    val c = LocalPclColors.current
    var expanded by remember(task.id) { mutableStateOf(TaskCenter.autoExpandLog(task.title)) }
    val (status, speed) = TaskCenter.splitProgressMessage(task.message)

    Column(
        modifier
            .fillMaxWidth()
            .background(c.panel(Settings.int(SettingsKeys.UI_SIDEBAR_OPACITY, 85)), RoundedCornerShape(10.dp))
            .border(1.dp, c.line, RoundedCornerShape(10.dp))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                t("{0}（{1}）").fmt(t("下载任务"), vm.activeDownloads),
                fontWeight = FontWeight.SemiBold,
                color = c.text,
                fontSize = 13.sp,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                status.ifBlank { task.title },
                color = c.muted,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (speed.isNotBlank()) Text(speed, color = c.muted, fontSize = 12.sp)
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) t("收起日志") else t("显示日志"), color = c.accent, fontSize = 12.sp)
            }
        }
        LinearProgressIndicator(
            progress = { TaskCenter.percent(task.current, task.total) / 100f },
            modifier = Modifier.fillMaxWidth(),
            color = c.accent,
        )
        if (expanded) {
            Text(
                task.log.joinToString("\n").ifBlank { t("安装过程的详细日志会显示在这里") },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(120.dp)
                    .padding(top = 6.dp)
                    .verticalScroll(rememberScrollState()),
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
                color = c.text,
            )
        }
    }
}

@Composable
private fun TaskCard(vm: AppViewModel, task: TaskInfo) {
    var expanded by remember(task.id) { mutableStateOf(TaskCenter.autoExpandLog(task.title)) }
    val (status, speed) = TaskCenter.splitProgressMessage(task.message)

    CardBox {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(task.title, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) t("收起日志") else t("显示日志"), color = PclGreen)
            }
            if (!task.done) {
                TextButton(onClick = { vm.cancelTask() }) { Text(t("取消"), color = ErrorRed) }
            }
        }
        if (task.total > 0 && !task.done) {
            LinearProgressIndicator(
                progress = { TaskCenter.percent(task.current, task.total) / 100f },
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                color = PclGreen,
            )
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (task.done) TaskCenter.summary(task) else status.ifBlank { t("排队中…") },
                color = if (task.done && !task.success) ErrorRed else PclMuted,
                fontSize = 12.sp,
                modifier = Modifier.weight(1f),
            )
            if (speed.isNotBlank()) Text(speed, color = PclMuted, fontSize = 12.sp)
        }
        if (expanded) {
            Text(
                task.log.joinToString("\n").ifBlank { t("安装过程的详细日志会显示在这里") },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(180.dp)
                    .padding(top = 6.dp)
                    .verticalScroll(rememberScrollState()),
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
                color = PclText,
            )
        }
    }
}
