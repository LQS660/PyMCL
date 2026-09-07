package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.model.LaunchPlan

@Composable
fun LaunchScreen(
    plan: LaunchPlan?,
    onLaunch: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("启动", style = MaterialTheme.typography.headlineMedium)
        Text(
            plan?.message ?: "选择实例后在此启动游戏。",
            style = MaterialTheme.typography.bodyLarge,
        )
        Button(onClick = onLaunch, enabled = plan != null) {
            Text("进入游戏（占位）")
        }
    }
}
