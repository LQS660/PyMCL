package com.pymcl.mobile.data

import android.content.Context
import android.os.Build
import com.tungsten.fclauncher.utils.Architecture
import com.tungsten.fclauncher.utils.FCLPath
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.TimeZone

object LaunchArgs {
    val FEATURES = setOf("has_custom_resolution")

    fun build(
        context: Context,
        json: JSONObject,
        plan: com.pymcl.mobile.model.LaunchPlan,
        username: String,
        memoryMb: Int,
        width: Int,
        height: Int,
    ): Array<String> {
        val inst = Paths.instanceDir(plan.instance)
        val gameDir = if (plan.gameDir.isNotBlank()) File(plan.gameDir) else inst
        val javaMajor = JavaRuntime.javaMajor(json, plan.version)
        val lwjgl = JavaRuntime.lwjglPack(json)
        val useX = JavaRuntime.needsLwjglX(json)
        val nativeDir = context.applicationInfo.nativeLibraryDir
        val abi = Architecture.archAsStringAndroid(Architecture.getDeviceArchitecture())
        val lwjglDir = File(FCLPath.LWJGL_DIR, lwjgl)
        val gameJar = JavaRuntime.versionJar(inst, json, plan.version)
        val uuid = JavaRuntime.offlineUuid(username)
        val assetsId = JavaRuntime.assetIndex(json).ifBlank { "legacy" }
        val assetsRoot = File(inst, "assets").absolutePath
        val classpath = linkedSetOf<String>()
        addLwjglJars(classpath, lwjglDir, useX)
        plan.classpath.forEach { path ->
            if (!JavaRuntime.isLwjglLibraryPath(path) && File(path).isFile) classpath += path
        }
        val wrapper = File(FCLPath.MIO_LAUNCH_WRAPPER)
        if (wrapper.isFile) classpath += wrapper.absolutePath
        if (gameJar.isFile) classpath += gameJar.absolutePath

        val out = mutableListOf<String>()
        addCacio(out, javaMajor, width, height)
        out += "-Xmx${memoryMb}m"
        out += "-Xms${(memoryMb / 2).coerceAtLeast(512)}m"
        out += "-Dfile.encoding=UTF-8"
        if (javaMajor < 19) {
            out += "-Dsun.stdout.encoding=UTF-8"
            out += "-Dsun.stderr.encoding=UTF-8"
        } else {
            out += "-Dstdout.encoding=UTF-8"
            out += "-Dstderr.encoding=UTF-8"
        }
        out += "-Djava.rmi.server.useCodebaseOnly=true"
        out += "-Dcom.sun.jndi.rmi.object.trustURLCodebase=false"
        out += "-Dcom.sun.jndi.cosnaming.object.trustURLCodebase=false"
        out += "-Dlog4j2.formatMsgNoLookups=true"
        out += "-Dminecraft.client.jar=${gameJar.absolutePath}"
        out += "-Dminecraft.launcher.brand=PyMCL"
        out += "-Dminecraft.launcher.version=${Paths.APP_VERSION}"
        out += "-XX:ActiveProcessorCount=${Runtime.getRuntime().availableProcessors()}"
        out += "-Dfml.ignoreInvalidMinecraftCertificates=true"
        out += "-Dfml.ignorePatchDiscrepancies=true"
        out += "-Dext.net.resolvPath=${FCLPath.JAVA_PATH}/resolv.conf"
        out += "-Djava.io.tmpdir=${FCLPath.CACHE_DIR}"
        out += "-Dos.name=Linux"
        out += "-Dos.version=Android-${Build.VERSION.RELEASE}"
        out += "-Dorg.lwjgl.opengl.libname=\${gl_lib_name}"
        out += "-Dorg.lwjgl.openal.libname=$nativeDir/libopenal.so"
        out += "-Dorg.lwjgl.freetype.libname=${lwjglDir.absolutePath}/natives/$abi/libfreetype.so"
        out += "-Dorg.lwjgl.system.allocator=system"
        out += "-Dfml.earlyprogresswindow=false"
        out += "-Dglfwstub.initEgl=false"
        out += "-Dloader.disable_forked_guis=true"
        out += "-Duser.home=${gameDir.absolutePath}"
        out += "-Duser.language=${Locale.getDefault().language}"
        out += "-Duser.country=${Locale.getDefault().country}"
        out += "-Duser.timezone=${TimeZone.getDefault().id}"
        out += "-Dorg.lwjgl.vulkan.libname=libvulkan.so"
        out += "-Dorg.lwjgl.spvc.libname=spirv-cross-c-shared"
        out += "-Dsodium.checks.issue2561=false"
        out += "-Djdk.lang.Process.launchMechanism=FORK"
        out += "-Djna.boot.library.path=${FCLPath.JNA_PATH}"
        val patcher = File(FCLPath.LIB_PATCHER_PATH)
        if (patcher.isFile) out += "-javaagent:${patcher.absolutePath}"

        val vars = mapOf(
            "\${natives_directory}" to "\${natives_directory}",
            "\${classpath}" to classpath.joinToString(File.pathSeparator),
            "\${launcher_name}" to "PyMCL",
            "\${launcher_version}" to Paths.APP_VERSION,
            "\${auth_player_name}" to username,
            "\${auth_session}" to "0",
            "\${auth_access_token}" to "0",
            "\${auth_uuid}" to uuid,
            "\${version_name}" to plan.version,
            "\${profile_name}" to "PyMCL",
            "\${version_type}" to json.optString("type", "release"),
            "\${game_directory}" to gameDir.absolutePath,
            "\${user_type}" to "legacy",
            "\${assets_index_name}" to assetsId,
            "\${assets_root}" to assetsRoot,
            "\${game_assets}" to assetsRoot,
            "\${user_properties}" to "{}",
            "\${resolution_width}" to width.toString(),
            "\${resolution_height}" to height.toString(),
            "\${library_directory}" to File(inst, "libraries").absolutePath,
            "\${classpath_separator}" to File.pathSeparator,
            "\${primary_jar}" to gameJar.absolutePath,
            "\${language}" to Locale.getDefault().toString(),
            "\${file_separator}" to File.separator,
            "\${primary_jar_name}" to gameJar.name,
            "\${clientid}" to "0",
            "\${auth_xuid}" to "0",
        )
        addJsonJvm(out, json, vars)
        out += "-cp"
        out += classpath.joinToString(File.pathSeparator)
        if (javaMajor != 8) {
            val pkg = plan.mainClass.substringBeforeLast('.', plan.mainClass)
            out += "--add-exports"
            out += "$pkg/$pkg=ALL-UNNAMED"
        }
        if (wrapper.isFile) {
            out += "mio.Wrapper"
        }
        out += plan.mainClass
        addGameArgs(out, json, vars, plan, width, height)
        return out.toTypedArray()
    }

    private fun addLwjglJars(classpath: LinkedHashSet<String>, dir: File, useX: Boolean) {
        val lwjgl = File(dir, "lwjgl.jar")
        if (lwjgl.isFile) classpath += lwjgl.absolutePath
        if (useX) {
            val x = File(dir, "lwjgl-lwjglx.jar")
            if (x.isFile) classpath += x.absolutePath
        }
        dir.listFiles()?.forEach { f ->
            if (f.isFile && f.name.endsWith(".jar") && f.name != "lwjgl.jar" && f.name != "lwjgl-lwjglx.jar") {
                classpath += f.absolutePath
            }
        }
    }

    private fun addCacio(out: MutableList<String>, javaMajor: Int, width: Int, height: Int) {
        val java8 = javaMajor == 8
        out += "-Djava.awt.headless=false"
        out += "-Dcacio.managed.screensize=${width}x$height"
        out += "-Dcacio.font.fontmanager=sun.awt.X11FontManager"
        out += "-Dcacio.font.fontscaler=sun.font.FreetypeFontScaler"
        out += "-Dswing.defaultlaf=javax.swing.plaf.nimbus.NimbusLookAndFeel"
        if (java8) {
            out += "-Dawt.toolkit=net.java.openjdk.cacio.ctc.CTCToolkit"
            out += "-Djava.awt.graphicsenv=net.java.openjdk.cacio.ctc.CTCGraphicsEnvironment"
        } else {
            out += "-Dawt.toolkit=com.github.caciocavallosilano.cacio.ctc.CTCToolkit"
            out += "-Djava.awt.graphicsenv=com.github.caciocavallosilano.cacio.ctc.CTCGraphicsEnvironment"
            out += "-javaagent:${FCLPath.CACIOCAVALLO_17_DIR}/cacio-agent.jar"
            listOf(
                "--add-exports=java.desktop/java.awt=ALL-UNNAMED",
                "--add-exports=java.desktop/java.awt.peer=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.awt.image=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.java2d=ALL-UNNAMED",
                "--add-exports=java.desktop/java.awt.dnd.peer=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.awt=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.awt.event=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.awt.datatransfer=ALL-UNNAMED",
                "--add-exports=java.desktop/sun.font=ALL-UNNAMED",
                "--add-exports=java.base/sun.security.action=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.desktop/java.awt=ALL-UNNAMED",
                "--add-opens=java.desktop/sun.font=ALL-UNNAMED",
                "--add-opens=java.desktop/sun.java2d=ALL-UNNAMED",
                "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
                "--add-opens=java.base/java.net=ALL-UNNAMED",
            ).forEach { out += it }
        }
        val dir = File(if (java8) FCLPath.CACIOCAVALLO_8_DIR else FCLPath.CACIOCAVALLO_17_DIR)
        val boot = StringBuilder("-Xbootclasspath/").append(if (java8) "p" else "a")
        dir.listFiles()?.forEach { f ->
            if (f.isFile && f.name.endsWith(".jar")) boot.append(":").append(f.absolutePath)
        }
        out += boot.toString()
    }

    private fun addJsonJvm(out: MutableList<String>, json: JSONObject, vars: Map<String, String>) {
        val jvm = json.optJSONObject("arguments")?.optJSONArray("jvm") ?: return
        var skipNext = false
        for (item in flattenArgs(jvm, hasCustomRes = true)) {
            if (skipNext) {
                skipNext = false
                continue
            }
            val filled = fill(item, vars)
            if (filled == "-cp" || filled == "-classpath") {
                skipNext = true
                continue
            }
            if (filled.startsWith("-Djava.library.path") ||
                filled.startsWith("-Djna.tmpdir") ||
                filled.startsWith("-Dorg.lwjgl.system.SharedLibraryExtractPath") ||
                filled.startsWith("-Dio.netty.native.workdir")
            ) {
                out += filled.replace(vars["\${natives_directory}"] ?: "", FCLPath.CACHE_DIR)
                continue
            }
            out += filled
        }
    }

    private fun addGameArgs(
        out: MutableList<String>,
        json: JSONObject,
        vars: Map<String, String>,
        plan: com.pymcl.mobile.model.LaunchPlan,
        width: Int,
        height: Int,
    ) {
        val game = json.optJSONObject("arguments")?.optJSONArray("game")
        val old = json.optString("minecraftArguments")
        if (game != null) {
            extractGameArgs(json).forEach { out += fill(it, vars) }
            out += "--width"
            out += width.toString()
            out += "--height"
            out += height.toString()
            return
        }
        if (old.isNotBlank()) {
            old.split(Regex("\\s+")).filter { it.isNotBlank() }.forEach { out += fill(it, vars) }
            return
        }
        out.addAll(plan.gameArgs)
        out += "--width"
        out += width.toString()
        out += "--height"
        out += height.toString()
    }

    fun extractGameArgs(json: JSONObject, enabled: Set<String> = FEATURES): List<String> {
        val game = json.optJSONObject("arguments")?.optJSONArray("game") ?: return emptyList()
        return flattenArgs(game, enabled).filterNot { isQuickPlayToken(it) }
    }

    private fun flattenArgs(arr: JSONArray, enabled: Set<String>): List<String> {
        val out = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val v = arr.opt(i) ?: continue
            when (v) {
                is String -> if (!isQuickPlayToken(v)) out += v
                is JSONObject -> {
                    if (!ruleAllows(v, enabled)) continue
                    when (val value = v.opt("value")) {
                        is String -> if (!isQuickPlayToken(value)) out += value
                        is JSONArray -> {
                            for (j in 0 until value.length()) {
                                val s = value.optString(j)
                                if (s.isNotBlank() && !isQuickPlayToken(s)) out += s
                            }
                        }
                    }
                }
            }
        }
        return out
    }

    private fun flattenArgs(arr: JSONArray, hasCustomRes: Boolean): List<String> {
        val enabled = if (hasCustomRes) FEATURES else emptySet()
        return flattenArgs(arr, enabled)
    }

    internal fun ruleAllows(obj: JSONObject, enabled: Set<String> = FEATURES): Boolean {
        val rules = obj.optJSONArray("rules") ?: return true
        var allow = false
        for (i in 0 until rules.length()) {
            val rule = rules.optJSONObject(i) ?: continue
            val os = rule.optJSONObject("os")
            if (os != null) {
                val name = os.optString("name")
                if (name.isNotBlank() && !name.equals("linux", ignoreCase = true)) continue
            }
            if (!featuresMatch(rule.optJSONObject("features"), enabled)) continue
            allow = rule.optString("action", "allow") == "allow"
        }
        return allow
    }

    private fun featuresMatch(features: JSONObject?, enabled: Set<String>): Boolean {
        if (features == null) return true
        val keys = features.keys()
        while (keys.hasNext()) {
            val key = keys.next() as String
            if (features.optBoolean(key) != (key in enabled)) return false
        }
        return true
    }

    private fun isQuickPlayToken(token: String): Boolean {
        return token.startsWith("--quickPlay") ||
            token.contains("\${quickPlay") ||
            token.contains("\${quick_play")
    }

    private fun fill(raw: String, vars: Map<String, String>): String {
        var s = raw
        vars.forEach { (k, v) -> s = s.replace(k, v) }
        return s
    }
}
