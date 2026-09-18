package com.pymcl.mobile

import com.pymcl.mobile.data.AccountKind
import com.pymcl.mobile.data.AuthAccount
import com.pymcl.mobile.data.AuthLogic
import com.pymcl.mobile.data.AuthRepo
import com.pymcl.mobile.data.JavaInfo
import com.pymcl.mobile.data.JavaRuntime
import com.pymcl.mobile.data.SkinRepo
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AccountJavaTest {
    // ------------------------------------------------------------------ 账号
    @Test
    fun nide8IdIsLiftedOutOfWhateverTheUserPastes() {
        val id = "0123456789abcdef0123456789abcdef"
        assertEquals(id, AuthLogic.parseNide8Id(id))
        assertEquals(id, AuthLogic.parseNide8Id("  $id  "))
        assertEquals(id, AuthLogic.parseNide8Id("https://login.mc-user.com:233/$id/"))
        assertEquals(id, AuthLogic.parseNide8Id("0123456789ABCDEF0123456789ABCDEF"))
        assertNull(AuthLogic.parseNide8Id("12345"))
        assertNull(AuthLogic.parseNide8Id("没有 ID"))
    }

    @Test
    fun offlineUuidMatchesMojangsRule() {
        // 这个算法是 Mojang 定死的：换一个随机数会导致同名玩家在服务器上不是同一个人
        assertEquals(36, AuthLogic.offlineUuid("Player").length)
        assertEquals(AuthLogic.offlineUuid("Player"), AuthLogic.offlineUuid("Player"))
        assertEquals(AuthLogic.offlineUuid("Steve"), JavaRuntime.offlineUuid("Steve"))
        assertTrue(AuthLogic.offlineUuid("Alex") != AuthLogic.offlineUuid("Steve"))
    }

    @Test
    fun offlineNamesFollowGameRules() {
        assertTrue(AuthLogic.validOfflineName("Player_1"))
        assertFalse(AuthLogic.validOfflineName(""))
        assertFalse(AuthLogic.validOfflineName("有中文"))
        assertFalse(AuthLogic.validOfflineName("a".repeat(17)))
        assertFalse(AuthLogic.validOfflineName("has space"))
    }

    @Test
    fun yggdrasilResponseBecomesAnAccount() {
        val body = """
            {"accessToken":"tok","clientToken":"ct",
             "selectedProfile":{"id":"0123456789abcdef0123456789abcdef","name":"Tester"}}
        """.trimIndent()
        val account = AuthLogic.parseYggdrasil(body)
        assertNotNull(account)
        assertEquals("Tester", account!!.name)
        assertEquals(AccountKind.AUTHLIB, account.type)
        assertEquals("tok", account.accessToken)
        // 游戏要带连字符的标准 UUID，Yggdrasil 给的是 32 位裸串
        assertEquals("01234567-89ab-cdef-0123-456789abcdef", account.uuid)
    }

    @Test
    fun yggdrasilFallsBackToFirstAvailableProfile() {
        val body = """
            {"accessToken":"tok",
             "availableProfiles":[{"id":"abc","name":"OnlyOne"}]}
        """.trimIndent()
        assertEquals("OnlyOne", AuthLogic.parseYggdrasil(body)?.name)
        // 没有 accessToken 就不是一次成功的登录
        assertNull(AuthLogic.parseYggdrasil("""{"error":"ForbiddenOperationException"}"""))
    }

    @Test
    fun yggdrasilErrorBodyBeatsBareHttpCode() {
        val message = AuthLogic.errorMessage(
            403,
            """{"error":"ForbiddenOperationException","errorMessage":"密码错误"}""",
        )
        assertTrue(message.contains("403"))
        assertTrue(message.contains("密码错误"))
        assertTrue(AuthLogic.errorMessage(500, "not json").contains("500"))
    }

    @Test
    fun apiUrlsAreNormalizedBeforeJoining() {
        assertEquals(
            "https://littleskin.cn/api/yggdrasil/authserver/authenticate",
            AuthLogic.authenticateUrl("https://littleskin.cn/api/yggdrasil/"),
        )
        assertEquals(
            "https://auth.mc-user.com:233/abc/authserver/refresh",
            AuthLogic.refreshUrl(AuthLogic.nide8Api("abc")),
        )
    }

    @Test
    fun authenticateBodyCarriesTheMinecraftAgent() {
        val json = JSONObject(AuthLogic.authenticateBody("u", "p", "ct"))
        assertEquals("u", json.optString("username"))
        assertEquals("ct", json.optString("clientToken"))
        assertEquals("Minecraft", json.optJSONObject("agent")?.optString("name"))
        assertEquals(1, json.optJSONObject("agent")?.optInt("version"))
    }

    @Test
    fun xstsErrorsGetARealExplanation() {
        assertTrue(AuthLogic.xstsHint("2148916233").contains("Xbox"))
        assertTrue(AuthLogic.xstsHint("2148916238").contains("未成年"))
        assertTrue(AuthLogic.xstsHint("999").contains("999"))
    }

    @Test
    fun loggingInTwiceRefreshesInsteadOfAddingARow() {
        val rows = listOf(
            AuthAccount("Tester", AccountKind.AUTHLIB, accessToken = "old", active = true),
            AuthAccount("Other", AccountKind.OFFLINE),
        )
        val updated = AuthLogic.upsert(
            rows,
            AuthAccount("Tester", AccountKind.AUTHLIB, accessToken = "new"),
        )
        assertEquals(2, updated.size)
        assertEquals("new", updated.first { it.name == "Tester" }.accessToken)
        assertEquals(1, updated.count { it.active })
        assertTrue(updated.first { it.name == "Tester" }.active)
    }

    @Test
    fun removingTheActiveAccountElectsANewOne() {
        val rows = listOf(
            AuthAccount("A", AccountKind.OFFLINE, active = true),
            AuthAccount("B", AccountKind.OFFLINE),
        )
        val left = AuthLogic.removeAndReelect(rows, "A")
        assertEquals(1, left.size)
        assertTrue("删掉当前账号后必须有人顶上", left[0].active)
        assertTrue(AuthLogic.removeAndReelect(left, "B").isEmpty())
    }

    @Test
    fun accountsRoundTripThroughJson() {
        val rows = listOf(
            AuthAccount("Tester", AccountKind.AUTHLIB, uuid = "u", api = "https://x", active = true),
            AuthAccount("Off", AccountKind.OFFLINE, skinFile = "off.png", skinModel = SkinRepo.SLIM),
        )
        val back = AuthRepo.parseAccounts(AuthRepo.encode(rows))
        assertEquals(rows.size, back.size)
        assertEquals("https://x", back[0].api)
        assertTrue(back[0].active)
        assertEquals(SkinRepo.SLIM, back[1].skinModel)
        assertEquals("off.png", back[1].skinFile)
    }

    // ------------------------------------------------------------------ 皮肤
    @Test
    fun pngHeaderIsReadWithoutDecodingTheImage() {
        assertEquals(64 to 64, SkinRepo.pngSize(fakePng(64, 64)))
        assertEquals(64 to 32, SkinRepo.pngSize(fakePng(64, 32)))
        assertNull(SkinRepo.pngSize(ByteArray(10)))
        assertNull(SkinRepo.pngSize("not a png at all!!!!!!!!".toByteArray()))
    }

    @Test
    fun onlyMojangCanvasSizesAreAccepted() {
        assertEquals(64 to 64, SkinRepo.validate(fakePng(64, 64)))
        val bad = runCatching { SkinRepo.validate(fakePng(128, 128)) }.exceptionOrNull()
        assertTrue(bad is SkinRepo.SkinError)
        assertTrue(bad!!.message!!.contains("128x128"))
    }

    @Test
    fun legacyCanvasMirrorsTheRightLimbs() {
        // 64x32 只有右半边，左臂左腿要靠右边那份镜像出来
        val legacy = SkinRepo.frontViewRegions(slim = false, legacy = true)
        assertTrue(legacy["armLeft"]!!.contentEquals(legacy["armRight"]!!))
        assertTrue(legacy["legLeft"]!!.contentEquals(legacy["legRight"]!!))

        val modern = SkinRepo.frontViewRegions(slim = false, legacy = false)
        assertFalse(modern["armLeft"]!!.contentEquals(modern["armRight"]!!))

        // Alex 的手臂只有 3 px
        assertEquals(3, SkinRepo.frontViewRegions(slim = true, legacy = false)["armRight"]!![2])
        assertEquals(4, modern["armRight"]!![2])
        assertTrue(SkinRepo.isLegacyCanvas(64 to 32))
        assertFalse(SkinRepo.isLegacyCanvas(64 to 64))
    }

    // ------------------------------------------------------------------ Java
    @Test
    fun vendorListMatchesDesktop() {
        assertEquals(listOf("adoptium", "zulu", "microsoft"), JavaRuntime.vendors.map { it.key })
        assertTrue(JavaRuntime.vendorLabel("adoptium").contains("Temurin"))
        assertEquals("nope", JavaRuntime.vendorLabel("nope"))
        assertEquals(listOf(8, 11, 17, 21), JavaRuntime.downloadableMajors.map { it.first })
    }

    @Test
    fun abiMapsToTheRightDownloadArch() {
        assertEquals("aarch64", JavaRuntime.adoptiumArch("arm64-v8a"))
        assertEquals("arm", JavaRuntime.adoptiumArch("armeabi-v7a"))
        assertEquals("x64", JavaRuntime.adoptiumArch("x86_64"))
        // 不认识的一律按主流手机算，别给用户下一个跑不起来的包
        assertEquals("aarch64", JavaRuntime.adoptiumArch(""))
    }

    @Test
    fun onlyGaMajorsAreRequestedFromVendors() {
        // Adoptium 没有 16 这种中间版本，要抬到 17
        assertEquals(17, JavaRuntime.adoptiumMajor(16))
        assertEquals(8, JavaRuntime.adoptiumMajor(8))
        assertEquals(21, JavaRuntime.adoptiumMajor(25))
        assertTrue(JavaRuntime.downloadUrl("adoptium", 16, "arm64-v8a").contains("/17/ga/linux/aarch64/"))
        assertTrue(JavaRuntime.downloadUrl("microsoft", 21, "arm64-v8a").contains("microsoft-jdk-21"))
        assertTrue(JavaRuntime.downloadUrl("zulu", 17, "x86_64").contains("java_version=17"))
    }

    @Test
    fun majorIsReadOutOfWhateverTheFolderIsCalled() {
        assertEquals(17, JavaRuntime.majorFromDirName("jre17"))
        assertEquals(21, JavaRuntime.majorFromDirName("java-21"))
        assertEquals(8, JavaRuntime.majorFromDirName("8"))
        assertEquals(0, JavaRuntime.majorFromDirName("runtime"))
    }

    @Test
    fun pickPrefersExactThenNextHigher() {
        val installed = listOf(
            JavaInfo(8, "/j8", "jre8"),
            JavaInfo(17, "/j17", "jre17"),
            JavaInfo(21, "/j21", "jre21"),
        )
        assertEquals("/j17", JavaRuntime.pick(installed, 17)?.path)
        // 没有 16 就往上取最小的那个更高版本，而不是随便挑
        assertEquals("/j17", JavaRuntime.pick(installed, 16)?.path)
        assertEquals("/j21", JavaRuntime.pick(installed, 25)?.path)
        // 明确指定过的优先
        assertEquals("/j8", JavaRuntime.pick(installed, 21, prefer = "/j8")?.path)
        assertNull(JavaRuntime.pick(emptyList(), 17))
    }

    @Test
    fun jreFolderNameFollowsMajor() {
        assertEquals("jre8", JavaRuntime.jreDirName(8))
        assertEquals("jre17", JavaRuntime.jreDirName(16))
        assertEquals("jre21", JavaRuntime.jreDirName(21))
        assertEquals("jre25", JavaRuntime.jreDirName(25))
    }

    private fun fakePng(width: Int, height: Int): ByteArray {
        val out = ByteArray(24)
        val signature = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        signature.copyInto(out)
        "IHDR".toByteArray().copyInto(out, 12)
        writeInt(out, 16, width)
        writeInt(out, 20, height)
        return out
    }

    private fun writeInt(buf: ByteArray, at: Int, value: Int) {
        buf[at] = (value ushr 24).toByte()
        buf[at + 1] = (value ushr 16).toByte()
        buf[at + 2] = (value ushr 8).toByte()
        buf[at + 3] = value.toByte()
    }
}
