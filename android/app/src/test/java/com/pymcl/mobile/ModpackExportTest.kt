package com.pymcl.mobile

import com.pymcl.mobile.data.ExportFile
import com.pymcl.mobile.data.ExportPlan
import com.pymcl.mobile.data.HashLookup
import com.pymcl.mobile.data.ModpackExport
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.PackFormat
import com.pymcl.mobile.data.PackMeta
import com.pymcl.mobile.data.Paths
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.FileNotFoundException
import java.nio.file.Files
import java.security.MessageDigest
import java.util.zip.ZipFile

/**
 * 导出 .mrpack，对照桌面 `mclauncher/export_pack.py`：
 * Modrinth 认得的 jar 进 files、认不得的进 overrides、四个 override 目录整目录进包、
 * 索引字段一致，而且导出来的包能被自家 [ModpackIndex] 原样读回去。全程不联网。
 */
class ModpackExportTest {
    private fun run(block: (File) -> Unit) {
        val root = Files.createTempDirectory("mrpack-export-").toFile()
        try { block(root) } finally { root.deleteRecursively() }
    }

    private fun sha1(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-1").digest(bytes).joinToString("") { "%02x".format(it) }

    /** Modrinth `version_file/<sha1>` 返回的 version 对象，只带用得上的那几格。 */
    private fun versionJson(url: String, sha512: String = "deadbeef", size: Long = 4321, primary: Boolean = true) = """
        {"id":"v1","files":[{"url":"$url","primary":$primary,"size":$size,"filename":"x.jar",
          "hashes":{"sha1":"ignored","sha512":"$sha512"}}]}
    """.trimIndent()

    private fun seed(root: File): Map<String, ByteArray> {
        val known = byteArrayOf(1, 2, 3, 4)
        val unknown = byteArrayOf(9, 9, 9)
        File(root, "mods").mkdirs()
        File(root, "mods/known.jar").writeBytes(known)
        File(root, "mods/local.jar").writeBytes(unknown)
        File(root, "mods/readme.txt").writeText("not a jar")
        File(root, "mods/Disabled.JAR.disabled").writeText("off")
        File(root, "config/sub").mkdirs()
        File(root, "config/a.toml").writeText("a=1")
        File(root, "config/sub/b.json").writeText("{}")
        File(root, "resourcepacks").mkdirs()
        File(root, "resourcepacks/pack.zip").writeBytes(byteArrayOf(0x50, 0x4B))
        File(root, "datapacks/dp").mkdirs()
        File(root, "datapacks/dp/pack.mcmeta").writeText("{}")
        // 不在四个 override 目录里的东西不该进包
        File(root, "saves/world").mkdirs()
        File(root, "saves/world/level.dat").writeText("lvl")
        File(root, "logs").mkdirs()
        File(root, "logs/latest.log").writeText("...")
        return mapOf("known" to known, "unknown" to unknown)
    }

    // ------------------------------------------------------------ 编排

    @Test
    fun knownJarsGoToFilesUnknownJarsAndOverrideDirsGoToOverrides() = run { root ->
        val bytes = seed(root)
        val knownSha1 = sha1(bytes.getValue("known"))
        val asked = ArrayList<String>()
        val lookup = HashLookup { sha ->
            asked.add(sha)
            if (sha == knownSha1) versionJson("https://cdn.modrinth.com/data/AAA/versions/1/known.jar") else null
        }
        val notes = ArrayList<String>()
        val plan = ModpackExport.collect(root, PackMeta("pack"), lookup) { what, _, _ -> notes.add(what) }

        // 只有 .jar 会去问 Modrinth（.txt / .disabled 都不算模组）
        assertEquals(2, asked.size)
        assertEquals(listOf("mods/known.jar"), plan.files.map { it.path })
        val f = plan.files.single()
        assertEquals(knownSha1, f.sha1)
        assertEquals("deadbeef", f.sha512)
        assertEquals("https://cdn.modrinth.com/data/AAA/versions/1/known.jar", f.url)
        assertEquals(4321L, f.size)

        val rels = plan.overrides.map { it.first }
        assertEquals(
            listOf("mods/local.jar", "config/a.toml", "config/sub/b.json", "resourcepacks/pack.zip", "datapacks/dp/pack.mcmeta"),
            rels,
        )
        assertTrue(plan.overrides.all { it.second.isFile })
        assertTrue(notes.any { it.contains("known.jar") } && notes.any { it.contains("local.jar") })
        // 桌面的 OVERRIDE_DIRS 原样
        assertEquals(listOf("config", "resourcepacks", "shaderpacks", "datapacks"), ModpackExport.OVERRIDE_DIRS)
    }

    @Test
    fun lookupErrorsAndMissingUrlsFallBackToOverrides() = run { root ->
        seed(root)
        val throwing = HashLookup { throw IllegalStateException("network down") }
        val plan = ModpackExport.collect(root, PackMeta("pack"), throwing)
        assertTrue(plan.files.isEmpty())
        assertEquals(listOf("mods/known.jar", "mods/local.jar"), plan.overrides.map { it.first }.filter { it.startsWith("mods/") })

        // Modrinth 认得但没给下载地址：同样只能进 overrides
        val noUrl = HashLookup { """{"files":[{"primary":true,"size":1,"hashes":{}}]}""" }
        assertTrue(ModpackExport.collect(root, PackMeta("pack"), noUrl).files.isEmpty())
    }

    @Test
    fun sizeFallsBackToLocalJarWhenModrinthOmitsIt() = run { root ->
        val bytes = seed(root)
        val lookup = HashLookup { versionJson("https://x/known.jar", size = 0) }
        val plan = ModpackExport.collect(root, PackMeta("pack"), lookup)
        assertEquals(bytes.getValue("known").size.toLong(), plan.files.first { it.path == "mods/known.jar" }.size)
    }

    @Test
    fun emptyInstanceExportsAnEmptyPlan() = run { root ->
        val plan = ModpackExport.collect(root, PackMeta("empty"), HashLookup { null })
        assertTrue(plan.files.isEmpty())
        assertTrue(plan.overrides.isEmpty())
    }

    // ------------------------------------------------------------ 主文件

    @Test
    fun primaryFilePicksMarkedPrimaryElseFirst() {
        val two = """{"files":[{"url":"https://x/a.jar"},{"url":"https://x/b.jar","primary":true}]}"""
        assertEquals("https://x/b.jar", ModpackExport.primaryFile(two)!!.getString("url"))
        val none = """{"files":[{"url":"https://x/a.jar"},{"url":"https://x/b.jar"}]}"""
        assertEquals("https://x/a.jar", ModpackExport.primaryFile(none)!!.getString("url"))
        // 多个 primary 取最后一个，与桌面那个循环一致
        val multi = """{"files":[{"url":"https://x/a.jar","primary":true},{"url":"https://x/b.jar","primary":true}]}"""
        assertEquals("https://x/b.jar", ModpackExport.primaryFile(multi)!!.getString("url"))
        assertNull(ModpackExport.primaryFile("""{"files":[{"primary":true}]}"""))
        assertNull(ModpackExport.primaryFile("""{"files":[]}"""))
        assertNull(ModpackExport.primaryFile("""{"error":"not found"}"""))
        assertNull(ModpackExport.primaryFile("<html>502</html>"))
    }

    // ------------------------------------------------------------ 索引

    @Test
    fun indexHasTheDesktopShape() {
        val plan = ExportPlan(
            meta = PackMeta("My Pack", "2.3.0", "1.20.1", "fabric-loader", "0.16.0", instanceName = "inst"),
            files = listOf(
                ExportFile("mods/a.jar", "abc", "def", "https://x/a.jar", 10),
                ExportFile("mods/nohash.jar", "", "", "https://x/n.jar", 1),
            ),
        )
        val idx = ModpackExport.buildIndex(plan)
        assertEquals(1, idx.getInt("formatVersion"))
        assertEquals("minecraft", idx.getString("game"))
        assertEquals("2.3.0", idx.getString("versionId"))
        assertEquals("My Pack", idx.getString("name"))
        assertTrue(idx.getString("summary").contains("inst"))
        val deps = idx.getJSONObject("dependencies")
        assertEquals("1.20.1", deps.getString("minecraft"))
        assertEquals("0.16.0", deps.getString("fabric-loader"))
        // 没 sha1 的那条不进 files
        val files = idx.getJSONArray("files")
        assertEquals(1, files.length())
        val f = files.getJSONObject(0)
        assertEquals("mods/a.jar", f.getString("path"))
        assertEquals("abc", f.getJSONObject("hashes").getString("sha1"))
        assertEquals("def", f.getJSONObject("hashes").getString("sha512"))
        assertEquals("https://x/a.jar", f.getJSONArray("downloads").getString(0))
        assertEquals(10L, f.getLong("fileSize"))
    }

    @Test
    fun indexOmitsUnknownDependencies() {
        // 原版：没有 mc 版本就没有 dependencies；加载器没有版本号也不写（桌面 `if v` 过滤）
        val bare = ModpackExport.buildIndex(ExportPlan(PackMeta("p")))
        assertEquals(0, bare.getJSONObject("dependencies").length())
        assertEquals("1.0.0", bare.getString("versionId"))
        assertEquals("p", bare.getString("name"))
        val noLoaderVer = ModpackExport.buildIndex(ExportPlan(PackMeta("p", mcVersion = "1.20.1", loader = "forge")))
        assertEquals(setOf("minecraft"), noLoaderVer.getJSONObject("dependencies").keySet())
        // 名字留空时用实例名顶上
        assertEquals("inst", ModpackExport.buildIndex(ExportPlan(PackMeta("", instanceName = "inst"))).getString("name"))
    }

    // ------------------------------------------------------------ 压包 + 回读

    @Test
    fun writtenPackRoundTripsThroughModpackIndex() = run { root ->
        val bytes = seed(root)
        val knownSha1 = sha1(bytes.getValue("known"))
        val lookup = HashLookup { sha -> if (sha == knownSha1) versionJson("https://x/known.jar") else null }
        val meta = PackMeta("Round Trip", "1.2.3", "1.20.1", "fabric-loader", "0.16.0", instanceName = "inst")
        val dest = File(root, "out/inst.mrpack")
        val notes = ArrayList<Triple<String, Int, Int>>()
        val written = ModpackExport.export(root, meta, dest, lookup) { w, a, b -> notes.add(Triple(w, a, b)) }
        assertEquals(dest, written)
        assertTrue(dest.isFile)
        assertFalse("不该留 .tmp", File(root, "out/inst.mrpack.tmp").exists())
        assertEquals(Triple("导出完成", 1, 1), notes.last())

        // 自家的导入解析器要能原样读回
        val info = ModpackIndex.probe(dest)!!
        assertEquals(PackFormat.MRPACK, info.format)
        assertEquals("Round Trip", info.name)
        assertEquals("1.2.3", info.version)
        assertEquals("1.20.1", info.mcVersion)
        assertEquals("fabric-loader", info.loader)
        assertEquals("0.16.0", info.loaderVersion)
        assertEquals(listOf("mods/known.jar"), info.files.map { it.path })
        assertEquals(listOf("https://x/known.jar"), info.files.single().urls)
        assertEquals(knownSha1, info.files.single().sha1)

        ZipFile(dest).use { zf ->
            val names = zf.entries().asSequence().map { it.name }.toList()
            assertEquals(
                setOf(
                    ModpackIndex.MRPACK_INDEX,
                    "overrides/mods/local.jar",
                    "overrides/config/a.toml",
                    "overrides/config/sub/b.json",
                    "overrides/resourcepacks/pack.zip",
                    "overrides/datapacks/dp/pack.mcmeta",
                ),
                names.toSet(),
            )
            // 内容原样
            val local = zf.getInputStream(zf.getEntry("overrides/mods/local.jar")).use { it.readBytes() }
            assertTrue(local.contentEquals(bytes.getValue("unknown")))
            // 索引是合法 JSON 且不带 BOM
            val raw = zf.getInputStream(zf.getEntry(ModpackIndex.MRPACK_INDEX)).use { it.readBytes() }
            assertTrue(raw.isNotEmpty() && raw[0] == '{'.code.toByte())
            JSONObject(raw.decodeToString())
        }
        // overrides 解出来的相对路径也要跟装的那一边对得上
        val plan = com.pymcl.mobile.data.ModpackInstall.plan(info, ZipFile(dest).use { zf -> zf.entries().asSequence().map { it.name }.toList() })
        assertEquals(
            listOf("mods/local.jar", "config/a.toml", "config/sub/b.json", "resourcepacks/pack.zip", "datapacks/dp/pack.mcmeta"),
            plan.extracts.map { it.relPath },
        )
    }

    @Test
    fun writeFailureLeavesNoHalfPack() = run { root ->
        val ghost = File(root, "config/missing.toml")
        val plan = ExportPlan(PackMeta("p"), overrides = listOf("config/missing.toml" to ghost))
        val dest = File(root, "exports/p.mrpack")
        assertThrows(FileNotFoundException::class.java) { ModpackExport.write(plan, dest) }
        assertFalse(dest.exists())
        assertFalse(File(root, "exports/p.mrpack.tmp").exists())
    }

    @Test
    fun rewritingReplacesThePreviousPack() = run { root ->
        val dest = File(root, "p.mrpack")
        ModpackExport.write(ExportPlan(PackMeta("first")), dest)
        ModpackExport.write(ExportPlan(PackMeta("second")), dest)
        assertEquals("second", ModpackIndex.probe(dest)!!.name)
    }

    // ------------------------------------------------------------ 元数据

    @Test
    fun loaderVersionIsReadOutOfTheLibraries() {
        fun json(vararg libs: String) = JSONObject().put(
            "libraries",
            org.json.JSONArray().apply { libs.forEach { put(JSONObject().put("name", it)) } },
        )
        assertEquals("0.16.0", ModpackExport.loaderVersionOf(json("org.ow2.asm:asm:9.6", "net.fabricmc:fabric-loader:0.16.0")))
        assertEquals("0.26.3", ModpackExport.loaderVersionOf(json("org.quiltmc:quilt-loader:0.26.3")))
        assertEquals("21.1.65", ModpackExport.loaderVersionOf(json("net.neoforged:neoforge:21.1.65")))
        assertEquals("47.2.0", ModpackExport.loaderVersionOf(json("net.minecraftforge:forge:1.20.1-47.2.0:universal")))
        assertEquals("47.2.0", ModpackExport.loaderVersionOf(json("net.minecraftforge:fmlloader:1.20.1-47.2.0")))
        assertEquals("", ModpackExport.loaderVersionOf(json("com.mojang:brigadier:1.0.18")))
        assertEquals("", ModpackExport.loaderVersionOf(JSONObject()))
    }

    @Test
    fun loaderNamesMapToModrinthDependencyKeys() {
        assertEquals("fabric-loader", ModpackExport.modrinthLoaderKey("Fabric"))
        assertEquals("fabric-loader", ModpackExport.modrinthLoaderKey("fabric-loader"))
        assertEquals("quilt-loader", ModpackExport.modrinthLoaderKey("Quilt"))
        assertEquals("forge", ModpackExport.modrinthLoaderKey("Forge"))
        assertEquals("neoforge", ModpackExport.modrinthLoaderKey("NeoForge"))
        assertEquals("", ModpackExport.modrinthLoaderKey("OptiFine"))
        assertEquals("", ModpackExport.modrinthLoaderKey("原版"))
        assertEquals("", ModpackExport.modrinthLoaderKey(""))
    }

    @Test
    fun metaPrefersInstanceModpackSectionThenVersionJson() = run { root ->
        // 没有 modpack 段：从版本 json 推
        val vdir = File(root, "versions/fabric-1.20.1").apply { mkdirs() }
        val versionJson = JSONObject()
            .put("id", "fabric-1.20.1")
            .put("inheritsFrom", "1.20.1")
            .put("mainClass", "net.fabricmc.loader.impl.launch.knot.KnotClient")
            .put("libraries", org.json.JSONArray().put(JSONObject().put("name", "net.fabricmc:fabric-loader:0.16.0")))
        File(vdir, "fabric-1.20.1.json").writeText(versionJson.toString())
        val derived = ModpackExport.metaFor(root, "inst", "fabric-1.20.1", versionJson)
        assertEquals(PackMeta("inst", "1.0.0", "1.20.1", "fabric-loader", "0.16.0", instanceName = "inst"), derived)

        // 有 modpack 段（桌面装整合包时留下的）：以它为准
        Paths.writeJson(
            File(root, ".instance.json"),
            JSONObject().put("name", "inst").put(
                "modpack",
                JSONObject().put("name", "Cobblemon").put("version", "1.5.2").put("mc_version", "1.20.1")
                    .put("loader", "forge").put("loader_version", "47.2.0"),
            ),
        )
        val fromMeta = ModpackExport.metaFor(root, "inst", "fabric-1.20.1", versionJson)
        assertEquals(PackMeta("Cobblemon", "1.5.2", "1.20.1", "forge", "47.2.0", instanceName = "inst"), fromMeta)

        // 没选版本、也没有 modpack 段：只剩实例名与默认版本号
        File(root, ".instance.json").delete()
        assertEquals(PackMeta("inst", instanceName = "inst"), ModpackExport.metaFor(root, "inst", "", null))
    }

    @Test
    fun hashLookupUrlsPreferTheMirror() {
        val urls = ModpackExport.hashUrls("abc")
        assertEquals(2, urls.size)
        assertTrue(urls[0].startsWith(Paths.MCIM))
        assertTrue(urls[0].endsWith("/modrinth/v2/version_file/abc"))
        assertEquals("https://api.modrinth.com/v2/version_file/abc", urls[1])
    }
}
