package com.pymcl.mobile

import com.pymcl.mobile.data.AiConfig
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.CrashReporter
import com.pymcl.mobile.data.FeedbackError
import com.pymcl.mobile.data.FeedbackRepo
import com.pymcl.mobile.data.RuntimeInstaller
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FeedbackCrashTest {
    // ------------------------------------------------------------------ 反馈
    @Test
    fun categoriesMatchDesktopExactly() {
        assertEquals(
            listOf("bug", "crash", "download", "multiplayer", "ai", "ui", "suggest", "other"),
            FeedbackRepo.CATEGORIES.map { it.first },
        )
        assertEquals("崩溃闪退", FeedbackRepo.categoryLabel("crash"))
        assertEquals("其他", FeedbackRepo.categoryLabel("不存在的分类"))
    }

    @Test
    fun payloadNormalizesTheSameWayDesktopDoes() {
        val payload = FeedbackRepo.buildPayload(
            deviceId = "dev-1",
            category = "  CRASH ",
            title = "",
            body = "第一行就是标题\n后面是正文",
            contact = "me@example.com",
            sysinfo = JSONObject().put("os", "Android 14"),
        )
        assertEquals("crash", payload.optString("category"))
        // 标题空了就拿正文第一行顶上
        assertEquals("第一行就是标题", payload.optString("title"))
        assertEquals("android", payload.optString("platform"))
        assertEquals("dev-1", payload.optString("device_id"))
        assertEquals("Android 14", payload.optJSONObject("sysinfo")?.optString("os"))
    }

    @Test
    fun unknownCategoryFallsBackToOther() {
        val payload = FeedbackRepo.buildPayload("d", "随便填的", "标题", "正文", "", null)
        assertEquals("other", payload.optString("category"))
    }

    @Test
    fun emptyReportIsRejectedBeforeItHitsTheNetwork() {
        val err = runCatching {
            FeedbackRepo.buildPayload("d", "bug", "   ", "  ", "", null)
        }.exceptionOrNull()
        assertTrue(err is FeedbackError)
    }

    @Test
    fun longTextIsTruncatedSoThePostDoesNotBlowUp() {
        val payload = FeedbackRepo.buildPayload(
            "d", "bug", "t".repeat(400), "b".repeat(30000), "c".repeat(400), null,
        )
        assertEquals(120, payload.optString("title").length)
        assertEquals(16000, payload.optString("body").length)
        assertEquals(120, payload.optString("contact").length)
    }

    // ------------------------------------------------------------------ 崩溃
    @Test
    fun tokensNeverLeaveTheDeviceInsideACrashLog() {
        val log = """
            [main] Launching with --accessToken eyJhbGciOiJIUzI1NiJ9.abcdefg --username Player
            "access_token": "ya29.A0ARrdaM9xxxxxxxxxxxxxxxxx"
            Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345
            "uuid": "01234567-89ab-cdef-0123-456789abcdef"
        """.trimIndent()
        val clean = CrashReporter.filterSecrets(log)
        assertFalse(clean.contains("eyJhbGciOiJIUzI1NiJ9"))
        assertFalse(clean.contains("ya29.A0ARrdaM9"))
        assertFalse(clean.contains("abcdefghijklmnopqrstuvwxyz012345"))
        assertFalse(clean.contains("01234567-89ab-cdef-0123-456789abcdef"))
        // 有用的上下文要留着，不然脱敏完日志就没法看了
        assertTrue(clean.contains("--username Player"))
        assertTrue(clean.contains("<hidden>"))
    }

    @Test
    fun knownCrashesGetANamedReason() {
        assertEquals(
            "内存不够了，把分配内存调大一档再试",
            CrashReporter.classify("java.lang.OutOfMemoryError: Java heap space"),
        )
        assertTrue(CrashReporter.classify("Pixel format not accelerated")!!.contains("LWJGL"))
        assertTrue(CrashReporter.classify("Mixin apply failed: sodium.mixins")!!.contains("Mixin"))
        assertNull(CrashReporter.classify("一切正常"))
    }

    @Test
    fun stoppingTheGameYourselfIsNotACrash() {
        assertFalse(CrashReporter.looksLikeCrash(0, cancelled = false))
        assertFalse(CrashReporter.looksLikeCrash(143, cancelled = true))
        assertTrue(CrashReporter.looksLikeCrash(1, cancelled = false))
    }

    @Test
    fun exitCodesGetPlainLanguage() {
        assertTrue(CrashReporter.exitHint(137).contains("内存"))
        assertTrue(CrashReporter.exitHint(139).contains("原生层"))
        assertEquals("正常退出", CrashReporter.exitHint(0))
        assertTrue(CrashReporter.exitHint(77).contains("77"))
    }

    @Test
    fun excerptKeepsHeadAndTailAndDropsTheMiddle() {
        val log = (1..5000).joinToString("\n") { "line $it" }
        val excerpt = CrashReporter.excerpt(log, head = 5, tail = 10)
        assertTrue(excerpt.contains("line 1"))
        assertTrue(excerpt.contains("line 5000"))
        assertTrue(excerpt.contains("中间省略"))
        assertFalse(excerpt.contains("line 2500"))
        // 短日志原样带走，不要凭空插一行「省略」
        assertFalse(CrashReporter.excerpt("a\nb\nc").contains("中间省略"))
    }

    @Test
    fun analyzeCombinesReasonAndExitCode() {
        val report = CrashReporter.analyze(1, "java.lang.OutOfMemoryError", cancelled = false)
        assertTrue(report.headline.contains("内存"))
        assertEquals(1, report.exitCode)
        assertTrue(report.summary.isNotBlank())
        assertTrue(report.excerpt.isNotBlank())
    }

    // ------------------------------------------------------------------ AI
    @Test
    fun gatewayIsUsedWheneverThereIsNoKey() {
        // 两样都没有 = 根本没配置。这一档必须当场说清楚，
        // 不能拿一个空地址去发请求然后报个看不懂的网络错
        val blank = AiConfig()
        assertFalse(blank.hasKey)
        assertEquals(AiConfig.DEFAULT_MODEL, blank.effectiveModel)
        val unconfigured = runCatching { AiRepo.resolve(blank) }.exceptionOrNull()
        assertTrue(unconfigured is com.pymcl.mobile.data.AiConfigError)

        // 填了网关、没填密钥 = 走网关：令牌由网关保管，不进手机
        val gateway = AiConfig(gatewayUrl = "https://gw.example.com")
        assertFalse(gateway.hasKey)
        val viaGateway = AiRepo.resolve(gateway)
        assertTrue(viaGateway.headers["Authorization"].isNullOrBlank())

        val direct = AiConfig(baseUrl = "https://api.example.com/v1/", apiKey = "sk-x", model = "gpt-x")
        assertTrue(direct.hasKey)
        val viaKey = AiRepo.resolve(direct)
        assertEquals("Bearer sk-x", viaKey.headers["Authorization"])
        assertEquals("gpt-x", viaKey.model)
        assertTrue(viaKey.urls.first().startsWith("https://api.example.com/v1/"))
        assertTrue(AiRepo.describe(direct).contains("api.example.com"))
    }

    @Test
    fun gatewayUrlIsReadFromEitherKeyName() {
        // 桌面写的是 ai_gateway_url，安卓早先写成 ai_url，两端 config.json 要能互拷
        val desktop = AiConfig.fromConfig(JSONObject().put("ai_gateway_url", "https://gw.example.com"))
        assertEquals("https://gw.example.com", desktop.effectiveGateway)
        val legacy = AiConfig.fromConfig(JSONObject().put("ai_url", "https://old.example.com"))
        assertEquals("https://old.example.com", legacy.effectiveGateway)
        // 两个都在时新名优先
        val both = AiConfig.fromConfig(
            JSONObject().put("ai_gateway_url", "https://new.example.com").put("ai_url", "https://old.example.com"),
        )
        assertEquals("https://new.example.com", both.effectiveGateway)
    }

    @Test
    fun chatBodyCarriesSystemPromptAndCappedHistory() {
        val history = (1..40).map {
            com.pymcl.mobile.data.AiMessage(if (it % 2 == 0) "assistant" else "user", "m$it")
        }
        val json = JSONObject(AiRepo.chatBody("最后一句", history))
        val messages = json.optJSONArray("messages")!!
        // system + 最多 MAX_MESSAGES 条历史 + 这一句
        assertEquals(AiRepo.MAX_MESSAGES + 2, messages.length())
        assertEquals("system", messages.optJSONObject(0)?.optString("role"))
        assertEquals("最后一句", messages.optJSONObject(messages.length() - 1)?.optString("content"))
        assertEquals(AiRepo.MODEL, json.optString("model"))
    }

    @Test
    fun repliesAndErrorsAreBothReadable() {
        assertEquals(
            "好",
            AiRepo.parseChatReply("""{"choices":[{"message":{"role":"assistant","content":"好"}}]}"""),
        )
        // 不是 JSON 时原样返回正文：有些网关直接吐纯文本，
        // 丢成空串等于把模型说的话吞了，还不如把原文摆出来让用户自己看
        assertEquals("这不是 JSON", AiRepo.parseChatReply("这不是 JSON"))
        val err = AiRepo.formatError(429, """{"error":{"message":"1分钟内最多请求5次"}}""")
        assertTrue(err.contains("429"))
        assertTrue(err.contains("1分钟内最多请求5次"))
    }

    // -------------------------------------------------------- 运行时解包工具
    @Test
    fun tarHeaderFieldsAreDecoded() {
        val header = ByteArray(512)
        "bin/java".toByteArray().copyInto(header)
        // tar 的 size 是八进制 ASCII：0644 大小 1024 = "2000"
        "00000002000 ".toByteArray().copyInto(header, 124)
        "0000755 ".toByteArray().copyInto(header, 100)
        assertEquals("bin/java", RuntimeInstaller.cString(header, 0, 100))
        assertEquals(1024L, RuntimeInstaller.octal(header, 124, 12))
        assertEquals(493L, RuntimeInstaller.octal(header, 100, 8))
    }
}
