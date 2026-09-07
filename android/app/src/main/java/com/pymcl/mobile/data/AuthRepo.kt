package com.pymcl.mobile.data

import android.content.Context
import com.pymcl.mobile.model.Account
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class AuthRepo(
    private val context: Context,
    private val store: InstanceStore = InstanceStore(context),
) {
    suspend fun listAccounts(): List<Account> = withContext(Dispatchers.IO) {
        val array = store.readAccounts()
        buildList {
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                add(
                    Account(
                        id = item.getString("id"),
                        username = item.getString("username"),
                        uuid = item.optString("uuid").ifBlank { null },
                        accessToken = item.optString("accessToken").ifBlank { null },
                        deviceCode = item.optString("deviceCode").ifBlank { null },
                    ),
                )
            }
        }
    }

    suspend fun saveAccount(account: Account) = withContext(Dispatchers.IO) {
        val array = store.readAccounts()
        val updated = JSONArray()
        var replaced = false
        for (i in 0 until array.length()) {
            val item = array.getJSONObject(i)
            if (item.getString("id") == account.id) {
                updated.put(account.toJson())
                replaced = true
            } else {
                updated.put(item)
            }
        }
        if (!replaced) updated.put(account.toJson())
        Paths.ensureLayout(context)
        Paths.accounts(context).writeText(updated.toString(2))
    }

    suspend fun createOfflineAccount(username: String): Account {
        val account = Account(
            id = UUID.randomUUID().toString(),
            username = username,
            uuid = UUID.randomUUID().toString(),
        )
        saveAccount(account)
        return account
    }

    /** 设备码登录占位：后续里程碑对接 OAuth 设备流 */
    suspend fun beginDeviceCodeLogin(): Result<String> =
        Result.failure(UnsupportedOperationException("设备码登录尚未接入"))

    private fun Account.toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("username", username)
        .put("uuid", uuid)
        .put("accessToken", accessToken)
        .put("deviceCode", deviceCode)
}
