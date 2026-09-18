package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.LayoutDoc
import com.pymcl.mobile.data.LayoutStore
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** 卡片类型 → 显示名。每次调用现取词，别存成顶层常量。 */
private fun cardLabel(type: String): String = when (type) {
    "banner" -> t("横幅")
    "config" -> t("启动配置")
    "log" -> t("日志")
    "news" -> t("资讯")
    "quick" -> t("快捷入口")
    "notes" -> t("便签")
    "playtime" -> t("游戏时长")
    "tasks" -> t("下载任务")
    "skin" -> t("皮肤")
    else -> type
}

/**
 * 布局方案页。对齐 `app/pages/layout_settings.py`：
 * 方案的保存 / 激活 / 删除 / 导入 / 导出 / 重置。
 *
 * 坐标存的是 0..1 比例，跟桌面 `ui_layout` 同一个键——桌面排好的布局
 * 拷过来手机上就是同一个，反之亦然。
 */
@Composable
fun LayoutSettingsScreen(modifier: Modifier = Modifier) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    var doc by remember { mutableStateOf<LayoutDoc?>(null) }
    var profiles by remember { mutableStateOf<List<String>>(emptyList()) }
    var active by remember { mutableStateOf("") }
    var newName by rememberSaveable { mutableStateOf("") }

    suspend fun reload() {
        val snapshot = withContext(Dispatchers.IO) {
            Triple(LayoutStore.activeDoc(), LayoutStore.profiles(), LayoutStore.activeProfile())
        }
        doc = snapshot.first
        profiles = snapshot.second
        active = snapshot.third
    }

    LaunchedEffect(Unit) { reload() }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t("启动页布局"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                Text(
                    t("卡片位置按画布比例存，换屏幕尺寸不会溢出；跟桌面共用同一份方案"),
                    color = c.muted,
                    fontSize = 12.sp,
                )
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "current") {
            PclCard {
                PclSectionTitle(
                    t("当前布局"),
                    if (active.isBlank()) t("未命名的自定义") else t("方案「{0}」").fmt(active),
                )
                doc?.items?.forEach { card ->
                    PclKeyValue(
                        cardLabel(card.type),
                        t("x %.2f  y %.2f  宽 %.2f  高 %.2f").format(card.x, card.y, card.w, card.h),
                    )
                }
                if (doc == null) PclEmpty(t("读取中…"))
            }
        }

        item(key = "save") {
            PclCard {
                PclSectionTitle(t("存成方案"), t("同名会覆盖"))
                PclTextRow(t("方案名"), newName) { newName = it }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PclButton(t("保存"), enabled = newName.isNotBlank()) {
                        scope.launch {
                            try {
                                withContext(Dispatchers.IO) { LayoutStore.saveProfile(newName.trim()) }
                                notice.ok(t("已保存方案「{0}」").fmt(newName.trim()))
                                newName = ""
                                reload()
                            } catch (e: Exception) {
                                notice.fail(t("保存失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("恢复出厂布局")) {
                        scope.launch {
                            withContext(Dispatchers.IO) { LayoutStore.resetToDefault() }
                            notice.ok(t("已恢复出厂布局"))
                            reload()
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PclLink(t("导出到 exports/")) {
                        scope.launch {
                            try {
                                val out = withContext(Dispatchers.IO) {
                                    LayoutStore.exportTo(File(Paths.exportsRoot, "layout.json"))
                                }
                                notice.ok(t("已导出 {0}").fmt(out.absolutePath))
                            } catch (e: Exception) {
                                notice.fail(t("导出失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("从 exports/layout.json 导入")) {
                        scope.launch {
                            try {
                                withContext(Dispatchers.IO) {
                                    LayoutStore.importFrom(File(Paths.exportsRoot, "layout.json"))
                                }
                                notice.ok(t("已导入"))
                                reload()
                            } catch (e: Exception) {
                                notice.fail(t("导入失败：{0}").fmt(e.message))
                            }
                        }
                    }
                }
            }
        }

        item(key = "profiles-title") { PclSectionTitle(t("已保存方案")) }

        if (profiles.isEmpty()) {
            item(key = "profiles-empty") { PclEmpty(t("还没有保存过方案")) }
        }

        items(profiles, key = { it }) { name ->
            PclCard {
                Row(Modifier.fillMaxWidth()) {
                    Column(Modifier.weight(1f)) {
                        Text(name, fontWeight = FontWeight.SemiBold, color = c.text)
                        if (name == active) Text(t("正在使用"), color = c.accent, fontSize = 11.sp)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    PclLink(t("激活"), enabled = name != active) {
                        scope.launch {
                            try {
                                withContext(Dispatchers.IO) { LayoutStore.activateProfile(name) }
                                notice.ok(t("已切到「{0}」").fmt(name))
                                reload()
                            } catch (e: Exception) {
                                notice.fail(t("激活失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("删除")) {
                        scope.launch {
                            withContext(Dispatchers.IO) { LayoutStore.deleteProfile(name) }
                            notice.ok(t("已删除「{0}」").fmt(name))
                            reload()
                        }
                    }
                }
            }
        }
    }
}
