package com.pymcl.mobile

import com.pymcl.mobile.data.FileKind
import com.pymcl.mobile.data.FileKinds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 认类型的单测。全程真的造 zip / PNG 文件再去认，不打桩——
 * java.util.zip 与 java.io 都是纯 JVM，脱离 Android 也跑得起来。
 */
class FileKindsTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun zip(name: String, vararg entries: Pair<String, String>): File {
        val f = tmp.newFile(name)
        ZipOutputStream(f.outputStream()).use { out ->
            entries.forEach { (path, body) ->
                out.putNextEntry(ZipEntry(path))
                out.write(body.toByteArray())
                out.closeEntry()
            }
        }
        return f
    }

    private fun png(name: String, w: Int, h: Int): File {
        val f = tmp.newFile(name)
        val head = ByteArray(24)
        byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A).copyInto(head)
        "IHDR".toByteArray(Charsets.US_ASCII).copyInto(head, 12)
        fun be(v: Int, at: Int) {
            head[at] = (v ushr 24).toByte(); head[at + 1] = (v ushr 16).toByte()
            head[at + 2] = (v ushr 8).toByte(); head[at + 3] = v.toByte()
        }
        be(w, 16); be(h, 20)
        f.writeBytes(head)
        return f
    }

    private val mrpack = """{"formatVersion":1,"name":"Demo","versionId":"1.0",
        "dependencies":{"minecraft":"1.20.1","fabric-loader":"0.15.7"},"files":[]}"""

    // ---------- 边界 1：改过名的 ----------

    @Test
    fun renamedMrpackIsStillRecognised() {
        // 后缀换成 .bin，按内容照样认得出来
        val f = zip("pack.bin", "modrinth.index.json" to mrpack)
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.MODPACK), g.kinds)
        assertTrue(g.sure)
        assertTrue(g.detail, g.detail.contains("1.20.1"))
    }

    @Test
    fun renamedResourcePackIsStillRecognised() {
        val f = zip("looks-like-anything.dat", "pack.mcmeta" to "{}", "assets/minecraft/x.png" to "x")
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.RESOURCEPACK), g.kinds)
        assertTrue(g.sure)
    }

    // ---------- 边界 2：嵌套目录 ----------

    @Test
    fun nestedMarkerStillCounts() {
        val f = zip("nested.zip", "MyPack/modrinth.index.json" to mrpack)
        assertEquals(listOf(FileKind.MODPACK), FileKinds.identify(f).kinds)
    }

    @Test
    fun markerBuriedTooDeepDoesNotCount() {
        // 资源包的 assets/minecraft/… 底下也可能躺着同名文件，
        // 按「任意深度」判会把一堆包认错。
        val deep = listOf("a/b/c/d/level.dat", "a/b/c/d/pack.mcmeta")
        assertFalse(FileKinds.hasEntry(deep, "level.dat"))
        assertFalse(FileKinds.hasEntry(deep, "pack.mcmeta"))
        assertTrue(FileKinds.hasEntry(listOf("one/level.dat"), "level.dat"))
    }

    // ---------- 边界 3：空 zip ----------

    @Test
    fun emptyZipIsUnknownNotCrash() {
        val f = zip("empty.zip")
        val g = FileKinds.identify(f)
        assertTrue(g.kinds.isEmpty())
        assertFalse(g.sure)
        assertTrue(g.detail.isNotBlank())
    }

    // ---------- 边界 4：损坏 zip ----------

    @Test
    fun corruptZipIsReportedNotThrown() {
        val f = tmp.newFile("broken.zip")
        f.writeBytes(ByteArray(512) { (it % 251).toByte() })
        val g = FileKinds.identify(f)
        assertTrue(g.kinds.isEmpty())
        assertEquals("打不开，也认不出是什么", g.detail)
        assertNull(FileKinds.entryNames(f))
    }

    @Test
    fun truncatedPngDoesNotThrow() {
        val f = tmp.newFile("half.png")
        f.writeBytes(byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47))
        assertNull(FileKinds.pngSize(f))
        // 读不出尺寸就当普通图片，不崩
        assertEquals(listOf(FileKind.WALLPAPER), FileKinds.identify(f).kinds)
    }

    @Test
    fun missingPathIsReported() {
        val g = FileKinds.identify(File(tmp.root, "nope.zip"))
        assertTrue(g.kinds.isEmpty())
        assertEquals("这个路径不存在", g.detail)
    }

    // ---------- 边界 5：同时像两样 ----------

    @Test
    fun skinSizedPngIsBothSkinAndWallpaper() {
        for ((w, h) in listOf(64 to 64, 64 to 32)) {
            val g = FileKinds.identify(png("skin-${w}x$h.png", w, h))
            assertEquals("${w}x$h", listOf(FileKind.SKIN, FileKind.WALLPAPER), g.kinds)
            assertFalse("两种都像就不能直接照办", g.sure)
        }
    }

    @Test
    fun ordinaryPngIsJustWallpaper() {
        val g = FileKinds.identify(png("photo.png", 1920, 1080))
        assertEquals(listOf(FileKind.WALLPAPER), g.kinds)
        assertTrue(g.sure)
    }

    @Test
    fun packWithBothAssetsAndDataOffersTwoChoices() {
        val f = zip("ambiguous.zip", "pack.mcmeta" to "{}", "assets/x" to "1", "data/y" to "2")
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.RESOURCEPACK, FileKind.DATAPACK), g.kinds)
        assertFalse(g.sure)
    }

    // ---------- 其余类型 ----------

    @Test
    fun worldBeatsEverythingElse() {
        val f = zip("save.zip", "level.dat" to "x", "datapacks/p/pack.mcmeta" to "{}")
        assertEquals(listOf(FileKind.WORLD), FileKinds.identify(f).kinds)
    }

    @Test
    fun shaderpackDetectedByShadersDir() {
        val f = zip("shader.zip", "shaders/final.fsh" to "void main(){}")
        assertEquals(listOf(FileKind.SHADERPACK), FileKinds.identify(f).kinds)
    }

    @Test
    fun fabricModIsAMod() {
        val f = zip("cool.jar", "fabric.mod.json" to """{"id":"cool"}""")
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.MOD), g.kinds)
        assertTrue(g.sure)
    }

    @Test
    fun loaderInstallerIsNotAMod() {
        // 丢进 mods 只会启动失败，得单独挑出来
        val f = zip("forge-installer.jar", "install_profile.json" to "{}")
        val g = FileKinds.identify(f)
        assertTrue(g.kinds.isEmpty())
        assertTrue(g.detail, g.detail.contains("加载器安装器"))
    }

    @Test
    fun jarWithoutDescriptorIsStillOfferedAsMod() {
        val f = zip("mystery.jar", "org/example/Main.class" to "x")
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.MOD), g.kinds)
        assertFalse("没有描述文件就不能拍胸脯", g.sure)
    }

    @Test
    fun videoIsWallpaper() {
        val f = tmp.newFile("clip.mp4")
        f.writeBytes(ByteArray(8))
        val g = FileKinds.identify(f)
        assertEquals(listOf(FileKind.WALLPAPER), g.kinds)
        assertTrue(g.sure)
    }

    @Test
    fun directoryIsWalkedLikeAnArchive() {
        val dir = tmp.newFolder("unpacked")
        File(dir, "shaders").mkdirs()
        File(dir, "shaders/final.fsh").writeText("x")
        val names = FileKinds.entryNames(dir)
        assertNotNull(names)
        assertTrue(FileKinds.hasDir(names!!, "shaders"))
        assertEquals(listOf(FileKind.SHADERPACK), FileKinds.identify(dir).kinds)
    }
}
