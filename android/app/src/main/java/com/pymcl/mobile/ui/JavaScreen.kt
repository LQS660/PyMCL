package com.pymcl.mobile.ui

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.JavaInfo
import com.pymcl.mobile.data.JavaRuntime
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.RuntimeInstaller
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Java 页。对齐 `app/pages/java_page.py`：
 * 本机环境卡片 + 重新检测、发行版下拉、四块大版本下载磁贴、每实例指定 Java。
 */
@Composable
fun JavaScreen(
    modifier: Modifier = Modifier,
    instance: String = "",
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    var installed by remember { mutableStateOf<List<JavaInfo>>(emptyList()) }
    var vendor by rememberSaveable { mutableStateOf("adoptium") }
    var busyMajor by remember { mutableStateOf(0) }
    var progress by remember { mutableFloatStateOf(0f) }
    var defaultJava by remember { mutableStateOf(Settings.str(SettingsKeys.DEFAULT_JAVA)) }
    var instanceJava by remember(instance) {
        mutableStateOf(if (instance.isBlank()) "" else JavaRuntime.instanceJava(instance))
    }

    // 扫目录是 IO，扔到 IO 线程；组合里只拿结果
    suspend fun rescan() {
        installed = withContext(Dispatchers.IO) { JavaRuntime.scanInstalled(Paths.javaRoot) }
    }

    LaunchedEffect(Unit) { rescan() }

    val abi = remember { Build.SUPPORTED_ABIS.firstOrNull().orEmpty() }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Java", fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                        Text(
                            t("启动时会按游戏版本自动挑一个；也能在下面为当前实例单独指定"),
                            color = c.muted,
                            fontSize = 12.sp,
                        )
                    }
                    PclLink(t("重新检测")) { scope.launch { rescan(); notice.ok(t("已重新扫描")) } }
                }
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "env-title") { PclSectionTitle(t("本机环境"), t("指令集 {0}").fmt(abi.ifBlank { t("未知") })) }

        if (installed.isEmpty()) {
            item(key = "env-empty") { PclCard { PclEmpty(t("未检测到 Java，请从下方下载")) } }
        }

        items(installed, key = { it.path }) { info ->
            JavaCard(
                info = info,
                isDefault = info.path == defaultJava,
                isInstanceJava = instance.isNotBlank() && info.path == instanceJava,
                onSetDefault = {
                    Settings.set(SettingsKeys.DEFAULT_JAVA, info.path)
                    Settings.flushIfDirty()
                    defaultJava = info.path
                    notice.ok(t("全局默认已设为 Java {0}").fmt(info.major))
                },
                onSetInstance = {
                    if (instance.isBlank()) {
                        notice.fail(t("还没有选中的实例"))
                    } else {
                        JavaRuntime.setInstanceJava(instance, info.path)
                        Settings.flushIfDirty()
                        instanceJava = info.path
                        notice.ok(t("实例「{0}」改用 Java {1}").fmt(instance, info.major))
                    }
                },
                onRemove = {
                    scope.launch {
                        withContext(Dispatchers.IO) { RuntimeInstaller.removeDownloaded(info.major) }
                        rescan()
                        notice.ok(t("已删除 Java {0}").fmt(info.major))
                    }
                },
            )
        }

        item(key = "vendor") {
            PclCard {
                PclSectionTitle(t("下载新运行时"), t("发行版"))
                PclOptionRow(
                    label = "",
                    options = JavaRuntime.vendors.map { it.key to it.label },
                    selected = vendor,
                ) { vendor = it }
                if (busyMajor > 0) {
                    Text(t("正在装 Java {0}…").fmt(busyMajor), color = c.muted, fontSize = 12.sp)
                    LinearProgressIndicator(
                        progress = { progress.coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth(),
                        color = c.accent,
                    )
                }
            }
        }

        items(JavaRuntime.downloadableMajors, key = { "dl-${it.first}" }) { (major, note) ->
            PclCard {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    PclTile("J", Color(0xFFE8862E), size = 40)
                    Column(Modifier.weight(1f)) {
                        Text("Java $major", fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(note, color = c.muted, fontSize = 11.sp)
                    }
                    val already = installed.any { it.major == major }
                    PclButton(
                        if (already) t("重装") else t("下载"),
                        enabled = busyMajor == 0,
                    ) {
                        scope.launch {
                            busyMajor = major
                            progress = 0f
                            notice.clear()
                            try {
                                withContext(Dispatchers.IO) {
                                    RuntimeInstaller.ensureDownloaded(
                                        major = major,
                                        vendor = vendor,
                                        abi = abi,
                                        onProgress = { done, total ->
                                            if (total > 0) progress = done.toFloat() / total
                                        },
                                    )
                                }
                                rescan()
                                notice.ok(t("Java {0} 装好了").fmt(major))
                            } catch (e: Exception) {
                                notice.fail(t("Java {0} 安装失败：{1}").fmt(major, e.message))
                            } finally {
                                busyMajor = 0
                                progress = 0f
                            }
                        }
                    }
                }
            }
        }

        item(key = "auto") {
            PclCard {
                PclSectionTitle(t("自动选择"), t("版本设置与实例偏好都是「自动」时才用全局默认"))
                PclKeyValue(t("全局默认"), defaultJava.ifBlank { t("自动") })
                if (instance.isNotBlank()) {
                    PclKeyValue(t("实例「{0}」").fmt(instance), instanceJava.ifBlank { t("跟随全局") })
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PclLink(t("清除全局默认"), enabled = defaultJava.isNotBlank()) {
                        Settings.set(SettingsKeys.DEFAULT_JAVA, "")
                        Settings.flushIfDirty()
                        defaultJava = ""
                        notice.ok(t("全局默认已改回自动"))
                    }
                    PclLink(
                        t("清除实例指定"),
                        enabled = instance.isNotBlank() && instanceJava.isNotBlank(),
                    ) {
                        JavaRuntime.setInstanceJava(instance, "")
                        Settings.flushIfDirty()
                        instanceJava = ""
                        notice.ok(t("实例改回跟随全局"))
                    }
                }
            }
        }
    }
}

@Composable
private fun JavaCard(
    info: JavaInfo,
    isDefault: Boolean,
    isInstanceJava: Boolean,
    onSetDefault: () -> Unit,
    onSetInstance: () -> Unit,
    onRemove: () -> Unit,
) {
    val c = LocalPclColors.current
    PclCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            PclTile("J", Color(0xFFE8862E), size = 40)
            Column(Modifier.weight(1f)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Java ${info.major}", fontWeight = FontWeight.SemiBold, color = c.text)
                    PclPill(t("可用"), c.accent)
                    if (isDefault) PclPill(t("全局默认"), Color(0xFF4C8BF5))
                    if (isInstanceJava) PclPill(t("本实例"), Color(0xFF7C5CD6))
                }
                Text(
                    info.path.ifBlank { info.name },
                    color = c.muted,
                    fontSize = 10.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            PclLink(t("设为全局默认"), enabled = !isDefault, onClick = onSetDefault)
            PclLink(t("给本实例用"), enabled = !isInstanceJava, onClick = onSetInstance)
            PclLink(t("删除"), onClick = onRemove)
        }
    }
}
