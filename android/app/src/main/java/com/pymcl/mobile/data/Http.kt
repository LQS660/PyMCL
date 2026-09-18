package com.pymcl.mobile.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.net.InetSocketAddress
import java.net.Proxy
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class HttpException(message: String) : RuntimeException(message)

object Http {
    val JSON = "application/json; charset=utf-8".toMediaType()

    /**
     * 全进程一个 OkHttpClient。
     *
     * 连接池与线程池都挂在实例上，每次请求新建一个等于每次重建连接池——
     * 装一个版本要发几百个请求，那是几百次 TLS 握手。
     */
    val client: OkHttpClient by lazy { build(null) }

    @Volatile
    private var proxied: OkHttpClient? = null

    @Volatile
    private var proxyKey: String = ""

    /**
     * 走代理的那个客户端。
     *
     * 同样只在代理地址变了的时候才重建，并且用 `newBuilder()` 从主客户端派生：
     * 连接池、Dispatcher 线程池都跟主客户端共用，不会因为开了代理就多出一套。
     */
    fun clientFor(proxyHost: String, proxyPort: Int): OkHttpClient {
        if (proxyHost.isBlank() || proxyPort <= 0) return client
        val key = "$proxyHost:$proxyPort"
        proxied?.let { if (proxyKey == key) return it }
        synchronized(this) {
            proxied?.let { if (proxyKey == key) return it }
            val built = client.newBuilder()
                .proxy(Proxy(Proxy.Type.HTTP, InetSocketAddress(proxyHost, proxyPort)))
                .build()
            proxied = built
            proxyKey = key
            return built
        }
    }

    private fun build(proxy: Proxy?): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .retryOnConnectionFailure(true)
        .apply { if (proxy != null) proxy(proxy) }
        .build()

    fun getText(url: String, headers: Map<String, String> = emptyMap()): String {
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", Paths.UA)
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw HttpException("HTTP ${resp.code} $url ${body.take(180)}")
            return body
        }
    }

    /** 镜像优先：挨个试，第一个成的就返回 (真正用上的 url, 正文)。 */
    fun getTextFirst(urls: List<String>): Pair<String, String> {
        var last: Exception? = null
        for (url in urls) {
            try {
                return url to getText(url)
            } catch (e: Exception) {
                last = e
            }
        }
        throw last ?: HttpException("empty url list")
    }

    /** 返回 (状态码, 正文)——4xx 的正文里常常才是真正的错误原因，不能直接丢掉。 */
    fun postJson(
        url: String,
        body: String,
        headers: Map<String, String> = emptyMap(),
    ): Pair<Int, String> {
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", Paths.UA)
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .post(body.toRequestBody(JSON))
            .build()
        client.newCall(req).execute().use { resp ->
            return resp.code to resp.body?.string().orEmpty()
        }
    }

    fun postForm(url: String, form: Map<String, String>): Pair<Int, String> {
        val encoded = form.entries.joinToString("&") { (k, v) ->
            java.net.URLEncoder.encode(k, "UTF-8") + "=" + java.net.URLEncoder.encode(v, "UTF-8")
        }
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", Paths.UA)
            .post(encoded.toRequestBody("application/x-www-form-urlencoded".toMediaType()))
            .build()
        client.newCall(req).execute().use { resp ->
            return resp.code to resp.body?.string().orEmpty()
        }
    }

    fun download(
        url: String,
        dest: File,
        sha1: String? = null,
        onProgress: (Long, Long) -> Unit = { _, _ -> },
    ) {
        dest.parentFile?.mkdirs()
        if (sha1 != null && dest.isFile && sha1Of(dest).equals(sha1, true)) {
            onProgress(dest.length(), dest.length())
            return
        }
        val req = Request.Builder().url(url).header("User-Agent", Paths.UA).get().build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw HttpException("HTTP ${resp.code} $url")
            val total = resp.body?.contentLength() ?: -1L
            val tmp = File(dest.parentFile, dest.name + ".part")
            resp.body!!.byteStream().use { input ->
                tmp.outputStream().buffered(64 * 1024).use { out ->
                    val buf = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                        done += n
                        onProgress(done, total)
                    }
                }
            }
            if (!sha1.isNullOrBlank()) {
                val got = sha1Of(tmp)
                if (!got.equals(sha1, true)) {
                    tmp.delete()
                    throw HttpException("sha1 mismatch ${dest.name} want=$sha1 got=$got")
                }
            }
            if (dest.exists()) dest.delete()
            if (!tmp.renameTo(dest)) {
                tmp.copyTo(dest, overwrite = true)
                tmp.delete()
            }
        }
    }

    fun sha1Of(file: File): String {
        val md = MessageDigest.getInstance("SHA-1")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    fun sha1OfString(text: String): String {
        val md = MessageDigest.getInstance("SHA-1")
        md.update(text.toByteArray(Charsets.UTF_8))
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
