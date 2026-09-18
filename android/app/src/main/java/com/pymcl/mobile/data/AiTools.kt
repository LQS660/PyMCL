package com.pymcl.mobile.data

import com.pymcl.mobile.model.CatalogHit
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * 工具执行需要的宿主能力。Android 实现见 AiToolsAndroid.kt；单测给一个假的。
 * 全部是只读查询——写入类操作本轮不接真实执行（见 [WriteGate]）。
 */
interface AiToolHost {
    /** 默认实例名，供工具参数省略 instance 时兜底。 */
    val defaultInstance: String

    /** 实例名 → 已装版本列表。 */
    fun listInstances(): Map<String, List<String>>

    fun installedVersions(instance: String): List<String>

    /** 实例 mods/ 目录下的文件名（含 .disabled）。实例不存在回空。 */
    fun listMods(instance: String): List<String>

    /** 联网搜模组；网络错误直接抛，由工具层包成「工具失败」。 */
    fun searchMods(query: String): List<CatalogHit>

    /** 当前设置的可读视图：用户名、内存、默认实例、AI 接入模式等。**不得包含密钥**。 */
    fun currentSettings(): JSONObject

    fun listAccounts(): List<String>

    // ---- 诊断 / 冲突分析要的几样，给默认实现，老的宿主实现不用跟着改 ----

    /** 实例 logs/latest.log 全文；没有回空串。 */
    fun readLatestLog(instance: String): String = ""

    /** 实例 crash-reports/ 下最新一份报告全文；没有回空串。 */
    fun readLatestCrashReport(instance: String): String = ""

    /** 实例 mods/ 下每个 jar 的元数据（读不出的退回文件名推断）。 */
    fun modMetas(instance: String): List<ModMeta> = emptyList()

    /** 实例的加载器 / MC 版本；认不出留空串。 */
    fun instanceTarget(instance: String): Pair<String, String> = "" to ""
}

/**
 * 写入类工具的口子。本轮所有写入工具都只有 schema：模型可以「想」调用它们，
 * 真正执行要先过这道门；默认实现 [WriteGate.DENY] 一律不放行并把原因写回给模型。
 * 以后接确认 UI 时，换一个实现即可，工具声明不用改。
 */
fun interface WriteGate {
    /** 放行就返回执行结果文本；返回 null = 本次不执行（未开放 / 用户拒绝）。 */
    fun run(tool: AiTool, args: JSONObject): String?

    companion object {
        val DENY = WriteGate { _, _ -> null }
    }
}

/**
 * 一个工具声明。[run] 为 null 表示本轮只有 schema、没有实现（全部写入类都是这样）。
 */
data class AiTool(
    val name: String,
    val description: String,
    val parameters: JSONObject,
    val write: Boolean,
    val run: ((AiToolHost, JSONObject) -> String)?,
) {
    /** OpenAI function-calling 形状。 */
    fun schema(): JSONObject = JSONObject()
        .put("type", "function")
        .put(
            "function",
            JSONObject()
                .put("name", name)
                .put("description", description)
                .put("parameters", parameters),
        )
}

object AiTools {
    /** 对齐桌面 ai/defaults.py。 */
    const val MAX_TOOL_ROUNDS = 10
    const val MAX_TOOL_RESULT = 8000

    /** 与桌面 WRITE_TOOLS 同名同集合，方便以后对齐确认策略。 */
    val WRITE_TOOLS = setOf(
        "install_game", "install_mod", "install_modpack", "install_shader", "install_resourcepack",
        "install_datapack", "install_world", "download_java", "launch_game", "create_instance",
        "delete_instance", "delete_mod", "disable_mod", "enable_mod", "write_mod_config",
    )

    /** 「完全访问」下仍必须确认的破坏性操作，同桌面 DANGEROUS_TOOLS。 */
    val DANGEROUS_TOOLS = setOf("delete_instance", "delete_mod", "write_mod_config")

    private fun params(props: Map<String, Pair<String, String>>, required: List<String> = emptyList()): JSONObject {
        val properties = JSONObject()
        props.forEach { (key, spec) ->
            val (type, desc) = spec
            val p = JSONObject().put("type", type)
            if (desc.isNotEmpty()) p.put("description", desc)
            properties.put(key, p)
        }
        val o = JSONObject().put("type", "object").put("properties", properties)
        if (required.isNotEmpty()) o.put("required", JSONArray(required))
        return o
    }

    private fun readOnly(
        name: String,
        desc: String,
        props: Map<String, Pair<String, String>> = emptyMap(),
        required: List<String> = emptyList(),
        run: (AiToolHost, JSONObject) -> String,
    ) = AiTool(name, desc, params(props, required), write = false, run = run)

    private fun writeOnly(
        name: String,
        desc: String,
        props: Map<String, Pair<String, String>> = emptyMap(),
        required: List<String> = emptyList(),
    ) = AiTool(name, desc, params(props, required), write = true, run = null)

    private const val INSTANCE_DESC = "实例名，空则用默认实例"

    /** 全部工具声明：只读的带实现，写入的只有 schema。 */
    fun registry(): List<AiTool> = listOf(
        readOnly("get_launcher_state", "查看当前状态：默认实例、全部实例及各自已装版本、账号、模组数量") { host, _ ->
            val inst = JSONObject()
            host.listInstances().forEach { (name, versions) ->
                inst.put(
                    name,
                    JSONObject()
                        .put("versions", JSONArray(versions))
                        .put("mod_count", host.listMods(name).size),
                )
            }
            JSONObject()
                .put("default_instance", host.defaultInstance)
                .put("instances", inst)
                .put("accounts", JSONArray(host.listAccounts()))
                .toString()
        },
        readOnly("list_instances", "列出全部实例") { host, _ ->
            JSONArray(host.listInstances().keys.toList()).toString()
        },
        readOnly(
            "list_installed_versions", "列出某实例已安装的游戏版本",
            mapOf("instance" to ("string" to INSTANCE_DESC)),
        ) { host, args ->
            val name = instanceOf(host, args)
            JSONObject().put("instance", name).put("versions", JSONArray(host.installedVersions(name))).toString()
        },
        readOnly(
            "list_mods", "列出实例已装模组文件（含 .disabled 的禁用项）",
            mapOf("instance" to ("string" to INSTANCE_DESC)),
        ) { host, args ->
            val name = instanceOf(host, args)
            JSONObject().put("instance", name).put("mods", JSONArray(host.listMods(name))).toString()
        },
        readOnly(
            "search_mods", "搜索模组（Modrinth，支持中文名）。同一轮只调用一次，搜完把结果列给用户选。",
            mapOf("query" to ("string" to "关键词"), "limit" to ("integer" to "最多返回几条，默认 8，上限 20")),
            listOf("query"),
        ) { host, args ->
            val query = args.optString("query").trim()
            if (query.isEmpty()) return@readOnly "参数缺失: query"
            val limit = args.optInt("limit", 8).coerceIn(1, 20)
            val arr = JSONArray()
            host.searchMods(query).take(limit).forEach { hit ->
                arr.put(
                    JSONObject()
                        .put("name", hit.name)
                        .put("slug", hit.slug)
                        .put("source", hit.source)
                        .put("downloads", hit.downloads)
                        .put("author", hit.author)
                        .put("description", hit.description.take(160)),
                )
            }
            JSONObject().put("query", query).put("count", arr.length()).put("hits", arr).toString()
        },
        readOnly("get_settings", "查看启动器当前设置（用户名、内存、默认实例、AI 接入模式）。不含任何密钥。") { host, _ ->
            host.currentSettings().toString()
        },
        readOnly("list_accounts", "列出已登录账号") { host, _ ->
            JSONArray(host.listAccounts()).toString()
        },
        readOnly(
            "diagnose_launch",
            "分析启动失败 / 崩溃原因：读实例的 latest.log 与最新崩溃报告，按已知特征给出原因与建议。认不出会明说「未识别」。",
            mapOf("instance" to ("string" to INSTANCE_DESC)),
        ) { host, args ->
            val name = instanceOf(host, args)
            val latest = host.readLatestLog(name)
            val crash = host.readLatestCrashReport(name)
            if (latest.isBlank() && crash.isBlank()) {
                return@readOnly JSONObject()
                    .put("instance", name)
                    .put("recognized", false)
                    .put("summary", "这个实例还没有 latest.log 和崩溃报告，先启动一次游戏再来诊断")
                    .toString()
            }
            CrashDiagnoser.diagnose(latest, crash).toJson()
                .put("instance", name)
                .put("has_latest", latest.isNotBlank())
                .put("has_crash", crash.isNotBlank())
                .toString()
        },
        readOnly(
            "scan_mod_conflicts",
            "扫描实例已装模组的冲突：同一模组装了多份、加载器不匹配、MC 版本不匹配、缺依赖、声明互斥。推不出的地方会写在 notes 里。",
            mapOf("instance" to ("string" to INSTANCE_DESC)),
        ) { host, args ->
            val name = instanceOf(host, args)
            val (loader, mc) = host.instanceTarget(name)
            ModConflictAnalyzer.analyze(host.modMetas(name), loader, mc).toJson()
                .put("instance", name)
                .toString()
        },

        // ---- 以下写入类：只有声明，没有执行。真正执行要过 WriteGate。 ----
        writeOnly(
            "install_game", "下载并安装 Minecraft 版本。纯原版 loader 填「无」。",
            mapOf(
                "version" to ("string" to "如 1.20.1"),
                "loader" to ("string" to "无 / Fabric / Forge / Quilt / NeoForge"),
                "loader_version" to ("string" to ""),
                "instance" to ("string" to INSTANCE_DESC),
            ),
            listOf("version"),
        ),
        writeOnly(
            "install_mod", "安装模组。优先传搜索结果里的 slug。",
            mapOf(
                "name" to ("string" to "显示名或 slug"),
                "slug" to ("string" to ""),
                "instance" to ("string" to INSTANCE_DESC),
            ),
            listOf("name"),
        ),
        writeOnly(
            "install_modpack", "安装整合包。建议先 create_instance。",
            mapOf("name" to ("string" to ""), "slug" to ("string" to ""), "instance" to ("string" to INSTANCE_DESC)),
            listOf("name"),
        ),
        writeOnly("create_instance", "新建隔离实例", mapOf("name" to ("string" to "")), listOf("name")),
        writeOnly("delete_instance", "删除整个实例（危险，不可恢复）", mapOf("name" to ("string" to "")), listOf("name")),
        writeOnly(
            "delete_mod", "删除模组文件",
            mapOf("filename" to ("string" to ""), "instance" to ("string" to INSTANCE_DESC)),
            listOf("filename"),
        ),
        writeOnly(
            "disable_mod", "禁用模组（改名为 .disabled，可恢复）",
            mapOf("filename" to ("string" to ""), "instance" to ("string" to INSTANCE_DESC)),
            listOf("filename"),
        ),
        writeOnly(
            "enable_mod", "重新启用已禁用模组",
            mapOf("filename" to ("string" to ""), "instance" to ("string" to INSTANCE_DESC)),
            listOf("filename"),
        ),
        writeOnly(
            "launch_game", "启动游戏。不填则用默认实例和已装版本。",
            mapOf(
                "instance" to ("string" to INSTANCE_DESC),
                "version" to ("string" to ""),
                "username" to ("string" to ""),
                "memory_mb" to ("integer" to ""),
            ),
        ),
        writeOnly(
            "write_mod_config", "写入模组配置文件（执行前会先备份）",
            mapOf(
                "path" to ("string" to "相对 config/ 的路径"),
                "content" to ("string" to "完整文件内容"),
                "instance" to ("string" to INSTANCE_DESC),
            ),
            listOf("path", "content"),
        ),
    )

    fun schemas(tools: List<AiTool> = registry()): JSONArray {
        val arr = JSONArray()
        tools.forEach { arr.put(it.schema()) }
        return arr
    }

    fun find(tools: List<AiTool>, name: String): AiTool? = tools.firstOrNull { it.name == name }

    private fun instanceOf(host: AiToolHost, args: JSONObject): String =
        args.optString("instance").trim().ifEmpty { host.defaultInstance }

    /**
     * 模型给的 arguments → JSONObject。合法 JSON 对象直接用；空 = 空对象；
     * 不合法时照桌面的做法捞一遍 `"key": "value"` 对，一个都捞不到才算失败（返回 null）。
     */
    fun parseArgs(raw: String?): JSONObject? {
        val s = raw?.trim().orEmpty()
        if (s.isEmpty()) return JSONObject()
        try {
            return JSONObject(s)
        } catch (_: JSONException) {
        }
        val salvaged = JSONObject()
        Regex("\"(\\w+)\"\\s*:\\s*\"([^\"]*)\"").findAll(s).forEach { m ->
            salvaged.put(m.groupValues[1], m.groupValues[2])
        }
        return if (salvaged.length() > 0) salvaged else null
    }

    fun clip(text: String): String =
        if (text.length <= MAX_TOOL_RESULT) text else text.take(MAX_TOOL_RESULT) + "\n…(已截断)"

    /**
     * 执行一条模型要求的调用，**永远返回一段文本**，不抛异常：
     * 工具名缺失 / 不存在 / 参数不是合法 JSON / 工具自己抛错，都写成给模型看的说明，
     * 让它下一轮自己纠正，而不是让循环崩掉。
     */
    fun execute(host: AiToolHost, tools: List<AiTool>, call: AiToolCall, gate: WriteGate = WriteGate.DENY): String {
        val name = call.name.trim()
        if (name.isEmpty()) {
            return "工具名缺失：这次调用没有 function.name。可用工具：${tools.joinToString(", ") { it.name }}"
        }
        val tool = find(tools, name)
            ?: return "没有这个工具：$name。可用工具：${tools.joinToString(", ") { it.name }}"
        val args = parseArgs(call.arguments)
            ?: return "参数不是合法 JSON：${call.arguments.take(200)}。请按 $name 的参数说明重新给一个 JSON 对象。"
        val missing = requiredMissing(tool, args)
        if (missing.isNotEmpty()) {
            return "参数缺失: ${missing.joinToString(", ")}。$name 需要这些字段。"
        }
        if (tool.write) {
            val out = try {
                gate.run(tool, args)
            } catch (e: Exception) {
                return "工具失败: ${e.message ?: e.toString()}"
            }
            return out?.let(::clip)
                ?: ("写入类工具「$name」在手机端尚未开放执行（需要先接用户确认）。已收到参数：$args。" +
                    "请告诉用户手机端目前只能查看和搜索，这一步得去桌面端或等后续版本。")
        }
        val run = tool.run ?: return "工具「$name」没有实现。"
        return try {
            clip(run(host, args))
        } catch (e: Exception) {
            "工具失败: ${e.message ?: e.toString()}"
        }
    }

    private fun requiredMissing(tool: AiTool, args: JSONObject): List<String> {
        val required = tool.parameters.optJSONArray("required") ?: return emptyList()
        val out = ArrayList<String>()
        for (i in 0 until required.length()) {
            val key = required.optString(i)
            if (key.isEmpty()) continue
            if (!args.has(key) || args.isNull(key) || args.optString(key).isBlank()) out.add(key)
        }
        return out
    }

    /** 给模型的第一条 system：它是谁、能做什么、当前状态。对齐桌面 agent._system_messages 的意图，篇幅更短。 */
    fun systemPrompt(host: AiToolHost): String {
        val state = try {
            val lines = host.listInstances().entries.take(12).map { (name, versions) ->
                "- $name：${if (versions.isEmpty()) "未装版本" else versions.take(6).joinToString(" / ")}"
            }
            if (lines.isEmpty()) "（还没有实例）" else lines.joinToString("\n")
        } catch (_: Exception) {
            "（读取失败）"
        }
        return """
            你是 PyMCL 手机端的 Minecraft 启动器助手。用简洁的中文回答。
            需要查实例、版本、模组、设置时调用工具，不要凭空猜。
            安装 / 删除 / 启动 / 改配置这类写入操作在手机端目前不会真的执行——工具会告诉你原因，你要如实转告用户。
            当前默认实例：${host.defaultInstance}
            当前实例与已装版本：
        """.trimIndent() + "\n" + state
    }
}
