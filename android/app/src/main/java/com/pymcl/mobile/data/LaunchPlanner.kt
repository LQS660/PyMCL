package com.pymcl.mobile.data

import com.pymcl.mobile.model.LaunchPlan
import org.json.JSONObject
import java.io.File

object LaunchPlanner {
    fun plan(
        instance: String,
        version: String,
        username: String,
        memoryMb: Int,
        instDir: File = Paths.instanceDir(instance),
    ): LaunchPlan {
        val inst = instDir
        val vdir = File(inst, "versions/$version")
        val jsonFile = File(vdir, "$version.json")
        val jar = File(vdir, "$version.jar")
        val missing = mutableListOf<String>()
        if (!jsonFile.isFile) missing += jsonFile.absolutePath
        if (!jar.isFile) missing += jar.absolutePath
        val json = if (jsonFile.isFile) JSONObject(jsonFile.readText()) else JSONObject()
        val main = json.optString("mainClass", "net.minecraft.client.main.Main")
        val classpath = mutableListOf<String>()
        if (jar.isFile) classpath += jar.absolutePath
        val libs = json.optJSONArray("libraries")
        var nativesMissing = false
        if (libs != null) {
            val libRoot = File(inst, "libraries")
            for (i in 0 until libs.length()) {
                val lib = libs.optJSONObject(i) ?: continue
                if (Installer.hasNativesClassifiers(lib) || Installer.isNativesArtifact(lib)) {
                    nativesMissing = true
                }
                if (!Installer.allowedByRules(lib)) continue
                val path = Installer.artifactRelPath(lib) ?: continue
                val f = File(libRoot, path.replace("/", File.separator))
                if (f.isFile) classpath += f.absolutePath else missing += f.absolutePath
            }
        }
        val jvm = listOf("-Xmx${memoryMb}M", "-Xms${(memoryMb / 2).coerceAtLeast(512)}M")
        val game = listOf(
            "--username", username,
            "--version", version,
            "--gameDir", inst.absolutePath,
            "--assetsDir", File(inst, "assets").absolutePath,
            "--accessToken", "0",
            "--uuid", "00000000-0000-0000-0000-000000000000",
            "--userType", "legacy",
        )
        return LaunchPlan(
            instance = instance,
            version = version,
            mainClass = main,
            classpath = classpath,
            gameArgs = game,
            jvmArgs = jvm,
            missing = missing.distinct(),
            nativesMissing = nativesMissing,
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
