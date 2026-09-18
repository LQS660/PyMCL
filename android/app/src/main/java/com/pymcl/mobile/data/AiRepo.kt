package com.pymcl.mobile.data

import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.nio.CharBuffer

/**
 * AI 接入配置，全部来自本地设置（config.json）。源码里不放任何令牌：
 * 用户填了密钥就直连 OpenAI 兼容口；没填就走公益网关，令牌由网关保管。
 */
data class AiConfig(
    /** 自定义 OpenAI 兼容口，到 /v1 为止。留空用 [DEFAULT_BASE]。 */
    val baseUrl: String = "",
    /** 留空用 [DEFAULT_MODEL]。 */
    val model: String = "",
    /** 留空 = 不走自定义口。 */
    val apiKey: String = "",
    /** 公益网关根地址（不带 /v1、不带 /pymcl/chat）。留空用 [DEFAULT_GATEWAY]。 */
    val gatewayUrl: String = "",
) {
    val effectiveModel: String get() = model.trim().ifEmpty { DEFAULT_MODEL }
    val effectiveGateway: String get() = gatewayUrl.trim().trimEnd('/').ifEmpty { DEFAULT_GATEWAY }
    val hasKey: Boolean get() = apiKey.isNotBlank()

    companion object {
        /** 公益口只认全小写 host；HTTPS 无有效证书，必须 HTTP。这只是地址，不含令牌。 */
        const val DEFAULT_BASE = "http://new.s.3q.hair/v1"
        const val DEFAULT_MODEL = "deepseek-v4-flash"

        /** 打包前填成公益网关公网地址，同桌面 ai/defaults.py 的 DEFAULT_GATEWAY_URL。 */
        const val DEFAULT_GATEWAY = ""

        fun fromConfig(cfg: JSONObject) = AiConfig(
            baseUrl = cfg.optString("ai_base_url", ""),
            model = cfg.optString("ai_model", ""),
            apiKey = cfg.optString("ai_api_key", ""),
            // 桌面 config.py 里这个键叫 ai_gateway_url；安卓早先写成了 ai_url。
            // 两个都认、新名优先，两端的 config.json 才能互相拷着用。
            gatewayUrl = cfg.optString("ai_gateway_url", "")
                .ifBlank { cfg.optString("ai_url", "") },
        )

        /** 从当前落盘的配置读一份。设置页与 AI 页都走它，免得各读各的键。 */
        fun current(): AiConfig = fromConfig(InstanceStore.loadConfig())
    }
}

/** 解析好的目标：按顺序尝试 [urls]，全部带 [headers]。 */
data class AiEndpoint(
    val mode: String,
    val urls: List<String>,
    val headers: Map<String, String>,
    val model: String,
)

class AiConfigError(message: String) : RuntimeException(message)

class AiCancelled : RuntimeException("已停止")

/** 一次请求的把手：UI 线程调 [cancel] 能把正在读的连接掐掉。 */
class AiCall {
    @Volatile
    var cancelled = false
        private set

    @Volatile
    internal var call: Call? = null

    fun cancel() {
        cancelled = true
        call?.cancel()
    }
}

/**
 * 把任意切分的 SSE 文本流拼回一个个事件。
 * 只认 data 字段（多行 data 用 \n 拼接）；event / id / retry 忽略；以 ':' 开头的注释行忽略。
 * 换行接受 \n、\r\n、\r。半包（一行还没到齐）留在缓冲里等下一次 [feed]。
 */
class SseParser {
    private val pending = StringBuilder()
    private val dataLines = ArrayList<String>()

    /** 喂一段文本，返回这段里凑齐的事件 data。 */
    fun feed(chunk: CharSequence): List<String> {
        val out = ArrayList<String>()
        pending.append(chunk)
        while (true) {
            val nl = indexOfLineEnd() ?: break
            val (end, skip) = nl
            val line = pending.substring(0, end)
            pending.delete(0, end + skip)
            processLine(line, out)
        }
        return out
    }

    /** 流结束：没有以空行收尾的最后一个事件也要吐出来。 */
    fun finish(): List<String> {
        val out = ArrayList<String>()
        if (pending.isNotEmpty()) {
            processLine(pending.toString(), out)
            pending.setLength(0)
        }
        dispatch(out)
        return out
    }

    private fun indexOfLineEnd(): Pair<Int, Int>? {
        for (i in pending.indices) {
            when (pending[i]) {
                '\n' -> return i to 1
                '\r' -> {
                    // 末尾的 \r 可能是 \r\n 的前半，等下一包再定。
                    if (i == pending.length - 1) return null
                    return if (pending[i + 1] == '\n') i to 2 else i to 1
                }
            }
        }
        return null
    }

    private fun processLine(line: String, out: MutableList<String>) {
        if (line.isEmpty()) {
            dispatch(out)
            return
        }
        if (line[0] == ':') return
        val colon = line.indexOf(':')
        val field = if (colon < 0) line else line.substring(0, colon)
        var value = if (colon < 0) "" else line.substring(colon + 1)
        if (value.startsWith(" ")) value = value.substring(1)
        if (field == "data") dataLines.add(value)
    }

    private fun dispatch(out: MutableList<String>) {
        if (dataLines.isEmpty()) return
        out.add(dataLines.joinToString("\n"))
        dataLines.clear()
    }
}

/** 流式分片里 tool_calls 的一个增量：同一 index 的碎片按顺序拼起来才是一条完整调用。 */
data class ToolDelta(
    val index: Int,
    val id: String = "",
    val name: String = "",
    val arguments: String = "",
)

/** 一个流式分片解析出来的东西。 */
data class StreamPiece(
    val text: String = "",
    val done: Boolean = false,
    val error: String? = null,
    val toolDeltas: List<ToolDelta> = emptyList(),
    val finishReason: String = "",
)

/** 一轮模型回复：正文 + 要求调用的工具（可能都空）。 */
data class AiReply(
    val content: String = "",
    val toolCalls: List<AiToolCall> = emptyList(),
    val finishReason: String = "",
)

object AiRepo {
    private const val JSON_TYPE = "application/json; charset=utf-8"
    private const val GATEWAY_PATH = "/pymcl/chat"

    /** 根据配置决定往哪打。没密钥也没网关就抛 [AiConfigError]，让 UI 指引用户去设置。 */
    fun resolve(cfg: AiConfig): AiEndpoint {
        val common = mapOf(
            "User-Agent" to Paths.UA,
            "Content-Type" to JSON_TYPE,
            "X-PyMCL-Client" to "PyMCL/${Paths.APP_VERSION}",
        )
        if (cfg.hasKey) {
            val base = normalizeBase(cfg.baseUrl.ifBlank { AiConfig.DEFAULT_BASE })
            return AiEndpoint(
                mode = "custom",
                urls = listOf("$base/chat/completions"),
                headers = common + ("Authorization" to "Bearer ${cfg.apiKey.trim()}"),
                model = cfg.effectiveModel,
            )
        }
        val gateway = cfg.effectiveGateway
        if (gateway.isEmpty()) {
            throw AiConfigError("还没配置 AI：到「设置」填自定义接口的密钥，或填公益网关地址")
        }
        return AiEndpoint(
            mode = "gateway",
            urls = listOf("$gateway$GATEWAY_PATH", "$gateway/v1/chat/completions"),
            headers = common,
            model = cfg.effectiveModel,
        )
    }

    /** 设置页 / AI 页顶部显示用的一句话。 */
    fun describe(cfg: AiConfig): String = when {
        cfg.hasKey -> "自定义接口 ${normalizeBase(cfg.baseUrl.ifBlank { AiConfig.DEFAULT_BASE })} · ${cfg.effectiveModel}"
        cfg.effectiveGateway.isNotEmpty() -> "公益网关 ${cfg.effectiveGateway} · ${cfg.effectiveModel}"
        else -> "未配置：填密钥或公益网关地址"
    }

    /** 去掉尾部斜杠，保证以 /v1 结尾（与桌面 client.normalize_base 一致）。 */
    fun normalizeBase(url: String): String {
        val u = url.trim().trimEnd('/')
        if (u.isEmpty()) return ""
        return if (u.endsWith("/v1")) u else "$u/v1"
    }

    /**
     * 发一轮纯聊天。[history] 已经是要带上的上下文（含最新一句用户消息）。
     * stream=true 时每收到一段文本就回调 [onDelta]；无论是否流式，返回完整回复正文。
     * 网关如果不理 stream 直接回 JSON，也当一整段交给 [onDelta]。
     */
    fun chat(
        cfg: AiConfig,
        history: List<AiMessage>,
        stream: Boolean = true,
        handle: AiCall = AiCall(),
        onDelta: (String) -> Unit = {},
    ): String = complete(cfg, history, tools = null, stream = stream, handle = handle, onDelta = onDelta).content

    /**
     * 发一轮带工具声明的请求，回 [AiReply]（正文 + tool_calls）。
     * [tools] 是 OpenAI function-calling 形状的数组（见 AiTools.schemas）；null / 空 = 不带工具。
     */
    fun complete(
        cfg: AiConfig,
        history: List<AiMessage>,
        tools: JSONArray? = null,
        stream: Boolean = true,
        handle: AiCall = AiCall(),
        onDelta: (String) -> Unit = {},
    ): AiReply {
        val ep = resolve(cfg)
        val payload = chatBody(ep.model, history, stream, tools)
        var last: String = "接口无可用路径"
        for ((i, url) in ep.urls.withIndex()) {
            if (handle.cancelled) throw AiCancelled()
            val builder = Request.Builder().url(url)
            ep.headers.forEach { (k, v) -> builder.header(k, v) }
            builder.post(payload.toRequestBody(JSON_TYPE.toMediaType()))
            val call = Http.client.newCall(builder.build())
            handle.call = call
            try {
                call.execute().use { resp ->
                    if (!resp.isSuccessful) {
                        val body = resp.body?.string().orEmpty()
                        val msg = formatError(resp.code, body)
                        // 401/403/429 是钥匙或额度问题，换路径也没用；404/405 才值得试下一条。
                        if (resp.code in setOf(401, 403, 429) || i == ep.urls.lastIndex) throw HttpException(msg)
                        last = msg
                        return@use
                    }
                    val type = resp.header("Content-Type").orEmpty().lowercase()
                    if (stream && type.contains("text/event-stream")) {
                        return readStream(resp.body!!.byteStream(), handle, onDelta)
                    }
                    val reply = parseReply(resp.body?.string().orEmpty())
                    if (reply.content.isNotEmpty()) onDelta(reply.content)
                    return reply
                }
            } catch (e: IOException) {
                if (handle.cancelled) throw AiCancelled()
                if (i == ep.urls.lastIndex) throw HttpException("连不上接口: ${e.message ?: e.toString()}")
                last = e.message ?: e.toString()
            }
        }
        throw HttpException(last)
    }

    private fun readStream(
        input: InputStream,
        handle: AiCall,
        onDelta: (String) -> Unit,
    ): AiReply {
        val parser = SseParser()
        val full = StringBuilder()
        val toolAcc = java.util.TreeMap<Int, ToolAcc>()
        var finishReason = ""
        var done = false
        // 按字符读而不是按字节读：InputStreamReader 自己处理跨包的多字节 UTF-8。
        val reader = InputStreamReader(input, Charsets.UTF_8)
        val buf = CharArray(4096)
        fun apply(events: List<String>) {
            for (data in events) {
                if (done) return
                val piece = parsePiece(data)
                if (piece.error != null) throw HttpException(piece.error)
                if (piece.text.isNotEmpty()) {
                    full.append(piece.text)
                    onDelta(piece.text)
                }
                for (d in piece.toolDeltas) {
                    val slot = toolAcc.getOrPut(d.index) { ToolAcc() }
                    if (d.id.isNotEmpty()) slot.id = d.id
                    if (d.name.isNotEmpty()) slot.name = d.name
                    slot.arguments.append(d.arguments)
                }
                if (piece.finishReason.isNotEmpty()) finishReason = piece.finishReason
                if (piece.done) done = true
            }
        }
        while (!done) {
            if (handle.cancelled) throw AiCancelled()
            val n = try {
                reader.read(buf)
            } catch (e: IOException) {
                if (handle.cancelled) throw AiCancelled()
                // 已经收到内容后断流：把手上的先交出去，别整段作废。
                if (full.isNotEmpty() || toolAcc.isNotEmpty()) break
                throw HttpException("流式读取中断: ${e.message ?: e.toString()}")
            }
            if (n < 0) break
            apply(parser.feed(CharBuffer.wrap(buf, 0, n)))
        }
        if (!done) apply(parser.finish())
        val calls = toolAcc.map { (idx, acc) -> acc.toCall(idx) }
        if (full.isEmpty() && calls.isEmpty() && !done) throw HttpException("接口没有返回内容")
        return AiReply(full.toString(), calls, finishReason)
    }

    private class ToolAcc {
        var id = ""
        var name = ""
        val arguments = StringBuilder()

        fun toCall(index: Int) = AiToolCall(
            id = id.ifEmpty { "call_$index" },
            name = name,
            arguments = arguments.toString().ifEmpty { "{}" },
        )
    }

    /**
     * Android 自带的 org.json 对 JSON null 的 optString 会给 "null" 字面量，
     * 桌面 JVM 那份给 ""。统一成：缺失或 null 都算空串。
     */
    private fun JSONObject.str(key: String): String =
        if (has(key) && !isNull(key)) optString(key) else ""

    /**
     * 一个 SSE data 段 → 文本增量 / 工具调用增量 / 结束 / 错误。
     * 同时认 OpenAI 增量（delta）、整条 message 与网关的 reply 形状。
     */
    internal fun parsePiece(data: String): StreamPiece {
        val s = data.trim()
        if (s.isEmpty()) return StreamPiece()
        if (s == "[DONE]") return StreamPiece(done = true)
        val o = runCatching { JSONObject(s) }.getOrNull() ?: return StreamPiece()
        o.optJSONObject("error")?.let { err ->
            val msg = err.str("message").ifBlank { err.toString() }
            return StreamPiece(error = msg)
        }
        if (o.opt("error") is String && o.str("error").isNotBlank()) {
            return StreamPiece(error = o.str("error"))
        }
        val choice = o.optJSONArray("choices")?.optJSONObject(0)
        if (choice != null) {
            val delta = choice.optJSONObject("delta")
            val message = choice.optJSONObject("message")
            val text = delta?.str("content").orEmpty().ifEmpty { message?.str("content").orEmpty() }
            val deltas = ArrayList<ToolDelta>()
            val arr = delta?.optJSONArray("tool_calls") ?: message?.optJSONArray("tool_calls")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val tc = arr.optJSONObject(i) ?: continue
                    val fn = tc.optJSONObject("function")
                    deltas.add(
                        ToolDelta(
                            index = tc.optInt("index", i),
                            id = tc.str("id"),
                            name = fn?.str("name").orEmpty(),
                            arguments = fn?.str("arguments").orEmpty(),
                        ),
                    )
                }
            }
            val reason = choice.str("finish_reason")
            val finished = reason == "stop" || reason == "length" || reason == "tool_calls"
            return StreamPiece(text = text, done = finished, toolDeltas = deltas, finishReason = reason)
        }
        val flat = o.str("reply").ifBlank { o.str("content") }
        return StreamPiece(text = flat)
    }

    internal fun chatBody(model: String, history: List<AiMessage>, stream: Boolean, tools: JSONArray? = null): String {
        val body = JSONObject()
            .put("model", model)
            .put("stream", stream)
            .put("temperature", 0.3)
            .put("max_tokens", 2048)
            .put("messages", AiHistory.toApiArray(history))
        if (tools != null && tools.length() > 0) {
            body.put("tools", tools)
            body.put("tool_choice", "auto")
        }
        return body.toString()
    }

    /** 非流式整段响应 → [AiReply]。错误体抛 [HttpException]；不是 JSON 就把前 800 字当正文。 */
    internal fun parseReply(body: String): AiReply {
        val o = runCatching { JSONObject(body) }.getOrNull() ?: return AiReply(content = body.take(800))
        o.optJSONObject("error")?.let { err ->
            throw HttpException(err.str("message").ifBlank { err.toString() })
        }
        val choice = o.optJSONArray("choices")?.optJSONObject(0)
        val message = choice?.optJSONObject("message")
        val calls = ArrayList<AiToolCall>()
        val arr = message?.optJSONArray("tool_calls")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val tc = arr.optJSONObject(i) ?: continue
                AiToolCall.fromJson(tc)?.let { c ->
                    calls.add(c.copy(id = c.id.ifEmpty { "call_$i" }, arguments = c.arguments.ifEmpty { "{}" }))
                }
            }
        }
        val content = message?.str("content")?.ifBlank { null }
            ?: o.str("reply").takeIf { it.isNotBlank() }
            ?: o.str("content").takeIf { it.isNotBlank() }
            ?: if (calls.isEmpty()) body.take(800) else ""
        return AiReply(content, calls, choice?.str("finish_reason").orEmpty())
    }

    internal fun parseChatReply(body: String): String = parseReply(body).content

    internal fun formatError(code: Int, body: String): String {
        val msg = runCatching {
            JSONObject(body).optJSONObject("error")?.str("message")
        }.getOrNull()?.takeIf { it.isNotBlank() }
        return if (msg != null) "接口 HTTP $code $msg" else "接口 HTTP $code ${body.take(240)}"
    }

    // ------------------------------------------------ 设置页 / 单测用的薄封装
    // 上面那套是给 agent 用的：流式、工具调用、取消。设置页只想「发一句、看通不通」，
    // 下面这几个就是给它和单测用的一次性口径，共用同一份配置解析。

    /** 出厂公益口，与 [AiConfig.DEFAULT_BASE] 同一个值，给不方便拿 AiConfig 的地方用。 */
    const val PUBLIC_BASE = AiConfig.DEFAULT_BASE

    /** 出厂模型，同 [AiConfig.DEFAULT_MODEL]。 */
    const val MODEL = AiConfig.DEFAULT_MODEL

    /** 一次对话最多带这么多条历史给模型，跟 [AiHistory.MAX_MESSAGES] 保持同一档。 */
    const val MAX_MESSAGES = AiHistory.MAX_MESSAGES

    private const val SYSTEM_PROMPT =
        "你是 PyMCL 启动器内置的 Minecraft 助手。回答用中文，简短直接。" +
            "涉及崩溃日志时先说结论，再说怎么改。"

    /** 非流式的请求体。agent 那条路走 [chat]，这条只给「测试连接」和单测用。 */
    fun chatBody(
        prompt: String,
        history: List<AiMessage> = emptyList(),
        model: String = MODEL,
    ): String {
        val messages = org.json.JSONArray()
        messages.put(JSONObject().put("role", "system").put("content", SYSTEM_PROMPT))
        history.takeLast(MAX_MESSAGES).forEach {
            messages.put(JSONObject().put("role", it.role).put("content", it.content))
        }
        messages.put(JSONObject().put("role", "user").put("content", prompt))
        return JSONObject()
            .put("model", model.ifBlank { MODEL })
            .put("messages", messages)
            .put("stream", false)
            .toString()
    }

    // parseChatReply / formatError 上面已经有了（internal），不再重复一份：
    // 单测跟它们在同一个模块里，internal 看得见。

    /** 设置页的「测试连接」：只发一句，回一行人话。 */
    fun testConnection(cfg: AiConfig): String {
        val started = System.currentTimeMillis()
        val reply = complete(cfg, listOf(AiMessage(role = "user", content = "回一个字：好")))
        val ms = System.currentTimeMillis() - started
        val text = reply.content.trim()
        if (text.isEmpty()) throw AiConfigError("接口通了，但模型没有返回内容")
        return "连通，${ms}ms · ${describe(cfg)} · 模型回了「${text.take(20)}」"
    }
}
