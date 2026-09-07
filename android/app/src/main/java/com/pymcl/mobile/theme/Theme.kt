package com.pymcl.mobile.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val PclGreen = Color(0xFF2E9B6B)
val PclGreenDeep = Color(0xFF1E7A52)
val PclBg = Color(0xFFFFFFFF)
val PclText = Color(0xFF2B2B2B)
val PclMuted = Color(0xFF888888)
val PclLine = Color(0xFFE6E6E6)
val PclHover = Color(0xFFF3F7F5)

private val Scheme = lightColorScheme(
    primary = PclGreen,
    onPrimary = Color.White,
    primaryContainer = PclHover,
    onPrimaryContainer = PclGreenDeep,
    secondary = PclGreenDeep,
    onSecondary = Color.White,
    secondaryContainer = PclHover,
    onSecondaryContainer = PclGreenDeep,
    tertiary = PclGreen,
    background = PclBg,
    surface = PclBg,
    surfaceVariant = PclHover,
    onBackground = PclText,
    onSurface = PclText,
    onSurfaceVariant = PclMuted,
    outline = PclLine,
)

@Composable
fun PyMclTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, content = content)
}
