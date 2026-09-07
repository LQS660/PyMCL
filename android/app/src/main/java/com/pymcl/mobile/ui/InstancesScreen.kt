package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.model.GameInstance

@Composable
fun InstancesScreen(
    instances: List<GameInstance>,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("实例", style = MaterialTheme.typography.headlineMedium)
        if (instances.isEmpty()) {
            Text("暂无实例；下载页拉取版本后可创建。", style = MaterialTheme.typography.bodyLarge)
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(instances, key = { it.id }) { instance ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(instance.name, style = MaterialTheme.typography.titleMedium)
                            Text("版本 ${instance.versionId}", style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }
    }
}
