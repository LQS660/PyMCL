package com.pymcl.mobile.data

import android.content.Context
import com.pymcl.mobile.model.GameInstance
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

class InstanceStore(private val context: Context) {
    suspend fun listInstances(): List<GameInstance> = withContext(Dispatchers.IO) {
        val root = Paths.minecraftRoot(context)
        if (!root.isDirectory) return@withContext emptyList()
        root.listFiles()
            ?.filter { it.isDirectory && File(it, ".instance.json").isFile }
            ?.mapNotNull { dir -> readInstance(dir.name) }
            .orEmpty()
            .sortedBy { it.name.lowercase() }
    }

    suspend fun readInstance(instanceId: String): GameInstance? = withContext(Dispatchers.IO) {
        val meta = Paths.instanceMeta(context, instanceId)
        if (!meta.isFile) return@withContext null
        val json = JSONObject(meta.readText())
        GameInstance(
            id = json.optString("id", instanceId),
            name = json.getString("name"),
            versionId = json.getString("versionId"),
            gameDir = Paths.instanceDir(context, instanceId),
            createdAt = json.optLong("createdAt", meta.lastModified()),
        )
    }

    suspend fun createInstance(name: String, versionId: String): GameInstance =
        withContext(Dispatchers.IO) {
            val id = UUID.randomUUID().toString().take(8)
            val dir = Paths.instanceDir(context, id)
            dir.mkdirs()
            val instance = GameInstance(
                id = id,
                name = name,
                versionId = versionId,
                gameDir = dir,
            )
            writeInstance(instance)
            instance
        }

    suspend fun deleteInstance(instanceId: String): Boolean = withContext(Dispatchers.IO) {
        val dir = Paths.instanceDir(context, instanceId)
        dir.exists() && dir.deleteRecursively()
    }

    private fun writeInstance(instance: GameInstance) {
        val json = JSONObject()
            .put("id", instance.id)
            .put("name", instance.name)
            .put("versionId", instance.versionId)
            .put("createdAt", instance.createdAt)
        Paths.instanceMeta(context, instance.id).writeText(json.toString(2))
    }

    fun readConfig(): JSONObject {
        val file = Paths.config(context)
        if (!file.isFile) return JSONObject()
        return runCatching { JSONObject(file.readText()) }.getOrDefault(JSONObject())
    }

    fun writeConfig(json: JSONObject) {
        Paths.ensureLayout(context)
        Paths.config(context).writeText(json.toString(2))
    }

    fun readAccounts(): JSONArray {
        val file = Paths.accounts(context)
        if (!file.isFile) return JSONArray()
        return runCatching { JSONArray(file.readText()) }.getOrDefault(JSONArray())
    }
}
