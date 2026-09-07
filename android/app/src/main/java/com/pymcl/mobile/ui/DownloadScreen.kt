package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.model.DownloadTask
import com.pymcl.mobile.model.VersionManifest

@Composable
fun DownloadScreen(
    manifest: VersionManifest?,
    tasks: List<DownloadTask>,
    onRefreshManifest: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("下载", style = MaterialTheme.typography.headlineMedium)
        Button(onClick = onRefreshManifest) {
            Text(if (manifest == null) "拉取版本清单" else "刷新版本清单")
        }
        manifest?.let {
            Text(
                "最新正式版 ${it.latestRelease} · 快照 ${it.latestSnapshot}",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text("共 ${it.versions.size} 个版本条目", style = MaterialTheme.typography.bodySmall)
        }
        if (tasks.isNotEmpty()) {
            Text("任务", style = MaterialTheme.typography.titleMedium)
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(tasks, key = { it.id }) { task ->
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("${task.label} · ${task.status}")
                        LinearProgressIndicator(
                            progress = { task.progress.coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        }
    }
}
