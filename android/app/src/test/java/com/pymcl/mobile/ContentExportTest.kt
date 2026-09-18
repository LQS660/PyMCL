package com.pymcl.mobile

import com.pymcl.mobile.data.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipInputStream
import org.junit.Assert.*
import org.junit.Test

class ContentExportTest {
    private fun run(block: (File) -> Unit) {
        val root = Files.createTempDirectory("content-export-").toFile()
        try { block(root) } finally { root.deleteRecursively() }
    }
    @Test fun fileKindsPreserveBytesAndNames() = run { root ->
        for (spec in listOf(CatalogKinds.MOD, CatalogKinds.RESOURCEPACK, CatalogKinds.DATAPACK, CatalogKinds.SHADERPACK)) {
            val name = "sample.${spec.extensions.first()}"
            val dir = spec.dirIn(root, "").apply { mkdirs() }
            File(dir, name).writeBytes(byteArrayOf(0, 1, 2, -1))
            val output = ByteArrayOutputStream()
            ContentExport.write(root, "", spec, name, output)
            assertArrayEquals(byteArrayOf(0, 1, 2, -1), output.toByteArray())
            assertEquals(name, ContentExport.filename(name, spec))
        }
    }
    @Test fun worldZipIncludesRootAndEmptyDirectories() = run { root ->
        val world = File(CatalogKinds.WORLD.dirIn(root, ""), "My World").apply { mkdirs() }
        File(world, "empty").mkdir()
        File(world, "level.dat").writeText("level")
        val output = ByteArrayOutputStream()
        ContentExport.write(root, "", CatalogKinds.WORLD, world.name, output)
        val entries = mutableMapOf<String, String>()
        ZipInputStream(output.toByteArray().inputStream()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes().toString(Charsets.UTF_8)
            }
        }
        assertTrue(entries.containsKey("My World/"))
        assertTrue(entries.containsKey("My World/empty/"))
        assertEquals("level", entries["My World/level.dat"])
    }
    @Test fun rejectsTraversalMissingFilesAndModpack() = run { root ->
        for (name in listOf("../outside.jar", "..\\outside.jar", "missing.jar")) {
            assertThrows(Exception::class.java) {
                ContentExport.write(root, "", CatalogKinds.MOD, name, ByteArrayOutputStream())
            }
        }
        assertThrows(IllegalArgumentException::class.java) {
            ContentExport.write(root, "", CatalogKinds.MODPACK, "pack.zip", ByteArrayOutputStream())
        }
    }
    @Test fun batchPacksEveryPickedFileIntoOneZip() = run { root ->
        val dir = CatalogKinds.MOD.dirIn(root, "").apply { mkdirs() }
        File(dir, "a.jar").writeText("alpha")
        File(dir, "b.jar").writeText("beta")
        val output = ByteArrayOutputStream()
        val result = ContentExport.writeMany(root, "", CatalogKinds.MOD, listOf("a.jar", "b.jar"), output)
        assertEquals(listOf("a.jar", "b.jar"), result.exported)
        assertTrue(result.failed.isEmpty())
        assertEquals(mapOf("a.jar" to "alpha", "b.jar" to "beta"), unzip(output))
    }
    @Test fun batchNestsDirectoryKindsUnderTheirOwnName() = run { root ->
        val world = File(CatalogKinds.WORLD.dirIn(root, ""), "My World").apply { mkdirs() }
        File(world, "level.dat").writeText("level")
        val output = ByteArrayOutputStream()
        val result = ContentExport.writeMany(root, "", CatalogKinds.WORLD, listOf("My World"), output)
        assertEquals(listOf("My World"), result.exported)
        val entries = unzip(output)
        assertTrue(entries.containsKey("My World/"))
        assertEquals("level", entries["My World/level.dat"])
    }
    @Test fun batchSkipsBadNamesAndStillShipsTheRest() = run { root ->
        val dir = CatalogKinds.MOD.dirIn(root, "").apply { mkdirs() }
        File(dir, "good.jar").writeText("ok")
        val output = ByteArrayOutputStream()
        val result = ContentExport.writeMany(
            root, "", CatalogKinds.MOD, listOf("missing.jar", "good.jar", "../outside.jar"), output)
        assertEquals(listOf("good.jar"), result.exported)
        assertEquals(listOf("missing.jar", "../outside.jar"), result.failed.map { it.name })
        assertTrue(result.failed.all { it.reason.isNotBlank() })
        assertEquals(setOf("good.jar"), unzip(output).keys)
    }
    @Test fun batchRefusesModpacksAndSuggestsABundleName() = run { _ ->
        assertEquals("pymcl-mods-3.zip", ContentExport.bundleName(CatalogKinds.MOD, 3))
        assertEquals("pymcl-saves-1.zip", ContentExport.bundleName(CatalogKinds.WORLD, 1))
        assertThrows(IllegalArgumentException::class.java) {
            ContentExport.writeMany(File("."), "", CatalogKinds.MODPACK, listOf("pack.zip"), ByteArrayOutputStream())
        }
    }
    private fun unzip(output: ByteArrayOutputStream): Map<String, String> {
        val entries = mutableMapOf<String, String>()
        ZipInputStream(output.toByteArray().inputStream()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes().toString(Charsets.UTF_8)
            }
        }
        return entries
    }
    @Test fun destinationFailurePropagatesWithoutChangingSource() = run { root ->
        val source = File(CatalogKinds.MOD.dirIn(root, "").apply { mkdirs() }, "keep.jar")
        source.writeText("original")
        val output = object : java.io.OutputStream() {
            override fun write(value: Int) { throw java.io.IOException("full") }
        }
        assertThrows(java.io.IOException::class.java) {
            ContentExport.write(root, "", CatalogKinds.MOD, source.name, output)
        }
        assertEquals("original", source.readText())
    }
}
