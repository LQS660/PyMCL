package com.pymcl.mobile.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import com.pymcl.mobile.data.SettingsLogic

/** 出厂配色，与桌面 `theme_color` 的默认值 `#2E9B6B` 一致。 */
val PclGreen = Color(0xFF2E9B6B)
val PclGreenDeep = Color(0xFF1E7A52)
val PclBg = Color(0xFFFFFFFF)
val PclText = Color(0xFF2B2B2B)
val PclMuted = Color(0xFF888888)
val PclLine = Color(0xFFE6E6E6)
val PclHover = Color(0xFFF3F7F5)

val PclBgDark = Color(0xFF14171A)
val PclTextDark = Color(0xFFE8EAED)
val PclMutedDark = Color(0xFF9AA0A6)
val PclLineDark = Color(0xFF2C3136)
val PclHoverDark = Color(0xFF1E2429)

val PclDanger = Color(0xFFC62828)
val PclWarn = Color(0xFFB26A00)

/**
 * 当前生效的一套颜色。
 *
 * 主题色和深浅是用户随时能改的，写死成 top-level `val` 的话改了要重启才生效。
 * 走 CompositionLocal：改一次配置，读到它的 Composable 自己重组，其余不动。
 */
data class PclColors(
    val accent: Color,
    val accentDeep: Color,
    val background: Color,
    val text: Color,
    val muted: Color,
    val line: Color,
    val hover: Color,
    val dark: Boolean,
) {
    /** 面板色：壁纸要从顶栏底栏后面透出来，不透明度由 `ui_sidebar_opacity` 定。 */
    fun panel(opacityPercent: Int): Color =
        background.copy(alpha = SettingsLogic.clampPercent(opacityPercent) / 100f)
}

val LocalPclColors = staticCompositionLocalOf { lightColors(PclGreen) }

fun lightColors(accent: Color): PclColors = PclColors(
    accent = accent,
    accentDeep = accent.darken(0.22f),
    background = PclBg,
    text = PclText,
    muted = PclMuted,
    line = PclLine,
    hover = accent.copy(alpha = 0.10f),
    dark = false,
)

fun darkColors(accent: Color): PclColors = PclColors(
    accent = accent,
    accentDeep = accent.darken(0.18f),
    background = PclBgDark,
    text = PclTextDark,
    muted = PclMutedDark,
    line = PclLineDark,
    hover = accent.copy(alpha = 0.18f),
    dark = true,
)

private fun Color.darken(amount: Float): Color = Color(
    red = (red * (1 - amount)).coerceIn(0f, 1f),
    green = (green * (1 - amount)).coerceIn(0f, 1f),
    blue = (blue * (1 - amount)).coerceIn(0f, 1f),
    alpha = alpha,
)

fun accentFrom(themeColor: String): Color = Color(SettingsLogic.parseColor(themeColor).toInt())

@Composable
fun PyMclTheme(
    themeColor: String = "#2E9B6B",
    dark: Boolean = false,
    content: @Composable () -> Unit,
) {
    val accent = accentFrom(themeColor)
    val colors = if (dark) darkColors(accent) else lightColors(accent)
    val onAccent = if (SettingsLogic.isLightColor(SettingsLogic.parseColor(themeColor))) {
        Color(0xFF1A1A1A)
    } else {
        Color.White
    }
    val scheme = if (dark) {
        darkColorScheme(
            primary = colors.accent,
            onPrimary = onAccent,
            primaryContainer = colors.hover,
            onPrimaryContainer = colors.text,
            secondary = colors.accentDeep,
            onSecondary = onAccent,
            background = colors.background,
            surface = colors.background,
            surfaceVariant = colors.hover,
            onBackground = colors.text,
            onSurface = colors.text,
            onSurfaceVariant = colors.muted,
            outline = colors.line,
            error = PclDanger,
        )
    } else {
        lightColorScheme(
            primary = colors.accent,
            onPrimary = onAccent,
            primaryContainer = colors.hover,
            onPrimaryContainer = colors.accentDeep,
            secondary = colors.accentDeep,
            onSecondary = onAccent,
            background = colors.background,
            surface = colors.background,
            surfaceVariant = colors.hover,
            onBackground = colors.text,
            onSurface = colors.text,
            onSurfaceVariant = colors.muted,
            outline = colors.line,
            error = PclDanger,
        )
    }
    CompositionLocalProvider(LocalPclColors provides colors) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
