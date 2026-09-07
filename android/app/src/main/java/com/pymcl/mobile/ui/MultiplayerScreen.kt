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

@Composable
fun MultiplayerScreen(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("联机", style = MaterialTheme.typography.headlineMedium)
        Text(
            "局域网 / 第三方联机占位；后续里程碑接入房间发现与加入。",
            style = MaterialTheme.typography.bodyLarge,
        )
    }
}
