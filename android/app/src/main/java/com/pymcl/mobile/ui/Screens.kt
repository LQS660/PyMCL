package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.People
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldColors
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.theme.PclBg
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclHover
import com.pymcl.mobile.theme.PclLine
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel

private data class BottomTab(
    val label: String,
    val icon: ImageVector,
    val index: Int,
)

private val tabs = listOf(
    BottomTab("启动", Icons.Outlined.PlayArrow, 0),
    BottomTab("实例", Icons.Outlined.GridView, 1),
    BottomTab("联机", Icons.Outlined.People, 2),
    BottomTab("下载", Icons.Outlined.Download, 3),
    BottomTab("AI", Icons.Outlined.Chat, 4),
    BottomTab("设置", Icons.Outlined.Settings, 5),
)

private val downloadChips = listOf(
    "原版游戏", "Mod", "整合包", "数据包", "资源包", "光影包", "下载任务",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppScaffold(vm: AppViewModel) {
    Scaffold(
        containerColor = PclBg,
        topBar = {
            TopAppBar(
                title = {
                    Text("PyMCL", fontWeight = FontWeight.Bold, color = PclText)
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = PclBg),
            )
        },
        bottomBar = {
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(PclBg)
                    .padding(vertical = 4.dp),
            ) {
                tabs.forEach { tab ->
                    val on = vm.tab == tab.index
                    Column(
                        Modifier
                            .weight(1f)
                            .clickable { vm.tab = tab.index }
                            .padding(vertical = 6.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Icon(
                            imageVector = tab.icon,
                            contentDescription = tab.label,
                            tint = if (on) PclGreen else PclMuted,
                        )
                        Text(
                            tab.label,
                            fontSize = 11.sp,
                            color = if (on) PclGreen else PclMuted,
                        )
                    }
                }
            }
        },
    ) { pad ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(pad)
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .imePadding(),
        ) {
            when (vm.tab) {
                0 -> LaunchScreen(vm)
                1 -> InstanceScreen(vm)
                2 -> MultiplayerScreen(vm)
                3 -> DownloadHub(vm)
                4 -> AiScreen(vm)
                else -> SettingsScreen(vm)
            }
        }
    }
}

@Composable
fun CardBox(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .border(1.dp, PclLine, RoundedCornerShape(10.dp))
            .padding(14.dp),
        content = content,
    )
}

@Composable
fun PrimaryBtn(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(containerColor = PclGreen, disabledContainerColor = PclMuted),
    ) { Text(text) }
}

@Composable
fun FieldColors(): TextFieldColors = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = PclGreen,
    cursorColor = PclGreen,
    focusedLabelColor = PclGreen,
)

@Composable
fun LaunchScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CardBox {
            Text("启动游戏", fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
            Text("实例 ${vm.instance} · ${vm.versionId.ifBlank { "未选版本" }}", color = PclMuted, fontSize = 13.sp)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryBtn("启动游戏", enabled = !vm.busy && vm.versionId.isNotBlank(), onClick = { vm.launchGame() })
                OutlinedButton(onClick = { vm.cancelTask() }, enabled = vm.busy) { Text("停止") }
            }
            Text("运行时 ${vm.runtimePkg ?: "点启动会自动解压 JRE"}", color = PclGreen, fontSize = 12.sp)
        }
        if (vm.busy || vm.progress > 0) {
            LinearProgressIndicator(
                progress = { (vm.progress / 100f).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
                color = PclGreen,
            )
        }
        Text(vm.status, color = PclMuted, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        CardBox {
            Text("启动配置", fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            ChipRow("实例", vm.instances.map { it.name }, vm.instance) { vm.selectInstance(it) }
            ChipRow("版本", vm.installed.ifEmpty { listOf(vm.versionId).filter { it.isNotEmpty() } }, vm.versionId) {
                vm.versionId = it
            }
            ChipRow("账号", vm.accounts.toList(), vm.account) { vm.account = it }
            OutlinedTextField(
                value = vm.username,
                onValueChange = {
                    vm.username = it
                    vm.persistUiDebounced()
                },
                label = { Text("离线用户名") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = FieldColors(),
            )
            Text("内存 ${vm.memoryMb} MB", color = PclMuted, fontSize = 12.sp)
            Slider(
                value = vm.memoryMb.toFloat(),
                onValueChange = { vm.memoryMb = it.toInt() },
                onValueChangeFinished = { vm.persistUi() },
                valueRange = 512f..8192f,
                colors = SliderDefaults.colors(thumbColor = PclGreen, activeTrackColor = PclGreen),
            )
            TextButton(onClick = { vm.startMsLogin() }) { Text("微软登录", color = PclGreen) }
            vm.device?.let {
                Text("打开 ${it.uri} 输入 ${it.userCode}", color = PclGreen, fontWeight = FontWeight.SemiBold)
            }
            OutlinedTextField(
                value = vm.skinApi,
                onValueChange = { vm.skinApi = it },
                label = { Text("皮肤站 API") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = FieldColors(),
            )
            OutlinedTextField(
                value = vm.skinUser,
                onValueChange = { vm.skinUser = it },
                label = { Text("皮肤站账号") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = FieldColors(),
            )
            OutlinedTextField(
                value = vm.skinPw,
                onValueChange = { vm.skinPw = it },
                label = { Text("皮肤站密码") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                colors = FieldColors(),
            )
            TextButton(onClick = { vm.loginAuthlib() }) { Text("登录皮肤站", color = PclGreen) }
        }
        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .border(1.dp, PclLine, RoundedCornerShape(10.dp))
                .padding(14.dp),
        ) {
            Text("日志", fontWeight = FontWeight.SemiBold)
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
        vm.error?.let { Text(it, color = Color(0xFFC62828), fontSize = 12.sp) }
    }
}

@Composable
fun ChipRow(label: String, items: List<String>, selected: String, onPick: (String) -> Unit) {
    Text(label, color = PclMuted, fontSize = 12.sp)
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(bottom = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items.take(8).forEach { item ->
            val on = item == selected
            Text(
                item,
                modifier = Modifier
                    .background(if (on) PclHover else Color.Transparent, RoundedCornerShape(8.dp))
                    .clickable { onPick(item) }
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                color = if (on) PclGreen else PclText,
                fontSize = 13.sp,
                maxLines = 1,
            )
        }
        if (items.isEmpty()) Text("无", color = PclMuted, fontSize = 12.sp)
    }
}

@Composable
fun InstanceScreen(vm: AppViewModel) {
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                label = { Text("新实例名") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                colors = FieldColors(),
            )
            Spacer(Modifier.width(8.dp))
            PrimaryBtn("新建") {
                vm.createInstance(vm.query.ifBlank { "游戏" })
                vm.query = ""
            }
        }
        Spacer(Modifier.height(8.dp))
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(vm.instances, key = { it.name }) { inst ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.weight(1f).clickable { vm.selectInstance(inst.name); vm.tab = 0 }) {
                            Text(inst.name, fontWeight = FontWeight.SemiBold)
                            Text("${inst.versions.size} 个版本", color = PclMuted, fontSize = 12.sp)
                            Text(inst.path, color = PclMuted, fontSize = 10.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
                        TextButton(onClick = { vm.deleteInstance(inst.name) }) { Text("删除", color = Color(0xFFC62828)) }
                    }
                }
            }
        }
    }
}

@Composable
fun MultiplayerScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CardBox {
            Text("陶瓦联机", fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
            Text("局域网：房主在游戏里对局域网开放后，把本机 IP:端口发给好友。陶瓦 P2P 目前仅桌面端。", color = PclMuted, fontSize = 13.sp)
            Text(remember { com.pymcl.mobile.data.Lan.hint() }, color = PclGreen, fontSize = 12.sp)
        }
        OutlinedTextField(
            value = vm.roomCode,
            onValueChange = { vm.roomCode = it },
            label = { Text("邀请码") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            colors = FieldColors(),
        )
        PrimaryBtn("保存邀请码", enabled = vm.roomCode.isNotBlank()) {
            vm.append("已记下房间 ${vm.roomCode}")
        }
    }
}

@Composable
fun DownloadHub(vm: AppViewModel) {
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            downloadChips.forEach { c ->
                val on = vm.downloadTab == c
                Text(
                    c,
                    modifier = Modifier
                        .background(if (on) PclHover else Color.Transparent, RoundedCornerShape(8.dp))
                        .clickable { vm.downloadTab = c }
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    color = if (on) PclGreen else PclText,
                    fontSize = 13.sp,
                    maxLines = 1,
                )
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (vm.downloadTab) {
                "原版游戏" -> VersionPane(vm)
                "下载任务" -> TasksPane(vm)
                else -> CatalogPane(vm)
            }
        }
    }
}

@Composable
fun VersionPane(vm: AppViewModel) {
    val rows = remember(vm.query, vm.onlyRelease, vm.versions.size) { vm.filteredVersions() }
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                label = { Text("过滤版本") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                colors = FieldColors(),
            )
            TextButton(onClick = { vm.reloadVersions(true) }) { Text("刷新", color = PclGreen) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = vm.onlyRelease,
                onCheckedChange = { vm.onlyRelease = it },
                colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
            )
            Text("仅正式版", fontSize = 13.sp)
            Spacer(Modifier.weight(1f))
            PrimaryBtn("安装", enabled = !vm.busy && vm.versionId.isNotBlank()) { vm.installSelected() }
        }
        Text("目标实例 ${vm.instance} · 选中 ${vm.versionId}", color = PclMuted, fontSize = 12.sp)
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(vertical = 8.dp),
        ) {
            items(rows, key = { it.id }) { row ->
                val on = row.id == vm.versionId
                Row(
                    Modifier
                        .fillMaxWidth()
                        .background(if (on) PclHover else Color.Transparent)
                        .clickable { vm.versionId = row.id }
                        .padding(vertical = 10.dp, horizontal = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column {
                        Text(row.id, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
                        Text(row.type, color = PclMuted, fontSize = 11.sp)
                    }
                    if (row.id in vm.installed) Text("已装", color = PclGreen, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
fun CatalogPane(vm: AppViewModel) {
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                label = { Text("名称后点搜索") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                colors = FieldColors(),
            )
            Spacer(Modifier.width(8.dp))
            PrimaryBtn("搜索", enabled = !vm.busy) { vm.searchCatalog() }
        }
        Text("${vm.downloadTab} · 空闲不联网。源：MCIM / Modrinth", color = PclMuted, fontSize = 12.sp)
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 8.dp),
        ) {
            items(vm.catalog, key = { it.slug + it.name }) { hit ->
                CardBox {
                    Text(hit.name, fontWeight = FontWeight.SemiBold)
                    Text(hit.description, color = PclMuted, fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Text("${hit.source} · ${hit.downloads} 下载 · ${hit.author}", color = PclMuted, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
fun TasksPane(vm: AppViewModel) {
    if (vm.tasks.isEmpty()) {
        Text("没有下载任务", color = PclMuted)
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(vm.tasks, key = { it.id }) { t ->
            CardBox {
                Text(t.title, fontWeight = FontWeight.SemiBold)
                Text(t.message, color = PclMuted, fontSize = 12.sp)
                if (t.total > 0) {
                    LinearProgressIndicator(
                        progress = { (t.current.toFloat() / t.total).coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                        color = PclGreen,
                    )
                }
                if (!t.done) {
                    TextButton(onClick = { vm.cancelTask() }) { Text("取消", color = PclGreen) }
                }
            }
        }
    }
}

@Composable
fun AiScreen(vm: AppViewModel) {
    Column(Modifier.fillMaxSize()) {
        Text(
            vm.aiOut,
            modifier = Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
            fontSize = 14.sp,
            color = PclText,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.aiInput,
                onValueChange = { vm.aiInput = it },
                label = { Text("消息") },
                modifier = Modifier.weight(1f),
                colors = FieldColors(),
                enabled = !vm.aiBusy,
            )
            Spacer(Modifier.width(8.dp))
            PrimaryBtn(if (vm.aiBusy) "…" else "发送", enabled = !vm.aiBusy) { vm.sendAi() }
        }
    }
}

@Composable
fun SettingsScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CardBox {
            Text("存储", fontWeight = FontWeight.SemiBold)
            Text(com.pymcl.mobile.data.Paths.root.absolutePath, fontSize = 12.sp, color = PclMuted)
        }
        OutlinedTextField(
            value = vm.aiUrl,
            onValueChange = {
                vm.aiUrl = it
                vm.persistUiDebounced()
            },
            label = { Text("自定义 AI 网关（留空走公益）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            colors = FieldColors(),
        )
        CardBox {
            Text("公益口 ${AiRepo.PUBLIC_BASE} · ${AiRepo.MODEL}")
            Text("下载源 bmclapi 优先，官方垫底。")
            Text("版本 ${com.pymcl.mobile.data.Paths.APP_VERSION} · app 0.1.0-dev", color = PclMuted, fontSize = 12.sp)
        }
    }
}
