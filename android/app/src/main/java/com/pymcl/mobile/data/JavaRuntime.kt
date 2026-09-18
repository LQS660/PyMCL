package com.pymcl.mobile.data

import org.json.JSONObject
import java.io.File
import java.util.UUID

/** 本机探测到的一个 Java。`path` 空 = 随包自带的运行时。 */
data class JavaInfo(
    val major: Int,
    val path: String,
    val name: String,
    val bundled: Boolean = false,
)

data class JavaVendor(val key: String, val label: String)

object JavaRuntime {
    // ------------------------------------------------------------ 版本判定
    fun javaMajor(json: JSONObject, versionId: String = ""): Int {
        val listed = json.optJSONObject("javaVersion")?.optInt("majorVersion", 0) ?: 0
        if (listed > 0) return listed
        val id = versionId.ifBlank { json.optString("id") }
        val n = mcNumber(id)
        return when {
            n >= 1.205 -> 21
            n >= 1.18 -> 17
            n >= 1.17 -> 16
            else -> 8
        }
    }

    /**
     * 大版本 → 随包运行时的目录名。
     *
     * 没有 jre16 这个档，1.17 要的 16 必须往上取 jre17——落到 jre8 的话
     * 1.17 一启动就是 UnsupportedClassVersionError。取整规则跟 [pick] 一致：
     * 装不到正好那一版就用更高的那一版，不往下退。
     */
    fun jreDirName(major: Int): String = when {
        major >= 25 -> "jre25"
        major >= 21 -> "jre21"
        major >= 16 -> "jre17"
        else -> "jre8"
    }

    fun lwjglPack(json: JSONObject): String {
        val libs = json.optJSONArray("libraries") ?: return "3.3.3"
        var best = "3.3.3"
        for (i in 0 until libs.length()) {
            val name = libs.optJSONObject(i)?.optString("name").orEmpty()
            val parts = name.split(":")
            if (parts.size < 3) continue
            if (parts[0] != "org.lwjgl" || parts[1] != "lwjgl") continue
            val ver = parts[2]
            if (compareVer(ver, "3.4.1") >= 0) return "3.4.1"
            if (compareVer(ver, "3.3.3") >= 0) best = "3.3.3"
        }
        return best
    }

    fun needsLwjglX(json: JSONObject): Boolean {
        val libs = json.optJSONArray("libraries") ?: return false
        for (i in 0 until libs.length()) {
            val name = libs.optJSONObject(i)?.optString("name").orEmpty()
            if (name.startsWith("org.lwjgl.lwjgl:lwjgl:2")) return true
        }
        return false
    }

    fun offlineUuid(username: String): String =
        UUID.nameUUIDFromBytes("OfflinePlayer:$username".toByteArray(Charsets.UTF_8)).toString()

    fun isLwjglLibraryPath(path: String): Boolean =
        path.replace('\\', '/').contains("/org/lwjgl/")

    fun mcNumber(id: String): Double {
        val m = Regex("""(\d+)\.(\d+)(?:\.(\d+))?""").find(id) ?: return 0.0
        val major = m.groupValues[1].toInt()
        val minor = m.groupValues[2].toInt()
        val patch = m.groupValues.getOrNull(3)?.toIntOrNull() ?: 0
        return major + minor / 100.0 + patch / 10000.0
    }

    fun compareVer(a: String, b: String): Int {
        val pa = a.split('.', '-').mapNotNull { it.toIntOrNull() }
        val pb = b.split('.', '-').mapNotNull { it.toIntOrNull() }
        val n = maxOf(pa.size, pb.size)
        for (i in 0 until n) {
            val x = pa.getOrElse(i) { 0 }
            val y = pb.getOrElse(i) { 0 }
            if (x != y) return x.compareTo(y)
        }
        return 0
    }

    fun assetIndex(json: JSONObject): String =
        json.optJSONObject("assetIndex")?.optString("id").orEmpty()
            .ifBlank { json.optString("assets") }

    fun versionJar(instDir: File, json: JSONObject, version: String): File {
        val direct = File(instDir, "versions/$version/$version.jar")
        if (direct.isFile) return direct
        val inherited = json.optString("inheritsFrom")
        if (inherited.isNotBlank()) {
            val parent = File(instDir, "versions/$inherited/$inherited.jar")
            if (parent.isFile) return parent
        }
        return direct
    }

    // -------------------------------------------------------------- 发行版
    /** 对齐桌面 `mclauncher/java.py` 的 `JAVA_VENDORS`：键、显示名、顺序都照抄。 */
    val vendors: List<JavaVendor> = listOf(
        JavaVendor("adoptium", "Adoptium Temurin"),
        JavaVendor("zulu", "Azul Zulu"),
        JavaVendor("microsoft", "Microsoft OpenJDK"),
    )

    /** ≡ 桌面 `java_vendor_list()`。 */
    val vendorKeys: List<String> get() = vendors.map { it.key }

    /** ≡ 桌面 `java_vendor_label()`：大小写不敏感；不认识的原样回，空的当 adoptium。 */
    fun vendorLabel(key: String): String {
        val k = key.trim().lowercase()
        return vendors.firstOrNull { it.key == k }?.label ?: key.ifBlank { "adoptium" }
    }

    /** 桌面 Java 页那四块下载磁贴，说明文字照抄，免得两端讲法不一样。 */
    val downloadableMajors: List<Pair<Int, String>> = listOf(
        8 to "1.16 及以下旧版本",
        11 to "部分旧模组环境",
        17 to "1.18 – 1.20.4 推荐",
        21 to "1.20.5+ 新版本",
    )

    /** 安卓只有这两种 ABI 值得管，x86 模拟器上跑 MC 不是我们的目标场景。 */
    fun adoptiumArch(abi: String): String = when {
        abi.startsWith("arm64") || abi == "aarch64" -> "aarch64"
        abi.startsWith("armeabi") || abi.startsWith("arm") -> "arm"
        abi == "x86_64" -> "x64"
        else -> "aarch64"
    }

    /** Adoptium 只有 8/11/17/21 这类 GA 大版本，16 这种要抬到 17。 */
    fun adoptiumMajor(major: Int): Int = when {
        major <= 8 -> 8
        major <= 11 -> 11
        major <= 17 -> 17
        major <= 21 -> 21
        else -> 21
    }

    fun downloadUrl(vendor: String, major: Int, abi: String): String {
        val arch = adoptiumArch(abi)
        val ga = adoptiumMajor(major)
        return when (vendor.trim().lowercase()) {
            "zulu" ->
                "https://api.azul.com/metadata/v1/zulu/packages/?java_version=$ga" +
                    "&os=linux&arch=$arch&java_package_type=jre&archive_type=tar.gz" +
                    "&javafx_bundled=false&latest=true&release_status=ga"
            "microsoft" ->
                "https://aka.ms/download-jdk/microsoft-jdk-$ga-linux-$arch.tar.gz"
            else ->
                "https://api.adoptium.net/v3/binary/latest/$ga/ga/linux/$arch/jre/hotspot/normal/eclipse"
        }
    }

    // -------------------------------------------------------------- 本机探测
    /** `java_dir` 下每个子目录就是一个装好的运行时，认 `bin/java` 是不是真在。 */
    fun scanInstalled(javaRoot: File): List<JavaInfo> {
        val dirs = javaRoot.listFiles()?.filter { it.isDirectory } ?: return emptyList()
        return dirs.mapNotNull { dir ->
            if (!File(dir, "bin/java").isFile) return@mapNotNull null
            JavaInfo(major = majorFromDirName(dir.name), path = dir.absolutePath, name = dir.name)
        }.sortedBy { it.major }
    }

    /** 目录名里那串数字就是大版本：jre17 / java-21 / 21 都认。 */
    fun majorFromDirName(name: String): Int {
        val m = Regex("""(\d{1,2})""").find(name) ?: return 0
        return m.groupValues[1].toIntOrNull() ?: 0
    }

    /**
     * 挑一个能跑这个版本的 Java。
     *
     * 规则跟桌面 `pick_java_for_version` 一致：优先精确匹配大版本，
     * 没有就往上取最小的一个更高版本；再没有才退回最高的那个。
     */
    fun pick(installed: List<JavaInfo>, want: Int, prefer: String = ""): JavaInfo? {
        if (installed.isEmpty()) return null
        if (prefer.isNotBlank()) {
            installed.firstOrNull { it.path == prefer }?.let { return it }
        }
        installed.firstOrNull { it.major == want }?.let { return it }
        installed.filter { it.major > want }.minByOrNull { it.major }?.let { return it }
        return installed.maxByOrNull { it.major }
    }

    /** 每个实例可以单独钉一个 Java，空 = 跟全局走。 */
    fun instanceJavaKey(instance: String): String = "java_for_$instance"

    fun instanceJava(instance: String): String = Settings.str(instanceJavaKey(instance))

    fun setInstanceJava(instance: String, path: String) {
        Settings.set(instanceJavaKey(instance), path)
    }

    /** 实例偏好 → 全局默认 → 自动，跟桌面「版本设置与实例偏好都是自动时才用全局」同序。 */
    fun resolvePreferred(instance: String): String {
        val perInstance = instanceJava(instance)
        if (perInstance.isNotBlank()) return perInstance
        return Settings.str(SettingsKeys.DEFAULT_JAVA)
    }
}
