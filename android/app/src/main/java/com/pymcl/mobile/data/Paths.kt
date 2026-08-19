package com.pymcl.mobile.data

import com.pymcl.mobile.PyMclApp
import org.json.JSONObject
import java.io.File

object Paths {
    const val APP_VERSION = "1.0.1"
    const val UA = "PyMCL/$APP_VERSION (android; +minecraft launcher)"
    const val BMCL = "https://bmclapi2.bangbang93.com"
    const val MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
    const val BMCL_MANIFEST = "$BMCL/mc/game/version_manifest_v2.json"
    const val MCIM = "https://mod.mcimirror.top"
    const val MS_DEVICE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
    const val MS_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    const val MS_CLIENT = "00000000402b5328"

    val root: File
        get() = File(PyMclApp.instance.filesDir, "pymcl").also { it.mkdirs() }

    val cache get() = File(root, "cache").also { it.mkdirs() }
    val instancesRoot get() = File(root, ".minecraft").also { it.mkdirs() }
    val configFile get() = File(root, "config.json")
    val accountsFile get() = File(root, "accounts.json")
    val manifestCache get() = File(cache, "version_manifest.json")

    fun instanceDir(name: String) = File(instancesRoot, name)

    fun readJson(file: File, fallback: JSONObject = JSONObject()): JSONObject {
        if (!file.isFile) return fallback
        return runCatching { JSONObject(file.readText(Charsets.UTF_8)) }.getOrDefault(fallback)
    }

    fun writeJson(file: File, obj: JSONObject) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(obj.toString(2), Charsets.UTF_8)
        if (file.exists()) file.delete()
        tmp.renameTo(file)
    }
}
