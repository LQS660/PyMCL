package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.model.AiMessage

@Composable
fun AiScreen(
    messages: List<AiMessage>,
    onSend: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var input by rememberSaveable { mutableStateOf("") }
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("AI", style = MaterialTheme.typography.headlineMedium)
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(messages, key = { "${it.timestamp}-${it.role}" }) { msg ->
                Text(
                    "${msg.role}: ${msg.content}",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
        OutlinedTextField(
            value = input,
            onValueChange = { input = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("输入问题…") },
            singleLine = true,
        )
        Button(
            onClick = {
                onSend(input)
                input = ""
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("发送")
        }
    }
}
