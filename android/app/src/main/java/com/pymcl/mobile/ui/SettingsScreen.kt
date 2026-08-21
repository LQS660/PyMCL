package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.BuildConfig

@Composable
fun SettingsScreen(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("设置", style = MaterialTheme.typography.headlineMedium)
        Text("PyMCL 独立骨架", style = MaterialTheme.typography.titleMedium)
        Text("版本 ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodyLarge)
        Text(
            "FCL 运行时与游戏启动将在后续里程碑接入；当前仅 UI 与数据层占位。",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
