package com.pymcl.mobile.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.CloudDownload
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
import androidx.compose.ui.graphics.vector.ImageVector

enum class MainTab(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Launch("launch", "启动", Icons.Default.PlayArrow),
    Instances("instances", "实例", Icons.Default.Storage),
    Multiplayer("multiplayer", "联机", Icons.Default.Groups),
    Download("download", "下载", Icons.Default.CloudDownload),
    Ai("ai", "AI", Icons.AutoMirrored.Filled.Chat),
    Settings("settings", "设置", Icons.Default.Settings),
}
