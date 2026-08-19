package com.pymcl.mobile.data

import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class HttpException(message: String) : RuntimeException(message)

object Http {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .build()

    fun getText(url: String): String {
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", Paths.UA)
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw HttpException("HTTP ${resp.code} $url ${body.take(180)}")
            return body
        }
    }

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
                tmp.outputStream().use { out ->
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
