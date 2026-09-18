package com.pymcl.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pymcl.mobile.data.TerracottaCore
import com.pymcl.mobile.data.TerracottaRepo
import com.pymcl.mobile.data.TerracottaVpnCoordinator
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel
import com.pymcl.mobile.vm.MultiplayerViewModel

/**
 * 联机页：局域网直连、陶瓦开房 / 加入、服务器列表。
 *
 * 状态与内核调用全走 [MultiplayerViewModel]（它只管联机这一摊，见交付里的职责边界）；
 * 用户名、实例这些跨页的东西还是从 [AppViewModel] 取。
 *
 * VPN 授权弹窗必须由**界面**发起——`VpnService.prepare` 返回的 Intent 只能从
 * Activity 起，所以这里用 rememberLauncherForActivityResult 挂一个消费者给
 * [TerracottaVpnCoordinator]，离开页面时摘掉。
 */
@Composable
fun MultiplayerScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    val mp: MultiplayerViewModel = viewModel()
    var showServers by remember { mutableStateOf(false) }
    var showLogs by remember { mutableStateOf<String?>(null) }
    val clipboard = LocalClipboardManager.current

    val consent = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        TerracottaVpnCoordinator.onConsentResult(result.resultCode == android.app.Activity.RESULT_OK)
    }

    DisposableEffect(Unit) {
        TerracottaVpnCoordinator.attachUi(
            launcher = { intent ->
                runCatching { consent.launch(intent) }.isSuccess
            },
            notice = { message -> com.pymcl.mobile.vm.TerracottaNotices.push(message) },
        )
        mp.onEnter()
        onDispose {
            TerracottaVpnCoordinator.detachUi()
            mp.onLeave()
        }
    }

    if (showServers) {
        Column(modifier.fillMaxSize()) {
            SectionHeader(t("联机")) {
                TextButton(onClick = { showServers = false }) { Text(t("回联机"), color = PclGreen) }
            }
            ServersScreen(vm, Modifier.weight(1f))
        }
        return
    }

    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        SectionHeader(t("联机"), mp.snapshot.label) {
            TextButton(onClick = { showServers = true }) { Text(t("服务器列表"), color = PclGreen) }
        }

        mp.notice?.let { message ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(message, color = ErrorRed, fontSize = 12.sp, modifier = Modifier.weight(1f))
                TextButton(onClick = { mp.dismissNotice() }) { Text(t("知道了"), color = PclGreen) }
            }
        }
        mp.fatal?.let { Text(it, color = ErrorRed, fontSize = 12.sp) }

        TerracottaCard(vm, mp, onCopy = { clipboard.setText(AnnotatedString(it)) })
        RoomMembersCard(mp)
        DirectConnectCard(vm)
        LanCard(vm)
        NodesCard()

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { showLogs = t("读取中…"); mp.dumpLogs { showLogs = it } }) {
                Text(t("导出内核日志"))
            }
            OutlinedButton(onClick = { clipboard.setText(AnnotatedString(TerracottaCore.HOME)) }) {
                Text(t("复制项目主页"))
            }
        }
        Text(TerracottaCore.COPYRIGHT, color = PclMuted, fontSize = 10.sp)
    }

    showLogs?.let { text ->
        AlertDialog(
            onDismissRequest = { showLogs = null },
            title = { Text(t("陶瓦内核日志")) },
            text = {
                Text(
                    text.takeLast(4000).ifBlank { t("内核还没起来，没有日志") },
                    fontFamily = FontFamily.Monospace,
                    fontSize = 10.sp,
                    modifier = Modifier.height(320.dp).verticalScroll(rememberScrollState()),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    clipboard.setText(AnnotatedString(text))
                    showLogs = null
                }) { Text(t("复制"), color = PclGreen) }
            },
            dismissButton = { TextButton(onClick = { showLogs = null }) { Text(t("关闭")) } },
        )
    }
}

@Composable
private fun TerracottaCard(vm: AppViewModel, mp: MultiplayerViewModel, onCopy: (String) -> Unit) {
    val snapshot = mp.snapshot
    CardBox {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(t("陶瓦联机"), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Pill(snapshot.label, if (mp.connected) PclGreen else PclMuted)
        }
        mp.kernelInfo?.let { Text(it, color = PclMuted, fontSize = 11.sp) }
        if (snapshot.difficultyHint.isNotBlank()) {
            Text(snapshot.difficultyHint, color = PclMuted, fontSize = 12.sp)
        }
        if (snapshot.error.isNotBlank()) {
            Text(snapshot.error, color = ErrorRed, fontSize = 12.sp)
            if (snapshot.errorHint.isNotBlank()) {
                Text(snapshot.errorHint, color = PclMuted, fontSize = 11.sp)
            }
        }

        if (snapshot.room.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(snapshot.room, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                TextButton(onClick = { onCopy(snapshot.room) }) { Text(t("复制房间号"), color = PclGreen) }
            }
            Text(
                t("好友进游戏后在多人游戏里双击「{0}」即可。").fmt(TerracottaCore.LOBBY_NAME),
                color = PclMuted,
                fontSize = 11.sp,
            )
        }

        Spacer(Modifier.height(6.dp))
        OutlinedTextField(
            value = mp.roomInput,
            onValueChange = { mp.onRoomInput(it) },
            label = { Text(t("房间号 / 邀请码（粘一整段也认）")) },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            colors = FieldColors(),
        )
        if (mp.roomHint.isNotBlank()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    mp.roomHint,
                    color = if (mp.normalizedRoom != null) PclGreen else ErrorRed,
                    fontSize = 11.sp,
                    modifier = Modifier.weight(1f),
                )
                if (mp.normalizedRoom != null && mp.normalizedRoom != mp.roomInput) {
                    TextButton(onClick = { mp.applyNormalized() }) { Text(t("用它"), color = PclGreen) }
                }
            }
        }

        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            PrimaryBtn(t("开房间"), enabled = !mp.working && !mp.connected) { mp.host(vm.username) }
            PrimaryBtn(t("加入"), enabled = !mp.working && !mp.connected && mp.normalizedRoom != null) {
                mp.join(vm.username)
            }
            if (mp.connected) {
                OutlinedButton(onClick = { mp.disconnect() }, enabled = !mp.busy) { Text(t("断开")) }
            }
        }
        Text(
            t("开房前先在游戏里「对局域网开放」，内核要扫到那个世界才开得起来。"),
            color = PclMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun RoomMembersCard(mp: MultiplayerViewModel) {
    val profiles = mp.snapshot.profiles
    if (profiles.isEmpty()) return
    CardBox {
        Text(t("房间成员 {0}").fmt(profiles.size), fontWeight = FontWeight.SemiBold)
        profiles.forEach { p ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(p.name, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Text("${p.vendor} · ${p.kind}", color = PclMuted, fontSize = 11.sp)
            }
        }
    }
}

/**
 * 公网直连，对齐桌面 `terracotta_direct_connect`：房主已经有公网地址（陶瓦房主端、端口映射、
 * 服务器）时不走房间号，填地址直接带 `--server/--port` 进游戏；地址同时写成多人列表里的
 * 「陶瓦联机大厅」那一行。解析走 [TerracottaCore.parseDirect]，本机地址与坏端口当场拦住。
 */
@Composable
private fun DirectConnectCard(vm: AppViewModel) {
    var address by rememberSaveable { mutableStateOf("") }
    var port by rememberSaveable { mutableStateOf("") }
    val target = remember(address, port) { TerracottaCore.parseDirect(address, port) }
    val ready = address.isNotBlank() && target.error.isEmpty()
    CardBox {
        Text(t("公网直连"), fontWeight = FontWeight.SemiBold)
        Text(
            t("房主有公网地址时不用房间号：填地址直接进房，进游戏后到「多人游戏」双击「{0}」。").fmt(TerracottaCore.LOBBY_NAME),
            color = PclMuted,
            fontSize = 12.sp,
        )
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = address,
                onValueChange = { address = it },
                label = { Text(t("房主地址，例如 1.2.3.4:25565")) },
                singleLine = true,
                modifier = Modifier.weight(2f),
                colors = FieldColors(),
            )
            OutlinedTextField(
                value = port,
                onValueChange = { text -> port = text.filter { it.isDigit() }.take(5) },
                label = { Text(t("端口")) },
                singleLine = true,
                modifier = Modifier.weight(1f),
                colors = FieldColors(),
            )
        }
        if (address.isNotBlank() && target.error.isNotEmpty()) {
            Text(
                when (target.error) {
                    TerracottaCore.DIRECT_LOOPBACK -> t("请输入房主的公网地址，例如 1.2.3.4:25565")
                    TerracottaCore.DIRECT_BAD_PORT -> t("端口号必须在 1-65535 之间")
                    else -> t("还没有联机地址。")
                },
                color = ErrorRed,
                fontSize = 11.sp,
            )
        } else if (ready) {
            Text(t("将连接 {0}，端口 {1}").fmt(target.host, target.port), color = PclGreen, fontSize = 11.sp)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            PrimaryBtn(t("直连进游戏"), enabled = ready && !vm.busy && vm.versionId.isNotBlank()) {
                vm.launchDirect(address, port)
            }
            if (vm.versionId.isBlank()) {
                Text(t("先到启动页选一个版本"), color = PclMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun LanCard(vm: AppViewModel) {
    CardBox {
        Text(t("局域网直连"), fontWeight = FontWeight.SemiBold)
        Text(vm.lanHint(), color = PclMuted, fontSize = 12.sp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.lanPort.toString(),
                onValueChange = { text -> vm.lanPort = text.filter { it.isDigit() }.take(5).toIntOrNull() ?: 0 },
                label = { Text(t("端口")) },
                singleLine = true,
                modifier = Modifier.weight(1f),
                colors = FieldColors(),
            )
            TextButton(onClick = { vm.append(vm.lanHint()) }) { Text(t("记进日志"), color = PclGreen) }
        }
    }
}

/**
 * 真正递给内核的那一份节点表。
 *
 * 摆在页面上是因为 d-157 那个坑的失败表现是 `PingHostFail`，看上去像协议不对；
 * 首位是不是 HMCL 那条会合节点，得让人一眼看见，而不是去翻日志。
 */
@Composable
private fun NodesCard() {
    val sent = TerracottaRepo.lastSentNodes()
    CardBox {
        Text(t("会合节点"), fontWeight = FontWeight.SemiBold)
        if (sent.isEmpty()) {
            Text(
                t("还没开过房 / 加过房，节点表在第一次调用内核时才算出来。首位固定是 HMCL 自定义节点。"),
                color = PclMuted,
                fontSize = 11.sp,
            )
            Text(TerracottaCore.HMCL_CUSTOM_NODE, color = PclGreen, fontSize = 10.sp, fontFamily = FontFamily.Monospace)
            return@CardBox
        }
        Text(t("本次交给内核 {0} 条，第一条就是必须带上的那条：").fmt(sent.size), color = PclMuted, fontSize = 11.sp)
        sent.forEachIndexed { i, node ->
            Text(
                "${i + 1}. $node",
                color = if (i == 0) PclGreen else PclMuted,
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
