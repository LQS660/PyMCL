package com.pymcl.mobile.data

import com.pymcl.mobile.model.LaunchPlan
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object LaunchPlanner {
    /** 一条 inheritsFrom 链最多走这么深，挡掉互相指向的坏 json。 */
    private const val MAX_CHAIN = 16

    /**
     * 从 `<version>.json` 出发，沿 `inheritsFrom` 一路往上，子在前、父在后。
     * 返回的第一项永远是 [version] 自己，即使它的 json 不存在。
     */
    fun chain(instDir: File, version: String): List<String> {
        val out = mutableListOf(version)
        var cur = version
        repeat(MAX_CHAIN) {
            val json = versionJson(instDir, cur) ?: return out
            val parent = json.optString("inheritsFrom").trim()
            if (parent.isEmpty() || parent in out) return out
            out += parent
            cur = parent
        }
        return out
    }

    private fun versionJson(instDir: File, version: String): JSONObject? {
        val f = File(instDir, "versions/$version/$version.json")
        if (!f.isFile) return null
        return runCatching { JSONObject(f.readText()) }.getOrNull()
    }

    /**
     * 把整条继承链合成一份 json：mainClass / assetIndex / arguments 子覆盖父，
     * libraries 按 `group:artifact` 去重，子的版本赢——Fabric 覆盖原版那颗 ASM 就靠这一条。
     */
    fun resolveJson(instDir: File, version: String): JSONObject {
        val ids = chain(instDir, version)
        val merged = JSONObject()
        val libs = linkedMapOf<String, JSONObject>()
        // 从最上游的父开始铺，子的同名 key 后写进来就盖掉父的
        for (id in ids.asReversed()) {
            val json = versionJson(instDir, id) ?: continue
            val keys = json.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                if (key == "libraries" || key == "inheritsFrom") continue
                merged.put(key, json.get(key))
            }
            val arr = json.optJSONArray("libraries") ?: continue
            for (i in 0 until arr.length()) {
                val lib = arr.optJSONObject(i) ?: continue
                libs[libKey(lib)] = lib
            }
        }
        merged.put("id", version)
        val out = JSONArray()
        libs.values.forEach { out.put(it) }
        merged.put("libraries", out)
        return merged
    }

    /** `group:artifact` —— 版本号和 classifier 都不参与，同一颗库只保留一份。 */
    internal fun libKey(lib: JSONObject): String {
        val name = lib.optString("name")
        if (name.isBlank()) {
            return lib.optJSONObject("downloads")?.optJSONObject("artifact")
                ?.optString("path").orEmpty()
        }
        val parts = name.split(":")
        return if (parts.size >= 2) "${parts[0]}:${parts[1]}" else name
    }

    /**
     * 游戏真正的工作目录。开了隔离（mods / saves / all 任一档）就落在版本目录里，
     * 吃大锅饭则落在实例根——和桌面 `version_settings.game_dir` 同一套判定。
     */
    fun gameDirOf(instDir: File, version: String): File =
        if (VersionSettings.isolatedAnywhere(VersionSettings.load(instDir, version))) {
            File(instDir, "versions/$version")
        } else {
            instDir
        }

    /** 继承链里真正带客户端 jar 的那个版本。Fabric/Forge 自己没有 jar，用原版那颗。 */
    internal fun baseJar(instDir: File, ids: List<String>): File {
        for (id in ids.asReversed()) {
            val jar = File(instDir, "versions/$id/$id.jar")
            if (jar.isFile) return jar
        }
        val base = ids.lastOrNull() ?: return File(instDir, "versions/unknown/unknown.jar")
        return File(instDir, "versions/$base/$base.jar")
    }

    /**
     * @param server 直连地址，空 = 不直连。地址里自带端口也认，解析走 [TerracottaCore.parseDirect]。
     */
    fun plan(
        instance: String,
        version: String,
        username: String,
        memoryMb: Int,
        instDir: File = Paths.instanceDir(instance),
        server: String = "",
    ): LaunchPlan {
        val ids = chain(instDir, version)
        val jsonFile = File(instDir, "versions/$version/$version.json")
        val missing = mutableListOf<String>()
        if (!jsonFile.isFile) missing += jsonFile.absolutePath
        val json = resolveJson(instDir, version)
        val main = json.optString("mainClass", "net.minecraft.client.main.Main")

        val classpath = mutableListOf<String>()
        val jar = baseJar(instDir, ids)
        if (jar.isFile) classpath += jar.absolutePath else missing += jar.absolutePath

        var nativesMissing = false
        val libRoot = File(instDir, "libraries")
        val libs = json.optJSONArray("libraries")
        if (libs != null) {
            for (i in 0 until libs.length()) {
                val lib = libs.optJSONObject(i) ?: continue
                if (Installer.hasNativesClassifiers(lib) || Installer.isNativesArtifact(lib)) {
                    nativesMissing = true
                }
                if (!Installer.allowedByRules(lib)) continue
                // Fabric / Forge 的库只给 maven 坐标、不给 downloads.artifact.path，
                // 只认后者的话整个加载器的库都会被静默丢掉，游戏起来就是 ClassNotFound
                val path = Installer.artifactRelPath(lib)
                    ?: LoaderInstall.mavenPath(lib.optString("name"))
                    ?: continue
                val f = File(libRoot, path.replace("/", File.separator))
                if (f.isFile) classpath += f.absolutePath else missing += f.absolutePath
            }
        }

        val gameDir = gameDirOf(instDir, version)
        val settings = VersionSettings.load(instDir, version)
        val mem = settings.memoryMb ?: memoryMb
        val jvm = mutableListOf("-Xmx${mem}M", "-Xms${(mem / 2).coerceAtLeast(512)}M")
        // GC 预设接在用户自己写的参数前面；用户已经写了 GC 旗标就不再叠一层
        val tuned = if (settings.gc.isBlank()) settings.jvmArgs else GcPresets.apply(settings.gc, settings.jvmArgs)
        jvm += VersionSettings.splitArgs(tuned)
        val game = mutableListOf(
            "--username", username,
            "--version", version,
            "--gameDir", gameDir.absolutePath,
            "--assetsDir", File(instDir, "assets").absolutePath,
            "--accessToken", "0",
            "--uuid", "00000000-0000-0000-0000-000000000000",
            "--userType", "legacy",
        )
        if (settings.server.isNotBlank()) {
            game += listOf("--quickPlayMultiplayer", VersionSettings.addressOf(settings))
        }
        game += VersionSettings.splitArgs(settings.gameArgs)

        val direct = TerracottaCore.parseDirect(server)
        val serverArgs = if (direct.error.isEmpty() && direct.host.isNotBlank()) {
            listOf("--server", direct.host, "--port", direct.port.toString())
        } else {
            emptyList()
        }

        return LaunchPlan(
            instance = instance,
            version = version,
            mainClass = main,
            classpath = classpath.distinct(),
            gameArgs = game,
            jvmArgs = jvm,
            missing = missing.distinct(),
            nativesMissing = nativesMissing,
            gameDir = gameDir.absolutePath,
            serverArgs = serverArgs,
        )
    }

    fun describe(plan: LaunchPlan): String {
        val b = StringBuilder()
        b.appendLine("实例 ${plan.instance} / ${plan.version}")
        b.appendLine("main ${plan.mainClass}")
        b.appendLine("classpath ${plan.classpath.size} 项")
        b.appendLine("缺文件 ${plan.missing.size}")
        if (plan.nativesMissing) {
            b.appendLine("官方 natives 已跳过，进游戏走 Android LWJGL/JNI")
        }
        plan.missing.take(8).forEach { b.appendLine("  - $it") }
        return b.toString().trim()
    }
}
