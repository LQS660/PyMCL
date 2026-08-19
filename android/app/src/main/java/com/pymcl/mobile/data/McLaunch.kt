package com.pymcl.mobile.data

import android.content.Context
import android.content.Intent
import com.mio.data.Renderer
import com.tungsten.fclauncher.FCLConfig
import com.tungsten.fclauncher.FCLauncher
import com.tungsten.fclauncher.bridge.FCLBridge
import com.tungsten.fclauncher.plugins.DriverPlugin
import com.tungsten.fclauncher.utils.FCLPath
import org.json.JSONObject
import java.io.File

object McLaunch {
    @Volatile
    var bridge: FCLBridge? = null
        private set

    fun prepare(
        context: Context,
        instance: String,
        version: String,
        username: String,
        memoryMb: Int,
        onLog: (String) -> Unit,
    ) {
        val app = context.applicationContext
        FCLPath.loadPaths(app)
        DriverPlugin.init(app)
        val inst = Paths.instanceDir(instance)
        val jsonFile = File(inst, "versions/$version/$version.json")
        val json = JSONObject(jsonFile.readText())
        val major = JavaRuntime.javaMajor(json, version)
        val jre = JavaRuntime.jreDirName(major)
        if (jre == "jre8" || jre == "jre25") {
            throw IllegalStateException("当前包只带 JRE 17/21，版本 $version 需要 $jre")
        }
        RuntimeInstaller.ensure(app, jre, onLog)
        val plan = LaunchPlanner.plan(instance, version, username, memoryMb)
        if (plan.missing.isNotEmpty()) {
            throw IllegalStateException("仍缺 ${plan.missing.size} 个文件：${plan.missing.first()}")
        }
        val width = 1280
        val height = 720
        writeOptions(inst, width, height)
        extractLog4j(app, inst, version, json)
        val args = LaunchArgs.build(app, json, plan, username, memoryMb, width, height)
        val javaHome = when (jre) {
            "jre21" -> FCLPath.JAVA_21_PATH
            else -> FCLPath.JAVA_17_PATH
        }
        val logDir = (app.getExternalFilesDir("logs") ?: File(app.filesDir, "logs")).also { it.mkdirs() }
        val renderer = Renderer(
            "Holy-GL4ES",
            "GL4ES",
            "libgl4es_114.so",
            "libEGL.so",
            "",
            null,
            null,
            Renderer.ID_GL4ES,
            "",
            "1.21.4",
        )
        val config = FCLConfig(
            app,
            logDir.absolutePath,
            javaHome,
            inst.absolutePath,
            renderer,
            args,
        )
        config.lwjglVersion = JavaRuntime.lwjglPack(json)
        onLog("JRE $jre  LWJGL ${config.lwjglVersion}  classpath ${plan.classpath.size}")
        val created = FCLauncher.launchMinecraft(config)
        created.setGameDir(inst.absolutePath)
        created.setRenderer(renderer.name)
        created.setJava(jre)
        created.setScaleFactor(1.0)
        created.setHasTouchController(true)
        bridge = created
    }

    fun open(context: Context) {
        if (bridge == null) throw IllegalStateException("还没有 prepare")
        val intent = Intent(context, com.pymcl.mobile.GameActivity::class.java)
        if (context !is android.app.Activity) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun writeOptions(inst: File, width: Int, height: Int) {
        val file = File(inst, "options.txt")
        val map = linkedMapOf<String, String>()
        if (file.isFile) {
            file.readLines().forEach { line ->
                val i = line.indexOf(':')
                if (i > 0) map[line.substring(0, i)] = line.substring(i + 1)
            }
        }
        map["fullscreen"] = "false"
        map["overrideWidth"] = width.toString()
        map["overrideHeight"] = height.toString()
        file.writeText(map.entries.joinToString("\n") { "${it.key}:${it.value}" } + "\n")
    }

    private fun extractLog4j(context: Context, inst: File, version: String, json: JSONObject) {
        val dest = File(inst, "versions/$version/log4j2.xml")
        if (dest.isFile) return
        val id = json.optString("id", version)
        val asset = if (JavaRuntime.mcNumber(id) < 1.12) "game/log4j2-1.7.xml" else "game/log4j2-1.12.xml"
        dest.parentFile?.mkdirs()
        runCatching {
            context.assets.open(asset).use { input -> dest.outputStream().use { input.copyTo(it) } }
        }
    }
}
