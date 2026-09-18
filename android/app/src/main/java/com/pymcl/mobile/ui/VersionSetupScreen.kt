package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.GcPresets
import com.pymcl.mobile.data.VersionSetting
import com.pymcl.mobile.data.VersionSettings
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel

/**
 * 单个版本的设置，对齐桌面 `app/pages/version_setup.py`。
 *
 * 这些选项只作用于这一个版本，落在 `versions/<id>/pymcl.json`——跟桌面同一个文件、
 * 同一批字段名，所以把实例目录搬到电脑上，两边读到的是同一份配置。
 *
 * 编辑时先改本地副本，点「保存」才落盘：中途退出去不该留下半套设置。
 */
@Composable
fun VersionSetupScreen(vm: AppViewModel, version: String, onClose: () -> Unit, modifier: Modifier = Modifier) {
    val loaded = remember(vm.instance, version) { VersionSettings.load(vm.instDir, version) }
    var draft by remember(vm.instance, version) { mutableStateOf(loaded) }
    var saving by remember(vm.instance, version) { mutableStateOf(false) }
    val dirty = draft != loaded

    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()),
    ) {
        SectionHeader(t("版本设置 · {0}").fmt(version), t("只作用于当前版本，对齐 PCL 的「版本设置」")) {
            TextButton(onClick = onClose, enabled = !saving) { Text(t("返回"), color = PclGreen) }
        }
        Spacer(Modifier.height(6.dp))

        CardBox {
            Text(t("隔离与资源"), fontWeight = FontWeight.SemiBold)
            ChipRow(
                t("隔离"),
                VersionSettings.LABELS.values.map(::t),
                t(VersionSettings.LABELS.getValue(draft.isolation)),
            ) { label ->
                VersionSettings.LABELS.entries.firstOrNull { t(it.value) == label }?.let {
                    draft = draft.copy(isolation = it.key)
                }
            }
            NumberField(t("独占内存 MB"), draft.memoryMb, t("留空则用启动页滑条")) { draft = draft.copy(memoryMb = it) }
            TextField("Java", draft.java, t("自动选择")) { draft = draft.copy(java = it) }
            val followGlobal = t("跟随全局")
            ChipRow("GC", listOf(followGlobal) + GcPresets.LABELS.values.map(::t), t(GcPresets.label(draft.gc))) { label ->
                val key = GcPresets.LABELS.entries.firstOrNull { t(it.value) == label }?.key
                draft = draft.copy(gc = if (label == followGlobal || key == null) GcPresets.FOLLOW_GLOBAL else key)
            }
            if (draft.gc.isNotBlank()) {
                Text(GcPresets.presetArgs(draft.gc), color = PclMuted, fontSize = 10.sp)
            }
        }

        Spacer(Modifier.height(8.dp))
        CardBox {
            Text(t("启动参数"), fontWeight = FontWeight.SemiBold)
            TextField(t("JVM 参数"), draft.jvmArgs, t("-XX:+UseG1GC 等，空格分隔")) { draft = draft.copy(jvmArgs = it) }
            TextField(t("游戏参数"), draft.gameArgs, t("附加游戏参数")) { draft = draft.copy(gameArgs = it) }
            TextField(t("启动前命令"), draft.preLaunch, t("启动前执行的命令")) { draft = draft.copy(preLaunch = it) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(
                    checked = draft.preLaunchWait,
                    onCheckedChange = { draft = draft.copy(preLaunchWait = it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                )
                Text(t("等待启动前命令结束"), fontSize = 13.sp)
            }
            TextField(t("退出后命令"), draft.postLaunch, t("退出后执行的命令")) { draft = draft.copy(postLaunch = it) }
            ChipRow(t("进程优先级"), listOf("low", "normal", "high"), draft.processPriority) {
                draft = draft.copy(processPriority = it)
            }
        }

        Spacer(Modifier.height(8.dp))
        CardBox {
            Text(t("账号与认证"), fontWeight = FontWeight.SemiBold)
            val followLaunch = t("跟随启动页")
            ChipRow(
                t("绑定账号"),
                listOf(followLaunch) + vm.accountNames(),
                draft.loginAccount.ifBlank { followLaunch },
            ) { name ->
                draft = draft.copy(loginAccount = if (name == followLaunch) "" else name)
            }
            TextField(t("统一通行证"), draft.nide8Id, t("32 位服务器 ID 或通行证链接")) { draft = draft.copy(nide8Id = it) }
            TextField(t("认证服 API"), draft.authServer, t("自定义认证服（可选）")) { draft = draft.copy(authServer = it) }
            val skins = offlineSkins()
            ChipRow(t("离线皮肤"), skins.values.toList(), skins.getValue(draft.offlineSkin)) { label ->
                skins.entries.firstOrNull { it.value == label }?.let {
                    draft = draft.copy(offlineSkin = it.key)
                }
            }
        }

        Spacer(Modifier.height(8.dp))
        CardBox {
            Text(t("直连与窗口"), fontWeight = FontWeight.SemiBold)
            TextField(t("服务器"), draft.server, t("启动后直连，例如 play.example.com")) { draft = draft.copy(server = it) }
            TextField(t("端口"), draft.port, "25565") { draft = draft.copy(port = it.filter { c -> c.isDigit() }) }
            TextField(t("窗口标题"), draft.windowTitle, t("自定义窗口标题")) { draft = draft.copy(windowTitle = it) }
            ChipRow(t("窗口模式"), listOf(t("窗口"), t("全屏")), if (draft.windowMode == "window") t("窗口") else t("全屏")) {
                draft = draft.copy(windowMode = if (it == t("窗口")) "window" else "maximize")
            }
            NumberField(t("窗口宽度"), draft.windowWidth, t("留空则用全局分辨率")) { draft = draft.copy(windowWidth = it) }
            NumberField(t("窗口高度"), draft.windowHeight, t("留空则用全局分辨率")) { draft = draft.copy(windowHeight = it) }
        }

        Spacer(Modifier.height(8.dp))
        CardBox {
            Text(t("列表"), fontWeight = FontWeight.SemiBold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(
                    checked = draft.hidden,
                    onCheckedChange = { draft = draft.copy(hidden = it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                )
                Text(t("在版本列表中隐藏"), fontSize = 13.sp)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(
                    checked = draft.skipAssets,
                    onCheckedChange = { draft = draft.copy(skipAssets = it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                )
                Text(t("启动时跳过资源校验"), fontSize = 13.sp)
            }
        }

        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            PrimaryBtn(if (saving) t("保存中…") else t("保存"), enabled = dirty && !saving) {
                saving = true
                vm.saveVersionSetting(version, draft) { success ->
                    saving = false
                    if (success) onClose()
                }
            }
            TextButton(onClick = { draft = loaded }, enabled = dirty) { Text(t("还原改动"), color = PclGreen) }
            Spacer(Modifier.height(0.dp))
            if (!dirty) Text(t("没有改动"), color = PclMuted, fontSize = 11.sp)
        }
        ErrorLine(vm)
        Spacer(Modifier.height(16.dp))
    }
}

/** 离线皮肤三档：键存盘、值显示。写成函数是为了切语言后「默认」跟着换。 */
private fun offlineSkins(): Map<String, String> =
    linkedMapOf("default" to t("默认"), "steve" to "Steve", "alex" to "Alex")

@Composable
private fun TextField(label: String, value: String, hint: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        placeholder = { Text(hint, fontSize = 12.sp) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        colors = FieldColors(),
    )
}

/** 留空 = 跟随全局，所以空串要映射成 null 而不是 0。 */
@Composable
private fun NumberField(label: String, value: Int?, hint: String, onChange: (Int?) -> Unit) {
    OutlinedTextField(
        value = value?.toString().orEmpty(),
        onValueChange = { text ->
            val digits = text.filter { it.isDigit() }.take(6)
            onChange(digits.toIntOrNull()?.takeIf { it > 0 })
        },
        label = { Text(label) },
        placeholder = { Text(hint, fontSize = 12.sp) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        colors = FieldColors(),
    )
}
