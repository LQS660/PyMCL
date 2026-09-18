package com.pymcl.mobile.data

import org.json.JSONArray

/** 代理循环里发给 UI 的事件。 */
sealed class AgentEvent {
    /** 模型正文增量。 */
    data class Delta(val text: String) : AgentEvent()

    /** 第 [round] 轮（从 1 起）开始向模型要回复；[afterTools] 表示前面已经有工具结果了。 */
    data class Round(val round: Int, val afterTools: Boolean) : AgentEvent()

    data class ToolStart(val call: AiToolCall, val write: Boolean) : AgentEvent()

    data class ToolDone(val call: AiToolCall, val result: String) : AgentEvent()

    /** 循环结束（正常 / 到顶 / 取消）时给一句说明。 */
    data class Notice(val text: String) : AgentEvent()
}

/** 一次 [AiAgent.run] 的结果。 */
data class AgentResult(
    /** 本轮新增的消息，按顺序：user → (assistant+tool_calls → tool…)* → assistant。调用方原样追加进会话。 */
    val messages: List<AiMessage>,
    val finalText: String,
    val roundsUsed: Int,
    val hitRoundLimit: Boolean,
    val cancelled: Boolean,
)

/**
 * 请模型回一轮。[history] 已经含 system 与本轮所有消息；[tools] 是要声明的工具；
 * 正文增量走 [onDelta]。默认实现是 [AiRepo.complete]，单测里换成脚本。
 */
typealias ModelCall = (history: List<AiMessage>, tools: JSONArray, handle: AiCall, onDelta: (String) -> Unit) -> AiReply

/**
 * 多轮工具调用循环，对齐桌面 ai/agent.py 的骨架：
 * 模型要工具 → 执行 → 结果以 tool 消息回填 → 再问模型，直到模型不再要工具，或到 [maxRounds]。
 * 任何一步都可以用 [AiCall.cancel] 掐掉。
 */
class AiAgent(
    private val host: AiToolHost,
    private val model: ModelCall,
    private val tools: List<AiTool> = AiTools.registry(),
    private val writeGate: WriteGate = WriteGate.DENY,
    private val maxRounds: Int = AiTools.MAX_TOOL_ROUNDS,
    /** 连续这么多轮模型给的全是坏调用（不存在的工具 / 非法参数）就提前收手，不用等到顶。 */
    private val maxBadRounds: Int = 3,
    private val systemPrompt: (AiToolHost) -> String = AiTools::systemPrompt,
) {
    companion object {
        /** 生产用：模型调用走 [AiRepo.complete]。 */
        fun forConfig(cfg: AiConfig, host: AiToolHost, writeGate: WriteGate = WriteGate.DENY): AiAgent =
            AiAgent(
                host = host,
                model = { history, tools, handle, onDelta ->
                    AiRepo.complete(cfg, history, tools, stream = true, handle = handle, onDelta = onDelta)
                },
                writeGate = writeGate,
            )

        const val LIMIT_NOTICE = "工具调用轮数到顶，先停在这里。你再说一下接下来要哪一步。"
        const val CANCEL_NOTICE = "已停止。"
        const val BAD_ROUNDS_NOTICE = "模型连续给出无法执行的调用，先停下。你换个说法再试。"
    }

    /**
     * 跑一轮用户请求。[history] 是会话里已有的消息（不含 system、不含这句新的用户话）。
     * 返回的 [AgentResult.messages] 只含本轮新增。
     */
    fun run(
        history: List<AiMessage>,
        userText: String,
        handle: AiCall = AiCall(),
        onEvent: (AgentEvent) -> Unit = {},
    ): AgentResult {
        val fresh = ArrayList<AiMessage>()
        val userMsg = AiMessage("user", userText)
        fresh.add(userMsg)
        val system = AiMessage("system", systemPrompt(host))
        val schemas = AiTools.schemas(tools)
        val transcript = StringBuilder()

        var rounds = 0
        var badRounds = 0
        var lastContent = ""
        try {
            while (rounds < maxRounds) {
                if (handle.cancelled) throw AiCancelled()
                rounds++
                val afterTools = fresh.any { it.role == "tool" }
                onEvent(AgentEvent.Round(rounds, afterTools))
                transcript.setLength(0)

                val context = AiHistory.trim(listOf(system) + history + fresh)
                val reply = model(context, schemas, handle) { piece ->
                    transcript.append(piece)
                    onEvent(AgentEvent.Delta(piece))
                }
                if (handle.cancelled) throw AiCancelled()
                lastContent = reply.content

                if (reply.toolCalls.isEmpty()) {
                    val text = reply.content.ifBlank { "我这边没有更多要做的了。" }
                    fresh.add(AiMessage("assistant", text))
                    return AgentResult(fresh, text, rounds, hitRoundLimit = false, cancelled = false)
                }

                fresh.add(AiMessage("assistant", reply.content, toolCalls = reply.toolCalls))
                var allBad = true
                for (call in reply.toolCalls) {
                    if (handle.cancelled) throw AiCancelled()
                    val tool = AiTools.find(tools, call.name)
                    onEvent(AgentEvent.ToolStart(call, tool?.write == true))
                    val result = AiTools.execute(host, tools, call, writeGate)
                    if (tool != null && AiTools.parseArgs(call.arguments) != null) allBad = false
                    onEvent(AgentEvent.ToolDone(call, result))
                    fresh.add(AiMessage("tool", result, toolCallId = call.id, name = call.name))
                }
                badRounds = if (allBad) badRounds + 1 else 0
                if (badRounds >= maxBadRounds) {
                    fresh.add(AiMessage("assistant", BAD_ROUNDS_NOTICE))
                    onEvent(AgentEvent.Notice(BAD_ROUNDS_NOTICE))
                    return AgentResult(fresh, BAD_ROUNDS_NOTICE, rounds, hitRoundLimit = false, cancelled = false)
                }
            }
        } catch (e: AiCancelled) {
            val partial = transcript.toString().ifBlank { lastContent }
            val text = if (partial.isBlank()) CANCEL_NOTICE else "$partial\n（已停止）"
            // 半截的 assistant/tool 配对交给 AiHistory.repairToolPairs 在下次发请求前修，这里只把已有的留下。
            fresh.add(AiMessage("assistant", text))
            onEvent(AgentEvent.Notice(CANCEL_NOTICE))
            return AgentResult(fresh, text, rounds, hitRoundLimit = false, cancelled = true)
        }

        val text = if (lastContent.isBlank()) LIMIT_NOTICE else "$lastContent\n\n$LIMIT_NOTICE"
        fresh.add(AiMessage("assistant", text))
        onEvent(AgentEvent.Notice(LIMIT_NOTICE))
        return AgentResult(fresh, text, rounds, hitRoundLimit = true, cancelled = false)
    }
}
