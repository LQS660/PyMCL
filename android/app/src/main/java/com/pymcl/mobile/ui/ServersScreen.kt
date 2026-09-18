package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
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
import com.pymcl.mobile.data.ServerPing
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.model.ServerEntry
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel

/** 服务器列表：写的是游戏真正读的 servers.dat，所以这里加的服务器进游戏就能看见。 */
@Composable
fun ServersScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<ServerEntry?>(null) }
    var importing by remember { mutableStateOf(false) }
    var exported by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(vm.instance, vm.versionId) { vm.reloadServers() }

    Column(modifier.fillMaxSize()) {
        SectionHeader(t("服务器列表"), t("{0} 个 · 写入 {1}/servers.dat").fmt(vm.servers.size, vm.gameDir.name))
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            PrimaryBtn(t("添加服务器")) { adding = true }
            TextButton(onClick = { vm.pingServers() }, enabled = !vm.pingBusy && vm.servers.isNotEmpty()) {
                Text(if (vm.pingBusy) t("刷新中…") else t("刷新状态"), color = PclGreen)
            }
            TextButton(onClick = { importing = true }) { Text(t("导入"), color = PclGreen) }
            TextButton(onClick = { exported = vm.exportServers() }) { Text(t("导出"), color = PclGreen) }
        }
        ErrorLine(vm)
        Spacer(Modifier.height(6.dp))

        if (vm.servers.isEmpty()) {
            EmptyHint(t("没有可用的服务器\n点「添加服务器」开始添加"), Modifier.weight(1f))
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            itemsIndexed(vm.servers, key = { _, s -> "${s.ip}:${s.port}" }) { index, s ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(s.name, fontWeight = FontWeight.SemiBold)
                            Text("${s.ip}:${s.port}", color = PclMuted, fontSize = 12.sp)
                            if (s.description.isNotBlank()) {
                                Text(s.description, color = PclMuted, fontSize = 11.sp, maxLines = 2)
                            }
                        }
                        if (s.hidden) Pill(t("已隐藏"), PclMuted)
                    }
                    vm.statusOf(s.ip, s.port)?.let { status ->
                        Text(
                            ServerPing.describe(status),
                            color = if (status.online) PclGreen else ErrorRed,
                            fontSize = 11.sp,
                        )
                        if (status.motd.isNotBlank()) {
                            Text(status.motd, color = PclMuted, fontSize = 11.sp, maxLines = 2)
                        }
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        TextButton(onClick = { vm.moveServer(index, index - 1) }, enabled = index > 0) {
                            Text(t("上移"), color = PclGreen)
                        }
                        TextButton(
                            onClick = { vm.moveServer(index, index + 1) },
                            enabled = index < vm.servers.lastIndex,
                        ) { Text(t("下移"), color = PclGreen) }
                        TextButton(onClick = { editing = s }) { Text(t("编辑"), color = PclGreen) }
                        TextButton(onClick = { vm.deleteServer(index) }) { Text(t("删除"), color = ErrorRed) }
                    }
                }
            }
        }
    }

    if (adding) {
        ServerPrompt(t("添加服务器"), "", "") { name, addr ->
            if (addr.isNotBlank()) vm.addServer(name, addr)
            adding = false
        }
    }

    editing?.let { s ->
        ServerPrompt(t("编辑服务器"), s.name, "${s.ip}:${s.port}") { name, addr ->
            if (addr.isNotBlank()) vm.updateServer(s.index, name, addr)
            editing = null
        }
    }

    if (importing) {
        TextAreaPrompt(
            t("导入服务器"),
            t("每行一条：名字<TAB>地址:端口 / 地址:端口 / 地址；也认整段 JSON 数组"),
        ) { text ->
            if (text.isNotBlank()) vm.importServers(text)
            importing = false
        }
    }

    exported?.let { text ->
        AlertDialog(
            onDismissRequest = { exported = null },
            title = { Text(t("导出结果")) },
            text = { Text(text, fontSize = 12.sp) },
            confirmButton = { TextButton(onClick = { exported = null }) { Text(t("关闭"), color = PclGreen) } },
        )
    }
}

@Composable
private fun ServerPrompt(title: String, initialName: String, initialAddr: String, onDone: (String, String) -> Unit) {
    var name by remember(initialName) { mutableStateOf(initialName) }
    var addr by remember(initialAddr) { mutableStateOf(initialAddr) }
    AlertDialog(
        onDismissRequest = { onDone(initialName, "") },
        title = { Text(title) },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(t("名称（可留空）")) },
                    singleLine = true,
                    colors = FieldColors(),
                )
                OutlinedTextField(
                    value = addr,
                    onValueChange = { addr = it },
                    label = { Text(t("地址，可写 example.com:25566")) },
                    singleLine = true,
                    colors = FieldColors(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onDone(name, addr) }, enabled = addr.isNotBlank()) {
                Text(t("确定"), color = PclGreen)
            }
        },
        dismissButton = { TextButton(onClick = { onDone(initialName, "") }) { Text(t("取消")) } },
    )
}

@Composable
fun TextAreaPrompt(title: String, hint: String, onDone: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { onDone("") },
        title = { Text(title) },
        text = {
            Column {
                Text(hint, color = PclMuted, fontSize = 12.sp)
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    modifier = Modifier.fillMaxWidth().height(160.dp),
                    colors = FieldColors(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onDone(text) }, enabled = text.isNotBlank()) {
                Text(t("导入"), color = PclGreen)
            }
        },
        dismissButton = { TextButton(onClick = { onDone("") }) { Text(t("取消")) } },
    )
}
