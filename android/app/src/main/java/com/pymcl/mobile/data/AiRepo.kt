package com.pymcl.mobile.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

object AiRepo {
    /** 公益口只认全小写 host；HTTPS 无有效证书，必须 HTTP。 */
    const val PUBLIC_BASE = "http://new.s.3q.hair/v1"
    private const val PUBLIC_TOKEN = "sk-wC70Ya4JUUiSjpVLkNFFdO1VbTvlnLKb1oWiHJGrVW175Hbu"
    const val MODEL = "deepseek-v4-flash"

    fun send(gatewayOverride: String, text: String): String {
        val custom = gatewayOverride.trim().trimEnd('/')
        if (custom.isNotBlank()) {
            val viaGateway = runCatching { postGateway(custom, text) }.getOrNull()
            if (!viaGateway.isNullOrBlank()) return viaGateway
        }
        return postPublic(text)
    }

    private fun postPublic(text: String): String {
        val req = Request.Builder()
            .url("$PUBLIC_BASE/chat/completions")
            .header("User-Agent", Paths.UA)
            .header("Authorization", "Bearer $PUBLIC_TOKEN")
            .header("Content-Type", "application/json")
            .header("X-PyMCL-Client", "PyMCL/${Paths.APP_VERSION}")
            .post(chatBody(text).toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()
        Http.client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw HttpException(formatError(resp.code, body))
            }
            return parseChatReply(body)
        }
    }

    private fun postGateway(root: String, text: String): String {
        val payload = chatBody(text)
        val urls = listOf("$root/pymcl/chat", "$root/v1/chat/completions", "$root/chat/completions")
        var last = "网关无可用路径"
        for (url in urls) {
            try {
                val builder = Request.Builder()
                    .url(url)
                    .header("User-Agent", Paths.UA)
                    .header("Content-Type", "application/json")
                    .header("X-PyMCL-Client", "PyMCL/${Paths.APP_VERSION}")
                    .post(payload.toRequestBody("application/json; charset=utf-8".toMediaType()))
                if (url.contains("/chat/completions")) {
                    builder.header("Authorization", "Bearer $PUBLIC_TOKEN")
                }
                Http.client.newCall(builder.build()).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) {
                        last = "HTTP ${resp.code} $url ${body.take(160)}"
                        return@use
                    }
                    return parseChatReply(body)
                }
            } catch (e: Exception) {
                last = e.message ?: e.toString()
            }
        }
        throw HttpException(last)
    }

    internal fun chatBody(text: String): String {
        return JSONObject()
            .put("model", MODEL)
            .put("stream", false)
            .put(
                "messages",
                JSONArray().put(JSONObject().put("role", "user").put("content", text)),
            )
            .toString()
    }

    internal fun parseChatReply(body: String): String {
        val o = JSONObject(body)
        val content = o.optJSONArray("choices")
            ?.optJSONObject(0)
            ?.optJSONObject("message")
            ?.optString("content")
        val reply = content?.ifBlank { null }
            ?: o.optString("reply").takeIf { it.isNotBlank() }
            ?: o.optString("content").takeIf { it.isNotBlank() }
        return reply ?: body.take(800)
    }

    internal fun formatError(code: Int, body: String): String {
        val msg = runCatching {
            JSONObject(body).optJSONObject("error")?.optString("message")
        }.getOrNull()?.takeIf { it.isNotBlank() }
        return if (msg != null) "公益接口 HTTP $code $msg" else "公益接口 HTTP $code ${body.take(240)}"
    }
}
