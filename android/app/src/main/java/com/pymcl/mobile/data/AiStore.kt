package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** 模型要求调用的一个工具。arguments 是模型给的原始 JSON 文本，合法与否由工具层判断。 */
data class AiToolCall(
    val id: String,
    val name: String,
    val arguments: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("type", "function")
        .put("function", JSONObject().put("name", name).put("arguments", arguments))

    companion object {
        fun fromJson(o: JSONObject): AiToolCall? {
            val fn = o.optJSONObject("function")
            val name = fn?.optString("name").orEmpty()
            val id = o.optString("id")
            if (id.isEmpty() && name.isEmpty()) return null
            return AiToolCall(id, name, fn?.optString("arguments").orEmpty())
        }
    }
}

/**
 * 一条对话消息。role 取 system / user / assistant / tool，与 OpenAI 兼容口一致。
 * assistant 可能带 [toolCalls]；tool 角色必须带 [toolCallId] 回应其中一条。
 */
data class AiMessage(
    val role: String,
    val content: String,
    val time: Long = System.currentTimeMillis(),
    val toolCalls: List<AiToolCall> = emptyList(),
    val toolCallId: String = "",
    val name: String = "",
) {
    fun toJson(): JSONObject {
        val o = JSONObject()
            .put("role", role)
            .put("content", content)
            .put("time", time)
        if (toolCalls.isNotEmpty()) {
            val arr = JSONArray()
            toolCalls.forEach { arr.put(it.toJson()) }
            o.put("tool_calls", arr)
        }
        if (toolCallId.isNotEmpty()) o.put("tool_call_id", toolCallId)
        if (name.isNotEmpty()) o.put("name", name)
        return o
    }

    /** 发给接口的形状：只带协议字段，不带 time。 */
    fun toApiJson(): JSONObject {
        val o = JSONObject().put("role", role)
        // assistant 只发工具调用、没有正文时，content 传 null 而不是空串，部分服务端会拒空串。
        if (role == "assistant" && toolCalls.isNotEmpty() && content.isEmpty()) o.put("content", JSONObject.NULL)
        else o.put("content", content)
        if (toolCalls.isNotEmpty()) {
            val arr = JSONArray()
            toolCalls.forEach { arr.put(it.toJson()) }
            o.put("tool_calls", arr)
        }
        if (role == "tool") {
            o.put("tool_call_id", toolCallId)
            if (name.isNotEmpty()) o.put("name", name)
        }
        return o
    }

    companion object {
        val API_ROLES = setOf("system", "user", "assistant", "tool")

        fun fromJson(o: JSONObject): AiMessage? {
            val role = o.optString("role").trim()
            if (role.isEmpty()) return null
            val calls = ArrayList<AiToolCall>()
            val arr = o.optJSONArray("tool_calls")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    arr.optJSONObject(i)?.let { c -> AiToolCall.fromJson(c)?.let { calls.add(it) } }
                }
            }
            return AiMessage(
                role = role,
                content = if (o.isNull("content")) "" else o.optString("content"),
                time = o.optLong("time", 0L),
                toolCalls = calls,
                toolCallId = o.optString("tool_call_id"),
                name = o.optString("name"),
            )
        }
    }
}

/** 一个会话。messages 只保留最近 [AiStore.MAX_MESSAGES] 条，与桌面 store.py 一致。 */
class AiChat(
    val id: String,
    var title: String = "",
    val messages: MutableList<AiMessage> = mutableListOf(),
    var updated: Long = System.currentTimeMillis(),
) {
    fun toJson(): JSONObject {
        val arr = JSONArray()
        messages.forEach { arr.put(it.toJson()) }
        return JSONObject()
            .put("id", id)
            .put("title", title)
            .put("updated", updated)
            .put("messages", arr)
    }

    companion object {
        fun fromJson(o: JSONObject): AiChat? {
            val id = o.optString("id").trim()
            if (id.isEmpty()) return null
            val chat = AiChat(id, o.optString("title"), updated = o.optLong("updated", 0L))
            val arr = o.optJSONArray("messages") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val m = arr.optJSONObject(i) ?: continue
                AiMessage.fromJson(m)?.let { chat.messages.add(it) }
            }
            while (chat.messages.size > AiStore.MAX_MESSAGES) chat.messages.removeAt(0)
            return chat
        }
    }
}

/**
 * 请求体里带多少历史。对齐桌面 agent.py 的 MAX_HISTORY=24，再加一道字符预算，
 * 防止几条超长消息把上下文窗口撑爆。
 */
object AiHistory {
    const val MAX_MESSAGES = 24
    const val MAX_CHARS = 12_000

    /**
     * 从旧到新丢，直到条数与字符数都在预算内。规则：
     * - 只保留 system / user / assistant / tool 四种角色，其它（比如 UI 自己的错误提示）不进请求；
     * - 最新一条永远保留；它自己就超出字符预算时，只留它并截掉开头；
     * - 开头的 system 消息不占条数预算，但占字符预算；
     * - 截完之后修一遍工具配对（见 [repairToolPairs]），别把孤儿 tool 消息发出去。
     */
    fun trim(
        history: List<AiMessage>,
        maxMessages: Int = MAX_MESSAGES,
        maxChars: Int = MAX_CHARS,
    ): List<AiMessage> {
        val usable = history.filter { it.role in AiMessage.API_ROLES && (it.content.isNotEmpty() || it.toolCalls.isNotEmpty()) }
        if (usable.isEmpty()) return emptyList()
        val system = usable.firstOrNull()?.takeIf { it.role == "system" }
        val rest = if (system != null) usable.drop(1) else usable
        if (rest.isEmpty()) return listOf(system!!)

        var budgetChars = maxChars - (system?.content?.length ?: 0)
        val kept = ArrayDeque<AiMessage>()
        for (m in rest.asReversed()) {
            if (kept.size >= maxMessages) break
            if (kept.isNotEmpty() && m.weight() > budgetChars) break
            kept.addFirst(m)
            budgetChars -= m.weight()
        }
        if (kept.size == 1 && kept.first().content.length > maxChars) {
            val only = kept.first()
            kept.clear()
            kept.addFirst(only.copy(content = only.content.takeLast(maxChars)))
        }
        val body = repairToolPairs(kept.toList())
        return if (system != null) listOf(system) + body else body
    }

    private fun AiMessage.weight(): Int = content.length + toolCalls.sumOf { it.name.length + it.arguments.length }

    /**
     * 截断可能把「assistant 要工具」和「tool 回结果」劈开。接口对这种半截是直接 400 的，所以：
     * - tool 消息找不到前面宣告它的 assistant → 丢；
     * - assistant 的某条 tool_call 后面没有对应 tool 结果 → 去掉它的 tool_calls，只留正文；正文也空就整条丢。
     */
    fun repairToolPairs(messages: List<AiMessage>): List<AiMessage> {
        val announced = HashSet<String>()
        val firstPass = ArrayList<AiMessage>()
        for (m in messages) {
            if (m.role == "tool") {
                if (m.toolCallId.isEmpty() || m.toolCallId !in announced) continue
                firstPass.add(m)
                continue
            }
            if (m.role == "assistant") m.toolCalls.forEach { announced.add(it.id) }
            firstPass.add(m)
        }
        val answered = firstPass.filter { it.role == "tool" }.map { it.toolCallId }.toSet()
        val out = ArrayList<AiMessage>()
        // 某条 assistant 的 tool_calls 被拿掉后，它名下已经收到的那几条 tool 结果也成了孤儿，一并跳过。
        val orphaned = HashSet<String>()
        for (m in firstPass) {
            if (m.role == "assistant" && m.toolCalls.isNotEmpty() && m.toolCalls.any { it.id !in answered }) {
                m.toolCalls.forEach { orphaned.add(it.id) }
                if (m.content.isNotEmpty()) out.add(m.copy(toolCalls = emptyList()))
                continue
            }
            if (m.role == "tool" && m.toolCallId in orphaned) continue
            out.add(m)
        }
        return out
    }

    /** 请求体用的 messages 数组：只带协议字段。 */
    fun toApiArray(messages: List<AiMessage>): JSONArray {
        val arr = JSONArray()
        messages.forEach { arr.put(it.toApiJson()) }
        return arr
    }
}

/**
 * 多会话持久化。文件名与桌面一致（ai_chats.json），放在 PYMCL 数据根下。
 * 不直接依赖 Android，路径由调用方传进来，纯 JVM 单测可以给临时文件。
 */
class AiStore(private val file: File) {
    val chats: MutableList<AiChat> = mutableListOf()
    var activeId: String = ""
        private set

    @Synchronized
    fun load(): AiStore {
        chats.clear()
        activeId = ""
        val root = runCatching { JSONObject(file.readText(Charsets.UTF_8)) }.getOrNull()
        if (root != null) {
            val arr = root.optJSONArray("chats") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                AiChat.fromJson(o)?.let { chats.add(it) }
            }
            activeId = root.optString("active")
        }
        while (chats.size > MAX_CHATS) chats.removeAt(chats.size - 1)
        if (chats.none { it.id == activeId }) activeId = chats.firstOrNull()?.id ?: ""
        return this
    }

    @Synchronized
    fun save() {
        val arr = JSONArray()
        chats.take(MAX_CHATS).forEach { arr.put(it.toJson()) }
        val root = JSONObject().put("active", activeId).put("chats", arr)
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(root.toString(2), Charsets.UTF_8)
        if (file.exists()) file.delete()
        if (!tmp.renameTo(file)) {
            tmp.copyTo(file, overwrite = true)
            tmp.delete()
        }
    }

    /** 当前会话；一个都没有就建一个。 */
    @Synchronized
    fun active(): AiChat {
        chats.firstOrNull { it.id == activeId }?.let { return it }
        return newChat()
    }

    @Synchronized
    fun newChat(): AiChat {
        val chat = AiChat(newId())
        chats.add(0, chat)
        while (chats.size > MAX_CHATS) chats.removeAt(chats.size - 1)
        activeId = chat.id
        return chat
    }

    @Synchronized
    fun setActive(id: String): AiChat? {
        val chat = chats.firstOrNull { it.id == id } ?: return null
        activeId = id
        return chat
    }

    @Synchronized
    fun deleteChat(id: String) {
        chats.removeAll { it.id == id }
        if (activeId == id) activeId = chats.firstOrNull()?.id ?: ""
    }

    /** 追加一条消息；首条用户消息顺手当标题。 */
    @Synchronized
    fun append(chatId: String, msg: AiMessage): AiChat? {
        val chat = chats.firstOrNull { it.id == chatId } ?: return null
        chat.messages.add(msg)
        while (chat.messages.size > MAX_MESSAGES) chat.messages.removeAt(0)
        chat.updated = System.currentTimeMillis()
        if (chat.title.isBlank() && msg.role == "user") {
            chat.title = msg.content.trim().replace('\n', ' ').take(24)
        }
        return chat
    }

    private fun newId(): String {
        var n = 0
        while (true) {
            val id = "chat-${System.currentTimeMillis()}" + if (n > 0) "-$n" else ""
            if (chats.none { it.id == id }) return id
            n++
        }
    }

    companion object {
        const val FILE_NAME = "ai_chats.json"
        const val MAX_CHATS = 40
        const val MAX_MESSAGES = 24
    }
}
