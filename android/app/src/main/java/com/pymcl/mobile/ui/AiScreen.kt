package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.AiConfig
import com.pymcl.mobile.data.AiHistory
import com.pymcl.mobile.data.AiMessage
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.AiStore
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * AI 页。对齐 `app/pages/ai_page.py`：对话、当前模式、新对话，配置在设置页。
 *
 * 会话落在 `ai_chats.json`（跟桌面同名同结构），走 [AiStore]；
 * 带给模型的历史由 [AiHistory] 裁剪，工具调用那条链路归 AiAgent，这里只做纯问答。
 */
@Composable
fun AiScreen(
    modifier: Modifier = Modifier,
    onOpenSettings: () -> Unit = {},
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    val rows = remember { mutableStateListOf<AiMessage>() }
    var store by remember { mutableStateOf<AiStore?>(null) }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var config by remember { mutableStateOf(AiConfig()) }

    // 读会话是文件 IO，不能挡住第一帧
    LaunchedEffect(Unit) {
        val loaded = withContext(Dispatchers.IO) {
            val s = AiStore(File(Paths.root, "ai_chats.json")).load()
            s to s.active().messages.toList()
        }
        store = loaded.first
        rows.addAll(loaded.second)
        config = withContext(Dispatchers.IO) { AiConfig.current() }
    }

    // 新消息落定就把列表推到底
    LaunchedEffect(rows.size, busy) {
        if (rows.isNotEmpty()) listState.animateScrollToItem(rows.size - 1)
    }

    fun send() {
        val text = input.trim()
        val s = store ?: return
        if (text.isEmpty() || busy) return
        input = ""
        error = null
        val mine = AiMessage(role = "user", content = text)
        rows.add(mine)
        scope.launch {
            busy = true
            try {
                val reply = withContext(Dispatchers.IO) {
                    s.append(s.active().id, mine)
                    // 只把裁剪过的那段带给模型：一整条长会话发过去既慢又容易超上下文
                    val history = AiHistory.trim(rows.toList())
                    AiRepo.complete(config, history)
                }
                val answer = AiMessage(role = "assistant", content = reply.content)
                rows.add(answer)
                withContext(Dispatchers.IO) {
                    s.append(s.active().id, answer)
                    s.save()
                }
            } catch (e: Exception) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }

    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                AiRepo.describe(config),
                modifier = Modifier.weight(1f),
                color = c.muted,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            PclLink(t("配置")) { onOpenSettings() }
            PclLink(t("新对话"), enabled = !busy && rows.isNotEmpty()) {
                val s = store ?: return@PclLink
                scope.launch {
                    rows.clear()
                    withContext(Dispatchers.IO) {
                        s.newChat()
                        s.save()
                    }
                }
            }
        }

        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            state = listState,
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 4.dp),
        ) {
            if (rows.isEmpty() && !busy) {
                item(key = "hint") {
                    Text(
                        t("直接发消息。同一对话里最近 {0} 条会一起带给模型，").fmt(AiHistory.MAX_MESSAGES) +
                            t("换话题点「新对话」。"),
                        color = c.muted,
                        fontSize = 13.sp,
                    )
                }
            }
            // key 带下标：同一毫秒内连发两条也不会撞 key
            itemsIndexed(rows, key = { i, m -> "$i-${m.time}-${m.role}" }) { _, m ->
                AiBubble(m.role, m.content)
            }
            if (busy) {
                item(key = "pending") { AiBubble("assistant", "…", streaming = true) }
            }
        }

        error?.let {
            Text(it, color = com.pymcl.mobile.theme.PclDanger, fontSize = 12.sp, maxLines = 3)
        }

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                label = { Text(t("消息")) },
                modifier = Modifier.weight(1f),
                colors = pclFieldColors(),
                enabled = !busy && store != null,
            )
            Spacer(Modifier.width(8.dp))
            if (busy) {
                OutlinedButton(onClick = { busy = false }) { Text(t("停止")) }
            } else {
                PclButton(t("发送"), enabled = input.isNotBlank() && store != null) { send() }
            }
        }
    }
}

@Composable
private fun AiBubble(role: String, content: String, streaming: Boolean = false) {
    val c = LocalPclColors.current
    val mine = role == "user"
    Column(
        Modifier
            .fillMaxWidth()
            .background(if (mine) c.hover else Color.Transparent, RoundedCornerShape(10.dp))
            .border(1.dp, c.line, RoundedCornerShape(10.dp))
            .padding(10.dp),
    ) {
        Text(
            when {
                mine -> t("你")
                streaming -> t("助手 · 输出中")
                else -> t("助手")
            },
            color = if (mine) c.accent else c.muted,
            fontSize = 11.sp,
        )
        Text(content, fontSize = 14.sp, color = c.text)
    }
}
