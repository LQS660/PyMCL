package com.pymcl.mobile.data

import com.pymcl.mobile.model.AiMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class AiRepo {
    private val _messages = MutableStateFlow<List<AiMessage>>(emptyList())
    val messages: StateFlow<List<AiMessage>> = _messages.asStateFlow()

    fun send(prompt: String): Result<AiMessage> {
        if (prompt.isBlank()) {
            return Result.failure(IllegalArgumentException("请输入内容"))
        }
        val userMsg = AiMessage(role = "user", content = prompt)
        val reply = AiMessage(
            role = "assistant",
            content = "AI 助手尚未接入后端；当前为骨架占位。",
        )
        _messages.value = _messages.value + userMsg + reply
        return Result.success(reply)
    }

    fun clear() {
        _messages.value = emptyList()
    }
}
