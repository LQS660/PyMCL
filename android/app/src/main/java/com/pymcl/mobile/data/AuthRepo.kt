package com.pymcl.mobile.data

import com.pymcl.mobile.model.AccountInfo
import com.pymcl.mobile.model.DeviceCode
import okhttp3.FormBody
import okhttp3.Request
import org.json.JSONObject

object AuthRepo {
    fun accounts(): List<AccountInfo> {
        val offline = AccountInfo("离线", "offline")
        val saved = InstanceStore.loadAccounts().map {
            AccountInfo(
                name = it.optString("name"),
                type = it.optString("type", "microsoft"),
                uuid = it.optString("uuid"),
                accessToken = it.optString("access_token"),
                refreshToken = it.optString("refresh_token"),
            )
        }
        return listOf(offline) + saved
    }

    fun startDeviceCode(): DeviceCode {
        val body = FormBody.Builder()
            .add("client_id", Paths.MS_CLIENT)
            .add("scope", "XboxLive.signin offline_access")
            .build()
        val req = Request.Builder().url(Paths.MS_DEVICE).header("User-Agent", Paths.UA).post(body).build()
        Http.client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw HttpException("device code HTTP ${resp.code} $text")
            val o = JSONObject(text)
            return DeviceCode(
                deviceCode = o.getString("device_code"),
                userCode = o.getString("user_code"),
                uri = o.optString("verification_uri", "https://www.microsoft.com/link"),
                interval = o.optInt("interval", 5),
                expiresIn = o.optInt("expires_in", 900),
            )
        }
    }

    fun pollOnce(deviceCode: String): JSONObject? {
        val body = FormBody.Builder()
            .add("grant_type", "urn:ietf:params:oauth:grant-type:device_code")
            .add("client_id", Paths.MS_CLIENT)
            .add("device_code", deviceCode)
            .build()
        val req = Request.Builder().url(Paths.MS_TOKEN).header("User-Agent", Paths.UA).post(body).build()
        Http.client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            val o = runCatching { JSONObject(text) }.getOrNull() ?: JSONObject()
            if (resp.isSuccessful) return o
            val err = o.optString("error")
            if (err == "authorization_pending" || err == "slow_down") return null
            throw HttpException(o.optString("error_description", err.ifBlank { text.take(160) }))
        }
    }

    fun saveMicrosoft(name: String, access: String, refresh: String) {
        val list = InstanceStore.loadAccounts().toMutableList()
        list.removeAll { it.optString("name") == name }
        list.add(
            JSONObject()
                .put("name", name)
                .put("type", "microsoft")
                .put("access_token", access)
                .put("refresh_token", refresh),
        )
        InstanceStore.saveAccounts(list)
    }
}
