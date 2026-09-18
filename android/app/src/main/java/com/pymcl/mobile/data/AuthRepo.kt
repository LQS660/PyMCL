package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * 微软设备码。
 *
 * 定义放在 `data` 而不是 `model`：它只有账号这条链路在用，
 * 放这儿账号域就不必跨 owner 去动别人的数据模型文件。
 */
data class DeviceCode(
    val deviceCode: String,
    val userCode: String,
    val uri: String,
    val interval: Int,
    val expiresIn: Int,
)

/** 账号类型，跟桌面 accounts.json 里的 `type` 字段同名。 */
object AccountKind {
    const val MICROSOFT = "microsoft"
    const val AUTHLIB = "authlib"
    const val NIDE8 = "nide8"
    const val OFFLINE = "offline"

    fun label(type: String): String = when (type) {
        MICROSOFT -> "微软"
        AUTHLIB -> "皮肤站"
        NIDE8 -> "统一通行证"
        OFFLINE -> "离线"
        else -> type
    }
}

data class AuthAccount(
    val name: String,
    val type: String,
    val uuid: String = "",
    val accessToken: String = "",
    val refreshToken: String = "",
    val api: String = "",
    val serverId: String = "",
    val skinFile: String = "",
    val skinModel: String = SkinRepo.CLASSIC,
    val active: Boolean = false,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("name", name)
        .put("type", type)
        .put("uuid", uuid)
        .put("access_token", accessToken)
        .put("refresh_token", refreshToken)
        .put("api", api)
        .put("server_id", serverId)
        .put("skin_file", skinFile)
        .put("skin_model", skinModel)
        .put("active", active)
}

data class AuthPreset(val name: String, val api: String)

/**
 * 不碰网络、不碰文件的那部分，单测直接跑。
 */
object AuthLogic {
    /** 桌面账号页下拉里那几个皮肤站，`api` 为空的那条表示「手填」。 */
    val presets: List<AuthPreset> = listOf(
        AuthPreset("自定义", ""),
        AuthPreset("LittleSkin", "https://littleskin.cn/api/yggdrasil"),
        AuthPreset("MCSkin 皮肤站", "https://mcskin.cn/api/yggdrasil"),
        AuthPreset("BlessingSkin 自建", ""),
    )

    fun presetApi(name: String): String = presets.firstOrNull { it.name == name }?.api.orEmpty()

    /**
     * 统一通行证要的是 32 位服务器 ID。用户往往直接贴一条带 ID 的链接进来，
     * 所以这里从任意文本里把第一段 32 位十六进制抠出来。
     */
    fun parseNide8Id(raw: String): String? {
        val m = Regex("[0-9a-fA-F]{32}").find(raw.trim()) ?: return null
        return m.value.lowercase()
    }

    /** 离线 UUID 的算法是 Mojang 定死的，不能随手换一个随机数。 */
    fun offlineUuid(username: String): String =
        UUID.nameUUIDFromBytes("OfflinePlayer:$username".toByteArray(Charsets.UTF_8)).toString()

    fun validOfflineName(name: String): Boolean =
        name.isNotBlank() && name.length <= 16 && Regex("^[A-Za-z0-9_]+$").matches(name)

    /** authlib-injector 的地址要收敛到不带尾斜杠，后面各段路径才拼得对。 */
    fun normalizeApi(api: String): String = api.trim().trimEnd('/')

    fun authenticateUrl(api: String): String = normalizeApi(api) + "/authserver/authenticate"

    fun refreshUrl(api: String): String = normalizeApi(api) + "/authserver/refresh"

    fun nide8Api(serverId: String): String = "https://auth.mc-user.com:233/$serverId"

    fun authenticateBody(username: String, password: String, clientToken: String): String =
        JSONObject()
            .put("username", username)
            .put("password", password)
            .put("clientToken", clientToken)
            .put("requestUser", false)
            .put("agent", JSONObject().put("name", "Minecraft").put("version", 1))
            .toString()

    /** Yggdrasil 的返回里，选中角色在 selectedProfile，没有就退回 availableProfiles 第一个。 */
    fun parseYggdrasil(body: String): AuthAccount? {
        val json = runCatching { JSONObject(body) }.getOrNull() ?: return null
        val token = json.optString("accessToken")
        if (token.isBlank()) return null
        val profile = json.optJSONObject("selectedProfile")
            ?: json.optJSONArray("availableProfiles")?.optJSONObject(0)
            ?: return null
        val name = profile.optString("name")
        if (name.isBlank()) return null
        return AuthAccount(
            name = name,
            type = AccountKind.AUTHLIB,
            uuid = dashUuid(profile.optString("id")),
            accessToken = token,
        )
    }

    /** Yggdrasil 给的是不带连字符的 32 位，游戏要的是带连字符的标准格式。 */
    fun dashUuid(raw: String): String {
        val hex = raw.replace("-", "")
        if (hex.length != 32) return raw
        return buildString {
            append(hex, 0, 8); append('-')
            append(hex, 8, 12); append('-')
            append(hex, 12, 16); append('-')
            append(hex, 16, 20); append('-')
            append(hex, 20, 32)
        }
    }

    /** Yggdrasil 的错误体是 `{errorMessage: …}`，不是 HTTP 文本。 */
    fun errorMessage(code: Int, body: String): String {
        val json = runCatching { JSONObject(body) }.getOrNull()
        val detail = json?.optString("errorMessage").orEmpty().ifBlank {
            json?.optString("error").orEmpty()
        }
        return if (detail.isBlank()) "登录失败 HTTP $code" else "登录失败 HTTP $code：$detail"
    }

    fun xblBody(msToken: String): String = JSONObject()
        .put(
            "Properties",
            JSONObject()
                .put("AuthMethod", "RPS")
                .put("SiteName", "user.auth.xboxlive.com")
                .put("RpsTicket", msToken),
        )
        .put("RelyingParty", "http://auth.xboxlive.com")
        .put("TokenType", "JWT")
        .toString()

    fun xstsBody(xblToken: String): String = JSONObject()
        .put(
            "Properties",
            JSONObject()
                .put("SandboxId", "RETAIL")
                .put("UserTokens", JSONArray().put(xblToken)),
        )
        .put("RelyingParty", "rp://api.minecraftservices.com/")
        .put("TokenType", "JWT")
        .toString()

    /** XSTS 的几个 XErr 各有各的说法，直接抛「登录失败」用户看不懂。 */
    fun xstsHint(xErr: String): String = when (xErr) {
        "2148916233" -> "这个微软账号还没有 Xbox 档案，先去 xbox.com 建一个"
        "2148916235" -> "所在区域不提供 Xbox Live 服务"
        "2148916236", "2148916237" -> "需要先通过成人验证"
        "2148916238" -> "未成年账号，需要家庭组的成年人先把它加进去"
        else -> "Xbox 授权被拒绝（XErr $xErr）"
    }

    /** 同名同类型算同一个账号：重复登录是刷新令牌，不是再加一行。 */
    fun upsert(rows: List<AuthAccount>, account: AuthAccount): List<AuthAccount> {
        val replaced = rows.map {
            if (it.name == account.name && it.type == account.type) {
                account.copy(active = true)
            } else {
                it.copy(active = false)
            }
        }
        return if (replaced.any { it.name == account.name && it.type == account.type }) {
            replaced
        } else {
            replaced + account.copy(active = true)
        }
    }

    /** 删掉当前账号后总得有人顶上，否则启动页的账号栏会空着。 */
    fun removeAndReelect(rows: List<AuthAccount>, name: String): List<AuthAccount> {
        val left = rows.filterNot { it.name == name }
        if (left.isEmpty()) return left
        if (left.any { it.active }) return left
        return left.mapIndexed { i, acc -> acc.copy(active = i == 0) }
    }

    fun activate(rows: List<AuthAccount>, name: String): List<AuthAccount> =
        rows.map { it.copy(active = it.name == name) }
}

/**
 * 账号仓储。对齐 `app/pages/account_page.py`：微软 / 离线 / authlib-injector / 统一通行证，
 * 多账号列表、切换、删除，外加离线账号的自定义皮肤。
 */
object AuthRepo {
    private const val CLIENT_TOKEN_KEY = "client_token"

    @Volatile
    private var cache: List<AuthAccount>? = null

    fun accounts(): List<AuthAccount> {
        cache?.let { return it }
        synchronized(this) {
            cache?.let { return it }
            val rows = parseAccounts(Paths.readJson(Paths.accountsFile))
            cache = rows
            return rows
        }
    }

    fun parseAccounts(json: JSONObject): List<AuthAccount> {
        val arr = json.optJSONArray("accounts") ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val name = o.optString("name")
            if (name.isBlank()) return@mapNotNull null
            AuthAccount(
                name = name,
                type = o.optString("type", AccountKind.OFFLINE),
                uuid = o.optString("uuid"),
                accessToken = o.optString("access_token"),
                refreshToken = o.optString("refresh_token"),
                api = o.optString("api"),
                serverId = o.optString("server_id"),
                skinFile = o.optString("skin_file"),
                skinModel = o.optString("skin_model", SkinRepo.CLASSIC),
                active = o.optBoolean("active"),
            )
        }
    }

    fun encode(rows: List<AuthAccount>): JSONObject {
        val arr = JSONArray()
        rows.forEach { arr.put(it.toJson()) }
        return JSONObject().put("accounts", arr)
    }

    fun save(rows: List<AuthAccount>) {
        synchronized(this) {
            cache = rows
            Paths.writeJson(Paths.accountsFile, encode(rows))
        }
    }

    fun active(): AuthAccount? = accounts().firstOrNull { it.active } ?: accounts().firstOrNull()

    fun activate(name: String) = save(AuthLogic.activate(accounts(), name))

    fun remove(name: String) = save(AuthLogic.removeAndReelect(accounts(), name))

    fun addOffline(name: String): AuthAccount {
        val account = AuthAccount(
            name = name,
            type = AccountKind.OFFLINE,
            uuid = AuthLogic.offlineUuid(name),
        )
        save(AuthLogic.upsert(accounts(), account))
        return account
    }

    fun setSkin(name: String, skinFile: String, model: String) {
        save(
            accounts().map {
                if (it.name == name) it.copy(skinFile = skinFile, skinModel = model) else it
            },
        )
    }

    fun clearSkin(name: String) = setSkin(name, "", SkinRepo.CLASSIC)

    private fun clientToken(): String {
        val existing = Settings.str(CLIENT_TOKEN_KEY)
        if (existing.isNotBlank()) return existing
        val fresh = UUID.randomUUID().toString().replace("-", "")
        Settings.set(CLIENT_TOKEN_KEY, fresh)
        Settings.flushIfDirty()
        return fresh
    }

    // ---------------------------------------------------------------- 皮肤站
    fun loginAuthlib(api: String, username: String, password: String): AuthAccount {
        val (code, body) = Http.postJson(
            AuthLogic.authenticateUrl(api),
            AuthLogic.authenticateBody(username, password, clientToken()),
        )
        val parsed = AuthLogic.parseYggdrasil(body)
            ?: throw HttpException(AuthLogic.errorMessage(code, body))
        val account = parsed.copy(api = AuthLogic.normalizeApi(api))
        save(AuthLogic.upsert(accounts(), account))
        return account
    }

    // ------------------------------------------------------------ 统一通行证
    fun loginNide8(rawId: String, username: String, password: String): AuthAccount {
        val serverId = AuthLogic.parseNide8Id(rawId)
            ?: throw HttpException("服务器 ID 要是 32 位十六进制，或一条含它的链接")
        val api = AuthLogic.nide8Api(serverId)
        val (code, body) = Http.postJson(
            AuthLogic.authenticateUrl(api),
            AuthLogic.authenticateBody(username, password, clientToken()),
        )
        val parsed = AuthLogic.parseYggdrasil(body)
            ?: throw HttpException(AuthLogic.errorMessage(code, body))
        val account = parsed.copy(type = AccountKind.NIDE8, api = api, serverId = serverId)
        save(AuthLogic.upsert(accounts(), account))
        return account
    }

    // ---------------------------------------------------------------- 微软
    fun startDeviceCode(): DeviceCode {
        val (code, body) = Http.postForm(
            Paths.MS_DEVICE_CODE,
            mapOf(
                "client_id" to Settings.str(SettingsKeys.MS_CLIENT_ID, Paths.MS_CLIENT),
                "scope" to Paths.MS_SCOPE,
                "response_type" to "device_code",
            ),
        )
        val json = runCatching { JSONObject(body) }.getOrNull()
            ?: throw HttpException("设备码接口返回看不懂 HTTP $code")
        val userCode = json.optString("user_code")
        if (userCode.isBlank()) throw HttpException("设备码申请失败 HTTP $code ${body.take(160)}")
        return DeviceCode(
            deviceCode = json.optString("device_code"),
            userCode = userCode,
            uri = json.optString("verification_uri").ifBlank { "https://www.microsoft.com/link" },
            interval = json.optInt("interval", 5),
            expiresIn = json.optInt("expires_in", 900),
        )
    }

    /** 还没授权时返回 null（`authorization_pending`），由调用方继续轮询。 */
    fun pollOnce(deviceCode: String): JSONObject? {
        val (code, body) = Http.postForm(
            Paths.MS_TOKEN,
            mapOf(
                "client_id" to Settings.str(SettingsKeys.MS_CLIENT_ID, Paths.MS_CLIENT),
                "device_code" to deviceCode,
                "grant_type" to "urn:ietf:params:oauth:grant-type:device_code",
            ),
        )
        val json = runCatching { JSONObject(body) }.getOrNull() ?: return null
        if (code == 200 && json.optString("access_token").isNotBlank()) return json
        val error = json.optString("error")
        if (error == "authorization_pending" || error == "slow_down") return null
        if (error.isNotBlank()) throw HttpException("微软登录失败：$error")
        return null
    }

    /** 微软令牌 → Xbox → XSTS → MC 令牌 → 档案，四段换票缺一不可。 */
    fun exchangeMinecraft(msAccessToken: String): AuthAccount {
        val (xblCode, xblBody) = Http.postJson(
            Paths.XBL_AUTH,
            AuthLogic.xblBody(msAccessToken),
            mapOf("Accept" to "application/json"),
        )
        val xbl = runCatching { JSONObject(xblBody) }.getOrNull()
            ?: throw HttpException("Xbox 授权返回看不懂 HTTP $xblCode")
        val xblToken = xbl.optString("Token")
        val uhs = xbl.optJSONObject("DisplayClaims")?.optJSONArray("xui")
            ?.optJSONObject(0)?.optString("uhs").orEmpty()
        if (xblToken.isBlank() || uhs.isBlank()) throw HttpException("Xbox 授权失败 HTTP $xblCode")

        val (xstsCode, xstsBody) = Http.postJson(
            Paths.XSTS_AUTH,
            AuthLogic.xstsBody(xblToken),
            mapOf("Accept" to "application/json"),
        )
        val xsts = runCatching { JSONObject(xstsBody) }.getOrNull()
            ?: throw HttpException("XSTS 返回看不懂 HTTP $xstsCode")
        val xErr = xsts.optLong("XErr", 0L)
        if (xErr != 0L) throw HttpException(AuthLogic.xstsHint(xErr.toString()))
        val xstsToken = xsts.optString("Token")
        if (xstsToken.isBlank()) throw HttpException("XSTS 授权失败 HTTP $xstsCode")

        val (mcCode, mcBody) = Http.postJson(
            Paths.MC_LOGIN,
            JSONObject().put("identityToken", "XBL3.0 x=$uhs;$xstsToken").toString(),
        )
        val mc = runCatching { JSONObject(mcBody) }.getOrNull()
            ?: throw HttpException("MC 换票返回看不懂 HTTP $mcCode")
        val mcToken = mc.optString("access_token")
        if (mcToken.isBlank()) throw HttpException("MC 换票失败 HTTP $mcCode")

        val profile = runCatching {
            JSONObject(Http.getText(Paths.MC_PROFILE, mapOf("Authorization" to "Bearer $mcToken")))
        }.getOrNull() ?: throw HttpException("这个微软账号没有 Minecraft 档案（没买过或还没设名字）")

        return AuthAccount(
            name = profile.optString("name").ifBlank { "Microsoft" },
            type = AccountKind.MICROSOFT,
            uuid = AuthLogic.dashUuid(profile.optString("id")),
            accessToken = mcToken,
        )
    }

    fun saveMicrosoft(account: AuthAccount, refreshToken: String) {
        save(AuthLogic.upsert(accounts(), account.copy(refreshToken = refreshToken)))
    }

    fun reload() {
        synchronized(this) { cache = null }
    }

    /** 单测用：绕开 filesDir，直接喂一份账号表进来。 */
    fun loadForTest(rows: List<AuthAccount>) {
        synchronized(this) { cache = rows }
    }
}
