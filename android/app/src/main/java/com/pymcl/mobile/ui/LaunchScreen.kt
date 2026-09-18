package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.NewsRepo
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel

/**
 * 启动页资讯卡，对齐桌面 `launch_page._load_news`：缓存先上屏，再后台拉一次覆盖，
 * 断网时看到的是上一次那几条而不是一张空卡。
 *
 * 手机竖屏比桌面那张卡矮得多，所以正文区限高自滚：六条还是六条，但不会把下面的日志挤没。
 */
@Composable
private fun NewsCard(vm: AppViewModel) {
    LaunchedEffect(Unit) { vm.reloadNews() }
    CardBox {
        SectionHeader(t("Minecraft 新闻"), t("来自 Mojang 官方启动器内容源")) {
            TextButton(onClick = { vm.reloadNews(force = true) }, enabled = !vm.newsBusy) {
                Text(t("刷新"), color = PclGreen)
            }
        }
        if (vm.news.isEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text(t("暂无新闻"), color = PclMuted, fontSize = 12.sp)
            return@CardBox
        }
        Column(
            Modifier
                .fillMaxWidth()
                .heightIn(max = 132.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            vm.news.take(NewsRepo.CARD_ROWS).forEach { row ->
                Spacer(Modifier.height(6.dp))
                Text(row.title, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = PclText)
                // 摘要只留 80 字，跟桌面 _fill_news 一样：卡片上要的是一眼扫过，不是读全文
                val detail = row.body.ifBlank { row.version }
                if (detail.isNotBlank()) {
                    Text(detail.take(80), color = PclMuted, fontSize = 11.sp)
                }
            }
        }
    }
}

/** 启动页：选实例 / 版本 / 用户名 / 内存，开打，下面跟着实时日志。 */
@Composable
fun LaunchScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    LaunchedEffect(vm.instance) { vm.reloadPlaytime() }

    Column(
        modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CardBox {
            SectionHeader(
                t("启动游戏"),
                t("实例 {0} · {1}").fmt(vm.instance, vm.versionId.ifBlank { t("未选版本") }),
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryBtn(t("启动游戏"), enabled = !vm.busy && vm.versionId.isNotBlank()) { vm.launchGame() }
                OutlinedButton(onClick = { vm.cancelTask() }, enabled = vm.busy) { Text(t("停止")) }
                // 桌面点启动前那一步预检，这里做成独立入口：只查不启，结果卡上每条都能跳去修
                OutlinedButton(onClick = { vm.runPreflight() }, enabled = !vm.busy) { Text(t("启动前体检")) }
            }
            Spacer(Modifier.height(6.dp))
            Text(t("运行时 {0}").fmt(vm.runtimePkg ?: t("点启动会自动装 JRE")), color = PclGreen, fontSize = 12.sp)
            Text(t("累计游玩 {0}").fmt(vm.totalPlaytimeText()), color = PclMuted, fontSize = 12.sp)
        }

        BusyBar(vm)
        ErrorLine(vm)
        PreflightCard(vm)
        CrashCard(vm)

        CardBox {
            Text(t("启动配置"), fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            ChipRow(t("实例"), vm.instances.map { it.name }, vm.instance) { vm.selectInstance(it) }
            ChipRow(t("已装版本"), vm.installed.toList(), vm.versionId) { vm.versionId = it }
            OutlinedTextField(
                value = vm.username,
                onValueChange = {
                    vm.username = it
                    vm.persistUiDebounced()
                },
                label = { Text(t("离线用户名")) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = FieldColors(),
            )
            Text(t("内存 {0} MB").fmt(vm.memoryMb), color = PclMuted, fontSize = 12.sp)
            Slider(
                value = vm.memoryMb.toFloat(),
                onValueChange = { vm.memoryMb = it.toInt() },
                onValueChangeFinished = { vm.persistUi() },
                valueRange = 512f..8192f,
                colors = SliderDefaults.colors(thumbColor = PclGreen, activeTrackColor = PclGreen),
            )
        }

        NewsCard(vm)

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(top = 2.dp),
        ) {
            Text(t("日志"), fontWeight = FontWeight.SemiBold)

            Text(
                vm.log,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
                color = PclText,
            )
        }
    }
}
