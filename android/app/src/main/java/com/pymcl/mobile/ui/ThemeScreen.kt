package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.data.SettingsLogic
import com.pymcl.mobile.data.ThemePack
import com.pymcl.mobile.data.ThemeStore
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** 出厂预设色，省得用户自己去背 16 进制。 */
private val SWATCHES = listOf(
    "#2E9B6B", "#4C8BF5", "#7C5CD6", "#E8862E",
    "#C62828", "#0F9B8E", "#D81B60", "#455A64",
)

/**
 * 主题页。对齐 `app/pages/layout_settings.py` 里主题包那一段 +
 * `settings_page` 的深色 / 主题色 / 壁纸观感三档，后端是 `mclauncher/themes.py`。
 */
@Composable
fun ThemeScreen(
    modifier: Modifier = Modifier,
    onThemeChanged: () -> Unit = {},
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    var color by remember { mutableStateOf(Settings.str(SettingsKeys.THEME_COLOR, "#2E9B6B")) }
    var dark by remember { mutableStateOf(Settings.bool(SettingsKeys.UI_DARK)) }
    var opacity by remember { mutableStateOf(Settings.int(SettingsKeys.UI_SIDEBAR_OPACITY, 85)) }
    var blur by remember { mutableStateOf(Settings.int(SettingsKeys.UI_BACKGROUND_BLUR, 0)) }
    var dim by remember { mutableStateOf(Settings.int(SettingsKeys.UI_BACKGROUND_DIM, 25)) }
    var background by remember { mutableStateOf(Settings.str(SettingsKeys.UI_BACKGROUND)) }
    var folder by remember { mutableStateOf(Settings.str(SettingsKeys.UI_BACKGROUND_FOLDER)) }
    var shuffle by remember { mutableStateOf(Settings.bool(SettingsKeys.UI_BACKGROUND_SHUFFLE)) }
    var interval by remember { mutableStateOf(Settings.int(SettingsKeys.UI_BACKGROUND_INTERVAL, 10)) }
    var packs by remember { mutableStateOf<List<ThemePack>>(emptyList()) }
    var newName by rememberSaveable { mutableStateOf("") }

    suspend fun reloadPacks() {
        packs = withContext(Dispatchers.IO) { ThemeStore.list() }
    }

    LaunchedEffect(Unit) { reloadPacks() }

    /** 改一项就刷一遍界面，但只往内存里写；落盘交给 [Settings.flushIfDirty]。 */
    fun apply(key: String, value: Any) {
        Settings.set(key, value)
        onThemeChanged()
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t("主题"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                Text(t("颜色、深浅、壁纸观感；存成主题包可以整套换"), color = c.muted, fontSize = 12.sp)
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "color") {
            PclCard {
                PclSectionTitle(t("主题色"), t("点一个预设，或填 #RRGGBB"))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SWATCHES.forEach { hex ->
                        val picked = hex.equals(color, true)
                        Column(
                            Modifier
                                .size(if (picked) 34.dp else 28.dp)
                                .background(
                                    Color(SettingsLogic.parseColor(hex).toInt()),
                                    RoundedCornerShape(8.dp),
                                )
                                .clickable {
                                    color = hex
                                    apply(SettingsKeys.THEME_COLOR, hex)
                                },
                        ) {}
                    }
                }
                PclTextRow(t("自定义颜色"), color) {
                    color = it
                    apply(SettingsKeys.THEME_COLOR, it)
                }
                PclSwitchRow(t("深色模式"), dark, t("整套底色换成深色，主题色不变")) {
                    dark = it
                    apply(SettingsKeys.UI_DARK, it)
                }
            }
        }

        item(key = "wallpaper") {
            PclCard {
                PclSectionTitle(t("壁纸"), t("留空就是纯色底"))
                PclTextRow(t("单张图片路径"), background) {
                    background = it
                    apply(SettingsKeys.UI_BACKGROUND, it)
                }
                PclTextRow(t("轮播文件夹"), folder, t("填了就轮播里面的图片，优先级高于单图")) {
                    folder = it
                    apply(SettingsKeys.UI_BACKGROUND_FOLDER, it)
                }
                PclSwitchRow(t("随机抽，不按文件名顺序"), shuffle) {
                    shuffle = it
                    apply(SettingsKeys.UI_BACKGROUND_SHUFFLE, it)
                }
                PclSliderRow(t("轮播间隔"), interval, 1..120, t(" 分钟"), onChange = { interval = it }) {
                    apply(SettingsKeys.UI_BACKGROUND_INTERVAL, interval)
                }
                PclLink(t("撤销上一张壁纸")) {
                    scope.launch {
                        val undone = withContext(Dispatchers.IO) { ThemeStore.undoBackground() }
                        if (undone) {
                            background = Settings.str(SettingsKeys.UI_BACKGROUND)
                            folder = Settings.str(SettingsKeys.UI_BACKGROUND_FOLDER)
                            onThemeChanged()
                            notice.ok(t("已退回上一张"))
                        } else {
                            notice.fail(t("没有可以退回的壁纸了"))
                        }
                    }
                }
            }
        }

        item(key = "look") {
            PclCard {
                PclSectionTitle(t("观感"), t("壁纸糊一点、暗一点，压在上面的字才看得清"))
                PclSliderRow(t("面板不透明度"), opacity, 0..100, "%", onChange = { opacity = it }) {
                    apply(SettingsKeys.UI_SIDEBAR_OPACITY, SettingsLogic.clampPercent(opacity))
                }
                PclSliderRow(t("壁纸模糊"), blur, 0..60, " px", onChange = { blur = it }) {
                    apply(SettingsKeys.UI_BACKGROUND_BLUR, SettingsLogic.clampBlur(blur))
                }
                PclSliderRow(t("壁纸遮罩"), dim, 0..100, "%", onChange = { dim = it }) {
                    apply(SettingsKeys.UI_BACKGROUND_DIM, SettingsLogic.clampPercent(dim))
                }
            }
        }

        item(key = "packs") {
            PclCard {
                PclSectionTitle(t("主题包"), t("把当前这一整套存下来，以后一键换回"))
                PclTextRow(t("新主题包名字"), newName) { newName = it }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PclButton(t("保存当前为主题包"), enabled = newName.isNotBlank()) {
                        scope.launch {
                            try {
                                withContext(Dispatchers.IO) {
                                    Settings.flushIfDirty()
                                    ThemeStore.save(newName.trim())
                                }
                                notice.ok(t("已保存主题包「{0}」").fmt(newName.trim()))
                                newName = ""
                                reloadPacks()
                            } catch (e: Exception) {
                                notice.fail(t("保存失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("从 exports/ 导入")) {
                        scope.launch {
                            try {
                                val src = File(Paths.exportsRoot, "theme.json")
                                val name = withContext(Dispatchers.IO) { ThemeStore.importFrom(src) }
                                notice.ok(t("已导入「{0}」").fmt(name))
                                reloadPacks()
                            } catch (e: Exception) {
                                notice.fail(t("导入失败：{0}").fmt(e.message))
                            }
                        }
                    }
                }
            }
        }

        if (packs.isEmpty()) {
            item(key = "packs-empty") { PclEmpty(t("还没有保存过主题包")) }
        }

        items(packs, key = { it.name }) { pack ->
            PclCard {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(
                        Modifier
                            .size(26.dp)
                            .background(
                                Color(SettingsLogic.parseColor(pack.themeColor).toInt()),
                                RoundedCornerShape(6.dp),
                            ),
                    ) {}
                    Column(Modifier.weight(1f)) {
                        Text(pack.name, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(
                            t("{0} · {1} · 面板 {2}%").fmt(pack.themeColor, if (pack.dark) t("深色") else t("浅色"), pack.sidebarOpacity),
                            color = c.muted,
                            fontSize = 11.sp,
                        )
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    PclLink(t("应用")) {
                        scope.launch {
                            try {
                                val applied = withContext(Dispatchers.IO) { ThemeStore.load(pack.name) }
                                color = applied.themeColor
                                dark = applied.dark
                                opacity = applied.sidebarOpacity
                                blur = applied.backgroundBlur
                                dim = applied.backgroundDim
                                background = applied.background
                                folder = applied.backgroundFolder
                                onThemeChanged()
                                notice.ok(t("已切到「{0}」").fmt(pack.name))
                            } catch (e: Exception) {
                                notice.fail(t("应用失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("导出")) {
                        scope.launch {
                            try {
                                val out = withContext(Dispatchers.IO) {
                                    ThemeStore.exportTo(
                                        pack.name,
                                        File(Paths.exportsRoot, "${Paths.sanitizeFileName(pack.name)}.json"),
                                    )
                                }
                                notice.ok(t("已导出到 {0}").fmt(out.absolutePath))
                            } catch (e: Exception) {
                                notice.fail(t("导出失败：{0}").fmt(e.message))
                            }
                        }
                    }
                    PclLink(t("删除")) {
                        scope.launch {
                            withContext(Dispatchers.IO) { ThemeStore.delete(pack.name) }
                            notice.ok(t("已删除「{0}」").fmt(pack.name))
                            reloadPacks()
                        }
                    }
                }
            }
        }
    }
}
