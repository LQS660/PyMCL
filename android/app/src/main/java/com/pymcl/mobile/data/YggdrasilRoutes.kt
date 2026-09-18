package com.pymcl.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.security.interfaces.RSAPrivateCrtKey
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.RSAPublicKeySpec
import java.util.Base64

/**
 * 本地 Yggdrasil 服务的**路由与响应拼装**，对齐桌面 mclauncher/skinserver.py。
 *
 * 离线账号没有正版会话，客户端拿不到任何材质，只能按 UUID 落到内置默认皮肤；
 * 1.19.3（22w45a）起内置默认皮肤从两种扩到九种，选哪一种改由九路映射决定，
 * 用户在设置里选了 Steve，进 1.20.1 可能变成 Zuri。所以走 HMCL / PCL2 那条路：
 * 起一个只听回环的 Yggdrasil 服务，用 authlib-injector 把客户端对 Mojang 会话
 * 服务的请求劫持过来，直接给真贴图。
 *
 * **这个文件里一个 socket 都没有**：[handle] 收一个 [HttpRequest] 给一个
 * [HttpReply]，监听那一层在 [SkinServer]。这么分是为了把五组端点的行为单测掉。
 */

const val YGG_LOOPBACK = "127.0.0.1"

data class SkinProfile(
    /** 无连字符的小写 uuid。 */
    val uuid: String,
    val name: String,
    val png: ByteArray,
    val model: String = SkinFile.CLASSIC,
) {
    val digest: String = MessageDigest.getInstance("SHA-256").digest(png)
        .joinToString("") { "%02x".format(it) }

    // png 是 ByteArray，默认的 equals 会按引用比；这里按内容比才合直觉。
    override fun equals(other: Any?): Boolean =
        this === other || (other is SkinProfile && uuid == other.uuid && name == other.name &&
            model == other.model && png.contentEquals(other.png))

    override fun hashCode(): Int = 31 * (31 * uuid.hashCode() + name.hashCode()) + model.hashCode()
}

data class HttpRequest(
    val method: String,
    val path: String,
    val query: Map<String, String> = emptyMap(),
    val body: String = "",
)

data class HttpReply(
    val status: Int,
    val body: ByteArray = ByteArray(0),
    val contentType: String = "application/json",
) {
    fun text(): String = body.decodeToString()

    override fun equals(other: Any?): Boolean =
        this === other || (other is HttpReply && status == other.status &&
            contentType == other.contentType && body.contentEquals(other.body))

    override fun hashCode(): Int = 31 * (31 * status + contentType.hashCode()) + body.contentHashCode()
}

/** 在内存里记着当前有哪些离线角色。服务每局游戏要被客户端打好几次，查得快就行。 */
class SkinRegistry {
    private val uuidIndex = LinkedHashMap<String, SkinProfile>()
    private val nameIndex = LinkedHashMap<String, SkinProfile>()
    private val textureIndex = LinkedHashMap<String, ByteArray>()

    @Synchronized
    fun register(profile: SkinProfile): SkinProfile {
        uuidIndex[profile.uuid.replace("-", "").lowercase()] = profile
        nameIndex[profile.name.lowercase()] = profile
        textureIndex[profile.digest] = profile.png
        return profile
    }

    @Synchronized
    fun byUuid(uuid: String): SkinProfile? = uuidIndex[uuid.replace("-", "").lowercase()]

    @Synchronized
    fun byName(name: String): SkinProfile? = nameIndex[name.lowercase()]

    @Synchronized
    fun texture(digest: String): ByteArray? = textureIndex[digest]

    @Synchronized
    fun first(): SkinProfile? = uuidIndex.values.firstOrNull()

    @Synchronized
    fun clear() {
        uuidIndex.clear(); nameIndex.clear(); textureIndex.clear()
    }
}

/**
 * 签名密钥。**生成一次就落盘复用**——RSA 生成在手机上要好几百毫秒，
 * 每次启动都来一遍会白白拖慢开游戏。
 *
 * 桌面那边用 4096 位；这里降到 2048：authlib-injector 不挑位数，而手机 CPU 生成
 * 4096 位要好几秒。要改回去把 [bits] 传大就行。
 */
class YggdrasilKeys(private val keyFile: File, private val bits: Int = 2048) {
    @Volatile
    private var cached: KeyPair? = null

    @Synchronized
    fun keyPair(): KeyPair {
        cached?.let { return it }
        loadFromDisk()?.let { cached = it; return it }
        val generated = KeyPairGenerator.getInstance("RSA").apply { initialize(bits) }.generateKeyPair()
        runCatching {
            keyFile.parentFile?.mkdirs()
            keyFile.writeBytes(generated.private.encoded)
        }
        cached = generated
        return generated
    }

    /** 密钥损坏就当没有，重新生成——没必要让用户自己去删文件。 */
    private fun loadFromDisk(): KeyPair? = runCatching {
        if (!keyFile.isFile || keyFile.length() <= 0L) return null
        val factory = KeyFactory.getInstance("RSA")
        val priv = factory.generatePrivate(PKCS8EncodedKeySpec(keyFile.readBytes()))
        val crt = priv as? RSAPrivateCrtKey ?: return null
        val pub = factory.generatePublic(RSAPublicKeySpec(crt.modulus, crt.publicExponent))
        KeyPair(pub, priv)
    }.getOrNull()

    fun publicKeyPem(): String {
        val b64 = Base64.getEncoder().encodeToString(keyPair().public.encoded)
        val body = b64.chunked(64).joinToString("\n")
        return "-----BEGIN PUBLIC KEY-----\n$body\n-----END PUBLIC KEY-----\n"
    }

    /** Yggdrasil 规范：对 base64 之后的属性值做 SHA1withRSA，再 base64。 */
    fun sign(payload: String): String {
        val sig = Signature.getInstance("SHA1withRSA")
        sig.initSign(keyPair().private)
        sig.update(payload.toByteArray(Charsets.US_ASCII))
        return Base64.getEncoder().encodeToString(sig.sign())
    }
}

class YggdrasilRoutes(
    private val registry: SkinRegistry,
    private val keys: YggdrasilKeys,
    /** 服务实际监听的端口；材质 URL 要用它拼。 */
    private val port: () -> Int,
    private val now: () -> Long = { System.currentTimeMillis() },
) {
    fun handle(req: HttpRequest): HttpReply {
        val path = req.path.trimEnd('/').ifEmpty { "/" }
        return when (req.method.uppercase()) {
            "GET", "HEAD" -> get(path, req)
            "POST" -> post(path, req)
            else -> HttpReply(405)
        }
    }

    // ---------------------------------------------------------- 五组端点

    private fun get(path: String, req: HttpRequest): HttpReply = when {
        // 1. 元数据：authlib-injector 启动时先打这一下
        path == "/" -> json(200, meta())

        // 2. 材质本体
        path.startsWith("/textures/") -> {
            val png = registry.texture(path.substringAfterLast('/'))
            if (png == null) HttpReply(404) else HttpReply(200, png, "image/png")
        }

        // 3. 按 uuid 查角色
        path.startsWith("/sessionserver/session/minecraft/profile/") -> {
            val prof = registry.byUuid(path.substringAfterLast('/'))
            if (prof == null) HttpReply(204)
            else json(200, profileJson(prof, signed = !req.query["unsigned"].equals("true", true)))
        }

        // 4. 加入服务器校验
        path == "/sessionserver/session/minecraft/hasJoined" -> {
            val prof = registry.byName(req.query["username"].orEmpty())
            if (prof == null) HttpReply(204) else json(200, profileJson(prof))
        }

        else -> HttpReply(404)
    }

    private fun post(path: String, req: HttpRequest): HttpReply = when {
        path == "/api/profiles/minecraft" -> {
            val names = runCatching { JSONArray(req.body) }.getOrNull()
            val out = JSONArray()
            if (names != null) {
                for (i in 0 until names.length()) {
                    registry.byName(names.optString(i))?.let {
                        out.put(JSONObject().put("id", it.uuid).put("name", it.name))
                    }
                }
            }
            json(200, out)
        }

        // 本地服务不做校验，直接放行
        path == "/sessionserver/session/minecraft/join" -> HttpReply(204)

        // 5. authserver：authenticate / refresh / validate / invalidate / signout
        path.startsWith("/authserver/") -> authserver(path.substringAfterLast('/'), req)

        else -> HttpReply(404)
    }

    private fun authserver(action: String, req: HttpRequest): HttpReply {
        if (action in setOf("validate", "invalidate", "signout")) return HttpReply(204)
        val body = runCatching { JSONObject(req.body) }.getOrNull() ?: JSONObject()
        val prof = registry.byName(body.optString("username")) ?: registry.first()
            ?: return json(
                403,
                JSONObject()
                    .put("error", "ForbiddenOperationException")
                    .put("errorMessage", "没有可用的离线角色"),
            )
        val selected = JSONObject().put("id", prof.uuid).put("name", prof.name)
        return json(
            200,
            JSONObject()
                .put("accessToken", body.optString("accessToken").ifBlank { "pymcl-offline" })
                .put("clientToken", body.optString("clientToken").ifBlank { "pymcl" })
                .put("selectedProfile", selected)
                .put("availableProfiles", JSONArray().put(selected)),
        )
    }

    // ---------------------------------------------------------- 响应拼装

    fun meta(): JSONObject = JSONObject()
        .put(
            "meta",
            JSONObject()
                .put("serverName", "PyMCL 本地皮肤")
                .put("implementationName", "pymcl-skinserver")
                .put("implementationVersion", "1"),
        )
        // authlib-injector 会拿材质 URL 的主机名比对这张白名单
        .put("skinDomains", JSONArray().put(YGG_LOOPBACK).put("localhost"))
        .put("signaturePublickey", keys.publicKeyPem())

    fun texturePayload(prof: SkinProfile): String {
        val skin = JSONObject().put("url", "http://$YGG_LOOPBACK:${port()}/textures/${prof.digest}")
        // 经典模型不写 metadata，客户端按宽臂处理
        if (prof.model == SkinFile.SLIM) skin.put("metadata", JSONObject().put("model", SkinFile.SLIM))
        val doc = JSONObject()
            .put("timestamp", now())
            .put("profileId", prof.uuid)
            .put("profileName", prof.name)
            .put("textures", JSONObject().put("SKIN", skin))
        return Base64.getEncoder().encodeToString(doc.toString().toByteArray(Charsets.UTF_8))
    }

    fun profileJson(prof: SkinProfile, signed: Boolean = true): JSONObject {
        val value = texturePayload(prof)
        val prop = JSONObject().put("name", "textures").put("value", value)
        if (signed) prop.put("signature", keys.sign(value))
        return JSONObject()
            .put("id", prof.uuid)
            .put("name", prof.name)
            .put("properties", JSONArray().put(prop))
    }

    private fun json(status: Int, doc: Any): HttpReply =
        HttpReply(status, doc.toString().toByteArray(Charsets.UTF_8), "application/json")
}
